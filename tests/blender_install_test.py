# LineForge — install the packaged zip the way a user would, enable it, render.
# GPL-2.0-or-later.
import os
import sys
import traceback

import bpy

ZIP = r"C:\LineForge\dist\lineforge-0.1.0.zip"
OUT = r"C:\LineForge\build"


def main():
    for mod in list(sys.modules):
        if mod == "lineforge" or mod.startswith("lineforge."):
            del sys.modules[mod]

    bpy.ops.preferences.addon_install(filepath=ZIP, overwrite=True)
    print("INSTALL OK")
    bpy.ops.preferences.addon_enable(module="lineforge")
    print("ENABLE OK")

    import lineforge
    print("MODULE_PATH", lineforge.__file__)
    from lineforge import nodes, renderer
    print("CORE", renderer.core().__file__)

    scene = bpy.context.scene
    bpy.ops.lf.create_tree()
    print("SETS", [(n.name, n.line_type) for n in nodes.active_sets(scene.lf.node_tree)])

    scene.render.resolution_x = 512
    scene.render.resolution_y = 384
    rgba = renderer.render(bpy.context)
    print("STATS", renderer.last_stats())
    print("COVERAGE", round(float((rgba[..., 3] > 1e-4).mean()), 5))

    img = renderer.write_pass_image(bpy.context, rgba)
    png = os.path.join(OUT, "installed_test.png")
    img.filepath_raw = png
    img.file_format = 'PNG'
    img.save()
    print("PNG", os.path.exists(png), os.path.getsize(png) if os.path.exists(png) else 0)

    bpy.ops.preferences.addon_disable(module="lineforge")
    print("DISABLE OK")
    bpy.ops.preferences.addon_remove(module="lineforge")
    print("REMOVE OK")
    print("INSTALL TEST OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
sys.exit(rc)
