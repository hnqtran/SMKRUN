/**
 * app.js - Main Application Bootstrap & Global State
 */

// Global State Variables shared across modules
let currentScripts = [];
let currentScriptPath = "";
let currentVars = [];
let originalSource = "";
let isEditingSource = false;
let activeViewFile = "";
let activeViewOffset = 0;
let activeViewTotal = 0;

function initSidebarResizer() {
  const resizer = document.getElementById('sidebar-resizer');
  const sidebar = document.querySelector('.sidebar');
  if (!resizer || !sidebar) return;

  const savedWidth = localStorage.getItem('smkrun_sidebar_width');
  if (savedWidth) {
    sidebar.style.width = `${Math.max(180, Math.min(750, parseInt(savedWidth)))}px`;
  }

  let isDragging = false;
  resizer.addEventListener('mousedown', (e) => {
    isDragging = true;
    resizer.classList.add('resizing');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    const containerRect = document.querySelector('.container')?.getBoundingClientRect();
    const leftOffset = containerRect ? containerRect.left : 0;
    const newWidth = Math.max(180, Math.min(750, e.clientX - leftOffset));
    sidebar.style.width = `${newWidth}px`;
  });

  window.addEventListener('mouseup', () => {
    if (isDragging) {
      isDragging = false;
      resizer.classList.remove('resizing');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem('smkrun_sidebar_width', parseInt(sidebar.style.width));
    }
  });
}

// Root Application Lifecycle Bootstrapper
window.addEventListener('DOMContentLoaded', async () => {
  // 1. Intercept console logs to bottom docking tray
  if (typeof initConsoleInterceptors === 'function') {
    initConsoleInterceptors();
  }

  // 2. Initialize draggable dialogs and sidebar resizer
  if (typeof initModalDraggables === 'function') {
    initModalDraggables();
  }
  initSidebarResizer();

  // 3. Setup context menu global listeners
  window.addEventListener('click', () => {
    if (typeof hideContextMenu === 'function') hideContextMenu();
  });
  window.addEventListener('contextmenu', (e) => {
    if (!e.target.closest('#vars-tbody') && !e.target.closest('.file-tree-item')) {
      if (typeof hideContextMenu === 'function') hideContextMenu();
    }
  });

  // 4. Load scripts tree and restore previous session
  if (typeof loadScripts === 'function') {
    await loadScripts();
  }
  if (typeof restoreSession === 'function') {
    await restoreSession();
  }
});
