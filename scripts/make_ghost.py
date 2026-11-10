"""
After-kiln "ghost" of a finished rock: the same shape as a faint clear glass
shell, with a fine wireframe of its surface drawn over it.

  Blender -b --factory-startup --python make_ghost.py -- in.glb out.glb

  * glass: the rock's mesh, near-colourless, mostly see-through and glossy
  * wire:  an irregular net over the rock's real surface: the shape is
           rebuilt on a grid about WIRE_CELL apart, every point nudged at
           random, some edges dissolved (mixed cell sizes and shapes), then
           snapped back onto the rock so every line follows its bumps and
           dips; then turned into thin struts
"""

import argparse
import bmesh
import bpy
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_common as bc  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("source")
p.add_argument("out")
p.add_argument("--wire-cell", type=float, default=0.06, help="rough size of the net's cells")
p.add_argument("--jitter", type=float, default=0.45, help="how far each point is nudged, share of a cell")
p.add_argument("--dissolve", type=float, default=0.3, help="share of edges removed")
p.add_argument("--wire-thickness", type=float, default=0.0035, help="strut thickness")
p.add_argument("--glass-alpha", type=float, default=0.3, help="0 invisible, 1 solid")
p.add_argument("--glass-faces", type=int, default=6000, help="the glass is smooth, so it needs few faces")
p.add_argument("--no-draco", action="store_true", help="skip mesh compression")
args = p.parse_args(bc.script_args())
SRC, OUT = os.path.abspath(args.source), os.path.abspath(args.out)
WIRE_CELL, JITTER, DISSOLVE = args.wire_cell, args.jitter, args.dissolve
WIRE_THICKNESS, GLASS_ALPHA = args.wire_thickness, args.glass_alpha

scene = bpy.context.scene
layer = bpy.context.view_layer
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.import_scene.gltf(filepath=SRC)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in bpy.data.objects:
    o.select_set(o in meshes)
layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
rock = layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
random.seed(7)


def keep_largest(obj):
    """Drop small detached fragments (they make stray lines)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    seen, parts = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        part, stack = [], [f]
        seen.add(f)
        while stack:
            g = stack.pop()
            part.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        parts.append(part)
    parts.sort(key=len, reverse=True)
    small = [f for part in parts[1:] for f in part]
    if small:
        bmesh.ops.delete(bm, geom=small, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()



def material(name, color, alpha, roughness):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Alpha"].default_value = alpha
    b.inputs["Roughness"].default_value = roughness
    b.inputs["Metallic"].default_value = 0.0
    if alpha < 1:                             # exported as a see-through (blend) material
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = "BLENDED"   # Blender 4.2+
        else:
            m.blend_method = "BLEND"
    return m


apply_modifiers = bc.apply_modifiers


# glass shell: the rock's own surface, smooth and glossy
glass = rock
glass.name = "Glass"
glass.data.materials.clear()
glass.data.materials.append(material("Glass", (0.86, 0.93, 0.95, 1), GLASS_ALPHA, 0.05))
for p in glass.data.polygons:
    p.use_smooth = True

# wireframe: a simplified copy, its edges turned into struts
wire = glass.copy()
wire.data = glass.data.copy()
wire.name = "Wire"
scene.collection.objects.link(wire)
grid = wire.modifiers.new("Grid", "REMESH")         # clean, closed surface on a grid
grid.mode = "VOXEL"
grid.voxel_size = WIRE_CELL
apply_modifiers(wire)
keep_largest(wire)                                   # the grid is one joined surface, so fragments are real ones
bm = bmesh.new()
bm.from_mesh(wire.data)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
for v in bm.verts:                                   # nudge every point: no two cells alike
    v.co += v.normal.cross((random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1))) * WIRE_CELL * JITTER
edges = [e for e in bm.edges if not e.is_boundary and random.random() < DISSOLVE]
bmesh.ops.dissolve_edges(bm, edges=edges, use_verts=False)   # merge some cells into bigger, odd shapes
bm.to_mesh(wire.data)
bm.free()
# what the net snaps onto: the real surface, joined across its texture seams and
# with loose fragments removed (otherwise stray points fly off to them)
target = glass.copy()
target.data = glass.data.copy()
scene.collection.objects.link(target)
bm = bmesh.new()
bm.from_mesh(target.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
bm.to_mesh(target.data)
bm.free()
keep_largest(target)
hug = wire.modifiers.new("Hug", "SHRINKWRAP")        # back onto the real surface, bumps and all
hug.target = target
hug.wrap_method = "NEAREST_SURFACEPOINT"
apply_modifiers(wire)
bpy.data.objects.remove(target)
wf = wire.modifiers.new("Wire", "WIREFRAME")
wf.thickness = WIRE_THICKNESS
wf.use_even_offset = False      # "even" thickness throws long spikes at the net's sharp corners
apply_modifiers(wire)
wire.data.materials.clear()
wire.data.materials.append(material("Wire", (0.22, 0.23, 0.24, 1), 1.0, 0.6))

# the glass is only a faint shell: weld its texture seams, then thin it out
bm = bmesh.new()
bm.from_mesh(glass.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
bm.to_mesh(glass.data)
bm.free()
keep_largest(glass)
if len(glass.data.polygons) > args.glass_faces:
    thin = glass.modifiers.new("Thin", "DECIMATE")
    thin.ratio = args.glass_faces / len(glass.data.polygons)
    apply_modifiers(glass)
for poly in glass.data.polygons:
    poly.use_smooth = True
while glass.data.uv_layers:
    glass.data.uv_layers.remove(glass.data.uv_layers[0])

for o in layer.objects:
    o.select_set(o in (glass, wire))
bc.export_glb(OUT, draco=not args.no_draco, image_format="NONE", export_texcoords=False)
print("ghost exported", OUT, "glass faces", len(glass.data.polygons), "wire faces", len(wire.data.polygons), f"{os.path.getsize(OUT) // 1024} KB")
