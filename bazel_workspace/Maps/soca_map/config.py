"""
config.py — centralised paths, constants and API key loading.

All other modules import from here.
"""

import json
import math as _math
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
MAPS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSONL_PATH1 = os.path.join(MAPS_DIR, "10.9.0.50_2026-05-08_12-10-46_UTC.jsonl")
JSONL_PATH2 = os.path.join(MAPS_DIR, "10.9.0.50_2026-05-08_09-51-50_UTC.jsonl")
IMG_PATH = os.path.join(MAPS_DIR, "image.png")
OUT_HTML = os.path.join(MAPS_DIR, "terrain_3d_result.html")
OUT_PNG = os.path.join(MAPS_DIR, "terrain_3d_result.png")
TRUST_DB_PATH = os.path.join(MAPS_DIR, "trust_db.jsonl")

# ── Grid resolution ───────────────────────────────────────────────────────────
GRID_N = 60  # cells per axis
_SAT_MARGIN = 1.5  # satellite tile padding around GPS bbox

# ── Camera/antenna height ─────────────────────────────────────────────────────
GPS_HEIGHT = 0.5  # metres above ground (UGV antenna)

# ── OpenTopography API key ────────────────────────────────────────────────────
_api_key_file = os.path.join(MAPS_DIR, "api_key")
OT_API_KEY = ""
if os.path.exists(_api_key_file):
    with open(_api_key_file) as _f:
        for _line in _f:
            if ":" in _line:
                OT_API_KEY = _line.split(":", 1)[1].strip()
                break
OT_API_KEY = OT_API_KEY or os.environ.get("OT_API_KEY", "")


# ── UTM Zone 32N → WGS84 ─────────────────────────────────────────────────────
def utm32n_to_latlon(easting: float, northing: float) -> tuple[float, float]:
    """UTM Zone 32N (WGS84) → (lat_deg, lon_deg)."""
    a = 6_378_137.0
    f = 1 / 298.257223563
    b = a * (1 - f)
    e2 = 1 - (b / a) ** 2
    ep2 = (a / b) ** 2 - 1
    k0 = 0.9996
    E0 = 500_000
    lon0 = _math.radians(9)  # Zone 32N: central meridian 9 °E
    x = easting - E0
    y = northing
    M = y / k0
    mu = M / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - _math.sqrt(1 - e2)) / (1 + _math.sqrt(1 - e2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * _math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * _math.sin(4 * mu)
        + (151 * e1**3 / 96) * _math.sin(6 * mu)
    )
    N1 = a / _math.sqrt(1 - e2 * _math.sin(phi1) ** 2)
    T1 = _math.tan(phi1) ** 2
    C1 = ep2 * _math.cos(phi1) ** 2
    R1 = a * (1 - e2) / (1 - e2 * _math.sin(phi1) ** 2) ** 1.5
    D = x / (N1 * k0)
    lat = phi1 - (N1 * _math.tan(phi1) / R1) * (
        D**2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * ep2) * D**4 / 24
    )
    lon = lon0 + (D - (1 + 2 * T1 + C1) * D**3 / 6) / _math.cos(phi1)
    return _math.degrees(lat), _math.degrees(lon)


# ── Auto-compute map bounds from GPS data ─────────────────────────────────────
def _gps_bounds(paths: list[str]) -> tuple[float, float, float, float]:
    all_e, all_n = [], []
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            for line in fh:
                try:
                    p = json.loads(line.strip())["payload"]
                    all_e.append(p["easting"])
                    all_n.append(p["northing"])
                except Exception:
                    continue
    if not all_e:
        raise RuntimeError("No GPS points found in JSONL files.")
    return min(all_e), max(all_e), min(all_n), max(all_n)


_e_min, _e_max, _n_min, _n_max = _gps_bounds([JSONL_PATH1, JSONL_PATH2])

UTM_E_CENTER = (_e_min + _e_max) / 2
UTM_N_CENTER = (_n_min + _n_max) / 2
LAT_CENTER, LON_CENTER = utm32n_to_latlon(UTM_E_CENTER, UTM_N_CENTER)

_cos_lat = _math.cos(_math.radians(LAT_CENTER))
_lat_half = (_n_max - _n_min) / 2 / 111_320 * _SAT_MARGIN
_lon_half = (_e_max - _e_min) / 2 / (111_320 * _cos_lat) * _SAT_MARGIN

LAT_SPAN = round(_lat_half * 2, 5)
LON_SPAN = round(_lon_half * 2, 5)
