/**
 * smkplot.js - SMKPLOT Interactive Multi-Window Visualization Engine (Zero-X11)
 */

let smkplotWinCounter = 0;
const smkplotWindows = new Map();

function getColormapRgb(t, cmapName = 'turbo') {
  const clamped = Math.max(0, Math.min(1, isNaN(t) ? 0 : t));
  switch (cmapName) {
    case 'jet': {
      const r = Math.max(0, Math.min(1, 1.5 - Math.abs(clamped * 4 - 3)));
      const g = Math.max(0, Math.min(1, 1.5 - Math.abs(clamped * 4 - 2)));
      const b = Math.max(0, Math.min(1, 1.5 - Math.abs(clamped * 4 - 1)));
      return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
    }
    case 'viridis': {
      const c0 = [68, 1, 84];
      const c1 = [59, 82, 139];
      const c2 = [33, 145, 140];
      const c3 = [94, 201, 98];
      const c4 = [253, 231, 37];
      if (clamped < 0.25) return interpRgb(c0, c1, clamped / 0.25);
      if (clamped < 0.5) return interpRgb(c1, c2, (clamped - 0.25) / 0.25);
      if (clamped < 0.75) return interpRgb(c2, c3, (clamped - 0.5) / 0.25);
      return interpRgb(c3, c4, (clamped - 0.75) / 0.25);
    }
    case 'plasma': {
      const c0 = [13, 8, 135];
      const c1 = [126, 3, 168];
      const c2 = [204, 71, 120];
      const c3 = [248, 149, 64];
      const c4 = [240, 249, 33];
      if (clamped < 0.25) return interpRgb(c0, c1, clamped / 0.25);
      if (clamped < 0.5) return interpRgb(c1, c2, (clamped - 0.25) / 0.25);
      if (clamped < 0.75) return interpRgb(c2, c3, (clamped - 0.5) / 0.25);
      return interpRgb(c3, c4, (clamped - 0.75) / 0.25);
    }
    case 'coolwarm': {
      const c0 = [59, 76, 192];
      const c1 = [221, 221, 221];
      const c2 = [180, 4, 38];
      if (clamped < 0.5) return interpRgb(c0, c1, clamped / 0.5);
      return interpRgb(c1, c2, (clamped - 0.5) / 0.5);
    }
    case 'reds': {
      const r = Math.round(255 - (1 - clamped) * 50);
      const g = Math.round((1 - clamped) * 240);
      const b = Math.round((1 - clamped) * 240);
      return [r, g, b];
    }
    case 'turbo':
    default: {
      const c0 = [48, 18, 59];
      const c1 = [70, 134, 251];
      const c2 = [27, 229, 181];
      const c3 = [164, 252, 60];
      const c4 = [251, 185, 56];
      const c5 = [227, 68, 10];
      const c6 = [122, 4, 3];
      if (clamped < 0.16) return interpRgb(c0, c1, clamped / 0.16);
      if (clamped < 0.33) return interpRgb(c1, c2, (clamped - 0.16) / 0.17);
      if (clamped < 0.50) return interpRgb(c2, c3, (clamped - 0.33) / 0.17);
      if (clamped < 0.67) return interpRgb(c3, c4, (clamped - 0.50) / 0.17);
      if (clamped < 0.84) return interpRgb(c4, c5, (clamped - 0.67) / 0.17);
      return interpRgb(c5, c6, (clamped - 0.84) / 0.16);
    }
  }
}

function interpRgb(c1, c2, fraction) {
  const f = Math.max(0, Math.min(1, fraction));
  return [
    Math.round(c1[0] + (c2[0] - c1[0]) * f),
    Math.round(c1[1] + (c2[1] - c1[1]) * f),
    Math.round(c1[2] + (c2[2] - c1[2]) * f)
  ];
}

class SmkplotWindowInstance {
  constructor(id, filePath) {
    this.id = id;
    this.filePath = filePath;
    this.meta = null;
    this.matrixData = null;
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.isDragging = false;
    this.dragStartX = 0;
    this.dragStartY = 0;
    this.animInterval = null;
    this.selectedCell = null;
    this.zoomToData = true;
    this.cachedMapImage = null;
    this.timeSliderDebounce = null;
    this.layerSliderDebounce = null;
    this.container = null;
  }

  bringToFront() {
    smkplotWinCounter++;
    if (this.container) {
      this.container.style.zIndex = 2100 + smkplotWinCounter;
      document.querySelectorAll('.smkplot-window').forEach(w => w.classList.remove('active'));
      this.container.classList.add('active');
    }
  }

