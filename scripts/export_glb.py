"""
Export a procedural rock to a web-ready .glb
--------------------------------------------
glTF can't carry Blender modifiers or procedural shader nodes, so this:
  1. makes a copy of the rock with every modifier applied (cuts, remesh,
     smoothing, displacement), then thins it out with Decimate,
  2. UV-unwraps the copy,
  3. bakes the procedural material into a colour texture and a normal map,
  4. exports only that copy, with the baked textures, as one .glb.

In Blender: run the rock's generator script first, then this one
(Scripting tab > Open > Run Script). It writes to OUTPUT below.

From a terminal (no window), e.g.:
  Blender -b --factory-startup --python tuff_generator.py --python export_glb.py -- out.glb 1024 [ObjectName]
"""

import bpy
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_common as bc  # noqa: E402

# ---------------------------------------------------------------- settings
ROCK = "TuffRock"                         # the object to export
OUTPUT = os.path.abspath("rock.glb")      # when run inside Blender without arguments
TEXTURE_SIZE = 1024                       # baked texture resolution (px)
DECIMATE = 0.3                            # keep this share of the faces (smaller file)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if argv:
    OUTPUT = os.path.abspath(argv[0])
if len(argv) > 1:
    TEXTURE_SIZE = int(argv[1])
if len(argv) > 2 and argv[2] != "--":
    ROCK = argv[2]

scene = bpy.context.scene
layer = bpy.context.view_layer
src = bpy.data.objects[ROCK]


select_only = bc.select_only


def bake_mesh(obj):
    """The object's mesh with all its modifiers applied."""
    dg = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(obj.evaluated_get(dg))


# 1. copy with modifiers applied, then decimated
low = bpy.data.objects.new(ROCK + "_web", bake_mesh(src))
scene.collection.objects.link(low)
low.matrix_world = src.matrix_world.copy()
dec = low.modifiers.new("Decimate", "DECIMATE")
dec.ratio = scene.get("decimate", DECIMATE)   # a generator script can ask for more detail
mesh = bake_mesh(low)
low.modifiers.clear()
old, low.data = low.data, mesh
bpy.data.meshes.remove(old)
src.hide_render = True
print(f"web mesh: {len(low.data.polygons)} faces")

# 2. UV unwrap
select_only(low)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.003)
bpy.ops.object.mode_set(mode="OBJECT")

# 3. bake colour and surface detail from the procedural material
bc.setup_bake()
nodes = low.data.materials[0].node_tree.nodes
color = bc.bake(nodes, "DIFFUSE", ROCK + "_color", TEXTURE_SIZE, pass_filter={"COLOR"})
normal = bc.bake(nodes, "NORMAL", ROCK + "_normal", TEXTURE_SIZE, noncolor=True, normal_space="TANGENT")
low.data.materials.clear()
low.data.materials.append(bc.web_material(ROCK + "_web", color, normal, 0.95))

# 4. export just the web copy
select_only(low)
bc.export_glb(OUTPUT)
print("exported", OUTPUT)
