#!/proj/ie/proj/SMOKE/htran/Emission_Modeling_Platform/utils/smkplot/.venv/bin/python
"""
smkplot_web_engine.py
=====================
Headless backend engine executing directly inside the smkplot virtualenv.
Invokes smkplot data processing and NetCDF modules to serve the interactive
Web GUI in smkrun_web without any X11 display requirement.
"""

import os
import sys
import json
import logging
import argparse
import numpy as np
import pandas as pd

import pyproj
import geopandas as gpd
from shapely.geometry import box, LineString, MultiLineString

import io
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Direct all standard logger output to stderr so stdout is pure JSON
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")

# Add smkplot repository to path
SMKPLOT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "smkplot"))
if SMKPLOT_DIR not in sys.path:
    sys.path.insert(0, SMKPLOT_DIR)

from data_processing import read_inputfile, detect_pollutants, is_netcdf_file, read_shpfile, merge_emissions_with_geometry, get_emis_fips
from ncf_processing import (
    read_ncf_grid_params, read_ncf_emissions, get_ncf_dims,
    get_ncf_timeseries, get_ncf_profile, get_proj_object_from_info
)
from smkplot import _parse_pollutant_with_formulas
from plotting import create_map_plot, _plot_crs
from config import DEFAULT_ONLINE_COUNTIES_URL
DEFAULT_ONLINE_STATES_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_state_500k.zip"

def _get_crs_from_coord_p(coord_p):
    gdtyp, p_alp, p_bet, p_gam, xcent, ycent = coord_p
    gi = {
        'proj_type': gdtyp,
        'p_alp': p_alp,
        'p_bet': p_bet,
        'p_gam': p_gam,
        'xcent': xcent,
        'ycent': ycent
    }
    return get_proj_object_from_info(gi)

# Cache overlays in memory by grid projection signature to avoid reprojecting shapefiles on every timestep
_OVERLAYS_CACHE = {}

