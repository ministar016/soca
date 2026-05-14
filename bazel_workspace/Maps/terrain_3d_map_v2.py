"""3D Terrain Navigation Map  v3
Koordinate: 48.2295, 11.6219 (München okolica, prosirena mapa)
- Visinski podaci: OpenTopography Copernicus DEM 30m (COP30, kesiran)
- Layer 1: Traversability overlay (HSV segmentacija image.png)
- Layer 2: Satelitska tekstura (ESRI World Imagery)
- PATH 1: zlatna  — 10.9.0.50_2026-05-08_12-10-46 (robot, 100% provjereno)
- PATH 2: ljubicasta — 10.9.0.50_2026-05-08_09-51-50 (robot, 100% provjereno)
- Interaktivni HTML: layer toggle, rotacija, zoom, hover
"""

import base64
import io
import json
import os
import sys
import time

import cv2
import numpy as np
import requests

MAPS_DIR = "/home/mn/soca/bazel_workspace/Maps"

# soca_map package lives alongside this script
if MAPS_DIR not in sys.path:
    sys.path.insert(0, MAPS_DIR)
from soca_map.segmentation import segment_image as _segment_image  # noqa: E402

IMG_PATH = os.path.join(MAPS_DIR, "image.png")
JSONL_PATH1 = os.path.join(MAPS_DIR, "10.9.0.50_2026-05-08_12-10-46_UTC.jsonl")
JSONL_PATH2 = os.path.join(MAPS_DIR, "10.9.0.50_2026-05-08_09-51-50_UTC.jsonl")
OUT_HTML = os.path.join(MAPS_DIR, "terrain_3d_result.html")
OUT_PNG = os.path.join(MAPS_DIR, "terrain_3d_result.png")

# OpenTopography API kljuc — registracija besplatna na https://portal.opentopography.org
# Ucitava se iz Maps/api_key fajla (format: "API key: <kljuc>"), env var OT_API_KEY,
# ili se moze direktno postaviti ovdje.
_api_key_file = os.path.join(MAPS_DIR, "api_key")
OT_API_KEY = ""
if os.path.exists(_api_key_file):
    with open(_api_key_file) as _f:
        for _line in _f:
            if ":" in _line:
                OT_API_KEY = _line.split(":", 1)[1].strip()
                break
OT_API_KEY = OT_API_KEY or os.environ.get("OT_API_KEY", "")

GRID_N = 180  # grid rezolucija (celija po osi)
_SAT_MARGIN = 1.5  # 50% margine oko GPS bounding boxa za satelitsku/DEM tile

# ── CLI parametar: lat,lon[,ZOOMz]  npr.  49.7619516,6.717021,14.62z ────────
import argparse as _argparse

_ap = _argparse.ArgumentParser(add_help=False)
_ap.add_argument(
    "coords",
    nargs="?",
    default=None,
    help="lat,lon[,ZOOMz]  e.g.  49.7619516,6.717021,14.62z",
)
_ap.add_argument(
    "--label",
    dest="labels",
    action="append",
    default=[],
    metavar="LAT,LON:Naziv",
    help="Dodaj oznaku na mapu, npr. --label 49.762,6.718:Moja_tacka",
)
_CLI, _ = _ap.parse_known_args()
MANUAL_MODE = _CLI.coords is not None

# MANUAL_LABELS = list of (easting, northing, text)
MANUAL_LABELS = []
for _lbl in _CLI.labels:
    _lbl_parts = _lbl.split(":")
    _lbl_text = _lbl_parts[1].replace("_", " ") if len(_lbl_parts) > 1 else "?"
    _lbl_ll = _lbl_parts[0].split(",")
    MANUAL_LABELS.append((_lbl_ll[0].strip(), _lbl_ll[1].strip(), _lbl_text))


# ── UTM Zone 32N ↔ WGS84 konverzija ─────────────────────────────────────────
import math as _math


def _utm32n_to_latlon(easting, northing):
    """UTM Zone 32N (WGS84) → (lat_deg, lon_deg)."""
    a = 6378137.0
    f = 1 / 298.257223563
    b = a * (1 - f)
    e2 = 1 - (b / a) ** 2
    ep2 = (a / b) ** 2 - 1
    k0 = 0.9996
    E0 = 500000
    lon0 = _math.radians(9)  # Zone 32N: meridian 9°E
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


def _gps_bounds_from_jsonl(paths):
    """Ucitaj sve JSONL putanje i vrati (e_min, e_max, n_min, n_max) u UTM."""
    all_e, all_n = [], []
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as _f:
            for _ln in _f:
                try:
                    p = json.loads(_ln.strip())["payload"]
                    all_e.append(p["easting"])
                    all_n.append(p["northing"])
                except Exception:
                    continue
    if not all_e:
        raise RuntimeError("Nije pronadjena ni jedna GPS tocka u JSONL fajlovima!")
    return min(all_e), max(all_e), min(all_n), max(all_n)


# ── Auto-compute map bounds iz GPS podataka ──────────────────────────────────


