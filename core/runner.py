"""
smkrun core runner module
=========================
Subprocess spawning and execution logic with TCSH environment and
script override patching.
"""

import os
import sys
import re
import time
import json
import tempfile
import subprocess
from typing import Dict, List, Optional, Any

from .state import STATE, STATE_LOCK, broadcast_log

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from smkrun import SHELL

SMKPLOT_ENGINE_SCRIPT = os.path.join(BASE_DIR, "core", "smkplot_web_engine.py")

def _get_smkplot_python_bin() -> str:
    """Find python interpreter in adjacent smkplot/.venv, or raise an explicit error."""
    parent_dir = os.path.dirname(BASE_DIR)
    checked_paths = []
    for name in ("smkplot", "SMKPLOT"):
        cand_venv = os.path.join(parent_dir, name, ".venv", "bin", "python")
        checked_paths.append(cand_venv)
        if os.path.isfile(cand_venv) and os.access(cand_venv, os.X_OK):
            return cand_venv
    raise FileNotFoundError(
        "SMKPLOT Python environment not found.\n"
        f"Checked paths:\n  " + "\n  ".join(checked_paths) + "\n"
        "Ensure smkplot is installed side-by-side with smkrun and its .venv is set up."
    )

def call_smkplot_web_engine(args: List[str]) -> Dict[str, Any]:
    """Execute headless smkplot web engine using the verified smkplot virtualenv."""
    if not os.path.isfile(SMKPLOT_ENGINE_SCRIPT):
        raise FileNotFoundError(f"SMKPLOT engine script not found: {SMKPLOT_ENGINE_SCRIPT}")

    py_bin = _get_smkplot_python_bin()
    cmd = [py_bin, SMKPLOT_ENGINE_SCRIPT] + args
    print(f"INFO [SMKPLOT-WEB] Invoking: {' '.join(cmd[:7])}...", flush=True)
    try:
        t0 = time.time()
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        dur = time.time() - t0
        print(f"DEBUG [SMKPLOT-WEB] Command finished in {dur:.2f}s (exit {res.returncode})", flush=True)
        if res.stderr:
            print(f"DEBUG [SMKPLOT-WEB] stderr output:\n{res.stderr.strip()}", flush=True)

        if res.returncode != 0:
            print(f"ERROR [SMKPLOT-WEB] Engine returned exit code {res.returncode}", flush=True)
            return {"error": res.stderr.strip() or f"smkplot engine failed (exit {res.returncode})"}

        raw_out = res.stdout.strip()
        # Robustly locate JSON boundary in case upstream tools printed to stdout
        start_idx = raw_out.find("{")
        end_idx = raw_out.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = raw_out[start_idx:end_idx + 1]
            out_obj = json.loads(json_str)
            if isinstance(out_obj, dict):
                out_obj["engine_stderr"] = res.stderr.strip() if res.stderr else ""
            return out_obj
        
        print(f"ERROR [SMKPLOT-WEB] No valid JSON block found in output:\n{raw_out}", flush=True)
        return {"error": f"Failed to parse engine output: {raw_out[:300]}", "engine_stderr": res.stderr.strip() if res.stderr else ""}
    except Exception as e:
        print(f"ERROR [SMKPLOT-WEB] Exception during execution: {str(e)}", flush=True)
        return {"error": str(e)}

