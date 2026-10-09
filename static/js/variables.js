/**
 * variables.js - Variable rendering, overrides, context menu & variable documentation
 */

function renderVars() {
  const q = document.getElementById('var-filter').value.toLowerCase();
  const tbody = document.getElementById('vars-tbody');
  tbody.innerHTML = "";
  currentVars.filter(v => v.var.toLowerCase().includes(q) || (v.expanded && v.expanded.toLowerCase().includes(q))).forEach(v => {
    const tr = document.createElement('tr');
    
    const isExistingFile = (v.status === "ok" || v.status === "empty" || v.status === "exists");
    let statClass = "status-ok";
    let statText = "[OK] Exists";
    if (v.status === "missing") { statClass = "status-missing"; statText = "[X] Missing"; }
    else if (v.status === "empty") { statClass = "status-empty"; statText = "[W] Empty"; }
    else if (v.status === "nopath") { statClass = ""; statText = "[-] Value"; }
    else if (isExistingFile) { statClass = "status-ok"; statText = "[OK] Exists"; }

    if (v.is_override) {
      tr.style.backgroundColor = 'rgba(234, 179, 8, 0.12)';
    }

    const valToEdit = v.value || v.expanded || '';
    tr.innerHTML = `
      <td style="font-weight: bold; color: var(--fg); cursor: pointer;" onclick="showVarDoc('${v.var}')">${v.var} ${v.is_override ? '<span title="Overridden" style="color: #f59e0b; font-size: 0.75rem;">[✎]</span>' : ''}</td>
      <td class="editable" ondblclick="promptOverride('${v.var}', '${valToEdit.replace(/'/g, "\\'")}')">${v.expanded || v.value}</td>
      <td class="${statClass}">${statText}</td>
    `;

    const isPathVar = v.status !== "nopath" && (v.status === "ok" || v.status === "empty" || v.status === "missing" || v.status === "exists");
    const lowerPath = (v.expanded || v.value || '').toLowerCase();
    const isPlottable = isExistingFile && (lowerPath.endsWith('.ncf') || lowerPath.endsWith('.nc') || lowerPath.endsWith('.csv') || lowerPath.endsWith('.rpt') || lowerPath.endsWith('.txt') || lowerPath.endsWith('.lst'));

    // Right-click context menu (identical to smkrun._show_var_context_menu)
    tr.oncontextmenu = (e) => {
      e.preventDefault();
      const menuItems = [
        { label: `Define Variable: ${v.var}`, icon: "ℹ", action: () => showVarDoc(v.var) },
        { label: `Override Variable: ${v.var}`, icon: "✏", action: () => promptOverride(v.var, valToEdit) }
      ];

      if (isPathVar) {
        menuItems.push({ label: `Browse Replacement File...`, icon: "📁", action: () => browseVarReplacement(v.var, v.expanded || v.value) });
      }

      if (v.is_override) {
        menuItems.push({ type: "separator" });
        menuItems.push({ label: `Save '${v.var}' to Source Script`, icon: "💾", action: () => saveVarToScript(v.var) });
      }

      if (isExistingFile) {
        menuItems.push({ type: "separator" });
        menuItems.push({ label: `View/Edit File: ${v.expanded.split('/').pop()}`, icon: "📄", action: () => viewFileContent(v.expanded) });
        if (isPlottable) {
          menuItems.push({ label: `Plot Emissions`, icon: "📊", action: () => launchSmkplot(v.expanded) });
        }
      }
      menuItems.push({ type: "separator" });
      menuItems.push({ label: "Copy Path", icon: "📋", action: () => copyToClipboard(v.expanded || v.value) });
      showContextMenu(e, menuItems);
    };

    tbody.appendChild(tr);
  });

  // Update override count & button state
  const overrideCount = currentVars.filter(v => v.is_override).length;
  const countBadge = document.getElementById('override-count');
  const btnSaveScript = document.getElementById('btn-save-vars-script');
  if (countBadge) {
    countBadge.textContent = overrideCount > 0 ? `${overrideCount} override(s) active` : "";
  }
  if (btnSaveScript) {
    btnSaveScript.disabled = overrideCount === 0;
  }
}

