#!/bin/bash
# Remake every rock in a folder as web-ready 3D models.
#
#   ./remake.sh SOURCE_DIR OUT_DIR
#
# SOURCE_DIR holds, for each rock, either a photo sheet (NAME.png or NAME.jpg)
#            or a subfolder NAME/ of photos called front, back, left, right, top, bottom.
#            A folder that directly holds such photos is treated as one rock.
# OUT_DIR    receives NAME.glb and NAME_ghost.glb.
#
# Work files and each rock's report.png go to ./work/NAME/. One bad rock doesn't stop
# the batch, and models are only replaced after their step has succeeded.
#
# BLENDER=path  Blender 4.2 or newer, if it isn't in /Applications or on the PATH
# RELIEF=1      press hollows in with estimate_depth.py (needs torch + transformers)
# DEPTH_PYTHON  a separate Python that has torch + transformers, if not the main one

set -u -o pipefail
shopt -s nullglob nocaseglob

SOURCE=${1:?usage: ./remake.sh SOURCE_DIR OUT_DIR}
OUT=${2:?usage: ./remake.sh SOURCE_DIR OUT_DIR}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python3}

if [ -z "${BLENDER:-}" ]; then
  BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
  [ -x "$BLENDER" ] || BLENDER=$(command -v blender || true)
fi
if [ ! -x "$BLENDER" ]; then
  echo "Blender not found; set BLENDER=/path/to/blender" >&2
  exit 2
fi
mkdir -p "$OUT" "$HERE/work"

run_blender() {  # log, script, args...
  local log=$1 script=$2
  shift 2
  "$BLENDER" -b --factory-startup --python-exit-code 1 --python "$HERE/scripts/$script" -- "$@" >>"$log" 2>&1
}

make_rock() {  # source, name
  local src=$1 name=$2 work="$HERE/work/$2"
  mkdir -p "$work"
  local log="$work/build.log"
  : >"$log"
  "$PY" "$HERE/scripts/cutout_views.py" "$src" "$work" || return 1
  if [ "${RELIEF:-0}" = 1 ]; then "${DEPTH_PYTHON:-$PY}" "$HERE/scripts/estimate_depth.py" "$work" || return 1; fi
  "$PY" "$HERE/scripts/build_hull.py" "$work" || return 1
  "$PY" "$HERE/scripts/prepare_textures.py" "$work" || return 1
  run_blender "$log" build_rock.py "$work" "$work/rock.glb" || { tail -n 15 "$log" >&2; return 1; }
  run_blender "$log" make_ghost.py "$work/rock.glb" "$work/ghost.glb" || { tail -n 15 "$log" >&2; return 1; }
  "$PY" "$HERE/scripts/qa_report.py" "$work" || return 1
  mv "$work/rock.glb" "$OUT/$name.glb" && mv "$work/ghost.glb" "$OUT/${name}_ghost.glb"
}

is_photo_folder() {
  local f
  for f in "$1"/front.*; do return 0; done
  return 1
}

made=0
failed=()
try() {
  echo "── $2"
  if make_rock "$1" "$2"; then made=$((made + 1)); else failed+=("$2"); echo "   FAILED: $2" >&2; fi
}

if is_photo_folder "$SOURCE"; then
  try "$SOURCE" "$(basename "$SOURCE" | tr ' ' '_')"
else
  for item in "$SOURCE"/*; do
    if [ -d "$item" ]; then
      is_photo_folder "$item" && try "$item" "$(basename "$item" | tr ' ' '_')"
    else
      case "$item" in
        *.png|*.jpg|*.jpeg) base=$(basename "$item"); try "$item" "${base%.*}" ;;
      esac
    fi
  done
fi

if [ "$made" -eq 0 ] && [ "${#failed[@]}" -eq 0 ]; then
  echo "no rocks found in $SOURCE" >&2
  exit 2
fi
echo "done: $made made, ${#failed[@]} failed. Models in $OUT, reports in $HERE/work/*/report.png"
[ "${#failed[@]}" -eq 0 ] || { echo "failed: ${failed[*]}" >&2; exit 1; }
