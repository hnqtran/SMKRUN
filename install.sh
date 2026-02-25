#!/bin/bash
# Author: tranhuy@email.unc.edu

# SMKRUN Setup Script
# This script sets up a local isolated Python environment using standard venv.
# We use venv instead of Conda to minimize external dependencies.

# Configuration
VENV_DIR=".venv"
MAIN_SCRIPT="smkrun.py"
PARSER_SCRIPT="smkug_parser.py"

# Ensure we are in the script's directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "   SMKRUN Environment Setup (Python Venv)"
echo "========================================================"

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Please install Python 3."
    exit 1
fi

# 2. Create Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/3] Creating virtual environment ($VENV_DIR)..."
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment."
        exit 1
    fi
else
    echo "[1/3] Virtual environment ($VENV_DIR) already exists."
    echo "      To reinstall cleanly, remove the $VENV_DIR directory first."
fi

# 3. Install Dependencies
echo "[2/3] Installing dependencies from requirements.txt..."
./$VENV_DIR/bin/pip install --upgrade pip setuptools wheel
if [ -f "requirements.txt" ]; then
    ./$VENV_DIR/bin/pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install requirements."
        exit 1
    fi
else
    echo "ERROR: requirements.txt not found."
    exit 1
fi

# 4. Update Shebang in scripts
echo "[3/3] Updating script shebangs..."

# Target scripts that or intended for direct execution
SCRIPTS_TO_PATCH=("$MAIN_SCRIPT" "$PARSER_SCRIPT" "utils_workflow.py" "utils_qarun.py" "emf_env_parser.py")

for script in "${SCRIPTS_TO_PATCH[@]}"; do
    if [ -f "$script" ]; then
        # Create a temporary file with the new shebang
        echo "#!$SCRIPT_DIR/$VENV_DIR/bin/python" > "${script}.tmp"
        
        # Check if the first line is currently a shebang
        FIRST_LINE=$(head -n 1 "$script")
        if [[ "$FIRST_LINE" == \#!* ]]; then
            # Append ignoring the old shebang
            sed -n '2,$p' "$script" >> "${script}.tmp"
        else
            # Append the whole file
            cat "$script" >> "${script}.tmp"
        fi
        
        # Replace the original file
        mv "${script}.tmp" "$script"
        
        # Make executable
        chmod +x "$script"
        echo "      Fixed shebang for: $script"
    else
        echo "      Skipping (not found): $script"
    fi
done

# 5. Final Capability Check
echo "========================================================"
echo "Checking GUI capabilities..."

PYTHON_EXEC="$SCRIPT_DIR/$VENV_DIR/bin/python"

# Check PyQt5
"$PYTHON_EXEC" -c "import PyQt5" &> /dev/null
PYQT_STATUS=$?

if [ $PYQT_STATUS -eq 0 ]; then
    echo "SUCCESS: Qt GUI (PyQt5) detected. Interface is ready."
else
    echo "WARNING: No GUI library (PyQt5) detected. The GUI will fail to load."
    echo "         You may need to install system dependencies for Qt (libX11, libxcb, etc.)"
fi

# Check for Display
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    echo "NOTE: No X11/Wayland display detected. You may need to set up X-forwarding locally."
fi

echo "========================================================"
echo "Setup Complete!"
echo "Run the tool using: ./$MAIN_SCRIPT"
echo "========================================================"
