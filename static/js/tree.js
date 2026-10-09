/**
 * SMKRUN Web Platform - Script Tree & Host Filesystem Browser Module
 */

const expandedNodes = new Map(); // path -> { dirs: [], scripts: [], isExpanded: bool }
let rootDirectoryPath = "";

let fsModalMode = "folder";
let fsCurrentPath = "";
let fsParentPath = null;
let fsSelectedItem = null;
let fsTargetVar = null;

// ── Window Dragging Utility ──
function makeElementDraggable(element, header) {
  if (!element || !header) return;
  let isDragging = false;
  let startX = 0, startY = 0;
  let initialLeft = 0, initialTop = 0;

  header.style.cursor = 'move';
  header.addEventListener('mousedown', (e) => {
    // Only drag with left mouse button and not when clicking buttons/inputs
    if (e.button !== 0 || e.target.closest('button, input, select, textarea, a')) return;
    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const rect = element.getBoundingClientRect();
    initialLeft = rect.left;
    initialTop = rect.top;

    // Switch element positioning to fixed absolute coordinates if not already
    element.style.position = 'fixed';
    element.style.margin = '0';
    element.style.left = `${initialLeft}px`;
    element.style.top = `${initialTop}px`;

    const onMouseMove = (ev) => {
      if (!isDragging) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      const newLeft = Math.max(0, Math.min(window.innerWidth - 60, initialLeft + dx));
      const newTop = Math.max(0, Math.min(window.innerHeight - 40, initialTop + dy));
      element.style.left = `${newLeft}px`;
      element.style.top = `${newTop}px`;
    };

    const onMouseUp = () => {
      isDragging = false;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  });
}

function initModalDraggables() {
  const fsBox = document.querySelector('#fs-modal .modal-box');
  const fsHeader = document.querySelector('#fs-modal .modal-header');
  if (fsBox && fsHeader) makeElementDraggable(fsBox, fsHeader);

  const fileBox = document.querySelector('#file-modal .modal-box');
  const fileHeader = document.querySelector('#file-modal .modal-header');
  if (fileBox && fileHeader) makeElementDraggable(fileBox, fileHeader);

  const docBox = document.querySelector('#doc-modal .modal-box');
  const docHeader = document.querySelector('#doc-modal .modal-header');
  if (docBox && docHeader) makeElementDraggable(docBox, docHeader);
}

async function loadScripts() {
  expandedNodes.clear();
  const res = await fetch('/api/scripts');
  const data = await res.json();
  rootDirectoryPath = data.root || "";
  const rootLbl = document.getElementById('current-root-label');
  if (rootLbl) {
    rootLbl.textContent = rootDirectoryPath;
    rootLbl.title = rootDirectoryPath;
  }

  expandedNodes.set(rootDirectoryPath, {
    dirs: data.dirs || [],
    scripts: data.scripts || [],
    isExpanded: true
  });
  renderScriptTree();
}

async function openFsModal(mode = "folder", targetVar = null) {
  fsModalMode = mode;
  fsTargetVar = targetVar;
  if (mode === "folder") {
    document.getElementById('fs-modal-title').textContent = "Select Root Directory";
    document.getElementById('fs-btn-select').textContent = "Select Folder";
  } else if (mode === "var_replace") {
    document.getElementById('fs-modal-title').textContent = `Select Replacement File for ${targetVar}`;
    document.getElementById('fs-btn-select').textContent = "Select File";
  } else {
    document.getElementById('fs-modal-title').textContent = "Open Runscript File";
    document.getElementById('fs-btn-select').textContent = "Open File";
  }
  document.getElementById('fs-modal').classList.add('open');
  const startPath = document.getElementById('current-root-label')?.textContent || "";
  await navigateFsTo(startPath);
}

function closeFsModal() {
  document.getElementById('fs-modal')?.classList.remove('open');
}

async function navigateFsTo(path) {
  fsSelectedItem = null;
  const res = await fetch(`/api/fs/ls?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  if (data.error) {
    alert(data.error);
    return;
  }
  fsCurrentPath = data.current;
  fsParentPath = data.parent;
  document.getElementById('fs-current-path').value = data.current;
  document.getElementById('fs-btn-up').disabled = !data.parent;

  const list = document.getElementById('fs-entries-list');
  list.innerHTML = "";

  // List Directories
  (data.dirs || []).forEach(d => {
    const item = document.createElement('div');
    item.className = 'fs-item';
    item.innerHTML = `<span>📁</span> <span style="font-weight: bold;">${d.name}</span>`;
    item.ondblclick = () => navigateFsTo(d.path);
    item.onclick = () => {
      document.querySelectorAll('.fs-item').forEach(el => el.classList.remove('selected'));
      item.classList.add('selected');
      fsSelectedItem = { type: 'dir', path: d.path };
    };
    list.appendChild(item);
  });

  // List Files
  (data.files || []).forEach(f => {
    const item = document.createElement('div');
    item.className = 'fs-item';
    const icon = f.is_script ? "📜" : (f.is_plottable ? "📊" : "📄");
    item.innerHTML = `<span>${icon}</span> <span>${f.name}</span>`;
    if (fsModalMode === 'file' || fsModalMode === 'var_replace') {
      item.ondblclick = () => {
        closeFsModal();
        if (fsModalMode === 'var_replace' && fsTargetVar) {
          applyVarFileReplacement(fsTargetVar, f.path);
        } else {
          loadScript(f.path);
        }
      };
      item.onclick = () => {
        document.querySelectorAll('.fs-item').forEach(el => el.classList.remove('selected'));
        item.classList.add('selected');
        fsSelectedItem = { type: 'file', path: f.path };
      };
    }
    list.appendChild(item);
  });
}

async function navigateFsUp() {
  if (fsParentPath) {
    await navigateFsTo(fsParentPath);
  }
}

async function confirmFsSelection() {
  if (fsModalMode === "folder") {
    const target = (fsSelectedItem && fsSelectedItem.type === 'dir') ? fsSelectedItem.path : fsCurrentPath;
    const res = await fetch(`/api/change_root?dir=${encodeURIComponent(target)}`);
    const data = await res.json();
    if (data.error) alert(data.error);
    else {
      closeFsModal();
      loadScripts();
    }
  } else if (fsModalMode === "file") {
    if (fsSelectedItem && fsSelectedItem.type === 'file') {
      closeFsModal();
      loadScript(fsSelectedItem.path);
    } else {
      alert("Please select a file to open.");
    }
  } else if (fsModalMode === "var_replace") {
    if (fsSelectedItem && fsSelectedItem.type === 'file') {
      const chosenPath = fsSelectedItem.path;
      const targetVar = fsTargetVar;
      closeFsModal();
      applyVarFileReplacement(targetVar, chosenPath);
    } else {
      alert("Please select a replacement file.");
    }
  }
}

async function toggleTreeNode(dirPath) {
  let node = expandedNodes.get(dirPath);
  if (!node) {
    const res = await fetch(`/api/scripts?dir=${encodeURIComponent(dirPath)}`);
    const data = await res.json();
    node = {
      dirs: data.dirs || [],
      scripts: data.scripts || [],
      isExpanded: true
    };
    expandedNodes.set(dirPath, node);
  } else {
    node.isExpanded = !node.isExpanded;
  }
  renderScriptTree();
}

function renderScriptTree() {
  const filterVal = (document.getElementById('script-search')?.value || "").toLowerCase();
  const list = document.getElementById('script-list');
  if (!list) return;
  list.innerHTML = "";

  if (!expandedNodes.has(rootDirectoryPath)) {
    list.innerHTML = '<div style="padding: 10px; color: var(--fg2); font-size: 0.8rem;">Loading directory...</div>';
    return;
  }

  function appendBranch(dirPath, depth) {
    const node = expandedNodes.get(dirPath);
    if (!node) return;

    // Subdirectories (strictly immediate 1 level)
    (node.dirs || []).forEach(sub => {
      const childNode = expandedNodes.get(sub.path);
      const isExpanded = childNode ? childNode.isExpanded : false;
      const arrow = isExpanded ? '▼' : '▶';

      const folderRow = document.createElement('div');
      folderRow.style.cssText = `
        font-size: 0.8rem;
        color: var(--fg);
        padding: 5px 6px;
        padding-left: ${depth * 14 + 6}px;
        border-radius: 4px;
        cursor: pointer;
        user-select: none;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: background 0.15s;
      `;
      folderRow.onmouseover = () => folderRow.style.background = 'rgba(255,255,255,0.04)';
      folderRow.onmouseout = () => folderRow.style.background = 'transparent';

      folderRow.innerHTML = `
        <span style="font-size: 0.68rem; width: 14px; text-align: center; color: var(--fg2);">${arrow}</span>
        <span>📁</span>
        <span style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${sub.name}</span>
      `;
      folderRow.onclick = () => toggleTreeNode(sub.path);
      list.appendChild(folderRow);

      if (isExpanded) {
        appendBranch(sub.path, depth + 1);
      }
    });

    // Scripts (strictly immediate 1 level)
    (node.scripts || []).forEach(s => {
      if (filterVal && !s.name.toLowerCase().includes(filterVal)) return;

      const item = document.createElement('div');
      item.className = 'script-item' + (s.full_path === currentScriptPath ? ' active' : '');
      item.style.paddingLeft = `${depth * 14 + 24}px`;
      item.innerHTML = `<span>📜</span> <span>${s.name}</span>`;
      item.title = s.rel_path || s.full_path;
      item.onclick = () => loadScript(s.full_path);
      item.ondblclick = () => {
        loadScript(s.full_path);
        if (typeof switchTab === 'function') switchTab('tab-vars');
      };
      list.appendChild(item);
    });
  }

  appendBranch(rootDirectoryPath, 0);

  const rootNode = expandedNodes.get(rootDirectoryPath);
  if (rootNode && rootNode.dirs.length === 0 && rootNode.scripts.length === 0) {
    list.innerHTML = '<div style="padding: 10px; color: var(--fg2); font-size: 0.8rem;">No .csh/.tcsh scripts or subdirectories found in root.</div>';
  }
}

function filterScripts() {
  renderScriptTree();
}

async function loadScript(fullPath) {
  currentScriptPath = fullPath;
  filterScripts();
  const titleEl = document.getElementById('active-script-title');
  if (titleEl) titleEl.textContent = fullPath;
  const btnRun = document.getElementById('btn-run');
  if (btnRun) btnRun.disabled = false;
  const res = await fetch(`/api/load_script?path=${encodeURIComponent(fullPath)}`);
  const data = await res.json();
  currentVars = data.vars;
  renderVars();
  originalSource = data.source;
  const ed = document.getElementById('source-editor');
  if (ed) ed.value = data.source;
  isEditingSource = false;
  updateSourceUIState();
  refreshFileIO();
  if (typeof switchTab === 'function') {
    switchTab('tab-vars');
  }
}
