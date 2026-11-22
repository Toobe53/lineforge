# AOV / multi-pass output: line, hidden and depth passes.
# Usage: blender -b --factory-startup --python tests/blender_passes_test.py
import os
import sys
import tempfile

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "addon")
sys.path.insert(0, ADDON)

import lineforge  # noqa: E402

if not hasattr(bpy.types.Scene, "lf"):
    lineforge.register()

from lineforge import renderer  # noqa: E402


def make_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 320
    scene.render.resolution_y = 240
    scene.render.resolution_percentage = 100

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
    front = bpy.context.object
    front.name = "front_cube"
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.9, 1.2, 0.0))
    back = bpy.context.object
    back.name = "back_cube"

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -5.0, 0.0)
    direction = -cam.location.normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam

    # register handlers AFTER the factory reset (it clears them)
    if not hasattr(bpy.types.Scene, "lf"):
        lineforge.register()
    scene = bpy.context.scene
    if scene.lf.node_tree is None:
        bpy.ops.lf.create_tree()
    scene.lf.auto_composite = False
    scene.lf.auto_render_on_f12 = False
    scene.lf.supersample = 1
    scene.lf.pass_hidden = True
    scene.lf.pass_depth = True
    # keep only the object outline set, with hidden lines enabled
    for node in scene.lf.node_tree.nodes:
        if node.bl_idname == "LFLineSetNode":
            node.enabled = node.line_type == 'OBJECT'
    scene.lf.hidden_lines = True
    return scene


def main():
    scene = make_scene()
    renderer.invalidate_snapshot()
    rgba = renderer.render(bpy.context)
    stats = renderer.last_stats()
    depth = renderer.last_depth()
    hidden = renderer.last_hidden()
    assert rgba.shape == (240, 320, 4), rgba.shape
    assert depth is not None and depth.shape == (240, 320), depth
    assert hidden is not None and hidden.shape == (240, 320, 4), hidden
    print("PASS stats", {k: stats[k] for k in ("lines", "strokes", "supersample")})
    print("DEPTH %.3f..%.3f cover %.3f" % (stats["depth_min"], stats["depth_max"],
                                          stats["depth_coverage"]))
    assert stats["depth_min"] > 0.0 and stats["depth_max"] >= stats["depth_min"]
    assert 0.0 < stats["depth_coverage"] < 1.0
    print("TIMING raster %.1f strokes %.1f composite %.1f" % (
        stats["raster_ms"], stats["stroke_ms"], stats["composite_ms"]))
    assert stats["raster_ms"] > 0.0 and stats["stroke_ms"] > 0.0

    # the hidden pass only holds occluded strokes: the front cube hides the back one
    hid_alpha = hidden[..., 3]
    print("HIDDEN alpha sum %.3f max %.3f" % (hid_alpha.sum(), hid_alpha.max()))
    assert hid_alpha.max() > 0.0, "hidden pass is empty although a cube is occluded"

    images = renderer.write_all_passes(bpy.context)
    assert set(images) == {"lines", "hidden", "depth"}, set(images)
    print("IMAGES", sorted(images))

    out_dir = tempfile.mkdtemp(prefix="lineforge_passes_")
    paths = renderer.save_passes(bpy.context, os.path.join(out_dir, "shot.png"))
    print("SAVED", [os.path.basename(p) for p in paths])
    names = [os.path.basename(p) for p in paths]
    assert "shot_lines.png" in names and "shot_hidden.png" in names
    assert "shot_depth.exr" in names
    for p in paths:
        size = os.path.getsize(p)
        assert size > 100, (p, size)
        print("FILE %s %d" % (os.path.basename(p), size))

    # the offset back cube sits farther away, so the depth pass must hold two
    # clearly separated distance shells
    valid = depth[depth > 0.0]
    d_near, d_far = float(valid.min()), float(valid.max())
    print("DEPTH near %.3f far %.3f" % (d_near, d_far))
    assert d_near > 0.0 and d_far - d_near > 0.5, (d_near, d_far)
    assert abs(float(depth[120, 160]) - d_near) < 1e-3

    print("PASSES OK")


if __name__ == "__main__":
    main()
