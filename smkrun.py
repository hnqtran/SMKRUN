#!./.venv/bin/python
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

# ── X11/SSH Forwarding Workarounds ─────────────
# Mute benign warnings about missing OpenGL FBConfigs and XDG runtime folders over SSH
os.environ["QT_XCB_GL_INTEGRATION"] = "none"
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = f"/tmp/runtime-{os.environ.get('USER', 'run')}"
os.makedirs(os.environ["XDG_RUNTIME_DIR"], exist_ok=True)

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem, 
                             QTabWidget, QLabel, QPushButton, QLineEdit, QComboBox, 
                             QTextEdit, QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView,
                             QFileDialog, QMessageBox, QAbstractItemView, QListWidget, 
                             QListWidgetItem, QInputDialog, QDialog, QDialogButtonBox,
                             QToolTip, QMenu, QStackedWidget, QPlainTextEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QFont, QTextCursor, QTextCharFormat, QBrush, QTextBlockFormat, QCursor, QSyntaxHighlighter

# ── Constants ─────────────────────────────────────────────────────────────────
SCRIPTS_ROOT = (
    "/proj/ie/proj/SMOKE/htran/12LISTOS/2022he_cb6_22m/scripts"
)
DIR_DEFS_CANDIDATES = [
    "directory_definitions.csh",
    "directory_definitions_12US2.csh",
]
SHELL = "/bin/tcsh"

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
        "UAM2ROADS", "RAW2EA", "PRESMOK", "BELDTOT"
    ]
    
    # Variables that suggest a file is an INPUT (to be ignored in output scans)
    INPUT_BLACKLIST = [
        "INPUT", "INV", "XREF", "MAP", "PROF", "FAC", "SRG", "GEO", "MET",
        "CONFIG", "DESC", "INC", "GRIDDESC", "SRGDESC", "SRGPRO", "TPRO",
        "GPRO", "BCON", "ICON", "DATES", "ROOT", "DIR"
    ]
    
    # Variables that strongly suggest a file is an OUTPUT or LOG
    OUTPUT_HINTS = ["OUT", "REPOUT", "PLAY", "INLN", "LOG", "NCF", "PREMERGED", "MRG"]
    
    # Paths to ignore during output scans
    PATH_BLACKLIST = [
        "/ge_dat/", "/input/", "/inventory/", "/srg/", "/crossref/",
        "/profiles/", "/scripts/", "/smoke/"
    ]

    @staticmethod
    def sanitize_tool_name(name: str) -> str:
        name_upper = name.upper()
        for tool in SMKContext.TOOLS:
            if tool in name_upper:
                return tool
        return name.split('_')[0].upper() if '_' in name else name_upper

# ── Helpers ─────────────────────────────────────────────────

_VAR_PAT = re.compile(r"\$\{?([A-Za-z0-9_]+)\}?")

