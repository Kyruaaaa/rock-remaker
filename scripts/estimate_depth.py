"""
Optional: estimate a depth map from each photo, so build_hull.py can press real
hollows into the rock. Writes <view>_depth.png next to each cut-out view.

Needs:  pip install torch transformers
The first run downloads the Depth Anything V2 Small model (about 100 MB).

    python3 estimate_depth.py rock_dir
"""

import json
import os
import sys

from PIL import Image


def main(d):
    try:
        from transformers import pipeline
    except ImportError:
        sys.exit("estimate_depth.py needs torch and transformers (pip install torch transformers)")
    estimate = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf")
    for name in json.load(open(os.path.join(d, "views.json"))):
        photo = Image.open(os.path.join(d, f"{name}.png")).convert("RGB")
        depth = estimate(photo)["depth"].convert("L").resize(photo.size, Image.BILINEAR)
        depth.save(os.path.join(d, f"{name}_depth.png"))
        print("depth:", name)


if __name__ == "__main__":
    main(sys.argv[1])
