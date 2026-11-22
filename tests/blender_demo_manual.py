# LineForge demo: beauty render + line pass, composited in numpy (deterministic).
# Usage: blender -b --factory-startup --python tests/blender_demo_manual.py
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
OUT_DIR = os.path.join(ROOT, "docs")
os.makedirs(OUT_DIR, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=BLEND)
scene = bpy.context.scene
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.resolution_percentage = 100

if scene.lf.node_tree is None:
    bpy.ops.lf.create_tree()
scene.lf.line_scale = 1.0
scene.lf.hidden_lines = False
scene.lf.auto_composite = False

# 1) line pass from the native core
rgba = renderer.render(bpy.context)
stats = renderer.last_stats()
print("STATS", stats)

pass_img = renderer.write_pass_image(bpy.context, rgba, name="LineForge Demo Pass")
pass_img.filepath_raw = os.path.join(OUT_DIR, "line_pass_1080p.png")
pass_img.file_format = 'PNG'
pass_img.save()
print("PASS", pass_img.filepath_raw)

# 2) beauty render without any lineforge compositing (display-referred, Standard view)
scene.render.use_compositing = False
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.filepath = os.path.join(OUT_DIR, "beauty_1080p.png")
bpy.ops.render.render(write_still=True)
print("BEAUTY", scene.render.filepath)

# 3) composite in display space: line pass (linear -> sRGB) over beauty (already sRGB)
beauty = bpy.data.images.load(scene.render.filepath)
beauty.colorspace_settings.name = 'Non-Color'
beauty.reload()
bw, bh = beauty.size
b = np.array(beauty.pixels[:], dtype=np.float32).reshape(bh, bw, 4)


def to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


a = rgba[::-1, :, 3:4]
lin = rgba[::-1, :, :3]
nz = a[..., 0] > 1e-6
lin_rgb = np.where(nz[..., None], lin / np.maximum(a, 1e-6), 0.0)
line_rgb = to_srgb(lin_rgb)
out = np.empty_like(b)
out[..., :3] = line_rgb * a + b[..., :3] * (1.0 - a)
out[..., 3] = 1.0

comp = bpy.data.images.new("LineForge Demo Composite", bw, bh, alpha=False, float_buffer=True)
comp.colorspace_settings.name = 'Non-Color'
comp.pixels.foreach_set(np.ascontiguousarray(out.reshape(-1), np.float32))
comp.filepath_raw = os.path.join(OUT_DIR, "composite_1080p.png")
comp.file_format = 'PNG'
comp.save()
print("COMPOSITE", comp.filepath_raw)
print("DEMO OK")
