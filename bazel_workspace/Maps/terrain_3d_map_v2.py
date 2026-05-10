"""3D Terrain Navigation Map  v3
Koordinate: 48.2295, 11.6219 (München okolica, prosirena mapa)
- Visinski podaci: OpenTopography Copernicus DEM 30m (COP30, kesiran)
- Layer 1: Traversability overlay (HSV segmentacija image.png)
- Layer 2: Satelitska tekstura (ESRI World Imagery)
- A* putanja: automatski izracunata (cyan)
- TRUST ROUTE:  zlatna  — 10.9.0.50_2026-05-08_12-10-46 (168m, potvrdjena)
- KNOWN ROUTE:  ljubicasta — 10.9.0.50_2026-05-08_09-51-50 (850m, ispitana)
- Interaktivni HTML: layer toggle, rotacija, zoom, hover
"""

import base64
import heapq
import json
import os
import time

import cv2
import numpy as np
import requests

MAPS_DIR = "/home/mn/soca/bazel_workspace/Maps"
IMG_PATH = os.path.join(MAPS_DIR, "image.png")
JSONL_TRUST = os.path.join(MAPS_DIR, "10.9.0.50_2026-05-08_12-10-46_UTC.jsonl")
JSONL_KNOWN = os.path.join(MAPS_DIR, "10.9.0.50_2026-05-08_09-51-50_UTC.jsonl")
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

# Prosireni bounds koji pokrivaju obje rute
# Ruta 1: 16m x 34m oko E0/N0
# Ruta 2: 254m x 382m, ide daleko na jug i istok
# Novi centar pomjeren da pokrije obje
LAT_CENTER = 48.2295  # pomjereno ~170m juznije
LON_CENTER = 11.6219  # pomjereno ~115m istocnije
LAT_SPAN = 0.0065  # ~720m sjever-jug
LON_SPAN = 0.0065  # ~480m istok-zapad
GRID_N = 60  # veci grid za bolju rezoluciju

# UTM zona 32N referentna tocka (odgovara originalnom LAT/LON centru 48.2310367, 11.6203496)
UTM_E0 = 694498.92
UTM_N0 = 5345502.56


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
                xs.append(p["easting"] - UTM_E0)
                ys.append(p["northing"] - UTM_N0)
            except Exception:
                continue
    return np.array(alts), np.array(xs), np.array(ys)


gps_alt_t, gps_x_t, gps_y_t = _read_gps_alt(JSONL_TRUST)
gps_alt_k, gps_x_k, gps_y_k = _read_gps_alt(JSONL_KNOWN)
all_gps_alt = np.concatenate([gps_alt_t, gps_alt_k])
all_gps_x = np.concatenate([gps_x_t, gps_x_k])
all_gps_y = np.concatenate([gps_y_t, gps_y_k])

dem_at_gps = _dem_at_xy(all_gps_x, all_gps_y)
DEM_OFFSET = float(np.median(all_gps_alt) - np.median(dem_at_gps))
elev_s = elev_s + DEM_OFFSET  # kalibriran DEM
print(
    f"DEM kalibracija: offset={DEM_OFFSET:+.1f}m  "
    f"(DEM median={np.median(dem_at_gps)-DEM_OFFSET:.1f}m → GPS median={np.median(all_gps_alt):.1f}m)"
)
print(f"Elevacija (kalibrirano): {elev_s.min():.1f}-{elev_s.max():.1f}m")

# UGV telemetrija: antena je ~0.5m iznad tla, vizualni offset 1.5m
GPS_HEIGHT = 0.5  # m — visina UGV antene iznad tla
ROUTE_Z_OFFSET = 0.0  # m — ruta je tacno GPS_HEIGHT iznad terena (0.5m)


def snap_to_terrain(xs, ys):
    """Interpolira kalibriranu visinu terena i vraca z = teren + GPS_HEIGHT."""
    terrain_z = _dem_at_xy(xs, ys)
    return (terrain_z + GPS_HEIGHT + ROUTE_Z_OFFSET).tolist()


