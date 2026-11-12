"""
Finish a rock made by build_hull.py and prepare_textures.py as a web-ready .glb.

  1. imports rock.obj, thins it out and adds a little surface irregularity,
  2. colours it by projecting each photo from the direction it was taken,
     every surface taking the photo that faces it most squarely,
  3. bakes a colour texture and a normal map made from the photos' fine grain,
  4. exports a compact .glb and renders previews (including a plain clay view
     for judging the shape alone).

    Blender -b --factory-startup --python build_rock.py -- rock_dir out.glb [--texture 1024 ...]
"""

import argparse
import json
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_common as bc  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("rock_dir")
p.add_argument("out")
p.add_argument("--texture", type=int, default=1024, help="baked texture size in pixels")
p.add_argument("--faces", type=int, default=30000, help="target mesh faces")
p.add_argument("--blend-power", type=float, default=8.0, help="higher = narrower blend between photos")
p.add_argument("--lumps", type=float, default=0.015, help="made-up surface irregularity, 0 for none")
p.add_argument("--sparkle", type=float, default=0.0,
               help="mica/glitter: share of the surface covered by mirror-like flakes, e.g. 0.12; 0 for none")
p.add_argument("--flake-size", type=float, default=0.008, help="flake size as a share of the rock's height")
p.add_argument("--no-draco", action="store_true", help="skip mesh compression")
a = p.parse_args(bc.script_args())

ROCK_DIR, OUT = os.path.abspath(a.rock_dir), os.path.abspath(a.out)
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

dec = rock.modifiers.new("Decimate", "DECIMATE")
dec.ratio = min(1.0, a.faces / len(rock.data.polygons))
if a.lumps > 0:
    lumps = rock.modifiers.new("Lumps", "DISPLACE")
    tex = bpy.data.textures.new("Lumps", "CLOUDS")
    tex.noise_scale = 0.18
    lumps.texture = tex
    lumps.texture_coords = "LOCAL"
    lumps.strength = a.lumps
    lumps.mid_level = 0.5
bc.apply_modifiers(rock)

bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.008)   # about 8 px: seams survive mipmapping
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.shade_smooth()

# ---------------------------------------------------------------- photo projection
mat = bpy.data.materials.new("Projected")
mat.use_nodes = True
nt = mat.node_tree
N, L = nt.nodes, nt.links
N.clear()
output = N.new("ShaderNodeOutputMaterial")
bsdf = N.new("ShaderNodeBsdfPrincipled")
bsdf.inputs["Roughness"].default_value = 0.9
L.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
tc = N.new("ShaderNodeTexCoord")


