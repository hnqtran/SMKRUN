# SMKRUN: Interactive SMOKE Runscript Launcher

**Location:** `/proj/ie/proj/SMOKE/htran/Emission_Modeling_Platform/utils/smkrun/`  
**Contact:** Huy Tran, UNC-IE  

---

## What is SMKRUN?

Logging into a cluster and manually digging through hundreds of lines of `.csh` SMOKE scripts can be tedious and error-prone. `smkrun.py` was built to take the guesswork out of running SMOKE. 

It's a GUI-based wrapper that lets you browse your project tree, inspect and validate your environment variables before you hit "Run," and analyze your logs in real-time. Whether you're debugging a tricky Fire or O&G run or just need to quickly verify if your input files exist, this tool is designed to save you time.

---

## Core Workflow Features

### 1. Smart Environment Inspection
Instead of running a script just to find out a path is wrong, SMKRUN parses your `.csh` files (following `source` and `setenv` commands) and gives you live status icons:
*   ✅ **Green**: The file exists and is ready.
*   ⚠️ **Yellow**: The file exists but appears to be empty or just comments.
*   ❌ **Red**: The path is missing. 

You can **double-click any row** to override a variable on the fly for testing, without actually modifying your original script.

### 2. Live Tabbed Interface
*   **Variables**: A searchable table of every environment variable detected in the script.
*   **Source View**: Direct access to the script code with syntax highlighting. You can even make quick edits and "save to file" or just "patch in-memory" for the current run.
*   **Execution Log**: Real-time streaming of the SMOKE run. It automatically scrolls and highlights **ERRORS** and **WARNINGS** so you don't miss them.
*   **I/O Files**: Automatically groups your input and output files by SMOKE program (Smkinven, Spcmat, Smkmerge, etc.), making it easy to find where your data is actually going.

### 3. Integrated Analysis & Plotting
*   **Error Navigation**: The Log Analysis tab summarizes issues. Clicking an error in the list jumps your log view directly to that specific line.
*   **One-Click Plotting**: See a NetCDF output you want to check? Right-click it in the Output Files tab and select **Plot Emissions** to launch `smkplot` immediately with the correct grid settings pre-filled.

---

## Getting Started

### Installation
We use a local absolute virtual environment to ensure the tool always has the right libraries regardless of your system-wide Python setup.

1.  **Run the setup script**:
    ```bash
    ./install.sh
    ```
    This creates a `.venv` folder, installs requirements, and fixes the script shebangs.

2.  **Update the tool**:
    If we've pushed new fixes to the repository, just run:
    ```bash
    ./update.csh
    ```
    This will pull the latest code and refresh your environment.

### Basic Usage
The easiest way to start is by navigating to the tool directory and running it directly:
```bash
./smkrun.py
```

You can also point it at a specific script or directory from the command line:
```bash
# Start browsing a specific sector
./smkrun.py -d /proj/ie/proj/SMOKE/htran/12LISTOS/2022he_cb6_22m/scripts/nonpoint

# Load a specific script immediately
./smkrun.py -f Annual_rwc_12US1_2022he_cb6_22m.csh
```

---

## Troubleshooting Tips
*   **X11 Forwarding**: Since this is a GUI, you need to connect to the cluster with `-X` or `-Y` (e.g., `ssh -Y user@server`).
*   **Missing Documentation**: If you see a variable that doesn't have a description on right-click, it will be saved to `undefined_variable.yaml`. Feel free to update the internal YAML files if you want to add permanent documentation for your sector's specific variables.
