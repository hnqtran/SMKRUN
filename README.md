# SMKRUN: Interactive SMOKE Runscript Launcher

**Location:** `/proj/ie/proj/SMOKE/htran/Emission_Modeling_Platform/utils/smkrun/`  
**Author:** Huy Tran, UNC-IE (2026-02)  
**Version:** 1.0 (Ported to PyQt5)

---

## Overview

`smkrun.py` is a powerful, interactive Graphical User Interface (GUI) designed to simplify the management, execution, and analysis of SMOKE (Sparse Matrix Operator Kernel Emissions) runscripts. Built with PyQt5, it provides a 5-tab interface that allows users to browse script trees, inspect and override environment variables in real-time, execute scripts with live log streaming, and perform post-run analysis.

---

## Key Features

### 1. Script Browser
- **Dynamic Tree View:** Automatically crawls the 2022v2 emissions platform script tree.
- **Substring Filtering:** Quickly find scripts (e.g., `ptfire`, `beis`, `merge`) with a real-time search box.
- **Root Switching:** Easily change the scripts root directory directly from the UI.

### 2. Environment Variable Inspector & Validator
- **Deep Parsing:** Extracts `setenv` and `set` variables from `.csh` and `.tcsh` scripts, including recursive `$VAR` expansion.
- **Live Path Validation:** Color-coded icons indicate path status:
  - ✅ **OK:** File exists and is non-empty.
  - ⚠️ **Empty:** File exists but contains no data (comments only).
  - ❌ **Missing:** Path does not exist on disk.
  - ➖ **Non-path:** Pure string or flag.
- **Integrated Documentation:** Right-click any variable to view its official definition from the SMOKE User Manual.

### 3. In-Place Overrides & Script Patching
- **Temporary Overrides:** Double-click any variable to set a temporary value for the current run without modifying the file on disk.
- **Live Script Editing:** Edit the `.csh` source directly in the "Source" tab. Apply changes as an in-memory "patch" or save them permanently.
- **Automatic Recalculation:** All dependent paths are instantly re-validated when an override or patch is applied.

### 4. High-Performance Execution & Logging
- **Subprocess Streaming:** Runs scripts via `tcsh` in a detached process, streaming logs with syntax highlighting.
- **Smart Highlighting:** Automatically colors ERRORs (red), WARNINGs (yellow), and "Normal Completion" (green).
- **Auto-Follow:** Log view automatically scrolls to the bottom during execution.
- **Process Control:** "Stop" button sends `SIGTERM`/`SIGKILL` to the entire process group for clean termination.

### 5. Log Analysis & Post-Processing
- **Error Navigation:** Jump directly to the line in the log where an error or warning occurred.
- **Linked Log Detection:** Automatically detects and allows viewing of external logs referenced within the main log.
- **Output Auto-Discovery:** Scans environment variables and run logs to find generated files (`.ncf`, `.txt`, `.rpt`, `.csv`, `.log`).
- **SMKPLOT Integration:** Right-click detected output files to visualize them using the `smkplot.py` tool.

---

## Installation

The tool requires a specific Python environment to handle PyQt5 and NetCDF dependencies reliably.

1. **Run the Setup Script:**
   ```bash
   ./install.sh
   ```
   *This script creates a local Conda environment in `.venv/` and configures the `smkrun.py` shebang.*

2. **Dependencies:**
   - Python 3.11+
   - PyQt5
   - PyYAML
   - netCDF4 / xarray (for NetCDF metadata viewing)
   - Matplotlib / Pandas (for visualization)

---

## How to Run

### Desktop / GUI Mode
If you are on a system with X11 forwarding or a local display:
```bash
./smkrun.py
```

### Remote / SSH Mode
If running over SSH, ensure you have X-Forwarding enabled (`ssh -X` or `-Y`). The tool includes workarounds for common OpenGL/FBConfig warnings over SSH.

---

## Interface Guide

### Tab 1: Variables
- **Inspect** all variables defined in the script.
- **Double-click** the "Raw Value" or "Expanded Path" column to set an **Override**.
- **Right-click** a variable to **Define Variable** (show documentation) or **View/Edit File** if the variable points to a text file.

### Tab 2: Source
- View the syntax-highlighted code of the runscript.
- Click **Edit Script** to make manual changes.
- Click **Finish Editing** to apply changes as a temporary patch for the next run.

### Tab 3: Run Log
- Monitor the execution progress.
- Toggle **Follow Log** to stay at the bottom of the output.
- Click **Analyse Current Log** to populate the Log Analysis tab.

### Tab 4: Output Files
- Scans for files created during the run or defined in the environment.
- **Double-click** a file to open the internal viewer.
- **Right-click** a file to **Plot Emissions** (requires `smkplot` install) or **Copy Absolute Path**.

### Tab 5: Log Analysis
- View a summary of Errors and Warnings.
- Click an entry in the "Issues List" to jump to the relevant log line.
- See a summary of which SMOKE programs were detected in the log.

---

## Directory Structure

```
smkrun/
├── smkrun.py               # Main GUI Application
├── install.sh             # Environment setup script
├── smoke_env_vars.yaml     # Metadata for core SMOKE variables
└── emf_env_vars.yaml       # Metadata for platform-specific variables
```
