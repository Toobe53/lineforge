# LineForge — render only the line pass of the current .blend (headless).
# GPL-2.0-or-later.
import os
import sys
import time
import traceback

import bpy

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
    scene.lf.line_scale = SCALE
    print("SETS", [(n.name, n.line_type, round(n.width, 2)) for n in nodes.active_sets(scene.lf.node_tree)])

    t0 = time.time()
    rgba = renderer.render(bpy.context, width=W, height=H)
    st = renderer.last_stats()
    print("STATS", st)
    print("SECONDS", round(time.time() - t0, 2))
    print("COVERAGE", round(float((rgba[..., 3] > 1e-4).mean()), 5))

    img = renderer.write_pass_image(bpy.context, rgba)
    png = os.path.join(OUT, "line_pass.png")
    img.filepath_raw = png
    img.file_format = 'PNG'
    img.save()
    print("PASS_PNG", os.path.exists(png), os.path.getsize(png) if os.path.exists(png) else 0)
    types = {}
    for pl in renderer.last_lines():
        t = int(pl["type"])
        types[t] = types.get(t, 0) + 1
    print("TYPES", types)
    print("PASS TEST OK")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