# ── 2. Traversability mapa ───────────────────────────────────────────────────
def compute_traversability(img_path):
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        return np.full((GRID_N, GRID_N), 0.3, dtype=np.float32)
    hsv = cv2.GaussianBlur(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV), (5, 5), 0)
    h, w = hsv.shape[:2]
    cost = np.full((h, w), 0.4, dtype=np.float32)
    cost[cv2.inRange(hsv, (0, 0, 90), (180, 45, 220)) > 0] = 0.10  # kamen
    cost[cv2.inRange(hsv, (8, 25, 60), (28, 255, 255)) > 0] = 0.15  # zemlja
    cost[cv2.inRange(hsv, (28, 20, 100), (40, 140, 255)) > 0] = 0.15
    cost[cv2.inRange(hsv, (30, 40, 20), (90, 255, 200)) > 0] = 0.55  # vegetacija
    cost[cv2.inRange(hsv, (90, 50, 20), (130, 255, 220)) > 0] = 0.95  # voda
    cost[cv2.inRange(hsv, (0, 0, 0), (180, 255, 55)) > 0] = 0.70  # tamno
    return cv2.resize(cost, (GRID_N, GRID_N), interpolation=cv2.INTER_AREA)


cost_map = compute_traversability(IMG_PATH)


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

    # UTM → metri relativno od centra mape
    route_x = [(r["e"] - UTM_E0) for r in rows]  # istok pozitivno
    route_y = [(r["n"] - UTM_N0) for r in rows]  # sjever pozitivno
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


route_x, route_y, route_z, route_spd, route_dist, route_ts = load_trust_route(
    JSONL_TRUST
)

# Downsample trust rute
STEP = 5
rx = route_x[::STEP]
ry = route_y[::STEP]
# Snapujemo na teren umjesto GPS altitude (izbjegava WGS84-vs-DEM razliku)
rz = snap_to_terrain(rx, ry)
rs = route_spd[::STEP]
rd = route_dist[::STEP]
rt = route_ts[::STEP]

# ── Known Route (09-51-50) ───────────────────────────────────────────────────
print("")
kroute_x, kroute_y, kroute_z, kroute_spd, kroute_dist, kroute_ts = load_trust_route(
    JSONL_KNOWN
)
KSTEP = 8  # veca ruta, veci korak
krx = kroute_x[::KSTEP]
kry = kroute_y[::KSTEP]
# Snapujemo na teren — UGV ruta ne prolazi kroz zemlju
krz = snap_to_terrain(krx, kry)
krs = kroute_spd[::KSTEP]
krd = kroute_dist[::KSTEP]
krt = kroute_ts[::KSTEP]


# ── 5. A* path planning ──────────────────────────────────────────────────────
def astar(cost_map, elev, start, goal):
    n = cost_map.shape[0]
    open_set = [(0.0, start)]
    came_from = {}
    g = {start: 0.0}
    dirs = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    while open_set:
        _, cur = heapq.heappop(open_set)
        if cur == goal:
            path = []
            while cur in came_from:
                path.append(cur)
                cur = came_from[cur]
            return [start] + path[::-1]
        r, c = cur
        for dr, dc in dirs:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < n and 0 <= nc < n):
                continue
            if cost_map[nr, nc] > 0.88:
                continue
            dh = abs(float(elev[nr, nc]) - float(elev[r, c]))
            dxy = max(
                np.sqrt(
                    (dr * (LAT_SPAN / GRID_N) * 111320) ** 2
                    + (
                        dc
                        * (LON_SPAN / GRID_N)
                        * 111320
                        * np.cos(np.radians(LAT_CENTER))
                    )
                    ** 2
                ),
                0.1,
            )
            sc = min(np.degrees(np.arctan(dh / dxy)) / 30.0, 1.5)
            ng = g[cur] + np.sqrt(dr**2 + dc**2) * (cost_map[nr, nc] + sc + 0.1)
            if ng < g.get((nr, nc), 1e18):
                came_from[(nr, nc)] = cur
                g[(nr, nc)] = ng
                heapq.heappush(
                    open_set,
                    (
                        ng + np.sqrt((nr - goal[0]) ** 2 + (nc - goal[1]) ** 2) * 0.1,
                        (nr, nc),
                    ),
                )
    return []


print("Racunam A* putanju...")
path = astar(cost_map, elev_s, (2, 2), (GRID_N - 3, GRID_N - 3))
print(f"A* putanja: {len(path)} koraka")

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

traces = [surf_trav, surf_sat]

# ─ A* putanja ─
if path:
    px = [float(x_m[c]) for r, c in path]
    py = [float(y_m[r]) for r, c in path]
    pz = [float(elev_s[r, c]) + 3 for r, c in path]
    traces.append(
        go.Scatter3d(
            x=px,
            y=py,
            z=pz,
            mode="lines",
            line=dict(color="cyan", width=4),
            name="A* Putanja (planer)",
            hoverinfo="skip",
        )
    )
    traces.append(
        go.Scatter3d(
            x=[px[0], px[-1]],
            y=[py[0], py[-1]],
            z=[pz[0] + 1, pz[-1] + 1],
            mode="markers+text",
            marker=dict(size=9, color=["lime", "red"], symbol="diamond"),
            text=["A* START", "A* CILJ"],
            textposition="top center",
            textfont=dict(size=11, color="white"),
            name="A* Start/Cilj",
            hoverinfo="text",
        )
    )

