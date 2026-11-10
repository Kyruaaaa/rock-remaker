"""Helpers shared by the scripts that run inside Blender."""

import bpy


def script_args():
    """Everything after the first `--` on Blender's command line."""
    import sys
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def apply_modifiers(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.clear()
    old, obj.data = obj.data, mesh
    bpy.data.meshes.remove(old)


def select_only(obj):
    layer = bpy.context.view_layer
    for o in layer.objects:
        o.select_set(False)
    obj.select_set(True)
    layer.objects.active = obj


def setup_bake(samples=8):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples


def bake(nodes, kind, name, size, noncolor=False, **kw):
    """Bake into a new image through a temporary active image node."""
    img = bpy.data.images.new(name, size, size, alpha=False)
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    target = nodes.new("ShaderNodeTexImage")
    target.image = img
    nodes.active = target
    bpy.ops.object.bake(type=kind, margin=16, use_clear=True, **kw)
    nodes.remove(target)
    img.pack()
    return img


def web_material(name, color, normal, roughness):
    """A plain material glTF understands: baked colour + normal map."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = roughness
    c = nodes.new("ShaderNodeTexImage")
    c.image = color
    links.new(c.outputs["Color"], bsdf.inputs["Base Color"])
    n = nodes.new("ShaderNodeTexImage")
    n.image = normal
    nm = nodes.new("ShaderNodeNormalMap")
    links.new(n.outputs["Color"], nm.inputs["Color"])
    links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def export_glb(path, draco=True, image_format="WEBP", quality=85, **extra):
    """Export the selection as a compact .glb."""
    options = dict(filepath=path, export_format="GLB", use_selection=True, export_yup=True,
                   export_apply=True, export_image_format=image_format, export_image_quality=quality)
    if draco:
        options.update(export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
                       export_draco_position_quantization=14, export_draco_normal_quantization=10,
                       export_draco_texcoord_quantization=12)
    options.update(extra)
    bpy.ops.export_scene.gltf(**options)
