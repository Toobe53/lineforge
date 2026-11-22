# LineForge — supersampling test: same size output, smoother edges with SSAA.
import sys

import numpy as np
import bpy

ROOT = r"C:\LineForge"
sys.path.insert(0, ROOT + r"\addon")

import lineforge  # noqa: E402

if not hasattr(bpy.types.Scene, "lf"):
    lineforge.register()

from lineforge import renderer  # noqa: E402

W, H = 320, 240


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y = W, H
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    cam.location = (3.2, 2.4, 3.6)
    direction = -cam.location.normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam
    bpy.ops.mesh.primitive_cube_add(size=1.6)
    bpy.ops.lf.create_tree()
    return scene


def render_with(ss):
    scene = build_scene()
    scene.lf.supersample = ss
    rgba = renderer.render(bpy.context, W, H)
    stats = renderer.last_stats()
    return rgba, stats


def edge_alpha_levels(rgba):
    # count distinct alpha values along the whole image (AA softness proxy)
    a = np.round(rgba[..., 3] * 255.0).astype(np.int32)
    vals = np.unique(a[(a > 0) & (a < 255)])
    return len(vals)


rgba1, st1 = render_with(1)
rgba2, st2 = render_with(2)
rgba4, st4 = render_with(4)

assert rgba1.shape == (H, W, 4), rgba1.shape
assert rgba2.shape == (H, W, 4), rgba2.shape
assert st2["supersample"] == 2, st2
assert st4["supersample"] == 4, st4


def rmse(a, b):
    return float(np.sqrt(np.mean((a[..., :4] - b[..., :4]) ** 2)))


e1 = rmse(rgba1, rgba4)
e2 = rmse(rgba2, rgba4)
print("RMSE ss1-vs-ss4", round(e1, 6), "ss2-vs-ss4", round(e2, 6))
assert e2 < e1, (e1, e2)

print("SS1 time", round(st1["total_ms"], 1), "SS2 time", round(st2["total_ms"], 1), "SS4 time", round(st4["total_ms"], 1))
assert st4["total_ms"] > st1["total_ms"], (st1["total_ms"], st4["total_ms"])

# line coordinates must be reported in final image space
lines = renderer.last_lines()
assert lines, "no lines"
for ln in lines[:50]:
    pts = np.asarray(ln["points"])
    assert pts[:, 0].max() <= W + 8 and pts[:, 1].max() <= H + 8, (pts[:, 0].max(), pts[:, 1].max())

print("SSAA OK")
