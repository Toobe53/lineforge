"""Line pattern / brush texture / per line set simplify checks.

Run with:  blender -b --factory-startup --python blender_pattern_test.py
"""
import math
import os
import sys
import traceback

import bpy
import numpy as np
from mathutils import Vector

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

import lineforge  # noqa: E402
from lineforge import nodes as lfnodes  # noqa: E402
from lineforge import renderer  # noqa: E402

W, H = 320, 240


def build_scene():
    scene = bpy.context.scene
    cube = bpy.data.objects.new("cube", bpy.data.meshes.new("cube"))
    scene.collection.objects.link(cube)
    import bmesh

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=20, radius=1.2)
    bm.to_mesh(cube.data)
    bm.free()

    cam_data = bpy.data.cameras.new("CAM")
    cam_data.lens = 50.0
    cam = bpy.data.objects.new("CAM", cam_data)
    cam.location = (3.4, -4.6, 3.0)
    direction = (Vector((0.0, 0.0, 0.0)) - cam.location).normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    return scene, cube


def setup_tree(scene):
    lf = scene.lf
    lf.enabled = True
    tree = bpy.data.node_groups.new("LineForge", "LFNodeTree")
    sets = []
    previous = None
    for i in range(4):
        node = tree.nodes.new("LFLineSetNode")
        node.location = (0.0, float(i) * 160.0)
        if previous is not None:
            # keep the sets out of each other's way
            pass
        previous = node
        sets.append(node)
    out = tree.nodes.new("LFOutputNode")
    out.location = (-260.0, 0.0)
    for i, node in enumerate(sets):
        tree.links.new(node.outputs[0], out.inputs[i])
    lf.node_tree = tree
    return tree, sets, out


def render(scene):
    img = renderer.render(bpy.context, W, H)
    cov = float(np.asarray(img, np.float32)[..., 3].sum())
    return renderer.last_stats(), renderer.last_lines(), cov


def widths_of(lines):
    vals = []
    for ln in lines:
        w = np.asarray(ln["widths"], np.float32)
        if w.size:
            vals.append(w)
    return np.concatenate(vals) if vals else np.zeros(0, np.float32)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        lineforge.unregister()
    except Exception:  # noqa: BLE001
        pass
    lineforge.register()

    scene, cube = build_scene()
    tree, sets, out = setup_tree(scene)
    out.simplify_px = 0.0

    # Only the object outline, one set enabled at a time.
    for node in sets:
        node.enabled = False
    node = sets[0]
    node.enabled = True
    node.line_type = 'OBJECT'
    node.width = 6.0
    node.random_width = 0.0
    node.taper_in = 0.0
    node.taper_out = 0.0
    node.brush_preset = 'SOLID'
    node.brush_width_amp = 0.0
    node.brush_alpha_amp = 0.0
    node.texture = 'NONE'
    node.pattern = 'SOLID'

    st_solid, l_solid, c_solid = render(scene)
    solid = st_solid["strokes"]
    assert solid > 0, st_solid
    assert c_solid > 0.0
    w_solid = widths_of(l_solid)
    assert w_solid.std() < 1e-4, w_solid.std()

    node.pattern = 'DASH'
    node.pattern_period = 20.0
    node.pattern_duty = 0.5
    st_dash, _, c_dash = render(scene)
    dash = c_dash / c_solid
    print("PATTERN solid %.0f dash %.0f ratio %.3f" % (c_solid, c_dash, dash))
    assert 0.3 < dash < 0.8, dash

    node.pattern = 'DOT'
    node.pattern_period = 20.0
    st_dot, _, c_dot = render(scene)
    dot = c_dot / c_solid
    print("PATTERN dot ratio %.3f" % dot)
    assert dot < dash, (dash, dot)
    # patterns change only the drawing, not the extracted geometry
    assert st_dot["tris"] == st_solid["tris"]

    node.pattern = 'SOLID'
    node.texture = 'CHARCOAL'
    node.texture_scale = 2.0
    st_tex, l_tex, c_tex = render(scene)
    w_tex = widths_of(l_tex)
    print("TEXTURE strokes %d width std %.3f ratio %.3f"
          % (st_tex["strokes"], float(w_tex.std()), c_tex / c_solid))
    assert w_tex.std() > 0.2, float(w_tex.std())

    node.texture = 'NONE'
    node.simplify_override = True
    node.simplify_px = 0.0
    st_fine, l_fine, _ = render(scene)
    n_fine = sum(len(ln["points"]) for ln in l_fine)
    node.simplify_px = 6.0
    st_coarse, l_coarse, _ = render(scene)
    n_coarse = sum(len(ln["points"]) for ln in l_coarse)
    print("SIMPLIFY fine %d coarse %d" % (n_fine, n_coarse))
    assert n_coarse < n_fine, (n_fine, n_coarse)
    assert st_coarse["strokes"] > 0

    print("PATTERN OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
sys.exit(rc)
