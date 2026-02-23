#!/bin/bash
# Author: tranhuy@email.unc.edu

# SMKRUN Setup Script
# This script sets up a local isolated Conda environment and configures the tool to use it.
# We exclusively use Conda to avoid PyQt5 XCB/libharfbuzz binding issues with system libraries.

# Configuration
VENV_DIR=".venv"
MAIN_SCRIPT="smkrun.py"
PARSER_SCRIPT="smkug_parser.py"
CONDA_EXEC="/nas/longleaf/home/tranhuy/software/pkg/miniconda3/bin/conda"

# Ensure we are in the script's directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "   SMKRUN Environment Setup"
echo "========================================================"

# 1. Check for Conda
if [ ! -f "$CONDA_EXEC" ]; then
    echo "ERROR: Conda not found at $CONDA_EXEC."
    exit 1
fi

# 2. Create Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/3] Creating virtual environment ($VENV_DIR) using conda-forge..."
    "$CONDA_EXEC" create -y -p "$SCRIPT_DIR/$VENV_DIR" -c conda-forge python=3.11 pyqt matplotlib pandas netcdf4 beautifulsoup4 pyyaml
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create Conda environment."
        exit 1
    fi
else
    echo "[1/3] Virtual environment ($VENV_DIR) already exists."
    echo "      To reinstall cleanly, remove the $VENV_DIR directory first."
fi

# 3. Setup Executables
echo "[2/3] Configuring executables..."
PYTHON_EXEC="$SCRIPT_DIR/$VENV_DIR/bin/python"

if [ ! -f "$PYTHON_EXEC" ]; then
    echo "ERROR: Python executable not found at $PYTHON_EXEC"
    exit 1
fi

# 4. Update Shebang in scripts
echo "[3/3] Updating script shebangs..."

for script in "$MAIN_SCRIPT" "$PARSER_SCRIPT"; do
    if [ -f "$script" ]; then
        # Create a temporary file with the new shebang
        echo "#!./$VENV_DIR/bin/python" > "${script}.tmp"
        
        # Append the original file content, skipping the first line (old shebang)
        sed -n '2,$p' "$script" >> "${script}.tmp"
        
        # Replace the original file
        mv "${script}.tmp" "$script"
        
        # Make executable
        chmod +x "$script"
        echo "      Updated shebang for $script to:"
        echo "      ./$VENV_DIR/bin/python"
    else
        echo "WARNING: $script not found. Skipping."
    fi
done

# 5. Final Capability Check
echo "========================================================"
echo "Checking GUI capabilities..."

# Check PyQt5
"$PYTHON_EXEC" -c "import PyQt5" &> /dev/null
PYQT_STATUS=$?

if [ $PYQT_STATUS -eq 0 ]; then
    echo "SUCCESS: Qt GUI (PyQt5) detected. Interface is ready."
else
    echo "WARNING: No GUI library (PyQt5) detected. The GUI will fail to load."
fi

# Check for Display
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    echo "NOTE: No X11/Wayland display detected. You may need to set up X-forwarding locally."
fi

echo "========================================================"
echo "Setup Complete!"
echo "Run the tool using: ./$MAIN_SCRIPT"
echo "========================================================"
