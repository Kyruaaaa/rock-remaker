"""
Finish a rock made by build_hull.py and export it as a web-ready .glb.

  1. imports rock.obj, thins it out and adds a little surface irregularity,
  2. colours it by projecting the photos onto it from each side: every
     surface takes the photo that faces it most directly, blending at the
     edges (front photo on the front, top photo on top, and so on),
  3. bakes that into a colour texture, plus a normal map made from the
     photos' light and dark grain so the surface catches light,
  4. exports the .glb and renders two preview images to check against.

    Blender -b --factory-startup --python build_rock.py -- rock_dir out.glb
"""

import bpy
import json
import math
import os
import sys

argv = sys.argv[sys.argv.index("--") + 1:]
ROCK_DIR, OUT = os.path.abspath(argv[0]), os.path.abspath(argv[1])
TEXTURE_SIZE = 1024
TARGET_FACES = 30000
rig = json.load(open(os.path.join(ROCK_DIR, "rig.json")))
W, D, H = rig["W"], rig["D"], rig["H"]
scene = bpy.context.scene
layer = bpy.context.view_layer

# ---------------------------------------------------------------- mesh
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.wm.obj_import(filepath=os.path.join(ROCK_DIR, "rock.obj"), forward_axis="Y", up_axis="Z")
rock = bpy.context.selected_objects[0]
rock.name = "Rock"
layer.objects.active = rock


def apply_modifiers(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.clear()
    old, obj.data = obj.data, mesh
    bpy.data.meshes.remove(old)


dec = rock.modifiers.new("Decimate", "DECIMATE")
dec.ratio = min(1.0, TARGET_FACES / len(rock.data.polygons))
lumps = rock.modifiers.new("Lumps", "DISPLACE")
tex = bpy.data.textures.new("Lumps", "CLOUDS")
tex.noise_scale = 0.18
lumps.texture = tex
lumps.texture_coords = "LOCAL"
lumps.strength = 0.025
lumps.mid_level = 0.5
apply_modifiers(rock)

bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.003)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.shade_smooth()

# ---------------------------------------------------------------- photo projection
# for each view: which way it faces, and how object x/y/z map to the photo's u/v
# (u = a*coord + b, v = c*coord + d; photo v runs bottom to top)
VIEWS = {
    "front":  ((0, -1, 0), ("x", 1 / W, 0.5), ("z", 1 / H, 0)),
    "back":   ((0, 1, 0),  ("x", -1 / W, 0.5), ("z", 1 / H, 0)),
    "right":  ((1, 0, 0),  ("y", 1 / D, 0.5), ("z", 1 / H, 0)),
    "left":   ((-1, 0, 0), ("y", -1 / D, 0.5), ("z", 1 / H, 0)),
    "top":    ((0, 0, 1),  ("x", 1 / W, 0.5), ("y", 1 / D, 0.5)),
    "bottom": ((0, 0, -1), ("x", 1 / W, 0.5), ("y", -1 / D, 0.5)),
}

mat = bpy.data.materials.new("Projected")
mat.use_nodes = True
nt = mat.node_tree
N, L = nt.nodes, nt.links
N.clear()
out = N.new("ShaderNodeOutputMaterial")
bsdf = N.new("ShaderNodeBsdfPrincipled")
bsdf.inputs["Roughness"].default_value = 0.9
L.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
tc = N.new("ShaderNodeTexCoord")
sep = N.new("ShaderNodeSeparateXYZ")
L.new(tc.outputs["Object"], sep.inputs["Vector"])
axis = {"x": sep.outputs["X"], "y": sep.outputs["Y"], "z": sep.outputs["Z"]}


