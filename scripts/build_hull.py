"""
Turn a rock's cut-out views (from cutout_views.py) into a 3D shape.

1. Works out how each view is turned (see orient.py).
2. Carves a signed-distance volume from the outlines. A hard intersection of
   extruded outlines leaves a plaid of straight grooves, because a bump on one
   outline gets dragged straight across the whole rock. So every outline keeps
   its full detail only near the middle of the rock along its viewing direction
   (where that outline is most likely to really be) and relaxes to a smoothed
   copy away from it.
3. Without a top view, each height gets its own rounded cross-section.
4. Optional: optional *_depth.png files press real hollows into the faces, and
   optional corner views (front_left, front_right, back_left, back_right) carve
   at 45 degrees.
5. Writes rock.obj, rig.json (how each photo projects) and qa.json (how well
   the finished shape matches every outline).

    python3 build_hull.py rock_dir [--res 128 ...]

An optional rock_dir/overrides.json such as {"rotate": {"right": 180}} forces a
view's clockwise rotation when automatic orientation guesses wrong.
"""

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import measure

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orient  # noqa: E402

AXIS_VIEWS = ("front", "back", "left", "right", "top", "bottom")
CORNERS = {  # name: yaw of the camera around the rock, degrees from the front
    "front_right": 45, "back_right": 135, "back_left": 225, "front_left": 315,
}
LOW_IOU = 0.85     # below this, qa.json flags a view


