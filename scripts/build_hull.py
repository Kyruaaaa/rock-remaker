"""
Turn a rock's cut-out photo views (from cutout_views.py) into a 3D shape.

1. Works out how each view is turned. The photos weren't all taken with
   the rock the same way up, so each view is rotated 0 or 90 degrees,
   whichever matches the front view's proportions best.
2. Carves a block with the outlines: front (width x height), one side
   (depth x height) and the top (width x depth) when there is one;
   without a top, the cross-section is a rounded rectangle.
3. Smooths the carved block and turns it into a mesh (rock.obj),
   scaled to the tuff's overall size, centred on the vertical axis.
4. Writes rig.json: the rock's width/depth and, for each view, the
   oriented photo used to colour that side.

    python3 build_hull.py rock_dir
"""

import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import measure

RES = 128            # voxels along the rock's longest side
SMOOTH = 1.6         # blur (in voxels) before meshing: rounds the carved edges
ROUND = 2.6          # cross-section shape when there's no top view (2 = ellipse, big = box)
SIZE = 1.306          # every rock's bounding-box diagonal, matching the tuff model
MARGIN = 0.18        # only turn a view when turning matches clearly better (log-ratio)


def load(d, name, rotate):
    img = Image.open(os.path.join(d, f"{name}.png"))
    mask = Image.open(os.path.join(d, f"{name}_mask.png"))
    if rotate:
        img, mask = img.rotate(-90, expand=True), mask.rotate(-90, expand=True)
    return img, mask


def grid(mask, cols, rows):
    """Mask resampled to cols x rows, as [col, row] with row 0 at the bottom."""
    m = np.asarray(mask.resize((cols, rows), Image.BILINEAR)) > 127
    return np.flipud(m).T


def main(d):
    views = json.load(open(os.path.join(d, "views.json")))
    fw, fh = views["front"]["w"], views["front"]["h"]

    # side: prefer the right view; turn it if its width (not height) matches the front's height
    side = "right" if "right" in views else "left"
    sw, sh = views[side]["w"], views[side]["h"]
    side_rot = abs(math.log(sw / fh)) + MARGIN < abs(math.log(sh / fh))
    if side_rot:
        sw, sh = sh, sw
    W, D = fw / fh, (sw / sh)            # in units of the rock's height
    expect = {"front": W, "back": W, "left": D, "right": D, "top": W / D, "bottom": W / D}

    rig = {"W": W, "D": D, "H": 1.0, "views": {}}
    for name, v in views.items():
        if name == side:
            rot = side_rot
        elif name in ("left", "right"):      # the other side: same rule as the main side
            rot = abs(math.log(v["w"] / fh)) + MARGIN < abs(math.log(v["h"] / fh))
        else:
            rot = abs(math.log((v["h"] / v["w"]) / expect[name])) + MARGIN < abs(math.log((v["w"] / v["h"]) / expect[name]))
        img, mask = load(d, name, rot)
        img.save(os.path.join(d, f"{name}_proj.png"))
        mask.save(os.path.join(d, f"{name}_proj_mask.png"))
        rig["views"][name] = {"image": f"{name}_proj.png", "rotated": bool(rot)}

    # voxel grid: x across (width), y into the picture (depth), z up
    vs = max(W, D, 1.0) / RES
    nx, ny, nz = (max(8, round(a / vs)) for a in (W, D, 1.0))
    pad = 4
    occ = np.ones((nx, ny, nz), bool)

    _, fm = load(d, "front", False)
    occ &= grid(fm, nx, nz)[:, None, :]
    _, sm = load(d, side, side_rot)
    sg = grid(sm, ny, nz)                     # right view: image right = +y
    if side == "left":
        sg = sg[::-1]                         # left view: image right = -y
    occ &= sg[None, :, :]
    if "top" in views:
        _, tm = load(d, "top", rig["views"]["top"]["rotated"])
        occ &= grid(tm, nx, ny)[:, :, None]   # top view: image up = +y
        rig["top_used"] = True
    else:
        x = np.linspace(-1, 1, nx)[:, None]
        y = np.linspace(-1, 1, ny)[None, :]
        occ &= ((np.abs(x) ** ROUND + np.abs(y) ** ROUND) <= 1)[:, :, None]
        rig["top_used"] = False

    vol = np.pad(occ.astype(np.float32), pad)
    vol = ndimage.gaussian_filter(vol, SMOOTH)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5, spacing=(vs, vs, vs))
    verts -= pad * vs
    verts[:, 0] -= W / 2
    verts[:, 1] -= D / 2
    # rescale so the finished rock is exactly 1 tall, sitting on z = 0
    z0, z1 = verts[:, 2].min(), verts[:, 2].max()
    verts = (verts - [0, 0, z0]) / (z1 - z0)
    verts[:, 0] -= (verts[:, 0].min() + verts[:, 0].max()) / 2
    verts[:, 1] -= (verts[:, 1].min() + verts[:, 1].max()) / 2
    # same overall size as the tuff, whatever the rock's proportions
    verts *= SIZE / np.linalg.norm(verts.max(0) - verts.min(0))
    rig["W"] = float(verts[:, 0].max() - verts[:, 0].min())
    rig["D"] = float(verts[:, 1].max() - verts[:, 1].min())
    rig["H"] = float(verts[:, 2].max())

    with open(os.path.join(d, "rock.obj"), "w") as f:
        for x, y, z in verts:
            f.write(f"v {x:.5f} {y:.5f} {z:.5f}\n")
        for a, b, c in faces + 1:
            f.write(f"f {a} {b} {c}\n")
    json.dump(rig, open(os.path.join(d, "rig.json"), "w"), indent=1)
    turned = [n for n, v in rig["views"].items() if v["rotated"]]
    print(f"{os.path.basename(d)}: W {rig['W']:.2f} D {rig['D']:.2f}, {len(faces)} faces,"
          f" side={side}, top={'yes' if rig['top_used'] else 'no'}, turned: {', '.join(turned) or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1])
