/**
 * workspace.js - Script source editing, tabs, file discovery, chunked viewer, and execution
 */

function toggleEditSource() {
  isEditingSource = !isEditingSource;
  updateSourceUIState();
}

function updateSourceUIState() {
  const ed = document.getElementById('source-editor');
  ed.readOnly = !isEditingSource;
  ed.style.border = isEditingSource ? "1px solid var(--accent)" : "1px solid var(--border)";
  document.getElementById('btn-edit-src').textContent = isEditingSource ? "Stop Editing" : "Edit Script";
  document.getElementById('btn-save-src').disabled = !isEditingSource;
  document.getElementById('btn-patch-src').disabled = !isEditingSource;
  document.getElementById('btn-revert-src').disabled = !isEditingSource;
}

async function saveSourceFile() {
  if (!confirm("Overwrite script permanently on disk? (A .bak copy will be created)")) return;
  const content = document.getElementById('source-editor').value;
  const res = await fetch('/api/source/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: content })
  });
  const data = await res.json();
  if (data.error) alert(data.error);
  else {
    alert(data.message || "Saved successfully");
    currentVars = data.vars;
    renderVars();
    originalSource = content;
    isEditingSource = false;
    updateSourceUIState();
  }
}

async function applySourcePatch() {
  const content = document.getElementById('source-editor').value;
  const res = await fetch('/api/source/patch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: content })
  });
  const data = await res.json();
  currentVars = data.vars;
  renderVars();
  document.getElementById('src-status-badge').textContent = "● Script Patched in memory";
  document.getElementById('src-status-badge').style.color = "var(--warn)";
  isEditingSource = false;
  updateSourceUIState();
}

function revertSource() {
  document.getElementById('source-editor').value = originalSource;
  isEditingSource = false;
  updateSourceUIState();
}

function switchTab(tabId) {
  localStorage.setItem('smkrun_active_tab', tabId);
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => {
    c.classList.remove('active');
    c.style.display = 'none';
  });
  
  const tabHeaders = Array.from(document.querySelectorAll('.tab'));
  const activeHeader = tabHeaders.find(t => t.getAttribute('onclick') && t.getAttribute('onclick').includes(tabId));
  if (activeHeader) activeHeader.classList.add('active');

  const target = document.getElementById(tabId);
  if (target) {
    target.classList.add('active');
    target.style.display = (tabId === 'tab-source') ? 'flex' : 'block';
  }

  if (tabId === 'tab-outputs' || tabId === 'tab-inputs') refreshFileIO();
  if (tabId === 'tab-analysis') refreshAnalysis();
}

