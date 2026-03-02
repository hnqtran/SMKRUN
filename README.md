# SMKRUN: Interactive SMOKE Runscript Launcher

**Location:** `/proj/ie/proj/SMOKE/htran/Emission_Modeling_Platform/utils/smkrun/`  
**Author:** Huy Tran, UNC-IE (2026-02)  
**Version:** 1.1 (Qt6/Qt5 Dynamic Shim)

---

## Overview

`smkrun.py` is a powerful, interactive GUI designed to simplify the management, execution, and analysis of SMOKE (Sparse Matrix Operator Kernel Emissions) runscripts. Built with a dynamic Qt shim, it automatically detects and uses **PySide6 (Qt6)** or **PyQt5 (Qt5)**. It provides a six-tab interface for browsing script trees, inspecting and overriding environment variables, executing scripts with real-time log streaming, discovering input/output files, and performing integrated log analysis.

---

## Key Features

### 1. Script Browser
- **Dynamic Tree View:** Crawls the configured emissions platform script tree for `.csh`/`.tcsh` files.
- **Substring Filtering:** Find scripts in real time (e.g., `ptfire`, `beis`, `merge`).
- **Root Switching:** Change the scripts root directory directly from the UI.

### 2. Environment Variable Inspector & Validator
- **Deep Parsing:** Extracts `setenv` and `set` variables from scripts, including recursive `$VAR` expansion and `source`-following.
- **Live Path Validation:** Color-coded icons indicate file status:
  - `[OK]`  File exists and is non-empty.
  - `[W]`   File exists but is functionally empty (comments only).
  - `[X]`   Path does not exist on disk.
  - `[-]`   Pure string or flag — not a file path.
- **Override Display:** Overridden variables show the new value in **both** the Raw Value and Expanded Path columns, highlighted in blue.
- **Integrated Documentation:** Right-click any variable to view its SMOKE/EMF definition. Unknown variables are automatically logged to `undefined_variable.yaml`.

### 3. In-Place Overrides & Script Patching
- **Temporary Overrides:** Double-click any row to set a temporary value for the next run without modifying the file on disk.
- **Live Script Editing:** Edit the `.csh` source directly in the Source tab. Apply changes as an in-memory "patch" or save them permanently to disk.
- **Automatic Recalculation:** All dependent paths are instantly re-validated after any override or patch.
- **Cancel Safety:** Entering edit mode enables Save/Reset/Cancel buttons; canceling correctly disables all three.

### 4. High-Performance Execution & Logging
- **Subprocess Streaming:** Runs scripts via `tcsh` in a detached background thread, streaming logs in real time without freezing the UI.
- **Smart Highlighting:** Colors ERRORs (red), WARNINGs (yellow), and "Normal Completion" (green) automatically.
- **Auto-Follow:** Log view scrolls to the bottom during execution.
- **Process Control:** Stop button sends `SIGTERM` then `SIGKILL` (after 2 s) to the entire process group.
- **Override Injection:** If overrides or a source patch are active, a temporary `.csh` file is created in the same directory, the original variable lines are commented out (preserving context), and the subprocess env dict carries the new values.

### 5. Input Files Tab
- **Immediate Detection:** Scans environment variable rows on script load — no run required.
- **Multi-Guard Classification:** A variable is only classified as an input if:
  1. Its name is **not** in `SMKINVEN_OUTPUT_VARS`
  2. Its name does **not** contain an `OUTPUT_HINTS` fragment
  3. Its resolved path is **not** inside a known output directory (`/intermed/`, `/outputs/`, etc.)
  4. Its name **does** contain an `INPUT_BLACKLIST` term (e.g., `INV`, `XREF`, `SRG`, `MET`)
- **Log-Driven Supplement:** After a run, log files are also scanned for "opened for input" / "opened as old" patterns to add further files.
- **Grouped by Program:** Files appear under the SMOKE program inferred from the variable name.

### 6. Output Files Tab
- **Dual Source Detection:** Scans both environment variable names (output hints) and run log files (BFS across discovered logs).
- **SMKINVEN Awareness:** Variables like `AREA`, `POINT`, `MOBILE`, `ASCIIDUMP`, and `REPINVEN` are correctly identified as outputs even though some contain input-blacklisted substrings.
- **LOGS Group:** All `.log` files — regardless of which program produced them — are consolidated under a single **LOGS** group after scanning.
- **Grouped by Program:** Non-log output files are grouped by the SMOKE program inferred from log context or variable name.
- **Right-click Actions:** View file content, copy path, or launch **smkplot** for visualization.