def _extract_map_overlays(coord_p, grid_p):
    """Generate state boundary polylines and graticule lines in grid cell coordinates [0..ncols, 0..nrows]."""
    cache_key = (tuple(coord_p) if coord_p else None, tuple(grid_p) if grid_p else None)
    if cache_key in _OVERLAYS_CACHE:
        return _OVERLAYS_CACHE[cache_key]
    try:
        _, xorig, yorig, xcell, ycell, ncols, nrows, _ = grid_p
        crs_lcc = _get_crs_from_coord_p(coord_p)
        tf_to_lcc = pyproj.Transformer.from_crs(pyproj.CRS.from_epsg(4326), crs_lcc, always_xy=True)
        tf_to_latlon = pyproj.Transformer.from_crs(crs_lcc, pyproj.CRS.from_epsg(4326), always_xy=True)

        min_x, max_x = xorig, xorig + ncols * xcell
        min_y, max_y = yorig, yorig + nrows * ycell

        # 1. Graticules: transform bounding box corners to lon/lat
        cx = [min_x, max_x, max_x, min_x]
        cy = [min_y, min_y, max_y, max_y]
        lons, lats = tf_to_latlon.transform(cx, cy)
        lon_min, lon_max = min(lons), max(lons)
        lat_min, lat_max = min(lats), max(lats)

        # Lon / Lat step increments
        lon_span = lon_max - lon_min
        lat_span = lat_max - lat_min
        lon_step = 2.0 if lon_span > 8 else (1.0 if lon_span > 3 else 0.5)
        lat_step = 2.0 if lat_span > 8 else (1.0 if lat_span > 3 else 0.5)

        graticules = []
        # Meridians (longitude lines)
        cur_lon = np.floor(lon_min / lon_step) * lon_step
        while cur_lon <= lon_max + lon_step:
            pts_lat = np.linspace(lat_min - 1, lat_max + 1, 30)
            pts_lon = np.full_like(pts_lat, cur_lon)
            gx, gy = tf_to_lcc.transform(pts_lon, pts_lat)
            # Transform to grid unit coordinates [0..ncols, 0..nrows]
            gc = (gx - xorig) / xcell
            gr = (gy - yorig) / ycell
            coords = [[round(float(c), 3), round(float(r), 3)] for c, r in zip(gc, gr)]
            label = f"{abs(int(round(cur_lon)))}°{'W' if cur_lon < 0 else 'E'}"
            graticules.append({"type": "meridian", "label": label, "val": cur_lon, "coords": coords})
            cur_lon += lon_step

        # Parallels (latitude lines)
        cur_lat = np.floor(lat_min / lat_step) * lat_step
        while cur_lat <= lat_max + lat_step:
            pts_lon = np.linspace(lon_min - 1, lon_max + 1, 30)
            pts_lat = np.full_like(pts_lon, cur_lat)
            gx, gy = tf_to_lcc.transform(pts_lon, pts_lat)
            gc = (gx - xorig) / xcell
            gr = (gy - yorig) / ycell
            coords = [[round(float(c), 3), round(float(r), 3)] for c, r in zip(gc, gr)]
            label = f"{abs(int(round(cur_lat)))}°{'S' if cur_lat < 0 else 'N'}"
            graticules.append({"type": "parallel", "label": label, "val": cur_lat, "coords": coords})
            cur_lat += lat_step

        # 2. State Boundaries
        boundaries = []
        try:
            gdf = read_shpfile(DEFAULT_ONLINE_STATES_URL, False)
        except Exception as e:
            gdf = None
            logging.warning(f"Could not load state shapefile: {e}")

        if gdf is not None and not gdf.empty:
                gdf_lcc = gdf.to_crs(crs_lcc)
                # Clip to bounding box expanded by 10%
                pad_x = (max_x - min_x) * 0.1
                pad_y = (max_y - min_y) * 0.1
                clip_box = box(min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)
                clipped = gdf_lcc.clip(clip_box)
                for geom in clipped.geometry:
                    if geom is None or geom.is_empty:
                        continue
                    lines = [geom.boundary] if hasattr(geom, "boundary") else [geom]
                    for ln in lines:
                        if isinstance(ln, MultiLineString):
                            sublines = ln.geoms
                        elif isinstance(ln, LineString):
                            sublines = [ln]
                        else:
                            continue
                        for sl in sublines:
                            xs, ys = sl.xy
                            gc = (np.array(xs) - xorig) / xcell
                            gr = (np.array(ys) - yorig) / ycell
                            pts = [[round(float(c), 3), round(float(r), 3)] for c, r in zip(gc, gr)]
                            if len(pts) > 1:
                                boundaries.append(pts)

        res = {"graticules": graticules, "boundaries": boundaries}
        _OVERLAYS_CACHE[cache_key] = res
        return res
    except Exception as e:
        logging.warning(f"Overlay generation error: {e}")
        return {"graticules": [], "boundaries": []}


def handle_load(fpath: str):
    if not os.path.exists(fpath):
        return {"error": f"File not found: {fpath}"}

    is_nc = is_netcdf_file(fpath)
    result = {
        "filepath": fpath,
        "basename": os.path.basename(fpath),
        "is_netcdf": is_nc,
        "pollutants": [],
        "dims": {},
        "grid": {}
    }

    if is_nc:
        try:
            dims = get_ncf_dims(fpath)
            coord_p, grid_p = read_ncf_grid_params(fpath)
            # grid_p: (GDNAM, XORIG, YORIG, XCELL, YCELL, NCOLS, NROWS, NTHIK)
            result["dims"] = {
                "n_tsteps": dims.get("n_tsteps", 1),
                "n_layers": dims.get("n_layers", 1),
                "tflags": dims.get("tflag_values", [])
            }
            result["grid"] = {
                "gdnam": grid_p[0],
                "xorig": grid_p[1],
                "yorig": grid_p[2],
                "xcell": grid_p[3],
                "ycell": grid_p[4],
                "ncols": grid_p[5],
                "nrows": grid_p[6],
                "coord_p": list(coord_p) if coord_p is not None else None
            }
            # Detect available pollutants from first slice
            sample_df = read_ncf_emissions(fpath, layer_idx=0, tstep_idx=0, lazy=True)
            result["pollutants"] = detect_pollutants(sample_df)
            
            # If smkplot converted inline point sources to 2D grid, use the true spatial grid metadata
            if hasattr(sample_df, "attrs") and "_smk_grid_info" in sample_df.attrs:
                gi = sample_df.attrs["_smk_grid_info"]
                result["grid"]["ncols"] = gi["ncols"]
                result["grid"]["nrows"] = gi["nrows"]
                result["grid"]["xorig"] = gi["xorig"]
                result["grid"]["yorig"] = gi["yorig"]
                result["grid"]["xcell"] = gi["xcell"]
                result["grid"]["ycell"] = gi["ycell"]
        except Exception as e:
            result["error"] = f"Failed to inspect NetCDF: {str(e)}"
    else:
        try:
            df, raw = read_inputfile(fpath)
            result["pollutants"] = detect_pollutants(df)
            result["dims"] = {"n_tsteps": 1, "n_layers": 1}
            cols_lower = [c.lower() for c in df.columns]
            has_grid = ("x cell" in cols_lower and "y cell" in cols_lower) or ("row" in cols_lower and "col" in cols_lower)
            has_county = any(c in cols_lower for c in ("fips", "region", "region_cd", "county", "#county"))
            pltyps = ["auto"]
            if has_grid:
                pltyps.append("grid")
            if has_county:
                pltyps.append("county")
            result["available_pltyps"] = pltyps
            result["has_grid"] = has_grid
            result["has_county"] = has_county
        except Exception as e:
            result["error"] = f"Failed to read file: {str(e)}"

    return result


