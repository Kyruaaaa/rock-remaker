"""Pipeline tests on a synthetic rock with a known shape (no Blender needed)."""

import json
import os
import sys

import numpy as np
import pytest
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_hull  # noqa: E402
import cutout_views  # noqa: E402
import orient  # noqa: E402
import prepare_textures  # noqa: E402


def blob(n=96):
    """A lumpy, wedge-shaped solid: bigger at the top, off-centre bulge."""
    x, y, z = np.meshgrid(*[np.linspace(-1, 1, n)] * 3, indexing="ij")
    r = (x / (0.45 + 0.2 * z)) ** 2 + (y / (0.3 + 0.15 * z)) ** 2 + (z / 0.92) ** 2
    bump = 0.5 * np.exp(-(((x - 0.3) ** 2 + (z - 0.4) ** 2) / 0.05))
    return r - bump < 1


def views_of(solid, rng=np.random.default_rng(3)):
    """Fake photos: outlines from each side, with a colour gradient along the height."""
    p = {
        "front": solid.any(axis=1).T[::-1],
        "back": solid.any(axis=1).T[::-1][:, ::-1],
        "right": solid.any(axis=0).T[::-1],
        "left": solid.any(axis=0).T[::-1][:, ::-1],
        "top": solid.any(axis=2).T[::-1],
        "bottom": solid.any(axis=2).T,
    }
    out = {}
    for name, m in p.items():
        ys, xs = np.nonzero(m)
        m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        g = np.linspace(40, 220, m.shape[0])[:, None] * np.ones(m.shape)
        rgb = np.stack([g, 255 - g, 120 + 40 * np.sin(g / 15)], axis=2) + rng.normal(0, 4, m.shape + (3,))
        out[name] = (np.clip(rgb, 0, 255).astype(np.uint8), m)
    return out


def write(d, views):
    os.makedirs(d, exist_ok=True)
    info = {}
    for n, (rgb, m) in views.items():
        Image.fromarray(rgb).save(os.path.join(d, f"{n}.png"))
        Image.fromarray((m * 255).astype(np.uint8)).save(os.path.join(d, f"{n}_mask.png"))
        info[n] = {"w": m.shape[1], "h": m.shape[0]}
    json.dump(info, open(os.path.join(d, "views.json"), "w"))


def test_upright_views_stay_upright():
    rot, _ = orient.choose(views_of(blob()))
    assert all(v == 0 for k, v in rot.items() if k not in ("top", "bottom"))


