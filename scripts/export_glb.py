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


def select_only(obj):
    for o in layer.objects:
        o.select_set(False)
    obj.select_set(True)
    layer.objects.active = obj


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
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 8
mat = low.data.materials[0]
nodes = mat.node_tree.nodes


def bake(kind, name, noncolor=False, **kw):
    img = bpy.data.images.new(name, TEXTURE_SIZE, TEXTURE_SIZE, alpha=False)
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    target = nodes.new("ShaderNodeTexImage")
    target.image = img
    nodes.active = target                 # Cycles bakes into the active image node
    bpy.ops.object.bake(type=kind, margin=8, use_clear=True, **kw)
    nodes.remove(target)
    img.pack()
    return img


color = bake("DIFFUSE", ROCK + "_color", pass_filter={"COLOR"})
normal = bake("NORMAL", ROCK + "_normal", noncolor=True, normal_space="TANGENT")

# a plain material glTF understands: baked colour + normal map
web = bpy.data.materials.new(ROCK + "_web")
web.use_nodes = True
wn, wl = web.node_tree.nodes, web.node_tree.links
bsdf = wn["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 0.95
tc = wn.new("ShaderNodeTexImage"); tc.image = color
wl.new(tc.outputs["Color"], bsdf.inputs["Base Color"])
tn = wn.new("ShaderNodeTexImage"); tn.image = normal
nm = wn.new("ShaderNodeNormalMap")
wl.new(tn.outputs["Color"], nm.inputs["Color"])
wl.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
low.data.materials.clear()
low.data.materials.append(web)

# 4. export just the web copy
select_only(low)
bpy.ops.export_scene.gltf(
    filepath=OUTPUT,
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_yup=True,
    export_image_format="JPEG",
)
print("exported", OUTPUT)
