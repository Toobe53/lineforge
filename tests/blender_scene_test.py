# LineForge — render a real .blend scene with the add-on (headless).
# GPL-2.0-or-later.
import os
import sys
import time
import traceback

import bpy
import numpy as np

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

import lineforge  # noqa: E402
from lineforge import nodes, renderer  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else r"C:\LineForge\build\real_scene"
W = int(argv[1]) if len(argv) > 1 else 1280
H = int(argv[2]) if len(argv) > 2 else 720
SCALE = float(argv[3]) if len(argv) > 3 else 2.0
os.makedirs(OUT, exist_ok=True)


def main():
    try:
        lineforge.unregister()
    except Exception:
        pass
    lineforge.register()
    scene = bpy.context.scene
    if scene.lf.node_tree is None:
        bpy.ops.lf.create_tree()
    tree = scene.lf.node_tree
    scene.lf.line_scale = SCALE
    scene.lf.auto_composite = True
    scene.lf.auto_render_on_f12 = True
    print("SETS", [(n.name, n.line_type, round(n.width, 2)) for n in nodes.active_sets(tree)])

    t0 = time.time()
    rgba = renderer.render(bpy.context, width=W, height=H)
    st = renderer.last_stats()
    print("STATS", st)
    print("SECONDS", round(time.time() - t0, 2))
    cov = float((rgba[..., 3] > 1e-4).mean())
    print("COVERAGE", round(cov, 5))

    img = renderer.write_pass_image(bpy.context, rgba)
    png = os.path.join(OUT, "line_pass.png")
    img.filepath_raw = png
    img.file_format = 'PNG'
    img.save()
    print("PASS_PNG", os.path.exists(png), os.path.getsize(png) if os.path.exists(png) else 0)

    # combined render (line pass over the beauty render) via the compositor
    renderer.setup_compositor(bpy.context, img)
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.resolution_percentage = 100
    try:
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = 16
        scene.cycles.use_denoising = False
    except Exception:
        pass
    out = os.path.join(OUT, "composite.png")
    scene.render.filepath = out
    t1 = time.time()
    bpy.ops.render.render(write_still=True)
    print("COMPOSITE", os.path.exists(out), os.path.getsize(out) if os.path.exists(out) else 0,
          "secs", round(time.time() - t1, 1))
    print("SCENE TEST OK")
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
