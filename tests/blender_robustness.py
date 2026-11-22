# LineForge — robustness test: core loading, empty scenes, degenerate geometry, ortho camera.
import sys

import bpy
import numpy as np

ROOT = r"C:\LineForge"
sys.path.insert(0, ROOT + r"\addon")

import lineforge  # noqa: E402

if not hasattr(bpy.types.Scene, "lf"):
    lineforge.register()

from lineforge import renderer  # noqa: E402
from lineforge.errors import LineForgeError  # noqa: E402

W, H = 160, 120


def fresh_scene(with_camera=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = W, H
    if with_camera:
        cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        cam.location = (3.2, 2.4, 3.6)
        direction = -cam.location.normalized()
        cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
        scene.collection.objects.link(cam)
        scene.camera = cam
    return scene


# 1. core status ------------------------------------------------------------
info = renderer.core_info()
assert info["available"], info
assert info["version"] == renderer.ADDON_VERSION, info
assert "bin" in info["path"].lower(), info
print("CORE OK", info["version"], renderer.platform_tag())

# 2. no camera --------------------------------------------------------------
scene = fresh_scene(with_camera=False)
bpy.ops.mesh.primitive_cube_add(size=1.0)
bpy.ops.lf.create_tree()
try:
    renderer.render(bpy.context)
except LineForgeError as exc:
    assert "camera" in str(exc).lower(), str(exc)
    print("NO CAMERA OK")
else:
    raise AssertionError("expected a LineForgeError for a scene without camera")

# 3. empty scene (camera, no meshes) ---------------------------------------
scene = fresh_scene()
bpy.ops.lf.create_tree()
try:
    renderer.render(bpy.context)
except LineForgeError as exc:
    assert "no renderable mesh" in str(exc).lower(), str(exc)
    print("EMPTY SCENE OK")
else:
    raise AssertionError("expected a LineForgeError for an empty scene")

# 4. degenerate triangle must not produce NaNs ------------------------------
scene = fresh_scene()
bpy.ops.mesh.primitive_cube_add(size=1.0)
me = bpy.data.meshes.new("Degenerate")
me.from_pydata([(-2.0, -2.0, -2.0), (-1.0, -2.0, -2.0), (0.0, -2.0, -2.0)], [], [(0, 1, 2)])
me.validate(verbose=False)
me.update()
ob = bpy.data.objects.new("Degenerate", me)
scene.collection.objects.link(ob)
bpy.ops.lf.create_tree()
rgba = renderer.render(bpy.context)
assert np.isfinite(rgba).all(), "non-finite pixels from degenerate geometry"
print("DEGENERATE OK", float(rgba[..., 3].sum()))

# 5. orthographic camera + world-space width --------------------------------
scene = fresh_scene()
bpy.ops.mesh.primitive_cube_add(size=1.0)
scene.camera.data.type = 'ORTHO'
scene.camera.data.ortho_scale = 4.0
bpy.ops.lf.create_tree()
tree = scene.lf.node_tree
sets = [n for n in tree.nodes if n.bl_idname == "LFLineSetNode"]
sets[0].world_space = True
accum = renderer.render(bpy.context)
st = renderer.last_stats()
assert np.isfinite(accum).all()
assert st["lines"] > 0, "orthographic camera produced no lines"
print("ORTHO OK", st["lines"], "alpha", round(float(accum[..., 3].sum()), 2))

# 6. resolution guard -------------------------------------------------------
try:
    renderer.render(bpy.context, 0, 10)
except LineForgeError as exc:
    assert "resolution" in str(exc).lower(), str(exc)
    print("RESOLUTION GUARD OK")
else:
    raise AssertionError("expected a resolution guard error")

print("ROBUSTNESS OK")
