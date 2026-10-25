---
name: rock-remaker
description: Turn photo sheets of rocks (six labelled views on white) into web-ready 3D models (.glb) — outline carving plus projected photographs, baked in Blender — and an after-kiln "ghost" version (glass + irregular wireframe). Use when someone wants to rebuild a physical rock, stone or similar object as a 3D model from a few photos, add a new rock to the Metamorphosis clock, or adjust how the remade rocks or ghosts look.
---

# Rock Remaker

Rebuild a physical rock as a 3D model from a sheet of photographs. Everything runs
headless: Python for the image work, Blender (`-b --factory-startup`) for the rest.

## Inputs

A **photo sheet** per rock: a PNG, pure white background, 2 × 3 grid —
Front | Left / Right | Back / Top | Bottom — each photo above its label. Missing
cells are fine; front plus one side is the minimum.

Requirements: Blender 4.x (default path `/Applications/Blender.app/Contents/MacOS/Blender`,
override with `BLENDER`), Python 3 with numpy, scipy, pillow, scikit-image.

## Run

```bash
./remake.sh SHEETS_DIR OUT_DIR
```

Per sheet `NAME.png` → `OUT_DIR/NAME.glb` + `OUT_DIR/NAME_ghost.glb`, work files
in `work/NAME/`. Then **look at the previews** (`work/NAME/preview_front.png`,
`preview_angle.png`) next to the sheet before calling it done — render the
comparison side by side and actually view it.

## Pipeline (one script per stage)

1. `scripts/cutout_views.py sheet.png work/NAME` — per view: `<view>.png` (photo,
   background filled from rock edge colours) and `<view>_mask.png`. Rock = any pixel
   with darkness or chroma > 8 (sheets are pure white — check the paper is 255 before
   loosening/tightening). Opening + largest component + hole fill. Grid bands are in
   `ROWS` (shares of sheet height) if a layout differs.
2. `scripts/build_hull.py work/NAME` — orients views (side turned 90° when its width
   matches the front height better, by a `MARGIN`), carves a voxel hull from
   front ∩ side ∩ top (rounded section without top), Gaussian-smooths, marching cubes,
   scales to `SIZE` (bbox diagonal 1.306 = the tuff), writes `rock.obj` + `rig.json`.
3. `scripts/build_rock.py -- work/NAME out.glb` (Blender) — decimate, light displace,
   UV unwrap, project each photo along its axis weighted by normal·direction⁴, bump
   from luminance, bake DIFFUSE colour + tangent NORMAL, export GLB (JPEG textures),
   render previews.
4. `scripts/make_ghost.py -- in.glb out_ghost.glb` (Blender) — glass shell (alpha
   0.3, BLEND) + wire net: voxel remesh at `WIRE_CELL`, keep largest part,
   triangulate, jitter in tangent plane, dissolve ~30% edges, shrinkwrap onto a
   welded/cleaned copy of the surface, wireframe modifier.

Hand-built rocks: `scripts/tuff_generator.py` / `scripts/lava_generator.py`, then
`scripts/export_glb.py -- out.glb TEXSIZE ObjectName` (applies modifiers, bakes
procedural material — glTF can't carry either otherwise).

## Lessons (check these first when something looks wrong)

- **Pale parts missing** → threshold too strict; the paper is pure white.
- **White fringe / pale streaks at edges** → background fill must sample from an
  eroded core, not the anti-aliased rim.
- **Pale glassy streaks on top** → no top photo; the fallback borrows front/back.
- **Sizes wildly different** → normalise the bbox diagonal, not the height.
- **Exported .glb looks nothing like Blender** → modifiers weren't applied or the
  material is procedural; use `export_glb.py`.
- **Imported glTF meshes are split at UV seams** → weld (`remove_doubles`) before
  any connectivity work such as "keep largest part".
- **Long spikes in the wireframe** → `use_even_offset` on irregular nets; keep it off.
- **Blender renders look washed out** → `view_transform = "Standard"`.
- Say plainly what is inferred: hidden sides, mismatched views, shadows in cutouts.

## Using the models on the web

`<model-viewer>` (CDN) with a fixed camera distance (e.g. `camera-orbit="0deg 80deg 5.2m"`)
keeps equally sized rocks equally sized. Pages opened from `file://` can't fetch
`.glb`; serve over HTTP or pack models as base64 into a script.
