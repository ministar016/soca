"""
terrain.py — elevation grid fetching, caching and DEM calibration.

Public API
----------
build_grid() -> (lats, lons, elev_s, x_m, y_m, XX, YY)
    Returns calibrated elevation grid and coordinate arrays.

snap_to_terrain(xs, ys) -> list[float]
    Returns z = terrain_elevation + GPS_HEIGHT for given metric coords.
"""

import json
import math
import os
import time

import numpy as np
import requests
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.ndimage import zoom as nd_zoom

from .config import (
    GPS_HEIGHT,
    GRID_N,
    LAT_CENTER,
    LAT_SPAN,
    LON_CENTER,
    LON_SPAN,
    MAPS_DIR,
    OT_API_KEY,
)

_CACHE_PATH = os.path.join(MAPS_DIR, "elevation_cache.json")
_META_PATH = os.path.join(MAPS_DIR, "elevation_meta.json")
_META_CURR = {
    "lat": round(LAT_CENTER, 6),
    "lon": round(LON_CENTER, 6),
    "lat_span": LAT_SPAN,
    "lon_span": LON_SPAN,
}

# Internal grid (set after build_grid())
_x_m: np.ndarray | None = None
_y_m: np.ndarray | None = None
_elev_s: np.ndarray | None = None


# ── Private helpers ───────────────────────────────────────────────────────────


def _parse_aaigrid(text: str) -> np.ndarray:
    """Parse ASCII Grid (AAIGrid) returned by OpenTopography API."""
    lines = text.strip().splitlines()
    header: dict[str, float] = {}
    data_start = 0
    for i, line in enumerate(lines):
        parts = line.strip().split()
        if len(parts) == 2 and not parts[0].lstrip("-").replace(".", "").isdigit():
            header[parts[0].lower()] = float(parts[1])
            data_start = i + 1
        else:
            data_start = i
            break
    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    nodata = header.get("nodata_value", -9999.0)
    vals = []
    for line in lines[data_start:]:
        if line.strip():
            vals.extend(float(x) for x in line.split())
    arr = np.array(vals, dtype=float).reshape(nrows, ncols)
    arr[arr == nodata] = np.nan
    return np.flipud(arr)  # rows run north→south, flip to south→north


