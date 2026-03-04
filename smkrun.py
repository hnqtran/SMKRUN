#!/proj/ie/proj/SMOKE/htran/Emission_Modeling_Platform/utils/smkrun/.venv/bin/python
"""
smkrun.py  [v1.0]   Interactive SMOKE Runscript Launcher GUI
=======================================================
Author : Huy Tran, UNC-IE  (2026-02) (Ported to PyQt5)

Features
--------
* Browse the 2022v2 emissions platform script tree
* Inspect every setenv/set variable in a script with live path-existence icons
* Override individual env-vars before launching (edit-in-place table)
* Execute the script via tcsh in a subprocess with real-time log streaming
* Auto-detect SMOKE output reports (.txt) and visualise them as bar/line charts
* Show a log analysis panel (warnings, errors, "Normal Completion" detection)
"""

import os
import re
import shlex
import subprocess
import threading
import queue
import time
import glob
import sys
import yaml
import tempfile
import signal
import argparse

# ── X11/SSH Forwarding Workarounds ─────────────
# Mute benign warnings about missing OpenGL FBConfigs and XDG runtime folders over SSH
os.environ["QT_XCB_GL_INTEGRATION"] = "none"
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = f"/tmp/runtime-{os.environ.get('USER', 'run')}"
os.makedirs(os.environ["XDG_RUNTIME_DIR"], exist_ok=True)

from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem, 
                                 QTabWidget, QLabel, QPushButton, QLineEdit, QComboBox, 
                                 QTextEdit, QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView,
                                 QFileDialog, QMessageBox, QAbstractItemView, QListWidget, 
                                 QListWidgetItem, QInputDialog, QDialog, QDialogButtonBox,
                                 QToolTip, QMenu, QStackedWidget, QPlainTextEdit)
    from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRect
    from PySide6.QtGui import QColor, QFont, QTextCursor, QTextCharFormat, QBrush, QTextBlockFormat, QCursor, QSyntaxHighlighter, QPainter, QPolygon
    QT_VERSION = 6
except ImportError:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem, 
                                 QTabWidget, QLabel, QPushButton, QLineEdit, QComboBox, 
                                 QTextEdit, QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView,
                                 QFileDialog, QMessageBox, QAbstractItemView, QListWidget, 
                                 QListWidgetItem, QInputDialog, QDialog, QDialogButtonBox,
                                 QToolTip, QMenu, QStackedWidget, QPlainTextEdit)
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal as Signal, QObject, QRect
    from PyQt5.QtGui import QColor, QFont, QTextCursor, QTextCharFormat, QBrush, QTextBlockFormat, QCursor, QSyntaxHighlighter, QPainter, QPolygon
    QT_VERSION = 5

# ── Constants ─────────────────────────────────────────────────────────────────
SCRIPTS_ROOT = (
    "/proj/ie/proj/SMOKE/htran/12LISTOS/2022he_cb6_22m/scripts"
)
DIR_DEFS_CANDIDATES = [
    "directory_definitions.csh",
    "directory_definitions_12US2.csh",
]
SHELL = "/bin/tcsh"
DEFAULT_SCRIPT_FILTER = "*.csh, *.tcsh"

PALETTE = {
    "bg":        "#1a1d2e",
    "panel":     "#242740",
    "accent":    "#5865f2",
    "accent2":   "#7289da",
    "success":   "#57f287",
    "warn":      "#fee75c",
    "error":     "#ed4245",
    "fg":        "#e0e3f0",
    "fg2":       "#9ba1bc",
    "border":    "#3a3f60",
    "entry_bg":  "#1e2235",
    "override":  "#2a3060",
}

# ── SMOKE Context & Metadata ──────────────────────────────────────────────────
class SMKContext:
    TOOLS = [
        "SMKINVEN", "SPCMAT", "TEMPORAL", "GRDMAT", "ELEPOINT", "LAYPOINT",
        "SMKMERGE", "SMKREPORT", "CNTLMAT", "NORMBEIS", "TMPBEIS", "SMK2EMF",
        "UAM2ROADS", "RAW2EA", "PRESMOK", "BELDTOT", "MOVESMRG", "MOVESPRB",
        "M3STAT", "M3XTRACT"
    ]
    
    # Variables that suggest a file is an INPUT (to be ignored in output scans)
    INPUT_BLACKLIST = [
        "INV", "XREF", "MAP", "PROF", "FAC", "SRG", "GEO", "MET",
        "CONFIG", "DESC", "INC", "GRIDDESC", "SRGDESC", "SRGPRO", "TPRO",
        "GPRO", "BCON", "ICON", "DATE", "DATES", "GRID", "SPC", "CASE", "REGION",
        "STDATE", "STTIME", "YEAR", "MONTH", "DAY", "INSTALL_DIR"
    ]
    
    # Variables that strongly suggest a file is an OUTPUT or LOG
    OUTPUT_HINTS = ["OUT", "REPOUT", "PLAY", "INLN", "LOG", "NCF", "PREMERGED", "MRG",
                    "AREA", "POINT", "MOBILE", "ASCIIDUMP", "REPINVEN", "REPORT"]

    # SMKINVEN primary output variable names that may contain INPUT_BLACKLIST substrings
    # (e.g. REPINVEN contains "INV") — these bypass the blacklist gate in _scan_outputs
    SMKINVEN_OUTPUT_VARS = {"AREA", "POINT", "MOBILE", "ASCIIDUMP", "REPINVEN"}
    
    # Variables that suggest a directory is an OUTPUT directory
    OUTPUT_DIR_HINTS = ["OUT", "REPOUT", "INTERMED", "PREMERGED", "LOGS", "OUTPUT", "IMD_ROOT", "OUT_ROOT"]
    
    # Paths to ignore during output scans (to filter out inputs and system files)
    PATH_BLACKLIST = [
        "/ge_dat/", "/input/", "/inventory/", "/srg/", "/crossref/",
        "/profiles/", "/bin/", "/ioapi/", "/etc/", "/subsys/", "/src/",
        "/.venv/", "/__pycache__/"
    ]

    # Known output directory path fragments — used to reject false-positive inputs in Step 0
    OUTPUT_PATH_HINTS = [
        "/intermed/", "/outputs/", "/reports/", "/logs/", "/premerged/", "/merge/"
    ]

    # Common parameters that contain "OUT" or "REP" but are not directories
    PARAM_BLACKLIST = [
        "OUTZONE", "REPORT_DEFAULTS", "YN", "OFFSET", "LENGTH", "UNITS", 
        "FORMAT", "VNAME", "BY_HOUR", "BY_DAY", "OUT_FORMAT", "OUTPUT_FORMAT",
        "REPCONFIG", "REPCATS", "REPORT_STAT", "SMK_SOURCE", "MRG_SOURCE",
        "RUN_PART", "USE_", "RUN_", "DO_", "_YN", "LABEL", "NAME", "EMF_LOGNAME",
        "EMF_LOGGERPYTHONDIR", "MRGDATE_FILES", "PYTHON", "PATH", "LD_LIBRARY_PATH",
        "EMF_CLIENT", "EMF_JOBNAME"
    ]
    
    # Static root containers that are NOT outputs themselves but contain outputs
    STATIC_ROOTS = [
        "PROJECT_ROOT", "INSTALL_DIR", "MET_ROOT", "INV_ROOT", "GE_ROOT", 
        "OUT_ROOT", "IMD_ROOT", "EMF_ROOT", "SMK_ROOT", "SCRIPTS", "BIN", "HOME",
        "DAT_ROOT", "DATA_ROOT", "DATA", "GE_DAT", "INV_DAT", "GE_DATA", "EMF_DATA", "SMK_DATA"
    ]

    # Variable name fragment → SMOKE program mapping (derived from smoke_env_vars.yaml).
    # Checked as substrings BEFORE the generic TOOLS loop in sanitize_tool_name.
    VAR_PREFIX_MAP = {
        # ── SMKINVEN ─────────────────────────────
        "ARINV":    "SMKINVEN",   # area raw inventory
        "PTINV":    "SMKINVEN",   # point raw inventory
        "MBINV":    "SMKINVEN",   # mobile raw inventory
        "MONINV":   "SMKINVEN",   # onroad monitor inventory
        "INVTABLE": "SMKINVEN",   # inventory species table
        "COSTCY":   "SMKINVEN",   # county/state/country codes
        "GEOCODE":  "SMKINVEN",   # expanded geographic code levels
        # ── GRDMAT ───────────────────────────────
        "GSREF":    "GRDMAT",     # speciation/gridding cross-reference
        "GSPRO":    "GRDMAT",     # speciation profile
        "AGREF":    "GRDMAT",     # area gridding surrogate cross-reference
        "MGREF":    "GRDMAT",     # mobile gridding surrogate cross-reference
        "PGREF":    "GRDMAT",     # point gridding surrogate cross-reference
        "AGSUP":    "GRDMAT",     # area gridding supplemental
        "MGSUP":    "GRDMAT",     # mobile gridding supplemental
        "SRGDESC":  "GRDMAT",     # surrogate description file
        "SRGPRO":   "GRDMAT",     # surrogate profile file
        "GRIDDESC": "GRDMAT",     # grid/projection description
        # ── TEMPORAL ─────────────────────────────
        "ATPRO":    "TEMPORAL",   # area temporal profiles
        "PTPRO":    "TEMPORAL",   # point temporal profiles
        "MTPRO":    "TEMPORAL",   # mobile temporal profiles
        "ATREF":    "TEMPORAL",   # area temporal cross-reference
        "PTREF":    "TEMPORAL",   # point temporal cross-reference
        "MTREF":    "TEMPORAL",   # mobile temporal cross-reference
        "HOLIDAYS": "TEMPORAL",   # holidays file
        # ── LAYPOINT ─────────────────────────────
        "MET_CRO":  "LAYPOINT",   # MCIP meteorology cross files
        "MET_DOT":  "LAYPOINT",   # MCIP meteorology dot file
        "METCRO":   "LAYPOINT",   # alternate naming convention
        "METDOT":   "LAYPOINT",   # alternate naming convention
        # ── CNTLMAT ──────────────────────────────
        "GCNTL":    "CNTLMAT",    # growth/control packet file
        "MOVES":    "MOVESMRG",   # movesmrg inputs
        "REP":      "SMKREPORT",  # smkreport inputs
        "REPORT":   "SMKREPORT",  # smkreport inputs
        "M3STAT":   "M3STAT",     # m3stat inputs
        "M3XTRACT": "M3XTRACT",   # m3xtract inputs
    }

    @staticmethod
    def sanitize_tool_name(name: str) -> str:
        name_upper = name.upper()
        # 1. Check explicit variable-fragment → tool mapping first
        for frag, tool in SMKContext.VAR_PREFIX_MAP.items():
            if frag in name_upper:
                return tool
        # 2. Fall back to generic SMOKE tool name substring scan
        for tool in SMKContext.TOOLS:
            if tool in name_upper:
                return tool
        return name.split('_')[0].upper() if '_' in name else name_upper

# ── Helpers ─────────────────────────────────────────────────

_VAR_PAT = re.compile(r"\$\{?([A-Za-z0-9_]+)\}?")

def parse_tcsh_all_env_vars(path: str, env_context: Dict[str, str] = None) -> Dict[str, str]:
    out: Dict[str, str] = env_context.copy() if env_context else {}
    if not os.path.exists(path): return out
    
    p_env = re.compile(r"^\s*setenv\s+([A-Za-z0-9_]+)(?:\s+|=)(.+?)$")
    p_set = re.compile(r"^\s*set\s+([A-Za-z0-9_]+)(?:\s*=\s*|\s+)(.+?)$")
    p_src = re.compile(r"^\s*source\s+(.+?)$")
    
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                line = raw.split("#")[0].strip()
                if not line: continue
                
                # Recursive source support
                m_src = p_src.match(line)
                if m_src:
                    src_p = m_src.group(1).strip().strip('"\'')
                    if "$" in src_p:
                        exp_src = recursive_expand(src_p, out)
                    else:
                        exp_src = src_p
                    
                    if not os.path.isabs(exp_src):
                        exp_src = os.path.normpath(os.path.join(os.path.dirname(path), exp_src))
                    
                    if os.path.exists(exp_src) and exp_src != path:
                        # Pass the current environment so nested variables resolve
                        out.update(parse_tcsh_all_env_vars(exp_src, out))
                    continue

                m = p_env.match(line) or p_set.match(line)
                if not m: continue
                var, val_part = m.group(1), m.group(2).strip().strip('"\'()')
                
                # Expand using current context
                out[var] = recursive_expand(val_part, out)
    except: pass
    return out