def handle_slice(fpath: str, pol_req: str, t_idx: int = 0, l_idx: int = 0, t_op: str = "select", l_op: str = "select", cmap: str = "turbo", log_scale: bool = False, zoom_to_data: bool = False, pltyp: str = "auto", skip_overlays: bool = False):
    if not os.path.exists(fpath):
        return {"error": f"File not found: {fpath}"}

    is_nc = is_netcdf_file(fpath)
    pol_list, formulas = _parse_pollutant_with_formulas(pol_req)
    if not pol_list:
        pol_list = [pol_req.strip()]

    target_pol = pol_list[0]

    # Required raw pollutants to read
    raw_pols = []
    if target_pol in formulas:
        rhs = formulas[target_pol]
        import re
        tokens = re.findall(r'[A-Za-z0-9_.\-]+', rhs)
        raw_pols = [t for t in tokens if not t.replace('.', '', 1).isdigit()]
    else:
        raw_pols = [target_pol]

    if is_nc:
        try:
            coord_p, grid_p = read_ncf_grid_params(fpath)
            ncols, nrows = grid_p[5], grid_p[6]
            n_dims = get_ncf_dims(fpath)
            tot_tsteps = n_dims.get("n_tsteps", 1)
            tot_layers = n_dims.get("n_layers", 1)

            # Read emissions using smkplot's native reader (auto-detects inline files & maps via STACK_GROUPS)
            df = read_ncf_emissions(
                fpath,
                pollutants=raw_pols,
                layer_idx=l_idx if l_op == "select" else None,
                tstep_idx=t_idx if t_op == "select" else None,
                layer_op=l_op,
                tstep_op=t_op
            )

            # Check if smkplot mapped an inline point file to a 2D spatial grid
            if hasattr(df, "attrs") and "_smk_grid_info" in df.attrs:
                gi = df.attrs["_smk_grid_info"]
                ncols, nrows = gi["ncols"], gi["nrows"]
                grid_p = (
                    grid_p[0],
                    gi["xorig"],
                    gi["yorig"],
                    gi["xcell"],
                    gi["ycell"],
                    ncols,
                    nrows,
                    grid_p[7] if len(grid_p) > 7 else 1
                )

            # Evaluate formula if requested
            if target_pol in formulas:
                rhs = formulas[target_pol]
                # evaluate using safe pandas eval
                df[target_pol] = df.eval(rhs)

            if target_pol not in df.columns:
                return {"error": f"Pollutant '{target_pol}' not found in dataset"}

            # Build 2D matrix
            matrix = np.zeros((nrows, ncols), dtype=np.float32)
            if "ROW" in df.columns and "COL" in df.columns:
                r_idx = df["ROW"].values.astype(int) - 1
                c_idx = df["COL"].values.astype(int) - 1
                vals = df[target_pol].values.astype(np.float32)
                valid = (r_idx >= 0) & (r_idx < nrows) & (c_idx >= 0) & (c_idx < ncols)
                matrix[r_idx[valid], c_idx[valid]] = vals[valid]
            else:
                # Flat sequential grid
                vals = df[target_pol].values.astype(np.float32)
                if len(vals) == nrows * ncols:
                    matrix = vals.reshape((nrows, ncols))

            # Statistics
            flat = matrix.flatten()
            nz = flat[flat > 0]
            stats = {
                "min": float(np.min(flat)),
                "max": float(np.max(flat)),
                "mean": float(np.mean(flat)),
                "sum": float(np.sum(flat)),
                "nonzero_count": int(len(nz)),
                "p50": float(np.percentile(flat, 50)) if len(flat) else 0.0,
                "p95": float(np.percentile(flat, 95)) if len(flat) else 0.0
            }

            overlays = {} if skip_overlays else _extract_map_overlays(coord_p, grid_p)

            # Human-readable labels for current slice dimensions
            t_str = f"T={t_idx + 1}/{tot_tsteps}" if t_op == "select" else f"T={t_op.upper()}(1..{tot_tsteps})"
            l_str = f"L={l_idx + 1}/{tot_layers}" if l_op == "select" else f"L={l_op.upper()}(1..{tot_layers})"
            plot_title = f"{target_pol} | {t_str} | {l_str}"

            # Extract units if available
            unit = ""
            if hasattr(df, "attrs") and "units" in df.attrs:
                unit = str(df.attrs["units"]).strip()

            return {
                "pollutant": target_pol,
                "title": plot_title,
                "unit": unit,
                "time_label": t_str,
                "layer_label": l_str,
                "time_step": t_idx + 1,
                "total_time_steps": tot_tsteps,
                "layer": l_idx + 1,
                "total_layers": tot_layers,
                "time_op": t_op,
                "layer_op": l_op,
                "nrows": nrows,
                "ncols": ncols,
                "grid": {
                    "xorig": float(grid_p[1]),
                    "yorig": float(grid_p[2]),
                    "xcell": float(grid_p[3]),
                    "ycell": float(grid_p[4]),
                    "ncols": int(ncols),
                    "nrows": int(nrows),
                    "coord_p": list(coord_p) if coord_p is not None else None
                },
                "matrix": matrix.tolist(),
                "data": matrix.tolist(),
                "stats": stats,
                "boundaries": overlays.get("boundaries", []),
                "graticules": overlays.get("graticules", [])
            }
        except Exception as e:
            return {"error": f"Slice error: {str(e)}"}
    else:
        try:
            df, raw = read_inputfile(fpath)
            if target_pol in formulas:
                df[target_pol] = df.eval(formulas[target_pol])
            if target_pol not in df.columns:
                return {"error": f"Pollutant '{target_pol}' not found"}

            vals = df[target_pol].dropna().values.astype(float)
            if len(vals) == 0:
                return {"error": f"No valid numerical values for '{target_pol}'"}

            min_v = float(np.min(vals))
            max_v = float(np.max(vals))
            stats = {
                "min": min_v,
                "max": max_v,
                "mean": float(np.mean(vals)),
                "sum": float(np.sum(vals)),
                "nonzero_count": int(np.sum(vals > 0)),
                "p50": float(np.percentile(vals, 50)),
                "p95": float(np.percentile(vals, 95))
            }

            # Map column names (case-insensitive lookup)
            lower_to_col = {c.lower(): c for c in df.columns}
            x_col = lower_to_col.get("x cell") or lower_to_col.get("col") or lower_to_col.get("x")
            y_col = lower_to_col.get("y cell") or lower_to_col.get("row") or lower_to_col.get("y")
            has_grid_coords = bool(x_col and y_col)

            reg_col = next((c for c in df.columns if c.lower() in ("fips", "region_cd", "region", "county")), None)
            has_county_id = bool(reg_col)

            # Determine plot mode based on pltyp and available columns
            chosen_mode = pltyp.lower()
            if chosen_mode == "auto":
                if has_grid_coords and not has_county_id:
                    chosen_mode = "grid"
                elif has_county_id:
                    chosen_mode = "county"
                elif has_grid_coords:
                    chosen_mode = "grid"
                else:
                    chosen_mode = "table"

            # ── 1. GRID MODE FOR TABULAR DATA (e.g. invgrid_cell reports) ──
            if chosen_mode == "grid" and has_grid_coords:
                c_vals = pd.to_numeric(df[x_col], errors="coerce").fillna(0).astype(int).values
                r_vals = pd.to_numeric(df[y_col], errors="coerce").fillna(0).astype(int).values
                ncols = int(np.max(c_vals)) if len(c_vals) else 1
                nrows = int(np.max(r_vals)) if len(r_vals) else 1

                matrix = np.zeros((nrows, ncols), dtype=np.float32)
                p_vals = df[target_pol].values.astype(np.float32)
                for r, c, val in zip(r_vals, c_vals, p_vals):
                    if 1 <= r <= nrows and 1 <= c <= ncols:
                        matrix[r - 1, c - 1] += val

                return {
                    "pollutant": target_pol,
                    "nrows": nrows,
                    "ncols": ncols,
                    "matrix": matrix.tolist(),
                    "data": matrix.tolist(),
                    "stats": stats,
                    "boundaries": [],
                    "graticules": []
                }

            # ── 2. COUNTY CHOROPLETH MODE ──
            map_image_b64 = None
            county_features = []
            x_lim = None
            y_lim = None

            if has_county_id and chosen_mode in ("county", "auto"):
                try:
                    counties_gdf = read_shpfile(DEFAULT_ONLINE_COUNTIES_URL, True)
                    # Normalize FIPS via smkplot's build_fips_column (handles 12-digit SMKREPORT, 5/6 digit FIPS, tribal mapping)
                    emis_df = df.copy()
                    raw_sample = emis_df[reg_col].head(3).tolist() if reg_col in emis_df.columns else []
                    logging.info(f"[SMKPLOT-WEB] Processing county emissions with reg_col='{reg_col}', sample raw values: {raw_sample}")

                    try:
                        emis_df = get_emis_fips(emis_df, verbose=False)
                    except Exception as bfc_err:
                        logging.warning(f"[SMKPLOT-WEB] get_emis_fips raised: {bfc_err}, using manual fallback")
                        if reg_col != "FIPS":
                            emis_df["FIPS"] = emis_df[reg_col].astype(str).str.strip()
                        # Extract last 6 digits if > 6 digits (SMKREPORT 12-digit format)
                        emis_df["FIPS"] = emis_df["FIPS"].astype(str).apply(lambda x: x[-6:] if len(x) > 6 else x).str.zfill(6)

                    # Diagnostic stats before merge
                    cleaned_sample = emis_df["FIPS"].head(3).tolist() if "FIPS" in emis_df.columns else []
                    shp_sample = counties_gdf["FIPS"].head(3).tolist() if "FIPS" in counties_gdf.columns else []
                    n_unique_fips = emis_df["FIPS"].nunique() if "FIPS" in emis_df.columns else 0
                    logging.info(f"[SMKPLOT-WEB] Cleaned FIPS sample: {cleaned_sample} (total unique={n_unique_fips}); Shapefile FIPS sample: {shp_sample}")

                    # Merge via smkplot merge_emissions_with_geometry (aggregates multiple cells per county, standardizes 6-digit keys)
                    merged, emis_prepped = merge_emissions_with_geometry(
                        emis_df, counties_gdf, "FIPS", sort=False, copy_geometry=False, pad_fips=True
                    )

                    # Update stats to reflect county-aggregated emissions rather than unaggregated source-level rows
                    if target_pol in emis_prepped.columns:
                        county_vals = emis_prepped[target_pol].dropna().values.astype(float)
                        if len(county_vals) > 0:
                            stats = {
                                "min": float(np.min(county_vals)),
                                "max": float(np.max(county_vals)),
                                "mean": float(np.mean(county_vals)),
                                "sum": float(np.sum(county_vals)),
                                "nonzero_count": int(np.sum(county_vals > 0)),
                                "p50": float(np.percentile(county_vals, 50)),
                                "p95": float(np.percentile(county_vals, 95))
                            }
                            vals = county_vals

                    if not zoom_to_data and target_pol in merged.columns:
                        merged[target_pol] = merged[target_pol].fillna(0.0)

                    plot_gdf = merged
                    emissive_subset = None
                    if target_pol in merged.columns:
                        emissive_subset = merged[merged[target_pol].notna() & (merged[target_pol] > 0)]

                    n_emissive = len(emissive_subset) if emissive_subset is not None else 0
                    total_emiss = float(emissive_subset[target_pol].sum()) if emissive_subset is not None and not emissive_subset.empty else 0.0
                    logging.info(f"[SMKPLOT-WEB] County dataset merged: total={len(merged)}, emissive({target_pol}>0)={n_emissive}, total_emissions={total_emiss:.4e}, zoom_to_data={zoom_to_data}")

                    if zoom_to_data and emissive_subset is not None and not emissive_subset.empty:
                        plot_gdf = emissive_subset
                        effective_zoom = True
                    else:
                        plot_gdf = merged
                        effective_zoom = False

                    fig, ax = plt.subplots(figsize=(10, 6.5), dpi=140)
                    fig.patch.set_facecolor("#ffffff")
                    ax.set_facecolor("#ffffff")

                    cmap_selected = getattr(plt.cm, cmap, getattr(plt.cm, "turbo", plt.cm.jet))
                    create_map_plot(
                        gdf=plot_gdf,
                        column=target_pol,
                        title=f"{target_pol} - County Emissions Map",
                        ax=ax,
                        cmap_name=cmap_selected,
                        log_scale=log_scale or (stats["max"] > 100),
                        overlay_counties=counties_gdf,
                        zoom_to_data=effective_zoom,
                        zoom_pad=0.06
                    )

                    ax.title.set_color('#0f172a')
                    ax.title.set_fontsize(11)
                    ax.title.set_fontweight('bold')
                    for spine in ax.spines.values():
                        spine.set_color('#cbd5e1')
                        spine.set_linewidth(1.0)

                    for c_ax in fig.axes:
                        if c_ax != ax:
                            c_ax.set_facecolor('#ffffff')
                            c_ax.tick_params(colors='#334155', labelsize=8)
                            c_ax.yaxis.label.set_color('#334155')
                            c_ax.xaxis.label.set_color('#334155')
                            for spine in c_ax.spines.values():
                                spine.set_color('#cbd5e1')

                    x_lim = [float(v) for v in ax.get_xlim()]
                    y_lim = [float(v) for v in ax.get_ylim()]

                    # Extract display bounding boxes and attributes for county hover inspection
                    try:
                        name_col = next((c for c in plot_gdf.columns if c.upper() in ("NAME", "COUNTY", "COUNTY_NAME")), None)
                        st_col = next((c for c in plot_gdf.columns if c.upper() in ("STATE_NAME", "STATE", "STUSPS")), None)
                        for _, row in plot_gdf.iterrows():
                            val = row.get(target_pol, None)
                            if pd.isna(val) or val is None:
                                continue
                            geom = row.geometry
                            if geom is None:
                                continue
                            minx, miny, maxx, maxy = geom.bounds
                            if maxx < x_lim[0] or minx > x_lim[1] or maxy < y_lim[0] or miny > y_lim[1]:
                                continue
                            c_name = str(row.get(name_col, "")) if name_col else ""
                            s_name = str(row.get(st_col, "")) if st_col else ""
                            fips_val = str(row.get("FIPS", ""))
                            county_features.append({
                                "fips": fips_val,
                                "name": c_name,
                                "state": s_name,
                                "val": float(val),
                                "bbox": [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)]
                            })
                    except Exception as he:
                        logging.warning(f"Error compiling hover metadata: {he}")

                    buf = io.BytesIO()
                    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="#ffffff", edgecolor="none")
                    plt.close(fig)
                    buf.seek(0)
                    map_image_b64 = base64.b64encode(buf.read()).decode("ascii")
                except Exception as ce:
                    logging.warning(f"[SMKPLOT-WEB] County map generation error: {ce}")

            return {
                "pollutant": target_pol,
                "is_county_map": bool(map_image_b64),
                "map_image": map_image_b64,
                "county_features": county_features,
                "map_extent": [x_lim[0], x_lim[1], y_lim[0], y_lim[1]] if (x_lim and y_lim) else None,
                "stats": stats,
                "count": len(vals)
            }
        except Exception as e:
            return {"error": f"Read error: {str(e)}"}


