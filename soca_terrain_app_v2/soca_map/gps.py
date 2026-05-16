"""
gps.py — JSONL route loading, traversability + trust map, trust overlay.

Public API
----------
load_route(jsonl_path) -> RouteData
    Load a single JSONL GPS route.

compute_traversability(img_path) -> np.ndarray
    HSV-based cost map (0=free … 1=blocked) from terrain image.

compute_trust_map(cost_map, route_specs) -> np.ndarray
    Semantic trust grid merging cost map + robot traversal evidence.

make_trust_overlay_b64(trust_map) -> str
    RGBA PNG base64 for the 2-D satellite panel overlay.
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from scipy.ndimage import label as nd_label

from .config import GRID_N, UTM_E_CENTER, UTM_N_CENTER

# ── Data container ────────────────────────────────────────────────────────────


@dataclass
class RouteData:
    """All data for one GPS route."""

    x: list[float]  # metres east of map centre
    y: list[float]  # metres north of map centre
    z: list[float]  # GPS altitude (m)
    spd: list[float]  # vehicle speed (km/h)
    dist: list[float]  # cumulative distance (m)
    ts: list[str]  # ISO timestamp strings
    name: str = ""
    _jsonl_path: str = field(default="", repr=False)

    # Downsampled views (set after snap_to_terrain)
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)
    zs: list[float] = field(default_factory=list)  # terrain-snapped
    spds: list[float] = field(default_factory=list)
    dists: list[float] = field(default_factory=list)
    tss: list[str] = field(default_factory=list)

    @property
    def total_dist(self) -> float:
        return self.dist[-1] if self.dist else 0.0


# ── Route loading ─────────────────────────────────────────────────────────────


def load_route(jsonl_path: str) -> RouteData:
    """Load GPS route from JSONL.  UTM → metres relative to map centre."""
    print(f"Loading GPS route from {os.path.basename(jsonl_path)}...")
    rows = []
    with open(jsonl_path) as fh:
        for line in fh:
            try:
                p = json.loads(line.strip())["payload"]
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

    x = [(r["e"] - UTM_E_CENTER) for r in rows]
    y = [(r["n"] - UTM_N_CENTER) for r in rows]
    z = [r["alt"] for r in rows]
    spd = [r["spd"] for r in rows]
    dist = [r["dist"] for r in rows]
    ts = [r["ts"] for r in rows]

    print(
        f"  {len(rows)} points | "
        f"X: {min(x):.1f}–{max(x):.1f} m | "
        f"Y: {min(y):.1f}–{max(y):.1f} m | "
        f"Total: {dist[-1]:.1f} m"
    )
    name = os.path.splitext(os.path.basename(jsonl_path))[0]
    return RouteData(
        x=x, y=y, z=z, spd=spd, dist=dist, ts=ts, name=name, _jsonl_path=jsonl_path
    )


# ── Traversability cost map ───────────────────────────────────────────────────


def compute_traversability(img_path: str) -> np.ndarray:
    """
    HSV-based traversability cost map from a terrain overview image.

    Returns GRID_N×GRID_N float32 array (0 = free, 1 = blocked).
    Falls back to a uniform 0.3 grid if the image cannot be read.
    """
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        return np.full((GRID_N, GRID_N), 0.3, dtype=np.float32)

    hsv = cv2.GaussianBlur(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV), (5, 5), 0)
    h, w = hsv.shape[:2]
    cost = np.full((h, w), 0.4, dtype=np.float32)

    cost[cv2.inRange(hsv, (0, 0, 90), (180, 45, 220)) > 0] = 0.10  # rock / path
    cost[cv2.inRange(hsv, (8, 25, 60), (28, 255, 255)) > 0] = 0.15  # bare earth
    cost[cv2.inRange(hsv, (28, 20, 100), (40, 140, 255)) > 0] = 0.15  # yellow-brown
    cost[cv2.inRange(hsv, (30, 40, 20), (90, 255, 200)) > 0] = 0.55  # vegetation
    cost[cv2.inRange(hsv, (90, 50, 20), (130, 255, 220)) > 0] = 0.95  # water
    cost[cv2.inRange(hsv, (0, 0, 0), (180, 255, 55)) > 0] = 0.70  # dark / shadow

    return cv2.resize(cost, (GRID_N, GRID_N), interpolation=cv2.INTER_AREA)


# ── Trust map ─────────────────────────────────────────────────────────────────


def compute_trust_map(
    cost_map: np.ndarray,
    route_specs: list[dict],
    x_m: np.ndarray,
    y_m: np.ndarray,
) -> np.ndarray:
    """
    Build a GRID_N×GRID_N trust grid.

    route_specs: list of {'xs': [...], 'ys': [...], 'trust': float}
      trust = 1.00  UGV confirmed passable
      trust = 0.70  surveyed from map, not driven

    Base levels (from cost_map):
      0.00  water / absolute blockage   (cost > 0.88)
      0.30  isolated road fragment      (cost < 0.17, small component)
      0.50  vegetation / dense terrain  (cost 0.45 – 0.88)
      0.70  open ground                 (cost < 0.45)
    """
    trust = np.full((GRID_N, GRID_N), 0.70, dtype=float)

    veg_mask = (cost_map >= 0.45) & (cost_map <= 0.88)
    water_mask = cost_map > 0.88
    trust[veg_mask] = 0.50
    trust[water_mask] = 0.00

    # Isolated road fragments → 30%
    road_mask = cost_map < 0.17
    labeled, n_comp = nd_label(road_mask)
    for cid in range(1, n_comp + 1):
        if (labeled == cid).sum() < 5:
            trust[labeled == cid] = 0.30

    # GPS routes — raise trust in a ±1 cell buffer around each point (~4m cell → ~12m corridor)
    robot_mask = np.zeros((GRID_N, GRID_N), dtype=bool)
    for spec in route_specs:
        t_level = float(spec["trust"])
        for xi, yi in zip(spec["xs"], spec["ys"]):
            col_f = (
                (float(xi) - float(x_m[0]))
                / (float(x_m[-1]) - float(x_m[0]))
                * (GRID_N - 1)
            )
            row_f = (
                (float(yi) - float(y_m[0]))
                / (float(y_m[-1]) - float(y_m[0]))
                * (GRID_N - 1)
            )
            ci = int(np.clip(round(col_f), 0, GRID_N - 1))
            ri = int(np.clip(round(row_f), 0, GRID_N - 1))
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    nr, nc = ri + dr, ci + dc
                    if 0 <= nr < GRID_N and 0 <= nc < GRID_N:
                        robot_mask[nr, nc] = True
                        if t_level > trust[nr, nc]:
                            trust[nr, nc] = t_level

    trust = gaussian_filter(trust, sigma=0.5)

    # Robot passed through a red zone → risky (0.9), not a hard block
    trust[water_mask & robot_mask] = 0.90
    trust[water_mask & ~robot_mask] = 0.00

    return np.clip(trust, 0.0, 1.0)


# ── Trust overlay PNG ─────────────────────────────────────────────────────────

# Colour stops matching colorscale_trust in visualize.py
_STOPS_V = np.array([0.00, 0.30, 0.50, 0.70, 0.90, 1.00])
_STOPS_C = np.array(
    [
        [139, 0, 0, 195],  # blockage
        [255, 90, 90, 160],  # broken path
        [230, 160, 0, 145],  # vegetation / amber
        [40, 200, 80, 55],  # open ground — low alpha (mostly passable)
        [0, 191, 255, 185],  # sky-blue — robot, risky
        [30, 144, 255, 210],  # blue — trusted
    ],
    dtype=float,
)


def make_trust_overlay_b64(trust_map: np.ndarray) -> str:
    """Convert trust_map to a base64 RGBA PNG for the 2-D HTML panel."""
    flat = trust_map.ravel()
    out = np.zeros((flat.size, 4), dtype=np.uint8)

    for i in range(len(_STOPS_V) - 1):
        v0, v1 = _STOPS_V[i], _STOPS_V[i + 1]
        last = i == len(_STOPS_V) - 2
        mask = (flat >= v0) & (flat <= v1 + (0.001 if last else 0))
        if not mask.any():
            continue
        t = (flat[mask] - v0) / (v1 - v0 + 1e-9)
        out[mask] = np.clip(
            _STOPS_C[i] + t[:, None] * (_STOPS_C[i + 1] - _STOPS_C[i]), 0, 255
        ).astype(np.uint8)

    h, w = trust_map.shape
    img = Image.fromarray(out.reshape(h, w, 4), "RGBA")
    img = img.resize((300, 300), Image.BILINEAR)
    img = img.transpose(Image.FLIP_TOP_BOTTOM)  # row 0 = south → north up
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