  close() {
    if (this.animInterval) {
      clearInterval(this.animInterval);
      this.animInterval = null;
    }
    if (this.container && this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
    smkplotWindows.delete(this.id);
  }

  createDOM(initialLeft, initialTop, width, height) {
    const fileName = this.filePath.split('/').pop();
    const win = document.createElement('div');
    win.id = `smkplot-win-${this.id}`;
    win.className = 'smkplot-window active';
    win.style.left = `${initialLeft}px`;
    win.style.top = `${initialTop}px`;
    win.style.width = `${width}px`;
    win.style.height = `${height}px`;
    win.style.zIndex = 2100 + (++smkplotWinCounter);

    win.addEventListener('mousedown', () => this.bringToFront());

    win.innerHTML = `
      <div class="smkplot-win-header">
        <div style="display: flex; gap: 8px; align-items: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
          <span style="color: var(--accent);">📊 SMKPLOT</span>
          <span id="win-${this.id}-title-text" style="font-size: 0.8rem; color: var(--fg2); font-family: monospace;" title="${this.filePath}">[#${this.id}] ${fileName}</span>
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          <button style="padding: 2px 6px; font-size: 0.75rem;" onclick="smkplotWindows.get(${this.id}).resetMapZoom()">🔍 Reset</button>
          <button style="padding: 2px 6px; font-size: 0.75rem;" onclick="smkplotWindows.get(${this.id}).zoomToDataExtent()">🎯 Zoom Extent</button>
          <button style="padding: 2px 6px; font-size: 0.75rem;" onclick="smkplotWindows.get(${this.id}).savePlotImage()">💾 Save</button>
          <button style="padding: 2px 7px; font-size: 0.85rem;" onclick="smkplotWindows.get(${this.id}).close()">✕</button>
        </div>
      </div>
      <div style="flex: 1; display: flex; flex-direction: row; gap: 8px; padding: 8px; overflow: hidden; background: var(--bg);">
        <!-- Controls Sidebar -->
        <div style="width: 260px; display: flex; flex-direction: column; gap: 8px; overflow-y: auto; background: var(--panel2); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
          <div>
            <label style="font-size: 0.72rem; color: var(--fg2); font-weight: bold; text-transform: uppercase;">Plot Type</label>
            <select id="win-${this.id}-sel-pltyp" class="search-input" style="margin-top: 4px;" onchange="smkplotWindows.get(${this.id}).renderSlice()">
              <option value="auto">Auto-detect</option>
              <option value="grid">Grid (ROW/COL)</option>
              <option value="county">County (FIPS)</option>
            </select>
          </div>

          <div>
            <label style="font-size: 0.72rem; color: var(--fg2); font-weight: bold; text-transform: uppercase;">Pollutant or Formula</label>
            <select id="win-${this.id}-sel-pol" class="search-input" style="margin-top: 4px;" onchange="smkplotWindows.get(${this.id}).syncPolInput(this.value)"></select>
            <input type="text" id="win-${this.id}-formula-input" class="search-input" style="margin-top: 4px; font-family: monospace;" placeholder="e.g. NOX = NO + NO2" onkeydown="if(event.key==='Enter') smkplotWindows.get(${this.id}).renderSlice()">
          </div>

          <div id="win-${this.id}-dim-controls" style="display: flex; flex-direction: column; gap: 8px;">
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: var(--fg2);">
                <label style="font-weight: bold; text-transform: uppercase;">Time Step</label>
                <span id="win-${this.id}-lbl-tstep" style="font-family: monospace;">T=1</span>
              </div>
              <div style="display: flex; gap: 6px; align-items: center; margin-top: 3px;">
                <button id="win-${this.id}-btn-play" style="padding: 2px 6px; font-size: 0.72rem;" onclick="smkplotWindows.get(${this.id}).toggleTimeAnimation()">▶</button>
                <input type="range" id="win-${this.id}-slider-time" min="0" max="0" value="0" style="flex: 1;" oninput="smkplotWindows.get(${this.id}).onTimeSliderChange(this.value)">
                <select id="win-${this.id}-sel-top" style="font-size: 0.72rem; padding: 2px;" onchange="smkplotWindows.get(${this.id}).renderSlice()">
                  <option value="select">Step</option>
                  <option value="mean">Avg</option>
                  <option value="sum">Sum</option>
                  <option value="max">Max</option>
                </select>
              </div>
            </div>

            <div>
              <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: var(--fg2);">
                <label style="font-weight: bold; text-transform: uppercase;">Vertical Layer</label>
                <span id="win-${this.id}-lbl-layer" style="font-family: monospace;">L=1</span>
              </div>
              <div style="display: flex; gap: 6px; align-items: center; margin-top: 3px;">
                <input type="range" id="win-${this.id}-slider-layer" min="0" max="0" value="0" style="flex: 1;" oninput="smkplotWindows.get(${this.id}).onLayerSliderChange(this.value)">
                <select id="win-${this.id}-sel-lop" style="font-size: 0.72rem; padding: 2px;" onchange="smkplotWindows.get(${this.id}).renderSlice()">
                  <option value="select">Layer</option>
                  <option value="sum">Sum</option>
                  <option value="mean">Avg</option>
                </select>
              </div>
            </div>
          </div>

          <div>
            <label style="font-size: 0.72rem; color: var(--fg2); font-weight: bold; text-transform: uppercase;">Colormap & Scale</label>
            <div style="display: flex; gap: 6px; margin-top: 3px;">
              <select id="win-${this.id}-sel-cmap" class="search-input" style="margin-top: 0; flex: 1;" onchange="smkplotWindows.get(${this.id}).onMapParamChanged()">
                <option value="turbo">Turbo</option>
                <option value="jet">Jet</option>
                <option value="viridis">Viridis</option>
                <option value="plasma">Plasma</option>
                <option value="inferno">Inferno</option>
                <option value="magma">Magma</option>
                <option value="coolwarm">Coolwarm</option>
                <option value="reds">Reds</option>
              </select>
              <label style="display: flex; align-items: center; gap: 3px; font-size: 0.72rem; cursor: pointer;">
                <input type="checkbox" id="win-${this.id}-chk-log" onchange="smkplotWindows.get(${this.id}).onMapParamChanged()"> Log
              </label>
            </div>
          </div>

          <div style="background: var(--panel); padding: 6px; border-radius: 4px; border: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px;">
            <label style="font-size: 0.7rem; color: var(--fg2); font-weight: bold; text-transform: uppercase;">Overlays</label>
            <label style="display: flex; align-items: center; gap: 4px; font-size: 0.72rem; cursor: pointer;">
              <input type="checkbox" id="win-${this.id}-chk-bounds" checked onchange="smkplotWindows.get(${this.id}).redrawCanvas()"> State / County
            </label>
            <label style="display: flex; align-items: center; gap: 4px; font-size: 0.72rem; cursor: pointer;">
              <input type="checkbox" id="win-${this.id}-chk-graticule" checked onchange="smkplotWindows.get(${this.id}).redrawCanvas()"> Graticules
            </label>
            <label style="display: flex; align-items: center; gap: 4px; font-size: 0.72rem; cursor: pointer;">
              <input type="checkbox" id="win-${this.id}-chk-gridlines" onchange="smkplotWindows.get(${this.id}).redrawCanvas()"> Gridlines
            </label>
          </div>

          <button class="btn-primary" style="margin-top: 2px; padding: 4px;" onclick="smkplotWindows.get(${this.id}).renderSlice()">⟳ Update</button>

          <!-- Summary Stats -->
          <div style="margin-top: 6px; border-top: 1px solid var(--border); padding-top: 6px;">
            <label style="font-size: 0.7rem; color: var(--fg2); font-weight: bold; text-transform: uppercase;">Grid Statistics</label>
            <div id="win-${this.id}-stats-content" style="font-family: monospace; font-size: 0.72rem; line-height: 1.5; margin-top: 3px; color: var(--fg);">
              Loading...
            </div>
          </div>
        </div>

        <!-- Interactive Map & Profiles Area -->
        <div style="flex: 1; display: flex; flex-direction: column; gap: 6px; overflow: hidden;">
          <div class="canvas-container" style="flex: 1; min-height: 260px; position: relative;">
            <canvas id="win-${this.id}-map-canvas" class="plot-canvas" style="width: 100%; height: 100%;"></canvas>
            <div id="win-${this.id}-cell-badge" class="grid-info-badge" style="bottom: 8px; left: 8px;">Hover over cells to inspect coordinates & emissions</div>
          </div>

          <!-- Diurnal and Vertical mini charts -->
          <div style="height: 135px; display: flex; gap: 6px;">
            <div style="flex: 1; background: var(--panel2); border: 1px solid var(--border); border-radius: 6px; padding: 4px; display: flex; flex-direction: column;">
              <span id="win-${this.id}-profile-ts-title" style="font-size: 0.7rem; font-weight: bold; color: var(--fg2);">24-hr Time Series</span>
              <canvas id="win-${this.id}-chart-ts" style="flex: 1; width: 100%; height: 100%;"></canvas>
            </div>
            <div style="flex: 1; background: var(--panel2); border: 1px solid var(--border); border-radius: 6px; padding: 4px; display: flex; flex-direction: column;">
              <span id="win-${this.id}-profile-v-title" style="font-size: 0.7rem; font-weight: bold; color: var(--fg2);">Vertical Profile</span>
              <canvas id="win-${this.id}-chart-v" style="flex: 1; width: 100%; height: 100%;"></canvas>
            </div>
          </div>
        </div>
      </div>
    `;

    this.container = win;
    makeElementDraggable(win, win.querySelector('.smkplot-win-header'));
    return win;
  }

  syncPolInput(val) {
    const inp = document.getElementById(`win-${this.id}-formula-input`);
    if (inp) {
      inp.value = val;
      this.renderSlice();
    }
  }

  onTimeSliderChange(val) {
    const lbl = document.getElementById(`win-${this.id}-lbl-tstep`);
    const n = this.meta ? (this.meta.n_tsteps || 1) : 1;
    if (lbl) lbl.textContent = `T=${parseInt(val) + 1} / ${n}`;
    clearTimeout(this.timeSliderDebounce);
    this.timeSliderDebounce = setTimeout(() => { this.renderSlice(); }, 40);
  }

  onLayerSliderChange(val) {
    const lbl = document.getElementById(`win-${this.id}-lbl-layer`);
    const n = this.meta ? (this.meta.n_layers || 1) : 1;
    if (lbl) lbl.textContent = `L=${parseInt(val) + 1} / ${n}`;
    clearTimeout(this.layerSliderDebounce);
    this.layerSliderDebounce = setTimeout(() => { this.renderSlice(); }, 40);
  }

  toggleTimeAnimation() {
    const btn = document.getElementById(`win-${this.id}-btn-play`);
    if (this.animInterval) {
      clearInterval(this.animInterval);
      this.animInterval = null;
      if (btn) btn.textContent = '▶';
    } else {
      if (btn) btn.textContent = '⏸';
      const slider = document.getElementById(`win-${this.id}-slider-time`);
      this.animInterval = setInterval(() => {
        if (this._isRendering) return; // Drop step if previous render still processing to eliminate lag
        let cur = parseInt(slider.value);
        let maxVal = parseInt(slider.max);
        let nxt = (cur + 1) > maxVal ? 0 : cur + 1;
        slider.value = nxt;
        const lbl = document.getElementById(`win-${this.id}-lbl-tstep`);
        const n = this.meta ? (this.meta.n_tsteps || 1) : 1;
        if (lbl) lbl.textContent = `T=${nxt + 1} / ${n}`;
        this.renderSlice();
      }, 150);
    }
  }

  onMapParamChanged() {
    if (this.matrixData && this.matrixData.is_county_map) {
      this.renderSlice();
    } else {
      this.redrawCanvas();
    }
  }

  async renderSlice() {
    if (!this.filePath || this._isRendering) return;
    this._isRendering = true;
    const formulaInput = document.getElementById(`win-${this.id}-formula-input`);
    const pollutant = formulaInput ? formulaInput.value.trim() : '';
    const timeIdx = document.getElementById(`win-${this.id}-slider-time`)?.value || '0';
    const layerIdx = document.getElementById(`win-${this.id}-slider-layer`)?.value || '0';
    const timeOp = document.getElementById(`win-${this.id}-sel-top`)?.value || 'select';
    const layerOp = document.getElementById(`win-${this.id}-sel-lop`)?.value || 'select';
    const cmap = document.getElementById(`win-${this.id}-sel-cmap`)?.value || 'turbo';
    const pltyp = document.getElementById(`win-${this.id}-sel-pltyp`)?.value || 'auto';
    const isLog = document.getElementById(`win-${this.id}-chk-log`)?.checked || false;

    const statsBox = document.getElementById(`win-${this.id}-stats-content`);
    if (statsBox) statsBox.textContent = 'Computing spatial slice...';

    // Only fetch boundary/graticule geometries on first load or when switching datasets
    const hasCachedOverlays = Boolean(this._cachedOverlays && (this._cachedOverlays.boundaries?.length || this._cachedOverlays.graticules?.length));

    try {
      const params = new URLSearchParams({
        path: this.filePath,
        pollutant: pollutant,
        time: timeIdx,
        layer: layerIdx,
        time_op: timeOp,
        layer_op: layerOp,
        cmap: cmap,
        pltyp: pltyp,
        log_scale: isLog ? 'true' : 'false',
        zoom_to_data: this.zoomToData ? 'true' : 'false',
        skip_overlays: hasCachedOverlays ? 'true' : 'false'
      });

      console.info(`[SMKPLOT-WEB #${this.id}] Requesting slice: pollutant="${pollutant}", pltyp=${pltyp}, skip_overlays=${hasCachedOverlays}`);
      const res = await fetch(`/api/smkplot/slice?${params.toString()}`);
      const data = await res.json();
      if (data.error) {
        if (statsBox) statsBox.textContent = `Error: ${data.error}`;
        console.error(`[SMKPLOT-WEB #${this.id}] Slice error:`, data.error);
        if (data.engine_stderr) {
          console.warn(`[SMKPLOT-ENGINE #${this.id}] stderr:\n${data.engine_stderr}`);
        }
        return;
      }

      if (data.engine_stderr) {
        const lines = data.engine_stderr.split('\n');
        for (const line of lines) {
          if (line.includes('ERROR:')) console.error(`[SMKPLOT-ENGINE] ${line}`);
          else if (line.includes('WARNING:')) console.warn(`[SMKPLOT-ENGINE] ${line}`);
          else console.info(`[SMKPLOT-ENGINE] ${line}`);
        }
      }

      data.matrix = data.matrix || data.data;

      // Preserve cached overlays if this response skipped them
      if (data.boundaries && data.boundaries.length > 0) {
        this._cachedOverlays = { boundaries: data.boundaries, graticules: data.graticules || [] };
      } else if (this._cachedOverlays) {
        data.boundaries = this._cachedOverlays.boundaries;
        data.graticules = this._cachedOverlays.graticules;
      }

      this.matrixData = data;
      this.updateTitleHeader(data);
      this.renderStatsDisplay(data);

      if (data.is_county_map && data.map_image) {
        console.info(`[SMKPLOT-WEB #${this.id}] Rendered county map image (${data.count} counties, zoom_to_data=${this.zoomToData})`);
        const img = new Image();
        img.onload = () => {
          this.cachedMapImage = img;
          this.redrawCanvas();
        };
        img.src = `data:image/png;base64,${data.map_image}`;
      } else {
        this.cachedMapImage = null;
        this.redrawCanvas();
      }

      if (this.selectedCell) {
        this.loadCellProfile(this.selectedCell.row, this.selectedCell.col);
      }
    } catch (err) {
      if (statsBox) statsBox.textContent = `Failed to fetch slice: ${err}`;
      console.error(`[SMKPLOT-WEB #${this.id}] Fetch slice exception:`, err);
    } finally {
      this._isRendering = false;
    }
  }

  updateTitleHeader(data) {
    const titleSpan = document.getElementById(`win-${this.id}-title-text`);
    if (!titleSpan) return;
    const fileName = this.filePath.split('/').pop();
    const timeIdx = document.getElementById(`win-${this.id}-slider-time`)?.value || '0';
    const layerIdx = document.getElementById(`win-${this.id}-slider-layer`)?.value || '0';
    const nT = this.meta ? (this.meta.n_tsteps || 1) : 1;
    const nL = this.meta ? (this.meta.n_layers || 1) : 1;
    const tOp = document.getElementById(`win-${this.id}-sel-top`)?.value || 'select';
    const lOp = document.getElementById(`win-${this.id}-sel-lop`)?.value || 'select';

    const tDesc = tOp === 'select' ? `T=${parseInt(timeIdx) + 1}/${nT}` : `T=${tOp.toUpperCase()}`;
    const lDesc = lOp === 'select' ? `L=${parseInt(layerIdx) + 1}/${nL}` : `L=${lOp.toUpperCase()}`;
    const pol = data.pollutant || 'Emissions';

    titleSpan.textContent = `[#${this.id}] ${fileName} — ${pol} [${tDesc}, ${lDesc}]`;
  }

  renderStatsDisplay(data) {
    const box = document.getElementById(`win-${this.id}-stats-content`);
    if (!box) return;
    const s = data.stats || {};
    const fmt = (v) => (v === null || v === undefined) ? '-' : (Math.abs(v) < 1e-3 || Math.abs(v) > 1e4 ? v.toExponential(3) : v.toFixed(3));
    if (data.is_table) {
      box.innerHTML = `
        <div><b>Pollutant:</b> ${data.pollutant}</div>
        <div><b>Mode:</b> Tabular (${data.count} records)</div>
        <div><b>Min:</b> ${fmt(s.min)}</div>
        <div><b>Mean:</b> ${fmt(s.mean)}</div>
        <div><b>P50:</b> ${fmt(s.p50)}</div>
        <div><b>P95:</b> ${fmt(s.p95)}</div>
        <div><b>Max:</b> ${fmt(s.max)}</div>
        <div><b>Total:</b> ${fmt(s.sum)}</div>
      `;
    } else {
      box.innerHTML = `
        <div><b>Pollutant:</b> ${data.pollutant}</div>
        <div><b>Unit:</b> ${data.unit || 'unspecified'}</div>
        <div><b>Dims:</b> ${data.nrows} rows × ${data.ncols} cols</div>
        <div><b>Min:</b> ${fmt(s.min)}</div>
        <div><b>Mean:</b> ${fmt(s.mean)}</div>
        <div><b>Max:</b> ${fmt(s.max)}</div>
        <div><b>Total:</b> ${fmt(s.sum)}</div>
      `;
    }
  }

  redrawCanvas() {
    const canvas = document.getElementById(`win-${this.id}-map-canvas`);
    if (!canvas || !this.matrixData) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    const targetW = Math.floor(rect.width) || canvas.parentElement.clientWidth || 500;
    const targetH = Math.floor(rect.height) || canvas.parentElement.clientHeight || 350;

    if (targetW <= 0 || targetH <= 0) {
      requestAnimationFrame(() => this.redrawCanvas());
      return;
    }

    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const data = this.matrixData;
    if (data.is_county_map && this.cachedMapImage) {
      const img = this.cachedMapImage;
      const availW = canvas.width - 20;
      const availH = canvas.height - 20;
      const scale = Math.min(availW / img.width, availH / img.height) * this.zoom;
      const drawW = img.width * scale;
      const drawH = img.height * scale;
      const drawX = (canvas.width - drawW) / 2 + this.panX;
      const drawY = (canvas.height - drawH) / 2 + this.panY;
      ctx.drawImage(img, drawX, drawY, drawW, drawH);
      return;
    }

    // Gridded Heatmap
    const { nrows, ncols, matrix, stats } = data;
    if (!nrows || !ncols || !matrix) return;

    const minVal = stats.min !== undefined ? stats.min : 0;
    const maxVal = stats.max !== undefined ? stats.max : 1;
    const logMin = Math.log10(Math.max(1e-12, minVal > 0 ? minVal : 1e-4));
    const logMax = Math.log10(Math.max(1e-12, maxVal > 0 ? maxVal : 1));

    const padding = 20;
    const availW = canvas.width - padding * 2;
    const availH = canvas.height - padding * 2;
    const baseCellSize = Math.max(1, Math.min(availW / ncols, availH / nrows));
    const cellSize = baseCellSize * this.zoom;

    const gridPixelW = ncols * cellSize;
    const gridPixelH = nrows * cellSize;
    const originX = (canvas.width - gridPixelW) / 2 + this.panX;
    const originY = (canvas.height - gridPixelH) / 2 + this.panY;

    const showGridlines = document.getElementById(`win-${this.id}-chk-gridlines`)?.checked || false;
    const showBounds = document.getElementById(`win-${this.id}-chk-bounds`)?.checked ?? true;
    const showGraticule = document.getElementById(`win-${this.id}-chk-graticule`)?.checked ?? true;
    const isLog = document.getElementById(`win-${this.id}-chk-log`)?.checked || false;
    const cmapName = document.getElementById(`win-${this.id}-sel-cmap`)?.value || 'turbo';

    for (let r = 0; r < nrows; r++) {
      const y = originY + (nrows - 1 - r) * cellSize;
      if (y + cellSize < 0 || y > canvas.height) continue;
      for (let c = 0; c < ncols; c++) {
        const x = originX + c * cellSize;
        if (x + cellSize < 0 || x > canvas.width) continue;
        const val = matrix[r][c];
        let t = 0;
        if (maxVal > minVal) {
          if (isLog) {
            t = val > 0 ? (Math.log10(val) - logMin) / Math.max(1e-9, logMax - logMin) : 0;
          } else {
            t = (val - minVal) / (maxVal - minVal);
          }
        }
        const [cr, cg, cb] = getColormapRgb(t, cmapName);
        ctx.fillStyle = `rgb(${cr},${cg},${cb})`;
        ctx.fillRect(Math.floor(x), Math.floor(y), Math.ceil(cellSize), Math.ceil(cellSize));

        if (showGridlines && cellSize >= 6) {
          ctx.strokeStyle = 'rgba(0,0,0,0.12)';
          ctx.lineWidth = 0.5;
          ctx.strokeRect(Math.floor(x), Math.floor(y), Math.ceil(cellSize), Math.ceil(cellSize));
        }
      }
    }

    if (showBounds && data.boundaries && data.boundaries.length > 0) {
      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 1.2;
      data.boundaries.forEach(poly => {
        ctx.beginPath();
        poly.forEach(([c, r], idx) => {
          const px = originX + c * cellSize;
          const py = originY + (nrows - r) * cellSize;
          if (idx === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.stroke();
      });
    }

    if (showGraticule && data.graticules && data.graticules.length > 0) {
      data.graticules.forEach(grat => {
        ctx.strokeStyle = 'rgba(100, 116, 139, 0.45)';
        ctx.lineWidth = 0.8;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        grat.coords.forEach(([c, r], idx) => {
          const px = originX + c * cellSize;
          const py = originY + (nrows - r) * cellSize;
          if (idx === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.stroke();
        ctx.setLineDash([]);
        if (grat.coords.length > 0) {
          const midIdx = Math.floor(grat.coords.length / 2);
          const [mc, mr] = grat.coords[midIdx];
          const lx = originX + mc * cellSize;
          const ly = originY + (nrows - mr) * cellSize;
          if (lx >= originX && lx <= originX + gridPixelW && ly >= originY && ly <= originY + gridPixelH) {
            ctx.fillStyle = '#475569';
            ctx.font = '9px monospace';
            ctx.fillText(grat.label, lx + 3, ly - 3);
          }
        }
      });
    }

    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(originX, originY, gridPixelW, gridPixelH);

    if (this.selectedCell) {
      const selR = this.selectedCell.row;
      const selC = this.selectedCell.col;
      const hx = originX + (selC - 1) * cellSize;
      const hy = originY + (nrows - selR) * cellSize;
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 2;
      ctx.strokeRect(hx, hy, cellSize, cellSize);
    }

    // ── Modern Vertical Color Scale Bar ──
    const cbW = 14;
    const cbH = Math.min(Math.max(120, canvas.height - 100), 260);
    const cbX = canvas.width - cbW - 75;
    const cbY = Math.round((canvas.height - cbH) / 2);

    if (cbX > 80 && cbH > 60) {
      // Backdrop panel
      ctx.fillStyle = 'rgba(255, 255, 255, 0.92)';
      ctx.strokeStyle = '#cbd5e1';
      ctx.lineWidth = 1;
      const padW = cbW + 68;
      const padH = cbH + 34;
      ctx.fillRect(cbX - 6, cbY - 18, padW, padH);
      ctx.strokeRect(cbX - 6, cbY - 18, padW, padH);

      // Color gradient bar
      for (let py = 0; py < cbH; py++) {
        const t = 1 - py / cbH; // top is maxVal, bottom is minVal
        const [cr, cg, cb] = getColormapRgb(t, cmapName);
        ctx.fillStyle = `rgb(${cr},${cg},${cb})`;
        ctx.fillRect(cbX, cbY + py, cbW, 1);
      }
      ctx.strokeStyle = '#475569';
      ctx.lineWidth = 1;
      ctx.strokeRect(cbX, cbY, cbW, cbH);

      // Scale unit / mode header
      ctx.fillStyle = '#0f172a';
      ctx.font = 'bold 9px sans-serif';
      ctx.textAlign = 'left';
      const scaleHeader = isLog ? 'Log Scale' : (data.unit || 'Value');
      ctx.fillText(scaleHeader, cbX - 2, cbY - 7);

      // Ticks and labels (5 equidistant ticks: 100%, 75%, 50%, 25%, 0%)
      ctx.font = '9px monospace';
      ctx.fillStyle = '#334155';
      const ticks = [
        { frac: 1.0, py: cbY },
        { frac: 0.75, py: cbY + cbH * 0.25 },
        { frac: 0.50, py: cbY + cbH * 0.50 },
        { frac: 0.25, py: cbY + cbH * 0.75 },
        { frac: 0.0, py: cbY + cbH }
      ];

      ticks.forEach(({ frac, py }) => {
        // Tick mark
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(cbX + cbW, py);
        ctx.lineTo(cbX + cbW + 4, py);
        ctx.stroke();

        // Tick value label
        let valAtTick = 0;
        if (isLog) {
          const lVal = logMin + frac * (logMax - logMin);
          valAtTick = Math.pow(10, lVal);
        } else {
          valAtTick = minVal + frac * (maxVal - minVal);
        }

        const lblStr = Math.abs(valAtTick) < 1e-3 || Math.abs(valAtTick) >= 1e4 ? valAtTick.toExponential(1) : (valAtTick < 10 ? valAtTick.toFixed(2) : valAtTick.toFixed(1));
        ctx.fillText(lblStr, cbX + cbW + 6, py + 3);
      });
    }
  }

  resetMapZoom() {
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    const data = this.matrixData;
    if (data && data.is_county_map && this.zoomToData) {
      console.info(`[SMKPLOT-WEB #${this.id}] Resetting county view to full extent (zoom_to_data=false)`);
      this.zoomToData = false;
      this.renderSlice();
      return;
    }
    this.redrawCanvas();
  }

  zoomToDataExtent(force) {
    const data = this.matrixData;
    if (!data) {
      console.warn(`[SMKPLOT-WEB #${this.id}] Cannot zoom: No matrixData loaded.`);
      return;
    }

    if (data.is_county_map) {
      this.zoom = 1;
      this.panX = 0;
      this.panY = 0;
      const targetState = (typeof force === 'boolean') ? force : true;
      if (this.zoomToData === targetState) {
        console.info(`[SMKPLOT-WEB #${this.id}] County zoom_to_data already ${targetState}`);
        return;
      }
      this.zoomToData = targetState;
      console.info(`[SMKPLOT-WEB #${this.id}] County Map Zoom-to-Data Extent set to: ${this.zoomToData}`);
      this.renderSlice();
      return;
    }

    const { nrows, ncols, matrix } = data;
    if (!nrows || !ncols || !matrix) {
      console.warn(`[SMKPLOT-WEB #${this.id}] Cannot zoom: Matrix shape missing.`, { nrows, ncols });
      return;
    }

    let minR = nrows, maxR = -1, minC = ncols, maxC = -1;
    let nonZeroCount = 0;
    for (let r = 0; r < nrows; r++) {
      for (let c = 0; c < ncols; c++) {
        if (matrix[r][c] > 0) {
          nonZeroCount++;
          if (r < minR) minR = r;
          if (r > maxR) maxR = r;
          if (c < minC) minC = c;
          if (c > maxC) maxC = c;
        }
      }
    }

    console.info(`[SMKPLOT-WEB #${this.id}] Grid Zoom Scan: nonZeroCells=${nonZeroCount}, bbox: Col[${minC + 1}..${maxC + 1}], Row[${minR + 1}..${maxR + 1}] of [${ncols}x${nrows}]`);

    if (maxR < minR || maxC < minC || nonZeroCount === 0) {
      console.info(`[SMKPLOT-WEB #${this.id}] No positive emission cells found. Resetting zoom.`);
      this.resetMapZoom();
      return;
    }

    const canvas = document.getElementById(`win-${this.id}-map-canvas`);
    if (!canvas) return;
    const padding = 24;
    const availW = canvas.width - padding * 2;
    const availH = canvas.height - padding * 2;
    const baseCellSize = Math.max(1, Math.min(availW / ncols, availH / nrows));

    const dataCols = Math.max(1, (maxC - minC + 1));
    const dataRows = Math.max(1, (maxR - minR + 1));
    const zoomFactorX = (availW * 0.9) / (dataCols * baseCellSize);
    const zoomFactorY = (availH * 0.9) / (dataRows * baseCellSize);
    const targetZoom = Math.max(1, Math.min(50, Math.min(zoomFactorX, zoomFactorY)));

    this.zoom = targetZoom;
    const cellSize = baseCellSize * targetZoom;
    const bboxCenterCol = (minC + maxC) / 2;
    const bboxCenterRow = (minR + maxR) / 2;

    this.panX = - (bboxCenterCol - (ncols - 1) / 2) * cellSize;
    this.panY = - ((nrows - 1 - bboxCenterRow) - (nrows - 1) / 2) * cellSize;
    console.info(`[SMKPLOT-WEB #${this.id}] Applied grid zoom: scale=${targetZoom.toFixed(2)}x, pan=(${this.panX.toFixed(1)}, ${this.panY.toFixed(1)})`);
    this.redrawCanvas();
  }

  savePlotImage() {
    const data = this.matrixData;
    if (!data) {
      alert('No plot data available to save.');
      return;
    }
    const pol = (data.pollutant || 'emissions').replace(/[^a-zA-Z0-9_-]/g, '_');
    const fileName = `${pol}_plot.png`;

    if (data.is_county_map && data.map_image) {
      const link = document.createElement('a');
      link.download = fileName;
      link.href = `data:image/png;base64,${data.map_image}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      console.info(`[SMKPLOT-WEB #${this.id}] Saved high-res county map: ${fileName}`);
      return;
    }

    const canvas = document.getElementById(`win-${this.id}-map-canvas`);
    if (!canvas) return;
    try {
      const link = document.createElement('a');
      link.download = fileName;
      link.href = canvas.toDataURL('image/png');
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      console.info(`[SMKPLOT-WEB #${this.id}] Saved canvas plot: ${fileName}`);
    } catch (err) {
      console.error(`[SMKPLOT-WEB #${this.id}] Failed to save plot:`, err);
      alert(`Could not export plot image: ${err}`);
    }
  }

  getCellAtMouse(e) {
    const canvas = document.getElementById(`win-${this.id}-map-canvas`);
    if (!canvas || !this.matrixData) return null;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;

    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const mouseY = (e.clientY - rect.top) * scaleY;

    const { nrows, ncols } = this.matrixData;
    if (!nrows || !ncols) return null;
    const padding = 20;
    const availW = canvas.width - padding * 2;
    const availH = canvas.height - padding * 2;
    const baseCellSize = Math.max(1, Math.min(availW / ncols, availH / nrows));
    const cellSize = baseCellSize * this.zoom;

    const gridPixelW = ncols * cellSize;
    const gridPixelH = nrows * cellSize;
    const originX = (canvas.width - gridPixelW) / 2 + this.panX;
    const originY = (canvas.height - gridPixelH) / 2 + this.panY;

    const colIdx = Math.floor((mouseX - originX) / cellSize);
    const rowInverted = Math.floor((mouseY - originY) / cellSize);
    const rowIdx = (nrows - 1) - rowInverted;

    if (colIdx >= 0 && colIdx < ncols && rowIdx >= 0 && rowIdx < nrows) {
      return { valid: true, row: rowIdx + 1, col: colIdx + 1, r0: rowIdx, c0: colIdx };
    }
    return { valid: false, colIdx, rowIdx, nrows, ncols };
  }

  initCanvasEvents() {
    const canvas = this.container ? this.container.querySelector('.plot-canvas') : document.getElementById(`win-${this.id}-map-canvas`);
    if (!canvas) {
      console.error(`[SMKPLOT-DEBUG #${this.id}] Cannot find canvas element to attach listeners.`);
      return;
    }
    console.info(`[SMKPLOT-DEBUG #${this.id}] Attaching mouse listeners to canvas:`, canvas.id);

    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 0.85;
      this.zoom = Math.min(50, Math.max(0.5, this.zoom * factor));
      console.info(`[SMKPLOT-DEBUG #${this.id}] Wheel zoom: ${this.zoom.toFixed(2)}x`);
      this.redrawCanvas();
    }, { passive: false });

    canvas.addEventListener('mousedown', (e) => {
      this.isDragging = true;
      this.dragStartX = e.clientX - this.panX;
      this.dragStartY = e.clientY - this.panY;
    });

    window.addEventListener('mouseup', () => {
      this.isDragging = false;
    });

    canvas.addEventListener('mousemove', (e) => {
      if (this.isDragging) {
        this.panX = e.clientX - this.dragStartX;
        this.panY = e.clientY - this.dragStartY;
        this.redrawCanvas();
      }
      this.updateCellHoverInfo(e);
    });

    canvas.addEventListener('click', (e) => {
      const cell = this.getCellAtMouse(e);
      if (cell && cell.valid) {
        console.info(`[SMKPLOT-DEBUG #${this.id}] Clicked cell: [Row ${cell.row}, Col ${cell.col}]`);
        this.selectedCell = { row: cell.row, col: cell.col };
        this.redrawCanvas();
        this.loadCellProfile(cell.row, cell.col);
      }
    });
  }

  updateCellHoverInfo(e) {
    const badge = document.getElementById(`win-${this.id}-cell-badge`) || (this.container ? this.container.querySelector(`#win-${this.id}-cell-badge`) : null);
    if (!badge) {
      return;
    }

    if (!this.matrixData) {
      badge.textContent = 'Hover over data to inspect emissions & coordinates';
      return;
    }

    const canvas = this.container ? this.container.querySelector('.plot-canvas') : document.getElementById(`win-${this.id}-map-canvas`);

    // Tabular / County Datasets (e.g., FF10, SMKREPORT, County CSV)
    if (this.matrixData.is_county_map || !this.matrixData.matrix) {
      if (this.matrixData.is_county_map && this.cachedMapImage && this.matrixData.county_features && this.matrixData.map_extent && canvas) {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const mouseCanvasX = (e.clientX - rect.left) * scaleX;
        const mouseCanvasY = (e.clientY - rect.top) * scaleY;

        const img = this.cachedMapImage;
        const availW = canvas.width - 20;
        const availH = canvas.height - 20;
        const scale = Math.min(availW / img.width, availH / img.height) * this.zoom;
        const drawW = img.width * scale;
        const drawH = img.height * scale;
        const drawX = (canvas.width - drawW) / 2 + this.panX;
        const drawY = (canvas.height - drawH) / 2 + this.panY;

        // Map mouse position to image normalized [0..1]
        const imgNormX = (mouseCanvasX - drawX) / drawW;
        const imgNormY = (mouseCanvasY - drawY) / drawH;

        if (imgNormX >= 0 && imgNormX <= 1 && imgNormY >= 0 && imgNormY <= 1) {
          const [minX, maxX, minY, maxY] = this.matrixData.map_extent;
          const dataX = minX + imgNormX * (maxX - minX);
          const dataY = maxY - imgNormY * (maxY - minY);

          const hit = this.matrixData.county_features.find(feat => {
            const [bx1, by1, bx2, by2] = feat.bbox;
            return dataX >= bx1 && dataX <= bx2 && dataY >= by1 && dataY <= by2;
          });

          if (hit) {
            const pol = this.matrixData.pollutant || 'Emissions';
            const fVal = Math.abs(hit.val) < 1e-3 || Math.abs(hit.val) > 1e4 ? hit.val.toExponential(4) : hit.val.toFixed(4);
            const countyLabel = hit.name ? `${hit.name}${hit.state ? ', ' + hit.state : ''}` : `County`;
            badge.textContent = `📍 ${countyLabel} (FIPS: ${hit.fips}) ➔ ${pol}: ${fVal}`;
            return;
          }
        }
      }

      const stats = this.matrixData.stats || {};
      const count = this.matrixData.count || (stats.nonzero_count ? stats.nonzero_count : '–');
      const pol = this.matrixData.pollutant || 'Emissions';
      const maxStr = (stats.max !== undefined) ? ` | Max: ${Math.abs(stats.max) > 1e4 ? stats.max.toExponential(2) : stats.max.toFixed(2)}` : '';
      const sumStr = (stats.sum !== undefined) ? ` | Total: ${Math.abs(stats.sum) > 1e4 ? stats.sum.toExponential(2) : stats.sum.toFixed(2)}` : '';
      const nzStr = (stats.nonzero_count !== undefined) ? ` (Non-zero: ${stats.nonzero_count})` : '';
      badge.textContent = `${pol}: ${count} records${nzStr}${maxStr}${sumStr} | Zoom: ${this.zoom.toFixed(2)}x`;
      return;
    }

    // Gridded NetCDF Datasets
    const cell = this.getCellAtMouse(e);
    if (!cell || !cell.valid) {
      badge.textContent = `Grid [${this.matrixData.nrows}×${this.matrixData.ncols}] ➔ Hover inside grid cells to inspect`;
      return;
    }

    const val = this.matrixData.matrix[cell.r0][cell.c0];
    const unit = this.matrixData.unit || '';
    const fmtVal = (Math.abs(val) < 1e-3 || Math.abs(val) > 1e4) ? val.toExponential(4) : val.toFixed(4);

    let coordTxt = '';
    const g = (this.matrixData && this.matrixData.grid) || (this.meta && this.meta.grid);
    if (g) {
      const xorig = g.xorig !== undefined ? Number(g.xorig) : (g.XORIG !== undefined ? Number(g.XORIG) : null);
      const yorig = g.yorig !== undefined ? Number(g.yorig) : (g.YORIG !== undefined ? Number(g.YORIG) : null);
      const xcell = g.xcell !== undefined ? Number(g.xcell) : (g.XCELL !== undefined ? Number(g.XCELL) : null);
      const ycell = g.ycell !== undefined ? Number(g.ycell) : (g.YCELL !== undefined ? Number(g.YCELL) : null);

      if (xorig !== null && xcell !== null && !isNaN(xorig) && !isNaN(xcell)) {
        const xCoord = xorig + (cell.col - 0.5) * xcell;
        const yCoord = yorig + (cell.row - 0.5) * ycell;

        // Convert LCC meters to Longitude / Latitude degrees
        const coordP = g.coord_p || (this.meta && this.meta.grid && this.meta.grid.coord_p);
        if (coordP && coordP.length >= 6) {
          const degCoords = this.lccToLonLat(xCoord, yCoord, coordP);
          if (degCoords) {
            const lonStr = `${Math.abs(degCoords.lon).toFixed(4)}°${degCoords.lon < 0 ? 'W' : 'E'}`;
            const latStr = `${Math.abs(degCoords.lat).toFixed(4)}°${degCoords.lat < 0 ? 'S' : 'N'}`;
            coordTxt = ` | ${lonStr}, ${latStr}`;
          }
        }
        if (!coordTxt) {
          coordTxt = ` | X: ${Math.round(xCoord).toLocaleString()}m, Y: ${Math.round(yCoord).toLocaleString()}m`;
        }
      }
    }
    badge.textContent = `Cell [R:${cell.row}, C:${cell.col}${coordTxt}] ➔ ${fmtVal} ${unit}`;
  }

  lccToLonLat(x, y, coordP) {
    try {
      const lat1 = Number(coordP[1]);
      const lat2 = Number(coordP[2]);
      const lon0 = Number(coordP[3]);
      const lat0 = Number(coordP[5]);
      const a = 6370000.0;
      const rad = Math.PI / 180.0;
      const deg = 180.0 / Math.PI;

      const phi1 = lat1 * rad;
      const phi2 = lat2 * rad;
      const phi0 = lat0 * rad;
      const lam0 = lon0 * rad;

      let n;
      if (Math.abs(lat1 - lat2) < 1e-9) {
        n = Math.sin(phi1);
      } else {
        n = Math.log(Math.cos(phi1) / Math.cos(phi2)) / Math.log(Math.tan(Math.PI / 4 + phi2 / 2) / Math.tan(Math.PI / 4 + phi1 / 2));
      }

      const f = (Math.cos(phi1) * Math.pow(Math.tan(Math.PI / 4 + phi1 / 2), n)) / n;
      const rho0 = a * f * Math.pow(Math.tan(Math.PI / 4 + phi0 / 2), -n);

      let xp = x;
      let yp = rho0 - y;
      let rho = Math.hypot(xp, yp);

      if (n < 0) {
        rho = -rho;
        xp = -xp;
        yp = -yp;
      }

      const theta = Math.atan2(xp, yp);
      const lon = (lam0 + theta / n) * deg;
      const lat = (2.0 * Math.atan(Math.pow((a * f) / rho, 1.0 / n)) - Math.PI / 2.0) * deg;

      if (!isNaN(lon) && !isNaN(lat) && isFinite(lon) && isFinite(lat)) {
        return { lon, lat };
      }
    } catch (err) {
      console.warn('[SMKPLOT] LCC transform error:', err);
    }
    return null;
  }

  async loadCellProfile(row, col) {
    if (!this.filePath) return;
    const pollutant = document.getElementById(`win-${this.id}-formula-input`)?.value.trim() || '';

    const tsTitle = document.getElementById(`win-${this.id}-profile-ts-title`);
    const vTitle = document.getElementById(`win-${this.id}-profile-v-title`);
    if (tsTitle) tsTitle.textContent = `24-hr Time Series @ [R:${row}, C:${col}]`;
    if (vTitle) vTitle.textContent = `Vertical Profile @ [R:${row}, C:${col}]`;

    try {
      const params = new URLSearchParams({
        path: this.filePath,
        pollutant: pollutant,
        row: row,
        col: col
      });
      const res = await fetch(`/api/smkplot/profile?${params.toString()}`);
      const data = await res.json();
      if (data.error) return;

      drawLineChart(`win-${this.id}-chart-ts`, data.timeseries, 'Hour', data.unit || '');
      drawLineChart(`win-${this.id}-chart-v`, data.vertical || data.vertical_profile, 'Layer', data.unit || '');
    } catch (err) {
      console.error('Failed to load profile:', err);
    }
  }
}

async function launchSmkplot(filePath) {
  const container = document.getElementById('smkplot-multi-container');
  if (!container) return;

  const winId = ++smkplotWinCounter;
  const instance = new SmkplotWindowInstance(winId, filePath);
  smkplotWindows.set(winId, instance);

  const openCount = smkplotWindows.size;
  const screenW = window.innerWidth;
  const screenH = window.innerHeight;
  let winW = Math.max(620, Math.floor(screenW * 0.48));
  let winH = Math.max(480, Math.floor(screenH * 0.82));
  let leftPos = 40 + ((openCount - 1) % 5) * 45;
  let topPos = 40 + ((openCount - 1) % 5) * 40;

  if (openCount === 2) {
    leftPos = Math.max(20, screenW - winW - 20);
    topPos = 40;
  }

  const dom = instance.createDOM(leftPos, topPos, winW, winH);
  container.appendChild(dom);
  instance.initCanvasEvents();

  try {
    const res = await fetch(`/api/smkplot/load?path=${encodeURIComponent(filePath)}`);
    const data = await res.json();
    if (data.error) {
      alert(`SMKPLOT Load Error: ${data.error}`);
      instance.close();
      return;
    }
    instance.meta = data;

    const selPol = document.getElementById(`win-${winId}-sel-pol`);
    selPol.innerHTML = '';
    (data.pollutants || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p;
      selPol.appendChild(opt);
    });

    const formulaInput = document.getElementById(`win-${winId}-formula-input`);
    if (data.pollutants && data.pollutants.length > 0) {
      formulaInput.value = data.pollutants[0];
    } else {
      formulaInput.value = '';
    }

    const dimControls = document.getElementById(`win-${winId}-dim-controls`);
    if (dimControls) {
      dimControls.style.display = data.is_netcdf ? 'flex' : 'none';
    }

    const tSlider = document.getElementById(`win-${winId}-slider-time`);
    const lSlider = document.getElementById(`win-${winId}-slider-layer`);
    if (data.is_netcdf && data.dims) {
      tSlider.min = 0;
      tSlider.max = Math.max(0, (data.dims.n_tsteps || 1) - 1);
      tSlider.value = 0;
      document.getElementById(`win-${winId}-lbl-tstep`).textContent = `T=1 / ${data.dims.n_tsteps || 1}`;

      lSlider.min = 0;
      lSlider.max = Math.max(0, (data.dims.n_layers || 1) - 1);
      lSlider.value = 0;
      document.getElementById(`win-${winId}-lbl-layer`).textContent = `L=1 / ${data.dims.n_layers || 1}`;
    }

    clearProfileCanvas(`win-${winId}-chart-ts`);
    clearProfileCanvas(`win-${winId}-chart-v`);
    const badge = document.getElementById(`win-${winId}-cell-badge`);
    if (data.is_netcdf) {
      if (badge) badge.textContent = 'Hover over cells to inspect coordinates & emissions';
    } else {
      if (badge) badge.textContent = `Tabular dataset: ${filePath.split('/').pop()}`;
    }

    await instance.renderSlice();
    if (instance.matrixData && !instance.matrixData.is_county_map) {
      instance.zoomToDataExtent();
    }
  } catch (err) {
    console.error(`[SMKPLOT] Failed to load file for plotting:`, err);
    alert(`Failed to load file for plotting: ${err}`);
  }
}

function clearProfileCanvas(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function drawLineChart(canvasId, series, xLabel, unit) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width) || 200;
  canvas.height = Math.floor(rect.height) || 90;

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!series || series.length === 0) {
    ctx.fillStyle = '#64748b';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No data at this point', canvas.width / 2, canvas.height / 2);
    ctx.textAlign = 'left';
    return;
  }

  const padLeft = 40;
  const padBottom = 20;
  const padTop = 10;
  const padRight = 10;
  const w = Math.max(10, canvas.width - padLeft - padRight);
  const h = Math.max(10, canvas.height - padTop - padBottom);

  const minVal = Math.min(...series);
  const maxVal = Math.max(...series);
  const isFlat = (maxVal - minVal) === 0;
  const range = isFlat ? (maxVal === 0 ? 1 : Math.abs(maxVal)) : (maxVal - minVal);

  // Background grid
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padLeft, padTop + h);
  ctx.lineTo(padLeft + w, padTop + h);
  ctx.stroke();

  // Draw Line
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 2;
  ctx.beginPath();
  series.forEach((val, idx) => {
    const x = series.length === 1 ? padLeft + w / 2 : padLeft + (idx / Math.max(1, series.length - 1)) * w;
    const norm = isFlat ? (maxVal === 0 ? 0 : 0.5) : (val - minVal) / range;
    const y = padTop + h - norm * h;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Draw points
  ctx.fillStyle = '#f59e0b';
  series.forEach((val, idx) => {
    const x = series.length === 1 ? padLeft + w / 2 : padLeft + (idx / Math.max(1, series.length - 1)) * w;
    const norm = isFlat ? (maxVal === 0 ? 0 : 0.5) : (val - minVal) / range;
    const y = padTop + h - norm * h;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });

  // Axis labels
  ctx.fillStyle = '#64748b';
  ctx.font = '9px monospace';
  const fmt = (v) => (Math.abs(v) < 1e-2 || Math.abs(v) > 1e4) ? v.toExponential(1) : v.toFixed(2);
  ctx.fillText(fmt(maxVal), 4, padTop + 8);
  ctx.fillText(fmt(minVal), 4, padTop + h);
  ctx.fillText(`${xLabel} 1..${series.length}${unit ? ' (' + unit + ')' : ''}`, padLeft, canvas.height - 4);
}
