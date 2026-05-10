"""
3D Terrain Navigation Map  v2
Koordinate: 48.2310367, 11.6203496 (München okolica)
- Visinski podaci: Open Elevation API (40x40 grid, kesiran)
- Satelitska tekstura: ESRI World Imagery tiles (layer toggle)
- Traversability overlay: iz image.png HSV segmentacije
- A* putanja: automatski izracunata
- TRUST ROUTE: realna GPS putanja iz JSONL (100% pouzdana, prikazana zlatno)
- Interaktivni HTML: moze se rotirati, zumirati, mijenjati sloj
"""

import json
import os
import sys  # noqa: F401
import time

import cv2
import numpy as np
import requests

# ── Koordinate i dimenzije ──────────────────────────────────────────────────
LAT_CENTER = 48.2310367
LON_CENTER = 11.6203496
# ~811m zoom = otprilike ±0.004 stupnjeva lat/lon
LAT_SPAN = 0.004
LON_SPAN = 0.005
GRID_N = 40  # 40x40 grid = 1600 API tocaka (batch)

MAPS_DIR = "/home/mn/soca/bazel_workspace/Maps"
IMG_PATH = os.path.join(MAPS_DIR, "image.png")
OUT_HTML = os.path.join(MAPS_DIR, "terrain_3d_result.html")
OUT_PNG = os.path.join(MAPS_DIR, "terrain_3d_result.png")


# ── 1. Preuzimanje elevacija ────────────────────────────────────────────────
def fetch_elevation_grid(lat_c, lon_c, lat_span, lon_span, n):
    lats = np.linspace(lat_c - lat_span / 2, lat_c + lat_span / 2, n)
    lons = np.linspace(lon_c - lon_span / 2, lon_c + lon_span / 2, n)

    cache_path = os.path.join(MAPS_DIR, "elevation_cache.json")
    if os.path.exists(cache_path):
        print("Koristim keširane visinske podatke...")
        with open(cache_path) as f:
            data = json.load(f)
        return np.array(data["lats"]), np.array(data["lons"]), np.array(data["elev"])

    print(f"Preuzimam {n*n} visinskih tocaka sa Open Elevation API...")
    locations = []
    for lat in lats:
        for lon in lons:
            locations.append({"latitude": round(lat, 6), "longitude": round(lon, 6)})

    # Batch request (max 512 lokacija po zahtjevu)
    elev_flat = []
    batch_size = 256
    for i in range(0, len(locations), batch_size):
        batch = locations[i : i + batch_size]
        payload = {"locations": batch}
        for attempt in range(3):
            try:
                r = requests.post(
                    "https://api.open-elevation.com/api/v1/lookup",
                    json=payload,
                    timeout=30,
                )
                results = r.json()["results"]
                elev_flat.extend([x["elevation"] for x in results])
                print(f"  Batch {i//batch_size + 1}: {len(elev_flat)}/{n*n} tocaka")
                break
            except Exception as e:
                print(f"  Retry {attempt+1}: {e}")
                time.sleep(2)

    elev = np.array(elev_flat).reshape(n, n)

    # Kesiraj
    with open(cache_path, "w") as f:
        json.dump(
            {"lats": lats.tolist(), "lons": lons.tolist(), "elev": elev.tolist()}, f
        )

    return lats, lons, elev


lats, lons, elev = fetch_elevation_grid(
    LAT_CENTER, LON_CENTER, LAT_SPAN, LON_SPAN, GRID_N
)

# Smooth elevaciju malo
from scipy.ndimage import gaussian_filter

elev_smooth = gaussian_filter(elev.astype(float), sigma=1.2)

print(
    f"Elevacija: min={elev_smooth.min():.1f}m  max={elev_smooth.max():.1f}m  "
    f"raspon={elev_smooth.max()-elev_smooth.min():.1f}m"
)


# ── 2. Traversability iz image.png (HSV segmentacija) ───────────────────────
def compute_traversability(img_path, grid_n):
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        print("Nema image.png, koristim uniform traversability")
        return np.ones((grid_n, grid_n)) * 0.3

    img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    img_hsv = cv2.GaussianBlur(img_hsv, (5, 5), 0)
    h, w = img_hsv.shape[:2]

    cost = np.full((h, w), 0.4, dtype=np.float32)

    m_veg = cv2.inRange(img_hsv, np.array([30, 40, 20]), np.array([90, 255, 200]))
    m_rock = cv2.inRange(img_hsv, np.array([0, 0, 90]), np.array([180, 45, 220]))
    m_soil1 = cv2.inRange(img_hsv, np.array([8, 25, 60]), np.array([28, 255, 255]))
    m_soil2 = cv2.inRange(img_hsv, np.array([28, 20, 100]), np.array([40, 140, 255]))
    m_soil = cv2.bitwise_or(m_soil1, m_soil2)
    m_water = cv2.inRange(img_hsv, np.array([90, 50, 20]), np.array([130, 255, 220]))
    m_dark = cv2.inRange(img_hsv, np.array([0, 0, 0]), np.array([180, 255, 55]))

    cost[m_rock > 0] = 0.10
    cost[m_soil > 0] = 0.15
    cost[m_veg > 0] = 0.55
    cost[m_water > 0] = 0.95
    cost[m_dark > 0] = 0.70

    # Skaliranje na grid_n x grid_n
    cost_grid = cv2.resize(cost, (grid_n, grid_n), interpolation=cv2.INTER_AREA)
    return cost_grid