def _fetch_raw_elevation(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Download elevation data. Tries COP30 first, falls back to Open-Elevation."""
    south = LAT_CENTER - LAT_SPAN / 2
    north = LAT_CENTER + LAT_SPAN / 2
    west = LON_CENTER - LON_SPAN / 2
    east = LON_CENTER + LON_SPAN / 2
    elev = None

    if OT_API_KEY:
        print("Fetching Copernicus DEM 30 m (OpenTopography COP30)...")
        params = dict(
            demtype="COP30",
            south=south,
            north=north,
            west=west,
            east=east,
            outputFormat="AAIGrid",
            API_Key=OT_API_KEY,
        )
        try:
            r = requests.get(
                "https://portal.opentopography.org/API/globaldem",
                params=params,
                timeout=60,
            )
            if r.status_code == 200 and "ncols" in r.text[:200]:
                raw = _parse_aaigrid(r.text)
                zy = GRID_N / raw.shape[0]
                zx = GRID_N / raw.shape[1]
                elev = nd_zoom(raw, (zy, zx), order=1)
                print(f"  COP30 OK ({raw.shape[1]}x{raw.shape[0]} → {GRID_N}x{GRID_N})")
            else:
                print(f"  OpenTopography error {r.status_code}: {r.text[:120]}")
        except Exception as exc:
            print(f"  OpenTopography error: {exc}")
    else:
        print("OT_API_KEY not set — using Open-Elevation fallback.")

    if elev is None:
        print(f"Fetching {GRID_N * GRID_N} elevation points (Open-Elevation)...")
        locations = [
            {"latitude": round(float(la), 6), "longitude": round(float(lo), 6)}
            for la in lats
            for lo in lons
        ]
        elev_flat: list[float] = []
        for i in range(0, len(locations), 256):
            for attempt in range(3):
                try:
                    r = requests.post(
                        "https://api.open-elevation.com/api/v1/lookup",
                        json={"locations": locations[i : i + 256]},
                        timeout=30,
                    )
                    elev_flat.extend([x["elevation"] for x in r.json()["results"]])
                    print(f"  {len(elev_flat)}/{GRID_N * GRID_N}")
                    break
                except Exception as exc:
                    print(f"  Retry: {exc}")
                    time.sleep(2)
        elev = np.array(elev_flat, dtype=float).reshape(GRID_N, GRID_N)

    return elev


# ── Public API ────────────────────────────────────────────────────────────────


def build_grid(
    gps_alts: np.ndarray,
    gps_xs: np.ndarray,
    gps_ys: np.ndarray,
) -> tuple:
    """
    Build and return the calibrated elevation grid.

    Parameters
    ----------
    gps_alts, gps_xs, gps_ys : np.ndarray
        All GPS altitudes and metric coordinates from all routes (for DEM
        calibration).

    Returns
    -------
    lats, lons, elev_s, x_m, y_m, XX, YY
    """
    global _x_m, _y_m, _elev_s

    lats = np.linspace(LAT_CENTER - LAT_SPAN / 2, LAT_CENTER + LAT_SPAN / 2, GRID_N)
    lons = np.linspace(LON_CENTER - LON_SPAN / 2, LON_CENTER + LON_SPAN / 2, GRID_N)

    # Cache invalidation
    if os.path.exists(_META_PATH):
        with open(_META_PATH) as fh:
            old_meta = json.load(fh)
        if old_meta != _META_CURR:
            print("  Elevation cache stale — deleting...")
            if os.path.exists(_CACHE_PATH):
                os.remove(_CACHE_PATH)

    if os.path.exists(_CACHE_PATH):
        print("Using cached elevation data...")
        with open(_CACHE_PATH) as fh:
            d = json.load(fh)
        elev = np.array(d["elev"])
    else:
        elev = _fetch_raw_elevation(lats, lons)
        with open(_CACHE_PATH, "w") as fh:
            json.dump(
                {"lats": lats.tolist(), "lons": lons.tolist(), "elev": elev.tolist()},
                fh,
            )
        with open(_META_PATH, "w") as fh:
            json.dump(_META_CURR, fh)

    elev_s = gaussian_filter(elev.astype(float), sigma=1.5)
    print(f"Elevation (raw DEM): {elev_s.min():.1f}–{elev_s.max():.1f} m")

    x_m = (lons - LON_CENTER) * 111_320 * math.cos(math.radians(LAT_CENTER))
    y_m = (lats - LAT_CENTER) * 111_320
    XX, YY = np.meshgrid(x_m, y_m)

    # ── DEM calibration to GPS altitude ──
    col = (gps_xs - x_m[0]) / (x_m[-1] - x_m[0]) * (GRID_N - 1)
    row = (gps_ys - y_m[0]) / (y_m[-1] - y_m[0]) * (GRID_N - 1)
    col = np.clip(col, 0, GRID_N - 1)
    row = np.clip(row, 0, GRID_N - 1)
    dem_at_gps = map_coordinates(elev_s, [row, col], order=1, mode="nearest")
    offset = float(np.median(gps_alts) - np.median(dem_at_gps))
    elev_s = elev_s + offset
    print(
        f"DEM calibration: offset={offset:+.1f} m  "
        f"(DEM median → GPS median={np.median(gps_alts):.1f} m)"
    )
    print(f"Elevation (calibrated): {elev_s.min():.1f}–{elev_s.max():.1f} m")

    _x_m = x_m
    _y_m = y_m
    _elev_s = elev_s
    return lats, lons, elev_s, x_m, y_m, XX, YY


def snap_to_terrain(xs: list[float], ys: list[float]) -> list[float]:
    """Interpolate calibrated terrain height at (x, y) and add GPS_HEIGHT."""
    if _elev_s is None or _x_m is None or _y_m is None:
        raise RuntimeError("build_grid() must be called before snap_to_terrain().")
    col = (np.asarray(xs) - _x_m[0]) / (_x_m[-1] - _x_m[0]) * (GRID_N - 1)
    row = (np.asarray(ys) - _y_m[0]) / (_y_m[-1] - _y_m[0]) * (GRID_N - 1)
    col = np.clip(col, 0, GRID_N - 1)
    row = np.clip(row, 0, GRID_N - 1)
    terrain_z = map_coordinates(_elev_s, [row, col], order=1, mode="nearest")
    return (terrain_z + GPS_HEIGHT).tolist()
