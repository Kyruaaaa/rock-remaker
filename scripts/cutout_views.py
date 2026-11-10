"""
Cut a rock's views out of its photographs.

Input is either
  * a photo sheet: a 2 x 3 grid on pure white (Front | Left / Right | Back / Top | Bottom),
  * or a folder of separate photos named front, back, left, right, top, bottom
    (any case; .jpg/.png), plus optional front_left, front_right, back_left, back_right.

Folder photos may be ordinary hand-held pictures. The rock is told apart from
the room by sharpness, position and colour, and parts of its outline hidden by
fingers are restored. If `rembg` is installed, --matte rembg uses it instead.

Writes, for every view found:
  <out>/<view>.png       the photo cropped to the rock, background filled with its own colours
  <out>/<view>_mask.png  white where the rock is
  <out>/views.json       each view's size

    python3 cutout_views.py sheet.png out_dir
    python3 cutout_views.py photos_dir out_dir [--matte auto|white|rembg]
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage
from scipy.cluster.vq import kmeans2
from skimage import color, morphology

SHEET_VIEWS = {  # name: (column, row) on the sheet
    "front": (0, 0), "left": (1, 0),
    "right": (0, 1), "back": (1, 1),
    "top": (0, 2), "bottom": (1, 2),
}
ALL_VIEWS = tuple(SHEET_VIEWS) + ("front_left", "front_right", "back_left", "back_right")
# vertical bands that hold the photos (as a share of the sheet height), above each row's labels
ROWS = [(0.0, 0.262), (0.300, 0.580), (0.620, 0.905)]
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")
MAX_SIDE = 1200           # long side of a saved view
MATTE_SIDE = 900          # long side used while separating the rock from the room


def fill_background(photo, core):
    """Colour everything outside `core` with blurred colour from inside it (no streaks)."""
    rgb = photo.astype(np.float32)
    m = core.astype(np.float32)
    span = max(core.shape)
    sigmas = [s for s in (span / 4, span / 8, span / 16, span / 32, span / 64, span / 128) if s >= 1]
    # coarsest layer: the rock's average colour, so nothing is left undefined
    out = np.broadcast_to(rgb[core].mean(axis=0), rgb.shape).copy()
    for s in sigmas:
        weight = ndimage.gaussian_filter(m, s)
        colour = np.stack([ndimage.gaussian_filter(rgb[..., c] * m, s) for c in range(3)], axis=2)
        colour /= np.maximum(weight, 1e-4)[..., None]
        alpha = np.clip(weight * 4, 0, 1)[..., None]
        out = out * (1 - alpha) + colour * alpha
    out[core] = rgb[core]
    return np.clip(out, 0, 255).astype(np.uint8)


def finish(rgb, mask):
    """Crop to the rock and hide the background behind its own colours."""
    ys, xs = np.nonzero(mask)
    t, b, l, r = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    mask, photo = mask[t:b, l:r], rgb[t:b, l:r].copy()
    rim = max(2, round(min(mask.shape) * 0.016))    # stay clear of the pale anti-aliased edge
    core = ndimage.binary_erosion(mask, iterations=rim)
    if not core.any():
        core = mask
    return fill_background(photo, core), mask


def clean(mask):
    """Drop specks, keep the one big piece, fill its holes."""
    scale = max(1, round(min(mask.shape) / 110))
    pad = 2 * scale + 2
    m = np.pad(mask, pad)
    m = ndimage.binary_opening(m, iterations=scale)
    labels, n = ndimage.label(m)
    if n == 0:
        return None
    sizes = ndimage.sum(m, labels, range(1, n + 1))
    biggest = int(np.argmax(sizes)) + 1
    if sizes[biggest - 1] < 0.002 * m.size:
        return None
    m = labels == biggest
    m = ndimage.binary_closing(m, iterations=scale + 1)
    m = ndimage.binary_fill_holes(m)
    return m[pad:-pad, pad:-pad]


def white_matte(rgb, alpha=None):
    px = rgb.astype(np.float32)
    mask = (255 - px.min(axis=2) > 8) | (px.max(axis=2) - px.min(axis=2) > 8)
    if alpha is not None:
        mask &= alpha > 128
    return clean(mask)


def rembg_matte(rgb):
    try:
        from rembg import remove
    except ImportError:
        sys.exit("--matte rembg needs the rembg package (pip install rembg)")
    a = np.asarray(remove(Image.fromarray(rgb), only_mask=True))
    return clean(a > 127)


def skin_mask(lab):
    """Hands: pink-orange and reasonably bright. Grey-brown stone has much lower a*."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    return (a > 11) & (b > 4) & (L > 28) & (a / np.maximum(b, 1) > 0.55)


