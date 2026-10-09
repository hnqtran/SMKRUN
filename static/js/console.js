/**
 * SMKRUN Web Platform - Dedicated Bottom Console Logger Module
 */

const consoleCounts = { error: 0, warn: 0, log: 0 };
let isConsoleCollapsed = false;

function appendToBottomConsole(type, ...args) {
  const content = document.getElementById('bottom-console-content');
  if (consoleCounts[type] !== undefined) {
    consoleCounts[type]++;
    const errBadge = document.getElementById('console-badge-errors');
    const warnBadge = document.getElementById('console-badge-warns');
    const logBadge = document.getElementById('console-badge-logs');
    if (errBadge) errBadge.textContent = `${consoleCounts.error} Errors`;
    if (warnBadge) warnBadge.textContent = `${consoleCounts.warn} Warns`;
    if (logBadge) logBadge.textContent = `${consoleCounts.log} Logs`;
  }

  if (!content) return;
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0] + '.' + String(now.getMilliseconds()).padStart(3, '0');

  const row = document.createElement('div');
  row.className = `console-row ${type}`;

  const timeEl = document.createElement('span');
  timeEl.className = 'console-time';
  timeEl.textContent = `[${timeStr}]`;

  const msgEl = document.createElement('span');
  msgEl.style.flex = '1';
  msgEl.textContent = args.map(a => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' ');

  row.appendChild(timeEl);
  row.appendChild(msgEl);
  content.appendChild(row);

  // Auto-scroll to bottom
  content.scrollTop = content.scrollHeight;
}

function clearBottomConsole() {
  const content = document.getElementById('bottom-console-content');
  if (content) content.innerHTML = '';
  consoleCounts.error = 0;
  consoleCounts.warn = 0;
  consoleCounts.log = 0;
  const errBadge = document.getElementById('console-badge-errors');
  const warnBadge = document.getElementById('console-badge-warns');
  const logBadge = document.getElementById('console-badge-logs');
  if (errBadge) errBadge.textContent = '0 Errors';
  if (warnBadge) warnBadge.textContent = '0 Warns';
  if (logBadge) logBadge.textContent = '0 Logs';
}

function toggleBottomConsole() {
  const consoleEl = document.getElementById('bottom-console');
  const btn = document.getElementById('btn-toggle-console');
  if (!consoleEl) return;
  isConsoleCollapsed = !isConsoleCollapsed;
  if (isConsoleCollapsed) {
    consoleEl.classList.add('collapsed');
    if (btn) btn.textContent = '▲ Expand';
  } else {
    consoleEl.classList.remove('collapsed');
    if (btn) btn.textContent = '▼ Collapse';
  }
}

// Hook into global browser console
(function initConsoleInterceptors() {
  const origLog = console.log;
  const origWarn = console.warn;
  const origError = console.error;
  const origInfo = console.info;

  console.log = function(...args) {
    origLog.apply(console, args);
    appendToBottomConsole('log', ...args);
  };
  console.info = function(...args) {
    origInfo.apply(console, args);
    appendToBottomConsole('info', ...args);
  };
  console.warn = function(...args) {
    origWarn.apply(console, args);
    appendToBottomConsole('warn', ...args);
  };
  console.error = function(...args) {
    origError.apply(console, args);
    appendToBottomConsole('error', ...args);
  };

  window.addEventListener('error', (event) => {
    appendToBottomConsole('error', `Uncaught: ${event.message} (${event.filename}:${event.lineno})`);
  });
  window.addEventListener('unhandledrejection', (event) => {
    appendToBottomConsole('error', `Unhandled Promise Rejection: ${event.reason}`);
  });
})();
