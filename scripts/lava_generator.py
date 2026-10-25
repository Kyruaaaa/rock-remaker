"""
Small lava rock (scoria) generator for Blender 4.x
--------------------------------------------------
A lumpy black stone full of gas-bubble pits, for the 12 / 3 / 6 / 9 markers.
Makes an object called "LavaRock"; export it with export_glb.py:

  Blender -b --factory-startup --python lava_generator.py --python export_glb.py -- out.glb 512 LavaRock -- SEED

SEED (after the second --) gives each rock a different shape.
"""

import bpy
import math
import random
import sys

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
rest = args[args.index("--") + 1:] if "--" in args else []
SEED = int(rest[0]) if rest else 1
SIZE = 0.55              # bounding-box diagonal (the clock's rocks are 1.3)
random.seed(SEED)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=0.5)
rock = bpy.context.active_object
rock.name = "LavaRock"
# a squashed, uneven lump
rock.scale = (random.uniform(0.95, 1.15), random.uniform(0.75, 0.95), random.uniform(0.65, 0.85))
rock.rotation_euler = [random.uniform(0, math.pi) for _ in range(3)]
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def displace(name, ttype, size, strength, **kw):
    tex = bpy.data.textures.new(name, ttype)
    tex.noise_scale = size
    for k, v in kw.items():
        setattr(tex, k, v)
    m = rock.modifiers.new(name, "DISPLACE")
    m.texture = tex
    m.texture_coords = "LOCAL"
    m.strength = strength
    return m


lump = displace("Lumps", "CLOUDS", 0.38, 0.32, noise_depth=2)     # lobed, uneven body
lump.mid_level = 0.5
# gas-bubble pits: every voronoi cell's middle stays put while its rim rises,
# so the surface is covered in cupped hollows
pits = displace("Pits", "VORONOI", 0.055, 0.075, distance_metric="DISTANCE")
pits.mid_level = 0.0
grit = displace("Grit", "CLOUDS", 0.02, 0.01, noise_depth=1)
bpy.context.view_layer.objects.active = rock
for m in list(rock.modifiers):
    bpy.ops.object.modifier_apply(modifier=m.name)

# scale to the marker size and stand it on the ground at the centre
dims = rock.dimensions
k = SIZE / math.sqrt(dims.x ** 2 + dims.y ** 2 + dims.z ** 2)
rock.scale = (k, k, k)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
rock.location = (0, 0, rock.dimensions.z / 2)
bpy.ops.object.shade_smooth()

# matte, opaque black with faint grey variation and dark pits
mat = bpy.data.materials.new("Lava")
mat.use_nodes = True
nt = mat.node_tree
N, L = nt.nodes, nt.links
bsdf = N["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 0.88
tc = N.new("ShaderNodeTexCoord")
noise = N.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 9.0
noise.inputs["Detail"].default_value = 8.0
L.new(tc.outputs["Object"], noise.inputs["Vector"])
ramp = N.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.012, 0.012, 0.013, 1)
ramp.color_ramp.elements[1].color = (0.06, 0.058, 0.057, 1)
L.new(noise.outputs["Fac"], ramp.inputs["Fac"])
vor = N.new("ShaderNodeTexVoronoi")
vor.inputs["Scale"].default_value = 26.0
L.new(tc.outputs["Object"], vor.inputs["Vector"])
pit = N.new("ShaderNodeMath")
pit.operation = "LESS_THAN"
pit.inputs[1].default_value = 0.12
L.new(vor.outputs["Distance"], pit.inputs[0])
mix = N.new("ShaderNodeMix")
mix.data_type = "RGBA"
mix.inputs[7].default_value = (0.004, 0.004, 0.004, 1)
L.new(pit.outputs["Value"], mix.inputs["Factor"])
L.new(ramp.outputs["Color"], mix.inputs[6])
L.new(mix.outputs[2], bsdf.inputs["Base Color"])
bump = N.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.8
bump.inputs["Distance"].default_value = 0.01
height = N.new("ShaderNodeMath")
height.operation = "SUBTRACT"
L.new(noise.outputs["Fac"], height.inputs[0])
L.new(pit.outputs["Value"], height.inputs[1])
L.new(height.outputs["Value"], bump.inputs["Height"])
L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
rock.data.materials.append(mat)
bpy.context.scene["decimate"] = 0.75   # export_glb.py: keep most faces so the pits survive
print("lava rock built, seed", SEED)