async function refreshFileIO() {
  const res = await fetch('/api/files/io');
  const data = await res.json();

  // Outputs
  const outBox = document.getElementById('outputs-container');
  outBox.innerHTML = "";
  if (!data.outputs || data.outputs.length === 0) {
    outBox.innerHTML = '<div style="padding: 20px; color: var(--fg2); text-align: center;">No output files discovered yet. Run the script to produce reports and NetCDF files.</div>';
  } else {
    data.outputs.forEach(progGrp => {
      const wrap = document.createElement('div');
      wrap.className = 'file-tree-prog';
      wrap.innerHTML = `
        <div class="file-tree-prog-header">
          <span>⚙ ${progGrp.program}</span>
          <span style="font-size: 0.75rem; color: var(--fg2);">${progGrp.files.length} output(s)</span>
        </div>
        <div class="file-tree-list"></div>
      `;
      const list = wrap.querySelector('.file-tree-list');
      progGrp.files.forEach(f => {
        const row = document.createElement('div');
        row.className = 'file-tree-item';
        const isLogFile = f.is_log || f.path.toLowerCase().endsWith('.log');
        let badge;
        if (isLogFile) badge = '<span class="file-badge badge-log">Log</span>';
        else if (f.is_netcdf) badge = '<span class="file-badge badge-nc">NetCDF</span>';
        else if (f.is_report) badge = '<span class="file-badge badge-rep">Report</span>';
        else if (f.is_csv) badge = '<span class="file-badge badge-nc" style="background: rgba(14, 165, 233, 0.15); color: #38bdf8; border-color: rgba(14, 165, 233, 0.3);">CSV</span>';
        else badge = '<span class="file-badge badge-log">Data</span>';

        const isPlottable = !isLogFile && (f.is_netcdf || f.is_csv || f.is_report || (f.path.toLowerCase().endsWith('.rpt')));
        row.style.cursor = "pointer";
        row.innerHTML = `
          <div style="display: flex; gap: 8px; align-items: center; overflow: hidden; width: 100%;">
            ${badge}
            <span style="font-weight: 500; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="${f.path}">${f.name}</span>
            <span style="font-size: 0.72rem; color: var(--fg2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">(${f.path})</span>
          </div>
        `;
        row.onclick = () => viewFileContent(f.path);
        row.oncontextmenu = (e) => {
          e.preventDefault();
          const items = [
            { label: "View Content", icon: "📄", action: () => viewFileContent(f.path) }
          ];
          if (isPlottable) {
            items.push({ label: "Plot Emissions", icon: "📊", action: () => launchSmkplot(f.path) });
          }
          items.push({ type: "separator" });
          items.push({ label: "Copy Path", icon: "📋", action: () => copyToClipboard(f.path) });
          showContextMenu(e, items);
        };
        list.appendChild(row);
      });
      outBox.appendChild(wrap);
    });
  }

  // Inputs
  const inBox = document.getElementById('inputs-container');
  inBox.innerHTML = "";
  if (!data.inputs || data.inputs.length === 0) {
    inBox.innerHTML = '<div style="padding: 20px; color: var(--fg2); text-align: center;">No input files detected in current log session.</div>';
  } else {
    data.inputs.forEach(progGrp => {
      const wrap = document.createElement('div');
      wrap.className = 'file-tree-prog';
      wrap.innerHTML = `
        <div class="file-tree-prog-header">
          <span>⚙ ${progGrp.program}</span>
          <span style="font-size: 0.75rem; color: var(--fg2);">${progGrp.files.length} input(s)</span>
        </div>
        <div class="file-tree-list"></div>
      `;
      const list = wrap.querySelector('.file-tree-list');
      progGrp.files.forEach(f => {
        const row = document.createElement('div');
        row.className = 'file-tree-item';
        const isLogFile = f.is_log || f.path.toLowerCase().endsWith('.log');
        let badge;
        if (isLogFile) badge = '<span class="file-badge badge-log">Log</span>';
        else if (f.is_netcdf) badge = '<span class="file-badge badge-nc">NetCDF</span>';
        else if (f.is_csv) badge = '<span class="file-badge badge-nc" style="background: rgba(14, 165, 233, 0.15); color: #38bdf8; border-color: rgba(14, 165, 233, 0.3);">CSV</span>';
        else if (f.is_report) badge = '<span class="file-badge badge-rep">Report</span>';
        else badge = '<span class="file-badge badge-log">Data</span>';

        const isPlottable = !isLogFile && (f.is_netcdf || f.is_csv || f.is_report || (f.path.toLowerCase().endsWith('.rpt')));
        row.style.cursor = "pointer";
        row.innerHTML = `
          <div style="display: flex; gap: 8px; align-items: center; overflow: hidden; width: 100%;">
            ${badge}
            <span style="font-weight: 500; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="${f.path}">${f.name}</span>
            <span style="font-size: 0.72rem; color: var(--fg2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">(${f.path})</span>
          </div>
        `;
        row.onclick = () => viewFileContent(f.path);
        row.oncontextmenu = (e) => {
          e.preventDefault();
          const items = [
            { label: "View Content", icon: "📄", action: () => viewFileContent(f.path) }
          ];
          if (isPlottable) {
            items.push({ label: "Plot Emissions", icon: "📊", action: () => launchSmkplot(f.path) });
          }
          items.push({ type: "separator" });
          items.push({ label: "Copy Path", icon: "📋", action: () => copyToClipboard(f.path) });
          showContextMenu(e, items);
        };
        list.appendChild(row);
      });
      inBox.appendChild(wrap);
    });
  }
}

