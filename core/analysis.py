"""
smkrun core analysis module
===========================
Diagnostics, log analysis, file discovery (outputs and inputs),
and environment variable documentation parser for SMKRUN.
"""

import os
import sys
import re
from typing import Dict, List, Optional, Tuple, Any

# smkrun root directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from smkrun import SMKContext

def smart_isfile(path: str) -> Optional[str]:
    """Check if path exists, or if it exists with common SMOKE extensions or .gz."""
    if os.path.isfile(path): return os.path.abspath(path)
    for ext in [".ncf", ".rpt", ".txt", ".nc", ".csv"]:
        p = path + ext
        if os.path.isfile(p): return os.path.abspath(p)
        if os.path.isfile(p + ".gz"): return os.path.abspath(p + ".gz")
    if os.path.isfile(path + ".gz"): return os.path.abspath(path + ".gz")
    return None

def identify_program_from_log_header(log_path: str, default_prog: str = None) -> str:
    """Read initial lines of a log file to identify which SMOKE program generated it."""
    if not log_path or not os.path.isfile(log_path):
        return default_prog if default_prog else SMKContext.sanitize_tool_name(os.path.basename(log_path))
    try:
        if os.path.getsize(log_path) > 15 * 1024 * 1024:
            return default_prog if default_prog else SMKContext.sanitize_tool_name(os.path.basename(log_path))
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for _ in range(150):
                line = f.readline()
                if not line: break
                m = re.search(r"Program\s+([A-Z0-9_]+)[,\s]+Version", line, re.IGNORECASE)
                if m:
                    prog = m.group(1).upper()
                    if prog in SMKContext.TOOLS: return prog
                    if len(prog) >= 5: return prog
    except (OSError, UnicodeDecodeError):
        pass
    return default_prog if default_prog else SMKContext.sanitize_tool_name(os.path.basename(log_path))

def extract_paths_from_log(text: str, base_dir: str, mode: str = "output") -> List[Tuple[str, str]]:
    """Unified log parser for discovering files in SMOKE/IOAPI logs."""
    found = []
    lines = [l.strip() for l in text.splitlines()]
    current_prog = "General"
    
    p_prog = re.compile(r"Program ([A-Z0-9_]+), Version", re.IGNORECASE)
    p_val_for = re.compile(r"Value for (\S+):\s+'(.+?)'", re.IGNORECASE)
    p_file_name = re.compile(r"File name\s+\"(.+?)\"", re.IGNORECASE)
    
    for i, line in enumerate(lines):
        low = line.lower()
        m_prog = p_prog.search(line)
        if m_prog:
            current_prog = m_prog.group(1).upper()
        
        m_log = re.search(r"([a-zA-Z0-9_\-\./\\]+\.log)", line, re.IGNORECASE)
        if m_log:
            log_p = m_log.group(1).strip("'\"")
            target = log_p if os.path.isabs(log_p) else os.path.normpath(os.path.join(base_dir, log_p))
            found_p = smart_isfile(target)
            if found_p:
                prog_name = identify_program_from_log_header(found_p)
                found.append((found_p, prog_name))
                if any(x in low for x in ["checking", "processing", "processing log"]):
                    current_prog = prog_name

        is_input_trigger = any(x in low for x in ["opened for input", "opened as old", "old:read-only", "input file", "successful open for inventory"])
        is_output_trigger = any(x in low for x in ["opened for output", "opened as unknown", "opened as new", "opened for write"])
        
        if mode == "input" and is_output_trigger: continue
        if mode == "output" and is_input_trigger: continue
        
        if is_input_trigger or is_output_trigger:
            path_found = False
            m_same = re.search(r"(?:file|path|log|inventory)\s*[:=]?\s*\"?((?:/|[.]{1,2}/)[A-Za-z0-9_\-\./]+\.[A-Za-z0-9]+)\"?", line, re.IGNORECASE)
            if m_same:
                target = m_same.group(1)
                found_p = smart_isfile(target if os.path.isabs(target) else os.path.normpath(os.path.join(base_dir, target)))
                if found_p:
                    found.append((found_p, current_prog))
                    path_found = True
            
            if not path_found:
                for j in range(i + 1, min(i + 6, len(lines))):
                    candidate = lines[j].strip().strip("'\"")
                    if not candidate or any(x in candidate.lower() for x in ["returning", "value for", "program", "error"]): continue
                    if candidate.startswith("/") or (("/" in candidate or "." in candidate) and len(candidate) > 4):
                        target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                        found_p = smart_isfile(target)
                        if found_p:
                            found.append((found_p, current_prog))
                            break

        m_fn = p_file_name.search(line)
        if m_fn:
            context_hint = " ".join([l.lower() for l in lines[max(0, i-2):i]])
            is_input_context = any(x in context_hint for x in ["opened for input", "opened as old", "old:read-only"])
            if (mode == "input" and is_input_context) or (mode == "output" and not is_input_context):
                path = m_fn.group(1).strip()
                target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                found_p = smart_isfile(target)
                if found_p: found.append((found_p, current_prog))

        m_vf = p_val_for.search(line)
        if m_vf:
            vname = m_vf.group(1).upper()
            candidate = m_vf.group(2).strip()
            if "/" in candidate or "." in candidate:
                is_out_var = any(x in vname for x in SMKContext.OUTPUT_HINTS) or any(x in candidate.lower() for x in SMKContext.OUTPUT_PATH_HINTS)
                if (mode == "output" and is_out_var) or (mode == "input" and not is_out_var):
                    target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                    found_p = smart_isfile(target)
                    if found_p and not any(x in found_p.lower() for x in SMKContext.PATH_BLACKLIST):
                        found.append((found_p, current_prog))
    return found