def _latlon_to_utm32n(lat_deg, lon_deg):
    """WGS84 → UTM Zone 32N (easting, northing)."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = 2 * f - f * f
    k0, E0 = 0.9996, 500000.0
    lon0 = _math.radians(9.0)
    lat = _math.radians(lat_deg)
    lon = _math.radians(lon_deg)
    N = a / _math.sqrt(1 - e2 * _math.sin(lat) ** 2)
    T = _math.tan(lat) ** 2
    C = e2 / (1 - e2) * _math.cos(lat) ** 2
    A = (lon - lon0) * _math.cos(lat)
    e4, e6 = e2 * e2, e2 * e2 * e2
    M = a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * _math.sin(2 * lat)
        + (15 * e4 / 256 + 45 * e6 / 1024) * _math.sin(4 * lat)
        - (35 * e6 / 3072) * _math.sin(6 * lat)
    )
    ep2 = e2 / (1 - e2)
    easting = (
        k0
        * N
        * (
            A
            + (1 - T + C) * A**3 / 6
            + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A**5 / 120
        )
        + E0
    )
    northing = k0 * (
        M
        + N
        * _math.tan(lat)
        * (
            A**2 / 2
            + (5 - T + 9 * C + 4 * C * C) * A**4 / 24
            + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A**6 / 720
        )
    )
    return easting, northing


if MANUAL_MODE:
    _parts = _CLI.coords.rstrip("z").split(",")
    LAT_CENTER = float(_parts[0])
    LON_CENTER = float(_parts[1])
    _zoom = float(_parts[2]) if len(_parts) > 2 else 14.0
    # Google Maps tile formula: mpp = 156543 * cos(lat) / 2^zoom ; span = mpp * 1024px
    _mpp = 156543.03392 * _math.cos(_math.radians(LAT_CENTER)) / (2.0**_zoom)
    _span_m = _mpp * 1024
    _cos_lat = _math.cos(_math.radians(LAT_CENTER))
    LAT_SPAN = round(_span_m / 111320, 5)
    LON_SPAN = round(_span_m / (111320 * _cos_lat), 5)
    UTM_E_CENTER, UTM_N_CENTER = _latlon_to_utm32n(LAT_CENTER, LON_CENTER)
    print(
        f"MANUELNI centar: {LAT_CENTER}°N {LON_CENTER}°E  zoom={_zoom}  span≈{_span_m:.0f}m"
    )
    print(f"  LAT_SPAN={LAT_SPAN:.5f}°  LON_SPAN={LON_SPAN:.5f}°")
else:
    _e_min, _e_max, _n_min, _n_max = _gps_bounds_from_jsonl([JSONL_PATH1, JSONL_PATH2])
    UTM_E_CENTER = (_e_min + _e_max) / 2
    UTM_N_CENTER = (_n_min + _n_max) / 2
    LAT_CENTER, LON_CENTER = _utm32n_to_latlon(UTM_E_CENTER, UTM_N_CENTER)
    _cos_lat = _math.cos(_math.radians(LAT_CENTER))
    _lat_half = (_n_max - _n_min) / 2 / 111320 * _SAT_MARGIN
    _lon_half = (_e_max - _e_min) / 2 / (111320 * _cos_lat) * _SAT_MARGIN
    LAT_SPAN = round(_lat_half * 2, 5)
    LON_SPAN = round(_lon_half * 2, 5)
    print(f"Auto MAP centar: {LAT_CENTER:.6f}N, {LON_CENTER:.6f}E")
    print(
        f"Auto MAP span:   LAT={LAT_SPAN:.5f}° ({LAT_SPAN*111320:.0f}m)  "
        f"LON={LON_SPAN:.5f}° ({LON_SPAN*111320*_cos_lat:.0f}m)"
    )

# Pretvori MANUAL_LABELS lat/lon stringove → UTM metre (after UTM_E/N_CENTER definisano)
_resolved_labels = []
for _ll_lat, _ll_lon, _ll_text in MANUAL_LABELS:
    _le, _ln = _latlon_to_utm32n(float(_ll_lat), float(_ll_lon))
    _lx = _le - UTM_E_CENTER
    _ly = _ln - UTM_N_CENTER
    _resolved_labels.append((_lx, _ly, _ll_text))
MANUAL_LABELS = _resolved_labels


# ── Invalidiraj satelitski cache ako se centar promijenio ───────────────────
_sat_meta_path = os.path.join(MAPS_DIR, "satellite_meta.json")
_sat_cache_path = os.path.join(MAPS_DIR, "satellite_tile.png")
_sat_meta = {
    "lat": round(LAT_CENTER, 6),
    "lon": round(LON_CENTER, 6),
    "lat_span": LAT_SPAN,
    "lon_span": LON_SPAN,
}
if os.path.exists(_sat_meta_path):
    with open(_sat_meta_path) as _f:
        _old_meta = json.load(_f)
    if _old_meta != _sat_meta:
        print("  Satelitski cache zastarjeo (centar se promijenio) — brišem...")
        if os.path.exists(_sat_cache_path):
            os.remove(_sat_cache_path)
with open(_sat_meta_path, "w") as _f:
    json.dump(_sat_meta, _f)


# ── 1. Elevacijski grid (kesirano) ──────────────────────────────────────────
def _parse_aaigrid(text):
    """Parsira ASCII Grid (AAIGrid) format koji vraca OpenTopography API."""
    lines = text.strip().splitlines()
    header = {}
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
    # OpenTopography vraca redove od sjevera prema jugu — flipujemo za linspace(south→north)
    return np.flipud(arr)


def fetch_elevation_grid():
    lats = np.linspace(LAT_CENTER - LAT_SPAN / 2, LAT_CENTER + LAT_SPAN / 2, GRID_N)
    lons = np.linspace(LON_CENTER - LON_SPAN / 2, LON_CENTER + LON_SPAN / 2, GRID_N)

    cache_path = os.path.join(MAPS_DIR, "elevation_cache.json")

    # ── Cache invalidacija: brisi ako se centar/span promijenio ────────────
    _elev_meta_path = os.path.join(MAPS_DIR, "elevation_meta.json")
    _elev_meta_curr = {
        "lat": round(LAT_CENTER, 6),
        "lon": round(LON_CENTER, 6),
        "lat_span": LAT_SPAN,
        "lon_span": LON_SPAN,
        "grid_n": GRID_N,  # invalidate cache when resolution changes
    }
    if os.path.exists(_elev_meta_path):
        with open(_elev_meta_path) as _mf:
            _old_elev_meta = json.load(_mf)
        if _old_elev_meta != _elev_meta_curr:
            print("  Elevacijski cache zastarjeo (centar se promijenio) — brišem...")
            if os.path.exists(cache_path):
                os.remove(cache_path)

    if os.path.exists(cache_path):
        print("Koristim kesirane visinske podatke...")
        with open(cache_path) as f:
            d = json.load(f)
        return np.array(d["lats"]), np.array(d["lons"]), np.array(d["elev"])

    api_key = OT_API_KEY or os.environ.get("OT_API_KEY", "")
    south = LAT_CENTER - LAT_SPAN / 2
    north = LAT_CENTER + LAT_SPAN / 2
    west = LON_CENTER - LON_SPAN / 2
    east = LON_CENTER + LON_SPAN / 2

    elev = None

    # ── Primarni izvor: OpenTopography Copernicus DEM 30m (COP30) ──
    if api_key:
        print("Preuzimam Copernicus DEM 30m (OpenTopography COP30)...")
        params = {
            "demtype": "COP30",
            "south": south,
            "north": north,
            "west": west,
            "east": east,
            "outputFormat": "AAIGrid",
            "API_Key": api_key,
        }
        try:
            r = requests.get(
                "https://portal.opentopography.org/API/globaldem",
                params=params,
                timeout=60,
            )
            if r.status_code == 200 and "ncols" in r.text[:200]:
                raw = _parse_aaigrid(r.text)
                # Upsample/downsample na GRID_N x GRID_N uz scipy zoom
                from scipy.ndimage import zoom as nd_zoom

                zy = GRID_N / raw.shape[0]
                zx = GRID_N / raw.shape[1]
                elev = nd_zoom(raw, (zy, zx), order=1)
                print(
                    f"  COP30 preuzet ({raw.shape[1]}x{raw.shape[0]} → {GRID_N}x{GRID_N})"
                )
            else:
                print(f"  OpenTopography greska {r.status_code}: {r.text[:120]}")
        except Exception as e:
            print(f"  OpenTopography greska: {e}")
    else:
        print("OT_API_KEY nije postavljen — koristim Open Elevation fallback.")
        print("  Registracija kljuca: https://portal.opentopography.org/requestApiKey")

    # ── Fallback: Open Elevation API (batch POST) ──
    if elev is None:
        print(f"Preuzimam {GRID_N*GRID_N} visinskih tocaka (Open Elevation)...")
        locations = [
            {"latitude": round(float(la), 6), "longitude": round(float(lo), 6)}
            for la in lats
            for lo in lons
        ]
        elev_flat = []
        for i in range(0, len(locations), 256):
            for attempt in range(3):
                try:
                    r = requests.post(
                        "https://api.open-elevation.com/api/v1/lookup",
                        json={"locations": locations[i : i + 256]},
                        timeout=30,
                    )
                    elev_flat.extend([x["elevation"] for x in r.json()["results"]])
                    print(f"  {len(elev_flat)}/{GRID_N*GRID_N}")
                    break
                except Exception as e:
                    print(f"  Retry: {e}")
                    time.sleep(2)
        elev = np.array(elev_flat, dtype=float).reshape(GRID_N, GRID_N)

    with open(cache_path, "w") as f:
        json.dump(
            {"lats": lats.tolist(), "lons": lons.tolist(), "elev": elev.tolist()}, f
        )
    with open(_elev_meta_path, "w") as _mf:
        json.dump(_elev_meta_curr, _mf)
    return lats, lons, elev


lats, lons, elev = fetch_elevation_grid()
from scipy.ndimage import gaussian_filter, map_coordinates

elev_s = gaussian_filter(elev.astype(float), sigma=1.5)
print(f"Elevacija (raw DEM): {elev_s.min():.1f}-{elev_s.max():.1f}m")

x_m = (lons - LON_CENTER) * 111320 * np.cos(np.radians(LAT_CENTER))
y_m = (lats - LAT_CENTER) * 111320
XX, YY = np.meshgrid(x_m, y_m)


# ── DEM kalibracija na GPS altitude ─────────────────────────────────────────
# Open Elevation / SRTM za München regiju ima sistemski offset vs GPS (WGS84).
# Kalibriramo DEM tako da mu medijan u GPS tocki odgovara medianu GPS altitude.
# Relativni reljef (oblik terena) ostaje tocno isti - samo se pomicase na
# pravu apsolutnu visinu.
def _dem_at_xy(xs, ys):
    """Vraca DEM visine (raw, bez kalibracije) za listu (x,y) metrickih kord."""
    col = (np.array(xs) - x_m[0]) / (x_m[-1] - x_m[0]) * (GRID_N - 1)
    row = (np.array(ys) - y_m[0]) / (y_m[-1] - y_m[0]) * (GRID_N - 1)
    col = np.clip(col, 0, GRID_N - 1)
    row = np.clip(row, 0, GRID_N - 1)
    return map_coordinates(elev_s, [row, col], order=1, mode="nearest")


def _read_gps_alt(jsonl_path):
    alts, xs, ys = [], [], []
    with open(jsonl_path) as f:
        for line in f:
            try:
                p = json.loads(line.strip())["payload"]
                alts.append(p["altitude"])
                xs.append(p["easting"] - UTM_E_CENTER)
                ys.append(p["northing"] - UTM_N_CENTER)
            except Exception:
                continue
    return np.array(alts), np.array(xs), np.array(ys)


if MANUAL_MODE:
    DEM_OFFSET = 0.0
    print("DEM kalibracija: preskocena (manuelni mode, offset=0.0m)")
else:
    gps_alt_1, gps_x_1, gps_y_1 = _read_gps_alt(JSONL_PATH1)
    gps_alt_2, gps_x_2, gps_y_2 = _read_gps_alt(JSONL_PATH2)
    all_gps_alt = np.concatenate([gps_alt_1, gps_alt_2])
    all_gps_x = np.concatenate([gps_x_1, gps_x_2])
    all_gps_y = np.concatenate([gps_y_1, gps_y_2])

    dem_at_gps = _dem_at_xy(all_gps_x, all_gps_y)
    DEM_OFFSET = float(np.median(all_gps_alt) - np.median(dem_at_gps))
    print(
        f"DEM kalibracija: offset={DEM_OFFSET:+.1f}m  "
        f"(DEM median={np.median(dem_at_gps)-DEM_OFFSET:.1f}m → GPS median={np.median(all_gps_alt):.1f}m)"
    )

elev_s = elev_s + DEM_OFFSET  # kalibriran DEM
print(f"Elevacija (kalibrirano): {elev_s.min():.1f}-{elev_s.max():.1f}m")

# UGV telemetrija: antena je ~0.5m iznad tla, vizualni offset 1.5m
GPS_HEIGHT = 0.5  # m — visina UGV antene iznad tla


def snap_to_terrain(xs, ys):
    """Interpolira kalibriranu visinu terena i vraca z = teren + GPS_HEIGHT."""
    terrain_z = _dem_at_xy(xs, ys)
    return (terrain_z + GPS_HEIGHT).tolist()


# ── 2. Traversability mapa ───────────────────────────────────────────────────
def compute_traversability(img_path):
    """Segmentira sliku koristeći soca_map HSV+K-Means klasifikator."""
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        print(f"  [WARN] Ne mogu citati sliku: {img_path} — fallback 0.3")
        return np.full((GRID_N, GRID_N), 0.3, dtype=np.float32)
    _, cost, _, _ = _segment_image(img_bgr)
    return cv2.resize(cost, (GRID_N, GRID_N), interpolation=cv2.INTER_AREA)


# cost_map se racuna NAKON fetch_satellite_tile (vidi ispod) — koristi sat tile


def compute_trust_map(c_map, route_specs):
    """
    Generise trust mapu stupnja povjerenja terena.

    route_specs: lista rjecnika:
      {'xs': [...], 'ys': [...], 'trust': float}
        xs/ys   — x/y koordinate u metrima (relativno na centar mape)
        trust   — nivo povjerenja koji ce biti dodijeljen pusjecenim celija:
                  1.00 = UGV potvrdio (TRUST ruta)
                  0.70 = ispitano ali nije vozeno (KNOWN ruta)

    Bazni nivoi (iz cost_map):
      0.00 = voda/blokada (c_map > 0.88)
      0.30 = prekinut put  (mali izolirani road fragment)
      0.50 = suma/vegetacija (c_map 0.45-0.88)
      0.70 = otvoreno zemljiste (c_map < 0.45)
    """
    from scipy.ndimage import gaussian_filter as gf
    from scipy.ndimage import label as nd_label

    trust = np.full((GRID_N, GRID_N), 0.70, dtype=float)

    # Vegetacija / suma → 50 %
    veg_mask = (c_map >= 0.45) & (c_map <= 0.88)
    trust[veg_mask] = 0.50

    # Voda / blokada → 0 %
    water_mask = c_map > 0.88
    trust[water_mask] = 0.00

    # Prekinuti putevi (mali road fragments, cost < 0.17) → 30 %
    road_mask = c_map < 0.17
    labeled, n_comp = nd_label(road_mask)
    for comp_id in range(1, n_comp + 1):
        if (labeled == comp_id).sum() < 5:
            trust[labeled == comp_id] = 0.30

    # GPS rute → nivo povjerenja prema specifikaciji (buffer ±1 celija, ~4m celija = ~12m koridor)
    robot_mask = np.zeros((GRID_N, GRID_N), dtype=bool)
    for spec in route_specs:
        t_level = float(spec["trust"])
        for x, y in zip(spec["xs"], spec["ys"]):
            col = (
                (float(x) - float(x_m[0]))
                / (float(x_m[-1]) - float(x_m[0]))
                * (GRID_N - 1)
            )
            row = (
                (float(y) - float(y_m[0]))
                / (float(y_m[-1]) - float(y_m[0]))
                * (GRID_N - 1)
            )
            col_i = int(np.clip(round(col), 0, GRID_N - 1))
            row_i = int(np.clip(round(row), 0, GRID_N - 1))
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    nr, nc = row_i + dr, col_i + dc
                    if 0 <= nr < GRID_N and 0 <= nc < GRID_N:
                        robot_mask[nr, nc] = True
                        # Samo povecavaj trust, nikad ne smanjuj
                        if t_level > trust[nr, nc]:
                            trust[nr, nc] = t_level

    trust = gf(trust, sigma=0.5)
    # Robot je prosao: ako cost_map kaže blokada ali robot prošao → riskantan (0.9)
    # Prava blokada (bez robota) → 0.0
    trust[water_mask & robot_mask] = 0.90
    trust[water_mask & ~robot_mask] = 0.00
    return np.clip(trust, 0.0, 1.0)


# ── 3. Preuzimanje satelitske tile slike ─────────────────────────────────────
def fetch_satellite_tile():
    """Preuzima ESRI World Imagery tile (1024px), projektuje na GRID_N x GRID_N.

    Vraca:
        sat_surf_color  -- 2D float array (GRID_N x GRID_N) za surfacecolor
        sat_colorscale  -- lista [value, 'rgb(R,G,B)'] za pravo RGB teksturiranje
        sat_b64         -- base64 PNG thumbnail za inset
    """
    cache_sat = os.path.join(MAPS_DIR, "satellite_tile.png")
    lat_min = LAT_CENTER - LAT_SPAN / 2
    lat_max = LAT_CENTER + LAT_SPAN / 2
    lon_min = LON_CENTER - LON_SPAN / 2
    lon_max = LON_CENTER + LON_SPAN / 2

    if not os.path.exists(cache_sat):
        print("Preuzimam satelitsku sliku (ESRI World Imagery 1024px)...")
        url = (
            "https://services.arcgisonline.com/arcgis/rest/services/"
            "World_Imagery/MapServer/export"
            f"?bbox={lon_min},{lat_min},{lon_max},{lat_max}"
            "&bboxSR=4326&imageSR=4326"
            "&size=1024,1024&format=png&f=image"
        )
        try:
            r = requests.get(url, timeout=40)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(cache_sat, "wb") as f:
                    f.write(r.content)
                print(f"  Satelitska slika preuzeta ({len(r.content)//1024}KB)")
            else:
                print(f"  ESRI greska {r.status_code} ({len(r.content)} B)")
        except Exception as e:
            print(f"  ESRI greska: {e}")

    if not os.path.exists(cache_sat):
        print("  Nema satelitske slike — preskacam.")
        return None, None, None

    img_bgr = cv2.imread(cache_sat)
    if img_bgr is None:
        return None, None, None

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    # ESRI vraca sliku s nizom od sjevera prema jugu (y=0 je sjever).
    # Nas linspace ide od juga prema sjeveru → flipujemo vertikalno.
    img_rgb = np.flipud(img_rgb)
    img_sm = cv2.resize(img_rgb, (GRID_N, GRID_N), interpolation=cv2.INTER_AREA)

    # Kvantizujemo na max 256 boja — colorscale ostaje mali, HTML brzi
    from PIL import Image

    pil_img = Image.fromarray(img_sm).quantize(
        colors=256, method=Image.Quantize.MEDIANCUT
    )
    idx_img = np.array(pil_img)  # (GRID_N, GRID_N), indeksi 0..255
    n_colors = int(idx_img.max()) + 1
    sat_surf_color = idx_img.astype(float) / max(n_colors - 1, 1)

    # Colorscale: max 256 unosa umjesto 3600
    palette = np.array(pil_img.getpalette()).reshape(-1, 3)[:n_colors]
    sat_colorscale = [
        [
            round(i / max(n_colors - 1, 1), 6),
            f"rgb({palette[i,0]},{palette[i,1]},{palette[i,2]})",
        ]
        for i in range(n_colors)
    ]

    with open(cache_sat, "rb") as f:
        sat_b64 = base64.b64encode(f.read()).decode()

    print(
        f"  Satelitska tekstura pripremljena ({GRID_N}x{GRID_N}, {n_colors} boja → 3D surface)"
    )
    return sat_surf_color, sat_colorscale, sat_b64


sat_surf_color, sat_colorscale, sat_b64 = fetch_satellite_tile()

# ── Traversability (koristi satelitsku sliku koja je sada dostupna) ──────────
_sat_tile_path = os.path.join(MAPS_DIR, "satellite_tile.png")
cost_map = compute_traversability(
    _sat_tile_path if os.path.exists(_sat_tile_path) else IMG_PATH
)
print(
    f"  Traversability: {(cost_map > 0.88).sum()} blocked / {(cost_map < 0.4).sum()} free cells"
)


# ── 4. JSONL GPS ruta (UTM → metre relativno od centra) ──────────────────────
def load_trust_route(jsonl_path):
    """
    Ucitava GPS rutu iz JSONL.
    UTM easting/northing → metre relativno od LAT/LON centra mape.
    Referentna tocka: UTM_E0, UTM_N0 odgovara LAT_CENTER, LON_CENTER.
    """
    print(f"Ucitavam GPS rutu iz {os.path.basename(jsonl_path)}...")
    rows = []
    with open(jsonl_path) as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
                p = obj["payload"]
                rows.append(
                    {
                        "e": p["easting"],
                        "n": p["northing"],
                        "alt": p["altitude"],
                        "spd": p["vehicle_speed_kmh"],
                        "dist": p["total_distance_m"],
                        "ts": p.get("timestamp", ""),
                    }
                )
            except Exception:
                continue

    # UTM → metri relativno od centra mape (UTM_E_CENTER/N_CENTER auto-computed iz GPS)
    route_x = [(r["e"] - UTM_E_CENTER) for r in rows]  # istok pozitivno
    route_y = [(r["n"] - UTM_N_CENTER) for r in rows]  # sjever pozitivno
    route_z = [r["alt"] for r in rows]
    route_spd = [r["spd"] for r in rows]
    route_dist = [r["dist"] for r in rows]
    route_ts = [r["ts"] for r in rows]

    print(
        f"  {len(rows)} GPS tocaka | "
        f"X: {min(route_x):.1f}–{max(route_x):.1f}m | "
        f"Y: {min(route_y):.1f}–{max(route_y):.1f}m | "
        f"Ukupno: {route_dist[-1]:.1f}m"
    )
    return route_x, route_y, route_z, route_spd, route_dist, route_ts


STEP = 5
KSTEP = 8

if not MANUAL_MODE:
    p1_x, p1_y, p1_z, p1_spd, p1_dist, p1_ts = load_trust_route(JSONL_PATH1)

    # Downsample PATH 1
    STEP = 5
    p1x = p1_x[::STEP]
    p1y = p1_y[::STEP]
    p1z = snap_to_terrain(p1x, p1y)
    p1s = p1_spd[::STEP]
    p1d = p1_dist[::STEP]
    p1t = p1_ts[::STEP]

    # ── PATH 2 (09-51-50) ───────────────────────────────────────────────────────
    print("")
    p2_x, p2_y, p2_z, p2_spd, p2_dist, p2_ts = load_trust_route(JSONL_PATH2)
    KSTEP = 8
    p2x = p2_x[::KSTEP]
    p2y = p2_y[::KSTEP]
    p2z = snap_to_terrain(p2x, p2y)
    p2s = p2_spd[::KSTEP]
    p2d = p2_dist[::KSTEP]
    p2t = p2_ts[::KSTEP]
else:
    # MANUAL_MODE: nema GPS ruta
    p1_x = p1_y = p1_z = p1_spd = p1_dist = p1_ts = []
    p1x = p1y = p1z = p1s = p1d = p1t = []
    p2_x = p2_y = p2_z = p2_spd = p2_dist = p2_ts = []
    p2x = p2y = p2z = p2s = p2d = p2t = []
    print("MANUELNI mode — GPS rute preskocene")

# ── Trust mapa (racuna se tek kad su obje rute ucitane) ──────────────────────
# Obje rute su robotske — 100% provjereno da je teren prohodan
print("Racunam trust mapu...")
trust_map = compute_trust_map(
    cost_map,
    [
        {"xs": p1_x, "ys": p1_y, "trust": 1.00},  # PATH 1: robot potvrdio
        {"xs": p2_x, "ys": p2_y, "trust": 1.00},  # PATH 2: robot potvrdio
    ],
)
print(
    f"  Trust: min={trust_map.min():.2f}  max={trust_map.max():.2f}  "
    f"GPS 100% celija: {(trust_map > 0.95).sum()}  GPS 70%+ celija: {(trust_map >= 0.68).sum()}"
)


# ── Trust overlay PNG za 2D panel ────────────────────────────────────────────
def _make_trust_overlay_b64(tm):
    """Pretvara trust_map u RGBA PNG (isti colorscale) za 2D satelitski panel."""
    from PIL import Image as _PIL_Image

    stops_v = np.array([0.00, 0.30, 0.50, 0.70, 0.90, 1.00])
    # R, G, B, A — zelena zona niska alpha (tlo je uglavnom prolazno)
    stops_c = np.array(
        [
            [139, 0, 0, 195],  # blokada
            [255, 90, 90, 160],  # prekinut put
            [230, 160, 0, 145],  # suma/amber
            [40, 200, 80, 55],  # zelena — niska alpha, samo hint
            [0, 191, 255, 185],  # sky-blue — robot, riskantan
            [30, 144, 255, 210],  # plava — trusted
        ],
        dtype=float,
    )
    flat = tm.ravel()
    out = np.zeros((flat.size, 4), dtype=np.uint8)
    for i in range(len(stops_v) - 1):
        v0, v1 = stops_v[i], stops_v[i + 1]
        mask = (flat >= v0) & (
            flat <= v1 if i < len(stops_v) - 2 else flat <= v1 + 0.001
        )
        if not mask.any():
            continue
        t = (flat[mask] - v0) / (v1 - v0) if v1 > v0 else np.zeros(mask.sum())
        t = t[:, None]
        out[mask] = np.clip(
            stops_c[i] + t * (stops_c[i + 1] - stops_c[i]), 0, 255
        ).astype(np.uint8)
    h, w = tm.shape
    rgba = out.reshape(h, w, 4)
    img = _PIL_Image.fromarray(rgba, "RGBA")
    img = img.resize((300, 300), _PIL_Image.BILINEAR)
    # trust_map row 0 = jug → flipuj za prikaz (sjever gore)
    img = img.transpose(_PIL_Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


trust_overlay_b64 = _make_trust_overlay_b64(trust_map)

# Serialize terrain grids for JS interactive routing engine
_js_cost_data = json.dumps([round(float(v), 3) for v in cost_map.ravel()])
_js_trust_data = json.dumps([round(float(v), 3) for v in trust_map.ravel()])
_js_elev_data = json.dumps([round(float(v), 2) for v in elev_s.ravel()])
_js_xarr_data = json.dumps([round(float(v), 2) for v in x_m])
_js_yarr_data = json.dumps([round(float(v), 2) for v in y_m])


# ── 6. Plotly interaktivna 3D mapa ───────────────────────────────────────────
import plotly.graph_objects as go

colorscale_trav = [
    [0.0, "rgb(0,200,0)"],
    [0.3, "rgb(160,220,0)"],
    [0.5, "rgb(255,200,0)"],
    [0.75, "rgb(255,80,0)"],
    [1.0, "rgb(200,0,0)"],
]

# ─ Surface: Traversability layer ─
surf_trav = go.Surface(
    x=XX,
    y=YY,
    z=elev_s,
    surfacecolor=cost_map,
    colorscale=colorscale_trav,
    cmin=0,
    cmax=1,
    colorbar=dict(
        title="Traversability<br>Cost",
        tickvals=[0, 0.15, 0.4, 0.7, 0.95],
        ticktext=["Slobodno", "Lako", "Srednje", "Teško", "Blokirano"],
        len=0.55,
        x=1.02,
    ),
    opacity=0.88,
    lighting=dict(ambient=0.75, diffuse=0.5, specular=0.05),
    name="Traversability",
    visible=False,
    showscale=True,
)

# ─ Surface: Satelitska projekcija layer ─
# Prava RGB tekstura iz satelitske slike mapirana na 3D teren
if sat_surf_color is not None:
    surf_sat = go.Surface(
        x=XX,
        y=YY,
        z=elev_s,
        surfacecolor=sat_surf_color,
        colorscale=sat_colorscale,
        cmin=0,
        cmax=1,
        opacity=0.95,
        lighting=dict(ambient=0.92, diffuse=0.5, specular=0.02),
        name="Satelitska (ESRI)",
        visible=True,
        showscale=False,
    )
else:
    # Fallback: elevation-based earth colorscale
    elevation_normalized = (elev_s - elev_s.min()) / max(
        elev_s.max() - elev_s.min(), 0.1
    )
    surf_sat = go.Surface(
        x=XX,
        y=YY,
        z=elev_s,
        surfacecolor=elevation_normalized,
        colorscale="earth",
        cmin=0,
        cmax=1,
        opacity=0.90,
        lighting=dict(ambient=0.85, diffuse=0.6, specular=0.1),
        name="Satelitska (elevation fallback)",
        visible=True,
        showscale=False,
    )

# ─ Surface: Trusted Area layer ─
# Semantika boja (dobro se upari sa satelitskim snimkom u hybrid modu):
#   tamno crvena  = apsolutna blokada (voda, zid)      → nikad ne idi
#   svetlo crvena = moguća prepreka / prekinut put     → pazi
#   amber         = šuma / teže prohodan teren         → otežano
#   zelena        = evaluirano s mape, nepotvrdeno UGV → vjerovatno ok
#   sky-blue      = robot prošao, riskantan teren      → oprez
#   plava         = UGV potvrdio prolaz (trusted)      → idi
colorscale_trust = [
    [0.00, "rgb(139,0,0)"],  # tamno crvena — apsolutna blokada
    [0.30, "rgb(255,90,90)"],  # svetlo crvena — prekinut put / upozorenje
    [0.50, "rgb(230,160,0)"],  # amber         — suma / teze prohodan
    [0.70, "rgb(40,200,80)"],  # zelena        — evaluirano s mape, nije UGV
    [0.90, "rgb(0,191,255)"],  # sky-blue      — robot prosao, riskantan teren
    [1.00, "rgb(30,144,255)"],  # plava         — UGV prosao, trusted
]
surf_trust = go.Surface(
    x=XX,
    y=YY,
    z=elev_s,
    surfacecolor=trust_map,
    colorscale=colorscale_trust,
    cmin=0,
    cmax=1,
    opacity=0.70,
    lighting=dict(ambient=0.85, diffuse=0.5, specular=0.02),
    name="Trusted Area",
    visible=False,
    showscale=True,
    colorbar=dict(
        title="Trust %",
        tickvals=[0.0, 0.30, 0.50, 0.70, 0.90, 1.0],
        ticktext=[
            "0% Blokada",
            "30% Put?",
            "50% Šuma",
            "70% Otvoreno",
            "90% Riskantan",
            "100% UGV",
        ],
        len=0.55,
        x=0.88,
    ),
)

traces = [surf_trav, surf_sat, surf_trust]

# ─ PATH 1 (GPS iz JSONL) ─
if len(p1x) > 0:
    hover_p1 = [
        f"<b>PATH 1</b><br>"
        f"Dist: {p1d[i]:.1f}m<br>"
        f"Alt: {p1_z[::STEP][i]:.2f}m<br>"
        f"Brzina: {p1s[i]:.1f}km/h<br>"
        f"Vrijeme: {p1t[i][:19].replace('T',' ')}"
        for i in range(len(p1x))
    ]
    traces.append(
        go.Scatter3d(
            x=p1x,
            y=p1y,
            z=p1z,
            mode="lines+markers",
            line=dict(color="gold", width=6),
            marker=dict(
                size=3,
                color=p1_dist[::STEP],
                colorscale="YlOrRd",
                showscale=False,
            ),
            name=f"PATH 1 (robot, 100% — {p1_dist[-1]:.0f}m)",
            hovertext=hover_p1,
            hoverinfo="text",
        )
    )

    # Markeri start/kraj PATH 1
    traces.append(
        go.Scatter3d(
            x=[p1x[0], p1x[-1]],
            y=[p1y[0], p1y[-1]],
            z=[p1z[0] + 1.5, p1z[-1] + 1.5],
            mode="markers+text",
            marker=dict(
                size=12,
                color=["gold", "orange"],
                symbol="circle",
                line=dict(color="white", width=2),
            ),
            text=["P1 START", "P1 KRAJ"],
            textposition=["top center", "top center"],
            textfont=dict(size=12, color="gold"),
            name="P1 Start/Kraj",
            hoverinfo="text",
        )
    )

# ─ PATH 2 (GPS iz 09-51-50 JSONL) ─
if len(p2x) > 0:
    hover_p2 = [
        f"<b>PATH 2</b><br>"
        f"Dist: {p2d[i]:.1f}m<br>"
        f"Alt: {p2_z[::KSTEP][i]:.2f}m<br>"
        f"Brzina: {p2s[i]:.1f}km/h<br>"
        f"Vrijeme: {p2t[i][:19].replace('T',' ')}"
        for i in range(len(p2x))
    ]
    traces.append(
        go.Scatter3d(
            x=p2x,
            y=p2y,
            z=p2z,
            mode="lines+markers",
            line=dict(color="mediumpurple", width=6),
            marker=dict(
                size=3,
                color=p2_dist[::KSTEP],
                colorscale="Purples",
                showscale=False,
            ),
            name=f"PATH 2 (robot, 100% — {p2_dist[-1]:.0f}m)",
            hovertext=hover_p2,
            hoverinfo="text",
        )
    )
    # Markeri start/kraj PATH 2
    traces.append(
        go.Scatter3d(
            x=[p2x[0], p2x[-1]],
            y=[p2y[0], p2y[-1]],
            z=[p2z[0] + 1.5, p2z[-1] + 1.5],
            mode="markers+text",
            marker=dict(
                size=12,
                color=["mediumpurple", "violet"],
                symbol="square",
                line=dict(color="white", width=2),
            ),
            text=["P2 START", "P2 KRAJ"],
            textposition=["top center", "top center"],
            textfont=dict(size=12, color="mediumpurple"),
            name="P2 Start/Kraj",
            hoverinfo="text",
        )
    )

# ─ Manuelne oznake ─
if MANUAL_LABELS:
    _lbl_xs, _lbl_ys, _lbl_zs, _lbl_ts = [], [], [], []
    _x_step = float(x_m[1] - x_m[0])
    _y_step = float(y_m[1] - y_m[0])
    for _lx, _ly, _lt in MANUAL_LABELS:
        _ci = int(np.clip(round((_lx - float(x_m[0])) / _x_step), 0, GRID_N - 1))
        _ri = int(np.clip(round((_ly - float(y_m[0])) / _y_step), 0, GRID_N - 1))
        _lbl_xs.append(_lx)
        _lbl_ys.append(_ly)
        _lbl_zs.append(float(elev_s[_ri, _ci]) + 3.0)
        _lbl_ts.append(_lt)
    traces.append(
        go.Scatter3d(
            x=_lbl_xs,
            y=_lbl_ys,
            z=_lbl_zs,
            mode="markers+text",
            marker=dict(
                size=10,
                color="cyan",
                symbol="diamond",
                line=dict(color="white", width=1),
            ),
            text=_lbl_ts,
            textposition="top center",
            textfont=dict(size=13, color="cyan"),
            name="Oznake",
            hoverinfo="text",
        )
    )

# ─ Layout ─
fig = go.Figure(data=traces)

# Updatemenus za layer toggle
fig.update_layout(
    updatemenus=[
        dict(
            type="buttons",
            direction="left",
            x=0.01,
            y=1.12,
            xanchor="left",
            bgcolor="rgba(20,20,40,0.9)",
            bordercolor="rgba(255,255,255,0.3)",
            font=dict(color="white", size=12),
            buttons=[
                dict(
                    label="Satelitski",
                    method="update",
                    args=[
                        {
                            "visible": [
                                False,
                                True,
                                False,
                                True,
                                True,
                                True,
                                True,
                                True,
                                True,
                            ]
                        }
                    ],
                ),
                dict(
                    label="Hybrid",
                    method="update",
                    args=[
                        {
                            "visible": [
                                True,
                                True,
                                False,
                                True,
                                True,
                                True,
                                True,
                                True,
                                True,
                            ],
                            "opacity": [0.55, 0.80, 0.70, 1, 1, 1, 1, 1, 1],
                        }
                    ],
                ),
                dict(
                    label="Topografija",
                    method="update",
                    args=[
                        {
                            "visible": [
                                True,
                                False,
                                False,
                                True,
                                True,
                                True,
                                True,
                                True,
                                True,
                            ]
                        }
                    ],
                ),
                dict(
                    label="Trusted Area",
                    method="update",
                    args=[
                        {
                            "visible": [
                                False,
                                True,
                                True,
                                True,
                                True,
                                True,
                                True,
                                True,
                                True,
                            ]
                        }
                    ],
                ),
            ],
        )
    ],
    title=dict(
        text=(
            f"3D Terrain Navigation Map  |  {LAT_CENTER}N, {LON_CENTER}E<br>"
            f"<sup>"
            + (
                f"Zlato = PATH 1 ({p1_dist[-1]:.0f}m, robot 100%)  |  "
                if p1_dist
                else ""
            )
            + (
                f"Ljubicasta = PATH 2 ({p2_dist[-1]:.0f}m, robot 100%)  |  "
                if p2_dist
                else ""
            )
            + "Rutiranje: klikni pinove na 2D panelu  |  Layer toggle gore lijevo"
            "</sup>"
        ),
        x=0.5,
        font=dict(size=15, color="white"),
    ),
    scene=dict(
        xaxis=dict(
            title="Istok-Zapad (m)",
            showbackground=True,
            backgroundcolor="rgb(12,12,28)",
            gridcolor="rgba(100,100,150,0.3)",
        ),
        yaxis=dict(
            title="Sjever-Jug (m)",
            showbackground=True,
            backgroundcolor="rgb(12,12,28)",
            gridcolor="rgba(100,100,150,0.3)",
        ),
        zaxis=dict(
            title="Nadmorska visina (m)",
            showbackground=True,
            backgroundcolor="rgb(8,8,20)",
            gridcolor="rgba(100,100,150,0.3)",
        ),
        bgcolor="rgb(8,8,18)",
        aspectmode="manual",
        aspectratio=dict(x=1.8, y=1.8, z=0.35),
        camera=dict(eye=dict(x=1.3, y=-1.3, z=0.85)),
    ),
    paper_bgcolor="rgb(12,12,25)",
    font=dict(color="white"),
    legend=dict(
        x=0.01,
        y=0.01,
        bgcolor="rgba(20,20,45,0.85)",
        bordercolor="rgba(255,255,255,0.2)",
        borderwidth=1,
        font=dict(size=11),
    ),
    margin=dict(l=0, r=120, t=100, b=0),
    height=800,
)


# ── 2D satelitski bočni panel + JS cursor koji prati 3D hover ────────────────
def to_svg_pts(xs, ys):
    """Pretvara metre koordinate u SVG viewBox (0-100) koordinate."""
    pts = []
    for x, y in zip(xs, ys):
        svgx = (float(x) - float(x_m[0])) / (float(x_m[-1]) - float(x_m[0])) * 100
        svgy = (
            1.0 - (float(y) - float(y_m[0])) / (float(y_m[-1]) - float(y_m[0]))
        ) * 100
        pts.append(f"{svgx:.2f},{svgy:.2f}")
    return " ".join(pts)


p1_svg_pts = to_svg_pts(p1x, p1y)
p2_svg_pts = to_svg_pts(p2x, p2y)

js_xmin = float(x_m[0])
js_xmax = float(x_m[-1])
js_ymin = float(y_m[0])
js_ymax = float(y_m[-1])

# Figura → HTML fragment (bez <html><body> wraппa)
plot_div_html = fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="plotly-3d")

if sat_b64:
    sat_panel_html = f"""  <div id="side-panel">
    <div class="panel-title">&#128225; Satelitska snimka 2D</div>
    <div id="zoom-controls">
      <button id="btn-zoom-reset" title="Reset zoom (R)">&#8635; Reset</button>
      <button id="btn-follow" title="Auto-prati 3D kursor" class="active">&#128247; Prati</button>
      <button id="btn-trust" title="Prikaži/sakrij Trusted Area sloj" class="active">&#128274; Trust</button>
      <span id="zoom-lbl">1.0x</span>
    </div>
    <div id="sat-container">
      <div id="sat-inner">
        <img id="sat-img" src="data:image/png;base64,{sat_b64}" alt="Satelitska snimka"/>
        <img id="trust-overlay-img" src="data:image/png;base64,{trust_overlay_b64}"
             alt="Trust overlay" style="position:absolute;top:0;left:0;width:100%;height:100%;
             pointer-events:none;image-rendering:pixelated;opacity:0.72;"/>
        <svg id="sat-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline points="{p1_svg_pts}" fill="none" stroke="gold" stroke-width="0.9"
                    stroke-opacity="0.92" vector-effect="non-scaling-stroke"/>
          <polyline points="{p2_svg_pts}" fill="none" stroke="mediumpurple" stroke-width="0.9"
                    stroke-opacity="0.92" vector-effect="non-scaling-stroke"/>
          <line id="cur-h" x1="0" y1="50" x2="100" y2="50"
                stroke="red" stroke-width="0.5" stroke-opacity="0.65"
                vector-effect="non-scaling-stroke" style="display:none"/>
          <line id="cur-v" x1="50" y1="0" x2="50" y2="100"
                stroke="red" stroke-width="0.5" stroke-opacity="0.65"
                vector-effect="non-scaling-stroke" style="display:none"/>
          <circle id="cur-circle" cx="50" cy="50" r="1.2"
                  fill="none" stroke="red" stroke-width="0.7"
                  vector-effect="non-scaling-stroke" style="display:none"/>
        </svg>
      </div>
    </div>
    <div id="hover-info">Scroll = zoom &bull; Drag = pan</div>
    <div id="legend">
      <div class="leg"><span class="leg-dot" style="background:gold"></span>PATH 1 &ndash; robot ({f"{p1_dist[-1]:.0f}" if p1_dist else "--"} m, 100%)</div>
      <div class="leg"><span class="leg-dot" style="background:mediumpurple"></span>PATH 2 &ndash; robot ({f"{p2_dist[-1]:.0f}" if p2_dist else "--"} m, 100%)</div>
      <hr class="leg-sep"/>
      <div class="leg-head">Trusted Area sloj:</div>
      <div class="leg"><span class="leg-dot" style="background:rgb(30,144,255)"></span>100% &ndash; UGV robot pro&scaron;ao</div>
      <div class="leg"><span class="leg-dot" style="background:rgb(0,191,255)"></span>90% &ndash; Robot pro&scaron;ao, riskantan teren</div>
      <div class="leg"><span class="leg-dot" style="background:rgb(40,200,80)"></span>70% &ndash; Evaluirano s mape</div>
      <div class="leg"><span class="leg-dot" style="background:rgb(230,160,0)"></span>50% &ndash; &Scaron;uma / te&zcaron;e prohodan</div>
      <div class="leg"><span class="leg-dot" style="background:rgb(255,90,90)"></span>30% &ndash; Prekinut put / upozorenje</div>
      <div class="leg"><span class="leg-dot" style="background:rgb(139,0,0)"></span>0% &ndash; Apsolutna blokada</div>
    </div>
    <hr class="leg-sep" style="margin-top:12px"/>
    <div class="panel-title" style="margin-top:8px">&#128506; Rutiranje</div>
    <div id="route-pin-mode">
      <button id="btn-pin-start" class="pin-btn active">&#128205; Postavi Start</button>
      <button id="btn-pin-end" class="pin-btn">&#127937; Postavi Kraj</button>
    </div>
    <div class="coord-row">
      <span class="coord-lbl">Start:</span>
      <input id="inp-sx" type="number" step="1" class="coord-inp" placeholder="X (m)"/>
      <input id="inp-sy" type="number" step="1" class="coord-inp" placeholder="Y (m)"/>
    </div>
    <div class="coord-row">
      <span class="coord-lbl">Kraj:</span>
      <input id="inp-ex" type="number" step="1" class="coord-inp" placeholder="X (m)"/>
      <input id="inp-ey" type="number" step="1" class="coord-inp" placeholder="Y (m)"/>
    </div>
    <div id="route-calc-btns">
      <button id="btn-route-short" class="route-calc-btn">&#128207; Najkra&#263;a</button>
      <button id="btn-route-fast" class="route-calc-btn">&#9889; Najbr&#382;a</button>
      <button id="btn-route-safe" class="route-calc-btn">&#128737; Najsigurnija</button>
      <button id="btn-route-clear" class="route-calc-btn clr-btn">&#10005; Obri&#353;i</button>
    </div>
    <div id="route-result">Klikni na satelitsku snimku za odabir ta&#269;aka.</div>
  </div>"""
else:
    sat_panel_html = ""

full_html = f"""<!DOCTYPE html>
<html lang="hr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>3D Terrain Navigation Map &ndash; SOCA</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #08080e;
      display: flex;
      height: 100vh;
      overflow: hidden;
      font-family: 'Segoe UI', system-ui, sans-serif;
      color: #ddd;
    }}
    #plot-wrap {{ flex: 1; min-width: 0; position: relative; }}
    #plot-wrap > div {{ width: 100% !important; height: 100% !important; }}
    #side-panel {{
      width: 380px;
      flex-shrink: 0;
      background: #0a0a1a;
      border-left: 1px solid rgba(255,255,255,0.12);
      display: flex;
      flex-direction: column;
      padding: 12px;
      overflow-y: auto;
      gap: 0;
    }}
    .panel-title {{
      font-size: 12px;
      font-weight: 600;
      color: #aaa;
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: 1px;
    }}
    #sat-container {{
      position: relative;
      width: 100%;
      flex: 1;
      min-height: 280px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.15);
      cursor: grab;
    }}
    #sat-inner {{
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      transform-origin: 0 0;
      will-change: transform;
    }}
    #sat-img {{
      width: 100%;
      height: 100%;
      display: block;
      object-fit: fill;
      image-rendering: crisp-edges;
      user-select: none;
      -webkit-user-drag: none;
    }}
    #zoom-controls {{
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 6px;
    }}
    #zoom-controls button {{
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.18);
      color: #ccc;
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 4px;
      cursor: pointer;
    }}
    #zoom-controls button:hover {{ background: rgba(255,255,255,0.16); }}
    #zoom-controls button.active {{ border-color: #1e90ff; color: #1e90ff; }}
    #zoom-lbl {{
      font-size: 11px;
      color: #666;
      margin-left: auto;
    }}
    #sat-overlay {{
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      pointer-events: none;
    }}
    #hover-info {{
      font-size: 11px;
      color: #999;
      margin-top: 8px;
      min-height: 36px;
      line-height: 1.6;
    }}
    #legend {{ margin-top: 12px; }}
    .leg-head {{ font-size: 11px; color: #888; margin-bottom: 4px; font-style: italic; }}
    .leg {{
      display: flex;
      align-items: center;
      font-size: 11px;
      color: #bbb;
      margin-bottom: 5px;
    }}
    .leg-dot {{
      width: 10px; height: 10px;
      border-radius: 50%;
      margin-right: 7px;
      flex-shrink: 0;
      border: 1px solid rgba(255,255,255,0.2);
    }}
    .leg-sep {{
      border: none;
      border-top: 1px solid rgba(255,255,255,0.1);
      margin: 8px 0;
    }}
    #route-pin-mode {{ display:flex; gap:6px; margin:6px 0 8px; }}
    .pin-btn {{
      flex:1; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.18);
      color:#ccc; font-size:10px; padding:4px 6px; border-radius:4px; cursor:pointer;
    }}
    .pin-btn.active {{ border-color:#00ff88; color:#00ff88; background:rgba(0,255,136,0.08); }}
    .coord-row {{ display:flex; align-items:center; gap:4px; margin-bottom:5px; }}
    .coord-lbl {{ font-size:10px; color:#888; width:32px; flex-shrink:0; }}
    .coord-inp {{
      flex:1; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.15);
      color:#ddd; font-size:10px; padding:3px 5px; border-radius:3px; min-width:0;
    }}
    #route-calc-btns {{ display:grid; grid-template-columns:1fr 1fr; gap:5px; margin-top:6px; }}
    .route-calc-btn {{
      background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.18);
      color:#ccc; font-size:10px; padding:5px 4px; border-radius:4px; cursor:pointer; text-align:center;
    }}
    .route-calc-btn:hover {{ background:rgba(255,255,255,0.14); }}
    .route-calc-btn.active {{ border-color:#1e90ff; color:#1e90ff; background:rgba(30,144,255,0.12); }}
    .clr-btn {{ border-color:rgba(200,60,60,0.5) !important; color:#f98 !important; background:rgba(180,40,40,0.2) !important; }}
    #route-result {{
      margin-top:8px; font-size:11px; color:#aaa; line-height:1.7;
      padding:7px 8px; background:rgba(0,0,0,0.3); border-radius:4px;
      min-height:28px; border:1px solid rgba(255,255,255,0.07);
    }}
  </style>
</head>
<body>
  <div id="plot-wrap">{plot_div_html}</div>
{sat_panel_html}
  <script>
    (function () {{
      var xMin = {js_xmin:.4f}, xMax = {js_xmax:.4f};
      var yMin = {js_ymin:.4f}, yMax = {js_ymax:.4f};

      function worldToSVG(x, y) {{
        return {{
          sx: (x - xMin) / (xMax - xMin) * 100,
          sy: (1 - (y - yMin) / (yMax - yMin)) * 100
        }};
      }}

      // ── 2D panel zoom / pan ──────────────────────────────────────────────
      var zs = {{ z: 1, dx: 0, dy: 0, drag: false, lx: 0, ly: 0, follow: true }};
      var satInner = document.getElementById('sat-inner');
      var satCont  = document.getElementById('sat-container');
      var zoomLbl  = document.getElementById('zoom-lbl');
      var btnFollow = document.getElementById('btn-follow');

      function clampPan() {{
        var w = satCont.offsetWidth, h = satCont.offsetHeight;
        zs.dx = Math.min(0, Math.max(-(zs.z - 1) * w, zs.dx));
        zs.dy = Math.min(0, Math.max(-(zs.z - 1) * h, zs.dy));
      }}

      function applyTransform() {{
        if (!satInner) return;
        satInner.style.transform =
          'translate(' + zs.dx + 'px,' + zs.dy + 'px) scale(' + zs.z + ')';
        if (zoomLbl) zoomLbl.textContent = zs.z.toFixed(1) + 'x';
      }}

      function panToSVG(sx, sy) {{
        if (!zs.follow || zs.z <= 1 || !satCont) return;
        var w = satCont.offsetWidth, h = satCont.offsetHeight;
        zs.dx = w / 2 - (sx / 100) * w * zs.z;
        zs.dy = h / 2 - (sy / 100) * h * zs.z;
        clampPan();
        applyTransform();
      }}

      if (satCont) {{
        satCont.addEventListener('wheel', function(e) {{
          e.preventDefault();
          var rect = satCont.getBoundingClientRect();
          var mx = e.clientX - rect.left, my = e.clientY - rect.top;
          var factor = e.deltaY < 0 ? 1.3 : 1 / 1.3;
          var newZ = Math.max(1, Math.min(8, zs.z * factor));
          zs.dx = mx - (mx - zs.dx) * (newZ / zs.z);
          zs.dy = my - (my - zs.dy) * (newZ / zs.z);
          zs.z  = newZ;
          clampPan();
          applyTransform();
        }}, {{ passive: false }});

        satCont.addEventListener('mousedown', function(e) {{
          if (e.button !== 0) return;
          zs.drag = true; zs.lx = e.clientX; zs.ly = e.clientY;
          satCont.style.cursor = 'grabbing';
          e.preventDefault();
        }});
        window.addEventListener('mousemove', function(e) {{
          if (!zs.drag) return;
          zs.dx += e.clientX - zs.lx; zs.dy += e.clientY - zs.ly;
          zs.lx = e.clientX; zs.ly = e.clientY;
          clampPan(); applyTransform();
        }});
        window.addEventListener('mouseup', function() {{
          if (zs.drag) {{ zs.drag = false; satCont.style.cursor = 'grab'; }}
        }});
      }}

      var btnReset = document.getElementById('btn-zoom-reset');
      if (btnReset) btnReset.addEventListener('click', function() {{
        zs.z = 1; zs.dx = 0; zs.dy = 0; applyTransform();
      }});

      if (btnFollow) btnFollow.addEventListener('click', function() {{
        zs.follow = !zs.follow;
        btnFollow.classList.toggle('active', zs.follow);
      }});

      var btnTrust = document.getElementById('btn-trust');
      var trustOverlay = document.getElementById('trust-overlay-img');
      if (btnTrust && trustOverlay) {{
        btnTrust.addEventListener('click', function() {{
          var visible = trustOverlay.style.display !== 'none';
          trustOverlay.style.display = visible ? 'none' : '';
          btnTrust.classList.toggle('active', !visible);
        }});
      }}

      window.addEventListener('keydown', function(e) {{
        if (e.key === 'r' || e.key === 'R') {{
          zs.z = 1; zs.dx = 0; zs.dy = 0; applyTransform();
        }}
      }});

      // ── 3D hover → cursor + auto-pan ────────────────────────────────────
      function attachHover() {{
        var plotDiv = document.getElementById('plotly-3d');
        if (!plotDiv || typeof plotDiv.on !== 'function') {{
          setTimeout(attachHover, 300);
          return;
        }}
        var curCircle = document.getElementById('cur-circle');
        var curH      = document.getElementById('cur-h');
        var curV      = document.getElementById('cur-v');
        var hoverInfo = document.getElementById('hover-info');

        plotDiv.on('plotly_hover', function (ev) {{
          if (!ev.points || !ev.points[0]) return;
          var pt = ev.points[0];
          var p  = worldToSVG(pt.x, pt.y);

          if (curCircle) {{
            curCircle.setAttribute('cx', p.sx); curCircle.setAttribute('cy', p.sy);
            curCircle.style.display = '';
          }}
          if (curH) {{ curH.setAttribute('y1', p.sy); curH.setAttribute('y2', p.sy); curH.style.display = ''; }}
          if (curV) {{ curV.setAttribute('x1', p.sx); curV.setAttribute('x2', p.sx); curV.style.display = ''; }}

          panToSVG(p.sx, p.sy);

          if (hoverInfo) hoverInfo.innerHTML =
            '<b style="color:#fff">Pozicija:</b><br>' +
            'X: ' + pt.x.toFixed(1) + ' m &nbsp; Y: ' + pt.y.toFixed(1) + ' m<br>' +
            'Visina: ' + (pt.z ? pt.z.toFixed(1) + ' m' : '&mdash;');
        }});

        plotDiv.on('plotly_unhover', function () {{
          if (curCircle) curCircle.style.display = 'none';
          if (curH)      curH.style.display      = 'none';
          if (curV)      curV.style.display      = 'none';
          if (hoverInfo) hoverInfo.innerHTML = 'Scroll = zoom &bull; Drag = pan &bull; R = reset';
        }});
      }}

      window.addEventListener('load', function () {{ setTimeout(attachHover, 500); }});
    }})();

    // ── Interactive Routing Engine ─────────────────────────────────────────
    window.addEventListener('load', function () {{
      var GN         = {GRID_N};
      var costData   = {_js_cost_data};
      var trustData  = {_js_trust_data};
      var elevData   = {_js_elev_data};
      var xArr       = {_js_xarr_data};
      var yArr       = {_js_yarr_data};
      var xMin2=xArr[0], xMax2=xArr[GN-1], yMin2=yArr[0], yMax2=yArr[GN-1];
      var cellW=(xMax2-xMin2)/(GN-1), cellH=(yMax2-yMin2)/(GN-1);

      function cm(r,c){{return costData[r*GN+c]||0;}}
      function tm(r,c){{return trustData[r*GN+c]||0;}}
      function em(r,c){{return elevData[r*GN+c]||0;}}
      function passable(r,c){{
        if(r<0||r>=GN||c<0||c>=GN) return false;
        if(tm(r,c)<=0.01) return false;
        if(cm(r,c)>0.88&&tm(r,c)<0.85) return false;
        return true;
      }}
      var D8=[[-1,0],[-1,1],[-1,-1],[1,0],[1,1],[1,-1],[0,-1],[0,1]];

      // Binary min-heap
      function Heap(){{this.h=[];}}
      Heap.prototype.push=function(v){{
        this.h.push(v);var i=this.h.length-1,p;
        while(i>0){{p=(i-1)>>1;if(this.h[p][0]<=this.h[i][0])break;var t=this.h[p];this.h[p]=this.h[i];this.h[i]=t;i=p;}}
      }};
      Heap.prototype.pop=function(){{
        var top=this.h[0],last=this.h.pop();
        if(this.h.length>0){{
          this.h[0]=last;var i=0,n=this.h.length;
          for(;;){{var l=2*i+1,r2=2*i+2,m=i;if(l<n&&this.h[l][0]<this.h[m][0])m=l;if(r2<n&&this.h[r2][0]<this.h[m][0])m=r2;if(m===i)break;var t=this.h[m];this.h[m]=this.h[i];this.h[i]=t;i=m;}}
        }}
        return top;
      }};
      Heap.prototype.size=function(){{return this.h.length;}};

      function astar(sr,sc,gr,gc,mode){{
        var INF=1e18,N=GN*GN;
        var g=new Float64Array(N).fill(INF);
        var from=new Int32Array(N).fill(-1);
        var closed=new Uint8Array(N);
        var si=sr*GN+sc,gi=gr*GN+gc;
        g[si]=0;
        var heap=new Heap();
        function h(r,c){{var dr=(r-gr)*cellH,dc=(c-gc)*cellW;return 0.08*Math.sqrt(dr*dr+dc*dc);}}
        heap.push([h(sr,sc),sr,sc]);
        while(heap.size()>0){{
          var cur=heap.pop(),cr=cur[1],cc=cur[2],ci=cr*GN+cc;
          if(closed[ci])continue; closed[ci]=1;
          if(ci===gi)break;
          for(var d=0;d<8;d++){{
            var dr=D8[d][0],dc=D8[d][1],nr=cr+dr,nc=cc+dc;
            if(!passable(nr,nc))continue;
            var ni=nr*GN+nc; if(closed[ni])continue;
            var dxy=Math.sqrt((dr*cellH)*(dr*cellH)+(dc*cellW)*(dc*cellW));
            if(dxy<0.01)dxy=0.01;
            var dh=Math.abs(em(nr,nc)-em(cr,cc));
            var sl=Math.min(Math.atan(dh/dxy)*57.3/30,1.5);
            var ng;
            if(mode==='shortest'){{
              ng=g[ci]+dxy;
            }}else if(mode==='fastest'){{
              ng=g[ci]+dxy*(cm(nr,nc)+sl*0.5+0.1);
            }}else{{
              ng=g[ci]+dxy*(2.0-tm(nr,nc))*(1+sl);
            }}
            if(ng<g[ni]){{g[ni]=ng;from[ni]=ci;heap.push([ng+h(nr,nc),nr,nc]);}}
          }}
        }}
        if(g[gi]>=INF)return null;
        var path=[],c2=gi;
        while(c2!==si){{path.push([Math.floor(c2/GN),c2%GN]);c2=from[c2];if(c2<0)return null;}}
        path.push([sr,sc]);return path.reverse();
      }}

      function pathStats(path){{
        var dist=0,tsum=0,csum=0;
        for(var i=0;i<path.length;i++){{
          tsum+=tm(path[i][0],path[i][1]);
          csum+=cm(path[i][0],path[i][1]);
          if(i>0){{var dx=(path[i][1]-path[i-1][1])*cellW,dy=(path[i][0]-path[i-1][0])*cellH;dist+=Math.sqrt(dx*dx+dy*dy);}}
        }}
        var n=path.length||1;
        var at=tsum/n, ac=csum/n;
        var spd=Math.max(0.3,2.8*(1-0.5*ac)*(0.5+0.5*at));
        return {{dist:dist,avgTrust:at,avgCost:ac,timeSec:dist/1000*3600/spd}};
      }}

      function worldToGrid2(wx,wy){{
        var c=Math.round((wx-xArr[0])/(xArr[GN-1]-xArr[0])*(GN-1));
        var r=Math.round((wy-yArr[0])/(yArr[GN-1]-yArr[0])*(GN-1));
        return [Math.max(0,Math.min(GN-1,r)),Math.max(0,Math.min(GN-1,c))];
      }}
      function worldToSVG2(wx,wy){{
        return {{sx:(wx-xMin2)/(xMax2-xMin2)*100,sy:(1-(wy-yMin2)/(yMax2-yMin2))*100}};
      }}

      // DOM refs
      var satCont2=document.getElementById('sat-container');
      var svgEl2=document.getElementById('sat-overlay');
      var inpSx=document.getElementById('inp-sx'),inpSy=document.getElementById('inp-sy');
      var inpEx=document.getElementById('inp-ex'),inpEy=document.getElementById('inp-ey');
      var btnPinStart=document.getElementById('btn-pin-start');
      var btnPinEnd=document.getElementById('btn-pin-end');
      var btnShort=document.getElementById('btn-route-short');
      var btnFast=document.getElementById('btn-route-fast');
      var btnSafe=document.getElementById('btn-route-safe');
      var btnClear2=document.getElementById('btn-route-clear');
      var routeResult=document.getElementById('route-result');
      if(!satCont2)return;

      var startPt=null,endPt=null,placingMode='start',_routeCount=0;

      function svgPin(id,cx,cy,color,label){{
        var old=svgEl2.querySelector('#'+id);if(old)old.parentNode.removeChild(old);
        var g=document.createElementNS('http://www.w3.org/2000/svg','g');g.setAttribute('id',id);
        var ci=document.createElementNS('http://www.w3.org/2000/svg','circle');
        ci.setAttribute('cx',cx);ci.setAttribute('cy',cy);ci.setAttribute('r','2.2');
        ci.setAttribute('fill',color);ci.setAttribute('stroke','white');ci.setAttribute('stroke-width','0.5');
        ci.setAttribute('vector-effect','non-scaling-stroke');
        var tx=document.createElementNS('http://www.w3.org/2000/svg','text');
        tx.setAttribute('x',cx+2.8);tx.setAttribute('y',cy-2.2);tx.setAttribute('fill',color);
        tx.setAttribute('font-size','4.5');tx.setAttribute('font-weight','bold');
        tx.setAttribute('vector-effect','non-scaling-stroke');tx.textContent=label;
        g.appendChild(ci);g.appendChild(tx);svgEl2.appendChild(g);
      }}
      function removePin(id){{var old=svgEl2.querySelector('#'+id);if(old)old.parentNode.removeChild(old);}}

      function clickToWorld(e){{
        var rect=satCont2.getBoundingClientRect();
        var cx2=e.clientX-rect.left,cy2=e.clientY-rect.top;
        var inner=document.getElementById('sat-inner');
        var tr=inner?inner.style.transform||'':"";
        var m=tr.match(/translate\\(([-0-9.]+)px,([-0-9.]+)px\\)\\s*scale\\(([-0-9.]+)\\)/);
        var dx=m?parseFloat(m[1]):0,dy=m?parseFloat(m[2]):0,sc=m?parseFloat(m[3]):1;
        var fx=(cx2-dx)/sc/rect.width,fy=(cy2-dy)/sc/rect.height;
        return {{x:xMin2+fx*(xMax2-xMin2),y:yMax2-fy*(yMax2-yMin2)}};
      }}

      function updatePinMode(){{
        if(btnPinStart)btnPinStart.classList.toggle('active',placingMode==='start');
        if(btnPinEnd)btnPinEnd.classList.toggle('active',placingMode==='end');
      }}

      // Drag detection — skip click if user panned
      var _mdPos=null;
      satCont2.addEventListener('mousedown',function(e){{_mdPos={{x:e.clientX,y:e.clientY}};}},true);
      satCont2.addEventListener('click',function(e){{
        if(_mdPos&&Math.hypot(e.clientX-_mdPos.x,e.clientY-_mdPos.y)>6)return;
        var pt=clickToWorld(e),sp=worldToSVG2(pt.x,pt.y);
        if(placingMode==='start'){{
          startPt=pt;svgPin('pin-start',sp.sx,sp.sy,'#00ff88','S');
          if(inpSx)inpSx.value=pt.x.toFixed(1);if(inpSy)inpSy.value=pt.y.toFixed(1);
          placingMode='end';
          if(routeResult)routeResult.innerHTML='Postavi krajnju ta&#269;ku &rarr; klikni E.';
        }}else{{
          endPt=pt;svgPin('pin-end',sp.sx,sp.sy,'#ff5555','E');
          if(inpEx)inpEx.value=pt.x.toFixed(1);if(inpEy)inpEy.value=pt.y.toFixed(1);
          placingMode='start';
          if(routeResult)routeResult.innerHTML='Odaberi tip rute.';
        }}
        updatePinMode();
      }});

      // Manual coordinate input
      function syncInputPins(){{
        if(inpSx&&inpSx.value!==''&&inpSy&&inpSy.value!==''){{
          startPt={{x:parseFloat(inpSx.value),y:parseFloat(inpSy.value)}};
          var s=worldToSVG2(startPt.x,startPt.y);svgPin('pin-start',s.sx,s.sy,'#00ff88','S');
        }}
        if(inpEx&&inpEx.value!==''&&inpEy&&inpEy.value!==''){{
          endPt={{x:parseFloat(inpEx.value),y:parseFloat(inpEy.value)}};
          var e2=worldToSVG2(endPt.x,endPt.y);svgPin('pin-end',e2.sx,e2.sy,'#ff5555','E');
        }}
      }}
      [inpSx,inpSy,inpEx,inpEy].forEach(function(inp){{if(inp)inp.addEventListener('change',syncInputPins);}});
      if(btnPinStart)btnPinStart.addEventListener('click',function(){{placingMode='start';updatePinMode();}});
      if(btnPinEnd)btnPinEnd.addEventListener('click',function(){{placingMode='end';updatePinMode();}});

      // 3D route management
      function clearRoute3D(){{
        var gd=document.getElementById('plotly-3d');
        if(!gd||!gd.data||_routeCount<1)return;
        var idxs=[];for(var i=gd.data.length-_routeCount;i<gd.data.length;i++)idxs.push(i);
        Plotly.deleteTraces(gd,idxs);_routeCount=0;
      }}

      function drawRoute(path,mode){{
        var colors={{shortest:'#00ff88',fastest:'#ffd700',safest:'#00cfff'}};
        var names={{shortest:'Najkra\u0107a ruta',fastest:'Najbr\u017ea ruta',safest:'Najsigurnija ruta'}};
        var col=colors[mode]||'#fff',name=names[mode]||'Ruta';
        var px=[],py=[],pz=[];
        for(var i=0;i<path.length;i++){{
          px.push(xArr[path[i][1]]);py.push(yArr[path[i][0]]);
          pz.push(elevData[path[i][0]*GN+path[i][1]]+2.5);
        }}
        // SVG polyline
        var old=svgEl2.querySelector('#route-line-svg');if(old)old.parentNode.removeChild(old);
        var poly=document.createElementNS('http://www.w3.org/2000/svg','polyline');
        poly.setAttribute('id','route-line-svg');
        poly.setAttribute('points',px.map(function(x,i){{var s=worldToSVG2(x,py[i]);return s.sx.toFixed(2)+','+s.sy.toFixed(2);}}).join(' '));
        poly.setAttribute('fill','none');poly.setAttribute('stroke',col);
        poly.setAttribute('stroke-width','1.5');poly.setAttribute('stroke-opacity','0.95');
        poly.setAttribute('vector-effect','non-scaling-stroke');
        svgEl2.insertBefore(poly,svgEl2.firstChild);
        // 3D
        clearRoute3D();
        var gd=document.getElementById('plotly-3d');if(!gd)return;
        var n=px.length;
        Plotly.addTraces(gd,[
          {{type:'scatter3d',x:px,y:py,z:pz,mode:'lines',line:{{color:col,width:5}},name:name,hoverinfo:'skip'}},
          {{type:'scatter3d',
            x:[px[0],px[n-1]],y:[py[0],py[n-1]],z:[pz[0]+1.5,pz[n-1]+1.5],
            mode:'markers+text',
            marker:{{size:11,color:[col,'#ff8800'],symbol:'diamond',line:{{color:'white',width:1}}}},
            text:['RUTA START','RUTA KRAJ'],textposition:'top center',
            textfont:{{size:10,color:col}},name:name+' S/K',hoverinfo:'text'}}
        ]);
        _routeCount=2;
      }}

      function calcRoute(mode){{
        if(!startPt||!endPt){{
          if(routeResult)routeResult.innerHTML='<span style="color:#f88">Postavi startnu i krajnju ta&#269;ku.</span>';
          return;
        }}
        var sg=worldToGrid2(startPt.x,startPt.y),eg=worldToGrid2(endPt.x,endPt.y);
        if(!passable(sg[0],sg[1])){{if(routeResult)routeResult.innerHTML='<span style="color:#f88">&#9888; Start je na neprolaznom terenu!</span>';return;}}
        if(!passable(eg[0],eg[1])){{if(routeResult)routeResult.innerHTML='<span style="color:#f88">&#9888; Kraj je na neprolaznom terenu!</span>';return;}}
        if(routeResult)routeResult.innerHTML='<i style="color:#888">Ra&#269;unam A*...</i>';
        [btnShort,btnFast,btnSafe].forEach(function(b){{if(b)b.classList.remove('active');}});
        var ab={{shortest:btnShort,fastest:btnFast,safest:btnSafe}}[mode];
        if(ab)ab.classList.add('active');
        setTimeout(function(){{
          var path=astar(sg[0],sg[1],eg[0],eg[1],mode);
          if(!path){{if(routeResult)routeResult.innerHTML='<span style="color:#f88">&#9888; Nema dostupne rute.</span>';return;}}
          var st=pathStats(path);
          var mm=Math.floor(st.timeSec/60),ss=Math.round(st.timeSec%60);
          var mn={{shortest:'Najkra\u0107a',fastest:'Najbr\u017ea',safest:'Najsigurnija'}};
          if(routeResult)routeResult.innerHTML=
            '<b style="color:#ddd">'+mn[mode]+':</b><br>'+
            '&#128207; Du\u017eina: <b>'+st.dist.toFixed(0)+'m</b>&emsp;'+
            '&#9201; Procjena: <b>'+mm+'min '+ss+'s</b><br>'+
            '&#128737; Prosj. trust: <b>'+(st.avgTrust*100).toFixed(0)+'%</b>&emsp;'+
            '&#128200; To&#269;ke: <b>'+path.length+'</b>';
          drawRoute(path,mode);
        }},10);
      }}

      if(btnShort)btnShort.addEventListener('click',function(){{calcRoute('shortest');}});
      if(btnFast)btnFast.addEventListener('click',function(){{calcRoute('fastest');}});
      if(btnSafe)btnSafe.addEventListener('click',function(){{calcRoute('safest');}});

      if(btnClear2)btnClear2.addEventListener('click',function(){{
        startPt=null;endPt=null;
        removePin('pin-start');removePin('pin-end');
        var old=svgEl2.querySelector('#route-line-svg');if(old)old.parentNode.removeChild(old);
        [inpSx,inpSy,inpEx,inpEy].forEach(function(i){{if(i)i.value='';}});
        if(routeResult)routeResult.innerHTML='Klikni na satelitsku snimku za odabir ta&#269;aka.';
        clearRoute3D();
        [btnShort,btnFast,btnSafe].forEach(function(b){{if(b)b.classList.remove('active');}});
        placingMode='start';updatePinMode();
      }});
    }});
  </script>
</body>
</html>"""

with open(OUT_HTML, "w", encoding="utf-8") as _f:
    _f.write(full_html)
print(f"\nInteraktivna 3D mapa (2D panel + Trusted Area): {OUT_HTML}")

# ── 7. Statican PNG (matplotlib) ─────────────────────────────────────────────
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

fig2 = plt.figure(figsize=(18, 11), facecolor="#08080e")
ax = fig2.add_subplot(111, projection="3d", facecolor="#08080e")

norm = Normalize(vmin=0, vmax=1)
colors = plt.cm.RdYlGn_r(norm(cost_map))
ax.plot_surface(
    XX, YY, elev_s, facecolors=colors, linewidth=0, antialiased=True, alpha=0.88
)

# PATH 1
for i in range(len(p1x) - 1):
    ax.plot(
        [p1x[i], p1x[i + 1]],
        [p1y[i], p1y[i + 1]],
        [p1z[i], p1z[i + 1]],
        color="gold",
        lw=2.5,
        zorder=12,
    )
if len(p1x) > 0:
    ax.scatter(
        [p1x[0]],
        [p1y[0]],
        [p1z[0] + 1],
        color="gold",
        s=120,
        marker="D",
        zorder=13,
        label="P1 START",
    )
    ax.scatter(
        [p1x[-1]],
        [p1y[-1]],
        [p1z[-1] + 1],
        color="orange",
        s=120,
        marker="D",
        zorder=13,
        label="P1 KRAJ",
    )

# PATH 2
if len(p2x) > 0:
    for i in range(len(p2x) - 1):
        ax.plot(
            [p2x[i], p2x[i + 1]],
            [p2y[i], p2y[i + 1]],
            [p2z[i], p2z[i + 1]],
            color="mediumpurple",
            lw=2.0,
            zorder=11,
        )
    ax.scatter(
        [p2x[0]],
        [p2y[0]],
        [p2z[0] + 1],
        color="mediumpurple",
        s=120,
        marker="s",
        zorder=13,
        label="P2 START",
    )
    ax.scatter(
        [p2x[-1]],
        [p2y[-1]],
        [p2z[-1] + 1],
        color="violet",
        s=120,
        marker="s",
        zorder=13,
        label="P2 KRAJ",
    )

# Manuelne oznake
_x_step_m = float(x_m[1] - x_m[0])
_y_step_m = float(y_m[1] - y_m[0])
for _lx, _ly, _lt in MANUAL_LABELS:
    _ci = int(np.clip(round((_lx - float(x_m[0])) / _x_step_m), 0, GRID_N - 1))
    _ri = int(np.clip(round((_ly - float(y_m[0])) / _y_step_m), 0, GRID_N - 1))
    _lz = float(elev_s[_ri, _ci]) + 3.0
    ax.scatter(
        [_lx], [_ly], [_lz], color="cyan", s=80, marker="D", zorder=14, label=_lt
    )
    ax.text(_lx, _ly, _lz + 1.0, _lt, color="cyan", fontsize=8, ha="center")

ax.set_xlabel("Istok-Zapad (m)", color="white", labelpad=8)
ax.set_ylabel("Sjever-Jug (m)", color="white", labelpad=8)
ax.set_zlabel("Visina (m)", color="white", labelpad=8)
ax.tick_params(colors="white")
ax.set_title(
    (
        f"3D Terrain Map  |  PATH 1 ({p1_dist[-1]:.0f}m) + PATH 2 ({p2_dist[-1]:.0f}m)\n"
        if not MANUAL_MODE
        else "3D Terrain Map  |  Manuelni pregled\n"
    )
    + f"{LAT_CENTER}N {LON_CENTER}E  |  Elev: {elev_s.min():.0f}–{elev_s.max():.0f}m",
    color="white",
    fontsize=12,
    pad=10,
)

sm = plt.cm.ScalarMappable(cmap="RdYlGn_r", norm=norm)
sm.set_array([])
cb = fig2.colorbar(sm, ax=ax, shrink=0.45, pad=0.08)
cb.set_label("Traversability Cost", color="white")
cb.ax.yaxis.set_tick_params(color="white")
plt.setp(plt.getp(cb.ax.axes, "yticklabels"), color="white")

# Satelitska slika kao inset
if sat_b64:
    sat_bytes = base64.b64decode(sat_b64)
    sat_arr = np.frombuffer(sat_bytes, dtype=np.uint8)
    sat_img = cv2.imdecode(sat_arr, cv2.IMREAD_COLOR)
    if sat_img is not None:
        sat_rgb = cv2.cvtColor(sat_img, cv2.COLOR_BGR2RGB)
        ax_inset = fig2.add_axes([0.01, 0.01, 0.22, 0.22])
        ax_inset.imshow(sat_rgb)
        ax_inset.set_title("Satelitska snimka", color="white", fontsize=8, pad=3)
        ax_inset.axis("off")

leg = ax.legend(
    loc="upper left",
    facecolor="#1a1a2e",
    edgecolor="white",
    labelcolor="white",
    fontsize=9,
)

ax.view_init(elev=28, azim=-55)
# tight_layout ne radi dobro s 3D subplot-om — koristimo savefig direktno
plt.savefig(OUT_PNG, dpi=150, bbox_inches="tight", facecolor="#08080e")
plt.close(fig2)
print(f"Statican PNG: {OUT_PNG}")

# ── 8. Trust DB (JSONL) ──────────────────────────────────────────────────────
if MANUAL_MODE:
    print("\nManuelni mode — trust_db.jsonl preskocen.")
    print("\nGotovo!")
    raise SystemExit(0)

import datetime as _dt

_trust_db_path = os.path.join(MAPS_DIR, "trust_db.jsonl")
print("\nGenerisem trust_db.jsonl...")

_p1_sid = os.path.basename(JSONL_PATH1).replace(".jsonl", "")
_p2_sid = os.path.basename(JSONL_PATH2).replace(".jsonl", "")

_sessions = [
    {
        "id": _p1_sid,
        "file": JSONL_PATH1,
        "trust_level": 1.0,
        "label": "PATH 1 – robot 100% provjereno",
        "n_points": len(p1_x),
    },
    {
        "id": _p2_sid,
        "file": JSONL_PATH2,
        "trust_level": 1.0,
        "label": "PATH 2 – robot 100% provjereno",
        "n_points": len(p2_x),
    },
]

# ── Ucitaj postojeci trust_db.jsonl radi deduplicacije ──────────────────────
_seg_index = {}  # seg_key → entry dict
_manual_zones = []  # sacuvaj rucne zone iz prethodnog fajla
_manual_block_keys = set()  # seg_key celija rucno potvrdjenih kao blokada (trust>=2)

if os.path.exists(_trust_db_path):
    with open(_trust_db_path, encoding="utf-8") as _ef:
        for _eln in _ef:
            _eln = _eln.strip()
            if not _eln:
                continue
            try:
                _eobj = json.loads(_eln)
            except Exception:
                continue
            if _eobj.get("type") == "meta":
                _manual_zones = _eobj.get("manual_zones", [])
                for _mz in _manual_zones:
                    if float(_mz.get("trust", 0)) >= 2.0:
                        _mk = (round(_mz["easting"]), round(_mz["northing"]))
                        _manual_block_keys.add(_mk)
            elif _eobj.get("type") == "point":
                _sk = (round(_eobj["easting"]), round(_eobj["northing"]))
                _seg_index[_sk] = _eobj


# ── Helper: da li je GPS tocka na blokiranom terenu (cost_map > 0.88)? ──────
def _is_risky_terrain(x_rel, y_rel):
    """Vraca True ako cost_map na toj lokaciji > 0.88 (crvena/blokirana zona)."""
    col = (
        (float(x_rel) - float(x_m[0])) / (float(x_m[-1]) - float(x_m[0])) * (GRID_N - 1)
    )
    row = (
        (float(y_rel) - float(y_m[0])) / (float(y_m[-1]) - float(y_m[0])) * (GRID_N - 1)
    )
    col_i = int(np.clip(round(col), 0, GRID_N - 1))
    row_i = int(np.clip(round(row), 0, GRID_N - 1))
    return float(cost_map[row_i, col_i]) > 0.88


# ── Izgradi/azuriraj indeks segmenata ────────────────────────────────────────
_risky_count = 0
_updated_count = 0
_new_count = 0

for _path_data in [
    (p1_x, p1_y, p1_z, p1_spd, p1_ts, _p1_sid),
    (p2_x, p2_y, p2_z, p2_spd, p2_ts, _p2_sid),
]:
    _xs, _ys, _alts, _spds, _tss, _sid = _path_data
    for _x, _y, _alt, _spd, _ts in zip(_xs, _ys, _alts, _spds, _tss):
        _e = round(float(_x) + UTM_E_CENTER, 3)
        _n = round(float(_y) + UTM_N_CENTER, 3)
        _sk = (round(_e), round(_n))
        _risky = _is_risky_terrain(_x, _y) and _sk not in _manual_block_keys
        _trust = 0.9 if _risky else 1.0
        if _risky:
            _risky_count += 1
        if _sk in _seg_index:
            # Segment vec postoji — samo azuriraj brzinu
            _seg_index[_sk]["speed_kmh"] = round(float(_spd), 2)
            _updated_count += 1
        else:
            _seg_index[_sk] = {
                "type": "point",
                "easting": _e,
                "northing": _n,
                "altitude": round(float(_alt), 2),
                "trust": _trust,
                "speed_kmh": round(float(_spd), 2),
                "risky": _risky,
                "session_id": _sid,
                "timestamp": _ts,
            }
            _new_count += 1

# ── Zapisi JSONL ─────────────────────────────────────────────────────────────
_meta_obj = {
    "type": "meta",
    "schema_version": 2,
    "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    "area": {
        "lat_center": round(LAT_CENTER, 7),
        "lon_center": round(LON_CENTER, 7),
        "utm_e_center": round(UTM_E_CENTER, 2),
        "utm_n_center": round(UTM_N_CENTER, 2),
        "utm_zone": "32N",
        "lat_span": LAT_SPAN,
        "lon_span": LON_SPAN,
    },
    "sessions": _sessions,
    "manual_zones": _manual_zones,
}

with open(_trust_db_path, "w", encoding="utf-8") as _f:
    _f.write(json.dumps(_meta_obj, ensure_ascii=False) + "\n")
    for _entry in _seg_index.values():
        _f.write(json.dumps(_entry, ensure_ascii=False) + "\n")

print(
    f"  trust_db.jsonl: {len(_seg_index)} jedinstvenih segmenata  "
    f"({_new_count} novih, {_updated_count} azuriranih, {_risky_count} riskantan prolaz (trust=0.9))"
)
print(f"  Lokacija: {_trust_db_path}")

print("\nGotovo!")