def parse(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("rock_dir")
    p.add_argument("--res", type=int, default=128, help="voxels along the longest side")
    p.add_argument("--smooth", type=float, default=1.1, help="final blur in voxels")
    p.add_argument("--soften", type=float, default=0.1, help="outline blur away from its mid-plane, share of RES")
    p.add_argument("--blend", type=float, default=0.05, help="corner rounding where outlines meet, share of RES")
    p.add_argument("--round", type=float, default=2.4, help="cross-section with no top view (2 ellipse, big box)")
    p.add_argument("--round-top", type=float, default=4.0, help="cross-section rounding when a top view exists")
    p.add_argument("--relief", type=float, default=0.09, help="deepest hollow from a depth map, share of RES")
    p.add_argument("--relief-width", type=float, default=0.2, help="widest hollow a depth map can make, share of RES")
    p.add_argument("--size", type=float, default=1.306, help="every rock's bounding-box diagonal")
    return p.parse_args(argv)


def smax(a, b, k):
    """Smooth maximum: like max(a, b), with a rounded join of width k."""
    if k <= 0:
        return np.maximum(a, b)
    h = np.maximum(k - np.abs(a - b), 0.0) / k
    return np.maximum(a, b) + h * h * k * 0.25


def smoothstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def load_view(d, name, deg):
    rgb = np.asarray(Image.open(os.path.join(d, f"{name}.png")).convert("RGB"))
    mask = np.asarray(Image.open(os.path.join(d, f"{name}_mask.png")).convert("L"))
    return np.rot90(rgb, -deg // 90).copy(), np.rot90(mask, -deg // 90).copy()


def grid(a, cols, rows):
    """Greyscale array resampled to cols x rows, as [col, row] with row 0 at the bottom."""
    img = Image.fromarray(a).resize((cols, rows), Image.BILINEAR)
    return np.flipud(np.asarray(img)).T


def sdf2(mask_grid):
    m = mask_grid > 127
    pad = 12
    p = np.pad(m, pad)
    d = ndimage.distance_transform_edt(~p) - ndimage.distance_transform_edt(p)
    return d[pad:-pad, pad:-pad].astype(np.float32)


def ray_position(occ, axis):
    """For rays along `axis`: how far each voxel is from the middle of the solid (0 mid .. 1 end)."""
    n = occ.shape[axis]
    first = occ.argmax(axis=axis)
    last = n - 1 - np.flip(occ, axis=axis).argmax(axis=axis)
    hit = occ.any(axis=axis)
    centre = np.expand_dims((first + last) / 2.0, axis)
    half = np.expand_dims(np.maximum((last - first) / 2.0, 1.0), axis)
    shape = [1, 1, 1]
    shape[axis] = n
    idx = np.arange(n, dtype=np.float32).reshape(shape)
    t = np.abs(idx - centre) / half
    t[~np.broadcast_to(np.expand_dims(hit, axis), t.shape)] = 1.0
    return np.clip(t, 0, 1).astype(np.float32)


def extrude(sd, axis):
    return np.expand_dims(sd, axis)


def relax(sharp, soft, axis, occ):
    t = ray_position(occ, axis)
    w = smoothstep(t, 0.0, 0.3)
    return extrude(sharp, axis) * (1 - w) + extrude(soft, axis) * w


def cross_section(occ_xz, occ_yz, nx, ny, nz, p):
    """Per-height superellipse fitted to that height's width and depth."""
    def span(a):  # a: [col, row]
        hit = a.any(axis=0)
        lo = a.argmax(axis=0).astype(np.float32)
        hi = (a.shape[0] - 1 - a[::-1].argmax(axis=0)).astype(np.float32)
        return hit, (lo + hi) / 2, np.maximum((hi - lo + 1) / 2, 0.5)

    hit_x, cx, hx = span(occ_xz)
    hit_y, cy, hy = span(occ_yz)
    # keep the loft from flickering between neighbouring heights
    for arr in (cx, hx, cy, hy):
        arr[:] = ndimage.gaussian_filter1d(arr, 1.5, mode="nearest")
    x = np.arange(nx, dtype=np.float32)[:, None, None]
    y = np.arange(ny, dtype=np.float32)[None, :, None]
    ux = np.abs(x - cx[None, None, :]) / hx[None, None, :]
    uy = np.abs(y - cy[None, None, :]) / hy[None, None, :]
    r = (ux ** p + uy ** p) ** (1 / p)
    out = (r - 1) * np.minimum(hx, hy)[None, None, :]
    out[..., ~(hit_x & hit_y)] = 20.0
    return out.astype(np.float32)


def corner_sdf(mask, yaw_deg, nx, ny, nz, occ, sigma):
    """Signed distance to a 45-degree view's outline, mapped onto the current solid's extent."""
    yaw = math.radians(yaw_deg)
    ux, uy = math.cos(yaw), math.sin(yaw)     # image right
    dx, dy = -math.sin(yaw), math.cos(yaw)    # into the picture
    xs, ys, zs = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    cx, cy = (nx - 1) / 2, (ny - 1) / 2
    u = (xs - cx) * ux + (ys - cy) * uy
    along = (xs - cx) * dx + (ys - cy) * dy
    umin, umax = u[occ].min(), u[occ].max()
    zhit = np.nonzero(occ.any(axis=(0, 1)))[0]
    cols, rows = max(8, round(umax - umin) + 1), max(8, int(zhit[-1] - zhit[0]) + 1)
    sd = sdf2(grid(mask, cols, rows))
    soft = ndimage.gaussian_filter(sd, sigma)
    coords = np.stack([(u - umin) / max(umax - umin, 1) * (cols - 1), (zs - zhit[0]) / max(zhit[-1] - zhit[0], 1) * (rows - 1)])
    sharp_v = ndimage.map_coordinates(sd, coords, order=1, mode="nearest").astype(np.float32)
    soft_v = ndimage.map_coordinates(soft, coords, order=1, mode="nearest").astype(np.float32)
    extent = max(np.abs(along[occ]).max(), 1)
    w = smoothstep(np.abs(along) / extent, 0.0, 0.3)
    return sharp_v * (1 - w) + soft_v * w


# (ray axis, starts from the far end?, grid flip) for pressing a depth map in
RELIEF = {
    "front": (1, False, lambda g: g), "back": (1, True, lambda g: g[::-1]),
    "right": (0, True, lambda g: g), "left": (0, False, lambda g: g[::-1]),
    "top": (2, True, lambda g: g), "bottom": (2, False, lambda g: g[:, ::-1]),
}


def press_relief(sdf, name, depth_grid, mask_sd, amount, width):
    """Carve hollows from a depth map (bright = near the camera). Only ever removes material."""
    axis, far, _ = RELIEF[name]
    m = mask_sd < 0
    d = depth_grid.astype(np.float32)
    weights = ndimage.gaussian_filter(m.astype(np.float32), width) + 1e-3
    broad = ndimage.gaussian_filter(d * m, width) / weights
    high = d - broad
    spread = high[m].std() + 1e-6
    hollow = np.clip(-high / spread, 0, 2.5) / 2.5
    hollow *= smoothstep(-mask_sd, 2, 12)                # leave the outline alone
    carve = amount * hollow
    occ = sdf < 0
    n = occ.shape[axis]
    view = np.flip(occ, axis=axis) if far else occ
    first = view.argmax(axis=axis).astype(np.float32)
    shape = [1, 1, 1]
    shape[axis] = n
    idx = np.arange(n, dtype=np.float32).reshape(shape)
    if far:
        idx = (n - 1) - idx
    # push the surface in by `carve`, fading out a few voxels behind it; zero carve changes nothing
    depth_in = idx - np.expand_dims(first, axis)
    deep = np.expand_dims(carve, axis)
    fade = 1 - smoothstep(depth_in, deep, deep + 6)
    return sdf + (deep * fade).astype(np.float32)


def project(vol, name):
    """Occupancy seen from a view, as [col, row] in that view's grid."""
    axis, _, flip = RELIEF[name]
    return flip(vol.any(axis=axis))


def main(argv=None):
    a = parse(sys.argv[1:] if argv is None else argv)
    d = a.rock_dir
    view_info = json.load(open(os.path.join(d, "views.json")))
    if "front" not in view_info or not ({"left", "right"} & set(view_info)):
        sys.exit(f"{d}: need a front view and at least one side view; found: {', '.join(view_info) or 'none'}")

    overrides = {}
    path = os.path.join(d, "overrides.json")
    if os.path.exists(path):
        overrides = json.load(open(path)).get("rotate", {})

    raw = {n: load_view(d, n, 0) for n in view_info}
    rot, conf = orient.choose({n: (r, m > 127) for n, (r, m) in raw.items() if n in AXIS_VIEWS}, overrides)
    for n in view_info:
        rot.setdefault(n, 0)
        conf.setdefault(n, 1.0)
    views = {n: load_view(d, n, rot[n]) for n in view_info}
    for n, (rgb, mask) in views.items():
        Image.fromarray(rgb).save(os.path.join(d, f"{n}_proj.png"))
        Image.fromarray(mask).save(os.path.join(d, f"{n}_proj_mask.png"))

    def wh(n):
        return views[n][1].shape[1], views[n][1].shape[0]

    fw, fh = wh("front")
    side = "right" if "right" in views else "left"
    sw, sh = wh(side)
    W, D = fw / fh, sw / sh                  # in units of the rock's height

    vs = max(W, D, 1.0) / a.res
    nx, ny, nz = (max(8, round(v / vs)) for v in (W, D, 1.0))
    sigma = a.soften * a.res
    k = a.blend * a.res

    sd_front = sdf2(grid(views["front"][1], nx, nz))
    side_grid = grid(views[side][1], ny, nz)
    if side == "left":
        side_grid = side_grid[::-1]
    sd_side = sdf2(side_grid)
    has_top = "top" in views
    sd_top = sdf2(grid(views["top"][1], nx, ny)) if has_top else None

    # first pass: where the solid is, to know each ray's mid-point
    occ = (sd_front < 0)[:, None, :] & (sd_side < 0)[None, :, :]
    if has_top:
        occ &= (sd_top < 0)[:, :, None]

    sdf = smax(relax(sd_front, ndimage.gaussian_filter(sd_front, sigma), 1, occ),
               relax(sd_side, ndimage.gaussian_filter(sd_side, sigma), 0, occ), k)
    if has_top:
        sdf = smax(sdf, relax(sd_top, ndimage.gaussian_filter(sd_top, sigma), 2, occ), k)
    section = cross_section(sd_front < 0, sd_side < 0, nx, ny, nz, a.round_top if has_top else a.round)
    sdf = smax(sdf, section, k)

    used_corners = []
    for name in CORNERS:
        if name in views:
            sdf = smax(sdf, corner_sdf(views[name][1], CORNERS[name], nx, ny, nz, sdf < 0, sigma), k)
            used_corners.append(name)

    grids = {"front": sd_front, side: sd_side}
    if has_top:
        grids["top"] = sd_top
    relief_used = []
    for name in AXIS_VIEWS:
        depth_path = os.path.join(d, f"{name}_depth.png")
        if name not in views or not os.path.exists(depth_path):
            continue
        dep = np.asarray(Image.open(depth_path).convert("L"))
        dep = np.rot90(dep, -rot[name] // 90).copy()
        axis = RELIEF[name][0]
        cols, rows = {1: (nx, nz), 0: (ny, nz), 2: (nx, ny)}[axis]
        flip = RELIEF[name][2]
        depth_grid = flip(grid(dep, cols, rows))
        mask_sd = sdf2(flip(grid(views[name][1], cols, rows)))
        sdf = press_relief(sdf, name, depth_grid, mask_sd, a.relief * a.res, a.relief_width * a.res)
        relief_used.append(name)

    pad = 4
    vol = np.pad(sdf, pad, constant_values=20.0)
    vol = ndimage.gaussian_filter(vol, a.smooth)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.0, spacing=(vs, vs, vs))
    verts -= pad * vs
    labels, n = ndimage.label(vol < 0)
    fragments = n - 1

    verts -= [0, 0, verts[:, 2].min()]
    verts /= verts[:, 2].max()
    verts[:, 0] -= (verts[:, 0].min() + verts[:, 0].max()) / 2
    verts[:, 1] -= (verts[:, 1].min() + verts[:, 1].max()) / 2
    verts *= a.size / np.linalg.norm(verts.max(0) - verts.min(0))
    W, D, H = (float(verts[:, i].max() - verts[:, i].min()) for i in range(3))

    # how every photo lands on the finished shape:  u = pos.u_axis * su + ou,  v likewise
    tables = {
        "front": ((0, -1, 0), (1, 0, 0), (0, 0, 1), W, H, 0.5, 0.0),
        "back": ((0, 1, 0), (-1, 0, 0), (0, 0, 1), W, H, 0.5, 0.0),
        "right": ((1, 0, 0), (0, 1, 0), (0, 0, 1), D, H, 0.5, 0.0),
        "left": ((-1, 0, 0), (0, -1, 0), (0, 0, 1), D, H, 0.5, 0.0),
        "top": ((0, 0, 1), (1, 0, 0), (0, 1, 0), W, D, 0.5, 0.5),
        "bottom": ((0, 0, -1), (1, 0, 0), (0, -1, 0), W, D, 0.5, 0.5),
    }
    rig = {"W": W, "D": D, "H": H, "top_used": has_top, "views": {}}
    for name in views:
        if name in tables:
            facing, u_axis, v_axis, eu, ev, ou, ov = tables[name]
            su, sv = 1 / eu, 1 / ev
        else:
            yaw = math.radians(CORNERS[name])
            u_axis = (math.cos(yaw), math.sin(yaw), 0)
            facing = (math.sin(yaw), -math.cos(yaw), 0)
            v_axis = (0, 0, 1)
            p = verts @ np.array(u_axis)
            su, ou = 1 / float(p.max() - p.min()), -float(p.min()) / float(p.max() - p.min())
            sv, ov = 1 / H, 0.0
        rig["views"][name] = {
            "image": f"{name}_proj.png", "turned": int(rot[name]),
            "facing": list(facing), "u_axis": list(u_axis), "v_axis": list(v_axis),
            "su": su, "ou": ou, "sv": sv, "ov": ov,
        }

    # how well does the shape's silhouette match each photo's outline?
    final = vol[pad:-pad, pad:-pad, pad:-pad] < 0
    qa = {"views": {}, "fragments": int(fragments), "flags": []}
    for name in AXIS_VIEWS:
        if name not in views:
            continue
        axis = RELIEF[name][0]
        cols, rows = {1: (nx, nz), 0: (ny, nz), 2: (nx, ny)}[axis]
        target = RELIEF[name][2](grid(views[name][1], cols, rows)) > 127
        got = project(final, name)
        iou = float((target & got).sum() / max(1, (target | got).sum()))
        qa["views"][name] = {"iou": round(iou, 3), "turned": int(rot[name]), "orient_margin": round(float(conf[name]), 3)}
        if iou < LOW_IOU:
            qa["flags"].append(f"{name}: outline only matches {iou:.0%}; photos may be turned or differently framed")
        if conf[name] < orient.LOW_CONFIDENCE and name != "front":
            qa["flags"].append(f"{name}: orientation is a close call ({rot[name]} deg); check it, or set overrides.json")
    if fragments:
        qa["flags"].append(f"{fragments} loose fragment(s) in the carved shape")
    qa["relief_views"], qa["corner_views"] = relief_used, used_corners

    with open(os.path.join(d, "rock.obj"), "w") as f:
        for x, y, z in verts:
            f.write(f"v {x:.5f} {y:.5f} {z:.5f}\n")
        for t1, t2, t3 in faces + 1:
            f.write(f"f {t1} {t2} {t3}\n")
    json.dump(rig, open(os.path.join(d, "rig.json"), "w"), indent=1)
    json.dump(qa, open(os.path.join(d, "qa.json"), "w"), indent=1)
    turned = [f"{n} {rot[n]}" for n in views if rot[n]]
    ious = " ".join(f"{n}:{v['iou']:.2f}" for n, v in qa["views"].items())
    print(f"{os.path.basename(os.path.normpath(d))}: W {W:.2f} D {D:.2f} H {H:.2f}, {len(faces)} faces, side={side},"
          f" top={'yes' if has_top else 'no'}, turned: {', '.join(turned) or 'none'} | outline match {ious}")
    for flag in qa["flags"]:
        print("  warning:", flag)


if __name__ == "__main__":
    main()