def get_log_program_order(log_text: str) -> List[str]:
    seen, seen_set = [], set()
    for m in re.finditer(r"Program\s+([A-Z0-9_]+)[,\s]+Version", log_text, re.IGNORECASE):
        prog = m.group(1).upper()
        if prog not in seen_set:
            seen.append(prog)
            seen_set.add(prog)
    return seen

def scan_files_io(script_path: str, log_text: str) -> Dict[str, Any]:
    from collections import defaultdict, deque
    script_dir = os.path.dirname(script_path) if script_path else ""
    
    # Output Scanning
    out_grouped = defaultdict(set)
    log_queue = deque()
    if log_text:
        for path, prog in extract_paths_from_log(log_text, script_dir, mode="output"):
            if prog not in ("General", "Global/Env"):
                out_grouped["Global/Env"].discard(path)
                out_grouped["General"].discard(path)
            out_grouped[prog].add(path)
            if path.endswith(".log"):
                p_name = identify_program_from_log_header(path, default_prog=prog)
                log_queue.append((path, p_name))

    scanned_logs = set()
    max_scans = 300
    while log_queue and max_scans > 0:
        log_p, context_prog = log_queue.popleft()
        if log_p in scanned_logs: continue
        scanned_logs.add(log_p)
        if not os.path.isfile(log_p) or os.path.getsize(log_p) > 15 * 1024 * 1024:
            continue
        max_scans -= 1
        log_p = os.path.abspath(log_p)
        if context_prog in ("General", "Global/Env"):
            context_prog = SMKContext.sanitize_tool_name(os.path.basename(log_p))
        try:
            base = os.path.dirname(log_p)
            with open(log_p, "r", encoding="utf-8", errors="ignore") as fl:
                content = fl.read()
                for path, prog in extract_paths_from_log(content, base, mode="output"):
                    use_prog = prog if prog != "General" else context_prog
                    if use_prog not in ("General", "Global/Env"):
                        out_grouped["Global/Env"].discard(path)
                        out_grouped["General"].discard(path)
                    out_grouped[use_prog].add(path)
                    if path.endswith(".log"):
                        log_queue.append((path, use_prog))
        except (OSError, UnicodeDecodeError):
            pass

    # Input Scanning
    in_grouped = defaultdict(set)
    in_log_queue = deque()
    if log_text:
        for path, prog in extract_paths_from_log(log_text, script_dir, mode="input"):
            if path.endswith(".log"):
                in_log_queue.append((path, prog))
            else:
                in_grouped[prog].add(path)

    scanned_in_logs = set()
    max_in_scans = 300
    while in_log_queue and max_in_scans > 0:
        log_p, context_prog = in_log_queue.popleft()
        log_p = os.path.abspath(log_p)
        if log_p in scanned_in_logs: continue
        scanned_in_logs.add(log_p)
        if not os.path.isfile(log_p) or os.path.getsize(log_p) > 20 * 1024 * 1024:
            continue
        max_in_scans -= 1
        try:
            base = os.path.dirname(log_p)
            with open(log_p, "r", encoding="utf-8", errors="ignore") as fl:
                content = fl.read()
                for path, prog in extract_paths_from_log(content, base, mode="input"):
                    if path.endswith(".log"):
                        in_log_queue.append((path, prog))
                    else:
                        if prog not in ("General", "Global/Env"):
                            in_grouped["Global/Env"].discard(path)
                            in_grouped["General"].discard(path)
                        in_grouped[prog].add(path)
        except (OSError, UnicodeDecodeError):
            pass

    _tools = set(SMKContext.TOOLS) | {"Global/Env", "General"}
    consolidated_inputs = defaultdict(set)
    for _prog, _paths in in_grouped.items():
        _canonical = _prog if _prog in _tools else SMKContext.sanitize_tool_name(_prog)
        if _canonical not in _tools:
            _canonical = "General"
        consolidated_inputs[_canonical].update(_paths)

    exec_order = get_log_program_order(log_text)
    
    def format_grouped(grp: Dict[str, set], is_input: bool = False):
        res = []
        all_progs = set(grp.keys())
        first = ["Global/Env"] if "Global/Env" in all_progs else []
        last = [p for p in ["General", "LOGS"] if p in all_progs]
        middle = all_progs - set(first) - set(last)
        ordered = [p for p in exec_order if p in middle]
        unordered = sorted(p for p in middle if p not in exec_order)
        prog_seq = first + ordered + unordered + last
        
        for p in prog_seq:
            if is_input and p == "Utility/Log": continue
            fps = sorted(grp[p], key=lambda x: os.path.basename(x).lower())
            if not fps: continue
            file_items = []
            for fp in fps:
                bname = os.path.basename(fp).lower()
                ext = os.path.splitext(fp)[1].lower()
                is_log = ext == ".log"
                is_nc = ext in [".ncf", ".nc"]
                is_csv = ext == ".csv"
                is_rep = (not is_log) and (not is_nc) and (
                    ext == ".rpt" or 
                    (bname.startswith("rep_") and not bname.startswith("repconfig")) or 
                    ("/reports/" in fp.lower() and ext in [".txt", ".csv", ".rpt"] and not bname.startswith("repconfig"))
                )
                file_items.append({
                    "name": os.path.basename(fp),
                    "path": fp,
                    "is_netcdf": is_nc,
                    "is_report": is_rep,
                    "is_csv": is_csv,
                    "is_log": is_log,
                    "size": os.path.getsize(fp) if os.path.exists(fp) else 0
                })
            res.append({"program": p, "files": file_items})
        return res

    return {
        "outputs": format_grouped(out_grouped, is_input=False),
        "inputs": format_grouped(consolidated_inputs, is_input=True)
    }

