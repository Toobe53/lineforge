# LineForge — extraction cache: same frame reuses the snapshot, edits and frame
# changes invalidate it, and animated scenes render per-frame lines.
# GPL-2.0-or-later.
import sys
import traceback

import bpy
import numpy as np

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

W, H = 400, 300


def _render(renderer):
    renderer._LAST.clear()
    renderer.render(bpy.context, W, H)
    st = renderer.last_stats()
    lines = renderer.last_lines()
    xs = [float(p[0]) for ln in lines for p in ln["points"]]
    return st, lines, (min(xs), max(xs)) if xs else (0.0, 0.0)


def main():
    import lineforge
    from lineforge import nodes, renderer

    bpy.ops.wm.read_factory_settings(use_empty=True)  # clears handlers, so register after it
    try:
        lineforge.unregister()
    except Exception:  # noqa: BLE001
        pass
    lineforge.register()

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = W
    scene.render.resolution_y = H

    bpy.ops.mesh.primitive_cube_add(size=1.5, location=(0.0, 0.0, 0.0))
    cube = bpy.context.object
    bpy.ops.object.camera_add(location=(4.0, -6.0, 4.0))
    cam = bpy.context.object
    scene.camera = cam
    direction = -cam.location.normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    bpy.ops.lf.create_tree()
    for n in nodes.active_sets(scene.lf.node_tree):
        n.enabled = (n.line_type == 'OBJECT')

    st1, l1, r1 = _render(renderer)
    st2, l2, r2 = _render(renderer)
    print("FIRST", st1["cache_hit"], round(st1["extract_ms"], 1), st1["lines"])
    print("SECOND", st2["cache_hit"], round(st2["extract_ms"], 1), st2["lines"])
    assert st1["cache_hit"] is False
    assert st2["cache_hit"] is True, "same frame must reuse the snapshot"
    assert st2["extract_ms"] < st1["extract_ms"], (st1["extract_ms"], st2["extract_ms"])
    assert st1["lines"] == st2["lines"] and r1 == r2

    # --- editing geometry invalidates -------------------------------------
    for v in cube.data.vertices:
        v.co.x += 1.2
    cube.data.update()
    bpy.context.view_layer.update()
    st3, l3, r3 = _render(renderer)
    print("EDIT", st3["cache_hit"], round(st3["extract_ms"], 1), [round(v, 2) for v in r3])
    assert st3["cache_hit"] is False, "a mesh edit must invalidate the snapshot"
    assert r3 != r1

    # --- animation: one snapshot per frame --------------------------------
    for v in cube.data.vertices:
        v.co.x -= 1.2
    cube.data.update()
    cube.location = (0.0, 0.0, 0.0)
    cube.keyframe_insert("location", frame=1)
    cube.location = (2.2, 0.0, 0.0)
    cube.keyframe_insert("location", frame=10)
    scene.frame_start, scene.frame_end = 1, 10

    scene.frame_set(1)
    st4, l4, r4 = _render(renderer)
    scene.frame_set(10)
    st5, l5, r5 = _render(renderer)
    scene.frame_set(10)
    st6, l6, r6 = _render(renderer)
    print("F1", round(r4[0], 1), round(r4[1], 1))
    print("F10", round(r5[0], 1), round(r5[1], 1), "REUSE", st6["cache_hit"])
    assert r5 != r4, "animated frame must produce different lines"
    assert st6["cache_hit"] is True and r6 == r5
    assert st4["frame"] == 1 and st5["frame"] == 10

    print("CACHE OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
sys.exit(rc)
