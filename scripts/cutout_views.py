"""
Cut the six labelled views out of a rock photo sheet.

A sheet is a 2 x 3 grid on white (Front | Left / Right | Back / Top | Bottom)
with the label under each photo. For every view that has a photo this writes
  <out>/<view>.png       the photo, cropped to the rock, background filled
                         with the rock's own edge colours (no white halo
                         when it is projected onto the 3D model)
  <out>/<view>_mask.png  white where the rock is
and <out>/views.json with each view's size.

    python3 cutout_views.py sheet.png out_dir
"""

import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

VIEWS = {  # name: (column, row) on the sheet
    "front": (0, 0), "left": (1, 0),
    "right": (0, 1), "back": (1, 1),
    "top": (0, 2), "bottom": (1, 2),
}
# vertical bands that hold the photos (as a share of the sheet height),
# stopping above each row's labels
ROWS = [(0.0, 0.262), (0.300, 0.580), (0.620, 0.905)]


def cut(sheet, col, row):
    h, w = sheet.shape[:2]
    y0, y1 = int(ROWS[row][0] * h), int(ROWS[row][1] * h)
    x0, x1 = col * w // 2, (col + 1) * w // 2
    cell = sheet[y0:y1, x0:x1]
    rgb = cell[..., :3].astype(np.float32)
    # rock = anything not pure white (the sheets have a pure white background)
    darkness = 255 - rgb.min(axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    mask = (darkness > 8) | (chroma > 8)
    if cell.shape[2] == 4:
        mask &= cell[..., 3] > 128
    # clean up: drop dust and speckle, keep the one big piece, fill holes
    mask = ndimage.binary_opening(mask, iterations=4)
    labels, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    biggest = int(np.argmax(sizes)) + 1
    if sizes[biggest - 1] < 0.002 * mask.size:
        return None
    mask = labels == biggest
    mask = ndimage.binary_closing(mask, iterations=6)
    mask = ndimage.binary_fill_holes(mask)
    ys, xs = np.nonzero(mask)
    t, b, l, r = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    mask = mask[t:b, l:r]
    photo = cell[t:b, l:r, :3].copy()
    # fill the background (and the rock's pale anti-aliased rim) with the
    # colour of the nearest pixel a little inside the rock
    core = ndimage.binary_erosion(mask, iterations=8)
    if not core.any():
        core = mask
    _, (iy, ix) = ndimage.distance_transform_edt(~core, return_indices=True)
    photo = photo[iy, ix]
    return photo, mask


def main(sheet_path, out):
    os.makedirs(out, exist_ok=True)
    sheet = np.asarray(Image.open(sheet_path).convert("RGBA"))
    info = {}
    for name, (col, row) in VIEWS.items():
        res = cut(sheet, col, row)
        if res is None:
            continue
        photo, mask = res
        Image.fromarray(photo).save(os.path.join(out, f"{name}.png"))
        Image.fromarray((mask * 255).astype(np.uint8)).save(os.path.join(out, f"{name}_mask.png"))
        info[name] = {"w": int(mask.shape[1]), "h": int(mask.shape[0])}
    with open(os.path.join(out, "views.json"), "w") as f:
        json.dump(info, f, indent=1)
    print(os.path.basename(sheet_path), "->", ", ".join(f"{k} {v['w']}x{v['h']}" for k, v in info.items()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
