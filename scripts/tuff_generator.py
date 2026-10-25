"""
Tuff rock generator for Blender 4.x
-----------------------------------
Open Blender > Scripting tab > Open this file > Run Script.

Everything stays non-destructive so you can keep sculpting it:
  * "TuffRock"      - the rock (Boolean > Remesh > 3x Displace modifiers)
  * "Cutters"       - hidden collection of boxes/spheres that carve the
                      fracture planes, notch and dents. Unhide them, move /
                      rotate / scale, and the rock updates live.
  * "Tuff"          - procedural porous material (pores, grains, specks)

Units: the rock is ~1 m tall. Scale the object to your real size
(e.g. 0.12 for a 12 cm rock) before exporting.
"""

import bpy
import bmesh
import math
import random
from mathutils import Vector, Euler

# ---------------------------------------------------------------- settings
SEED = 7
HEIGHT = 1.0            # long axis (Z), the "Front" photo's vertical
WIDTH = 0.62            # X, the "Front" photo's horizontal
THICK_TOP = 0.55        # Y thickness at the top (thick end of the wedge)
THICK_BOTTOM = 0.20     # Y thickness at the bottom (thin end of the wedge)
VOXEL = 0.02            # remesh resolution before smoothing/subdivision
ROUNDNESS = 12          # smoothing passes: higher = softer, more weathered edges
random.seed(SEED)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.textures,
                  bpy.data.collections, bpy.data.lights, bpy.data.cameras):
        for item in list(block):
            if item.users == 0 or block is bpy.data.collections:
                block.remove(item)


# ---------------------------------------------------------------- base block
def make_wedge_block():
    """A subdivided box whose thickness tapers along Z (the wedge seen in
    the Right/Left photos). Back face is flat, front face slopes."""
    mesh = bpy.data.meshes.new("TuffRock")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=6, use_grid_fill=True)
    for v in bm.verts:
        x, y, z = v.co
        t = z + 0.5                                   # 0 bottom .. 1 top
        thick = THICK_BOTTOM + (THICK_TOP - THICK_BOTTOM) * t
        v.co.x = x * WIDTH
        v.co.z = t * HEIGHT
        # back face at y = +thick/2 of the top, front face slides in
        v.co.y = (THICK_TOP / 2) - (0.5 - y) * thick
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("TuffRock", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------- cutters
def add_cutter(coll, kind, loc, scale, rot=(0, 0, 0), name="Cut"):
    if kind == "box":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif kind == "sphere":
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.5)
    elif kind == "cyl":
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.5, depth=1.0)
    ob = bpy.context.active_object
    ob.name = name
    ob.location = loc
    ob.scale = scale
    ob.rotation_euler = Euler([math.radians(a) for a in rot])
    for c in ob.users_collection:
        c.objects.unlink(ob)
    coll.objects.link(ob)
    ob.display_type = "WIRE"
    ob.hide_render = True
    return ob


def front_y(z):
    """Y of the (sloped) front face at height z."""
    return THICK_TOP / 2 - (THICK_BOTTOM + (THICK_TOP - THICK_BOTTOM) * z / HEIGHT)


def make_cutters():
    coll = bpy.data.collections.new("Cutters")
    bpy.context.scene.collection.children.link(coll)
    yc = 0.0  # cutters are deep enough in Y to pass through

    # Top edge slants down to the left (Front photo)
    add_cutter(coll, "box", (-0.05, yc, 1.08), (1.2, 1.5, 0.3), (0, 8, 0), "Cut_TopSlant")
    # Bottom edge rises to the right (Front photo)
    add_cutter(coll, "box", (0.25, yc, -0.10), (1.2, 1.5, 0.3), (0, 10, 0), "Cut_BottomSlant")
    # Lower-right is stepped in below the notch (Front photo)
    add_cutter(coll, "box", (0.36, yc, 0.12), (0.26, 1.5, 0.55), (0, -6, 0), "Cut_LowerRightStep")
    # The rounded notch on the right side, ~38% up
    add_cutter(coll, "cyl", (0.21, yc, 0.38), (0.13, 0.11, 1.5), (90, 0, 0), "Cut_Notch")
    # Upper-right bulge corner chip
    add_cutter(coll, "box", (0.40, -0.25, 0.92), (0.3, 0.3, 0.4), (20, 0, 35), "Cut_ChipTR")
    # Back-left chamfer (Back photo's diagonal plane)
    add_cutter(coll, "box", (-0.42, 0.32, 0.75), (0.4, 0.35, 1.0), (0, 0, 40), "Cut_BackChamfer")
    # Shallow dents / groove on the front face (Front & Top photos)
    # (centres sit just outside the front face so they scoop, not tunnel)
    add_cutter(coll, "sphere", (-0.02, front_y(0.84) - 0.03, 0.84), (0.30, 0.12, 0.09), (0, -25, 0), "Dent_Groove1")
    add_cutter(coll, "sphere", (0.13, front_y(0.74) - 0.025, 0.74), (0.11, 0.10, 0.11), (0, 0, 0), "Dent_Pit")
    add_cutter(coll, "sphere", (-0.12, front_y(0.55) - 0.03, 0.55), (0.25, 0.10, 0.16), (0, 30, 0), "Dent_Hollow")

    # A few random small chips around the edges for irregularity
    for i in range(10):
        z = random.uniform(0.05, 0.95)
        thick = THICK_BOTTOM + (THICK_TOP - THICK_BOTTOM) * z
        x = random.choice([-1, 1]) * WIDTH / 2
        y = random.choice([THICK_TOP / 2, THICK_TOP / 2 - thick])
        s = random.uniform(0.08, 0.16)
        rot = [random.uniform(0, 90) for _ in range(3)]
        add_cutter(coll, "box", (x, y, z), (s, s, s), rot, f"Chip_{i:02d}")

    coll.hide_viewport = True
    return coll