# ─ TRUST ROUTE (GPS iz JSONL) ─
hover_trust = [
    f"<b>TRUST ROUTE</b><br>"
    f"Dist: {rd[i]:.1f}m<br>"
    f"Alt: {route_z[::STEP][i]:.2f}m<br>"
    f"Brzina: {rs[i]:.1f}km/h<br>"
    f"Vrijeme: {rt[i][:19].replace('T',' ')}"
    for i in range(len(rx))
]
traces.append(
    go.Scatter3d(
        x=rx,
        y=ry,
        z=rz,
        mode="lines+markers",
        line=dict(color="gold", width=6),
        marker=dict(
            size=3,
            color=route_dist[::STEP],
            colorscale="YlOrRd",
            showscale=False,
        ),
        name="TRUST ROUTE (GPS realizovana, 100%)",
        hovertext=hover_trust,
        hoverinfo="text",
    )
)

# Markeri start/kraj trust route
traces.append(
    go.Scatter3d(
        x=[rx[0], rx[-1]],
        y=[ry[0], ry[-1]],
        z=[rz[0] + 1.5, rz[-1] + 1.5],
        mode="markers+text",
        marker=dict(
            size=12,
            color=["gold", "orange"],
            symbol="circle",
            line=dict(color="white", width=2),
        ),
        text=["ROBOT START", "ROBOT KRAJ"],
        textposition=["top center", "top center"],
        textfont=dict(size=12, color="gold"),
        name="Robot Start/Kraj",
        hoverinfo="text",
    )
)

