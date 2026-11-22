# LineForge: exercise the compositor-free render operator headlessly.
# Usage: blender -b --factory-startup --python tests/blender_composite_op.py
import os
import sys

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "addon"))

import lineforge  # noqa: E402

if not hasattr(bpy.types.Scene, "lf"):
    lineforge.register()

from lineforge import renderer  # noqa: E402

BLEND = r"C:\PencilPlus\vrm_pcl_line5.blend"
OUT = os.path.join(ROOT, "build", "composite_op.png")

bpy.ops.wm.open_mainfile(filepath=BLEND)
scene = bpy.context.scene
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100

if scene.lf.node_tree is None:
    bpy.ops.lf.create_tree()
scene.lf.line_scale = 1.0
scene.lf.hidden_lines = False

res = bpy.ops.lf.render_composite(filepath=OUT)
assert res == {'FINISHED'}, res
assert os.path.exists(OUT), OUT
size = os.path.getsize(OUT)
print("OP OK", res, size)

img = bpy.data.images.load(OUT)
img.colorspace_settings.name = 'Non-Color'
img.reload()
w, h = img.size
px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
assert (w, h) == (1280, 720), (w, h)
dark = float((px[..., 0] < 0.25).mean())
mid = float(((px[..., 0] >= 0.25) & (px[..., 0] < 0.7)).mean())
print("PIXELS dark %.4f mid %.4f alpha %.3f" % (dark, mid, float(px[..., 3].mean())))
assert dark > 0.005, dark
assert mid > 0.002, mid
assert abs(float(px[..., 3].mean()) - 1.0) < 1e-3
assert scene.render.use_compositing is not None
print("COMPOSITE_OP OK")
