# LineForge — hair curves must render as strand lines, and must respect depth.
# GPL-2.0-or-later.
import sys
import traceback

import bpy
import numpy as np

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

W, H = 480, 320


def _hair_object(name, strands, radius=0.01):
    cv = bpy.data.hair_curves.new(name)
    lengths = [len(s) for s in strands]
    cv.add_curves(lengths)
    pts = np.array([p for s in strands for p in s], np.float32)
    cv.points.foreach_set("position", pts.reshape(-1))
    try:
        cv.attributes["radius"].data.foreach_set("value", np.full(len(pts), radius, np.float32))
    except Exception:
        pass
    ob = bpy.data.objects.new(name, cv)
    bpy.context.collection.objects.link(ob)
    return ob


def main():
    import lineforge
    from lineforge import nodes, renderer
    from lineforge.scene_extract import extract

    try:
        lineforge.unregister()
    except Exception:  # noqa: BLE001
        pass
    lineforge.register()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = W
    scene.render.resolution_y = H

    # three vertical strands in front of the camera
    _hair_object("HairA", [[(-0.4 + 0.4 * i, 0.0, t) for t in np.linspace(-1.2, 1.2, 12)]
                           for i in range(3)])

    bpy.ops.object.camera_add(location=(0.0, -10.0, 0.0), rotation=(np.pi / 2.0, 0.0, 0.0))
    scene.camera = bpy.context.object
    scene.camera.data.lens = 50.0

    bpy.ops.lf.create_tree()
    for n in nodes.active_sets(scene.lf.node_tree):
        n.enabled = (n.line_type == 'OBJECT')

    # --- extraction level -------------------------------------------------
    snap = extract(bpy.context, W, H)
    print("STRAIDS", snap.nstrands, "PTS", 0 if snap.strand_pts is None else len(snap.strand_pts))
    assert snap.nstrands == 3, snap.nstrands
    assert snap.strand_pts is not None and len(snap.strand_pts) == 36, len(snap.strand_pts)
    assert snap.strand_offsets[-1] == len(snap.strand_pts)
    assert snap.tris.shape[0] == 0, "curves-only scene must not fabricate triangles"

    # --- render level -----------------------------------------------------
    renderer._LAST.clear()
    rgba = renderer.render(bpy.context, W, H)
    lines = renderer.last_lines()
    alpha = rgba[..., 3]
    print("LINES", len(lines), "COVERAGE", round(float((alpha > 1e-3).mean()), 5))
    assert len(lines) == 3, len(lines)
    assert float((alpha > 1e-3).mean()) > 0.003
    for ln in lines:  # strand colour comes from the outline style
        assert len(ln["widths"]) == len(ln["points"]), ln

    # --- strands are depth tested against surfaces ------------------------
    bpy.ops.mesh.primitive_cube_add(size=1.5, location=(0.0, -4.0, 0.0))
    renderer._LAST.clear()
    renderer.render(bpy.context, W, H)
    blocked = float((renderer._LAST["image"][..., 3] > 1e-3).mean())
    print("BLOCKED COVERAGE", round(blocked, 5), "WAS", round(float((alpha > 1e-3).mean()), 5))
    assert blocked > 0.0, "cube itself should draw"

    # --- hair toggle (the cube keeps the scene drawable) -------------------
    snap_off = extract(bpy.context, W, H, hair=False)
    print("OFF STRAIDS", snap_off.nstrands)
    assert snap_off.nstrands == 0 and snap_off.strand_pts is None
    assert snap_off.tris.shape[0] > 0
    bpy.data.objects.remove(bpy.context.object, do_unlink=True)

    print("STRAND OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
sys.exit(rc)
