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

import heapq
import os
import sys
import uuid
from pathlib import Path

import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from matplotlib.path import Path as MplPath
from pydantic import BaseModel

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

# Manual trust zones added via the UI (per-session, not persisted)
_manual_zones: list[dict] = []


# ── Trust-zone helpers ───────────────────────────────────────────────────────
def _polygon_to_grid_mask(poly_latlons: list) -> np.ndarray:
    """[[lat, lon], ...] polygon  →  bool GRID_N×GRID_N mask."""
    lat_min = LAT_CENTER - LAT_SPAN / 2
    lat_max = LAT_CENTER + LAT_SPAN / 2
    lon_min = LON_CENTER - LON_SPAN / 2
    lon_max = LON_CENTER + LON_SPAN / 2
    poly_cr = [
        (
            (lon - lon_min) / (lon_max - lon_min) * (GRID_N - 1),
            (lat - lat_min) / (lat_max - lat_min) * (GRID_N - 1),
        )
        for lat, lon in poly_latlons
    ]
    if len(poly_cr) < 3:
        return np.zeros((GRID_N, GRID_N), dtype=bool)
    path = MplPath(poly_cr)
    cols, rows = np.meshgrid(
        np.arange(GRID_N, dtype=float), np.arange(GRID_N, dtype=float)
    )
    pts = np.column_stack([cols.ravel(), rows.ravel()])
    return path.contains_points(pts).reshape(GRID_N, GRID_N)


def _recompute_trust() -> None:
    """Rebuild _trust_map from GPS routes + manual zones."""
    global _trust_map
    base = compute_trust_map(_cost_map, _route_specs, _x_m, _y_m)
    for zone in _manual_zones:
        mask = _polygon_to_grid_mask(zone["polygon"])
        base[mask] = float(zone["trust_level"])
    _trust_map = np.clip(base, 0.0, 1.0)


def _astar(start_rc: tuple, end_rc: tuple) -> list | None:
    """Grid A* on _trust_map.  Returns [(row, col), ...] or None."""
    sr, sc = start_rc
    er, ec = end_rc

    def h(r: int, c: int) -> float:
        return ((r - er) ** 2 + (c - ec) ** 2) ** 0.5

    open_heap: list = [(h(sr, sc), 0.0, sr, sc)]
    g_score: dict = {(sr, sc): 0.0}
    parent: dict = {(sr, sc): None}
    visited: set = set()

    while open_heap:
        _, g, r, c = heapq.heappop(open_heap)
        if (r, c) in visited:
            continue
        visited.add((r, c))
        if r == er and c == ec:
            path: list = []
            cur: tuple | None = (r, c)
            while cur is not None:
                path.append(cur)
                cur = parent[cur]
            return path[::-1]
        t = float(_trust_map[r, c])
        cell_cost = (1.0 / t) if t >= 0.01 else 1e6
        for dr, dc in [
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < GRID_N and 0 <= nc < GRID_N and (nr, nc) not in visited:
                step = cell_cost * (1.414 if dr and dc else 1.0)
                ng = g + step
                if ng < g_score.get((nr, nc), float("inf")):
                    g_score[(nr, nc)] = ng
                    parent[(nr, nc)] = (r, c)
                    heapq.heappush(open_heap, (ng + h(nr, nc), ng, nr, nc))
    return None


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


# ── Trust-zone endpoints ────────────────────────────────────────────────────
class TrustZoneReq(BaseModel):
    polygon: list[list[float]]  # [[lat, lon], ...]
    trust_level: float = 1.0
    label: str = "Zone"


@app.post("/api/trust/zone")
async def add_trust_zone(req: TrustZoneReq):
    """Add a manual trust zone polygon and recompute the trust grid."""
    zone_id = str(uuid.uuid4())[:8]
    _manual_zones.append(
        {
            "id": zone_id,
            "polygon": req.polygon,
            "trust_level": req.trust_level,
            "label": req.label,
        }
    )
    _recompute_trust()
    return {"ok": True, "zone_id": zone_id, "zones": _manual_zones}


@app.delete("/api/trust/zone/{zone_id}")
async def remove_trust_zone(zone_id: str):
    """Remove a manual trust zone and recompute the trust grid."""
    global _manual_zones
    _manual_zones = [z for z in _manual_zones if z["id"] != zone_id]
    _recompute_trust()
    return {"ok": True, "zones": _manual_zones}


@app.get("/api/trust/zones")
async def list_trust_zones():
    """Return all manual trust zones."""
    return {"zones": _manual_zones}


# ── Route generation endpoint ────────────────────────────────────────────────
class RouteGenReq(BaseModel):
    start: list[float]  # [lat, lon]
    end: list[float]  # [lat, lon]


@app.post("/api/route/generate")
async def generate_route(req: RouteGenReq):
    """A* shortest path on the trust grid from start to end."""
    lat_min = LAT_CENTER - LAT_SPAN / 2
    lat_max = LAT_CENTER + LAT_SPAN / 2
    lon_min = LON_CENTER - LON_SPAN / 2
    lon_max = LON_CENTER + LON_SPAN / 2

    def ll_to_rc(lat: float, lon: float) -> tuple:
        row = int(
            np.clip((lat - lat_min) / (lat_max - lat_min) * (GRID_N - 1), 0, GRID_N - 1)
        )
        col = int(
            np.clip((lon - lon_min) / (lon_max - lon_min) * (GRID_N - 1), 0, GRID_N - 1)
        )
        return row, col

    def rc_to_ll(row: int, col: int) -> tuple:
        lat = lat_min + row / (GRID_N - 1) * (lat_max - lat_min)
        lon = lon_min + col / (GRID_N - 1) * (lon_max - lon_min)
        return lat, lon

    start_rc = ll_to_rc(req.start[0], req.start[1])
    end_rc = ll_to_rc(req.end[0], req.end[1])
    path = _astar(start_rc, end_rc)
    if path is None:
        raise HTTPException(404, "No path found between start and end")

    # Downsample: keep every 3rd point + always include last
    sampled = path[::3]
    if sampled[-1] != path[-1]:
        sampled = sampled + [path[-1]]
    coords = [[rc_to_ll(r, c)[1], rc_to_ll(r, c)[0]] for r, c in sampled]  # [lon,lat]
    return {
        "type": "Feature",
        "properties": {"n_waypoints": len(coords)},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


# ── Frontend ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = BASE_DIR / "app.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=False)