def recursive_expand(val: str, env: Dict[str, str], depth: int = 20) -> str:
    if not val or not isinstance(val, str) or "$" not in val: return val
    result = val
    for _ in range(depth):
        hits = _VAR_PAT.findall(result)
        if not hits: break
        orig = result
        for v in set(hits):
            if v in env and env[v] is not None:
                # Literal replacement for safety
                target_long = f"${{{v}}}"
                target_short = f"${v}"
                result = result.replace(target_long, env[v]).replace(target_short, env[v])
        if result == orig: break
    return result

def is_functionally_empty(path: str) -> bool:
    if not os.path.isfile(path): return False
    if os.path.getsize(path) == 0: return True
    try:
        data_lines = 0
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip() and not line.strip().startswith("#"):
                    data_lines += 1
                    if data_lines > 1: return False
        return True
    except Exception:
        return False

def find_dir_defs(script_path: str) -> Optional[str]:
    script_dir = os.path.dirname(os.path.abspath(script_path))
    src_pat = re.compile(r"^\s*source\s+(.+?)\s*$")
    try:
        with open(script_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = src_pat.match(line.split("#")[0].strip())
                if m:
                    p = m.group(1).strip()
                    if "directory_definitions" in p:
                        candidate = os.path.normpath(os.path.join(script_dir, p))
                        if os.path.exists(candidate): return candidate
    except Exception: pass
    for name in DIR_DEFS_CANDIDATES:
        for d in [script_dir, os.path.dirname(script_dir)]:
            c = os.path.join(d, name)
            if os.path.exists(c): return c
    return None

def check_netcdf(path):
    try:
        with open(path, "rb") as f:
            sig = f.read(4)
            return sig.startswith(b"CDF") or sig.startswith(b"\x89HDF")
    except: return False

def get_nc_metadata(path):
    try:
        import netCDF4
        ds = netCDF4.Dataset(path, 'r')
        lines = [f"File: {os.path.basename(path)}", f"Format: {ds.file_format}", ""]
        lines.append("--- Global Attributes ---")
        for attr in ds.ncattrs():
            lines.append(f"{attr}: {getattr(ds, attr)}")
        lines.append("\n--- Dimensions ---")
        for name, dim in ds.dimensions.items():
            lines.append(f"{name}: {len(dim)}")
        lines.append("\n--- Variables ---")
        for name, var in ds.variables.items():
            dims = ", ".join(var.dimensions)
            lines.append(f"{var.dtype} {name}({dims})")
            for attr in var.ncattrs():
                if attr not in ['_FillValue']:
                    lines.append(f"    {attr}: {getattr(var, attr)}")
        ds.close()
        return "\n".join(lines)
    except ImportError:
        try:
            import xarray as xr
            ds = xr.open_dataset(path)
            lines = [f"File: {os.path.basename(path)}", "[Metadata read via xarray fallback]", ""]
            lines.append("--- Global Attributes ---")
            for k, v in ds.attrs.items(): lines.append(f"{k}: {v}")
            lines.append("\n--- Dimensions ---")
            for k, v in ds.dims.items(): lines.append(f"{k}: {v}")
            lines.append("\n--- Variables ---")
            for k, var in ds.variables.items():
                lines.append(f"{var.dtype} {k}{var.dims}")
                for ak, av in var.attrs.items(): lines.append(f"    {ak}: {av}")
            ds.close()
            return "\n".join(lines)
        except ImportError:
            return f"[Binary NetCDF File]\n\nNote: 'netCDF4' or 'xarray' libraries not found.\nInstall via: pip install netCDF4 xarray"
        except Exception as e:
            return f"[Binary NetCDF File]\n\nError reading with xarray: {e}"
    except Exception as e:
        return f"[Binary NetCDF File]\n\nError reading with netCDF4: {e}"

def parse_script_vars(script_path: str, overrides: Dict[str, str] = None, raw_content: str = None) -> Tuple[List[Dict], Dict[str, str]]:
    dir_defs = find_dir_defs(script_path)
    env: Dict[str, str] = {}
    
    # 1. Base Environment from directory_definitions and sourced files
    if dir_defs:
        env.update(parse_tcsh_all_env_vars(dir_defs, env))

    rows: List[Dict] = []
    p_env = re.compile(r"^\s*setenv\s+([A-Za-z0-9_]+)(?:\s+|=)(.+?)\s*$")
    p_set = re.compile(r"^\s*set\s+([A-Za-z0-9_]+)(?:\s*=\s*|\s+)(.+?)\s*$")
    p_src = re.compile(r"^\s*source\s+(.+?)\s*$")

    if raw_content is not None:
        lines = raw_content.splitlines()
    else:
        try:
            with open(script_path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except Exception:
            lines = []

    # PASS 1: Pre-collect all environment variables defined in this script
    for raw in lines:
        stripped = raw.split("#")[0].strip()
        if not stripped: continue
        m = p_env.match(stripped) or p_set.match(stripped)
        if m:
            var = m.group(1)
            val_part = m.group(2).strip().strip('"\'()')
            # If overridden, use override value immediately
            if overrides and var in overrides:
                env[var] = overrides[var]
            else:
                try:
                    tokens = shlex.split(val_part, posix=True)
                    env[var] = tokens[0] if tokens else ""
                except Exception:
                    env[var] = val_part.strip('"\'')

    # Deep expand local variables
    for _ in range(3):
        for k in env:
            env[k] = recursive_expand(env[k], env)

    # PASS 2: Re-process the script to build rows and follow sourced files
    for lineno, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        stripped = line.split("#")[0].strip()
        if not stripped: continue
        
        # Follow Sourced Files (e.g., ASSIGNS.emf) using the collected environment
        m_src = p_src.match(stripped)
        if m_src:
            src_p = m_src.group(1).strip().strip('"\'')
            expanded_src = recursive_expand(src_p, env)
            if not os.path.isabs(expanded_src):
                 expanded_src = os.path.normpath(os.path.join(os.path.dirname(script_path), expanded_src))
            
            if os.path.exists(expanded_src) and expanded_src != script_path:
                env.update(parse_tcsh_all_env_vars(expanded_src, env))
            continue

        m = p_env.match(stripped) or p_set.match(stripped)
        if not m: continue
        var = m.group(1)
        val_part = m.group(2).strip().strip('"\'()')
        
        # Determine status for the GUI row
        expanded = env.get(var, "")
        status = "nopath"
        if re.match(r"^(/|\.\.?/)", expanded):
            if glob.glob(expanded):
                status = "empty" if is_functionally_empty(expanded) else "ok"
            else:
                status = "missing"

        kind = "setenv" if p_env.match(stripped) else "set"
        rows.append(dict(var=var, value=val_part, expanded=expanded,
                         kind=kind, lineno=lineno, status=status))
    
    # 3. Final deep expansion pass for all variables and rows
    for _ in range(5): 
        for k in env:
            env[k] = recursive_expand(env[k], env)
            
    for row in rows:
        if overrides and row["var"] in overrides:
            row["value"] = overrides[row["var"]]
            row["expanded"] = overrides[row["var"]]
        else:
            row["expanded"] = recursive_expand(row["value"], env)
        # Re-check status with fully expanded path
        expanded = row["expanded"]
        if expanded and re.match(r"^(/|\.\.?/)", expanded):
             if glob.glob(expanded):
                 row["status"] = "empty" if is_functionally_empty(expanded) else "ok"
             else:
                 row["status"] = "missing"
        
    return rows, env

class CSHHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []
        
        # Keywords
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#c678dd"))
        kw_fmt.setFontWeight(QFont.Bold)
        keywords = ["setenv", "set", "source", "if", "then", "else", "endif", "foreach", "end", "while", "breaksw", "switch", "endsw", "limit"]
        for kw in keywords:
            self._rules.append((re.compile(rf"\b{kw}\b"), kw_fmt))
            
        # Variables
        var_fmt = QTextCharFormat()
        var_fmt.setForeground(QColor("#61afef"))
        self._rules.append((re.compile(r"\$\{?[A-Za-z0-9_]+\}?"), var_fmt))
        
        # Strings
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#98c379"))
        self._rules.append((re.compile(r'"[^"\n]*"'), str_fmt))
        self._rules.append((re.compile(r"'[^'\n]*'"), str_fmt))
        
        # Comments
        comm_fmt = QTextCharFormat()
        comm_fmt.setForeground(QColor("#5c6370"))
        comm_fmt.setFontItalic(True)
        self._rules.append((re.compile(r"#.*"), comm_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)

# ── Main ──────────────────────────────────────────────────────────

class LogSignal(QObject):
    new_line = Signal(str)
    done = Signal(int)

class OverrideDialog(QDialog):
    def __init__(self, var, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Override {var}")
        self.setStyleSheet(f"background-color: {PALETTE['bg']}; color: {PALETTE['fg']};")
        self.var = var
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Variable: {var}"))
        self.entry = QLineEdit(current)
        self.entry.setStyleSheet(f"background-color: {PALETTE['entry_bg']};")
        layout.addWidget(self.entry)
        
        btn_box = QDialogButtonBox()
        btn_apply = btn_box.addButton("Apply", QDialogButtonBox.AcceptRole)
        btn_clear = btn_box.addButton("Clear Override", QDialogButtonBox.DestructiveRole)
        btn_cancel = btn_box.addButton("Cancel", QDialogButtonBox.RejectRole)
        layout.addWidget(btn_box)
        
        btn_apply.clicked.connect(self.accept)
        btn_clear.clicked.connect(self.clear_reject)
        btn_cancel.clicked.connect(self.reject)
        
        self.cleared = False
        
    def clear_reject(self):
        self.cleared = True
        self.accept()

class DefinitionDialog(QDialog):
    def __init__(self, var_key, doc_html, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Documentation: {var_key}")
        self.setMinimumSize(700, 500)
        self.setStyleSheet(f"background-color: {PALETTE['bg']};")
        
        layout = QVBoxLayout(self)
        
        self.browser = QTextBrowser()
        self.browser.setHtml(doc_html)
        self.browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {PALETTE['panel']};
                color: {PALETTE['fg']};
                border: 1px solid {PALETTE['border']};
                padding: 15px;
                line-height: 1.6;
            }}
        """)
        layout.addWidget(self.browser)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

class ColumnRuler(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setFixedHeight(22)
        # Inherit font from editor to ensure exact match
        self.setFont(self.editor.font())
        self.editor.horizontalScrollBar().valueChanged.connect(self.update)
        self.editor.updateRequest.connect(self._handle_update)
        
    def _handle_update(self, rect, dy):
        if dy == 0: self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(PALETTE['entry_bg']))
        painter.setPen(QColor(PALETTE['fg2']))
        
        # Use editor's font metrics for perfect synchronization
        fm = self.editor.fontMetrics()
        char_width = fm.horizontalAdvance(' ') if QT_VERSION == 6 else fm.width(' ')
        
        offset = self.editor.horizontalScrollBar().value()
        start_col = offset
        
        # Account for viewport margins and document margin
        margin = self.editor.document().documentMargin()
        content_offset = self.editor.contentOffset().x() + margin
        
        width = self.width()
        max_cols = int(width / char_width) + 2
        
        painter.setFont(self.editor.font())
        for col in range(start_col, start_col + max_cols + 1):
            x = (col - start_col) * char_width + content_offset
            
            if col % 10 == 0:
                painter.drawLine(int(x), 12, int(x), 22)
                if col > 0:
                    painter.drawText(int(x) - (fm.horizontalAdvance(str(col))//2 if QT_VERSION==6 else fm.width(str(col))//2), 10, str(col))
            elif col % 5 == 0:
                painter.drawLine(int(x), 17, int(x), 22)
            else:
                painter.drawLine(int(x), 20, int(x), 22)

class FileViewerDialog(QDialog):
    def __init__(self, path, var_name, parent=None):
        super().__init__(parent)
        self.path = path
        self.var_name = var_name
        self.parent_app = parent
        self.original_content = ""
        self.is_netcdf = check_netcdf(path)
        
        self.setWindowTitle(f"Viewing: {os.path.basename(path)} ({var_name})")
        self.resize(1100, 800)
        self.setStyleSheet(f"background-color: {PALETTE['bg']}; color: {PALETTE['fg']};")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)
        
        # Toolbar
        tbar_container = QWidget()
        tbar = QHBoxLayout(tbar_container)
        tbar.setContentsMargins(5, 5, 5, 5)
        
        self.btn_edit = QPushButton("Edit File")
        self.btn_edit.clicked.connect(lambda: self._set_edit_mode(True))
        tbar.addWidget(self.btn_edit)
        
        self.btn_cancel = QPushButton("Cancel Edits")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(lambda: self._set_edit_mode(False))
        tbar.addWidget(self.btn_cancel)
        
        self.btn_save_as = QPushButton("Save As...")
        self.btn_save_as.setEnabled(False)
        self.btn_save_as.clicked.connect(self._save_as)
        tbar.addWidget(self.btn_save_as)

        if self.is_netcdf:
            self.btn_edit.hide()
            self.btn_cancel.hide()
            self.btn_save_as.hide()
            tbar.addWidget(QLabel("<b>[Binary NetCDF Mode]</b> Read-only metadata visualization"))
        
        tbar.addStretch()
        layout.addWidget(tbar_container)

        # Content Area (Text/NC View)
        self.text = QPlainTextEdit()
        # Set high-priority monospaced font for precision alignment
        v_font = QFont("DejaVu Sans Mono", 10)
        v_font.setStyleHint(QFont.Monospace)
        self.text.setFont(v_font)
        
        self.ruler = ColumnRuler(self.text)
        layout.addWidget(self.ruler)
        layout.addWidget(self.text)
        if self.is_netcdf: self.ruler.hide()

        # Shared Editor styling
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {PALETTE['panel']};
                color: {PALETTE['fg']};
                border: 1px solid {PALETTE['border']};
                padding: 0px;
            }}
        """)
        
        try:
            if self.is_netcdf:
                self.original_content = get_nc_metadata(path)
                self.text.setPlainText(self.original_content)
            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    self.original_content = f.read(5*1024*1024) 
                    self.text.setPlainText(self.original_content)
                    if f.read(1):
                        self.text.appendPlainText("\n\n... [File truncated for performance] ...")
                    
        except Exception as e:
            if hasattr(self, 'text'):
                self.text.setPlainText(f"[Error reading file: {path}\n\n{e}]")
        
        # Status Bar
        self.status_bar = QWidget()
        self.status_bar.setFixedHeight(25)
        self.status_bar.setStyleSheet(f"background-color: {PALETTE['panel']}; border-top: 1px solid {PALETTE['border']};")
        sbox = QHBoxLayout(self.status_bar)
        sbox.setContentsMargins(10, 0, 10, 0)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 9pt; font-weight: bold;")
        sbox.addWidget(self.status_label)
        sbox.addStretch()
        layout.addWidget(self.status_bar)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
        # Connect signals only after all UI members are initialized
        self.text.cursorPositionChanged.connect(self._update_status)
        self._update_status()

    def _update_status(self, *args):
        cursor = self.text.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.status_label.setText(f"Line: {line}, Col: {col}")


    def _set_edit_mode(self, editing):
        self.text.setReadOnly(not editing)
        self.text.setStyleSheet(f"background-color: {PALETTE['entry_bg'] if editing else PALETTE['panel']}; color: {PALETTE['fg']}; border: 1px solid {PALETTE['border']}; padding: 10px;")
        self.btn_edit.setEnabled(not editing)
        self.btn_cancel.setEnabled(editing)
        self.btn_save_as.setEnabled(editing)
        if not editing:
            self.text.setPlainText(self.original_content)
            
    def _save_as(self):
        new_path, _ = QFileDialog.getSaveFileName(self, "Save File As", os.path.dirname(self.path), "All Files (*)")
        if new_path:
            try:
                content = self.text.toPlainText()
                with open(new_path, "w", encoding="utf-8") as f:
                    f.write(content)
                
                QMessageBox.information(self, "Success", f"File saved to:\n{new_path}\n\nThe variable '{self.var_name}' has been updated with this new path.")
                
                # Update original content to current so cancel doesn't wipe it
                self.original_content = content
                self._set_edit_mode(False)
                
                # Propagate to parent app
                if self.parent_app:
                    self.parent_app.apply_override(self.var_name, new_path)
                    
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save file: {e}")

class SMKRunApp(QMainWindow):
    def __init__(self, initial_script: Optional[str] = None, initial_dir: Optional[str] = None, auto_run: bool = False):
        super().__init__()
        self.setWindowTitle(f"SMOKE Run Launcher · 2022v2 Platform (Qt{QT_VERSION})")
        self.resize(1600, 950)
        
        self._scripts_root = SCRIPTS_ROOT
        if initial_dir and os.path.isdir(initial_dir):
            self._scripts_root = os.path.abspath(initial_dir)
        elif initial_script and os.path.exists(initial_script):
            self._scripts_root = os.path.dirname(os.path.abspath(initial_script))
        self._proc = None
        self._running = False
        self._current_script: Optional[str] = None
        self._var_rows: List[Dict] = []
        self._overrides: Dict[str, str] = {}
        self._script_override_content: Optional[str] = None
        self._last_output_state = None  # Hash of grouping state to avoid redundant churn
        self._last_input_state = None
        
        self.log_signal = LogSignal()
        self.log_signal.new_line.connect(self._append_log)
        self.log_signal.done.connect(self._run_done)
        
        self._env_docs = self._load_env_docs()
        
        self._apply_theme()
        self._build_ui()
        self._filter_tree()
        
        if initial_script and os.path.exists(initial_script):
            # Use QTimer to ensure the UI is fully initialized before loading
            def do_init_load():
                self._load_script(initial_script)
                if auto_run:
                    self._run_script(bypass_confirm=True)
            QTimer.singleShot(100, do_init_load)
        
    def _load_env_docs(self) -> Dict[str, str]:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        yaml_files = [
            os.path.join(base_dir, "smoke_env_vars.yaml"),
            os.path.join(base_dir, "emf_env_vars.yaml")
        ]
        
        docs = {}
        import collections
        # Group by Variable Name -> (Description, Default) -> List of Programs
        raw_grouped = collections.defaultdict(lambda: collections.defaultdict(list))

        for yaml_path in yaml_files:
            if not os.path.exists(yaml_path):
                continue
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
            except Exception as e:
                print(f"Error loading {os.path.basename(yaml_path)}: {e}")

        # Construct HTML for each variable
        for vname, groups in raw_grouped.items():
            sections = []
            # Sort by progs to keep it stable
            for (desc, default), progs in sorted(groups.items(), key=lambda x: sorted(x[1])[0]):
                prog_list = ", ".join(sorted(progs))
                html = f"<b>{vname}</b> <i>({prog_list})</i>"
                if default and default != "None" and default != "''":
                    html += f"<br><b>Default:</b> {default}"
                if desc:
                    html += f"<br><br>{desc}"
                sections.append(html)
            docs[vname] = "<hr>".join(sections)
            
        # Clean up undefined list if we found docs for something previously undefined
        undef_path = os.path.join(base_dir, "undefined_variable.yaml")
        if os.path.exists(undef_path):
            try:
                with open(undef_path, 'r', encoding='utf-8') as f:
                    undef_data = yaml.safe_load(f) or {}
                
                # Remove if now documented
                cleaned_undef = {k: v for k, v in undef_data.items() if k not in docs}
                
                if len(cleaned_undef) != len(undef_data):
                    with open(undef_path, 'w', encoding='utf-8') as f:
                        yaml.dump(cleaned_undef, f)
            except Exception as e:
                print(f"Error cleaning undefined variables list: {e}")
                        
        return docs

    def _apply_theme(self):
        qss = f"""
        QMainWindow, QDialog, QWidget {{
            background-color: {PALETTE['bg']};
            color: {PALETTE['fg']};
            font-family: Inter, sans-serif;
            font-size: 10pt;
        }}
        QSplitter::handle {{ background-color: {PALETTE['border']}; }}
        QTreeWidget, QTableWidget, QListWidget {{
            background-color: {PALETTE['panel']};
            border: 1px solid {PALETTE['border']};
            color: {PALETTE['fg']};
            gridline-color: {PALETTE['border']};
        }}
        QHeaderView::section {{
            background-color: {PALETTE['border']};
            color: {PALETTE['fg2']};
            font-weight: bold;
            padding: 4px;
            border: none;
        }}
        QPushButton {{
            background-color: {PALETTE['accent']};
            color: white;
            font-weight: bold;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
        }}
        QPushButton:hover {{ background-color: {PALETTE['accent2']}; }}
        QPushButton:pressed {{ background-color: #4752c4; }}
        QPushButton#success {{ background-color: {PALETTE['success']}; color: white; }}
        QPushButton#danger {{ background-color: {PALETTE['error']}; color: white; }}
        QPushButton#danger:disabled {{ background-color: {PALETTE['border']}; color: {PALETTE['fg2']}; }}
        QPushButton:disabled {{ background-color: {PALETTE['border']}; color: {PALETTE['fg2']}; }}
        QTextEdit, QLineEdit, QComboBox {{
            background-color: {PALETTE['entry_bg']};
            color: {PALETTE['fg']};
            border: 1px solid {PALETTE['border']};
            padding: 4px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {PALETTE['panel']};
            selection-background-color: {PALETTE['accent']};
        }}
        QTabWidget::pane {{ border: 1px solid {PALETTE['border']}; background-color: {PALETTE['panel']}; }}
        QTabBar::tab {{
            background-color: {PALETTE['border']};
            color: {PALETTE['fg']};
            padding: 8px 16px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{ background-color: {PALETTE['accent']}; color: white; }}
        """
        self.setStyleSheet(qss)

    def _build_ui(self):
        main_w = QWidget()
        self.setCentralWidget(main_w)
        layout = QVBoxLayout(main_w)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Toolbar
        tb = QWidget()
        tb.setStyleSheet(f"background-color: {PALETTE['panel']};")
        tb_layout = QHBoxLayout(tb)
        tb_layout.setContentsMargins(8, 8, 8, 8)
        
        lbl_title = QLabel("SMOKE Run Launcher")
        lbl_title.setFont(QFont("Inter", 14, QFont.Bold))
        tb_layout.addWidget(lbl_title)
        
        lbl_author = QLabel("Author: tranhuy@email.unc.edu")
        lbl_author.setStyleSheet(f"color: {PALETTE['fg2']}; font-size: 9pt; margin-left: 10px;")
        tb_layout.addWidget(lbl_author)
        
        self._lbl_script = QLabel("No script selected")
        self._lbl_script.setStyleSheet(f"color: {PALETTE['fg2']};")
        tb_layout.addWidget(self._lbl_script)
        
        tb_layout.addStretch()
        
        self._status_var = QLabel("Ready")
        self._status_var.setStyleSheet(f"color: {PALETTE['fg2']};")
        tb_layout.addWidget(self._status_var)
        
        btn_open = QPushButton("Open Script")
        btn_open.clicked.connect(self._browse_script)
        tb_layout.addWidget(btn_open)
        
        self._btn_run = QPushButton("Run Script")
        self._btn_run.setObjectName("success")
        self._btn_run.clicked.connect(self._run_script)
        tb_layout.addWidget(self._btn_run)
        
        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_script)
        tb_layout.addWidget(self._btn_stop)
        
        layout.addWidget(tb)
        
        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)
        
        # LEFT: Tree
        left_w = QWidget()
        left_w.setStyleSheet(f"background-color: {PALETTE['panel']};")
        left_layout = QVBoxLayout(left_w)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        lh = QWidget()
        lh_layout = QHBoxLayout(lh)
        lbl_tree = QLabel("Script Browser")
        lbl_tree.setFont(QFont("Inter", 11, QFont.Bold))
        lbl_tree.setStyleSheet(f"color: {PALETTE['accent2']};")
        lh_layout.addWidget(lbl_tree)
        btn_root = QPushButton("Root")
        btn_root.clicked.connect(self._change_scripts_root)
        lh_layout.addWidget(btn_root)
        left_layout.addWidget(lh)
        
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter scripts (e.g. *.csh, *.py, mrg)")
        self._filter_edit.setText(DEFAULT_SCRIPT_FILTER)
        self._filter_edit.textChanged.connect(self._filter_tree)
        left_layout.addWidget(self._filter_edit)
        
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(self._on_tree_double)
        left_layout.addWidget(self._tree, 1)
        
        splitter.addWidget(left_w)
        
        # CENTER: Notebook
        self._notebook = QTabWidget()
        splitter.addWidget(self._notebook)
        
        self._build_vars_tab(self._notebook)
        self._build_source_tab(self._notebook)
        self._build_log_tab(self._notebook)
        self._build_input_tab(self._notebook)
        self._build_viz_tab(self._notebook)
        self._build_analysis_tab(self._notebook)
        
        splitter.setSizes([300, 1300])

    def _tab_index(self, title: str) -> int:
        """Return the notebook index whose tabText matches *title* exactly.
        Falls back to 0 if not found, so navigation never crashes."""
        for i in range(self._notebook.count()):
            if self._notebook.tabText(i) == title:
                return i
        return 0

    def _build_vars_tab(self, parent):
        w = QWidget()
        layout = QVBoxLayout(w)
        
        top = QHBoxLayout()
        lbl = QLabel("Environment Variables (double-click value to edit override)")
        lbl.setFont(QFont("Inter", 10, QFont.Bold))
        lbl.setStyleSheet(f"color: {PALETTE['accent2']};")
        top.addWidget(lbl)
        top.addStretch()
        btn_reload = QPushButton("Reload")
        btn_reload.clicked.connect(self._reload_vars)
        top.addWidget(btn_reload)
        btn_check = QPushButton("Check Paths")
        btn_check.clicked.connect(self._check_paths)
        top.addWidget(btn_check)
        layout.addLayout(top)
        
        leg = QHBoxLayout()
        for sym, text, col in [("[OK] ", "File exists", PALETTE["success"]),
                               ("[W] ", "Empty file", PALETTE["warn"]),
                               ("[X] ", "Missing", PALETTE["error"]),
                               ("[-] ", "Not a path", PALETTE["fg2"])]:
            l = QLabel(f" {sym} {text}")
            l.setStyleSheet(f"color: {col};")
            leg.addWidget(l)
        leg.addStretch()
        layout.addLayout(leg)
        
        self._var_table = QTableWidget(0, 6)
        self._var_table.setHorizontalHeaderLabels(["#", "kind", "Variable", "Raw Value", "Expanded Path", "Status"])
        self._var_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._var_table.horizontalHeader().setStretchLastSection(True)
        self._var_table.setColumnWidth(0, 50)
        self._var_table.setColumnWidth(1, 80)
        self._var_table.setColumnWidth(2, 200)
        self._var_table.setColumnWidth(3, 260)
        self._var_table.setColumnWidth(4, 380)
        self._var_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._var_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._var_table.cellDoubleClicked.connect(self._edit_var_cell)
        self._var_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._var_table.customContextMenuRequested.connect(self._show_var_context_menu)
        layout.addWidget(self._var_table, 1)
        
        self._lbl_overrides = QLabel("No overrides set.")
        self._lbl_overrides.setStyleSheet(f"color: {PALETTE['fg2']};")
        layout.addWidget(self._lbl_overrides)
        
        parent.addTab(w, "  Variables  ")

    def _build_log_tab(self, parent):
        w = QWidget()
        layout = QVBoxLayout(w)
        
        ctrl = QHBoxLayout()
        btn_clear = QPushButton("Clear Log")
        btn_clear.clicked.connect(self._clear_log)
        ctrl.addWidget(btn_clear)
        btn_save = QPushButton("Save Log")
        btn_save.clicked.connect(self._save_log)
        ctrl.addWidget(btn_save)
        ctrl.addStretch()
        self._lbl_run_status = QLabel("")
        self._lbl_run_status.setFont(QFont("Inter", 10, QFont.Bold))
        ctrl.addWidget(self._lbl_run_status)
        
        layout.addLayout(ctrl)
        
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Courier New", 9))
        self._log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._log_text.setMaximumBlockCount(10000) # Robustness for massive logs
        layout.addWidget(self._log_text, 1)
        
        parent.addTab(w, "  Run Log  ")

    def _build_source_tab(self, parent):
        w = QWidget()
        layout = QVBoxLayout(w)
        
        # Source Toolbar
        tbar = QHBoxLayout()
        self._btn_edit_src = QPushButton("Edit Script")
        self._btn_edit_src.clicked.connect(self._toggle_edit_src)
        tbar.addWidget(self._btn_edit_src)
        
        self._btn_save_src = QPushButton("Save to File")
        self._btn_save_src.setEnabled(False)
        self._btn_save_src.clicked.connect(self._save_src_to_file)
        tbar.addWidget(self._btn_save_src)
        
        self._btn_reset_src = QPushButton("Reset Script")
        self._btn_reset_src.setEnabled(False)
        self._btn_reset_src.clicked.connect(self._reset_src)
        tbar.addWidget(self._btn_reset_src)

        self._btn_cancel_src = QPushButton("Cancel Edit")
        self._btn_cancel_src.setEnabled(False)
        self._btn_cancel_src.setObjectName("danger")
        self._btn_cancel_src.clicked.connect(self._cancel_edit_src)
        tbar.addWidget(self._btn_cancel_src)
        
        tbar.addStretch()
        
        self._src_search = QLineEdit()
        self._src_search.setPlaceholderText("Find in script...")
        self._src_search.setFixedWidth(200)
        self._src_search.textChanged.connect(self._search_source)
        tbar.addWidget(self._src_search)
        
        layout.addLayout(tbar)
        
        self._src_text = QTextEdit() # Use QTextEdit here for full highlighter support
        self._src_text.setReadOnly(True)
        self._src_text.setStyleSheet(f"background-color: {PALETTE['panel']}; color: {PALETTE['fg']};")
        self._src_text.setFont(QFont("Courier New", 10))
        self._src_text.setLineWrapMode(QTextEdit.NoWrap)
        self._src_highlighter = CSHHighlighter(self._src_text.document())
        layout.addWidget(self._src_text)
        parent.addTab(w, "  Source  ")

    def _build_viz_tab(self, parent):
        w = QWidget()
        layout = QVBoxLayout(w)
        
        
        self._file_tree = QTreeWidget()
        self._file_tree.setColumnCount(2)
        self._file_tree.setHeaderLabels(["File Name", "Absolute Path"])
        self._file_tree.setColumnWidth(0, 300)
        self._file_tree.setHeaderHidden(False)
        self._file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._file_tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        # Double-click to open in pop-up viewer
        self._file_tree.itemDoubleClicked.connect(self._handle_tree_selection)
        self._file_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {PALETTE['panel']};
                border: 1px solid {PALETTE['border']};
                padding: 10px;
            }}
            QTreeWidget::item {{ padding: 6px; }}
        """)
        layout.addWidget(self._file_tree, 1)
        
        parent.addTab(w, "  Output Files  ")

    def _build_input_tab(self, parent):
        w = QWidget()
        layout = QVBoxLayout(w)
        
        
        self._input_file_tree = QTreeWidget()
        self._input_file_tree.setColumnCount(2)
        self._input_file_tree.setHeaderLabels(["File Name", "Absolute Path"])
        self._input_file_tree.setColumnWidth(0, 300)
        self._input_file_tree.setHeaderHidden(False)
        self._input_file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._input_file_tree.customContextMenuRequested.connect(self._on_input_tree_context_menu)
        self._input_file_tree.itemDoubleClicked.connect(self._handle_input_tree_selection)
        self._input_file_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {PALETTE['panel']};
                border: 1px solid {PALETTE['border']};
                padding: 10px;
            }}
            QTreeWidget::item {{ padding: 6px; }}
        """)
        layout.addWidget(self._input_file_tree, 1)
        
        parent.addTab(w, "  Input Files  ")

    def _build_analysis_tab(self, parent):
        w = QWidget()
        layout = QVBoxLayout(w)
        
        ctrl = QHBoxLayout()
        btn = QPushButton("Analyse Current Log")
        btn.clicked.connect(self._analyse_log)
        ctrl.addWidget(btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)
        
        paned = QSplitter(Qt.Horizontal)
        
        left = QWidget()
        lv = QVBoxLayout(left)
        lh1 = QLabel("Errors & Warnings")
        lh1.setFont(QFont("Inter", 10, QFont.Bold))
        lh1.setStyleSheet(f"color: {PALETTE['warn']};")
        lv.addWidget(lh1)
        self._issues_list = QListWidget()
        self._issues_list.setFont(QFont("Courier New", 9))
        self._issues_list.itemClicked.connect(self._jump_to_log_line)
        lv.addWidget(self._issues_list, 1)
        paned.addWidget(left)
        
        right = QWidget()
        rv = QVBoxLayout(right)
        lh2 = QLabel("Summary")
        lh2.setFont(QFont("Inter", 10, QFont.Bold))
        lh2.setStyleSheet(f"color: {PALETTE['accent2']};")
        rv.addWidget(lh2)
        self._analysis_text = QTextEdit()
        self._analysis_text.setReadOnly(True)
        self._analysis_text.setFont(QFont("Courier New", 9))
        rv.addWidget(self._analysis_text, 1)
        paned.addWidget(right)
        
        layout.addWidget(paned, 1)
        parent.addTab(w, "  Log Analysis  ")

    def _populate_script_tree(self, root_dir: str, exts: Tuple[str, ...] = (".csh", ".tcsh")):
        self._tree.clear()
        if not os.path.isdir(root_dir): return
        self._walk_dir(root_dir, self._tree.invisibleRootItem(), exts)
        
    def _walk_dir(self, path: str, parent: QTreeWidgetItem, exts: Tuple[str, ...]):
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError: return
        for entry in entries:
            if entry.name.startswith("."): continue
            if entry.is_dir():
                item = QTreeWidgetItem(parent, [f"[+] {entry.name}"])
                item.setData(0, Qt.UserRole, entry.path)
                self._walk_dir(entry.path, item, exts)
            elif entry.name.lower().endswith(exts):
                item = QTreeWidgetItem(parent, [f"    {entry.name}"])
                item.setData(0, Qt.UserRole, entry.path)

    def _change_scripts_root(self):
        d = QFileDialog.getExistingDirectory(self, "Select Scripts Root Directory", self._scripts_root)
        if d:
            self._scripts_root = d
            self._filter_edit.setText(DEFAULT_SCRIPT_FILTER)
            self._filter_tree()

    def _parse_filter(self, text: str) -> Tuple[Tuple[str, ...], List[str]]:
        if not text.strip():
            return (".csh", ".tcsh"), []
        parts = [p.strip().lower() for p in text.split(",") if p.strip()]
        exts = []
        keywords = []
        for p in parts:
            if p == "*.*":
                exts.append("")
            elif p.startswith("*.") or (p.startswith(".") and len(p) > 1):
                exts.append(p.replace("*", ""))
            else:
                keywords.append(p)
        if not exts:
            exts = [".csh", ".tcsh"]
        return tuple(exts), keywords

    def _filter_tree(self):
        text = self._filter_edit.text()
        exts, keywords = self._parse_filter(text)
        
        if not keywords:
            self._populate_script_tree(self._scripts_root, exts)
            return
            
        self._tree.clear()
        query = " ".join(keywords).lower()
        for root, dirs, files in os.walk(self._scripts_root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for f in sorted(files):
                if query in f.lower() and f.lower().endswith(exts):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, self._scripts_root)
                    it = QTreeWidgetItem(self._tree.invisibleRootItem(), [f"    {rel}"])
                    it.setData(0, Qt.UserRole, full)

    def _on_tree_double(self, item: QTreeWidgetItem, column: int):
        path = item.data(0, Qt.UserRole)
        if path and os.path.isfile(path):
            self._load_script(path)

    def _browse_script(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open SMOKE Runscript", self._scripts_root, "CSH scripts (*.csh *.tcsh);;All files (*)")
        if path:
            self._load_script(path)

    def _load_script(self, path: str):
        self._current_script = os.path.abspath(path)
        self._script_override_content = None
        self._lbl_script.setText(os.path.basename(path))
        self._btn_cancel_src.setEnabled(False)
        try: rel = os.path.relpath(path, self._scripts_root)
        except ValueError: rel = path
        self._status_var.setText(f"Loaded: {rel}")
        self._load_vars(path)
        self._load_source(path)
        self._scan_outputs()
        self._scan_inputs()
        self._notebook.setCurrentIndex(self._tab_index("  Variables  "))

    def _load_vars(self, path: str):
        self._var_rows, self._env = parse_script_vars(path)
        self._overrides.clear()
        self._refresh_var_tree()
        self._lbl_overrides.setText("No overrides set.")

    def _reload_vars(self):
        if self._current_script:
            self._load_vars(self._current_script)

    def _refresh_var_tree(self):
        self._var_table.setRowCount(0)
        status_sym = {"ok": "[OK] ", "missing": "[X] ", "empty": "[W] ", "nopath": "[-] "}
        status_col = {"ok": PALETTE["success"], "missing": PALETTE["error"], "empty": PALETTE["warn"], "nopath": PALETTE["fg"]}
        
        for row in self._var_rows:
            r = self._var_table.rowCount()
            self._var_table.insertRow(r)
            var = row["var"]
            val = row["value"]
            expanded = row["expanded"]
            status = row["status"]
            
            sym = status_sym.get(status, "[-] ")
            
            items = [
                QTableWidgetItem(str(row["lineno"])),
                QTableWidgetItem(row["kind"]),
                QTableWidgetItem(var),
                QTableWidgetItem(val),
                QTableWidgetItem(expanded),
                QTableWidgetItem(sym)
            ]
            
            items[5].setForeground(QBrush(QColor(status_col.get(status, PALETTE["fg"]))))
            
            if var in self._overrides:
                for i in range(6): items[i].setBackground(QBrush(QColor(PALETTE["override"])))
            
            for c, it in enumerate(items):
                it.setData(Qt.UserRole, var)
                self._var_table.setItem(r, c, it)

    def _show_var_context_menu(self, pos):
        it = self._var_table.itemAt(pos)
        if it:
            var = it.data(Qt.UserRole)
            if var:
                var_key = var.strip(" :.'\",").upper()
                desc = "No builtin documentation available for this variable."
                if hasattr(self, "_env_docs") and var_key in self._env_docs:
                    desc = self._env_docs[var_key]
                else:
                    # Log undocumented variable
                    undef_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "undefined_variable.yaml")
                    try:
                        import yaml
                        undef_data = {}
                        if os.path.exists(undef_path):
                            with open(undef_path, 'r', encoding='utf-8') as f:
                                undef_data = yaml.safe_load(f) or {}
                                
                        if var_key not in undef_data:
                            undef_data[var_key] = "Placeholder: Write documentation for this variable here."
                            with open(undef_path, 'w', encoding='utf-8') as f:
                                yaml.dump(undef_data, f)
                    except Exception as e:
                        print(f"Could not update undefined variables list: {e}")
                    
                menu = QMenu(self)
                action_def = menu.addAction(f"Define Variable: {var}")
                action_def.triggered.connect(lambda checked=False, k=var_key, d=desc: self._show_var_definition(k, d))
                
                action_over = menu.addAction(f"Override Variable: {var}")
                action_over.triggered.connect(lambda checked=False, r=it.row(), c=it.column(): self._edit_var_cell(r, c))
                
                # Add View File if it's an existing file
                r_idx = it.row()
                if r_idx < len(self._var_rows):
                    expanded_path = self._var_rows[r_idx]["expanded"]
                    if os.path.isfile(expanded_path):
                        menu.addSeparator()
                        action_view = menu.addAction(f"View/Edit File: {os.path.basename(expanded_path)}")
                        action_view.triggered.connect(lambda checked=False, p=expanded_path, v=var: self._show_file_viewer(p, v))
                        
                        action_copy = menu.addAction("Copy Path")
                        action_copy.triggered.connect(lambda checked=False, p=expanded_path: QApplication.clipboard().setText(p))
                
                if QT_VERSION == 6: menu.exec(self._var_table.viewport().mapToGlobal(pos))
                else: menu.exec_(self._var_table.viewport().mapToGlobal(pos))
                
    def _show_var_definition(self, var_key, desc):
        dlg = DefinitionDialog(var_key, desc, self)
        if QT_VERSION == 6: dlg.exec()
        else: dlg.exec_()
        
    def _show_file_viewer(self, path, var_name):
        dlg = FileViewerDialog(path, var_name, self)
        dlg.show() # Non-modal so user can keep it open
        
    def apply_override(self, var, value):
        self._overrides[var] = value
        self._var_rows, self._env = parse_script_vars(self._current_script, self._overrides, self._script_override_content)
        self._refresh_var_tree()
        n = len(self._overrides)
        self._lbl_overrides.setText(f"{n} override(s) active" + (" + Patched" if self._script_override_content else ""))

    def _check_paths(self):
        if not self._current_script: return
        
        miss, empty, ok, nopath = 0, 0, 0, 0
        for i in range(self._var_table.rowCount()):
            sym = self._var_table.item(i, 5).text().strip()
            if sym == "[X]": miss += 1
            elif sym == "[W]": empty += 1
            elif sym == "[OK]": ok += 1
            else: nopath += 1
            
        QMessageBox.information(self, "Path Check", f"[OK]  OK: {ok}\n[W]  Empty: {empty}\n[X]  Missing: {miss}\n[-]  Non-path: {nopath}")

    def _edit_var_cell(self, row, col):
        it = self._var_table.item(row, col)
        if not it: return
        var = it.data(Qt.UserRole)
        r_info = next((r for r in self._var_rows if r["var"] == var), None)
        if not r_info: return
        current = self._overrides.get(var, r_info["value"])
        
        dlg = OverrideDialog(var, current, self)
        res = dlg.exec() if QT_VERSION == 6 else dlg.exec_()
        if res == QDialog.Accepted:
            if dlg.cleared:
                self._overrides.pop(var, None)
            else:
                nv = dlg.entry.text().strip()
                if nv: self._overrides[var] = nv
                elif var in self._overrides: self._overrides.pop(var, None)
            
            # Cascade re-parse all paths dynamically
            self._var_rows, self._env = parse_script_vars(self._current_script, self._overrides, self._script_override_content)
            self._refresh_var_tree()
            n = len(self._overrides)
            self._lbl_overrides.setText(f"{n} override(s): {', '.join(self._overrides)}" if n else "No overrides set.")

    def _load_source(self, path: str):
        self._src_text.clear()
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                self._src_text.setPlainText(fh.read())
            self._highlight_source()
        except Exception as exc:
            self._src_text.setPlainText(f"[Error: {exc}]")

    def _highlight_source(self):
        # Highlighting is now handled by CSHHighlighter class automatically
        pass

    def _search_source(self, text):
        if not text: return
        # Simple search and highlight selection
        cursor = self._src_text.textCursor()
        curr_pos = cursor.position()
        
        # Try finding next from current position
        found = self._src_text.find(text)
        if not found:
            # Wrap around
            cursor.setPosition(0)
            self._src_text.setTextCursor(cursor)
            self._src_text.find(text)

    def _toggle_edit_src(self):
        if not self._current_script: return
        
        if self._src_text.isReadOnly():
            # Entering Edit Mode
            if self._script_override_content is not None:
                content = self._script_override_content
            else:
                try:
                    with open(self._current_script, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Could not read file: {e}")
                    return
            
            self._src_text.setPlainText(content)
            self._src_text.setReadOnly(False)
            self._src_text.setStyleSheet(f"background-color: {PALETTE['entry_bg']};")
            self._btn_edit_src.setText("Finish Editing (Apply Override)")
            self._btn_save_src.setEnabled(True)
            self._btn_reset_src.setEnabled(True)
            self._btn_cancel_src.setEnabled(True)
        else:
            # Exiting Edit Mode - Apply as Override
            self._script_override_content = self._src_text.toPlainText()
            self._src_text.setReadOnly(True)
            self._src_text.setStyleSheet(f"background-color: {PALETTE['panel']};")
            self._btn_edit_src.setText("Edit Script")
            self._btn_cancel_src.setEnabled(False)
            self._highlight_source()
            
            n_over = len(self._overrides)
            msg = f"{n_over} var override(s)"
            if self._script_override_content:
                msg += " + Script Patched"
            self._lbl_overrides.setText(msg)
            
            # Refresh variables from edited source
            self._var_rows, self._env = parse_script_vars(self._current_script, self._overrides, self._script_override_content)
            self._refresh_var_tree()

    def _save_src_to_file(self):
        if not self._current_script: return
        
        reply = QMessageBox.question(self, "Confirm Save", 
                                   f"Overwrite {os.path.basename(self._current_script)} permanently?\nThis will save your current edits to the actual file.",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No: return
        
        try:
            content = self._src_text.toPlainText() if not self._src_text.isReadOnly() else self._script_override_content
            if content is None:
                with open(self._current_script, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                    
            with open(self._current_script, "w", encoding="utf-8") as fh:
                fh.write(content)
            
            QMessageBox.information(self, "Saved", "Source file updated permanently.")
            self._script_override_content = None # No longer an override, it's the source
            
            # Reset UI state to non-editing mode
            self._src_text.setReadOnly(True)
            self._src_text.setStyleSheet(f"background-color: {PALETTE['panel']};")
            self._btn_edit_src.setText("Edit Script")
            self._btn_save_src.setEnabled(False)
            self._btn_reset_src.setEnabled(False)
            self._btn_cancel_src.setEnabled(False)
            
            self._load_script(self._current_script) # Re-load everything
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file: {e}")

    def _reset_src(self):
        if not self._current_script: return
        reply = QMessageBox.question(self, "Reset Script", "Discard all edits and reload from disk?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._load_script(self._current_script)
            self._btn_cancel_src.setEnabled(False)

    def _cancel_edit_src(self):
        if not self._current_script: return
        self._src_text.setReadOnly(True)
        self._src_text.setStyleSheet(f"background-color: {PALETTE['panel']};")
        self._btn_edit_src.setText("Edit Script")
        self._btn_save_src.setEnabled(False)
        self._btn_reset_src.setEnabled(False)
        self._btn_cancel_src.setEnabled(False)
        
        # Revert to last applied state or original
        if self._script_override_content is not None:
            self._src_text.setPlainText(self._script_override_content)
        else:
            try:
                with open(self._current_script, "r", encoding="utf-8", errors="ignore") as fh:
                    self._src_text.setPlainText(fh.read())
            except Exception: pass
        self._highlight_source()

    # ── Script Execution ──
    def _run_script(self, bypass_confirm=False):
        if not self._current_script:
            QMessageBox.warning(self, "No Script", "Please select a runscript first.")
            return
        if self._running:
            QMessageBox.warning(self, "Running", "A script is already running.")
            return

        env = os.environ.copy()
        for v, val in self._overrides.items(): env[v] = val

        name = os.path.basename(self._current_script)
        msg = f"Execute:\n  {name}"
        if self._overrides:
            msg += f"\n\nWith {len(self._overrides)} override(s):\n"
            for v, val in self._overrides.items(): msg += f"  {v} = {val}\n"
        if not bypass_confirm:
            reply = QMessageBox.question(self, "Confirm", msg, QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No: return

        self._clear_log()
        self._running = True
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lbl_run_status.setText("[*]  Running...")
        self._lbl_run_status.setStyleSheet(f"color: {PALETTE['warn']};")
        self._status_var.setText(f"Running: {name}")
        self._notebook.setCurrentIndex(self._tab_index("  Run Log  "))

        script_dir = os.path.dirname(self._current_script)
        run_file = self._current_script
        
        if self._overrides or self._script_override_content:
            fd, tmp_script = tempfile.mkstemp(suffix=".csh", prefix="smkrun_override_", dir=script_dir)
            if self._script_override_content:
                lines = self._script_override_content.splitlines(True)
            else:
                with open(self._current_script, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                
            p_env = re.compile(r"^(\s*setenv\s+)([A-Za-z0-9_]+)(\s+.*)$")
            p_set = re.compile(r"^(\s*set\s+)([A-Za-z0-9_]+)(\s*=.*)$")
            
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for line in lines:
                    m_env = p_env.match(line)
                    m_set = p_set.match(line)
                    if m_env and m_env.group(2) in self._overrides:
                        f.write(f"# smkrun override: {line}")
                    elif m_set and m_set.group(2) in self._overrides:
                        f.write(f"# smkrun override: {line}")
                    else:
                        f.write(line)
            
            run_file = tmp_script
            os.chmod(tmp_script, 0o755)

        cmd = [SHELL, run_file]

        def _worker():
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env=env, cwd=script_dir if script_dir else None, universal_newlines=True, bufsize=1,
                    preexec_fn=os.setsid
                )
                for line in self._proc.stdout:
                    self.log_signal.new_line.emit(line)
                self._proc.wait()
                rc = self._proc.returncode
                self.log_signal.new_line.emit(f"\n── Process exited with code {rc} ──\n")
                self.log_signal.done.emit(rc)
            except Exception as exc:
                self.log_signal.new_line.emit(f"\n[smkrun error] {exc}\n")
                self.log_signal.done.emit(-1)
            finally:
                if run_file != self._current_script and os.path.exists(run_file):
                    try: os.remove(run_file)
                    except Exception: pass

        threading.Thread(target=_worker, daemon=True).start()

    def _run_done(self, rc):
        self._running = False
        self._proc = None
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        if rc == 0:
            self._lbl_run_status.setText("[OK]  Completed OK")
            self._lbl_run_status.setStyleSheet(f"color: {PALETTE['success']};")
        else:
            self._lbl_run_status.setText(f"[X]  Exit {rc}")
            self._lbl_run_status.setStyleSheet(f"color: {PALETTE['error']};")
        self._status_var.setText(f"Finished (exit {rc})")
        self._scan_outputs()
        self._scan_inputs()

    def _stop_script(self):
        if self._proc:
            try:
                import signal
                try:
                    pgid = os.getpgid(self._proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    def force_kill():
                        try: os.killpg(pgid, signal.SIGKILL)
                        except Exception: pass
                    QTimer.singleShot(2000, force_kill)
                except ProcessLookupError:
                    pass
            except Exception as e: 
                print(f"Stop Error: {e}")
                pass
        self._lbl_run_status.setText("Stopped")
        self._lbl_run_status.setStyleSheet(f"color: {PALETTE['warn']};")

    def _append_log(self, line: str):
        fmt = QTextCharFormat()
        low = line.lower()
        
        if any(w in low for w in ["error", "abort", "fatal", "sigsegv", "seg fault"]):
            fmt.setForeground(QBrush(QColor(PALETTE["error"])))
        elif any(w in low for w in ["warning", "warn"]):
            fmt.setForeground(QBrush(QColor(PALETTE["warn"])))
        elif "normal completion" in low:
            fmt.setForeground(QBrush(QColor(PALETTE["success"])))
        elif line.startswith(" ") or line.startswith("\t"):
            fmt.setForeground(QBrush(QColor(PALETTE["fg2"])))
        else:
            fmt.setForeground(QBrush(QColor(PALETTE["fg"])))
            
        self._log_text.setCurrentCharFormat(fmt)
        self._log_text.appendPlainText(line.rstrip("\n"))
        
        self._log_text.ensureCursorVisible()
        self._handle_log_path(line)
            


    # Opportunistic scan: if we see a log path being created, trigger a re-scan of outputs
    def _handle_log_path(self, line):
        low = line.lower()
        # Scan if we see a log path OR I/O API output indicators
        if ".log" in low or any(x in low for x in ["opened for output", "opened as unknown", "opened as new", "file name"]):
            now = time.time()
            if not hasattr(self, "_last_auto_scan") or (now - self._last_auto_scan > 2.0):
                self._last_auto_scan = now
                QTimer.singleShot(100, self._scan_outputs)
                QTimer.singleShot(110, self._scan_inputs)

    def _clear_log(self):
        self._log_text.clear()
        self._lbl_run_status.setText("")

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Log", "", "Log files (*.log);;Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._log_text.toPlainText())
            QMessageBox.information(self, "Saved", f"Log saved to:\n{path}")

    def _get_log_program_order(self) -> list:
        """Return a deduplicated list of SMOKE program names in the order they first
        appeared in the Run Log, as identified by 'Program X, Version' markers."""
        text = self._log_text.toPlainText()
        seen, seen_set = [], set()
        for m in re.finditer(r"Program\s+([A-Z0-9_]+)[,\s]+Version", text, re.IGNORECASE):
            prog = m.group(1).upper()
            if prog not in seen_set:
                seen.append(prog)
                seen_set.add(prog)
        return seen

    # ── Outputs ──

    def _smart_isfile(self, path: str) -> Optional[str]:
        """Check if path exists, or if it exists with common Smk extensions or .gz"""
        if os.path.isfile(path): return os.path.abspath(path)
        for ext in [".ncf", ".rpt", ".txt", ".nc", ".csv"]:
            p = path + ext
            if os.path.isfile(p): return os.path.abspath(p)
            if os.path.isfile(p + ".gz"): return os.path.abspath(p + ".gz")
        if os.path.isfile(path + ".gz"): return os.path.abspath(path + ".gz")
        return None

    def _identify_program_from_log_header(self, log_path: str, default_prog: str = None) -> str:
        """Read the first bit of a log file to identify which SMOKE program generated it."""
        if not log_path or not os.path.isfile(log_path):
            return default_prog if default_prog else SMKContext.sanitize_tool_name(os.path.basename(log_path))
        
        try:
            # Avoid huge files
            if os.path.getsize(log_path) > 15 * 1024 * 1024:
                return default_prog if default_prog else SMKContext.sanitize_tool_name(os.path.basename(log_path))
                
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Headers are usually in the first 100 lines
                for _ in range(150):
                    line = f.readline()
                    if not line: break
                    m = re.search(r"Program\s+([A-Z0-9_]+)[,\s]+Version", line, re.IGNORECASE)
                    if m:
                        prog = m.group(1).upper()
                        # If it's a known tool, great
                        if prog in SMKContext.TOOLS: return prog
                        # Otherwise if it looks like a program name (e.g. MOVESMRG)
                        if len(prog) >= 5: return prog
        except:
            pass
            
        # Fallback to filename-based mapping
        return default_prog if default_prog else SMKContext.sanitize_tool_name(os.path.basename(log_path))

    def _parse_log_for_files(self, text: str, base_dir: str) -> List[Tuple[str, str]]:
        found = [] # List of (path, program)
        lines = [l.strip() for l in text.splitlines()]
        
        current_prog = "General"
        
        p_prog = re.compile(r"Program ([A-Z0-9_]+), Version", re.IGNORECASE)
        p_val_for = re.compile(r"Value for \S+:\s+'(.+?)'", re.IGNORECASE)
        p_file_name = re.compile(r"File name\s+\"(.+?)\"", re.IGNORECASE)
        p_log_path = re.compile(r"([a-zA-Z0-9_\-\./\\]+\.log)", re.IGNORECASE)

        for i, line in enumerate(lines):
            low = line.lower()
            
            # Identify current SMOKE program context
            m_prog = p_prog.search(line)
            if m_prog:
                current_prog = m_prog.group(1).upper()
            elif "checking log file" in low or "processing log:" in low:
                # We try to extract a path string from the line
                m_check = re.search(r"([a-zA-Z0-9_\-\./\\]+\.log)", line, re.IGNORECASE)
                if m_check:
                    log_p = m_check.group(1).strip("'\"")
                    target = log_p if os.path.isabs(log_p) else os.path.normpath(os.path.join(base_dir, log_p))
                    found_p = self._smart_isfile(target)
                    if found_p:
                        current_prog = self._identify_program_from_log_header(found_p)
                    else:
                        current_prog = SMKContext.sanitize_tool_name(os.path.basename(log_p))
                else:
                    # Fallback to simple name extraction if no path found
                    m_simple = re.search(r"([a-z0-9_\-\.]+)\.log", low, re.IGNORECASE)
                    if m_simple:
                        fname = os.path.basename(m_simple.group(1))
                        current_prog = SMKContext.sanitize_tool_name(fname)

            # Follow log files only for recursive tracking
            for m_path in p_log_path.finditer(line):
                target = m_path.group(1)
                if not os.path.isabs(target):
                    target = os.path.normpath(os.path.join(base_dir, target))
                found_p = self._smart_isfile(target)
                if found_p:
                    # Logs should always be grouped by their own header, not current context
                    p_name = self._identify_program_from_log_header(found_p)
                    found.append((found_p, p_name))
                    # If this line implies we are starting to process this log, update context
                    if any(x in low for x in ["checking", "processing", "processing log"]):
                        current_prog = p_name

            # Skip lines that explicitly mention input operations
            if any(x in low for x in ["opened for input", "old:read-only", "opened as old", "input file"]):
                continue

            # Pattern 1: SMOKE "File ... opened for output/UNKNOWN/NEW/WRITE on unit"
            # Support multi-line path discovery (path might be 1-5 lines later)
            if any(x in low for x in ["opened for output", "opened as unknown", "opened for write", "opened as new"]):
                # Look ahead for a path string
                for j in range(i + 1, min(i + 6, len(lines))):
                    candidate = lines[j].strip().strip("'\"")
                    # Remove I/O API prefixes if present
                    for prefix in ["File name", "File:", "Path:"]:
                        if candidate.lower().startswith(prefix.lower()):
                            candidate = candidate[len(prefix):].strip().strip("'\"")
                    
                    if candidate and not any(x in candidate.lower() for x in ["returning", "value for", "program", "execution"]):
                        target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                        found_p = self._smart_isfile(target)
                        if found_p:
                            found.append((found_p, current_prog))
                            break

            # Pattern 2: "File name ..." (Common for NetCDF or detailed logs)
            m_fn = p_file_name.search(line)
            if m_fn:
                context_hint = " ".join([l.lower() for l in lines[max(0, i-2):i]])
                if not any(x in context_hint for x in ["opened for input", "old:read-only", "opened as old"]):
                    path = m_fn.group(1).strip()
                    target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                    found_p = self._smart_isfile(target)
                    if found_p:
                        # If it's a log, use its header; otherwise use context
                        p_name = current_prog
                        if found_p.endswith(".log"):
                            p_name = self._identify_program_from_log_header(found_p)
                        found.append((found_p, p_name))

            # Pattern 3: "Value for VAR: 'PATH'" - Variable based discovery
            m_vf = p_val_for.search(line)
            if m_vf:
                var_match = re.search(r"Value for ([A-Z0-9_]+):", line, re.IGNORECASE)
                if var_match:
                    vname = var_match.group(1).upper()
                    if vname in SMKContext.SMKINVEN_OUTPUT_VARS or not any(x in vname for x in SMKContext.INPUT_BLACKLIST):
                        path = m_vf.group(1).strip()
                        target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                        found_p = self._smart_isfile(target)
                        if found_p:
                            # Filter using hints to avoid noise, but allow if it's in an intermed or reports dir
                            t_low = target.lower()
                            is_output_dir = any(x in t_low for x in ["/intermed", "/reports", "/outputs"])
                            if is_output_dir or any(x in vname for x in SMKContext.OUTPUT_HINTS):
                                if not any(x in t_low for x in SMKContext.PATH_BLACKLIST):
                                    found.append((found_p, current_prog))

            # Pattern 4: "WARNING: output file already exists: VAR" followed by path
            if "output file already exists" in low and (i + 1) < len(lines):
                 path = lines[i+1].strip().strip("'\"")
                 if path.startswith("/") or "." in path:
                     target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                     found_p = self._smart_isfile(target)
                     if found_p:
                         found.append((found_p, current_prog))

        return found

    def _parse_log_for_inputs(self, text: str, base_dir: str, default_prog="General") -> List[Tuple[str, str]]:
        found = []
        lines = [l.strip() for l in text.splitlines()]
        current_prog = default_prog
        p_prog = re.compile(r"Program ([A-Z0-9_]+), Version", re.IGNORECASE)
        p_file_name = re.compile(r"File name\s+\"(.+?)\"", re.IGNORECASE)
        # We capture the variable name in group 1 to filter out outputs misidentified as inputs
        p_val_for = re.compile(r"Value for (\S+):\s+'(.+?)'", re.IGNORECASE)

        for i, line in enumerate(lines):
            low = line.lower()
            
            # Unconditionally detect log files and update program context
            # We look for explicit "checking log file" or any absolute path ending in .log
            m_log = re.search(r"([a-zA-Z0-9_\-\./\\]+\.log)", line, re.IGNORECASE)
            if m_log:
                log_p = m_log.group(1).strip("'\"")
                target = log_p if os.path.isabs(log_p) else os.path.normpath(os.path.join(base_dir, log_p))
                found_p = self._smart_isfile(target)
                if found_p:
                    prog_name = self._identify_program_from_log_header(found_p)
                    found.append((found_p, prog_name))
                    # If this line implies we are about to check this log, update context
                    if "checking" in low or "processing" in low:
                        current_prog = prog_name

            m_prog = p_prog.search(line)
            if m_prog:
                current_prog = m_prog.group(1).upper()

            # Match data inputs for ANY program context
            # Pattern: Opened for input (SMOKE style: path is usually on the next line)
            if any(x in low for x in ["opened for input", "opened as old", "old:read-only", "checking log file", "input file"]):
                # First, check if the path is on the SAME line
                m_same = re.search(r"(?:input|old|only|file|log)\s+((?:/|[.]{1,2}/)[A-Za-z0-9_\-\./]+\.[A-Za-z0-9]{1,4})", line, re.IGNORECASE)
                if m_same:
                    candidate = m_same.group(1).strip("'\"")
                    target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                    found_p = self._smart_isfile(target)
                    if found_p: found.append((found_p, current_prog))
                
                # Then, Search ahead for the path (standard SMOKE behavior)
                for j in range(i + 1, min(i + 6, len(lines))):
                    # Use the original (non-lowered) line from our reconstructed lines list
                    # Wait, 'lines' are already stripped. Let's use them but carefully.
                    candidate = lines[j].strip().strip("'\"")
                    if candidate and not any(x in candidate.lower() for x in ["returning", "value for", "program", "error", "warning", "note:", "skip", "successful", "checking"]):
                        # Check if it looks like a path (allow uppercase)
                        if candidate.startswith("/") or (("/" in candidate or "." in candidate) and len(candidate) > 4):
                            target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                            found_p = self._smart_isfile(target)
                            if found_p:
                                found.append((found_p, current_prog))
                                break

            # Pattern: Successful OPEN (Alternative SMOKE format)
            if "successful open for inventory file" in low:
                 # Check current line first
                 m_same = re.search(r"file:\s+((?:/|[.]{1,2}/)[A-Za-z0-9_\-\./]+\.[A-Za-z0-9]+)", line, re.IGNORECASE)
                 path = None
                 if m_same: path = m_same.group(1)
                 elif (i + 1) < len(lines): path = lines[i+1].strip().strip("'\"")
                 
                 if path:
                     target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                     found_p = self._smart_isfile(target)
                     if found_p: found.append((found_p, current_prog))

            # Pattern: File name (often used in netCDF open messages)
            m_fn = p_file_name.search(line)
            if m_fn:
                context_hint = " ".join([l.lower() for l in lines[max(0, i-2):i]])
                if any(x in context_hint for x in ["opened for input", "opened as old", "old:read-only", "checking"]):
                    path = m_fn.group(1).strip()
                    target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                    found_p = self._smart_isfile(target)
                    if found_p: found.append((found_p, current_prog))

            # Pattern: Value for (captures variables that are files)
            m_vf = p_val_for.search(line)
            if m_vf:
                vname = m_vf.group(1).upper()
                candidate = m_vf.group(2).strip()
                
                # Filter: If the variable name or path implies this is an OUTPUT, skip it in the input scan.
                is_output_var = any(x in vname for x in SMKContext.OUTPUT_HINTS)
                t_low = candidate.lower()
                is_output_path = any(x in t_low for x in SMKContext.OUTPUT_PATH_HINTS)
                
                if not (is_output_var or is_output_path):
                    if "/" in candidate or "." in candidate:
                        target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                        found_p = self._smart_isfile(target)
                        if found_p:
                            found.append((found_p, current_prog))

        return found

    def _scan_inputs(self):
        if not self._current_script or not hasattr(self, "_var_rows"): return
        from collections import defaultdict, deque
        grouped = defaultdict(set)
        script_dir = os.path.dirname(self._current_script)

        # 1. Start log discovery
        log_queue = deque()
        scanned_logs = set()
        
        # Add main log content from the UI (the primary source of file discovery)
        main_log = self._log_text.toPlainText()
        if main_log:
            for path, prog in self._parse_log_for_inputs(main_log, script_dir):
                if path.endswith(".log"):
                    log_queue.append((path, prog))
                else:
                    grouped[prog].add(path)

        # 2. Iterative scan of the discovered logs
        max_scans = 50 
        while log_queue and max_scans > 0:
            log_p, context_prog = log_queue.popleft()
            log_p = os.path.abspath(log_p)
            if log_p in scanned_logs: continue
            scanned_logs.add(log_p)
            if not os.path.isfile(log_p) or os.path.getsize(log_p) > 20 * 1024 * 1024:
                continue
                
            max_scans -= 1
            try:
                base = os.path.dirname(log_p)
                with open(log_p, "r", encoding="utf-8", errors="ignore") as fl:
                    content = fl.read()
                    # Capture data inputs from this program log
                    for path, prog in self._parse_log_for_inputs(content, base, default_prog=context_prog):
                        if path.endswith(".log"):
                            log_queue.append((path, prog))
                        else:
                            if prog != "General" and prog != "Global/Env":
                                grouped["Global/Env"].discard(path)
                                grouped["General"].discard(path)
                            grouped[prog].add(path)
            except Exception: pass

        # 2.5 Consolidate groups: Map orphan keys (variables) into known tools or General
        from collections import defaultdict as _dd
        _tools = set(SMKContext.TOOLS) | {"Global/Env", "General"}
        _consolidated = _dd(set)
        for _prog, _paths in grouped.items():
            _canonical = _prog if _prog in _tools else SMKContext.sanitize_tool_name(_prog)
            if _canonical not in _tools:
                _canonical = "General"
            _consolidated[_canonical].update(_paths)
        grouped = _consolidated

        # 2.6 Cache check: only rebuild if set of paths OR their grouping has changed
        current_state = hash(frozenset((p, frozenset(ps)) for p, ps in grouped.items()))
        if current_state == getattr(self, "_last_input_state", None):
            return
        self._last_input_state = current_state

        # 2.6 Save UI state
        selected_path = None
        sel_items = self._input_file_tree.selectedItems()
        if sel_items:
            selected_path = sel_items[0].data(0, Qt.UserRole)

        expanded_progs = set()
        for i in range(self._input_file_tree.topLevelItemCount()):
            item = self._input_file_tree.topLevelItem(i)
            if item.isExpanded():
                expanded_progs.add(item.text(0).strip())
        scroll_pos = self._input_file_tree.verticalScrollBar().value()

        # 3. Build the tree
        self._input_file_tree.blockSignals(True)
        self._input_file_tree.clear()
        
        # Sort programs by execution appearance, Global/Env first, General last
        exec_order = self._get_log_program_order()
        _tools_progs = set(grouped.keys())
        
        _first = ["Global/Env"] if "Global/Env" in _tools_progs else []
        _ordered = [p for p in exec_order if p in _tools_progs and p not in _first]
        _unordered = sorted(p for p in _tools_progs if p not in exec_order and p not in _first and p != "General")
        _progs_sorted = _first + _ordered + _unordered + (["General"] if "General" in _tools_progs else [])

        for prog in _progs_sorted:
            if prog == "Utility/Log": continue # Don't show log files as data inputs
            fps = sorted(grouped[prog], key=lambda x: os.path.basename(x).lower())
            if not fps: continue
            prog_item = QTreeWidgetItem(self._input_file_tree, [prog])
            prog_item.setFont(0, QFont("Inter", 10, QFont.Bold))
            prog_item.setForeground(0, QBrush(QColor(PALETTE["accent2"])))
            for p in fps:
                display_name = os.path.basename(p)
                it = QTreeWidgetItem(prog_item, [display_name, p])
                it.setData(0, Qt.UserRole, p)
                it.setToolTip(0, display_name) # Show full filename on hover
                it.setForeground(1, QBrush(QColor(PALETTE["fg2"])))
                it.setFont(1, QFont("Courier New", 8))
                
                ext = os.path.splitext(p)[1].lower()
                if ext in [".ncf", ".nc"]: it.setForeground(0, QBrush(QColor(PALETTE["success"])))
                elif ext in [".txt", ".rpt", ".csv", ".lst"]: it.setForeground(0, QBrush(QColor(PALETTE["warn"])))
                elif ext == ".log": it.setForeground(0, QBrush(QColor(PALETTE["fg2"])))
                
                if p == selected_path:
                    it.setSelected(True)
                    self._input_file_tree.setCurrentItem(it)

            if prog.strip() in expanded_progs or not expanded_progs:
                prog_item.setExpanded(True)
                
        self._input_file_tree.blockSignals(False)
        self._input_file_tree.verticalScrollBar().setValue(scroll_pos)

    def _handle_input_tree_selection(self, item, column):
        path = item.data(0, Qt.UserRole)
        if path and os.path.exists(path): self._show_file_viewer(path, os.path.basename(path))

    def _on_input_tree_context_menu(self, pos):
        item = self._input_file_tree.itemAt(pos)
        if not item: return
        path = item.data(0, Qt.UserRole)
        if not path: return
        
        menu = QMenu(self)
        view_action = menu.addAction("View Content")
        
        # Add Plot action if file type is supported by smkplot
        ext = os.path.splitext(path)[1].lower()
        plottable = ext in [".ncf", ".nc", ".csv", ".txt", ".rpt", ".lst"]
        plot_action = None
        if plottable:
            plot_action = menu.addAction("Plot Emissions")
            
        copy_action = menu.addAction("Copy Path")
        
        if QT_VERSION == 6:
            action = menu.exec(self._input_file_tree.viewport().mapToGlobal(pos))
        else:
            action = menu.exec_(self._input_file_tree.viewport().mapToGlobal(pos))
        if action == view_action:
            self._show_file_viewer(path, os.path.basename(path))
        elif action == plot_action and plot_action:
            self._plot_emissions(path)
        elif action == copy_action:
            QApplication.clipboard().setText(path)

    def _scan_outputs(self):
        if not self._current_script or not hasattr(self, "_var_rows"): return
        
        from collections import defaultdict, deque
        grouped = defaultdict(set)
        patterns = {".txt", ".rpt", ".csv", ".lst", ".ncf", ".nc", ".log"}
        script_dir = os.path.dirname(self._current_script)
        log_queue = deque()
        
        # Start with the main run log (the primary source of file discovery)
        log_content = self._log_text.toPlainText()
        if log_content:
            for path, prog in self._parse_log_for_files(log_content, script_dir):
                if prog != "General" and prog != "Global/Env":
                    grouped["Global/Env"].discard(path)
                    grouped["General"].discard(path)
                grouped[prog].add(path)
                if path.endswith(".log"):
                    # Use header-based IDs for recursive scans
                    p_name = self._identify_program_from_log_header(path, default_prog=prog)
                    log_queue.append((path, p_name))

        scanned_logs = set()
        max_scans = 50 # Safeguard against deep circularities

        while log_queue and max_scans > 0:
            log_p, context_prog = log_queue.popleft()
            if log_p in scanned_logs: continue
            scanned_logs.add(log_p)
            
            if not os.path.isfile(log_p) or os.path.getsize(log_p) > 15 * 1024 * 1024:
                continue
            
            max_scans -= 1
            log_p = os.path.abspath(log_p)
            # Infer program if context is generic
            if context_prog == "General" or context_prog == "Global/Env":
                context_prog = SMKContext.sanitize_tool_name(os.path.basename(log_p))
            
            try:
                base = os.path.dirname(log_p)
                with open(log_p, "r", encoding="utf-8", errors="ignore") as fl:
                    content = fl.read()
                    # Scan log for deeper files
                    for path, prog in self._parse_log_for_files(content, base):
                        use_prog = prog if prog != "General" else context_prog
                        
                        # Always prioritize specific program groupings; remove from generic groups
                        if use_prog != "General" and use_prog != "Global/Env":
                            grouped["Global/Env"].discard(path)
                            grouped["General"].discard(path)
                        
                        grouped[use_prog].add(path)
                        if path.endswith(".log"):
                            log_queue.append((path, use_prog))
            except: pass

        # 0. Cache check: only rebuild if set of paths OR their grouping has changed
        current_state = hash(frozenset((p, frozenset(ps)) for p, ps in grouped.items()))
        if current_state == getattr(self, "_last_output_state", None):
            return
        self._last_output_state = current_state

        # 1. Save UI state (Expansion, Scroll, and Selection)
        selected_path = None
        sel_items = self._file_tree.selectedItems()
        if sel_items:
            selected_path = sel_items[0].data(0, Qt.UserRole)

        expanded_progs = set()
        for i in range(self._file_tree.topLevelItemCount()):
            item = self._file_tree.topLevelItem(i)
            if item.isExpanded():
                expanded_progs.add(item.text(0).strip())
        scroll_pos = self._file_tree.verticalScrollBar().value()

        self._file_tree.blockSignals(True)
        self._file_tree.clear()
        
        # Sort programs by log execution order; Global/Env first, General & LOGS last
        exec_order = self._get_log_program_order()
        _all_progs = set(grouped.keys())
        _first = ["Global/Env"] if "Global/Env" in _all_progs else []
        _last  = [p for p in ["General", "LOGS"] if p in _all_progs]
        _middle_set = _all_progs - set(_first) - set(_last)
        _ordered   = [p for p in exec_order if p in _middle_set]
        _unordered = sorted(p for p in _middle_set if p not in exec_order)
        progs = _first + _ordered + _unordered + _last

        for prog in progs:
            fps = sorted(grouped[prog], key=lambda x: os.path.basename(x).lower())
            if not fps: continue
            
            prog_item = QTreeWidgetItem(self._file_tree, [prog])
            prog_item.setFont(0, QFont("Inter", 10, QFont.Bold))
            prog_item.setForeground(0, QBrush(QColor(PALETTE["accent2"])))
            
            # --- Smart Shortening Logic ---
            basenames = [os.path.basename(f) for f in fps]
            lcp = ""
            if len(basenames) > 1:
                # Find common prefix
                s1, s2 = min(basenames), max(basenames)
                for i, c in enumerate(s1):
                    if i < len(s2) and c == s2[i]: lcp += c
                    else: break
                # Only use LCP if it's reasonably long and doesn't cover the whole filename
                if len(lcp) < 5 or any(len(l) == len(lcp) for l in basenames):
                    lcp = ""
            elif len(basenames) == 1:
                # For single files, try to strip the program name if it repeats
                b = basenames[0]
                if b.upper().startswith(prog):
                    lcp = b[:len(prog)]
                    if len(b) > len(lcp) and b[len(lcp)] in ["_", "."]:
                        lcp = b[:len(lcp)+1]

            for i, p in enumerate(fps):
                display_name = basenames[i]
                if lcp and display_name.startswith(lcp):
                    display_name = "..." + display_name[len(lcp):]
                
                it = QTreeWidgetItem(prog_item, [display_name, p])
                it.setData(0, Qt.UserRole, p)
                it.setToolTip(0, basenames[i]) # Show full filename on hover
                it.setForeground(1, QBrush(QColor(PALETTE["fg2"])))
                it.setFont(1, QFont("Courier New", 8))
                
                if p == selected_path:
                    it.setSelected(True)
                    self._file_tree.setCurrentItem(it)
                
                ext = os.path.splitext(p)[1].lower()
                if ext in [".ncf", ".nc"]: it.setForeground(0, QBrush(QColor(PALETTE["success"])))
                elif ext in [".txt", ".rpt"]: it.setForeground(0, QBrush(QColor(PALETTE["warn"])))
                elif ext == ".log": it.setForeground(0, QBrush(QColor(PALETTE["fg2"])))
            
            # Restore expansion state
            if prog.strip() in expanded_progs or not expanded_progs:
                prog_item.setExpanded(True)
            
        self._file_tree.blockSignals(False)
        self._file_tree.verticalScrollBar().setValue(scroll_pos)

    def _handle_tree_selection(self, item, column):
        path = item.data(0, Qt.UserRole)
        if not path or not os.path.exists(path): return
        self._show_file_viewer(path, os.path.basename(path))

    def _on_tree_context_menu(self, pos):
        item = self._file_tree.itemAt(pos)
        if not item: return
        path = item.data(0, Qt.UserRole)
        if not path: return
        menu = QMenu(self)
        view_action = menu.addAction("View Content")
        
        # Add Plot action if file type is supported by smkplot
        ext = os.path.splitext(path)[1].lower()
        plottable = ext in [".ncf", ".nc", ".csv", ".txt", ".rpt"]
        plot_action = None
        if plottable:
            plot_action = menu.addAction("Plot Emissions")
            
        copy_action = menu.addAction("Copy Path")
        
        if QT_VERSION == 6:
            action = menu.exec(self._file_tree.viewport().mapToGlobal(pos))
        else:
            action = menu.exec_(self._file_tree.viewport().mapToGlobal(pos))
        if action == view_action:
            self._show_file_viewer(path, os.path.basename(path))
        elif action == plot_action and plot_action:
            self._plot_emissions(path)
        elif action == copy_action:
            QApplication.clipboard().setText(path)

    def _plot_emissions(self, path):
        # Smart detection: Resolve smkplot location relative to this script
        smkrun_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(smkrun_dir)
        smkplot_dir = os.path.join(parent_dir, "smkplot")
        smkplot_exe = os.path.join(smkplot_dir, "smkplot.py")
        
        if not os.path.exists(smkplot_exe):
            msg = (
                "SMKPLOT visualization tool not found.\n\n"
                f"SMKRUN Location detected:\n{smkrun_dir}\n\n"
                f"Expected SMKPLOT location:\n{smkplot_exe}\n\n"
                "Relative to your current installation, you should install the SMKPLOT package here:\n"
                f"  {parent_dir}/smkplot/\n\n"
                "This ensures the 'utils' folder contains both 'smkrun' and 'smkplot' side-by-side, "
                "allowing them to communicate automatically."
            )
            QMessageBox.critical(self, "Visualization Dependency Missing", msg)
            return
            
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext not in (".ncf", ".nc"):
                cmd = [smkplot_exe, "--filepath", path, "--zoom-to-data"]
            else:
                cmd = [smkplot_exe, "--filepath", path]
            if ext not in (".ncf", ".nc"):
                env = getattr(self, "_env", {})
                griddesc = env.get("GRIDDESC", "")
                gridname = env.get("REGION_IOAPI_GRIDNAME", "")
                if griddesc:
                    cmd += ["--griddesc", griddesc]
                if gridname:
                    cmd += ["--gridname", gridname]
            # Run detached
            subprocess.Popen(cmd)
            self._status_var.setText(f"Launching Plotter: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Plot Error", f"Failed to launch smkplot:\n{str(e)}")

    def _browse_report(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File to View", "", "All Relevant (*.txt *.rpt *.csv *.lst *.ncf *.nc *.log);;All (*)")
        if path:
            self._show_file_viewer(path, os.path.basename(path))

    # ── Analysis ──
    def _analyse_log(self):
        lines = self._log_text.toPlainText().splitlines()
        errors, warnings = [], []
        for i, line in enumerate(lines, 1):
            low = line.lower()
            ext_path = None
            
            # Special detection: Error in another log file OR Log Analyzer report
            if "error detected in logfile" in low and i < len(lines):
                next_line = lines[i].strip().strip("* ").strip()
                if os.path.exists(next_line) and os.path.isfile(next_line):
                    ext_path = next_line
            elif "please review" in low and "report" in low:
                # Look ahead for a rep_logs report path
                for j in range(i, min(i + 3, len(lines))):
                    candidate = lines[j].strip().strip("* ").strip()
                    if ("rep_logs" in candidate or "/reports/log_analyzer/" in candidate) and os.path.isfile(candidate):
                        ext_path = candidate
                        break
            
            if any(w in low for w in ["error", "abort", "fatal", "sigsegv"]) or ext_path:
                text = line.strip()
                if ext_path:
                    text += f" -> {ext_path}"
                errors.append({"line": i, "text": text, "ext_path": ext_path})
            elif any(w in low for w in ["warning", "warn"]): 
                warnings.append({"line": i, "text": line.strip()})

        completed = any("normal completion" in l.lower() for l in lines)
        smoke_progs = [l.strip() for l in lines if re.search(r"\b(smkinven|spcmat|temporal|laypoint|elevpoint|smkmerge|smkreport)\b", l, re.IGNORECASE)]

        self._issues_list.clear()
        for err in errors:
            prefix = "[X] " if not err["ext_path"] else "[!] "
            it = QListWidgetItem(f"[L{err['line']}] {prefix} {err['text'][:120]}")
            it.setForeground(QBrush(QColor(PALETTE["error"])))
            it.setData(Qt.UserRole, err['line'])
            if err["ext_path"]:
                it.setData(Qt.UserRole + 1, err["ext_path"])
                it.setToolTip(f"Referenced Log: {err['ext_path']}")
            self._issues_list.addItem(it)
            
        for wrn in warnings:
            it = QListWidgetItem(f"[L{wrn['line']}] [W]   {wrn['text'][:120]}")
            it.setForeground(QBrush(QColor(PALETTE["warn"])))
            it.setData(Qt.UserRole, wrn['line'])
            self._issues_list.addItem(it)

        summary = (
            f"{'='*40}\n"
            f"  Log Analysis Summary\n"
            f"{'='*40}\n"
            f"  Total lines  : {len(lines)}\n"
            f"  Errors       : {len(errors)}\n"
            f"  Warnings     : {len(warnings)}\n"
            f"  Completion   : {'[OK]  Normal Completion' if completed else '[X]  NOT completed'}\n\n"
            f"  SMOKE programs detected:\n"
        )
        seen = set()
        for p in smoke_progs:
            m = re.search(r"\b(smkinven|spcmat|temporal|laypoint|elevpoint|smkmerge|smkreport)\b", p, re.IGNORECASE)
            if m and m.group(0).lower() not in seen:
                seen.add(m.group(0).lower())
                summary += f"    • {m.group(0)}\n"
        if errors:
            summary += f"\n  First 5 errors:\n"
            for err in errors[:5]: 
                summary += f"    [L{err['line']}] {err['text'][:80]}\n"
                if err["ext_path"]: summary += f"       -> Path: {err['ext_path']}\n"

        self._analysis_text.setPlainText(summary)
        self._notebook.setCurrentIndex(self._tab_index("  Log Analysis  "))

    def _jump_to_log_line(self, item: QListWidgetItem):
        lineno = item.data(Qt.UserRole)
        ext_path = item.data(Qt.UserRole + 1)
        
        if ext_path and os.path.exists(ext_path):
            reply = QMessageBox.question(self, "Open Reference File?", 
                                         f"This entry references an external file:\n\n{ext_path}\n\nWould you like to open it?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._show_file_viewer(ext_path, os.path.basename(ext_path))
                return

        self._notebook.setCurrentIndex(self._tab_index("  Run Log  "))
        blk = self._log_text.document().findBlockByLineNumber(lineno - 1)
        cursor = self._log_text.textCursor()
        cursor.setPosition(blk.position())
        self._log_text.setTextCursor(cursor)
        self._log_text.ensureCursorVisible()

    def closeEvent(self, event):
        if hasattr(self, "_proc") and self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
        event.accept()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SMKRUN: Interactive SMOKE Runscript Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1) Launch normally (standard root):
  ./smkrun.py

  # 2) Launch with a specific project directory in the browser:
  ./smkrun.py -d /proj/ie/proj/SMOKE/2022v2/scripts/point

  # 3) Load a specific script on startup:
  ./smkrun.py -f run_area_paved_road_2022he_cb6_22m.csh

  # 4) Load AND run a script immediately:
  ./smkrun.py -r run_pt_oilgas_onetime_2022he_cb6_22m.csh
        """
    )
    parser.add_argument("-f", "--file", help="Path to a SMOKE runscript (.csh) to load on startup")
    parser.add_argument("-d", "--dir", help="Project root directory for the script browser")
    parser.add_argument("-r", "--run", help="Load and automatically run this SMOKE runscript")
    args = parser.parse_args()

    # Determine which script to load and if it should auto-run
    initial_script = args.file
    auto_run = False
    
    if args.run:
        initial_script = args.run
        auto_run = True

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    window = SMKRunApp(initial_script=initial_script, initial_dir=args.dir, auto_run=auto_run)
    window.show()
    if QT_VERSION == 6:
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
