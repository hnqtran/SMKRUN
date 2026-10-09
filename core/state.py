"""
smkrun core state management
============================
Thread-safe execution and process state for SMKRUN web platform.
"""

import queue
import subprocess
import threading
from typing import Dict, List, Optional

# Root path fallback from smkrun core
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from smkrun import SCRIPTS_ROOT

class State:
    scripts_root: str = SCRIPTS_ROOT
    current_script: Optional[str] = None
    script_override_content: Optional[str] = None
    overrides: Dict[str, str] = {}
    var_rows: List[Dict] = []
    env_context: Dict[str, str] = {}
    
    # Process management
    proc: Optional[subprocess.Popen] = None
    is_running: bool = False
    log_history: List[str] = []
    log_subscribers: List[queue.Queue] = []
    exit_code: Optional[int] = None

STATE = State()
STATE_LOCK = threading.Lock()

def broadcast_log(line: str):
    """Broadcast log line to all active SSE subscribers and append to log history."""
    with STATE_LOCK:
        STATE.log_history.append(line)
        # Cap in-memory history at 50,000 lines
        if len(STATE.log_history) > 50000:
            STATE.log_history = STATE.log_history[-40000:]
        for q in list(STATE.log_subscribers):
            try:
                q.put_nowait(line)
            except Exception:
                pass
