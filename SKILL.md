---
name: rock-remaker
description: Turn photo sheets of rocks (six labelled views on white) into web-ready 3D models (.glb) — outline carving plus projected photographs, baked in Blender — and an after-kiln "ghost" version (glass + irregular wireframe). Use when someone wants to rebuild a physical rock, stone or similar object as a 3D model from a few photos, add a new rock to the Metamorphosis clock, or adjust how the remade rocks or ghosts look.
---

# Rock Remaker

Rebuild a physical rock as a 3D model from a sheet of photographs. Everything runs
headless: Python for the image work, Blender (`-b --factory-startup`) for the rest.

## Inputs

Either a **photo sheet** (PNG or JPG, pure white, 2 × 3 grid: Front | Left / Right |
Back / Top | Bottom), or a **folder of photos** named front, back, left, right, top,
bottom (any case), optionally front_left, front_right, back_left, back_right. Hand-held
photos are fine. Front plus one side is the minimum.

Requirements: Blender 4.2+ (override with `BLENDER`), Python 3 with `requirements.txt`.

## Run

```bash
./remake.sh SOURCE_DIR OUT_DIR
```

Then **look at `work/NAME/report.png`** and read its warnings before calling it done.
Wrong turn → `work/NAME/overrides.json`: `{"rotate": {"top": 180}}`, then rerun from
`build_hull.py` onward. `RELIEF=1` adds depth-based hollows (needs torch, transformers).
`MATTE=rembg` uses a trained background remover for cluttered or in-focus rooms.
`ROCK_ARGS="--sparkle 0.12 --texture 2048"` adds glinting mica flakes for shiny rocks.

## Pipeline (one script per stage)

1. `cutout_views.py SOURCE work/NAME` — outlines and filled photos.
2. `build_hull.py work/NAME` — `orient.py` picks each turn; relaxed outline volumes →
   `rock.obj`, `rig.json`, `qa.json`.
3. `prepare_textures.py work/NAME` — lighting, exposure match, height maps, inferred ends;
   a missing back or side borrows the opposite photo.
4. `build_rock.py -- work/NAME out.glb` (Blender) — bake, export, previews incl. clay.
5. `make_ghost.py -- in.glb out_ghost.glb` (Blender) — glass shell + wire net.
6. `qa_report.py work/NAME` — `report.png`.

Hand-built rocks: `tuff_generator.py` / `lava_generator.py`, then
`export_glb.py -- out.glb TEXSIZE ObjectName`.

## Lessons (check these first when something looks wrong)

- **Pale parts missing** → threshold too strict; the paper is pure white.
- **White fringe / pale streaks at edges** → background fill must sample from an
  eroded core, not the anti-aliased rim.
- **Nub or crease on one side, odd colour on it** → a finger is still in the outline;
  check `<view>_mask.png`.
- **Grooves or ribs in the clay preview** → raise `--soften` in `build_hull.py`.
- **Pale parts missing on a hand-held photo** → try `--matte rembg` (`MATTE=rembg`).
- **A tail or stick hanging off the rock** → the remover kept a pole or cable;
  rembg cutouts trim anything thinner than about an eighth of the rock.
- **Pink patches on a green or grey rock** → a pale palm passed the skin filter;
  rerun with `SKIN_A=5` (the default, 11, is safe for reddish rocks).
- **Mica, glitter or a wet-looking shine** → `--sparkle`. Keep flakes non-metallic:
  metallic flakes show as dark dots wherever they reflect a dark room.
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
