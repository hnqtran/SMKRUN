#!/bin/csh -f
# Author: tranhuy@email.unc.edu

# SMKRUN Update Script
# This script forcefully pulls the latest updates from the GitHub repository and reinstalls the environment.
# WARNING: This will discard any local modifications made to tracked files.

# Navigate to the directory where this script is located
set script_path = `readlink -f "$0"`
set script_dir = `dirname "$script_path"`
cd "$script_dir"

echo "========================================================"
echo "   SMKRUN Update Script"
echo "========================================================"

echo "WARNING: This will discard any local changes to tracked files."
echo -n "Are you sure you want to continue? (y/n) "
set reply = $<

if ( "$reply" != "y" && "$reply" != "Y" ) then
    echo "Update aborted by user."
    exit 1
endif

echo "[1/3] Discarding local modifications..."
git reset --hard origin/main
if ( $status != 0 ) then
    echo "ERROR: Failed to reset local branch. Are you connected to the repository?"
    exit 1
endif

echo "[2/3] Pulling latest code from origin/main..."
git pull origin main
if ( $status != 0 ) then
    echo "ERROR: Failed to pull updates."
    exit 1
endif

echo "[3/3] Re-running installation to update hooks and shebangs..."
if ( -x "./install.sh" ) then
    ./install.sh
else
    echo "ERROR: install.sh not found or not executable. Please run it manually."
    exit 1
endif

echo "========================================================"
echo "Update Complete!"
echo "========================================================"