@pytest.mark.parametrize("deg", [90, 180, 270])
def test_turned_back_view_is_recovered(deg):
    v = views_of(blob())
    rgb, m = v["back"]
    v["back"] = (np.rot90(rgb, deg // 90).copy(), np.rot90(m, deg // 90).copy())
    rot, _ = orient.choose(v)
    assert rot["back"] == deg


def test_side_photographed_at_double_scale_is_not_turned():
    v = views_of(blob())
    rgb, m = v["right"]
    size = (m.shape[1] * 2, m.shape[0] * 2)
    v["right"] = (np.asarray(Image.fromarray(rgb).resize(size)),
                  np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize(size)) > 127)
    rot, _ = orient.choose(v)
    assert rot["right"] == 0


def test_shape_matches_outlines(tmp_path):
    d = str(tmp_path / "rock")
    write(d, views_of(blob()))
    build_hull.main([d])
    qa = json.load(open(os.path.join(d, "qa.json")))
    assert qa["fragments"] == 0
    assert all(v["iou"] > build_hull.LOW_IOU for v in qa["views"].values())


def test_depth_map_only_removes_material(tmp_path):
    d = str(tmp_path / "rock")
    write(d, views_of(blob()))
    build_hull.main([d])
    before = os.path.getsize(os.path.join(d, "rock.obj"))
    iou_before = json.load(open(os.path.join(d, "qa.json")))["views"]["front"]["iou"]
    w, h = Image.open(os.path.join(d, "front.png")).size
    yy, xx = np.mgrid[0:h, 0:w]
    dent = 255 * (1 - np.exp(-(((xx - w / 2) ** 2 + (yy - h / 2) ** 2) / (0.03 * w * h))))
    Image.fromarray(dent.astype(np.uint8)).save(os.path.join(d, "front_depth.png"))
    build_hull.main([d])
    qa = json.load(open(os.path.join(d, "qa.json")))
    assert qa["relief_views"] == ["front"]
    assert qa["views"]["front"]["iou"] >= iou_before - 0.02   # the outline is left alone
    assert os.path.getsize(os.path.join(d, "rock.obj")) != before


def test_corner_view_carves_without_breaking_the_outlines(tmp_path):
    d = str(tmp_path / "rock")
    solid = blob()
    v = views_of(solid)
    turned = ndimage.rotate(solid.astype(np.float32), 45, axes=(0, 1), reshape=True, order=1) > 0.5
    m = turned.any(axis=1).T[::-1]
    ys, xs = np.nonzero(m)
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    v["front_right"] = (np.full(m.shape + (3,), 128, np.uint8), m)
    write(d, v)
    build_hull.main([d])
    qa = json.load(open(os.path.join(d, "qa.json")))
    assert qa["corner_views"] == ["front_right"]
    assert all(x["iou"] > build_hull.LOW_IOU for x in qa["views"].values())
    assert "front_right" in json.load(open(os.path.join(d, "rig.json")))["views"]


def test_zero_relief_changes_nothing():
    sd = build_hull.sdf2((np.hypot(*np.mgrid[-30:31, -30:31]) < 20).astype(np.uint8) * 255)
    vol = np.stack([sd] * 40, axis=1)
    before = vol.copy()
    out = build_hull.press_relief(vol, "front", np.full(sd.shape, 200, np.uint8), sd, 0.0, 12)
    assert np.allclose(out, before)


def test_missing_side_view_is_a_clear_error(tmp_path):
    d = str(tmp_path / "rock")
    v = views_of(blob())
    write(d, {"front": v["front"]})
    with pytest.raises(SystemExit, match="side view"):
        build_hull.main([d])


def test_top_is_inferred_when_missing(tmp_path):
    d = str(tmp_path / "rock")
    v = views_of(blob())
    write(d, {k: v[k] for k in ("front", "right")})
    build_hull.main([d])
    prepare_textures.main([d])
    rig = json.load(open(os.path.join(d, "rig.json")))
    assert rig["views"]["top"]["inferred"] and rig["views"]["bottom"]["inferred"]


def test_missing_back_borrows_the_front_photo(tmp_path):
    d = str(tmp_path / "rock")
    v = views_of(blob())
    write(d, {k: v[k] for k in ("front", "right", "left", "top")})
    build_hull.main([d])
    prepare_textures.main([d])
    views = json.load(open(os.path.join(d, "rig.json")))["views"]
    assert views["back"]["inferred"] and views["back"]["image"] == views["front"]["image"]
    assert views["back"]["facing"] == [-x for x in views["front"]["facing"]]
    assert not views["right"].get("inferred")


def test_thin_pole_is_trimmed_off_the_rock():
    yy, xx = np.mgrid[0:400, 0:300]
    rock = (xx - 150) ** 2 / 90 ** 2 + (yy - 150) ** 2 / 120 ** 2 < 1
    pole = (abs(xx - 160) < 8) & (yy > 200)
    out = cutout_views.trim_spurs(rock | pole)
    assert not out[300:, :].any()                          # the pole is gone
    assert out.sum() > 0.97 * rock.sum()                   # the rock is kept


def test_skin_floor_can_be_lowered_for_pale_hands(monkeypatch):
    pale_palm = np.array([[[75.0, 8.0, 9.0]]], np.float32)   # L*, a*, b*
    assert not cutout_views.skin_mask(pale_palm).any()
    monkeypatch.setenv("SKIN_A", "5")
    assert cutout_views.skin_mask(pale_palm).all()


def test_white_background_fill_has_no_white(tmp_path):
    rgb = np.full((300, 300, 3), 255, np.uint8)
    yy, xx = np.mgrid[0:300, 0:300]
    m = (xx - 150) ** 2 + (yy - 150) ** 2 < 100 ** 2
    rgb[m] = (90, 80, 70)
    mask = cutout_views.white_matte(rgb)
    photo, cropped = cutout_views.finish(rgb, mask)
    assert photo.min(axis=2).max() < 120
    assert abs(cropped.sum() - m.sum()) < 0.05 * m.sum()


def test_cell_touching_the_edge_is_not_clipped():
    m = np.zeros((200, 200), bool)
    m[0:150, 40:160] = True
    cleaned = cutout_views.clean(m)
    assert cleaned[0, 100]