def fit(pixels, k):
    if len(pixels) > 6000:
        pixels = pixels[np.random.default_rng(1).choice(len(pixels), 6000, replace=False)]
    centres, labels = kmeans2(pixels, k, minit="++", seed=1, iter=12)
    parts = []
    for i in range(k):
        p = pixels[labels == i]
        if len(p) < 12:
            continue
        parts.append((len(p) / len(pixels), p.mean(axis=0), p.var(axis=0) + 6.0))
    return parts


def log_like(pixels, model):
    terms = []
    for w, mean, var in model:
        terms.append(np.log(w) - 0.5 * (((pixels - mean) ** 2 / var).sum(axis=-1) + np.log(var).sum()))
    return np.max(np.stack(terms), axis=0)


def auto_matte(rgb):
    """Rock versus room for a hand-held photo: sharp, central and differently coloured."""
    h, w = rgb.shape[:2]
    lab = color.rgb2lab(rgb).astype(np.float32)
    L = lab[..., 0]
    span = max(h, w)
    edges = np.abs(ndimage.laplace(ndimage.gaussian_filter(L, span / 900)))
    focus = ndimage.gaussian_filter(edges, span / 60)
    focus = focus / np.percentile(focus, 99)
    yy, xx = np.mgrid[0:h, 0:w]
    centre = np.exp(-0.5 * (((xx / w - 0.5) / 0.26) ** 2 + ((yy / h - 0.5) / 0.28) ** 2)).astype(np.float32)
    skin = ndimage.binary_opening(skin_mask(lab), iterations=2)
    skin_near = ndimage.binary_dilation(skin, iterations=max(2, span // 200))
    border = np.ones((h, w), bool)
    border[int(h * .05):int(h * .95), int(w * .05):int(w * .95)] = False

    score = focus * centre
    fg = (score > np.percentile(score, 90)) & ~skin_near
    bg = border | skin_near | (centre < 0.08)

    for _ in range(5):
        fm, bm = fit(lab[fg], 5), fit(lab[bg], 8)
        ratio = log_like(lab, fm) - log_like(lab, bm)
        evidence = np.clip(ratio, -12, 12) + 5.0 * (centre - 0.32) + 4.0 * (focus - 0.28)
        evidence = ndimage.gaussian_filter(evidence, span / 300)
        evidence[skin] = -20
        current = clean(evidence > 0)
        if current is None:
            return None
        fg = ndimage.binary_erosion(current, iterations=max(2, span // 120)) & ~skin_near
        if fg.sum() < 200:
            fg = current
        bg = ~ndimage.binary_dilation(current, iterations=max(2, span // 90))

    # the room is out of focus: anything much softer than the rock's own centre isn't rock
    core = ndimage.binary_erosion(current, iterations=max(2, span // 40))
    sharp = focus > 0.42 * np.median(focus[core if core.any() else current])
    mask = clean(current & (sharp | core))
    if mask is None:
        return None
    hand_seen = skin
    # a tighter sharpness check near the rim: the room and hand are soft, even dark rock is grainy
    middle = ndimage.distance_transform_edt(np.pad(mask, 1))[1:-1, 1:-1] > span * 0.09
    if middle.sum() > 500:
        fine = ndimage.gaussian_filter(edges, span / 110)
        tight = ndimage.gaussian_filter((fine > 0.24 * np.median(fine[middle])).astype(np.float32), span / 200) > 0.5
        hand = skin
        if skin.sum() > 400:           # learn this photo's hand colours, so warm-lit fingers are caught too
            looks = log_like(lab, fit(lab[skin], 3)) - log_like(lab, fit(lab[middle], 6))
            hand = skin | (ndimage.gaussian_filter(looks, span / 300) > 1.0)
        hand_seen = hand
        refined = clean(mask & (middle | (tight & ~hand)))
        if refined is not None and refined.sum() > 0.6 * mask.sum():
            mask = refined
    # snip anything joined to the rock by a narrow neck
    radius = span / 28
    inner = ndimage.distance_transform_edt(np.pad(mask, 2)) > radius
    if inner.any():
        grown = ndimage.distance_transform_edt(~inner) <= radius
        mask = clean(mask & grown[2:-2, 2:-2]) if (mask & grown[2:-2, 2:-2]).any() else mask
    # a thumb lying along the rim: a rounded-off copy of the outline shows what sticks out,
    # and anything sticking out that touches the hand is hand
    radius = span / 15
    inner = ndimage.distance_transform_edt(np.pad(mask, 2)) > radius
    if inner.any():
        rounded = (ndimage.distance_transform_edt(~inner) <= radius)[2:-2, 2:-2]
        bumps, n = ndimage.label(mask & ~rounded)
        near_hand = ndimage.binary_dilation(hand_seen, iterations=max(2, span // 40))
        for i in range(1, n + 1):
            bump = bumps == i
            if (bump & near_hand).any():
                mask = mask & ~ndimage.binary_dilation(bump, iterations=max(1, span // 150))
        kept = ndimage.binary_fill_holes(ndimage.binary_opening(np.pad(mask, 2), iterations=2))[2:-2, 2:-2]
        labels, n = ndimage.label(kept)
        if n:
            mask = labels == (int(np.argmax(ndimage.sum(kept, labels, range(1, n + 1)))) + 1)
    # fingers bite into the outline: restore shallow gaps in its convex shape that touch skin
    hull = morphology.convex_hull_image(mask)
    gaps, n = ndimage.label(hull & ~mask)
    for i in range(1, n + 1):
        gap = gaps == i
        thick = ndimage.distance_transform_edt(np.pad(gap, 1)).max()
        if (gap & skin_near).sum() > 0.25 * gap.sum() and thick < span * 0.02:
            mask = mask | gap
    # a smooth outline: phone-photo mattes are ragged at this scale
    s = span / 220
    return clean(ndimage.gaussian_filter(mask.astype(np.float32), s) > 0.5)


def cut_sheet_cell(sheet, col, row):
    h, w = sheet.shape[:2]
    y0, y1 = int(ROWS[row][0] * h), int(ROWS[row][1] * h)
    x0, x1 = col * w // 2, (col + 1) * w // 2
    cell = sheet[y0:y1, x0:x1]
    mask = white_matte(cell[..., :3], cell[..., 3])
    return None if mask is None else finish(cell[..., :3], mask)


def read_photo(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return np.asarray(im)


def looks_white(rgb):
    ring = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3), rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
    return (ring.min(axis=1) > 247).mean() > 0.98


def matte_photo(rgb, method):
    if method == "rembg":
        return rembg_matte(rgb)
    if method == "white" or (method == "auto" and looks_white(rgb)):
        return white_matte(rgb)
    k = MATTE_SIDE / max(rgb.shape[:2])
    if k >= 1:
        return auto_matte(rgb)
    size = (round(rgb.shape[1] * k), round(rgb.shape[0] * k))
    small = np.asarray(Image.fromarray(rgb).resize(size, Image.LANCZOS))
    m = auto_matte(small)
    if m is None:
        return None
    big = Image.fromarray((m * 255).astype(np.uint8)).resize((rgb.shape[1], rgb.shape[0]), Image.BICUBIC)
    return np.asarray(big) > 127


def find_photos(folder):
    found = {}
    for entry in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(entry)
        name = stem.lower().replace("-", "_").replace(" ", "_")
        if ext.lower() in PHOTO_EXT and name in ALL_VIEWS:
            found[name] = os.path.join(folder, entry)
    return found


def save(out, results):
    os.makedirs(out, exist_ok=True)
    info = {}
    for name, (photo, mask) in results.items():
        Image.fromarray(photo).save(os.path.join(out, f"{name}.png"))
        Image.fromarray((mask * 255).astype(np.uint8)).save(os.path.join(out, f"{name}_mask.png"))
        info[name] = {"w": int(mask.shape[1]), "h": int(mask.shape[0])}
    with open(os.path.join(out, "views.json"), "w") as f:
        json.dump(info, f, indent=1)
    return info


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", help="photo sheet, or a folder of named photos")
    p.add_argument("out")
    p.add_argument("--matte", choices=("auto", "white", "rembg"), default="auto")
    a = p.parse_args(argv)

    results = {}
    if os.path.isdir(a.source):
        photos = find_photos(a.source)
        if not photos:
            sys.exit(f"{a.source}: no photos named {', '.join(ALL_VIEWS)}")
        for name, path in photos.items():
            rgb = read_photo(path)
            mask = matte_photo(rgb, a.matte)
            if mask is None:
                print(f"  warning: could not find the rock in {path}")
                continue
            results[name] = finish(rgb, mask)
    else:
        sheet = np.asarray(Image.open(a.source).convert("RGBA"))
        for name, (col, row) in SHEET_VIEWS.items():
            cut = cut_sheet_cell(sheet, col, row)
            if cut is not None:
                results[name] = cut

    info = save(a.out, results)
    print(os.path.basename(os.path.normpath(a.source)), "->", ", ".join(f"{k} {v['w']}x{v['h']}" for k, v in info.items()) or "no views")
    if "front" not in info or not ({"left", "right"} & set(info)):
        sys.exit(f"{a.source}: need a front view and at least one side view; found: {', '.join(info) or 'none'}")


if __name__ == "__main__":
    main()
