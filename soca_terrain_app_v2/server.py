"""
server.py — SOCA Terrain Live Server
FastAPI backend serving:
  - /             → CesiumJS frontend
  - /api/routes   → GPS routes (GeoJSON)
  - /api/trust    → Trust map grid (JSON)
  - /api/dem      → DEM elevation grid (JSON)
  - /tile/sat/{z}/{x}/{y}.png → ESRI satellite tile proxy (live, cached)
  - /tile/dem/{z}/{x}/{y}.png → Terrain-coloured elevation tile proxy
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from soca_map.config import (  # noqa: E402
    GRID_N,
    JSONL_PATH1,
    JSONL_PATH2,
    LAT_CENTER,
    LAT_SPAN,
    LON_CENTER,
    LON_SPAN,
    UTM_E_CENTER,
    UTM_N_CENTER,
    utm32n_to_latlon,
)
from soca_map.gps import RouteData, compute_trust_map, load_route  # noqa: E402
from soca_map.terrain import build_grid, snap_to_terrain  # noqa: E402

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="SOCA Terrain API", version="2.0")

TILE_CACHE = BASE_DIR / "tile_cache"
TILE_CACHE.mkdir(exist_ok=True)

# ── Load GPS routes once at startup ─────────────────────────────────────────
_routes: list[RouteData] = []
for _path in [JSONL_PATH1, JSONL_PATH2]:
    if os.path.exists(_path):
        _routes.append(load_route(_path))

# Gather all GPS coords for DEM calibration
_all_alts = (
    np.concatenate([np.array(r.z) for r in _routes]) if _routes else np.array([0.0])
)
_all_xs = (
    np.concatenate([np.array(r.x) for r in _routes]) if _routes else np.array([0.0])
)
_all_ys = (
    np.concatenate([np.array(r.y) for r in _routes]) if _routes else np.array([0.0])
)

# Snap routes to terrain after building grid
print("[SOCA] Building DEM grid …")
_lats, _lons, _elev, _x_m, _y_m, _XX, _YY = build_grid(_all_alts, _all_xs, _all_ys)
print(f"[SOCA] DEM ready  elev={_elev.min():.1f}–{_elev.max():.1f} m")

for r in _routes:
    if r.x:
        r.xs = r.x
        r.ys = r.y
        r.zs = snap_to_terrain(r.x, r.y)
        r.spds = r.spd
        r.dists = r.dist
        r.tss = r.ts

_route_specs = [{"xs": r.xs, "ys": r.ys, "trust": 1.0} for r in _routes if r.xs]
_cost_map = np.full((GRID_N, GRID_N), 0.3, dtype=np.float32)
_trust_map = compute_trust_map(_cost_map, _route_specs, _x_m, _y_m)
print("[SOCA] Trust map ready")


# ── Tile proxy ──────────────────────────────────────────────────────────────
def _tile_cache_path(kind: str, z: int, x: int, y: int) -> Path:
    p = TILE_CACHE / kind / str(z) / str(x)
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{y}.png"


async def _fetch_tile(url: str, headers: dict | None = None) -> bytes:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=headers or {})
        r.raise_for_status()
        return r.content


@app.get("/tile/sat/{z}/{x}/{y}.png")
async def sat_tile(z: int, x: int, y: int):
    """Live ESRI World Imagery tile with disk cache."""
    cache = _tile_cache_path("sat", z, x, y)
    if cache.exists():
        return Response(content=cache.read_bytes(), media_type="image/png")

    url = f"https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    try:
        data = await _fetch_tile(url)
        cache.write_bytes(data)
        return Response(content=data, media_type="image/png")
    except Exception as e:
        raise HTTPException(502, f"Tile fetch failed: {e}")


@app.get("/tile/dem/{z}/{x}/{y}.png")
async def dem_tile(z: int, x: int, y: int):
    """Terrain-RGB tile from Mapbox (elevation encoded in RGB)."""
    cache = _tile_cache_path("dem", z, x, y)
    if cache.exists():
        return Response(content=cache.read_bytes(), media_type="image/png")

    url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
    try:
        data = await _fetch_tile(url)
        cache.write_bytes(data)
        return Response(content=data, media_type="image/png")
    except Exception as e:
        raise HTTPException(502, f"DEM tile fetch failed: {e}")


# ── GeoJSON routes API ───────────────────────────────────────────────────────
@app.get("/api/routes")
async def api_routes():
    """Return all GPS routes as GeoJSON FeatureCollection."""
    colors = ["#FFD700", "#9370DB", "#00BFFF", "#FF6347"]
    features = []
    for i, route in enumerate(_routes):
        if not route.xs:
            continue
        coords = []
        speeds = []
        for x, y, z_val, spd in zip(route.xs, route.ys, route.zs, route.spds):
            lat, lon = utm32n_to_latlon(x + UTM_E_CENTER, y + UTM_N_CENTER)
            coords.append([lon, lat, float(z_val)])
            speeds.append(float(spd))
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": route.name or f"PATH {i + 1}",
                    "color": colors[i % len(colors)],
                    "total_dist_m": route.total_dist,
                    "n_points": len(coords),
                    "speeds": speeds,
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )
    return {"type": "FeatureCollection", "features": features}


# ── Trust map API ────────────────────────────────────────────────────────────
@app.get("/api/trust")
async def api_trust():
    """Return trust grid as flat array with bounds."""
    return {
        "grid": _trust_map.tolist(),
        "grid_n": GRID_N,
        "lat_min": LAT_CENTER - LAT_SPAN / 2,
        "lat_max": LAT_CENTER + LAT_SPAN / 2,
        "lon_min": LON_CENTER - LON_SPAN / 2,
        "lon_max": LON_CENTER + LON_SPAN / 2,
    }


# ── DEM grid API ─────────────────────────────────────────────────────────────
@app.get("/api/dem")
async def api_dem():
    """Return DEM elevation grid and geographic bounds."""
    return {
        "grid": _elev.tolist(),
        "grid_n": int(_elev.shape[0]),
        "lats": _lats.tolist(),
        "lons": _lons.tolist(),
        "lat_center": LAT_CENTER,
        "lon_center": LON_CENTER,
        "elev_min": float(_elev.min()),
        "elev_max": float(_elev.max()),
    }


# ── Map bounds API ───────────────────────────────────────────────────────────
@app.get("/api/bounds")
async def api_bounds():
    return {
        "lat_center": LAT_CENTER,
        "lon_center": LON_CENTER,
        "lat_span": LAT_SPAN,
        "lon_span": LON_SPAN,
        "utm_e_center": UTM_E_CENTER,
        "utm_n_center": UTM_N_CENTER,
    }


# ── Frontend ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = BASE_DIR / "app.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=False)
