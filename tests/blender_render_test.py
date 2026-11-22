# LineForge — full render + intersection tests inside Blender (headless).
# GPL-2.0-or-later.
import os
import sys
import traceback

import bpy
import numpy as np

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

import lineforge  # noqa: E402
from lineforge import nodes, renderer  # noqa: E402

OUT = r"C:\LineForge\build"


def reset_engine(scene):
    try:
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = 8
        scene.cycles.use_denoising = False
    except Exception:
        pass
    scene.render.resolution_x = 400
    scene.render.resolution_y = 300
    scene.render.resolution_percentage = 100


def only_node(tree, keep_type):
    for n in tree.nodes:
        if n.bl_idname == "LFLineSetNode":
            n.enabled = (n.line_type == keep_type)


def main():
    try:
        lineforge.unregister()
    except Exception:
        pass
    lineforge.register()
    scene = bpy.context.scene
    bpy.ops.lf.create_tree()
    tree = scene.lf.node_tree
    reset_engine(scene)

    # ---- test A: F12 render with compositing -----------------------------
    png = os.path.join(OUT, "f12_cube.png")
    if os.path.exists(png):
        os.remove(png)
    renderer.render_still(bpy.context, filepath=png)
    ok_png = os.path.exists(png) and os.path.getsize(png) > 1000
    print("F12_PNG", ok_png, os.path.getsize(png) if os.path.exists(png) else 0)
    img = bpy.data.images.get("Render Result")
    print("RENDER_RESULT", img is not None, tuple(img.size) if img else None)

    # ---- test B: intersection pass with two overlapping cubes ------------
    cube = bpy.data.objects.get("Cube")
    bpy.ops.mesh.primitive_cube_add(size=1.6, location=(0.45, 0.35, 0.25))
    second = bpy.context.active_object
    second.rotation_euler = (0.3, 0.2, 0.6)

    only_node(tree, 'INTERSECTION')
    scene.render.resolution_x = 480
    scene.render.resolution_y = 360
    rgba = renderer.render(bpy.context)
    st = renderer.last_stats()
    print("INTER_STATS", st)
    inter_lines = [pl for pl in renderer.last_lines() if int(pl["type"]) == 4]
    print("INTER_LINES", len(inter_lines), "coverage", round(float((rgba[..., 3] > 1e-4).mean()), 5))
    img = renderer.write_pass_image(bpy.context, rgba, name="LineForge Intersection")
    ipng = os.path.join(OUT, "test_intersection.png")
    img.filepath_raw = ipng
    img.file_format = 'PNG'
    img.save()
    print("INTER_PNG", os.path.exists(ipng), os.path.getsize(ipng) if os.path.exists(ipng) else 0)
    if len(inter_lines) == 0:
        raise RuntimeError("no intersection lines between the two cubes")

    only_node(tree, 'OBJECT')
    rgba2 = renderer.render(bpy.context)
    print("OBJ_STATS", renderer.last_stats())
    print("RENDER TEST OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
finally:
    try:
        lineforge.unregister()
    except Exception:
        traceback.print_exc()
sys.exit(rc)
