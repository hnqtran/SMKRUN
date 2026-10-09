"""
smkrun core HTTP server and request router
==========================================
Serves templates, static CSS/JS assets, SSE execution stream,
and REST APIs for script management and smkplot NetCDF data extraction.
"""

import os
import sys
import re
import json
import queue
import urllib.parse
import threading
import http.server
import socketserver

from .state import STATE, STATE_LOCK
from .analysis import (
    scan_files_io,
    analyze_log_text,
    load_env_docs
)
from .runner import run_script_worker, launch_smkplot_app, call_smkplot_web_engine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from smkrun import (
    parse_script_vars,
    recursive_expand,
    is_functionally_empty,
    check_netcdf,
    get_nc_metadata
)

def _enrich_var_rows(rows, overrides, env):
    for r in rows:
        var = r.get("var")
        is_ovr = bool(overrides and var in overrides)
        r["is_override"] = is_ovr
        if is_ovr and "$" in r.get("expanded", ""):
            r["expanded"] = recursive_expand(r["expanded"], env or {})
            exp = r["expanded"]
            if exp and re.match(r"^(/|\.\.?/)", exp):
                if os.path.exists(exp):
                    r["status"] = "empty" if is_functionally_empty(exp) else "ok"
                else:
                    r["status"] = "missing"
    return rows

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

ENV_DOCS_CACHE = load_env_docs()

class SMKRunHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute noisy console HTTP access logs
        return

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, rel_path: str):
        full_path = os.path.normpath(os.path.join(STATIC_DIR, rel_path))
        if not full_path.startswith(STATIC_DIR) or not os.path.isfile(full_path):
            self.send_json({"error": "Static file not found"}, status=404)
            return

        content_type = "text/plain"
        if full_path.endswith(".css"): content_type = "text/css; charset=utf-8"
        elif full_path.endswith(".js"): content_type = "application/javascript; charset=utf-8"
        elif full_path.endswith(".png"): content_type = "image/png"
        elif full_path.endswith(".svg"): content_type = "image/svg+xml"

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def serve_index(self):
        index_path = os.path.join(TEMPLATES_DIR, "index.html")
        if not os.path.isfile(index_path):
            self.send_json({"error": "Template index.html not found"}, status=500)
            return
        with open(index_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self.serve_index()
            return

        # ── Static Asset Serving ──
        if path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            self.serve_static(rel_path)
            return

        # ── API: File & Directory Tree (1-level hierarchy) ──
        if path == "/api/scripts":
            exts = (".csh", ".tcsh")
            req_dir = qs.get("dir", [""])[0]
            root_dir = STATE.scripts_root if os.path.isdir(STATE.scripts_root) else os.getcwd()
            target_dir = os.path.abspath(req_dir) if req_dir and os.path.isdir(req_dir) else root_dir

            subdirs = []
            scripts = []
            try:
                entries = sorted(os.scandir(target_dir), key=lambda e: (not e.is_dir(), e.name.lower()))
                for entry in entries:
                    if entry.name.startswith(".") or entry.name == "__pycache__":
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=True):
                            subdirs.append({
                                "name": entry.name,
                                "path": entry.path,
                                "rel_path": os.path.relpath(entry.path, root_dir)
                            })
                        elif entry.is_file(follow_symlinks=True):
                            if entry.name.lower().endswith(exts):
                                scripts.append({
                                    "name": entry.name,
                                    "path": entry.path,
                                    "full_path": entry.path,
                                    "rel_path": os.path.relpath(entry.path, root_dir)
                                })
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError) as e:
                self.send_json({"error": str(e), "root": root_dir, "current": target_dir}, status=403)
                return

            self.send_json({
                "root": root_dir,
                "current": target_dir,
                "dirs": subdirs,
                "scripts": scripts
            })
            return

        # ── API: Change Scripts Root Directory ──
        if path == "/api/change_root":
            new_root = qs.get("dir", [""])[0]
            if os.path.isdir(new_root):
                with STATE_LOCK:
                    STATE.scripts_root = os.path.abspath(new_root)
                self.send_json({"status": "ok", "root": STATE.scripts_root})
            else:
                self.send_json({"error": f"Directory not found: {new_root}"}, status=400)
            return

        # ── API: Active Session State (Preserve state on refresh) ──
        if path == "/api/session/state":
            with STATE_LOCK:
                self.send_json({
                    "current_script": STATE.current_script,
                    "is_running": STATE.is_running,
                    "exit_code": STATE.exit_code,
                    "scripts_root": STATE.scripts_root,
                    "has_logs": len(STATE.log_history) > 0
                })
            return

        # ── API: Interactive Local Filesystem Browser ──
        if path == "/api/fs/ls":
            target_dir = qs.get("path", [""])[0]
            if not target_dir or not os.path.isdir(target_dir):
                target_dir = STATE.scripts_root if os.path.isdir(STATE.scripts_root) else os.getcwd()
            target_dir = os.path.abspath(target_dir)

            parent_dir = os.path.dirname(target_dir) if target_dir != "/" else None
            dirs, files = [], []

            try:
                entries = sorted(os.scandir(target_dir), key=lambda e: (not e.is_dir(), e.name.lower()))
                for entry in entries:
                    if entry.name.startswith("."): continue
                    try:
                        if entry.is_dir(follow_symlinks=True):
                            dirs.append({"name": entry.name, "path": entry.path})
                        elif entry.is_file(follow_symlinks=True):
                            ext = os.path.splitext(entry.name)[1].lower()
                            files.append({
                                "name": entry.name,
                                "path": entry.path,
                                "is_script": ext in [".csh", ".tcsh"],
                                "is_plottable": ext in [".ncf", ".nc", ".csv", ".rpt", ".txt"]
                            })
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError) as e:
                self.send_json({"error": str(e), "current": target_dir}, status=403)
                return

            self.send_json({
                "current": target_dir,
                "parent": parent_dir,
                "dirs": dirs,
                "files": files
            })
            return

        # ── API: Script Load ──
        if path == "/api/load_script":
            script_path = qs.get("path", [""])[0]
            if not os.path.isfile(script_path):
                self.send_json({"error": "File not found"}, status=404)
                return
            with STATE_LOCK:
                STATE.current_script = script_path
                STATE.overrides.clear()
                rows, env = parse_script_vars(script_path)
                STATE.var_rows = _enrich_var_rows(rows, STATE.overrides, env)
                STATE.env_context = env

            sz = os.path.getsize(script_path)
            with open(script_path, "r", encoding="utf-8", errors="ignore") as fh:
                src = fh.read(2 * 1024 * 1024)
            self.send_json({
                "script": os.path.basename(script_path),
                "full_path": script_path,
                "vars": rows,
                "source": src,
                "size_mb": sz / (1024 * 1024)
            })
            return

        # ── API: Log SSE Stream ──
        if path == "/api/logs/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q = queue.Queue()
            with STATE_LOCK:
                STATE.log_subscribers.append(q)
                backlog = "".join(STATE.log_history[-1000:])
                
            if backlog:
                msg = f"data: {json.dumps({'line': backlog, 'running': STATE.is_running, 'rc': STATE.exit_code})}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()

            try:
                while True:
                    try:
                        line = q.get(timeout=1.0)
                        msg = f"data: {json.dumps({'line': line, 'running': STATE.is_running, 'rc': STATE.exit_code})}\n\n"
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with STATE_LOCK:
                    if q in STATE.log_subscribers:
                        STATE.log_subscribers.remove(q)
            return

        # ── API: Chunked File Viewer ──
        if path == "/api/file/view":
            f_path = qs.get("path", [""])[0]
            offset = int(qs.get("offset", [0])[0])
            chunk_size = 2 * 1024 * 1024
            if not os.path.isfile(f_path):
                self.send_json({"error": "File not found"}, status=404)
                return
            tot = os.path.getsize(f_path)
            is_nc = check_netcdf(f_path)
            if is_nc:
                content = get_nc_metadata(f_path)
                self.send_json({
                    "file": os.path.basename(f_path),
                    "is_netcdf": True,
                    "content": content,
                    "total_size": tot,
                    "offset": 0
                })
                return
            with open(f_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(offset)
                chunk = f.read(chunk_size)
            self.send_json({
                "file": os.path.basename(f_path),
                "is_netcdf": False,
                "content": chunk,
                "total_size": tot,
                "offset": offset,
                "chunk_size": chunk_size
            })
            return

        # ── API: Interactive SMKPLOT Web Engine (Zero-X11) ──
        if path == "/api/smkplot/load":
            target_path = qs.get("path", [""])[0]
            if not target_path or not os.path.exists(target_path):
                self.send_json({"error": f"File not found: {target_path}"}, status=404)
                return
            res = call_smkplot_web_engine(["load", "--path", target_path])
            self.send_json(res)
            return

        if path == "/api/smkplot/slice":
            target_path = qs.get("path", [""])[0]
            pollutant = qs.get("pollutant", [""])[0]
            time_idx = qs.get("time", ["0"])[0]
            layer_idx = qs.get("layer", ["0"])[0]
            time_op = qs.get("time_op", ["select"])[0]
            layer_op = qs.get("layer_op", ["select"])[0]
            cmap = qs.get("cmap", ["turbo"])[0]
            pltyp = qs.get("pltyp", ["auto"])[0].lower()
            log_scale = qs.get("log_scale", ["false"])[0].lower() in ("true", "1", "yes")
            zoom_to_data = qs.get("zoom_to_data", ["false"])[0].lower() in ("true", "1", "yes")
            skip_overlays = qs.get("skip_overlays", ["false"])[0].lower() in ("true", "1", "yes")
            args = ["slice", "--path", target_path, "--pollutant", pollutant,
                    "--time", str(time_idx), "--layer", str(layer_idx),
                    "--time-op", time_op, "--layer-op", layer_op,
                    "--cmap", cmap, "--pltyp", pltyp]
            if log_scale:
                args.append("--log-scale")
            if zoom_to_data:
                args.append("--zoom-to-data")
            if skip_overlays:
                args.append("--skip-overlays")
            res = call_smkplot_web_engine(args)
            self.send_json(res)
            return

        if path == "/api/smkplot/profile":
            target_path = qs.get("path", [""])[0]
            pollutant = qs.get("pollutant", [""])[0]
            row = qs.get("row", ["1"])[0]
            col = qs.get("col", ["1"])[0]
            args = ["profile", "--path", target_path, "--pollutant", pollutant,
                    "--row", str(row), "--col", str(col)]
            res = call_smkplot_web_engine(args)
            self.send_json(res)
            return

        # ── API: Launch Desktop SMKPLOT (when X11 is available) ──
        if path == "/api/plot/launch":
            target_path = qs.get("path", [""])[0]
            if not target_path or not os.path.exists(target_path):
                self.send_json({"error": f"File not found: {target_path}"}, status=404)
                return
            with STATE_LOCK:
                env_context = STATE.env_context.copy() if STATE.env_context else {}
            res = launch_smkplot_app(target_path, env_context)
            if "error" in res:
                self.send_json(res, status=500)
            else:
                self.send_json(res)
            return

        # ── API: Input and Output File Discovery ──
        if path == "/api/files/io":
            with STATE_LOCK:
                cur_script = STATE.current_script
                log_txt = "".join(STATE.log_history)
            data = scan_files_io(cur_script, log_txt)
            self.send_json(data)
            return

        # ── API: Log Analysis & Diagnostics ──
        if path == "/api/log/analysis":
            with STATE_LOCK:
                log_txt = "".join(STATE.log_history)
                rc = STATE.exit_code
            data = analyze_log_text(log_txt, rc)
            self.send_json(data)
            return

        # ── API: Variable Documentation Tooltip ──
        if path == "/api/var/doc":
            var_name = qs.get("name", [""])[0].strip().upper()
            doc_html = ENV_DOCS_CACHE.get(var_name, "")
            self.send_json({"var": var_name, "doc": doc_html})
            return

        self.send_json({"error": "Endpoint not found"}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            req = json.loads(body)
        except Exception:
            req = {}

        # ── API: Set Overrides ──
        if path == "/api/override":
            var = req.get("var")
            val = req.get("val")
            with STATE_LOCK:
                if val is None or val == "":
                    STATE.overrides.pop(var, None)
                else:
                    STATE.overrides[var] = str(val)
                if STATE.current_script:
                    rows, env = parse_script_vars(STATE.current_script, STATE.overrides, STATE.script_override_content)
                    STATE.var_rows = _enrich_var_rows(rows, STATE.overrides, env)
                    STATE.env_context = env
            self.send_json({"status": "ok", "overrides": STATE.overrides, "vars": STATE.var_rows})
            return

        # ── API: In-Memory Script Patch ──
        if path == "/api/source/patch":
            content = req.get("content", "")
            with STATE_LOCK:
                STATE.script_override_content = content if content else None
                if STATE.current_script:
                    rows, env = parse_script_vars(STATE.current_script, STATE.overrides, STATE.script_override_content)
                    STATE.var_rows = _enrich_var_rows(rows, STATE.overrides, env)
                    STATE.env_context = env
            self.send_json({"status": "ok", "is_patched": STATE.script_override_content is not None, "vars": STATE.var_rows})
            return

        # ── API: Save Script Directly to File ──
        if path == "/api/source/save":
            content = req.get("content", "")
            with STATE_LOCK:
                target_file = STATE.current_script
            if not target_file or not os.path.isfile(target_file):
                self.send_json({"error": "No script file loaded to save"}, status=400)
                return
            try:
                bak_file = target_file + ".bak"
                with open(target_file, "r", encoding="utf-8", errors="ignore") as f_in:
                    orig_content = f_in.read()
                with open(bak_file, "w", encoding="utf-8") as f_bak:
                    f_bak.write(orig_content)
                with open(target_file, "w", encoding="utf-8") as f_out:
                    f_out.write(content)
                with STATE_LOCK:
                    STATE.script_override_content = None
                    rows, env = parse_script_vars(target_file, STATE.overrides)
                    STATE.var_rows = _enrich_var_rows(rows, STATE.overrides, env)
                    STATE.env_context = env
                self.send_json({"status": "ok", "message": f"Saved successfully. Backup written to {os.path.basename(bak_file)}", "vars": STATE.var_rows})
            except Exception as e:
                self.send_json({"error": f"Failed to save file: {str(e)}"}, status=500)
            return

        # ── API: Save Generic Text File (View/Edit) ──
        if path == "/api/file/save":
            file_path = req.get("path", "")
            content = req.get("content", "")
            if not file_path or not os.path.isfile(file_path):
                self.send_json({"error": "File does not exist"}, status=400)
                return
            if check_netcdf(file_path):
                self.send_json({"error": "Cannot edit binary NetCDF file directly"}, status=400)
                return
            try:
                bak_file = file_path + ".bak"
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f_in:
                    orig_content = f_in.read()
                with open(bak_file, "w", encoding="utf-8") as f_bak:
                    f_bak.write(orig_content)
                with open(file_path, "w", encoding="utf-8") as f_out:
                    f_out.write(content)
                self.send_json({"status": "ok", "message": f"Saved {os.path.basename(file_path)} (backup: {os.path.basename(bak_file)})"})
            except Exception as e:
                self.send_json({"error": f"Failed to save file: {str(e)}"}, status=500)
            return

        # ── API: Write Variable Overrides to Source Script File ──
        if path == "/api/vars/save_to_script":
            target_var = req.get("var")
            with STATE_LOCK:
                target_file = STATE.current_script
                overrides_to_write = dict(STATE.overrides)
            if not target_file or not os.path.isfile(target_file):
                self.send_json({"error": "No active script loaded to modify"}, status=400)
                return

            if target_var:
                if target_var in overrides_to_write:
                    overrides_to_write = {target_var: overrides_to_write[target_var]}
                else:
                    self.send_json({"error": f"Variable '{target_var}' is not currently overridden"}, status=400)
                    return
            elif not overrides_to_write:
                self.send_json({"error": "No variable overrides to write"}, status=400)
                return

            try:
                with open(target_file, "r", encoding="utf-8", errors="ignore") as f_in:
                    lines = f_in.readlines()

                bak_file = target_file + ".bak"
                with open(bak_file, "w", encoding="utf-8") as f_bak:
                    f_bak.writelines(lines)

                p_env = re.compile(r"^(\s*setenv\s+)([A-Za-z0-9_]+)(\s+|=)(.+?)$")
                p_set = re.compile(r"^(\s*set\s+)([A-Za-z0-9_]+)(\s*=\s*|\s+)(.+?)$")

                written_vars = set()
                new_lines = []

                for line in lines:
                    comment = ""
                    code_part = line
                    if "#" in line:
                        idx = line.find("#")
                        code_part = line[:idx]
                        comment = line[idx:]

                    m_env = p_env.match(code_part)
                    m_set = p_set.match(code_part)

                    if m_env and m_env.group(2) in overrides_to_write:
                        vname = m_env.group(2)
                        new_val = overrides_to_write[vname]
                        written_vars.add(vname)
                        prefix = m_env.group(1)
                        delim = m_env.group(3)
                        line_ending = "\n" if not comment else f" {comment.strip()}\n"
                        new_lines.append(f'{prefix}{vname}{delim}"{new_val}"{line_ending}')
                    elif m_set and m_set.group(2) in overrides_to_write:
                        vname = m_set.group(2)
                        new_val = overrides_to_write[vname]
                        written_vars.add(vname)
                        prefix = m_set.group(1)
                        delim = m_set.group(3)
                        line_ending = "\n" if not comment else f" {comment.strip()}\n"
                        new_lines.append(f'{prefix}{vname}{delim}"{new_val}"{line_ending}')
                    else:
                        new_lines.append(line)

                # For any variable not found inline in the script, append cleanly
                unfound = [k for k in overrides_to_write if k not in written_vars]
                if unfound:
                    new_lines.append("\n# Overrides added by SMKRUN Web Platform\n")
                    for k in unfound:
                        new_lines.append(f'setenv {k} "{overrides_to_write[k]}"\n')
                        written_vars.add(k)

                with open(target_file, "w", encoding="utf-8") as f_out:
                    f_out.writelines(new_lines)

                with STATE_LOCK:
                    for k in written_vars:
                        STATE.overrides.pop(k, None)
                    rows, env = parse_script_vars(target_file, STATE.overrides)
                    STATE.var_rows = _enrich_var_rows(rows, STATE.overrides, env)
                    STATE.env_context = env

                with open(target_file, "r", encoding="utf-8", errors="ignore") as f_read:
                    updated_source = f_read.read()

                self.send_json({
                    "status": "ok",
                    "message": f"Successfully updated {len(written_vars)} variable(s) in {os.path.basename(target_file)}. Backup written to {os.path.basename(bak_file)}",
                    "vars": STATE.var_rows,
                    "overrides": STATE.overrides,
                    "source": updated_source
                })
            except Exception as e:
                self.send_json({"error": f"Failed to update script: {str(e)}"}, status=500)
            return

        # ── API: Execute Runscript ──
        if path == "/api/run":
            with STATE_LOCK:
                if STATE.is_running:
                    self.send_json({"error": "Process already running"}, status=400)
                    return
                script = STATE.current_script
                if not script or not os.path.isfile(script):
                    self.send_json({"error": "No script loaded"}, status=400)
                    return
                overrides_copy = STATE.overrides.copy()
                override_content = STATE.script_override_content
            threading.Thread(target=run_script_worker, args=(script, overrides_copy, override_content), daemon=True).start()
            self.send_json({"status": "started", "script": os.path.basename(script)})
            return

        # ── API: Stop Execution ──
        if path == "/api/stop":
            import signal
            import time
            with STATE_LOCK:
                proc = STATE.proc
            if proc:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    time.sleep(0.5)
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except Exception:
                        pass
                except Exception:
                    pass
            self.send_json({"status": "stopped"})
            return

        self.send_json({"error": "Not found"}, status=404)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _watch_files_and_reload(server: ThreadedHTTPServer):
    """Monitor python files in smkrun and core/ for modifications and restart server in-place."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    watch_dirs = [base_dir, os.path.join(base_dir, "core")]

    def get_mtimes():
        mtimes = {}
        for d in watch_dirs:
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                if fname.endswith(".py"):
                    full_p = os.path.join(d, fname)
                    try:
                        mtimes[full_p] = os.stat(full_p).st_mtime
                    except OSError:
                        pass
        return mtimes

    init_mtimes = get_mtimes()

    while True:
        time.sleep(1.0)
        curr_mtimes = get_mtimes()
        changed = False
        for path, mt in curr_mtimes.items():
            if path in init_mtimes and mt > init_mtimes[path]:
                changed = True
                print(f"\n[AUTO-RELOAD] Detected modification in {os.path.basename(path)}. Reloading server...", flush=True)
                break
        if changed:
            try:
                server.server_close()
            except Exception:
                pass
            sys.stdout.flush()
            sys.stderr.flush()
            script_path = os.path.abspath(sys.argv[0])
            new_argv = [sys.executable, script_path] + sys.argv[1:]
            try:
                os.execv(sys.executable, new_argv)
            except Exception as ex:
                print(f"[AUTO-RELOAD] Failed to re-exec server: {ex}", flush=True)
