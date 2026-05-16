"""
segmentation.py — HSV + K-Means terrain classification.

Can be run as a standalone script to (re-)segment all images in Maps/:
    python -m soca_map.segmentation

Public API
----------
segment_image(img_bgr) -> (seg_map, cost_map, color_seg, img_rgb)

process_all(maps_dir, out_dir)
    Process every image in maps_dir and write labelled PNGs to out_dir.
"""

from __future__ import annotations

import glob
import os

import cv2
import matplotlib
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

# ── Class definitions ─────────────────────────────────────────────────────────

LABELS: dict[int, str] = {
    0: "Unknown",
    1: "Vegetation",
    2: "Bare earth / Sand",
    3: "Rock / Stone / Path",
    4: "Water / Mud",
    5: "Shadow / Dark",
}

COLOR_MAP: dict[int, list[int]] = {
    0: [128, 128, 128],
    1: [34, 139, 34],
    2: [194, 154, 93],
    3: [180, 180, 180],
    4: [30, 100, 200],
    5: [40, 40, 40],
}

COST_TABLE: dict[int, float] = {
    0: 0.50,  # unknown
    1: 0.55,  # vegetation
    2: 0.15,  # bare earth — good traction
    3: 0.10,  # rock / path — easiest
    4: 0.95,  # water / mud — blocked
    5: 0.70,  # shadow — caution
}


# ── Core segmentation ─────────────────────────────────────────────────────────


