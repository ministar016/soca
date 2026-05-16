"""
satellite.py — ESRI World Imagery tile fetching, caching and texture prep.

Public API
----------
fetch_tile() -> (surf_color, colorscale, b64_png) | (None, None, None)
    surf_color   — 2-D float array (GRID_N×GRID_N) for Plotly surfacecolor
    colorscale   — list of [value, 'rgb(R,G,B)'] entries
    b64_png      — base64-encoded PNG thumbnail for the HTML side-panel
"""

import base64
import os

import cv2
import numpy as np
import requests
from PIL import Image

from .config import GRID_N, LAT_CENTER, LAT_SPAN, LON_CENTER, LON_SPAN, MAPS_DIR

_CACHE_PNG = os.path.join(MAPS_DIR, "satellite_tile.png")
_META_PATH = os.path.join(MAPS_DIR, "satellite_meta.json")

import json

_META_CURR = {
    "lat": round(LAT_CENTER, 6),
    "lon": round(LON_CENTER, 6),
    "lat_span": LAT_SPAN,
    "lon_span": LON_SPAN,
}


def _invalidate_if_stale() -> None:
    """Remove cached satellite tile if map bounds changed."""
    if os.path.exists(_META_PATH):
        with open(_META_PATH) as fh:
            old = json.load(fh)
        if old != _META_CURR:
            print("  Satellite cache stale — deleting...")
            if os.path.exists(_CACHE_PNG):
                os.remove(_CACHE_PNG)
    with open(_META_PATH, "w") as fh:
        json.dump(_META_CURR, fh)


def fetch_tile() -> tuple:
    """
    Download (or load cached) ESRI satellite tile.

    Returns (surf_color, colorscale, b64_png) or (None, None, None).
    """
    _invalidate_if_stale()

    lat_min = LAT_CENTER - LAT_SPAN / 2
    lat_max = LAT_CENTER + LAT_SPAN / 2
    lon_min = LON_CENTER - LON_SPAN / 2
    lon_max = LON_CENTER + LON_SPAN / 2

    if not os.path.exists(_CACHE_PNG):
        print("Fetching satellite tile (ESRI World Imagery 1024 px)...")
        url = (
            "https://services.arcgisonline.com/arcgis/rest/services/"
            "World_Imagery/MapServer/export"
            f"?bbox={lon_min},{lat_min},{lon_max},{lat_max}"
            "&bboxSR=4326&imageSR=4326&size=1024,1024&format=png&f=image"
        )
        try:
            r = requests.get(url, timeout=40)
            if r.status_code == 200 and len(r.content) > 10_000:
                with open(_CACHE_PNG, "wb") as fh:
                    fh.write(r.content)
                print(f"  Tile saved ({len(r.content) // 1024} KB)")
            else:
                print(f"  ESRI error {r.status_code} ({len(r.content)} B)")
        except Exception as exc:
            print(f"  ESRI error: {exc}")

    if not os.path.exists(_CACHE_PNG):
        print("  No satellite tile — skipping.")
        return None, None, None

    img_bgr = cv2.imread(_CACHE_PNG)
    if img_bgr is None:
        return None, None, None

    # ESRI delivers rows north→south; our y linspace is south→north — flip.
    img_rgb = np.flipud(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    img_sm = cv2.resize(img_rgb, (GRID_N, GRID_N), interpolation=cv2.INTER_AREA)

    # Quantise to ≤256 colours — keeps colorscale small and HTML fast.
    pil_img = Image.fromarray(img_sm).quantize(
        colors=256, method=Image.Quantize.MEDIANCUT
    )
    idx_img = np.array(pil_img)
    n_colors = int(idx_img.max()) + 1
    surf_color = idx_img.astype(float) / max(n_colors - 1, 1)

    palette = np.array(pil_img.getpalette()).reshape(-1, 3)[:n_colors]
    colorscale = [
        [
            round(i / max(n_colors - 1, 1), 6),
            f"rgb({palette[i,0]},{palette[i,1]},{palette[i,2]})",
        ]
        for i in range(n_colors)
    ]

    with open(_CACHE_PNG, "rb") as fh:
        b64_png = base64.b64encode(fh.read()).decode()

    print(f"  Satellite texture ready ({GRID_N}×{GRID_N}, {n_colors} colours)")
    return surf_color, colorscale, b64_png