# ---------------------------------------------------------------- modifiers
def displace_tex(name, ttype, size, depth=2):
    tex = bpy.data.textures.new(name, ttype)
    tex.noise_scale = size
    if hasattr(tex, "noise_depth"):
        tex.noise_depth = depth
    if hasattr(tex, "noise_basis"):
        tex.noise_basis = "BLENDER_ORIGINAL"
    return tex


def add_modifiers(obj, cutters):
    b = obj.modifiers.new("Carve", "BOOLEAN")
    b.operation = "DIFFERENCE"
    b.operand_type = "COLLECTION"
    b.collection = cutters
    b.solver = "EXACT"

    r = obj.modifiers.new("Remesh", "REMESH")
    r.mode = "VOXEL"
    r.voxel_size = VOXEL
    r.use_smooth_shade = True

    # Round off the knife-sharp boolean edges like weathered tuff
    sm = obj.modifiers.new("Weather", "SMOOTH")
    sm.factor = 1.0
    sm.iterations = ROUNDNESS
    sub = obj.modifiers.new("Density", "SUBSURF")
    sub.levels = sub.render_levels = 2

    # Big lumpy undulation
    d1 = obj.modifiers.new("Lumps", "DISPLACE")
    d1.texture = displace_tex("Lumps", "CLOUDS", 0.25, 2)
    d1.strength = 0.12
    d1.texture_coords = "LOCAL"
    # Medium knobbly surface
    d2 = obj.modifiers.new("Knobs", "DISPLACE")
    d2.texture = displace_tex("Knobs", "CLOUDS", 0.06, 3)
    d2.strength = 0.045
    d2.texture_coords = "LOCAL"
    # Fine gritty grain (the sandy texture of tuff)
    d3 = obj.modifiers.new("Grit", "DISPLACE")
    t3 = bpy.data.textures.new("Grit", "VORONOI")
    t3.noise_scale = 0.015
    t3.distance_metric = "DISTANCE"
    d3.texture = t3
    d3.strength = 0.010
    d3.texture_coords = "LOCAL"


