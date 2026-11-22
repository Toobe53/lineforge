# Image based brush texture: a loaded image modulates line width along strokes.
# Usage: blender -b --factory-startup --python tests/blender_brush_image_test.py
import os
import sys

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "addon"))

import lineforge  # noqa: E402

if not hasattr(bpy.types.Scene, "lf"):
    lineforge.register()

from lineforge import renderer, nodes  # noqa: E402


def stripe_image(name, w=512, h=8):
    """Vertical stripes: every other column is black, the rest white."""
    img = bpy.data.images.get(name)
    if img is not None:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    buf = np.ones((h, w, 4), np.float32)
    cols = np.arange(w)
    dark = (cols // 16) % 2 == 0
    buf[:, dark, :3] = 0.0
    img.pixels.foreach_set(np.ascontiguousarray(buf.reshape(-1), np.float32))
    img.update()
    return img


def make_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 480
    scene.render.resolution_y = 360
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.4)
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (3.4, -4.6, 3.0)
    direction = -cam.location.normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    if not hasattr(bpy.types.Scene, "lf"):
        lineforge.register()
    scene = bpy.context.scene
    if scene.lf.node_tree is None:
        bpy.ops.lf.create_tree()
    scene.lf.auto_composite = False
    scene.lf.auto_render_on_f12 = False
    scene.lf.supersample = 1
    for node in scene.lf.node_tree.nodes:
        if node.bl_idname == "LFLineSetNode":
            node.enabled = node.line_type == 'OBJECT'
    return scene


def profile_of_widths(lines):
    vals = []
    for ln in lines:
        w = np.asarray(ln["widths"], np.float32)
        if w.size:
            vals.append(w)
    return np.concatenate(vals) if vals else np.zeros(0, np.float32)


def main():
    scene = make_scene()
    tree = scene.lf.node_tree
    node = None
    for n in tree.nodes:
        if n.bl_idname == "LFLineSetNode" and n.line_type == 'OBJECT':
            node = n
            break
    assert node is not None

    renderer.invalidate_snapshot()
    renderer.render(bpy.context)
    base = profile_of_widths(renderer.last_lines())
    print("BASE n %d std %.4f" % (base.size, float(base.std())))

    img = stripe_image("lf_stripes")
    node.texture_image = img
    node.texture_channel = 'LUMA'
    node.texture_amp = 0.9
    node.texture_repeat = 2.0
    renderer.invalidate_snapshot()
    renderer.render(bpy.context)
    striped = profile_of_widths(renderer.last_lines())
    print("STRIPED n %d std %.4f" % (striped.size, float(striped.std())))
    assert striped.size == base.size, (striped.size, base.size)
    assert striped.std() > base.std() * 3.0 + 1e-4, (striped.std(), base.std())
    assert striped.min() < base.min() * 0.95

    prof = renderer._image_profile(img, 'LUMA', False)
    print("PROFILE n %d min %.3f max %.3f" % (len(prof), min(prof), max(prof)))
    assert len(prof) > 8 and min(prof) <= 0.05 + 1e-6 and max(prof) >= 0.999

    inv = renderer._image_profile(img, 'LUMA', True)
    print("INVERT first %.3f vs %.3f" % (inv[0], prof[0]))
    assert abs(inv[0] - (1.0 - prof[0])) < 0.06 or inv[0] != prof[0]

    # invert through the node must flip which columns are thick
    node.texture_invert = True
    renderer.invalidate_snapshot()
    renderer.render(bpy.context)
    inv_lines = profile_of_widths(renderer.last_lines())
    print("INVERTED std %.4f" % float(inv_lines.std()))
    assert inv_lines.std() > base.std() * 3.0 + 1e-4

    # clearing the image falls back to the preset brush (uniform again)
    node.texture_invert = False
    node.texture_image = None
    renderer.invalidate_snapshot()
    renderer.render(bpy.context)
    cleared = profile_of_widths(renderer.last_lines())
    print("CLEARED std %.4f" % float(cleared.std()))
    assert cleared.std() <= base.std() + 1e-3

    print("BRUSH IMAGE OK")


if __name__ == "__main__":
    main()
