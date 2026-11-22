# LineForge add-on integration test inside real Blender (headless).
# GPL-2.0-or-later.
import os
import sys
import traceback

import bpy

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

import lineforge  # noqa: E402
from lineforge import nodes, renderer  # noqa: E402

OUT = r"C:\LineForge\build"


def main():
    try:
        lineforge.unregister()
    except Exception:
        pass
    lineforge.register()
    print("REGISTER OK")

    scene = bpy.context.scene
    bpy.ops.lf.create_tree()
    tree = scene.lf.node_tree
    print("TREE", tree.name if tree else None)
    sets = nodes.active_sets(tree)
    print("SETS", [(n.name, n.line_type, round(n.width, 2)) for n in sets])

    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False

    rgba = renderer.render(bpy.context)  # native core through the add-on
    st = renderer.last_stats()
    print("STATS", st)
    print("LINES", len(renderer.last_lines()))
    cov = float((rgba[..., 3] > 1e-4).mean())
    print("COVERAGE", round(cov, 5))
    if cov <= 0.0:
        raise RuntimeError("empty line pass")

    img = renderer.write_pass_image(bpy.context, rgba)
    png = os.path.join(OUT, "test_pass.png")
    img.filepath_raw = png
    img.file_format = 'PNG'
    img.save()
    print("PNG", os.path.exists(png), os.path.getsize(png) if os.path.exists(png) else 0)

    # compositor wiring must not raise
    renderer.setup_compositor(bpy.context, img)
    print("COMPOSITOR", scene.use_nodes, scene.render.use_compositing)
    print("ADDON TEST OK")
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
