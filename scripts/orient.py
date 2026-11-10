"""
Work out how each photo is turned, without assuming the photos share a scale.

Each view may be turned 0/90/180/270 degrees clockwise. Evidence, strongest first:
  * opposite views are mirror images of each other (front/back, left/right),
  * neighbouring views show the same colours along the edge they share,
  * a top view fixes the rock's width-to-depth ratio,
  * a narrow end usually stays narrow from every side (width profiles),
  * photos are probably at a similar scale,
  * people mostly photograph a rock upright (a small cost for any turn).

Corner views (front_left and so on) are assumed upright.
"""

import itertools
import math

import numpy as np
from PIL import Image

TURNS = (0, 90, 180, 270)
WORK_SIZE = 256        # views are compared at this size
LOW_CONFIDENCE = 0.08  # best score must beat the runner-up by this much
TURN_COST = {0: 0.0, 90: 0.12, 180: 0.3, 270: 0.12}   # evidence needed to believe a turn


def turn(a, deg):
    return np.rot90(a, -deg // 90)


def shrink(rgb, mask):
    scale = WORK_SIZE / max(mask.shape)
    size = (max(8, round(mask.shape[1] * scale)), max(8, round(mask.shape[0] * scale)))
    small = np.asarray(Image.fromarray(rgb).resize(size, Image.BILINEAR)).astype(np.float32)
    m = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize(size, Image.BILINEAR)) > 127
    return small, m


def _to_left_edge(a, edge):
    """Rearrange so that `edge` is column 0, keeping the shared axis along rows."""
    if edge == "l":
        return a
    if edge == "r":
        return a[:, ::-1]
    if edge == "t":
        return np.swapaxes(a, 0, 1)
    if edge == "b":
        return np.swapaxes(a, 0, 1)[:, ::-1]
    raise ValueError(edge)


