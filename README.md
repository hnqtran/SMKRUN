# SMKRUN: Interactive SMOKE Runscript Launcher

**Location:** `/proj/ie/proj/SMOKE/htran/Emission_Modeling_Platform/utils/smkrun/`  
**Author:** Huy Tran, UNC-IE (2026-02)  
**Version:** 1.0 (Qt6/Qt5 Dynamic Shim)

---

## Overview

`smkrun.py` is a powerful, interactive Graphical User Interface (GUI) designed to simplify the management, execution, and analysis of SMOKE (Sparse Matrix Operator Kernel Emissions) runscripts. Built with a dynamic Qt shim, it automatically detects and uses **PySide6 (Qt6)** or **PyQt5 (Qt5)**. It provides a multi-tab interface for browsing script trees, inspecting/overriding environment variables, executing scripts with live log streaming, and performing integrated log analysis.

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

The tool uses a standard nested Python `venv` to ensure zero-conflict operation with system libraries.

1. **Run the Setup Script:**
   ```bash
   ./install.sh
   ```
   *This script creates an isolated virtual environment in `.venv/`, installs dependencies via `pip`, and patches the `smkrun.py` shebang with an absolute path to the local interpreter.*

2. **Dependencies (Automated):**
   - **PySide6** (Primary) or **PyQt5** (Fallback)
   - **PyYAML**, **netCDF4**, **matplotlib**, **pandas**, **beautifulsoup4**

---

## Usage (CLI)

`smkrun` supports several command-line arguments to streamline your workflow:

| Argument | Description |
| :--- | :--- |
| `-f, --file [PATH]` | Load a specific `.csh` runscript immediately on startup. |
| `-d, --dir [PATH]` | Set the **Script Browser** root to a specific project directory. |
| `-r, --run [PATH]` | Load a script AND **automatically start execution** without confirmation. |
| `-h, --help` | Display full help and example usage patterns. |

### Examples:
```bash
# Launch with a specific project directory in the browser
./smkrun.py -d /proj/ie/proj/SMOKE/2022v2/scripts/point

# Load a specific script and wait for user input
./smkrun.py -f run_area_paved_road.csh

# Load and RUN a script immediately (Automated Mode)
./smkrun.py -r run_pt_oilgas_onetime.csh
```

---

## Interface Guide

### Tab 1: Variables
- **Inspect** all variables. **Double-click** "Raw Value" to set an **Override**.
- **Right-click** a variable to show documentation or view the target file.

### Tab 2: Source
- View the syntax-highlighted code of the runscript.
- Click **Edit Script** to make manual changes.
- Click **Finish Editing** to apply changes as a temporary patch for the next run.

### Tab 3: Run Log
- Real-time streamed output with error/warning auto-coloring.

### Tab 4: Input/Output Files
- Scans for discovered inputs and outputs. Right-click files to **Plot Emissions** via `smkplot`.

### Tab 5: Log Analysis
- Summary of Errors and Warnings with "Click-to-Jump" navigation into the log.

---

## Directory Structure

```
smkrun/
├── smkrun.py               # Main GUI Application
├── install.sh             # Environment setup script
├── smoke_env_vars.yaml     # Metadata for core SMOKE variables
└── emf_env_vars.yaml       # Metadata for platform-specific variables
```
