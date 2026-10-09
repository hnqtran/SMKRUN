# SMKRUN: SMOKE Runscript Execution and Analysis Platform

**Location:** `/proj/ie/proj/SMOKE/htran/Emission_Modeling_Platform/utils/smkrun/`  
**Maintainer:** Huy Tran, UNC-IE  

---

## Overview

`SMKRUN` is an execution wrapper and diagnostic environment for SMOKE modeling runscripts (`.csh`, `.tcsh`). It automates the static analysis of environment variables, provides runtime variable overrides without altering source files, monitors script execution in real-time, and indexes intermediate and final dataset inputs and outputs.

---

## Core Features

### 1. Static Environment Analysis and Path Validation
`SMKRUN` parses C-shell script hierarchies, traversing nested `source` calls and `setenv` directives to extract all runtime parameters:
* **File Existence Verification:**
  * **Valid:** The target path exists and contains non-trivial data.
  * **Empty / Comments Only:** The file exists on disk but contains zero bytes or solely comments.
  * **Missing:** The resolved filesystem path does not exist.
* **Non-Destructive Overrides:** Environment variables can be modified in-place for a specific execution run without writing changes back to the underlying script files.

### 2. Execution Monitoring and Diagnostic Parsing
* **Streaming Log Capture:** Captures `stdout` and `stderr` asynchronously from child processes, applying real-time regex filters to index errors, warnings, and standard termination flags (`Normal Completion`).
* **Source Code Editor:** Provides syntax-highlighted runscript inspection, allowing in-memory script patching or persistent disk updates.
* **Program-Level I/O Accounting:** Tracks file handles across SMOKE core modules (`Smkinven`, `Spcmat`, `Temporal`, `Laypoint`, `Smkmerge`, `Smkreport`), categorizing artifacts into structured input/output inventories.

### 3. Integrated Post-Processing and Plotting
* **Diagnostic Navigation:** Error and warning indices link directly to corresponding line offsets in execution logs.
* **Emissions Visualization:** Invokes `smkplot` directly from identified NetCDF outputs, initializing grid parameters, map projections, and variable lists automatically from dataset metadata.

---

## Installation and Maintenance

The platform utilizes a dedicated Python virtual environment:

1. **Setup Environment:**
   ```bash
   ./install.sh
   ```
   Initializes the local `.venv`, installs necessary dependencies, and configures binary entrypoints.

2. **Synchronize Repository:**
   ```bash
   ./update.csh
   ```
   Pulls recent platform updates and refreshes dependencies.

---

## Usage

### 1. Native Desktop GUI (Primary, Requires X11)
The primary execution mode provides the complete feature set, including full-fidelity GIS visualization via `smkplot`:
```bash
./smkrun.py
```

Command-line parameters:
```bash
# Set script browser root directory:
./smkrun.py -d /proj/ie/proj/SMOKE/htran/smoke_example_case_v3/2022he_cb6_22m/scripts

# Pre-load a specific runscript:
./smkrun.py -f Annual_rwc_12US1_2022he_cb6_22m.csh

# Pre-load and immediately execute:
./smkrun.py -r Annual_rwc_12US1_2022he_cb6_22m.csh
```

### 2. Web Interface (Headless / Zero-X11, `--html`)
Designed for headless compute nodes or high-latency network connections where X11 forwarding is suboptimal:
```bash
# Launch web interface (default port 8080):
./smkrun.py --html

# Specify port, host, or script directory:
./smkrun.py --html -p 8080 --host 127.0.0.1 -d /path/to/scripts
```

> **Feature Scope Notice (Experimental):**
> * The Web/HTML interface is an **experimental deployment**.
> * Emissions visualization within the browser provides lightweight previews (gridded heatmaps, 24-hour time series, and vertical layer profiles).
> * **Visualization features are reduced compared to the native desktop interface.** Comprehensive GIS capabilities—such as auxiliary shapefile overlay stacking, interactive spatial polygon subsetting, custom color palette configurations, and advanced multi-pollutant comparison tools—are exclusively supported in the native X11 interface (`smkplot`).

---

## Remote Access via SSH Port Forwarding

When running the web interface on remote servers or HPC compute clusters, bind a local port from the client machine to access the service:

### Direct Server Connection (Linux, macOS, MobaXterm Local Terminal)
Forward local port `8080` to the remote service:
```bash
ssh -L 8080:localhost:8080 username@remote_host
```
*(AWS EC2 with key pair: `ssh -i /path/to/key.pem -L 8080:localhost:8080 ec2-user@ec2-ip`)*

### Multi-Hop Cluster Access (SLURM / PBS Compute Nodes)
When executing jobs on an internal cluster node behind a login node:
1. Determine the assigned compute node identifier:
   ```bash
   hostname
   # Output example: c0123
   ```
2. Initialize the service on the compute node:
   ```bash
   ./smkrun.py --html
   ```
3. Open a tunnel from the local workstation through the cluster gateway:
   ```bash
   ssh -L 8080:c0123:8080 username@login.cluster.edu
   ```
4. Access the application in any modern web browser at:
   ```text
   http://localhost:8080
   ```

---

## Operational Notes
* **X11 Forwarding Configuration:** When utilizing `./smkrun.py` without `--html`, ensure the SSH client is connected with `-X` or `-Y` flags.
* **Port Availability:** In multi-tenant environments where port `8080` is allocated, `smkrun` scans subsequent sequential ports (up to `8100`). Adjust the local forwarding port parameter (`-L <local_port>:localhost:<assigned_port>`) accordingly.
* **Environment Variable Definitions:** Unrecognized configuration keys are logged to `undefined_variable.yaml` for administrative documentation and schema expansion.