def rim_profile(rgb, mask, edge, n=48):
    """Colour along one edge of the rock, just inside its outline; n x 3."""
    rgb, mask = _to_left_edge(rgb, edge), _to_left_edge(mask, edge)
    rows, cols = mask.shape
    skip, band = max(1, cols // 40), max(2, cols // 12)
    out = np.full((rows, 3), np.nan, np.float32)
    has = mask.any(axis=1)
    first = mask.argmax(axis=1)
    for r in np.nonzero(has)[0]:
        a = min(cols - 1, first[r] + skip)
        out[r] = rgb[r, a:a + band].mean(axis=0)
    idx = np.linspace(0, rows - 1, n)
    keep = ~np.isnan(out[:, 0])
    if keep.sum() < 4:
        return np.zeros((n, 3), np.float32)
    return np.stack([np.interp(idx, np.nonzero(keep)[0], out[keep, c]) for c in range(3)], axis=1)


def width_profile(mask, across="rows", n=48):
    counts = mask.sum(axis=1 if across == "rows" else 0).astype(np.float32)
    return np.interp(np.linspace(0, len(counts) - 1, n), np.arange(len(counts)), counts)


def corr(a, b):
    a, b = np.ravel(a - a.mean(axis=0)), np.ravel(b - b.mean(axis=0))
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 1e-6 else 0.0


def mirror_match(a, b):
    """How alike outline a and the mirror image of outline b are (bbox-normalised)."""
    h, w = a.shape
    bm = np.asarray(Image.fromarray((b[:, ::-1] * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)) > 127
    iou = (a & bm).sum() / max(1, (a | bm).sum())
    aspect = abs(math.log((a.shape[1] / a.shape[0]) / (b.shape[1] / b.shape[0])))
    return float(iou) - 0.6 * aspect


def _pick(scores):
    ranked = sorted(scores, key=scores.get, reverse=True)
    margin = scores[ranked[0]] - scores[ranked[1]] if len(ranked) > 1 else 1.0
    return ranked[0], margin


def choose(views, overrides=None):
    """views: {name: (rgb, mask)}. Returns ({name: degrees clockwise}, {name: margin})."""
    overrides = overrides or {}
    small = {k: shrink(*v) for k, v in views.items()}
    turned = {k: {t: (turn(r, t), turn(m, t)) for t in TURNS} for k, (r, m) in small.items()}
    rot, conf = {"front": overrides.get("front", 0)}, {"front": 1.0}
    f_rgb, f_mask = turned["front"][rot["front"]]
    fh = views["front"][1].shape[0]
    fw = views["front"][1].shape[1]
    if rot["front"] % 180:
        fw, fh = fh, fw

    def shape(name, t):
        h, w = views[name][1].shape
        return (h, w) if t % 180 else (w, h)

    # back: the mirror image of the front
    if "back" in views:
        if "back" in overrides:
            rot["back"], conf["back"] = overrides["back"], 1.0
        else:
            rot["back"], conf["back"] = _pick({t: mirror_match(f_mask, turned["back"][t][1]) - TURN_COST[t] for t in TURNS})

    # top aspect (if any) tells us width / depth, independent of photo scale
    top_ar = None
    tv = next((n for n in ("top", "bottom") if n in views), None)
    if tv:
        h, w = views[tv][1].shape
        top_ar = w / h

    def side_score(name, t):
        rgb, mask = turned[name][t]
        s = -TURN_COST[t]
        if name == "right":
            s += 0.5 * corr(rim_profile(f_rgb, f_mask, "r"), rim_profile(rgb, mask, "l"))
        else:
            s += 0.5 * corr(rim_profile(f_rgb, f_mask, "l"), rim_profile(rgb, mask, "r"))
        s += 0.25 * corr(width_profile(f_mask), width_profile(mask))
        w, h = shape(name, t)
        s -= 0.6 * abs(math.log(fh / h))               # similar photo scale
        if top_ar is not None:
            wd = (fw / fh) / (w / h)
            s -= 0.8 * min(abs(math.log(wd / top_ar)), abs(math.log(wd * top_ar)))
        if "back" in views:
            b_rgb, b_mask = turned["back"][rot["back"]]
            if name == "right":
                s += 0.25 * corr(rim_profile(rgb, mask, "r"), rim_profile(b_rgb, b_mask, "l"))
            else:
                s += 0.25 * corr(rim_profile(rgb, mask, "l"), rim_profile(b_rgb, b_mask, "r"))
        return s

    sides = [n for n in ("right", "left") if n in views]
    if len(sides) == 2:
        options = {}
        for tr, tl in itertools.product(TURNS, TURNS):
            if overrides.get("right", tr) != tr or overrides.get("left", tl) != tl:
                continue
            options[(tr, tl)] = (side_score("right", tr) + side_score("left", tl)
                                 + 1.2 * mirror_match(turned["right"][tr][1], turned["left"][tl][1]))
        (rot["right"], rot["left"]), margin = _pick(options)
        conf["right"] = conf["left"] = margin
    elif sides:
        name = sides[0]
        options = {t: side_score(name, t) for t in TURNS if overrides.get(name, t) == t}
        rot[name], conf[name] = _pick(options)

    # top and bottom: their width/depth now has a target
    if sides:
        sw, sh = shape(sides[0], rot[sides[0]])
        target = (fw / fh) / (sw / sh)
    else:
        target = None
    for name, f_edge, v_edge in (("top", "t", "b"), ("bottom", "b", "t")):
        if name not in views:
            continue
        options = {}
        for t in TURNS:
            if overrides.get(name, t) != t:
                continue
            rgb, mask = turned[name][t]
            s = 0.5 * corr(rim_profile(f_rgb, f_mask, f_edge), rim_profile(rgb, mask, v_edge)) - TURN_COST[t]
            s += 0.25 * corr(width_profile(f_mask, "cols"), width_profile(mask, "cols"))
            if target is not None:
                w, h = shape(name, t)
                s -= 1.0 * abs(math.log((w / h) / target))
            options[t] = s
        rot[name], conf[name] = _pick(options)

    for name in views:
        rot.setdefault(name, overrides.get(name, 0))
        conf.setdefault(name, 1.0)
    return rot, conf