### 7. SMKPLOT Integration
- **One-click plotting:** Right-click any detected output file → "Plot Emissions" launches `smkplot.py` as a detached process.
- **Automatic grid arguments:** For non-NetCDF files (`.txt`, `.rpt`, `.csv`, etc.), `--griddesc` and `--gridname` are resolved from the current script's `$GRIDDESC` and `$REGION_IOAPI_GRIDNAME` variables and passed automatically.
- **Zoom to data:** `--zoom-to-data true` is always passed so plots are immediately framed on valid data.

### 8. Log Analysis Tab
- **Error Navigation:** Click any issue to jump to the exact line in the Run Log tab.
- **Linked Log Detection:** Automatically detects and allows viewing of external logs referenced in the run log.
- **Summary Panel:** Displays  total error/warning counts and "Normal Completion" status.

---

## Installation

The tool uses a nested Python `venv` for zero-conflict operation with system libraries.

1. **Run the Setup Script:**
   ```bash
   ./install.sh
   ```
   *Creates `.venv/`, installs dependencies, and patches the `smkrun.py` shebang with the local interpreter path.*

2. **Dependencies (automated by `install.sh`):**
   - **PySide6** (primary) or **PyQt5** (fallback)
   - **PyYAML**, **netCDF4**, **matplotlib**, **pandas**

---

## Usage (CLI)

| Argument | Description |
| :--- | :--- |
| `-f, --file PATH` | Load a specific `.csh` runscript on startup. |
| `-d, --dir PATH` | Set the Script Browser root to a specific directory. |
| `-r, --run PATH` | Load a script **and automatically start execution** without confirmation. |
| `-h, --help` | Display full help and examples. |

### Examples
```bash
# Launch with a specific project directory in the browser
./smkrun.py -d /proj/ie/proj/SMOKE/2022v2/scripts/point

# Load a specific script and wait for user confirmation
./smkrun.py -f run_area_paved_road.csh

# Load and RUN a script immediately (automated mode)
./smkrun.py -r run_pt_oilgas_onetime.csh
```

---

## Interface Guide

### Tab 1 — Variables
- **Inspect** all `setenv`/`set` variables with live path-status icons.
- **Double-click** any row to set a temporary override for that variable.
- **Right-click** to view documentation, view/edit the target file, or copy its path.
- Active overrides are highlighted in blue; the override count is shown at the bottom.

### Tab 2 — Source
- Syntax-highlighted tcsh source of the loaded runscript.
- **Edit Script** → enters edit mode (Save to File / Reset Script / Cancel Edit all become active).
- **Finish Editing** → applies current content as an in-memory patch without writing to disk.
- **Save to File** → permanently overwrites the original `.csh` file on disk.
- **Cancel Edit** → discards edits, reverts to last applied state, disables all edit buttons.

### Tab 3 — Run Log
- Real-time streamed output from the `tcsh` subprocess.
- Run status label shows `[*] Running…`, `[OK] Completed OK`, or `[X] Exit <code>`.

### Tab 4 — Input Files
- Populated immediately on script load from environment variable analysis.
- Supplemented by log scanning after a run completes.
- Files are grouped by the SMOKE program associated with the variable.

### Tab 5 — Output Files
- Populated on script load (env-var pass) and updated after every run (log BFS).
- All log files appear under a dedicated **LOGS** group.
- Right-click any file to **View Content**, **Plot Emissions** (via smkplot), or **Copy Path**.

### Tab 6 — Log Analysis
- Click **Analyse Current Log** to extract errors, warnings, and completion status.
- Click any item in the Errors & Warnings list to jump directly to that line in the Run Log tab.

---

## Directory Structure

```
smkrun/
├── smkrun.py                # Main GUI Application
├── install.sh               # Environment setup script
├── smoke_env_vars.yaml      # Documentation for core SMOKE environment variables
├── emf_env_vars.yaml        # Documentation for platform-specific EMF variables
└── undefined_variable.yaml  # Auto-generated: variables seen but not yet documented
```