# ---------------------------------------------------------------- material
def make_material():
    mat = bpy.data.materials.new("Tuff")
    mat.use_nodes = True
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    N.clear()

    def node(t, x, y, **kw):
        n = N.new(t)
        n.location = (x, y)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    out = node("ShaderNodeOutputMaterial", 1400, 0)
    bsdf = node("ShaderNodeBsdfPrincipled", 1100, 0)
    bsdf.inputs["Roughness"].default_value = 0.95
    L.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    tc = node("ShaderNodeTexCoord", -1200, 0)
    obj_co = tc.outputs["Object"]

    # 1. Broad colour variation: cool grey <-> warm beige
    n_big = node("ShaderNodeTexNoise", -900, 300)
    n_big.inputs["Scale"].default_value = 3.0
    n_big.inputs["Detail"].default_value = 6.0
    L.new(obj_co, n_big.inputs["Vector"])
    ramp_big = node("ShaderNodeValToRGB", -650, 300)
    ramp_big.color_ramp.elements[0].position = 0.35
    ramp_big.color_ramp.elements[0].color = (0.36, 0.37, 0.38, 1)   # cool grey
    ramp_big.color_ramp.elements[1].position = 0.70
    ramp_big.color_ramp.elements[1].color = (0.46, 0.43, 0.37, 1)   # warm beige
    L.new(n_big.outputs["Fac"], ramp_big.inputs["Fac"])

    # 2. Grains: random dark and light specks
    v_grain = node("ShaderNodeTexVoronoi", -900, 0)
    v_grain.inputs["Scale"].default_value = 220.0
    L.new(obj_co, v_grain.inputs["Vector"])
    ramp_grain = node("ShaderNodeValToRGB", -650, 0)
    cr = ramp_grain.color_ramp
    cr.interpolation = "CONSTANT"
    cr.elements[0].position = 0.0
    cr.elements[0].color = (0.18, 0.18, 0.18, 1)                     # dark lithic grain
    cr.elements[1].position = 0.10
    cr.elements[1].color = (0.5, 0.5, 0.5, 1)                        # neutral (= no change)
    e = cr.elements.new(0.93)
    e.color = (0.85, 0.84, 0.80, 1)                                  # bright pumice grain
    L.new(v_grain.outputs["Color"], ramp_grain.inputs["Fac"])

    mix_grain = node("ShaderNodeMix", -350, 200, data_type="RGBA", blend_type="OVERLAY")
    mix_grain.inputs["Factor"].default_value = 0.8
    L.new(ramp_big.outputs["Color"], mix_grain.inputs[6])
    L.new(ramp_grain.outputs["Color"], mix_grain.inputs[7])

    # 3. Pores (vesicles): small dark holes
    v_pore = node("ShaderNodeTexVoronoi", -900, -300)
    v_pore.inputs["Scale"].default_value = 60.0
    v_pore.inputs["Randomness"].default_value = 1.0
    L.new(obj_co, v_pore.inputs["Vector"])
    # vary pore size so only some cells become holes
    n_pore = node("ShaderNodeTexNoise", -900, -550)
    n_pore.inputs["Scale"].default_value = 18.0
    L.new(obj_co, n_pore.inputs["Vector"])
    pore_size = node("ShaderNodeMapRange", -650, -550)
    pore_size.inputs["From Min"].default_value = 0.45
    pore_size.inputs["From Max"].default_value = 0.65
    pore_size.inputs["To Min"].default_value = 0.0
    pore_size.inputs["To Max"].default_value = 0.20
    L.new(n_pore.outputs["Fac"], pore_size.inputs["Value"])
    pore = node("ShaderNodeMath", -400, -300, operation="LESS_THAN")
    L.new(v_pore.outputs["Distance"], pore.inputs[0])
    L.new(pore_size.outputs["Result"], pore.inputs[1])

    mix_pore = node("ShaderNodeMix", -100, 100, data_type="RGBA", blend_type="MIX")
    mix_pore.inputs[7].default_value = (0.07, 0.07, 0.07, 1)
    L.new(pore.outputs["Value"], mix_pore.inputs["Factor"])
    L.new(mix_grain.outputs[2], mix_pore.inputs[6])
    L.new(mix_pore.outputs[2], bsdf.inputs["Base Color"])

    # 4. Bump: grit + pores pushed in
    n_grit = node("ShaderNodeTexNoise", -650, -800)
    n_grit.inputs["Scale"].default_value = 350.0
    n_grit.inputs["Detail"].default_value = 4.0
    L.new(obj_co, n_grit.inputs["Vector"])
    height = node("ShaderNodeMath", -100, -500, operation="MULTIPLY_ADD")
    L.new(pore.outputs["Value"], height.inputs[0])
    height.inputs[1].default_value = -1.0
    L.new(n_grit.outputs["Fac"], height.inputs[2])
    bump = node("ShaderNodeBump", 700, -300)
    bump.inputs["Strength"].default_value = 0.7
    bump.inputs["Distance"].default_value = 0.004
    L.new(height.outputs["Value"], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# ---------------------------------------------------------------- stage
def make_stage(rock):
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.9, 0.9, 0.9, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 2.2
    sun.data.angle = math.radians(8)
    sun.rotation_euler = Euler((math.radians(50), math.radians(-20), math.radians(-35)))
    bpy.context.scene.collection.objects.link(sun)

    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = 85
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    target = Vector((0, 0.05, 0.5))
    cam.location = target + Vector((0, -4.2, 0))
    track = cam.constraints.new("TRACK_TO")
    empty = bpy.data.objects.new("CamTarget", None)
    empty.location = target
    bpy.context.scene.collection.objects.link(empty)
    track.target = empty


def build():
    clear_scene()
    rock = make_wedge_block()
    cutters = make_cutters()
    add_modifiers(rock, cutters)
    rock.data.materials.append(make_material())
    make_stage(rock)
    bpy.ops.object.select_all(action="DESELECT")
    rock.select_set(True)
    bpy.context.view_layer.objects.active = rock
    return rock


rock = build()
print("Tuff rock built:", rock.name)