def math_node(op, a, b=None, c=None):
    n = N.new("ShaderNodeMath")
    n.operation = op
    for i, v in enumerate((a, b, c)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            L.new(v, n.inputs[i])
    return n.outputs[0]


# without a top or bottom photo, borrow the front / back photo so those
# surfaces get real rock texture rather than stretched edge pixels
FALLBACK = {"top": ["front"], "bottom": ["back", "front"]}

color_sum, weight_sum = None, None
for name, (facing, (ua, us, uo), (va, vs_, vo)) in VIEWS.items():
    src = name if name in rig["views"] else next((f for f in FALLBACK.get(name, []) if f in rig["views"]), None)
    if src is None:
        continue
    img = bpy.data.images.load(os.path.join(ROCK_DIR, rig["views"][src]["image"]))
    u = math_node("MULTIPLY_ADD", axis[ua], us, uo)
    v = math_node("MULTIPLY_ADD", axis[va], vs_, vo)
    uv = N.new("ShaderNodeCombineXYZ")
    L.new(u, uv.inputs["X"])
    L.new(v, uv.inputs["Y"])
    t = N.new("ShaderNodeTexImage")
    t.image = img
    t.extension = "EXTEND"
    L.new(uv.outputs["Vector"], t.inputs["Vector"])
    # weight: how squarely the surface faces this photo, sharpened
    dot = N.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    L.new(tc.outputs["Normal"], dot.inputs[0])
    dot.inputs[1].default_value = facing
    w = math_node("POWER", math_node("MAXIMUM", dot.outputs["Value"], 0.0), 4.0)
    w = math_node("ADD", w, 1e-4)
    scaled = N.new("ShaderNodeVectorMath")
    scaled.operation = "SCALE"
    L.new(t.outputs["Color"], scaled.inputs[0])
    L.new(w, scaled.inputs["Scale"])
    if color_sum is None:
        color_sum, weight_sum = scaled.outputs["Vector"], w
    else:
        add = N.new("ShaderNodeVectorMath")
        add.operation = "ADD"
        L.new(color_sum, add.inputs[0])
        L.new(scaled.outputs["Vector"], add.inputs[1])
        color_sum = add.outputs["Vector"]
        weight_sum = math_node("ADD", weight_sum, w)

final = N.new("ShaderNodeVectorMath")
final.operation = "SCALE"
L.new(color_sum, final.inputs[0])
L.new(math_node("DIVIDE", 1.0, weight_sum), final.inputs["Scale"])
L.new(final.outputs["Vector"], bsdf.inputs["Base Color"])
# surface relief from the photos' light/dark grain
bw = N.new("ShaderNodeRGBToBW")
L.new(final.outputs["Vector"], bw.inputs["Color"])
bump = N.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.45
bump.inputs["Distance"].default_value = 0.006
L.new(bw.outputs["Val"], bump.inputs["Height"])
L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
rock.data.materials.clear()
rock.data.materials.append(mat)

# ---------------------------------------------------------------- bake
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 8


def bake(kind, name, noncolor=False, **kw):
    img = bpy.data.images.new(name, TEXTURE_SIZE, TEXTURE_SIZE, alpha=False)
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    target = N.new("ShaderNodeTexImage")
    target.image = img
    N.active = target
    bpy.ops.object.bake(type=kind, margin=8, use_clear=True, **kw)
    N.remove(target)
    img.pack()
    return img


color = bake("DIFFUSE", "rock_color", pass_filter={"COLOR"})
normal = bake("NORMAL", "rock_normal", noncolor=True, normal_space="TANGENT")

web = bpy.data.materials.new("Rock")
web.use_nodes = True
wn, wl = web.node_tree.nodes, web.node_tree.links
b = wn["Principled BSDF"]
b.inputs["Roughness"].default_value = 0.9
ct = wn.new("ShaderNodeTexImage"); ct.image = color
wl.new(ct.outputs["Color"], b.inputs["Base Color"])
ntex = wn.new("ShaderNodeTexImage"); ntex.image = normal
nm = wn.new("ShaderNodeNormalMap")
wl.new(ntex.outputs["Color"], nm.inputs["Color"])
wl.new(nm.outputs["Normal"], b.inputs["Normal"])
rock.data.materials.clear()
rock.data.materials.append(web)

# ---------------------------------------------------------------- export
for o in layer.objects:
    o.select_set(False)
rock.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=True,
                          export_yup=True, export_image_format="JPEG")
print("exported", OUT)

# ---------------------------------------------------------------- previews
world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 2.0
sun.rotation_euler = (math.radians(40), math.radians(-25), math.radians(-30))
scene.collection.objects.link(sun)
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = max(W, D, H) * 1.25
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.resolution_x = scene.render.resolution_y = 360
scene.cycles.samples = 16
scene.render.film_transparent = False
for tag, yaw, pitch in (("front", 0, 0), ("angle", 35, 25)):
    r = 6.0
    yaw_r, pitch_r = math.radians(yaw), math.radians(pitch)
    cam.location = (r * math.sin(yaw_r) * math.cos(pitch_r), -r * math.cos(yaw_r) * math.cos(pitch_r),
                    0.5 + r * math.sin(pitch_r))
    cam.rotation_euler = (math.radians(90) - pitch_r, 0, yaw_r)
    scene.render.filepath = os.path.join(ROCK_DIR, f"preview_{tag}.png")
    bpy.ops.render.render(write_still=True)