let activeFileIsEditMode = false;
let activeFileIsNetCDF = false;

// ── File Content Viewer / Editor (Chunked 2MB) ──
async function viewFileContent(filePath, offset = 0) {
  activeViewFile = filePath;
  activeViewOffset = offset;
  activeFileIsEditMode = false;
  activeFileIsNetCDF = false;

  const titleEl = document.getElementById('file-modal-title');
  if (titleEl) titleEl.textContent = "File: " + filePath;
  const statusEl = document.getElementById('file-save-status');
  if (statusEl) statusEl.textContent = "";

  const contentBox = document.getElementById('file-modal-content');
  const editorBox = document.getElementById('file-modal-editor');
  const editToggleBtn = document.getElementById('btn-file-edit-toggle');
  const saveBtn = document.getElementById('btn-file-save');

  if (contentBox) contentBox.style.display = 'block';
  if (editorBox) editorBox.style.display = 'none';
  if (editToggleBtn) {
    editToggleBtn.textContent = "✏️ Edit";
    editToggleBtn.style.display = 'inline-block';
  }
  if (saveBtn) saveBtn.style.display = 'none';

  document.getElementById('file-modal').classList.add('open');

  const res = await fetch(`/api/file/view?path=${encodeURIComponent(filePath)}&offset=${offset}`);
  const data = await res.json();
  if (data.error) {
    if (contentBox) contentBox.textContent = data.error;
    if (editToggleBtn) editToggleBtn.style.display = 'none';
    return;
  }
  activeViewTotal = data.total_size || 0;
  activeFileIsNetCDF = !!data.is_netcdf;

  const sizeMB = (activeViewTotal / (1024 * 1024)).toFixed(2);
  const sizeEl = document.getElementById('file-modal-size');
  if (sizeEl) sizeEl.textContent = `Size: ${sizeMB} MB | Offset: ${(offset / (1024*1024)).toFixed(2)} MB`;
  
  if (contentBox) contentBox.textContent = data.content;
  if (editorBox) editorBox.value = data.content;

  document.getElementById('btn-file-prev').disabled = offset <= 0;
  document.getElementById('btn-file-next').disabled = data.is_netcdf || (offset + (data.chunk_size || 0) >= activeViewTotal);

  if (activeFileIsNetCDF || activeViewTotal > 2 * 1024 * 1024) {
    if (editToggleBtn) {
      editToggleBtn.disabled = true;
      editToggleBtn.title = activeFileIsNetCDF ? "Binary NetCDF files cannot be edited as text" : "Editing large files over 2MB chunk is disabled";
    }
  } else {
    if (editToggleBtn) {
      editToggleBtn.disabled = false;
      editToggleBtn.title = "Edit file content";
    }
  }

  const plotBtn = document.getElementById('btn-file-plot');
  const lower = filePath.toLowerCase();
  const isPlottable = lower.endsWith('.ncf') || lower.endsWith('.nc') || lower.endsWith('.csv') || lower.endsWith('.rpt') || lower.endsWith('.txt') || lower.endsWith('.lst');
  if (plotBtn) {
    plotBtn.style.display = isPlottable ? 'inline-block' : 'none';
  }
}

