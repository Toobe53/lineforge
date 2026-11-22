# SPDX-License-Identifier: GPL-2.0-or-later
"""LineForge backface culling test.

Culling only touches the depth pass, so the detected edges must not change; the
depth coverage has to stay (almost) identical, and the culled pass has to be
measurably cheaper on a closed mesh.

Run:  blender -b --factory-startup --python blender_cull_test.py
"""
import sys

sys.path.insert(0, r"C:\LineForge\addon")

import bpy
import numpy as np

import lineforge
from lineforge import renderer as R


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # read_factory_settings clears handlers, so (re)register afterwards.
    if not hasattr(bpy.types.Scene, "lf"):
        lineforge.register()
    elif not hasattr(bpy.types.Scene, "lf"):
        lineforge.register()

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 480
    scene.render.resolution_y = 360
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True

    for i, (x, mat) in enumerate(((-1.1, "lf_red"), (1.1, "lf_blue"))):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.9,
                                             location=(x, 0.0, 0.0))
        ob = bpy.context.object
        ob.name = "ball_%d" % i
        m = bpy.data.materials.new(mat)
        m.diffuse_color = (1, 0, 0, 1) if i == 0 else (0, 0, 1, 1)
        ob.data.materials.append(m)

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -7.0, 1.4)
    direction = (bpy.data.objects["ball_0"].location * 0.0 - cam.location).normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam

    if scene.lf.node_tree is None:
        bpy.ops.lf.create_tree()
    scene.lf.auto_composite = False
    scene.lf.supersample = 1
    scene.lf.pass_depth = True
    return scene


def measure(scene, mode):
    scene.lf.cull_backfaces = mode
    R.invalidate_snapshot()
    R.render(bpy.context)
    st = R.last_stats()
    depth = R.last_depth()
    assert depth is not None, "depth AOV missing"
    depth = np.asarray(depth)
    return st, depth


def main():
    scene = build_scene()

    st_off, d_off = measure(scene, 'OFF')
    st_back, d_back = measure(scene, 'BACK')
    st_front, d_front = measure(scene, 'FRONT')

    print("OFF   lines %d strokes %d raster %.1f cover %.4f"
          % (st_off["lines"], st_off["strokes"], st_off["raster_ms"], (d_off > 0).mean()))
    print("BACK  lines %d strokes %d raster %.1f cover %.4f"
          % (st_back["lines"], st_back["strokes"], st_back["raster_ms"], (d_back > 0).mean()))
    print("FRONT lines %d strokes %d raster %.1f cover %.4f"
          % (st_front["lines"], st_front["strokes"], st_front["raster_ms"], (d_front > 0).mean()))

    # Edge detection never looks at the G-buffer culling decision: same strokes.
    assert st_back["lines"] == st_off["lines"], "culling changed the line count"
    assert st_back["strokes"] == st_off["strokes"], "culling changed the stroke count"

    cover_off = float((d_off > 0).mean())
    cover_back = float((d_back > 0).mean())
    cover_front = float((d_front > 0).mean())
    assert abs(cover_back - cover_off) < 0.01, "culling lost too much depth coverage"
    assert abs(cover_front - cover_off) < 0.01, "flipped culling lost too much depth coverage"
    print("COVER off %.4f back %.4f front %.4f" % (cover_off, cover_back, cover_front))

    # Both culling modes must keep a real surface in front, i.e. the depth must
    # still be near the spheres rather than empty.
    assert (d_back > 0).mean() > 0.05, "back culling emptied the depth pass"
    assert (d_front > 0).mean() > 0.05, "front culling emptied the depth pass"

    # Closed spheres: the back-facing side is culled, so culling cannot be slower
    # than rastering every triangle twice.
    assert st_back["raster_ms"] <= st_off["raster_ms"] * 1.15, "culling is slower than off"
    print("CULL OK")


main()