def analyze_log_text(log_text: str, exit_code: Optional[int]) -> Dict[str, Any]:
    lines = log_text.splitlines()
    errors, warnings = [], []
    for i, line in enumerate(lines, 1):
        low = line.lower()
        ext_path = None
        if "error detected in logfile" in low and i < len(lines):
            next_line = lines[i].strip().strip("* ").strip()
            if os.path.exists(next_line) and os.path.isfile(next_line):
                ext_path = next_line
        elif "please review" in low and "report" in low:
            for j in range(i, min(i + 3, len(lines))):
                candidate = lines[j].strip().strip("* ").strip()
                if ("rep_logs" in candidate or "/reports/log_analyzer/" in candidate) and os.path.isfile(candidate):
                    ext_path = candidate
                    break
        
        if any(w in low for w in ["error", "abort", "fatal", "sigsegv"]) or ext_path:
            text = line.strip()
            if ext_path: text += f" -> {ext_path}"
            errors.append({"line": i, "text": text, "ext_path": ext_path})
        elif any(w in low for w in ["warning", "warn"]):
            warnings.append({"line": i, "text": line.strip()})

    completed = (exit_code == 0) if exit_code is not None else False
    smoke_progs = []
    seen = set()
    for l in lines:
        m = re.search(r"\b(smkinven|spcmat|temporal|laypoint|elevpoint|smkmerge|smkreport)\b", l, re.IGNORECASE)
        if m and m.group(0).lower() not in seen:
            seen.add(m.group(0).lower())
            smoke_progs.append(m.group(0))

    return {
        "total_lines": len(lines),
        "errors": errors,
        "warnings": warnings,
        "completed": completed,
        "smoke_programs": smoke_progs
    }

def load_env_docs() -> Dict[str, str]:
    import collections
    import yaml
    yaml_files = [
        os.path.join(BASE_DIR, "smoke_env_vars.yaml"),
        os.path.join(BASE_DIR, "emf_env_vars.yaml")
    ]
    raw_grouped = collections.defaultdict(lambda: collections.defaultdict(list))
    for yaml_path in yaml_files:
        if not os.path.exists(yaml_path): continue
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            if not data: continue
            for prog, vars_dict in data.items():
                if not vars_dict: continue
                for vname, vinfo in vars_dict.items():
                    vname_clean = vname.strip(" :.'\",").upper()
                    desc = vinfo.get("description", "").replace('\n', ' ')
                    default = str(vinfo.get("default", ""))
                    raw_grouped[vname_clean][(desc, default)].append(prog)
        except Exception:
            pass

    docs = {}
    for vname, groups in raw_grouped.items():
        sections = []
        for (desc, default), progs in sorted(groups.items(), key=lambda x: sorted(x[1])[0]):
            prog_list = ", ".join(sorted(progs))
            html = f"<b>{vname}</b> <i>({prog_list})</i>"
            if default and default not in ("None", "''"):
                html += f"<br><b>Default:</b> {default}"
            if desc:
                html += f"<br><br>{desc}"
            sections.append(html)
        docs[vname] = "<hr style='margin: 8px 0; border: 0; border-top: 1px solid var(--border);'>".join(sections)
    return docs