# ─ KNOWN ROUTE (GPS iz 09-51-50 JSONL) ─
hover_known = [
    f"<b>KNOWN ROUTE</b><br>"
    f"Dist: {krd[i]:.1f}m<br>"
    f"Alt: {kroute_z[::KSTEP][i]:.2f}m<br>"
    f"Brzina: {krs[i]:.1f}km/h<br>"
    f"Vrijeme: {krt[i][:19].replace('T',' ')}"
    for i in range(len(krx))
]
traces.append(
    go.Scatter3d(
        x=krx,
        y=kry,
        z=krz,
        mode="lines+markers",
        line=dict(color="mediumpurple", width=6),
        marker=dict(
            size=3,
            color=kroute_dist[::KSTEP],
            colorscale="Purples",
            showscale=False,
        ),
        name="KNOWN ROUTE (ispitana, 850m)",
        hovertext=hover_known,
        hoverinfo="text",
    )
)
# Markeri start/kraj known route
traces.append(
    go.Scatter3d(
        x=[krx[0], krx[-1]],
        y=[kry[0], kry[-1]],
        z=[krz[0] + 1.5, krz[-1] + 1.5],
        mode="markers+text",
        marker=dict(
            size=12,
            color=["mediumpurple", "violet"],
            symbol="square",
            line=dict(color="white", width=2),
        ),
        text=["KNOWN START", "KNOWN KRAJ"],
        textposition=["top center", "top center"],
        textfont=dict(size=12, color="mediumpurple"),
        name="Known Start/Kraj",
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
                        {"visible": [False, True, True, True, True, True, True, True]}
                    ],
                ),
                dict(
                    label="Hybrid",
                    method="update",
                    args=[
                        {
                            "visible": [True, True, True, True, True, True, True, True],
                            "opacity": [0.55, 0.80, 1, 1, 1, 1, 1, 1],
                        }
                    ],
                ),
                dict(
                    label="Topografija",
                    method="update",
                    args=[
                        {"visible": [True, False, True, True, True, True, True, True]}
                    ],
                ),
            ],
        )
    ],
    title=dict(
        text=(
            f"3D Terrain Navigation Map  |  {LAT_CENTER}N, {LON_CENTER}E<br>"
            f"<sup>"
            f"Zlato = TRUST ROUTE ({route_dist[-1]:.0f}m, 100% pouzdana)  |  "
            f"Ljubicasta = KNOWN ROUTE ({kroute_dist[-1]:.0f}m, ispitana)  |  "
            f"Cyan = A* planer  |  Layer toggle gore lijevo"
            f"</sup>"
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

# Satelitsku sliku dodaj kao pozadinsku sliku (2D layout image u donjem lijevom uglu)
if sat_b64:
    lat_min = LAT_CENTER - LAT_SPAN / 2
    lat_max = LAT_CENTER + LAT_SPAN / 2
    lon_min = LON_CENTER - LON_SPAN / 2
    lon_max = LON_CENTER + LON_SPAN / 2
    x_min_m = (lon_min - LON_CENTER) * 111320 * np.cos(np.radians(LAT_CENTER))
    x_max_m = (lon_max - LON_CENTER) * 111320 * np.cos(np.radians(LAT_CENTER))
    y_min_m = (lat_min - LAT_CENTER) * 111320
    y_max_m = (lat_max - LAT_CENTER) * 111320
    fig.add_layout_image(
        dict(
            source=f"data:image/png;base64,{sat_b64}",
            xref="paper",
            yref="paper",
            x=0.72,
            y=0.28,
            sizex=0.26,
            sizey=0.26,
            xanchor="left",
            yanchor="bottom",
            opacity=0.92,
            layer="above",
        )
    )
    # Anotacija za thumbnail
    fig.add_annotation(
        x=0.72,
        y=0.28,
        xref="paper",
        yref="paper",
        text="Satelitska snimka (thumbnail)",
        showarrow=False,
        font=dict(size=9, color="rgba(200,200,200,0.8)"),
        bgcolor="rgba(10,10,30,0.6)",
        xanchor="left",
        yanchor="top",
    )

fig.write_html(OUT_HTML, include_plotlyjs="cdn")
print(f"\nInteraktivna 3D mapa: {OUT_HTML}")

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

# A* putanja
if path:
    px2 = [float(x_m[c]) for r, c in path]
    py2 = [float(y_m[r]) for r, c in path]
    pz2 = [float(elev_s[r, c]) + 3 for r, c in path]
    ax.plot(px2, py2, pz2, color="cyan", lw=2, zorder=10, label="A* Putanja")
    ax.scatter([px2[0]], [py2[0]], [pz2[0]], color="lime", s=80, zorder=11)
    ax.scatter([px2[-1]], [py2[-1]], [pz2[-1]], color="red", s=80, zorder=11)

# TRUST ROUTE
sc_colors = plt.cm.YlOrRd(np.linspace(0, 1, len(rx)))
for i in range(len(rx) - 1):
    ax.plot(
        [rx[i], rx[i + 1]],
        [ry[i], ry[i + 1]],
        [rz[i], rz[i + 1]],
        color="gold",
        lw=2.5,
        zorder=12,
    )
ax.scatter(
    [rx[0]],
    [ry[0]],
    [rz[0] + 1],
    color="gold",
    s=120,
    marker="D",
    zorder=13,
    label="Robot START",
)
ax.scatter(
    [rx[-1]],
    [ry[-1]],
    [rz[-1] + 1],
    color="orange",
    s=120,
    marker="D",
    zorder=13,
    label="Robot KRAJ",
)

# KNOWN ROUTE
if len(krx) > 0:
    for i in range(len(krx) - 1):
        ax.plot(
            [krx[i], krx[i + 1]],
            [kry[i], kry[i + 1]],
            [krz[i], krz[i + 1]],
            color="mediumpurple",
            lw=2.0,
            zorder=11,
        )
    ax.scatter(
        [krx[0]],
        [kry[0]],
        [krz[0] + 1],
        color="mediumpurple",
        s=120,
        marker="s",
        zorder=13,
        label="Known START",
    )
    ax.scatter(
        [krx[-1]],
        [kry[-1]],
        [krz[-1] + 1],
        color="violet",
        s=120,
        marker="s",
        zorder=13,
        label="Known KRAJ",
    )

ax.set_xlabel("Istok-Zapad (m)", color="white", labelpad=8)
ax.set_ylabel("Sjever-Jug (m)", color="white", labelpad=8)
ax.set_zlabel("Visina (m)", color="white", labelpad=8)
ax.tick_params(colors="white")
ax.set_title(
    f"3D Terrain Map  |  Trust ({route_dist[-1]:.0f}m) + Known ({kroute_dist[-1]:.0f}m)  |  A*\n"
    f"{LAT_CENTER}N {LON_CENTER}E  |  Elev: {elev_s.min():.0f}–{elev_s.max():.0f}m",
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
plt.tight_layout()
plt.savefig(OUT_PNG, dpi=150, bbox_inches="tight", facecolor="#08080e")
plt.close(fig2)
print(f"Statican PNG: {OUT_PNG}")
print("\nGotovo!")