def handle_profile(fpath: str, pol_req: str, row: int, col: int):
    if not os.path.exists(fpath) or not is_netcdf_file(fpath):
        return {"error": "Profiles supported on NetCDF files only"}

    try:
        dims = get_ncf_dims(fpath)
        r_idx = max(0, row - 1)
        c_idx = max(0, col - 1)

        # Auto-detect STACK_GROUPS file if inline file (smkplot heuristic)
        stack_groups = os.environ.get("STACK_GROUPS")
        base_name = os.path.basename(fpath).lower()
        if not stack_groups and ("inln" in base_name or "inln_" in base_name):
            import re
            parent_dir = os.path.dirname(os.path.abspath(fpath))
            match_date = re.search(r'(20\d{6}|20\d{5})', base_name)
            if match_date:
                d_str = match_date.group(1)
                try:
                    candidates = [f for f in os.listdir(parent_dir) if "stack_groups" in f.lower() and d_str in f and (f.endswith(".nc") or f.endswith(".ncf"))]
                    if candidates:
                        stack_groups = os.path.join(parent_dir, candidates[0])
                except Exception:
                    pass
            if not stack_groups:
                try:
                    candidates = [f for f in os.listdir(parent_dir) if "stack_groups" in f.lower() and (f.endswith(".nc") or f.endswith(".ncf"))]
                    if candidates:
                        stack_groups = os.path.join(parent_dir, candidates[0])
                except Exception:
                    pass

        # Use smkplot's tested get_ncf_timeseries
        ts_res = get_ncf_timeseries(
            ncf_path=fpath,
            pollutant=pol_req,
            row_indices=[r_idx],
            col_indices=[c_idx],
            layer_idx=0,
            layer_op='select',
            op='sum',
            stack_groups_path=stack_groups
        )
        ts_raw = ts_res.get("values", []) if ts_res else []
        if isinstance(ts_raw, dict):
            timeseries = ts_raw.get("Total") or (list(ts_raw.values())[0] if ts_raw else [])
        else:
            timeseries = ts_raw or []

        # Use smkplot's tested get_ncf_profile
        prof_res = get_ncf_profile(
            ncf_path=fpath,
            pollutant=pol_req,
            row_indices=[r_idx],
            col_indices=[c_idx],
            time_idx=0,
            time_op='select',
            op='sum',
            stack_groups_path=stack_groups
        )
        prof_raw = prof_res.get("values", []) if prof_res else []
        if isinstance(prof_raw, dict):
            vertical = prof_raw.get("Total") or (list(prof_raw.values())[0] if prof_raw else [])
        else:
            vertical = prof_raw or []

        unit = ""
        if ts_res and ts_res.get("units"):
            unit = str(ts_res.get("units", "")).strip()
        elif prof_res and prof_res.get("units"):
            unit = str(prof_res.get("units", "")).strip()

        return {
            "row": row,
            "col": col,
            "pollutant": pol_req,
            "timeseries": [float(x) for x in timeseries if x is not None],
            "vertical": [float(x) for x in vertical if x is not None],
            "unit": unit,
            "tflags": dims.get("tflag_values", [])
        }
    except Exception as e:
        return {"error": f"Profile query error: {str(e)}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["load", "slice", "profile"])
    parser.add_argument("--path", required=True)
    parser.add_argument("--pollutant", default="")
    parser.add_argument("--time", type=int, default=0)
    parser.add_argument("--layer", type=int, default=0)
    parser.add_argument("--time-op", default="select")
    parser.add_argument("--layer-op", default="select")
    parser.add_argument("--row", type=int, default=1)
    parser.add_argument("--col", type=int, default=1)
    parser.add_argument("--cmap", default="turbo")
    parser.add_argument("--pltyp", default="auto")
    parser.add_argument("--log-scale", action="store_true")
    parser.add_argument("--zoom-to-data", action="store_true")
    parser.add_argument("--skip-overlays", action="store_true")

    args = parser.parse_args()

    if args.action == "load":
        res = handle_load(args.path)
    elif args.action == "slice":
        res = handle_slice(args.path, args.pollutant, args.time, args.layer, args.time_op, args.layer_op, args.cmap, args.log_scale, args.zoom_to_data, args.pltyp, args.skip_overlays)
    elif args.action == "profile":
        res = handle_profile(args.path, args.pollutant, args.row, args.col)
    else:
        res = {"error": "Unknown action"}

    print(json.dumps(res))