// ── Floating Desktop-Style Context Menu ──
function showContextMenu(e, items) {
  const menu = document.getElementById('custom-context-menu');
  if (!menu) return;
  menu.innerHTML = "";
  items.forEach(it => {
    if (it.type === "separator") {
      const sep = document.createElement('div');
      sep.className = 'context-menu-sep';
      menu.appendChild(sep);
    } else {
      const itemEl = document.createElement('div');
      itemEl.className = 'context-menu-item';
      itemEl.innerHTML = `<span>${it.icon || ''}</span> <span>${it.label}</span>`;
      itemEl.onclick = (evt) => {
        evt.stopPropagation();
        hideContextMenu();
        it.action();
      };
      menu.appendChild(itemEl);
    }
  });

  menu.style.display = 'block';
  menu.classList.add('open');

  // Boundary checks to stay inside window
  let x = e.clientX;
  let y = e.clientY;
  const menuW = 220;
  const menuH = menu.offsetHeight || 150;
  if (x + menuW > window.innerWidth) x = window.innerWidth - menuW - 10;
  if (y + menuH > window.innerHeight) y = window.innerHeight - menuH - 10;

  menu.style.left = `${Math.max(10, x)}px`;
  menu.style.top = `${Math.max(10, y)}px`;
}

function hideContextMenu() {
  const menu = document.getElementById('custom-context-menu');
  if (menu) {
    menu.style.display = 'none';
    menu.classList.remove('open');
  }
}

function copyToClipboard(text) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    alert("Copied to clipboard: " + text);
  }).catch(() => {
    prompt("Copy path:", text);
  });
}

async function reloadVars() {
  if (!currentScriptPath) return;
  const res = await fetch(`/api/load_script?path=${encodeURIComponent(currentScriptPath)}`);
  const data = await res.json();
  currentVars = data.vars;
  renderVars();
}

function checkPaths() {
  if (!currentVars || currentVars.length === 0) {
    alert("No variables loaded.");
    return;
  }
  let ok = 0, empty = 0, missing = 0, nopath = 0;
  currentVars.forEach(v => {
    if (v.status === "exists") ok++;
    else if (v.status === "empty") empty++;
    else if (v.status === "missing") missing++;
    else nopath++;
  });
  alert(`Path Check Results:\n[OK]  OK: ${ok}\n[W]  Empty: ${empty}\n[X]  Missing: ${missing}\n[-]  Non-path: ${nopath}`);
}

async function promptOverride(varName, currentVal) {
  const newVal = prompt(`Override value for ${varName}:`, currentVal);
  if (newVal !== null) {
    const res = await fetch('/api/override', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ var: varName, val: newVal })
    });
    const data = await res.json();
    currentVars = data.vars;
    renderVars();
  }
}

function browseVarReplacement(varName, currentVal) {
  openFsModal("var_replace", varName);
}

async function applyVarFileReplacement(varName, filePath) {
  const res = await fetch('/api/override', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ var: varName, val: filePath })
  });
  const data = await res.json();
  currentVars = data.vars;
  renderVars();
}

async function saveVarToScript(varName) {
  if (!confirm(`Permanently write override for '${varName}' into script file? (A .bak copy will be created)`)) return;
  const res = await fetch('/api/vars/save_to_script', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ var: varName })
  });
  const data = await res.json();
  if (data.error) {
    alert(data.error);
  } else {
    alert(data.message || "Variable saved to script.");
    currentVars = data.vars;
    renderVars();
    if (data.source) {
      document.getElementById('source-editor').value = data.source;
      originalSource = data.source;
    }
  }
}

async function saveAllOverridesToScript() {
  const overrideCount = currentVars.filter(v => v.is_override).length;
  if (overrideCount === 0) return;
  if (!confirm(`Permanently write all ${overrideCount} active override(s) into script file? (A .bak copy will be created)`)) return;
  const res = await fetch('/api/vars/save_to_script', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  const data = await res.json();
  if (data.error) {
    alert(data.error);
  } else {
    alert(data.message || "Overrides saved to script.");
    currentVars = data.vars;
    renderVars();
    if (data.source) {
      document.getElementById('source-editor').value = data.source;
      originalSource = data.source;
    }
  }
}

async function showVarDoc(varName) {
  const res = await fetch(`/api/var/doc?name=${encodeURIComponent(varName)}`);
  const data = await res.json();
  document.getElementById('doc-modal-title').textContent = `Documentation: ${varName}`;
  document.getElementById('doc-modal-body').innerHTML = data.doc || `<i>No specific documentation entry found for ${varName}.</i>`;
  document.getElementById('doc-modal').classList.add('open');
}

function closeDocModal() {
  document.getElementById('doc-modal').classList.remove('open');
}
