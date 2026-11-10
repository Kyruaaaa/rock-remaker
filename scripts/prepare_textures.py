"""
Prepare the oriented photos (from build_hull.py) for projection onto the rock.

For every view this writes
  <view>_tex.png     colour, with the room's broad light and shadow reduced and
                     exposure matched to the neighbouring views
  <view>_height.png  fine grain only, for the bump map, so that a patch of dark
                     mineral or moss is not mistaken for a pit

Views with no top or bottom photo get one made from the matching end of the
front photo, mirrored over the edge so colours meet at the seam, at true
proportions. rig.json records these as "inferred".

    python3 prepare_textures.py rock_dir [--delight 0.6]
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orient  # noqa: E402

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
# view -> (neighbour, edge on this view, edge on the neighbour), tried in order
NEIGHBOURS = {
    "right": [("front", "l", "r")], "left": [("front", "r", "l")],
    "back": [("right", "l", "r"), ("left", "r", "l")],
    "top": [("front", "b", "t")], "bottom": [("front", "t", "b")],
}
GAIN_LIMITS = (0.6, 1.6)


def masked_blur(a, mask, sigma):
    m = mask.astype(np.float32)
    weight = ndimage.gaussian_filter(m, sigma)
    return ndimage.gaussian_filter(a * m, sigma) / np.maximum(weight, 1e-3), weight


def delight(rgb, mask, strength):
    """Even out broad light and shadow, leaving texture and colour alone."""
    luma = (rgb @ LUMA).astype(np.float32)
    low, weight = masked_blur(luma, mask, 0.16 * min(mask.shape))
    ref = float(np.median(luma[mask]))
    low = np.where(weight > 0.02, low, ref)
    ratio = np.clip((ref / np.maximum(low, 1.0)) ** strength, 0.65, 1.5)
    return np.clip(rgb * ratio[..., None], 0, 255)


def height_map(rgb, mask):
    """High-pass luminance: grain, not colour patches. 0.5 is neutral."""
    luma = (rgb @ LUMA).astype(np.float32)
    low, _ = masked_blur(luma, mask, max(1.5, 0.015 * min(mask.shape)))
    detail = (luma - low) * ndimage.gaussian_filter(mask.astype(np.float32), 2)
    spread = detail[mask].std() + 1e-3
    return np.clip(0.5 + 0.2 * np.tanh(detail / (2 * spread)) * 2, 0, 1)


def edge_colour(rgb, mask, edge):
    prof = orient.rim_profile(*orient.shrink(rgb.astype(np.uint8), mask), edge)
    return np.median(prof, axis=0)


def synth_end(front, rig, name):
    """A stand-in top/bottom: the end of the front photo, mirrored, at true proportions."""
    h, w = front.shape[:2]
    band = max(2, min(h, round(h * rig["D"] / rig["H"])))
    piece = front[:band] if name == "top" else front[h - band:]
    return piece[::-1].copy()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("rock_dir")
    p.add_argument("--delight", type=float, default=0.6, help="0 keeps the photo's lighting, 1 removes all broad light")
    a = p.parse_args(argv)
    d = a.rock_dir
    rig = json.load(open(os.path.join(d, "rig.json")))

    photos, masks = {}, {}
    for name in rig["views"]:
        photos[name] = np.asarray(Image.open(os.path.join(d, f"{name}_proj.png")).convert("RGB")).astype(np.float32)
        masks[name] = np.asarray(Image.open(os.path.join(d, f"{name}_proj_mask.png")).convert("L")) > 127
        photos[name] = delight(photos[name], masks[name], a.delight)

    # match exposure outward from the front along the edges neighbours share
    gains = {"front": np.ones(3, np.float32)}
    for name in ("right", "left", "back", "top", "bottom"):
        if name not in photos:
            continue
        for other, mine, theirs in NEIGHBOURS[name]:
            if other in gains:
                target = edge_colour(photos[other], masks[other], theirs)
                own = edge_colour(photos[name], masks[name], mine)
                gain = np.clip((target + 1) / (own + 1), *GAIN_LIMITS)
                photos[name] = np.clip(photos[name] * gain, 0, 255)
                gains[name] = gain
                break
    for name in photos:                 # corner views: match the front's overall colour
        if name not in gains:
            gain = np.clip(np.median(photos["front"][masks["front"]], axis=0) / (np.median(photos[name][masks[name]], axis=0) + 1), *GAIN_LIMITS)
            photos[name] = np.clip(photos[name] * gain, 0, 255)
            gains[name] = gain

    # keep the rock's overall brightness: gains only balance the views against each other
    overall = np.exp(np.mean([np.log(g) for g in gains.values()], axis=0))
    for name in photos:
        photos[name] = np.clip(photos[name] / overall, 0, 255)
        gains[name] = gains[name] / overall

    for name in list(photos):
        Image.fromarray(photos[name].astype(np.uint8)).save(os.path.join(d, f"{name}_tex.png"))
        h = height_map(photos[name], masks[name])
        Image.fromarray((h * 255).astype(np.uint8)).save(os.path.join(d, f"{name}_height.png"))
        rig["views"][name]["image"] = f"{name}_tex.png"
        rig["views"][name]["height"] = f"{name}_height.png"
        rig["views"][name]["gain"] = [round(float(g), 3) for g in gains[name]]

    tables = {"top": ((0, 0, 1), (1, 0, 0), (0, 1, 0)), "bottom": ((0, 0, -1), (1, 0, 0), (0, -1, 0))}
    for name, (facing, u_axis, v_axis) in tables.items():
        if name in rig["views"]:
            continue
        piece = synth_end(photos["front"], rig, name)
        mask = np.ones(piece.shape[:2], bool)
        Image.fromarray(piece.astype(np.uint8)).save(os.path.join(d, f"{name}_tex.png"))
        Image.fromarray((height_map(piece, mask) * 255).astype(np.uint8)).save(os.path.join(d, f"{name}_height.png"))
        rig["views"][name] = {
            "image": f"{name}_tex.png", "height": f"{name}_height.png", "inferred": True,
            "facing": list(facing), "u_axis": list(u_axis), "v_axis": list(v_axis),
            "su": 1 / rig["W"], "ou": 0.5, "sv": 1 / rig["D"], "ov": 0.5,
        }

    json.dump(rig, open(os.path.join(d, "rig.json"), "w"), indent=1)
    inferred = [n for n, v in rig["views"].items() if v.get("inferred")]
    print("textures ready" + (f"; inferred from the front photo: {', '.join(inferred)}" if inferred else ""))


if __name__ == "__main__":
    main()
