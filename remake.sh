#!/bin/zsh
# Remake every rock in a folder of photo sheets as web-ready 3D models.
#
#   ./remake.sh SHEETS_DIR OUT_DIR
#
# SHEETS_DIR  one .png photo sheet per rock (see README: a 2 x 3 grid on white,
#             Front | Left / Right | Back / Top | Bottom, labelled underneath)
# OUT_DIR     where the models go. For a sheet called 05oclock.png you get
#               05oclock.glb        the rock, its photos wrapped round it
#               05oclock_ghost.glb  the same rock as glass + an irregular wireframe
#
# Work files (cutouts, outlines, meshes, previews) go to ./work/<sheet name>/.
# Set BLENDER if Blender isn't in /Applications.

set -e
SHEETS=${1:?usage: ./remake.sh SHEETS_DIR OUT_DIR}
OUT=${2:?usage: ./remake.sh SHEETS_DIR OUT_DIR}
HERE=${0:A:h}
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
mkdir -p "$OUT" "$HERE/work"

for sheet in "$SHEETS"/*.png; do
  name=${${sheet:t}:r}
  work="$HERE/work/$name"
  echo "── $name"
  python3 "$HERE/scripts/cutout_views.py" "$sheet" "$work"
  python3 "$HERE/scripts/build_hull.py" "$work"
  "$BLENDER" -b --factory-startup --python "$HERE/scripts/build_rock.py" -- "$work" "$OUT/$name.glb" 2>&1 | grep -E "exported|Error|Traceback" || true
  "$BLENDER" -b --factory-startup --python "$HERE/scripts/make_ghost.py" -- "$OUT/$name.glb" "$OUT/${name}_ghost.glb" 2>&1 | grep -E "ghost exported|Error|Traceback" || true
done
echo "done: models in $OUT, previews in $HERE/work/*/preview_*.png"
