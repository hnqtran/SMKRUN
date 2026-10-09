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

// Root Application Lifecycle Bootstrapper
window.addEventListener('DOMContentLoaded', async () => {
  // 1. Intercept console logs to bottom docking tray
  if (typeof initConsoleInterceptors === 'function') {
    initConsoleInterceptors();
  }

  // 2. Initialize draggable dialogs
  if (typeof initModalDraggables === 'function') {
    initModalDraggables();
  }

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