function toggleFileEditMode() {
  activeFileIsEditMode = !activeFileIsEditMode;
  const contentBox = document.getElementById('file-modal-content');
  const editorBox = document.getElementById('file-modal-editor');
  const editToggleBtn = document.getElementById('btn-file-edit-toggle');
  const saveBtn = document.getElementById('btn-file-save');

  if (activeFileIsEditMode) {
    if (contentBox) contentBox.style.display = 'none';
    if (editorBox) {
      editorBox.style.display = 'block';
      editorBox.value = contentBox ? contentBox.textContent : "";
      editorBox.focus();
    }
    if (editToggleBtn) editToggleBtn.textContent = "👁️ View Mode";
    if (saveBtn) saveBtn.style.display = 'inline-block';
  } else {
    if (contentBox) {
      contentBox.style.display = 'block';
      if (editorBox) contentBox.textContent = editorBox.value;
    }
    if (editorBox) editorBox.style.display = 'none';
    if (editToggleBtn) editToggleBtn.textContent = "✏️ Edit";
    if (saveBtn) saveBtn.style.display = 'none';
  }
}

async function saveFileContentFromModal() {
  if (!activeViewFile) return;
  const editorBox = document.getElementById('file-modal-editor');
  const statusEl = document.getElementById('file-save-status');
  if (!editorBox) return;

  const newContent = editorBox.value;
  if (statusEl) statusEl.textContent = "Saving...";

  try {
    const res = await fetch('/api/file/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: activeViewFile, content: newContent })
    });
    const data = await res.json();
    if (data.error) {
      if (statusEl) {
        statusEl.textContent = "❌ " + data.error;
        statusEl.style.color = "var(--red)";
      }
    } else {
      if (statusEl) {
        statusEl.textContent = "✓ Saved (.bak backup created)";
        statusEl.style.color = "var(--green)";
      }
      const contentBox = document.getElementById('file-modal-content');
      if (contentBox) contentBox.textContent = newContent;
      setTimeout(() => {
        if (statusEl && statusEl.textContent.startsWith("✓")) {
          statusEl.textContent = "";
        }
      }, 4000);
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = "❌ Network error";
      statusEl.style.color = "var(--red)";
    }
  }
}

function launchPlotFromViewer() {
  if (activeViewFile) {
    launchSmkplot(activeViewFile);
  }
}

function navFileChunk(dir) {
  const step = 2 * 1024 * 1024;
  const newOffset = Math.max(0, activeViewOffset + (dir * step));
  viewFileContent(activeViewFile, newOffset);
}

function closeFileModal() {
  document.getElementById('file-modal').classList.remove('open');
}

// ── Log Analysis Diagnostics ──
async function refreshAnalysis() {
  const res = await fetch('/api/log/analysis');
  const data = await res.json();

  const issuesList = document.getElementById('analysis-issues');
  issuesList.innerHTML = "";

  const allIssues = [...(data.errors || []).map(e => ({...e, type: 'error'})), ...(data.warnings || []).map(w => ({...w, type: 'warn'}))];
  if (allIssues.length === 0) {
    issuesList.innerHTML = '<div style="padding: 15px; color: var(--success); text-align: center;">No errors or warnings detected in current log.</div>';
  } else {
    allIssues.forEach(item => {
      const div = document.createElement('div');
      div.className = `issue-item ${item.type}`;
      const prefix = item.type === 'error' ? '✖ [ERROR]' : '⚠ [WARN]';
      if (item.ext_path) {
        div.innerHTML = `<span style="cursor: pointer;" title="Jump to execution log line"><b>[L${item.line}]</b></span> <span style="flex: 1;">${prefix} ${item.text}</span> <span style="font-size: 0.75rem; background: var(--accent); color: #fff; padding: 2px 6px; border-radius: 3px; white-space: nowrap;">📄 Open Log</span>`;
        div.onclick = (e) => {
          if (e.target.closest('span')?.getAttribute('title') === "Jump to execution log line") {
            jumpToLogLine(item.line);
          } else {
            viewFileContent(item.ext_path);
          }
        };
      } else {
        div.innerHTML = `<span><b>[L${item.line}]</b></span> <span>${prefix} ${item.text}</span>`;
        div.onclick = () => jumpToLogLine(item.line);
      }
      issuesList.appendChild(div);
    });
  }

  let smkList = (data.smoke_programs || []).map(p => `  • ${p}`).join('\n');
  const sumText = 
`========================================
  Log Analysis Summary
========================================
  Total lines  : ${data.total_lines}
  Errors       : ${(data.errors || []).length}
  Warnings     : ${(data.warnings || []).length}
  Completion   : ${data.completed ? '✓ Normal Completion' : '✗ NOT completed'}

  SMOKE programs detected:
${smkList || '  (None detected yet)'}
`;
  document.getElementById('analysis-summary').textContent = sumText;
}