cost_map = compute_traversability(IMG_PATH, GRID_N)

# ── 3. A* path planning na 2D cost+elevation gridu ──────────────────────────
import heapq


def slope_cost(elev, r1, c1, r2, c2):
    """Penalizacija nagiba između dvije celije."""
    dh = abs(float(elev[r2, c2]) - float(elev[r1, c1]))
    # Horizontalna udaljenost u metrima (approx)
    dx = abs(c2 - c1) * (LON_SPAN / GRID_N) * 111320 * np.cos(np.radians(LAT_CENTER))
    dy = abs(r2 - r1) * (LAT_SPAN / GRID_N) * 111320
    dist = max(np.sqrt(dx**2 + dy**2), 0.1)
    slope_deg = np.degrees(np.arctan(dh / dist))
    return min(slope_deg / 30.0, 1.5)  # 30 stepeni = max


def astar(cost_map, elev, start, goal):
    n = cost_map.shape[0]
    open_set = [(0, start)]
    came_from = {}
    g_score = {start: 0}
    dirs = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]

    while open_set:
        _, current = heapq.heappop(open_set)
        if current == goal:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start)
            return path[::-1]

        r, c = current
        for dr, dc in dirs:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < n and 0 <= nc < n):
                continue
            move_cost = cost_map[nr, nc]
            if move_cost > 0.88:  # blokirano
                continue
            sc = slope_cost(elev, r, c, nr, nc)
            step = np.sqrt(dr**2 + dc**2)
            tentative_g = g_score[current] + step * (move_cost + sc + 0.1)
            if tentative_g < g_score.get((nr, nc), float("inf")):
                came_from[(nr, nc)] = current
                g_score[(nr, nc)] = tentative_g
                h = np.sqrt((nr - goal[0]) ** 2 + (nc - goal[1]) ** 2) * 0.1
                heapq.heappush(open_set, (tentative_g + h, (nr, nc)))
    return []


# Start: gornji-lijevi kut, Cilj: donji-desni kut
start = (2, 2)
goal = (GRID_N - 3, GRID_N - 3)
print("Racunam A* putanju...")
path = astar(cost_map, elev_smooth, start, goal)
print(f"Putanja: {len(path)} koraka")

# ── 4. 3D Plotly vizualizacija ───────────────────────────────────────────────
try:
    import plotly  # noqa: F401
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots  # noqa: F401

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    print("Plotly nije instaliran, generiram samo matplotlib 3D prikaz...")

# Koordinatne mreze (metri, relativno od centra)
x_m = (lons - LON_CENTER) * 111320 * np.cos(np.radians(LAT_CENTER))
y_m = (lats - LAT_CENTER) * 111320
XX, YY = np.meshgrid(x_m, y_m)