def launch_smkplot_app(path: str, env_context: Dict[str, str] = None) -> Dict[str, Any]:
    """Launch the full SMKPLOT visualization tool identically to smkrun._plot_emissions."""
    parent_dir = os.path.dirname(BASE_DIR)
    smkplot_dir = os.path.join(parent_dir, "smkplot")
    if not os.path.exists(smkplot_dir):
        smkplot_dir = os.path.join(parent_dir, "SMKPLOT")
    smkplot_exe = os.path.join(smkplot_dir, "smkplot.py")

    if not os.path.exists(smkplot_exe):
        msg = (
            "SMKPLOT visualization tool not found.\n\n"
            f"SMKRUN Location detected:\n{BASE_DIR}\n\n"
            f"Expected SMKPLOT location:\n{smkplot_exe}\n\n"
            "Relative to your current installation, you should install the SMKPLOT package here:\n"
            f"  {parent_dir}/smkplot/\n\n"
            "This ensures the 'utils' folder contains both 'smkrun' and 'smkplot' side-by-side."
        )
        return {"error": msg}

    if not os.access(smkplot_exe, os.X_OK):
        return {"error": f"SMKPLOT launcher is not executable: {smkplot_exe}"}

    ext = os.path.splitext(path)[1].lower()

    if ext not in (".ncf", ".nc"):
        cmd = [smkplot_exe, "--filepath", path, "--zoom-to-data"]
    else:
        cmd = [smkplot_exe, "--filepath", path]

    if ext not in (".ncf", ".nc") and env_context:
        griddesc = env_context.get("GRIDDESC", "")
        gridname = env_context.get("REGION_IOAPI_GRIDNAME", "")
        if griddesc:
            cmd += ["--griddesc", griddesc]
        if gridname:
            cmd += ["--gridname", gridname]

    try:
        # Run detached identical to smkrun.py
        subprocess.Popen(cmd)
        return {"status": "ok", "message": f"Launched SMKPLOT for {os.path.basename(path)}"}
    except Exception as e:
        return {"error": f"Failed to launch smkplot:\n{str(e)}"}

def run_script_worker(script_path: str, overrides: Dict[str, str], script_override_content: Optional[str] = None):
    """Worker function executed in background thread to run script and stream logs."""
    with STATE_LOCK:
        STATE.is_running = True
        STATE.exit_code = None
        STATE.log_history.clear()
        script_dir = os.path.dirname(script_path)
    
    env = os.environ.copy()
    for v, val in overrides.items():
        env[v] = val

    run_file = script_path
    is_temp = False

    if overrides or script_override_content:
        try:
            fd, tmp_script = tempfile.mkstemp(suffix=".csh", prefix="smkrun_override_", dir=script_dir)
        except (PermissionError, OSError):
            fd, tmp_script = tempfile.mkstemp(suffix=".csh", prefix="smkrun_override_")
        is_temp = True
        
        if script_override_content:
            lines = script_override_content.splitlines(True)
        else:
            with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            
        p_env = re.compile(r"^(\s*setenv\s+)([A-Za-z0-9_]+)(\s+.*)$")
        p_set = re.compile(r"^(\s*set\s+)([A-Za-z0-9_]+)(\s*=.*)$")
        p_src = re.compile(r"^\s*source\s+(.+?)$")
        
        # Find the last source statement related to directory_definitions or initial setup
        inject_idx = 0
        if lines and lines[0].startswith("#!"):
            inject_idx = 1
        for idx, line in enumerate(lines):
            stripped = line.split("#")[0].strip()
            if p_src.match(stripped):
                inject_idx = idx + 1
        
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            # Write lines up to injection point
            for i in range(inject_idx):
                f.write(lines[i])
            
            f.write("\n# ── SMKRUN WEB OVERRIDES ─────────────────────────\n")
            for v, val in overrides.items():
                f.write(f"setenv {v} \"{val}\"\n")
            f.write("# ────────────────────────────────────────────────\n\n")
            
            overridden_keys = set(overrides.keys())
            for line in lines[inject_idx:]:
                m_env = p_env.match(line)
                m_set = p_set.match(line)
                if (m_env and m_env.group(2) in overridden_keys) or (m_set and m_set.group(2) in overridden_keys):
                    f.write(f"# smkrun override: {line}")
                else:
                    f.write(line)
        run_file = tmp_script
        os.chmod(tmp_script, 0o755)

    cmd = [SHELL, run_file]
    broadcast_log(f"── Starting Execution: {os.path.basename(script_path)} ──\n")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=script_dir if script_dir else None,
            universal_newlines=True,
            bufsize=1,
            preexec_fn=os.setsid
        )
        with STATE_LOCK:
            STATE.proc = proc
            
        for line in proc.stdout:
            broadcast_log(line)
        proc.wait()
        rc = proc.returncode
        broadcast_log(f"\n── Process exited with return code {rc} ──\n")
        with STATE_LOCK:
            STATE.exit_code = rc
    except Exception as exc:
        broadcast_log(f"\n[smkrun error] {exc}\n")
        with STATE_LOCK:
            STATE.exit_code = -1
    finally:
        with STATE_LOCK:
            STATE.is_running = False
            STATE.proc = None
        if is_temp and os.path.exists(run_file):
            try:
                os.remove(run_file)
            except Exception:
                pass
