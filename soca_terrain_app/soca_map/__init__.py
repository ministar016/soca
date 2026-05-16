# soca_map — SOCA terrain navigation map package

from .config import (
    GPS_HEIGHT,
    GRID_N,
    IMG_PATH,
    JSONL_PATH1,
    JSONL_PATH2,
    LAT_CENTER,
    LAT_SPAN,
    LON_CENTER,
    LON_SPAN,
    MAPS_DIR,
    OT_API_KEY,
    OUT_HTML,
    OUT_PNG,
    TRUST_DB_PATH,
    UTM_E_CENTER,
    UTM_N_CENTER,
    utm32n_to_latlon,
)
from .gps import (
    RouteData,
    compute_traversability,
    compute_trust_map,
    load_route,
    make_trust_overlay_b64,
)
from .routing import update_and_save
from .satellite import fetch_tile
from .segmentation import process_all, segment_image
from .terrain import build_grid, snap_to_terrain

__all__ = [
    # config
    "MAPS_DIR",
    "JSONL_PATH1",
    "JSONL_PATH2",
    "IMG_PATH",
    "OUT_HTML",
    "OUT_PNG",
    "TRUST_DB_PATH",
    "GRID_N",
    "GPS_HEIGHT",
    "OT_API_KEY",
    "LAT_CENTER",
    "LON_CENTER",
    "LAT_SPAN",
    "LON_SPAN",
    "UTM_E_CENTER",
    "UTM_N_CENTER",
    "utm32n_to_latlon",
    # gps
    "RouteData",
    "load_route",
    "compute_traversability",
    "compute_trust_map",
    "make_trust_overlay_b64",
    # terrain
    "build_grid",
    "snap_to_terrain",
    # satellite
    "fetch_tile",
    # segmentation
    "segment_image",
    "process_all",
    # routing
    "update_and_save",
]