function jumpToLogLine(lineNo) {
  switchTab('tab-log');
  const box = document.getElementById('log-display');
  const lines = box.textContent.split('\n');
  const approxScroll = (lineNo / Math.max(1, lines.length)) * box.scrollHeight;
  box.scrollTop = Math.max(0, approxScroll - 100);
}

// ── Log Stream SSE with Buffered Non-Blocking UI Rendering ──
let logBuffer = "";
let logRenderScheduled = false;
const MAX_DOM_LINES = 8000;

function flushLogBuffer() {
  logRenderScheduled = false;
  if (!logBuffer) return;

  const box = document.getElementById('log-display');
  if (!box) return;

  // Append buffered content
  box.textContent += logBuffer;
  logBuffer = "";

  // Prune top lines if content exceeds MAX_DOM_LINES to keep DOM light and responsive
  if (box.textContent.length > 500000) {
    const lines = box.textContent.split('\n');
    if (lines.length > MAX_DOM_LINES) {
      box.textContent = lines.slice(-MAX_DOM_LINES).join('\n');
    }
  }

  box.scrollTop = box.scrollHeight;
}

const evtSource = new EventSource('/api/logs/stream');
evtSource.onmessage = function(e) {
  const data = JSON.parse(e.data);
  if (data.line) {
    logBuffer += data.line;
    if (!logRenderScheduled) {
      logRenderScheduled = true;
      requestAnimationFrame(flushLogBuffer);
    }
  }

  const st = document.getElementById('run-status');
  if (st) {
    if (data.running) {
      st.textContent = "● Running...";
      st.style.color = "var(--warn)";
      document.getElementById('btn-run').disabled = true;
      document.getElementById('btn-stop').disabled = false;
    } else {
      document.getElementById('btn-run').disabled = !currentScriptPath;
      document.getElementById('btn-stop').disabled = true;
      if (data.rc !== null) {
        st.textContent = data.rc === 0 ? "✓ Completed (0)" : `✗ Exit (${data.rc})`;
        st.style.color = data.rc === 0 ? "var(--success)" : "var(--error)";
      }
    }
  }
};

async function runScript() {
  if (!currentScriptPath) return;
  document.getElementById('log-display').textContent = "";
  switchTab('tab-log');
  await fetch('/api/run', { method: 'POST', body: '{}' });
}

async function stopScript() {
  await fetch('/api/stop', { method: 'POST', body: '{}' });
}

async function restoreSession() {
  try {
    const res = await fetch('/api/session/state');
    const state = await res.json();
    if (state.current_script) {
      await loadScript(state.current_script);
    }
    const st = document.getElementById('run-status');
    if (state.is_running) {
      st.textContent = "● Running...";
      st.style.color = "var(--warn)";
      document.getElementById('btn-run').disabled = true;
      document.getElementById('btn-stop').disabled = false;
    } else if (state.exit_code !== null && state.exit_code !== undefined) {
      st.textContent = state.exit_code === 0 ? "✓ Completed (0)" : `✗ Exit (${state.exit_code})`;
      st.style.color = state.exit_code === 0 ? "var(--success)" : "var(--error)";
    }
    const savedTab = localStorage.getItem('smkrun_active_tab');
    if (savedTab && document.getElementById(savedTab)) {
      switchTab(savedTab);
    }
  } catch (err) {
    console.warn('[SMKRUN] Could not restore session state:', err);
  }
}
