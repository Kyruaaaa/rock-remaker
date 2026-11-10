"""
Put each photo beside the matching render, with the outline match, in report.png.

    python3 qa_report.py rock_dir
"""

import json
import os
import sys

from PIL import Image, ImageDraw

TILE = 260
VIEWS = ("front", "right", "back", "left", "top")


def tile(path):
    canvas = Image.new("RGB", (TILE, TILE), (255, 255, 255))
    if os.path.exists(path):
        im = Image.open(path).convert("RGB")
        im.thumbnail((TILE - 12, TILE - 12))
        canvas.paste(im, ((TILE - im.width) // 2, (TILE - im.height) // 2))
    return canvas


def main(d):
    qa = json.load(open(os.path.join(d, "qa.json")))
    extra = ("preview_angle.png", "preview_clay.png", "preview_clay_back.png")
    sheet = Image.new("RGB", (TILE * (len(VIEWS) + 1), TILE * 2 + 40 + 18 * (len(qa["flags"]) + 1)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for i, name in enumerate(VIEWS):
        sheet.paste(tile(os.path.join(d, f"{name}_tex.png")), (i * TILE, 22))
        sheet.paste(tile(os.path.join(d, f"preview_{name}.png")), (i * TILE, 22 + TILE))
        info = qa["views"].get(name)
        label = f"{name}  outline {info['iou']:.0%}" if info else f"{name}  (inferred)"
        draw.text((i * TILE + 8, 5), label, fill=(0, 0, 0))
    for j, name in enumerate(extra[:2]):
        sheet.paste(tile(os.path.join(d, name)), (len(VIEWS) * TILE, 22 + j * TILE))
    y = 2 * TILE + 30
    draw.text((8, y), "Warnings:" if qa["flags"] else "No warnings.", fill=(160, 0, 0) if qa["flags"] else (0, 110, 0))
    for flag in qa["flags"]:
        y += 18
        draw.text((8, y), flag, fill=(160, 0, 0))
    sheet.save(os.path.join(d, "report.png"))
    print("report:", os.path.join(d, "report.png"))


if __name__ == "__main__":
    main(sys.argv[1])