def parse_tcsh_all_env_vars(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.exists(path): return out
    p_env = re.compile(r"^\s*setenv\s+([A-Za-z0-9_]+)\s+(.+?)\s*$")
    p_set = re.compile(r"^\s*set\s+([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$")
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            m = p_env.match(line) or p_set.match(line)
            if not m: continue
            var, val_part = m.group(1), m.group(2).strip()
            try:
                tokens = shlex.split(val_part, posix=True)
                out[var] = tokens[0] if tokens else ""
            except Exception:
                out[var] = val_part.strip('"')
    return out

def recursive_expand(val: str, env: Dict[str, str], depth: int = 12) -> str:
    result = val
    for _ in range(depth):
        hits = _VAR_PAT.findall(result)
        if not hits: break
        for v in set(hits):
            if v in env:
                result = re.sub(rf"\${{?{v}}}?", env[v], result)
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

def parse_script_vars(script_path: str, overrides: Dict[str, str] = None, raw_content: str = None) -> List[Dict]:
    dir_defs = find_dir_defs(script_path)
    env: Dict[str, str] = parse_tcsh_all_env_vars(dir_defs) if dir_defs else {}
    rows: List[Dict] = []
    p_env = re.compile(r"^\s*setenv\s+([A-Za-z0-9_]+)\s+(.+?)\s*$")
    p_set = re.compile(r"^\s*set\s+([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$")

    if raw_content is not None:
        lines = raw_content.splitlines()
    else:
        try:
            with open(script_path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except Exception:
            lines = []

    for lineno, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        stripped = line.lstrip()
        if stripped.startswith("#") or not stripped: continue
        m = p_env.match(line) or p_set.match(line)
        if not m: continue
        var = m.group(1)
        val_part = m.group(2).strip()
        try:
            tokens = shlex.split(val_part, posix=True)
            raw_val = tokens[0] if tokens else ""
        except Exception:
            raw_val = val_part.strip('"')
        
        if overrides and var in overrides:
            raw_val = overrides[var]

        env[var] = recursive_expand(raw_val, env)
        expanded = env[var]

        status = "nopath"
        if re.match(r"^(/|\.\.?/)", expanded):
            if glob.glob(expanded):
                status = "empty" if is_functionally_empty(expanded) else "ok"
            else:
                status = "missing"

        kind = "setenv" if p_env.match(line) else "set"
        rows.append(dict(var=var, value=raw_val, expanded=expanded,
                         kind=kind, lineno=lineno, status=status))
    return rows

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
    new_line = pyqtSignal(str)
    done = pyqtSignal(int)

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
        
        # Toolbar
        tbar = QHBoxLayout()
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
        layout.addLayout(tbar)
        
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Courier New", 11))
        self.text.setLineWrapMode(QTextEdit.NoWrap)
        self.text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {PALETTE['panel']};
                color: {PALETTE['fg']};
                border: 1px solid {PALETTE['border']};
                padding: 10px;
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
                        self.text.append("\n\n... [File truncated for performance] ...")
        except Exception as e:
            self.text.setPlainText(f"[Error reading file: {path}\n\n{e}]")
            
        layout.addWidget(self.text)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SMOKE Run Launcher · 2022v2 Platform (PyQt5)")
        self.resize(1600, 950)
        
        self._scripts_root = SCRIPTS_ROOT
        self._proc = None
        self._running = False
        self._current_script: Optional[str] = None
        self._var_rows: List[Dict] = []
        self._overrides: Dict[str, str] = {}
        self._script_override_content: Optional[str] = None
        
        self.log_signal = LogSignal()
        self.log_signal.new_line.connect(self._append_log)
        self.log_signal.done.connect(self._run_done)
        
        self._env_docs = self._load_env_docs()
        
        self._apply_theme()
        self._build_ui()
        self._populate_script_tree(self._scripts_root)
        
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
        self._filter_edit.setPlaceholderText("Filter scripts...")
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
        
        # Toolbar
        tbar = QHBoxLayout()
        btn_refresh = QPushButton("Refresh Output Files")
        btn_refresh.clicked.connect(self._scan_outputs)
        tbar.addWidget(btn_refresh)
        
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_report)
        tbar.addWidget(btn_browse)
        
        tbar.addStretch()
        layout.addLayout(tbar)
        
        list_header = QLabel("DETECTED OUTPUTS (Grouped by SMOKE Program)")
        list_header.setFont(QFont("Inter", 10, QFont.Bold))
        list_header.setStyleSheet(f"color: {PALETTE['accent2']};")
        layout.addWidget(list_header)
        
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
        
        tbar = QHBoxLayout()
        btn_refresh = QPushButton("Refresh Input Files")
        btn_refresh.clicked.connect(self._scan_inputs)
        tbar.addWidget(btn_refresh)
        
        tbar.addStretch()
        layout.addLayout(tbar)
        
        list_header = QLabel("DETECTED INPUTS (Focus: SMKINVEN)")
        list_header.setFont(QFont("Inter", 10, QFont.Bold))
        list_header.setStyleSheet(f"color: {PALETTE['accent2']};")
        layout.addWidget(list_header)
        
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

    def _populate_script_tree(self, root_dir: str):
        self._tree.clear()
        if not os.path.isdir(root_dir): return
        self._walk_dir(root_dir, self._tree.invisibleRootItem())
        
    def _walk_dir(self, path: str, parent: QTreeWidgetItem):
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError: return
        for entry in entries:
            if entry.name.startswith("."): continue
            if entry.is_dir():
                item = QTreeWidgetItem(parent, [f"[+] {entry.name}"])
                item.setData(0, Qt.UserRole, entry.path)
                self._walk_dir(entry.path, item)
            elif entry.name.endswith((".csh", ".tcsh")):
                item = QTreeWidgetItem(parent, [f"    {entry.name}"])
                item.setData(0, Qt.UserRole, entry.path)

    def _change_scripts_root(self):
        d = QFileDialog.getExistingDirectory(self, "Select Scripts Root Directory", self._scripts_root)
        if d:
            self._scripts_root = d
            self._filter_edit.setText("")
            self._populate_script_tree(self._scripts_root)

    def _filter_tree(self):
        q = self._filter_edit.text().lower()
        if not q or q == "filter scripts...":
            self._populate_script_tree(self._scripts_root)
            return
        self._tree.clear()
        for root, dirs, files in os.walk(self._scripts_root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for f in sorted(files):
                if q in f.lower() and f.endswith((".csh", ".tcsh")):
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
        self._current_script = path
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
        self._notebook.setCurrentIndex(0)

    def _load_vars(self, path: str):
        self._var_rows = parse_script_vars(path)
        self._overrides.clear()
        self._refresh_var_tree()
        self._lbl_overrides.setText("No overrides set.")

    def _reload_vars(self):
        if self._current_script: self._load_vars(self._current_script)

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
                
                menu.exec_(self._var_table.viewport().mapToGlobal(pos))
                
    def _show_var_definition(self, var_key, desc):
        dlg = DefinitionDialog(var_key, desc, self)
        dlg.exec_()
        
    def _show_file_viewer(self, path, var_name):
        dlg = FileViewerDialog(path, var_name, self)
        dlg.show() # Non-modal so user can keep it open
        
    def apply_override(self, var, value):
        self._overrides[var] = value
        self._var_rows = parse_script_vars(self._current_script, self._overrides, self._script_override_content)
        self._refresh_var_tree()
        self._check_paths()
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
        if dlg.exec_() == QDialog.Accepted:
            if dlg.cleared:
                self._overrides.pop(var, None)
            else:
                nv = dlg.entry.text().strip()
                if nv: self._overrides[var] = nv
                elif var in self._overrides: self._overrides.pop(var, None)
            
            # Cascade re-parse all paths dynamically
            self._var_rows = parse_script_vars(self._current_script, self._overrides, self._script_override_content)
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
            self._var_rows = parse_script_vars(self._current_script, self._overrides, self._script_override_content)
            self._refresh_var_tree()
            self._check_paths()

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
            self._check_paths() # Auto check paths logic
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
    def _run_script(self):
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
        reply = QMessageBox.question(self, "Confirm", msg, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No: return

        self._clear_log()
        self._running = True
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lbl_run_status.setText("[*]  Running...")
        self._lbl_run_status.setStyleSheet(f"color: {PALETTE['warn']};")
        self._status_var.setText(f"Running: {name}")
        self._notebook.setCurrentIndex(2)

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
                    env=env, cwd=script_dir, universal_newlines=True, bufsize=1,
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
        if ".log" in low:
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

    # ── Outputs ──

    def _parse_log_for_files(self, text: str, base_dir: str) -> List[Tuple[str, str]]:
        found = [] # List of (path, program)
        lines = [l.strip() for l in text.splitlines()]
        
        current_prog = "General"
        
        p_prog = re.compile(r"Program ([A-Z0-9_]+), Version", re.IGNORECASE)
        p_val_for = re.compile(r"Value for \S+:\s+'(.+?)'", re.IGNORECASE)
        p_file_name = re.compile(r"File name\s+\"(.+?)\"", re.IGNORECASE)
        p_log_path = re.compile(r"((?:/|[./]+[a-zA-Z0-9_\-]+/)[a-zA-Z0-9_\-\./]+\.log)", re.IGNORECASE)

        for i, line in enumerate(lines):
            low = line.lower()
            
            # Identify current SMOKE program context
            m_prog = p_prog.search(line)
            if m_prog:
                current_prog = m_prog.group(1).upper()
            elif "checking log file" in low or "processing log:" in low:
                m_check = re.search(r"([a-z0-9_]+)\.log", low, re.IGNORECASE)
                if m_check:
                    current_prog = SMKContext.sanitize_tool_name(m_check.group(1))

            # Follow log files only for recursive tracking
            for m_path in p_log_path.finditer(line):
                target = m_path.group(1)
                if not os.path.isabs(target):
                    target = os.path.normpath(os.path.join(base_dir, target))
                if os.path.isfile(target):
                    found.append((os.path.abspath(target), current_prog))

            # Skip lines that explicitly mention input operations
            if any(x in low for x in ["opened for input", "old:read-only", "opened as old", "input file"]):
                continue

            # Pattern 1: SMOKE "File ... opened for output/UNKNOWN/NEW/WRITE on unit"
            # Support multi-line path discovery (path might be 1-5 lines later)
            if any(x in low for x in ["opened for output", "opened as unknown", "opened for write", "opened as new"]):
                # Look ahead for a path string
                for j in range(i + 1, min(i + 6, len(lines))):
                    candidate = lines[j].strip().strip("'\"")
                    if candidate and not any(x in candidate.lower() for x in ["returning", "value for", "program", "execution"]):
                        # Check if it looks like a file path
                        if candidate.startswith("/") or "." in candidate or "/" in candidate:
                            target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                            if os.path.isfile(target):
                                found.append((os.path.abspath(target), current_prog))
                                break

            # Pattern 2: "File name ..." (Common for NetCDF or detailed logs)
            m_fn = p_file_name.search(line)
            if m_fn:
                # Check preceding lines to Ensure it's not an input file
                context_hint = " ".join([l.lower() for l in lines[max(0, i-2):i]])
                if not any(x in context_hint for x in ["opened for input", "old:read-only", "opened as old"]):
                    path = m_fn.group(1).strip()
                    target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                    if os.path.isfile(target):
                        found.append((os.path.abspath(target), current_prog))

            # Pattern 3: "Value for VAR: 'PATH'" - Variable based discovery
            m_vf = p_val_for.search(line)
            if m_vf:
                var_match = re.search(r"Value for ([A-Z0-9_]+):", line, re.IGNORECASE)
                if var_match:
                    vname = var_match.group(1).upper()
                    if not any(x in vname for x in SMKContext.INPUT_BLACKLIST):
                        path = m_vf.group(1).strip()
                        target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                        if os.path.isfile(target):
                            # Filter using hints to avoid noise, but allow if it's in an intermed or reports dir
                            t_low = target.lower()
                            is_output_dir = any(x in t_low for x in ["/intermed", "/reports", "/outputs"])
                            if is_output_dir or any(x in vname for x in SMKContext.OUTPUT_HINTS):
                                if not any(x in t_low for x in SMKContext.PATH_BLACKLIST):
                                    found.append((os.path.abspath(target), current_prog))

            # Pattern 4: "WARNING: output file already exists: VAR" followed by path
            if "output file already exists" in low and (i + 1) < len(lines):
                 path = lines[i+1].strip().strip("'\"")
                 if path.startswith("/") or "." in path:
                     target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                     if os.path.isfile(target):
                         found.append((os.path.abspath(target), current_prog))

        return found

    def _parse_log_for_inputs(self, text: str, base_dir: str, default_prog="General") -> List[Tuple[str, str]]:
        found = []
        lines = [l.strip() for l in text.splitlines()]
        current_prog = default_prog
        p_prog = re.compile(r"Program ([A-Z0-9_]+), Version", re.IGNORECASE)
        p_file_name = re.compile(r"File name\s+\"(.+?)\"", re.IGNORECASE)
        p_val_for = re.compile(r"Value for \S+:\s+'(.+?)'", re.IGNORECASE)

        for i, line in enumerate(lines):
            low = line.lower()
            
            # Unconditionally detect log files and update program context
            # We look for explicit "checking log file" or any absolute path ending in .log
            m_log = re.search(r"((?:/|[./]+[a-zA-Z0-9_\-]+/)[a-z0-9_\-\./]+\.log)", low, re.IGNORECASE)
            if m_log:
                log_p = m_log.group(1).strip("'\"")
                target = log_p if os.path.isabs(log_p) else os.path.normpath(os.path.join(base_dir, log_p))
                if os.path.isfile(target):
                    prog_name = SMKContext.sanitize_tool_name(os.path.basename(log_p))
                    found.append((os.path.abspath(target), prog_name))
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
                m_same = re.search(r"(?:input|old|only|file|log)\s+((?:/|[.]{1,2}/)[a-z0-9_\-\./]+\.[a-z0-9]{1,4})", low, re.IGNORECASE)
                if m_same:
                    # Extract from the original 'line' to preserve case
                    m_orig = re.search(r"(?:input|old|only|file|log)\s+((?:/|[.]{1,2}/)[A-Za-z0-9_\-\./]+\.[A-Za-z0-9]{1,4})", line, re.IGNORECASE)
                    candidate = m_orig.group(1).strip("'\"") if m_orig else m_same.group(1).strip("'\"")
                    target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                    if os.path.isfile(target): found.append((os.path.abspath(target), current_prog))
                
                # Then, Search ahead for the path (standard SMOKE behavior)
                for j in range(i + 1, min(i + 6, len(lines))):
                    # Use the original (non-lowered) line from our reconstructed lines list
                    # Wait, 'lines' are already stripped. Let's use them but carefully.
                    candidate = lines[j].strip().strip("'\"")
                    if candidate and not any(x in candidate.lower() for x in ["returning", "value for", "program", "error", "warning", "note:", "skip", "successful", "checking"]):
                        # Check if it looks like a path (allow uppercase)
                        if candidate.startswith("/") or (("/" in candidate or "." in candidate) and len(candidate) > 4):
                            target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                            if os.path.isfile(target):
                                found.append((os.path.abspath(target), current_prog))
                                break

            # Pattern: Successful OPEN (Alternative SMOKE format)
            if "successful open for inventory file" in low:
                 # Check current line first
                 m_same = re.search(r"file:\s+((?:/|[.]{1,2}/)[a-z0-9_\-\./]+\.[a-z0-9]+)", low, re.IGNORECASE)
                 path = None
                 if m_same: path = m_same.group(1)
                 elif (i + 1) < len(lines): path = lines[i+1].strip().strip("'\"")
                 
                 if path:
                     target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                     if os.path.isfile(target): found.append((os.path.abspath(target), current_prog))

            # Pattern: File name (often used in netCDF open messages)
            m_fn = p_file_name.search(line)
            if m_fn:
                # To avoid capturing output files as inputs, check if recent context implies an input open
                # In many SMOKE logs, "File name" is used for both. We'll check the preceding lines.
                context_hint = " ".join([l.lower() for l in lines[max(0, i-2):i]])
                if any(x in context_hint for x in ["opened for input", "opened as old", "old:read-only", "checking"]):
                    path = m_fn.group(1).strip()
                    target = path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
                    if os.path.isfile(target): found.append((os.path.abspath(target), current_prog))

            # Pattern: Value for (captures variables that are files)
            m_vf = p_val_for.search(line)
            if m_vf:
                candidate = m_vf.group(1).strip()
                if "/" in candidate or "." in candidate:
                    target = candidate if os.path.isabs(candidate) else os.path.normpath(os.path.join(base_dir, candidate))
                    if os.path.isfile(target):
                        # Filter out common output-looking variables if needed, 
                        # but usually logs only print "Value for" for inputs.
                        found.append((os.path.abspath(target), current_prog))

        return found

    def _scan_inputs(self):
        if not self._current_script or not hasattr(self, "_var_rows"): return
        from collections import defaultdict, deque
        grouped = defaultdict(set)
        script_dir = os.path.dirname(self._current_script)

        # 1. Start log discovery
        log_queue = deque()
        scanned_logs = set()
        
        # A. Add main log content from the UI (it might contain paths to other logs or direct inputs)
        main_log = self._log_text.toPlainText()
        if main_log:
            for path, prog in self._parse_log_for_inputs(main_log, script_dir):
                if path.endswith(".log"):
                    log_queue.append((path, prog))
                else:
                    grouped[prog].add(path)

        # B. Add any log files found in variables
        log_hints = ["LOG", "OUTLOG", "S_LOG", "LOGFILE", "SUM", "REP", "M_LOG", "I_LOG", "T_LOG", "INLOG"]
        possible_roots = {script_dir}
        
        for row in self._var_rows:
            vname = row["var"].upper()
            p = row["expanded"]
            if not p: continue
            
            # Directory variables: catch anything that looks like a path
            if os.path.isdir(p):
                possible_roots.add(p)
                # If it's a root variable, maybe its parent is also interesting
                parent = os.path.dirname(p)
                if len(parent) > 5: possible_roots.add(parent)

            if (p.endswith(".log") or any(h in vname for h in log_hints)) and os.path.isfile(p):
                prog = SMKContext.sanitize_tool_name(os.path.basename(p))
                log_queue.append((p, prog))

        # C. Proactively search for logs in all discovered roots
        # We'll do a shallow recursive search (depth 2) to find all .log files
        for r in list(possible_roots):
            if not os.path.isdir(r): continue
            try:
                for root, dirs, files in os.walk(r):
                    # Limit depth to avoid massive scans
                    depth = root[len(r):].count(os.sep)
                    if depth > 4: 
                        dirs[:] = [] # Stop recursion
                        continue
                    
                    for f in files:
                        if f.endswith(".log"):
                            lp = os.path.join(root, f)
                            p_name = SMKContext.sanitize_tool_name(f)
                            log_queue.append((lp, p_name))
            except: pass

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
                            grouped[prog].add(path)
            except Exception: pass

        # 3. Build the tree
        self._input_file_tree.blockSignals(True)
        self._input_file_tree.clear()
        
        for prog in sorted(grouped.keys()):
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

            prog_item.setExpanded(True)
        self._input_file_tree.blockSignals(False)

    def _handle_input_tree_selection(self, item, column):
        path = item.data(0, Qt.UserRole)
        if path and os.path.exists(path): self._show_file_viewer(path, os.path.basename(path))

    def _on_input_tree_context_menu(self, pos):
        item = self._input_file_tree.itemAt(pos)
        if not item: return
        path = item.data(0, Qt.UserRole)
        if not path: return
        
        from PyQt5.QtWidgets import QMenu
        menu = QMenu()
        view_action = menu.addAction("View Content")
        
        # Add Plot action if file type is supported by smkplot
        ext = os.path.splitext(path)[1].lower()
        plottable = ext in [".ncf", ".nc", ".csv", ".txt", ".rpt", ".lst"]
        plot_action = None
        if plottable:
            plot_action = menu.addAction("Plot Emissions")
            
        copy_action = menu.addAction("Copy Path")
        
        action = menu.exec_(self._input_file_tree.viewport().mapToGlobal(pos))
        if action == view_action:
            self._show_file_viewer(path, os.path.basename(path))
        elif action == plot_action and plot_action:
            self._plot_emissions(path)
        elif action == copy_action:
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(path)

    def _scan_outputs(self):
        if not self._current_script or not hasattr(self, "_var_rows"): return
        
        from collections import defaultdict, deque
        grouped = defaultdict(set)
        
        patterns = {".txt", ".rpt", ".csv", ".lst", ".ncf", ".nc", ".log"}
        script_dir = os.path.dirname(self._current_script)

        # Filter: strictly only include if it looks like an output
        output_var_hints = ["OUT", "REPOUT", "PLAY", "INLN", "LOG", "NCF", "PREMERGED", "MRG"]
        input_var_blacklist = ["INPUT", "INV", "XREF", "MAP", "PROF", "FAC", "SRG", "GEO", "MET", "CONFIG", "DESC", "INC", "GRIDDESC", "SRGDESC", "SRGPRO", "TPRO", "GPRO", "BCON", "ICON", "DATES", "ROOT", "DIR"]

        for row in self._var_rows:
            vname = row["var"].upper()
            if any(x in vname for x in SMKContext.INPUT_BLACKLIST): continue
            
            # Must look like an output or log
            if not any(x in vname for x in SMKContext.OUTPUT_HINTS): continue

            p = row["expanded"]
            if not p or len(p) < 4: continue 
            if os.path.isfile(p):
                # Path-based check: ignore script and staging dirs
                p_low = p.lower()
                if any(x in p_low for x in SMKContext.PATH_BLACKLIST):
                    continue
                    
                ext = os.path.splitext(p)[1].lower()
                if ext in patterns:
                    grouped["Global/Env"].add(os.path.abspath(p))

        # 2. Iterative scan of logs (BFS approach)
        log_queue = deque()
        
        # Start with the main run log
        log_content = self._log_text.toPlainText()
        if log_content:
            for path, prog in self._parse_log_for_files(log_content, script_dir):
                grouped[prog].add(path)
                if path.endswith(".log"):
                    log_queue.append((path, prog))

        # Add any logs found in Env vars to the scan queue
        for p in list(grouped["Global/Env"]):
            if p.endswith(".log"):
                log_queue.append((p, "General"))

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
                        
                        # If we previously had this path in Global/Env or General, move it to the specific prog
                        if path in grouped["Global/Env"]: grouped["Global/Env"].remove(path)
                        if path in grouped["General"]: grouped["General"].remove(path)
                        
                        grouped[use_prog].add(path)
                        if path.endswith(".log"):
                            log_queue.append((path, use_prog))
            except: pass

        self._file_tree.blockSignals(True)
        self._file_tree.clear()
        
        # Sort programs by name, but Global/Env first
        progs = sorted(grouped.keys())
        if "Global/Env" in progs:
            progs.remove("Global/Env")
            progs = ["Global/Env"] + progs
            
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
                
                ext = os.path.splitext(p)[1].lower()
                if ext in [".ncf", ".nc"]: it.setForeground(0, QBrush(QColor(PALETTE["success"])))
                elif ext in [".txt", ".rpt"]: it.setForeground(0, QBrush(QColor(PALETTE["warn"])))
                elif ext == ".log": it.setForeground(0, QBrush(QColor(PALETTE["fg2"])))
            
            prog_item.setExpanded(True)
            
        self._file_tree.blockSignals(False)

    def _handle_tree_selection(self, item, column):
        path = item.data(0, Qt.UserRole)
        if not path or not os.path.exists(path): return
        self._show_file_viewer(path, os.path.basename(path))

    def _on_tree_context_menu(self, pos):
        item = self._file_tree.itemAt(pos)
        if not item: return
        path = item.data(0, Qt.UserRole)
        if not path: return
        
        from PyQt5.QtWidgets import QMenu
        menu = QMenu()
        view_action = menu.addAction("View Content")
        
        # Add Plot action if file type is supported by smkplot
        ext = os.path.splitext(path)[1].lower()
        plottable = ext in [".ncf", ".nc", ".csv", ".txt", ".rpt"]
        plot_action = None
        if plottable:
            plot_action = menu.addAction("Plot Emissions")
            
        copy_action = menu.addAction("Copy Path")
        
        action = menu.exec_(self._file_tree.viewport().mapToGlobal(pos))
        if action == view_action:
            self._show_file_viewer(path, os.path.basename(path))
        elif action == plot_action and plot_action:
            self._plot_emissions(path)
        elif action == copy_action:
            from PyQt5.QtWidgets import QApplication
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
            # Run detached
            subprocess.Popen([smkplot_exe, "--filepath", path])
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
            
            # Special detection: Error in another log file
            if "error detected in logfile" in low and i < len(lines):
                next_line = lines[i].strip().strip("* ").strip()
                if os.path.exists(next_line) and os.path.isfile(next_line):
                    ext_path = next_line
            
            if any(w in low for w in ["error", "abort", "fatal", "sigsegv"]): 
                errors.append({"line": i, "text": line.strip(), "ext_path": ext_path})
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
                if err["ext_path"]: summary += f"       -> Linked: {os.path.basename(err['ext_path'])}\n"

        self._analysis_text.setPlainText(summary)
        self._notebook.setCurrentIndex(5)

    def _jump_to_log_line(self, item: QListWidgetItem):
        lineno = item.data(Qt.UserRole)
        ext_path = item.data(Qt.UserRole + 1)
        
        if ext_path and os.path.exists(ext_path):
            reply = QMessageBox.question(self, "Open Reference Log?", 
                                         f"This error references an external log file:\n\n{ext_path}\n\nWould you like to open it?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._show_file_viewer(ext_path, os.path.basename(ext_path))
                return

        self._notebook.setCurrentIndex(2)
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
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    window = SMKRunApp()
    window.show()
    sys.exit(app.exec_())