def math_node(op, x, y=None, z=None):
    n = N.new("ShaderNodeMath")
    n.operation = op
    for i, v in enumerate((x, y, z)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            L.new(v, n.inputs[i])
    return n.outputs[0]


def dot(socket, vec):
    n = N.new("ShaderNodeVectorMath")
    n.operation = "DOT_PRODUCT"
    L.new(socket, n.inputs[0])
    n.inputs[1].default_value = vec
    return n.outputs["Value"]


def vec_op(op, x, y):
    n = N.new("ShaderNodeVectorMath")
    n.operation = op
    L.new(x, n.inputs[0])
    if op == "SCALE":
        L.new(y, n.inputs["Scale"])
    else:
        L.new(y, n.inputs[1])
    return n.outputs["Vector"]


def load_image(name, noncolor=False):
    img = bpy.data.images.load(os.path.join(ROCK_DIR, name))
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    return img


colour_sum, height_sum, weight_sum = None, None, None
for name, v in rig["views"].items():
    u = math_node("MULTIPLY_ADD", dot(tc.outputs["Object"], v["u_axis"]), v["su"], v["ou"])
    w_v = math_node("MULTIPLY_ADD", dot(tc.outputs["Object"], v["v_axis"]), v["sv"], v["ov"])
    uv = N.new("ShaderNodeCombineXYZ")
    L.new(u, uv.inputs["X"])
    L.new(w_v, uv.inputs["Y"])
    t_c = N.new("ShaderNodeTexImage")
    t_c.image = load_image(v["image"])
    t_c.extension = "EXTEND"
    L.new(uv.outputs["Vector"], t_c.inputs["Vector"])
    t_h = N.new("ShaderNodeTexImage")
    t_h.image = load_image(v["height"], noncolor=True)
    t_h.extension = "EXTEND"
    L.new(uv.outputs["Vector"], t_h.inputs["Vector"])
    w = math_node("POWER", math_node("MAXIMUM", dot(tc.outputs["Normal"], v["facing"]), 0.0), a.blend_power)
    w = math_node("ADD", w, 1e-5)
    c = vec_op("SCALE", t_c.outputs["Color"], w)
    h = math_node("MULTIPLY", t_h.outputs["Color"], w)
    if colour_sum is None:
        colour_sum, height_sum, weight_sum = c, h, w
    else:
        colour_sum = vec_op("ADD", colour_sum, c)
        height_sum = math_node("ADD", height_sum, h)
        weight_sum = math_node("ADD", weight_sum, w)

inv = math_node("DIVIDE", 1.0, weight_sum)
final = vec_op("SCALE", colour_sum, inv)
bump = N.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.6
bump.inputs["Distance"].default_value = 0.012
L.new(math_node("MULTIPLY", height_sum, inv), bump.inputs["Height"])

flake = None
if a.sparkle > 0:
    # mica: small flat flakes, each a little mirror tilted its own way
    vor = N.new("ShaderNodeTexVoronoi")
    vor.feature = "F1"
    vor.inputs["Scale"].default_value = 1.0 / (a.flake_size * H)
    vor.inputs["Randomness"].default_value = 1.0
    L.new(tc.outputs["Object"], vor.inputs["Vector"])
    rnd = N.new("ShaderNodeSeparateColor")
    L.new(vor.outputs["Color"], rnd.inputs["Color"])
    flake = math_node("GREATER_THAN", rnd.outputs["Red"], 1.0 - a.sparkle)
    # tilt: height rising across the flake in a random direction -> a flat, tilted facet
    centre_offset = vec_op("SUBTRACT", tc.outputs["Object"], vor.outputs["Position"])
    rand_vec = N.new("ShaderNodeVectorMath")
    rand_vec.operation = "SUBTRACT"
    L.new(vor.outputs["Color"], rand_vec.inputs[0])
    rand_vec.inputs[1].default_value = (0.5, 0.5, 0.5)
    slope = N.new("ShaderNodeVectorMath")
    slope.operation = "DOT_PRODUCT"
    L.new(centre_offset, slope.inputs[0])
    L.new(rand_vec.outputs["Vector"], slope.inputs[1])
    tilt = math_node("MULTIPLY", math_node("MULTIPLY", slope.outputs["Value"], flake), 1.4)
    fb = N.new("ShaderNodeBump")
    fb.inputs["Strength"].default_value = 1.0
    fb.inputs["Distance"].default_value = 1.0
    L.new(tilt, fb.inputs["Height"])
    L.new(bump.outputs["Normal"], fb.inputs["Normal"])
    normal_out = fb.outputs["Normal"]
    # flakes read a touch lighter and silvery
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "SCREEN"
    L.new(math_node("MULTIPLY", flake, 0.35), mix.inputs["Factor"])
    L.new(final, mix.inputs["A"])
    mix.inputs["B"].default_value = (0.85, 0.85, 0.82, 1)
    final = mix.outputs["Result"]
else:
    normal_out = bump.outputs["Normal"]
L.new(final, bsdf.inputs["Base Color"])
L.new(normal_out, bsdf.inputs["Normal"])
rock.data.materials.clear()
rock.data.materials.append(mat)

# ---------------------------------------------------------------- bake
bc.setup_bake()
color = bc.bake(N, "DIFFUSE", "rock_color", a.texture, pass_filter={"COLOR"})
normal = bc.bake(N, "NORMAL", "rock_normal", a.texture, noncolor=True, normal_space="TANGENT")
rough = None
if flake is not None:
    def bake_value(value, name):
        em = N.new("ShaderNodeEmission")
        L.new(value, em.inputs["Color"])
        L.new(em.outputs["Emission"], output.inputs["Surface"])
        img = bc.bake(N, "EMIT", name, a.texture, noncolor=True)
        L.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        return img
    # mica is glassy, not metal: its glint comes from smooth, tilted faces alone
    rough = bake_value(math_node("MULTIPLY_ADD", flake, -0.75, 0.9), "rock_roughness")   # 0.9 stone, 0.15 flake
rock.data.materials.clear()
rock.data.materials.append(bc.web_material("Rock", color, normal, 0.9, rough))

# ---------------------------------------------------------------- export
bc.select_only(rock)
bc.export_glb(OUT, draco=not a.no_draco)
print("exported", OUT, f"{os.path.getsize(OUT) // 1024} KB")

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
scene.view_settings.view_transform = "Standard"
scene.render.film_transparent = False


def shoot(tag, yaw, pitch):
    r = 6.0
    yaw_r, pitch_r = math.radians(yaw), math.radians(pitch)
    cam.location = (r * math.sin(yaw_r) * math.cos(pitch_r), -r * math.cos(yaw_r) * math.cos(pitch_r),
                    H / 2 + r * math.sin(pitch_r))
    cam.rotation_euler = (math.radians(90) - pitch_r, 0, yaw_r)
    scene.render.filepath = os.path.join(ROCK_DIR, f"preview_{tag}.png")
    bpy.ops.render.render(write_still=True)


SHOTS = {"front": (0, 0), "right": (90, 0), "back": (180, 0), "left": (270, 0), "top": (0, 89.9), "angle": (35, 25)}
for tag, (yaw, pitch) in SHOTS.items():
    shoot(tag, yaw, pitch)
clay = bpy.data.materials.new("Clay")
clay.use_nodes = True
clay.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.55, 0.55, 1)
layer.material_override = clay
shoot("clay", 35, 25)
shoot("clay_back", 215, 25)
shoot("clay_right", 90, 0)