def segment_image(
    img_bgr: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Segment a BGR image into terrain classes.

    Returns
    -------
    seg_map   : (H, W) uint8   — class index per pixel
    cost_map  : (H, W) float32 — traversability cost per pixel [0, 1]
    color_seg : (H, W, 3) uint8 — false-colour visualisation
    img_rgb   : (H, W, 3) uint8 — input converted to RGB
    """
    h, w = img_bgr.shape[:2]
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    hsv_b = cv2.GaussianBlur(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV), (5, 5), 0)
    seg_map = np.zeros((h, w), dtype=np.uint8)

    # ── Prioritised HSV masks ─────────────────────────────────────────────────
    # 1. Water (before soil — murky water has warm tones)
    m_water = cv2.bitwise_or(
        cv2.inRange(hsv_b, (90, 50, 20), (130, 255, 220)),  # blue water
        cv2.inRange(hsv_b, (5, 15, 10), (30, 90, 100)),  # murky / muddy
    )
    seg_map[m_water > 0] = 4

    # 2. Vegetation
    m_veg = cv2.bitwise_or(
        cv2.inRange(hsv_b, (30, 40, 20), (90, 255, 200)),
        cv2.inRange(hsv_b, (30, 25, 150), (80, 180, 255)),
    )
    m_veg[m_water > 0] = 0
    seg_map[m_veg > 0] = 1

    # 3. Rock / path — low saturation, mid-high brightness
    m_rock = cv2.inRange(hsv_b, (0, 0, 90), (180, 45, 220))
    m_rock[m_veg > 0] = 0
    m_rock[m_water > 0] = 0
    seg_map[m_rock > 0] = 3

    # 4. Bare earth / sand — warm hues
    m_soil = cv2.bitwise_or(
        cv2.bitwise_or(
            cv2.inRange(hsv_b, (8, 25, 60), (28, 255, 255)),
            cv2.inRange(hsv_b, (28, 20, 100), (40, 140, 255)),
        ),
        cv2.inRange(hsv_b, (155, 10, 80), (180, 120, 255)),
    )
    m_soil[m_veg > 0] = 0
    m_soil[m_water > 0] = 0
    m_soil[m_rock > 0] = 0
    seg_map[m_soil > 0] = 2

    # 5. Shadow / dark
    m_dark = cv2.inRange(hsv_b, (0, 0, 0), (180, 255, 55))
    m_dark[m_water > 0] = 0
    seg_map[m_dark > 0] = 5

    # ── K-Means for remaining unassigned pixels ───────────────────────────────
    unassigned = seg_map == 0
    if unassigned.sum() > 500:
        pixels = img_rgb[unassigned].astype(np.float32)
        K = min(6, max(2, pixels.shape[0] // 500))
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels_km, centers = cv2.kmeans(
            pixels, K, None, criteria, 5, cv2.KMEANS_PP_CENTERS
        )
        for k in range(K):
            center_hsv = cv2.cvtColor(
                centers[k].astype(np.uint8).reshape(1, 1, 3), cv2.COLOR_RGB2HSV
            )[0, 0]
            ch, cs, cv_ = int(center_hsv[0]), int(center_hsv[1]), int(center_hsv[2])
            if cv_ < 55:
                cls = 5
            elif cs < 45 and cv_ > 90:
                cls = 3
            elif 30 <= ch <= 90 and cs > 35:
                cls = 1
            elif ch <= 30 and cs > 20 and cv_ > 60:
                cls = 2
            elif 90 <= ch <= 130 and cs > 40:
                cls = 4
            else:
                cls = 2
            mask_k = unassigned.copy()
            mask_k[unassigned] = labels_km.flatten() == k
            seg_map[mask_k] = cls

    # ── Morphological cleanup ─────────────────────────────────────────────────
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    for cls in range(1, 6):
        m = (seg_map == cls).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=2)
        seg_map[seg_map == cls] = 0
        seg_map[m > 0] = cls

    # ── Cost and colour maps ──────────────────────────────────────────────────
    cost_map = np.zeros((h, w), dtype=np.float32)
    color_seg = np.zeros((h, w, 3), dtype=np.uint8)
    for cls in range(6):
        cost_map[seg_map == cls] = COST_TABLE[cls]
        color_seg[seg_map == cls] = COLOR_MAP[cls]

    return seg_map, cost_map, color_seg, img_rgb


# ── Batch processing ──────────────────────────────────────────────────────────


def process_all(maps_dir: str, out_dir: str) -> None:
    """Segment all images in maps_dir and write overlays to out_dir."""
    os.makedirs(out_dir, exist_ok=True)

    extensions = ["*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG"]
    all_images: list[str] = []
    for ext in extensions:
        all_images += glob.glob(os.path.join(maps_dir, ext))

    # Exclude previous outputs and segment_terrain results
    all_images = [
        p
        for p in all_images
        if "_seg.png" not in p
        and "segmentation_result" not in p
        and "results" not in p
        and "satellite_tile" not in p
    ]
    all_images.sort()
    print(f"\nFound {len(all_images)} image(s) to process...")

    for img_path in all_images:
        _process_one(img_path, out_dir)

    print(f"\nAll results saved to: {out_dir}/")


def _process_one(img_path: str, out_dir: str) -> None:
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        print(f"  [ERROR] Cannot read: {img_path}")
        return

    name = os.path.splitext(os.path.basename(img_path))[0]
    h, w = img_bgr.shape[:2]
    total_px = h * w

    seg_map, cost_map, color_seg, img_rgb = segment_image(img_bgr)
    overlay = cv2.addWeighted(img_rgb, 0.55, color_seg, 0.45, 0)

    traversable_pct = float(np.sum(cost_map < 0.4)) / total_px * 100
    blocked_pct = float(np.sum(cost_map >= 0.8)) / total_px * 100

    print(f"\n{'='*60}")
    print(f"  {name}  ({w}×{h} px)")
    print(f"{'='*60}")
    print(f"  {'Class':<25} {'%':>7}  {'Cost':>6}")
    print(f"  {'-'*42}")
    for cls, lbl in LABELS.items():
        count = int(np.sum(seg_map == cls))
        pct = count / total_px * 100
        print(f"  {lbl:<25} {pct:>6.1f}%  {COST_TABLE[cls]:>6.2f}")
    print(f"\n  Passable (<0.4):  {traversable_pct:.1f}%")
    print(f"  Blocked  (>=0.8): {blocked_pct:.1f}%")

    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    fig.suptitle(f"Terrain Segmentation — {name}", fontsize=13, fontweight="bold")

    axes[0].imshow(img_rgb)
    axes[0].set_title("Original")
    axes[0].axis("off")
    axes[1].imshow(overlay)
    axes[1].set_title("Segmentation overlay")
    axes[1].axis("off")
    axes[1].legend(
        handles=[
            mpatches.Patch(color=[c / 255 for c in COLOR_MAP[cls]], label=LABELS[cls])
            for cls in LABELS
        ],
        loc="lower right",
        fontsize=7,
        framealpha=0.85,
    )

    im = axes[2].imshow(cost_map, cmap="RdYlGn_r", vmin=0, vmax=1)
    axes[2].set_title(
        f"Traversability cost\nPassable: {traversable_pct:.0f}%  Blocked: {blocked_pct:.0f}%",
        fontsize=10,
    )
    axes[2].axis("off")
    plt.colorbar(im, ax=axes[2], fraction=0.046, pad=0.04, label="0=free  1=blocked")

    plt.tight_layout()
    out_path = os.path.join(out_dir, f"{name}_seg.png")
    plt.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {os.path.relpath(out_path)}")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from .config import MAPS_DIR

    process_all(MAPS_DIR, os.path.join(MAPS_DIR, "results"))
