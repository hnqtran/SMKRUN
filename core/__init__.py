"""
smkrun core package
===================
Modular backend for SMKRUN interactive web platform.
"""

from .state import STATE, STATE_LOCK, broadcast_log
from .analysis import (
    smart_isfile,
    identify_program_from_log_header,
    extract_paths_from_log,
    get_log_program_order,
    scan_files_io,
    analyze_log_text,
    load_env_docs
)
from .runner import run_script_worker, launch_smkplot_app
from .server import SMKRunHandler, ThreadedHTTPServer

__all__ = [
    "STATE",
    "STATE_LOCK",
    "broadcast_log",
    "smart_isfile",
    "identify_program_from_log_header",
    "extract_paths_from_log",
    "get_log_program_order",
    "scan_files_io",
    "analyze_log_text",
    "load_env_docs",
    "run_script_worker",
    "launch_smkplot_app",
    "SMKRunHandler",
    "ThreadedHTTPServer"
]
