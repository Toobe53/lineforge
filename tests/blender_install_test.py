# LineForge — install the packaged zip the way a user would, enable it, render.
# GPL-2.0-or-later.
import os
import sys
import traceback

import bpy

import glob

ZIP = sorted(glob.glob(r"C:\LineForge\dist\lineforge-*.zip"),
             key=lambda p: os.path.getmtime(p))[-1]
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

    # Leave the add-on installed and enabled (this mirrors what a user gets from
    # Preferences > Add-ons), so the desk session keeps LineForge available.
    bpy.ops.wm.save_userpref()
    print("USERPREF SAVED")
    print("INSTALL TEST OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
sys.exit(rc)
