# LineForge — demo render on a real VRM scene with the installed add-on.
# GPL-2.0-or-later.
import os
import sys
import traceback

import bpy

BLEND = r"C:\PencilPlus\vrm_pcl_line5.blend"
OUT_DIR = r"C:\LineForge\docs"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sys.path.insert(0, r"C:\LineForge\addon")
    import lineforge
    if not hasattr(bpy.types.Scene, "lf"):
        lineforge.register()
    from lineforge import nodes, renderer, operators

    bpy.ops.wm.open_mainfile(filepath=BLEND)
    scene = bpy.context.scene

    scene.render.resolution_percentage = 100
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    if scene.lf.node_tree is None:
        bpy.ops.lf.create_tree()
    tree = scene.lf.node_tree
    sets = nodes.active_sets(tree)
    print("SETS", [(n.name, n.line_type, round(n.width, 2), n.enabled) for n in sets])

    scene.lf.line_scale = 1.0
    scene.lf.hidden_lines = False
    scene.lf.hidden_alpha = 0.22
    scene.lf.hidden_width = 0.6
    scene.lf.enabled = True

    rgba = renderer.render(bpy.context)
    stats = renderer.last_stats()
    print("STATS", stats)

    img = renderer.write_pass_image(bpy.context, rgba)
    pass_png = os.path.join(OUT_DIR, "line_pass_1080p.png")
    img.filepath_raw = pass_png
    img.file_format = 'PNG'
    img.save()
    print("PASS", pass_png, os.path.getsize(pass_png))

    # Full F12 pipeline: line pass + compositor wiring + beauty render.
    out = os.path.join(OUT_DIR, "composite_1080p.png")
    try:
        renderer.render_still(bpy.context, filepath=out)
        print("COMPOSITE", out, os.path.getsize(out) if os.path.exists(out) else -1)
        print("COMPOSITOR_GROUP", getattr(scene, "compositing_node_group", None))
    except Exception:
        print("COMPOSITE SKIPPED")
        traceback.print_exc(limit=3)

    print("ENGINE", scene.render.engine)
    print("DEMO OK")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
