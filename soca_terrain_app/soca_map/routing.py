"""
routing.py — trust-database JSONL export.

The trust_db.jsonl file is the map export that can be loaded by the vehicle
for autonomous navigation decisions.

Schema (schema_version 2)
--------------------------
Line 1  (meta):   {"type":"meta", "schema_version":2, "generated_at":...,
                    "area":{...}, "sessions":[...], "manual_zones":[]}
Other lines:      {"type":"point", "easting":..., "northing":...,
                    "altitude":..., "trust":..., "speed_kmh":...,
                    "risky":bool, "session_id":..., "timestamp":...}

Trust values
------------
1.0  — UGV confirmed passable (cost_map ≤ 0.88)
0.9  — UGV passed through red zone (risky, not manually blocked)
2.0  — manually confirmed blockage (manual_zones only, never from GPS)

Deduplication key: (round(easting), round(northing)) — 1 m grid cell.
On re-run only speed_kmh is updated for existing segments.

Public API
----------
update_and_save(routes, cost_map, x_m, y_m) -> None
"""

from __future__ import annotations

import datetime
import json
import os

import numpy as np

from .config import (
    GRID_N,
    LAT_CENTER,
    LAT_SPAN,
    LON_CENTER,
    LON_SPAN,
    TRUST_DB_PATH,
    UTM_E_CENTER,
    UTM_N_CENTER,
)
from .gps import RouteData


def _is_risky(
    x_rel: float, y_rel: float, cost_map: np.ndarray, x_m: np.ndarray, y_m: np.ndarray
) -> bool:
    """Return True when the GPS point falls on cost_map > 0.88 (red zone)."""
    col = (
        (float(x_rel) - float(x_m[0])) / (float(x_m[-1]) - float(x_m[0])) * (GRID_N - 1)
    )
    row = (
        (float(y_rel) - float(y_m[0])) / (float(y_m[-1]) - float(y_m[0])) * (GRID_N - 1)
    )
    col_i = int(np.clip(round(col), 0, GRID_N - 1))
    row_i = int(np.clip(round(row), 0, GRID_N - 1))
    return float(cost_map[row_i, col_i]) > 0.88


def update_and_save(
    routes: list[RouteData],
    cost_map: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
) -> None:
    """
    Merge GPS routes into trust_db.jsonl.

    Existing entries are kept; speed_kmh is updated on re-run.
    manual_zones (trust ≥ 2.0) are preserved from the previous file.
    """
    print("\nGenerating trust_db.jsonl...")

    # ── Load existing DB ──────────────────────────────────────────────────────
    seg_index: dict[tuple, dict] = {}  # (E_rounded, N_rounded) → entry
    manual_zones: list[dict] = []
    manual_block_keys: set[tuple] = set()

    if os.path.exists(TRUST_DB_PATH):
        with open(TRUST_DB_PATH, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if obj.get("type") == "meta":
                    manual_zones = obj.get("manual_zones", [])
                    for mz in manual_zones:
                        if float(mz.get("trust", 0)) >= 2.0:
                            manual_block_keys.add(
                                (round(mz["easting"]), round(mz["northing"]))
                            )
                elif obj.get("type") == "point":
                    sk = (round(obj["easting"]), round(obj["northing"]))
                    seg_index[sk] = obj

    # ── Build sessions metadata ───────────────────────────────────────────────
    sessions = []
    for route in routes:
        sid = os.path.basename(getattr(route, "_jsonl_path", ""))
        if not sid:
            # Fall back to a deterministic ID from name
            sid = route.name
        sessions.append(
            {
                "id": sid,
                "trust_level": 1.0,
                "label": f"{route.name} — robot 100% confirmed",
                "n_points": len(route.x),
            }
        )

    # ── Merge GPS points ──────────────────────────────────────────────────────
    new_count = 0
    updated_count = 0
    risky_count = 0

    for route in routes:
        sid = route.name
        for xi, yi, alt, spd, ts in zip(route.x, route.y, route.z, route.spd, route.ts):
            e = round(float(xi) + UTM_E_CENTER, 3)
            n = round(float(yi) + UTM_N_CENTER, 3)
            sk = (round(e), round(n))

            risky = (
                _is_risky(xi, yi, cost_map, x_m, y_m) and sk not in manual_block_keys
            )
            trust = 0.9 if risky else 1.0
            if risky:
                risky_count += 1

            if sk in seg_index:
                seg_index[sk]["speed_kmh"] = round(float(spd), 2)
                updated_count += 1
            else:
                seg_index[sk] = {
                    "type": "point",
                    "easting": e,
                    "northing": n,
                    "altitude": round(float(alt), 2),
                    "trust": trust,
                    "speed_kmh": round(float(spd), 2),
                    "risky": risky,
                    "session_id": sid,
                    "timestamp": ts,
                }
                new_count += 1

    # ── Write JSONL ───────────────────────────────────────────────────────────
    meta = {
        "type": "meta",
        "schema_version": 2,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "area": {
            "lat_center": round(LAT_CENTER, 7),
            "lon_center": round(LON_CENTER, 7),
            "utm_e_center": round(UTM_E_CENTER, 2),
            "utm_n_center": round(UTM_N_CENTER, 2),
            "utm_zone": "32N",
            "lat_span": LAT_SPAN,
            "lon_span": LON_SPAN,
        },
        "sessions": sessions,
        "manual_zones": manual_zones,
    }

    with open(TRUST_DB_PATH, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for entry in seg_index.values():
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(
        f"  trust_db.jsonl: {len(seg_index)} unique segments  "
        f"({new_count} new, {updated_count} updated, {risky_count} risky (trust=0.9))"
    )
    print(f"  Location: {TRUST_DB_PATH}")
