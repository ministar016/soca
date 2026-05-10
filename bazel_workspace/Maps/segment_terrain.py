"""
Terrain Segmentation + Traversability Map
Kombinuje K-Means klasterovanje i HSV maske za robusnu klasifikaciju terena.
Procesira sve slike u Maps/ folderu.
"""

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")  # bez GUI, samo snima fajlove
import glob  # noqa: E402
import os  # noqa: E402

import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

MAPS_DIR = "/home/mn/soca/bazel_workspace/Maps"
OUT_DIR = os.path.join(MAPS_DIR, "results")
os.makedirs(OUT_DIR, exist_ok=True)

# --- Klase ---
LABELS = {
    0: "Nepoznato",
    1: "Vegetacija",
    2: "Gola zemlja / Pijesak",
    3: "Stijena / Kamen / Put",
    4: "Voda / Blato",
    5: "Sjena / Tamno",
}
COLOR_MAP = {
    0: [128, 128, 128],
    1: [34, 139, 34],
    2: [194, 154, 93],
    3: [180, 180, 180],
    4: [30, 100, 200],
    5: [40, 40, 40],
}
COST_TABLE = {
    0: 0.5,  # nepoznato
    1: 0.55,  # vegetacija - ovisno o gustoci
    2: 0.15,  # gola zemlja - dobro prolazno
    3: 0.10,  # stijena/put - najlakse
    4: 0.95,  # voda/blato - blokirano
    5: 0.70,  # sjena - oprezno
}