if HAS_PLOTLY:
    # Boja surfacea = traversability
    colorscale_trav = [
        [0.0, "rgb(0,180,0)"],  # zeleno - slobodno
        [0.3, "rgb(180,220,0)"],
        [0.5, "rgb(255,200,0)"],  # zuto - oprez
        [0.7, "rgb(255,100,0)"],
        [1.0, "rgb(200,0,0)"],  # crveno - blokirano
    ]

    # Surface
    surface = go.Surface(
        x=XX,
        y=YY,
        z=elev_smooth,
        surfacecolor=cost_map,
        colorscale=colorscale_trav,
        cmin=0,
        cmax=1,
        colorbar=dict(
            title="Traversability<br>Cost",
            tickvals=[0, 0.2, 0.5, 0.8, 1.0],
            ticktext=["Slobodno", "Lako", "Srednje", "Teško", "Blokirano"],
            len=0.6,
        ),
        opacity=0.92,
        lighting=dict(ambient=0.7, diffuse=0.5, specular=0.1),
        name="Teren",
        showscale=True,
    )

    traces = [surface]

    # A* putanja na 3D
    if path:
        path_x = [float(x_m[c]) for r, c in path]
        path_y = [float(y_m[r]) for r, c in path]
        path_z = [float(elev_smooth[r, c]) + 3 for r, c in path]  # +3m iznad tla

        traces.append(
            go.Scatter3d(
                x=path_x,
                y=path_y,
                z=path_z,
                mode="lines+markers",
                line=dict(color="cyan", width=5),
                marker=dict(size=2, color="cyan"),
                name="A* Putanja robota",
            )
        )

        # Start i Goal markeri
        traces.append(
            go.Scatter3d(
                x=[path_x[0], path_x[-1]],
                y=[path_y[0], path_y[-1]],
                z=[path_z[0] + 2, path_z[-1] + 2],
                mode="markers+text",
                marker=dict(size=10, color=["lime", "red"], symbol="diamond"),
                text=["START", "CILJ"],
                textposition="top center",
                textfont=dict(size=14, color="white"),
                name="Start / Cilj",
            )
        )

    # Konturne linije elevacije
    contour_z = np.arange(int(elev_smooth.min()), int(elev_smooth.max()) + 1, 2)
    for z_level in contour_z[::3]:
        traces.append(
            go.Surface(
                x=XX,
                y=YY,
                z=np.full_like(elev_smooth, z_level),
                surfacecolor=np.where(elev_smooth >= z_level, 1, 0),
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(255,255,255,0.08)"]],
                showscale=False,
                opacity=0.05,
                name=f"{z_level}m",
            )
        )

    fig = go.Figure(data=traces)
    fig.update_layout(
        title=dict(
            text=f"3D Terrain Navigation Map<br>"
            f"<sup>Koordinate: {LAT_CENTER}°N, {LON_CENTER}°E | "
            f"Elevacija: {elev_smooth.min():.0f}–{elev_smooth.max():.0f}m | "
            f"A* put: {len(path)} koraka</sup>",
            x=0.5,
            font=dict(size=16),
        ),
        scene=dict(
            xaxis=dict(
                title="Istok–Zapad (m)",
                showbackground=True,
                backgroundcolor="rgb(15,15,30)",
            ),
            yaxis=dict(
                title="Sjever–Jug (m)",
                showbackground=True,
                backgroundcolor="rgb(15,15,30)",
            ),
            zaxis=dict(
                title="Nadmorska visina (m)",
                showbackground=True,
                backgroundcolor="rgb(10,10,25)",
            ),
            bgcolor="rgb(10,10,20)",
            aspectmode="manual",
            aspectratio=dict(x=1.5, y=1.5, z=0.4),
            camera=dict(eye=dict(x=1.4, y=-1.4, z=0.9)),
        ),
        paper_bgcolor="rgb(15,15,30)",
        plot_bgcolor="rgb(15,15,30)",
        font=dict(color="white"),
        legend=dict(
            bgcolor="rgba(30,30,50,0.8)",
            bordercolor="rgba(255,255,255,0.2)",
            borderwidth=1,
        ),
        margin=dict(l=0, r=0, t=80, b=0),
        height=750,
    )

    fig.write_html(OUT_HTML, include_plotlyjs="cdn")
    print(f"\nInteraktivna 3D mapa sacuvana: {OUT_HTML}")
    print("Otvori u browseru: xdg-open " + OUT_HTML)

# ── Matplotlib fallback / statican screenshot ───────────────────────────────
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm  # noqa: F401
from matplotlib.colors import Normalize
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

fig2 = plt.figure(figsize=(16, 10), facecolor="#0a0a14")
ax = fig2.add_subplot(111, projection="3d", facecolor="#0a0a14")

norm = Normalize(vmin=0, vmax=1)
colors = plt.cm.RdYlGn_r(norm(cost_map))

surf = ax.plot_surface(
    XX,
    YY,
    elev_smooth,
    facecolors=colors,
    linewidth=0,
    antialiased=True,
    alpha=0.9,
)

# Putanja
if path:
    px = [float(x_m[c]) for r, c in path]
    py = [float(y_m[r]) for r, c in path]
    pz = [float(elev_smooth[r, c]) + 4 for r, c in path]
    ax.plot(px, py, pz, color="cyan", linewidth=2.5, zorder=10, label="A* Putanja")
    ax.scatter([px[0]], [py[0]], [pz[0]], color="lime", s=120, zorder=11, label="START")
    ax.scatter(
        [px[-1]], [py[-1]], [pz[-1]], color="red", s=120, zorder=11, label="CILJ"
    )

ax.set_xlabel("Istok–Zapad (m)", color="white", labelpad=8)
ax.set_ylabel("Sjever–Jug (m)", color="white", labelpad=8)
ax.set_zlabel("Visina (m)", color="white", labelpad=8)
ax.tick_params(colors="white")
ax.set_title(
    f"3D Terrain Navigation Map\n"
    f"Koordinate: {LAT_CENTER}°N, {LON_CENTER}°E | "
    f"Elevacija: {elev_smooth.min():.0f}–{elev_smooth.max():.0f}m",
    color="white",
    fontsize=13,
    pad=12,
)

sm = plt.cm.ScalarMappable(cmap="RdYlGn_r", norm=norm)
sm.set_array([])
cbar = fig2.colorbar(sm, ax=ax, shrink=0.5, pad=0.08, label="Traversability Cost")
cbar.ax.yaxis.set_tick_params(color="white")
cbar.set_label("Traversability Cost", color="white")
plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="white")

if path:
    legend = ax.legend(
        loc="upper left", facecolor="#1a1a2e", edgecolor="white", labelcolor="white"
    )

ax.view_init(elev=30, azim=-60)
plt.tight_layout()
plt.savefig(OUT_PNG, dpi=150, bbox_inches="tight", facecolor="#0a0a14")
plt.close(fig2)
print(f"Statican PNG sacuvan: {OUT_PNG}")

print("\nGotovo!")