def segment_image(img_bgr):
    """
    Vraca (seg_map, cost_map, color_seg) za ulaznu BGR sliku.
    Koristi kombinaciju HSV maskiranja (prioritetizirano) i
    K-Means klasteringa za neoznacene piksele.
    """
    h, w = img_bgr.shape[:2]
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    # Blur za smanjenje suma
    img_hsv_b = cv2.GaussianBlur(img_hsv, (5, 5), 0)

    seg_map = np.zeros((h, w), dtype=np.uint8)  # 0 = neoznaceno

    # ---- Prioritetizirane HSV maske (redoslijed je vazan) ----

    # 1. VODA - visoka saturacija plava (mora biti prije tla jer blato moze biti slicno)
    m_water_blue = cv2.inRange(
        img_hsv_b, np.array([90, 50, 20]), np.array([130, 255, 220])
    )
    # Muljevita/smeda voda (niska S, niska V, braonkasta H)
    m_water_murky = cv2.inRange(
        img_hsv_b, np.array([5, 15, 10]), np.array([30, 90, 100])
    )
    m_water = cv2.bitwise_or(m_water_blue, m_water_murky)
    seg_map[m_water > 0] = 4

    # 2. VEGETACIJA - zelena (razlicite nijanse)
    m_veg_dark = cv2.inRange(
        img_hsv_b, np.array([30, 40, 20]), np.array([90, 255, 200])
    )
    m_veg_light = cv2.inRange(
        img_hsv_b, np.array([30, 25, 150]), np.array([80, 180, 255])
    )
    m_veg = cv2.bitwise_or(m_veg_dark, m_veg_light)
    m_veg[m_water > 0] = 0
    seg_map[m_veg > 0] = 1

    # 3. STIJENA / KAMEN / PUTEVi - niska saturacija, srednja-visoka svjetlost
    m_rock = cv2.inRange(img_hsv_b, np.array([0, 0, 90]), np.array([180, 45, 220]))
    m_rock[m_veg > 0] = 0
    m_rock[m_water > 0] = 0
    seg_map[m_rock > 0] = 3

    # 4. GOLA ZEMLJA / PIJESAK - topli tonovi (braon, narandzasta, zuta, beza)
    m_soil1 = cv2.inRange(img_hsv_b, np.array([8, 25, 60]), np.array([28, 255, 255]))
    m_soil2 = cv2.inRange(
        img_hsv_b, np.array([28, 20, 100]), np.array([40, 140, 255])
    )  # zutosmedja
    m_soil3 = cv2.inRange(
        img_hsv_b, np.array([155, 10, 80]), np.array([180, 120, 255])
    )  # crvenkasta zemlja
    m_soil = cv2.bitwise_or(cv2.bitwise_or(m_soil1, m_soil2), m_soil3)
    m_soil[m_veg > 0] = 0
    m_soil[m_water > 0] = 0
    m_soil[m_rock > 0] = 0
    seg_map[m_soil > 0] = 2

    # 5. SJENA / TAMNO
    m_dark = cv2.inRange(img_hsv_b, np.array([0, 0, 0]), np.array([180, 255, 55]))
    m_dark[m_water > 0] = 0
    seg_map[m_dark > 0] = 5

    # ---- K-Means za neoznacene piksele (cls=0) ----
    unassigned = seg_map == 0
    if unassigned.sum() > 500:
        pixels = img_rgb[unassigned].astype(np.float32)
        K = min(6, max(2, pixels.shape[0] // 500))
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels_km, centers = cv2.kmeans(
            pixels, K, None, criteria, 5, cv2.KMEANS_PP_CENTERS
        )
        # Za svaki klaster odredi klasu po sredisnjoj boji (HSV)
        for k in range(K):
            center_rgb = centers[k].astype(np.uint8).reshape(1, 1, 3)
            center_hsv = cv2.cvtColor(center_rgb, cv2.COLOR_RGB2HSV)[0, 0]
            ch, cs, cv_ = int(center_hsv[0]), int(center_hsv[1]), int(center_hsv[2])
            if cv_ < 55:
                cls = 5  # tamno/sjena
            elif cs < 45 and cv_ > 90:
                cls = 3  # siva -> kamen/put
            elif 30 <= ch <= 90 and cs > 35:
                cls = 1  # zelena -> vegetacija
            elif ch <= 30 and cs > 20 and cv_ > 60:
                cls = 2  # topla boja -> zemlja
            elif 90 <= ch <= 130 and cs > 40:
                cls = 4  # plava -> voda
            else:
                cls = 2  # default: zemlja
            mask_k = unassigned.copy()
            mask_k[unassigned] = labels_km.flatten() == k
            seg_map[mask_k] = cls

    # ---- Morfološko ciscenje ----
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    for cls in range(1, 6):
        m = (seg_map == cls).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=2)
        seg_map[seg_map == cls] = 0
        seg_map[m > 0] = cls

    # ---- Cost mapa ----
    cost_map = np.zeros((h, w), dtype=np.float32)
    for cls, cost in COST_TABLE.items():
        cost_map[seg_map == cls] = cost

    # ---- Vizualna segmentacijska slika ----
    color_seg = np.zeros((h, w, 3), dtype=np.uint8)
    for cls, color in COLOR_MAP.items():
        color_seg[seg_map == cls] = color

    return seg_map, cost_map, color_seg, img_rgb


def process_image(img_path):
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        print(f"  [GRESKA] Ne mogu ucitati: {img_path}")
        return

    name = os.path.splitext(os.path.basename(img_path))[0]
    h, w = img_bgr.shape[:2]
    total_px = h * w

    seg_map, cost_map, color_seg, img_rgb = segment_image(img_bgr)

    # Statistike
    print(f"\n{'='*60}")
    print(f"  {name}  ({w}x{h} px)")
    print(f"{'='*60}")
    print(f"  {'Klasa':<25} {'%':>7}  {'Cost':>6}")
    print(f"  {'-'*42}")
    for cls, lbl in LABELS.items():
        count = int(np.sum(seg_map == cls))
        pct = count / total_px * 100
        print(f"  {lbl:<25} {pct:>6.1f}%  {COST_TABLE[cls]:>6.2f}")

    traversable_pct = float(np.sum(cost_map < 0.4)) / total_px * 100
    blocked_pct = float(np.sum(cost_map >= 0.8)) / total_px * 100
    print(f"\n  ✅ Prolazno  (<0.4 cost): {traversable_pct:.1f}%")
    print(f"  🔴 Blokirano (>=0.8 cost): {blocked_pct:.1f}%")

    # Blended overlay (original + segmentacija)
    overlay = cv2.addWeighted(img_rgb, 0.55, color_seg, 0.45, 0)

    # Plot
    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    fig.suptitle(f"Terrain Segmentation — {name}", fontsize=13, fontweight="bold")

    axes[0].imshow(img_rgb)
    axes[0].set_title("Originalna slika", fontsize=11)
    axes[0].axis("off")

    axes[1].imshow(overlay)
    axes[1].set_title("Segmentacija (overlay)", fontsize=11)
    axes[1].axis("off")
    patches = [
        mpatches.Patch(color=[c / 255 for c in COLOR_MAP[cls]], label=LABELS[cls])
        for cls in LABELS
    ]
    axes[1].legend(
        handles=patches,
        loc="lower right",
        fontsize=7,
        framealpha=0.85,
        edgecolor="white",
    )

    im = axes[2].imshow(cost_map, cmap="RdYlGn_r", vmin=0, vmax=1)
    axes[2].set_title(
        f"Traversability Cost Map\n✅ Prolazno: {traversable_pct:.0f}%  "
        f"🔴 Blokirano: {blocked_pct:.0f}%",
        fontsize=10,
    )
    axes[2].axis("off")
    plt.colorbar(
        im, ax=axes[2], fraction=0.046, pad=0.04, label="0=slobodno  1=blokirano"
    )

    plt.tight_layout()
    out_path = os.path.join(OUT_DIR, f"{name}_seg.png")
    plt.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  Sacuvano → results/{name}_seg.png")


# ---- Procesiranje svih slika ----
extensions = ["*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG"]
all_images = []
for ext in extensions:
    all_images += glob.glob(os.path.join(MAPS_DIR, ext))

# Iskljuci prethodni output
all_images = [
    p
    for p in all_images
    if "_seg.png" not in p and "segmentation_result" not in p and "results" not in p
]
all_images.sort()

print(f"\nPronadjeno {len(all_images)} slika za obradu...")
for img_path in all_images:
    process_image(img_path)

print(f"\n\nSvi rezultati su u: {OUT_DIR}/")
