# LineForge — see-through faces must not be rasterised or outlined.
# GPL-2.0-or-later.
import sys
import traceback

import bpy

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

W, H = 320, 240


def _alpha_texture(alpha):
    """An image whose alpha channel is `alpha` everywhere (colour is white)."""
    img = bpy.data.images.new("lf_alpha", 16, 16, alpha=True)
    px = [1.0, 1.0, 1.0, alpha] * (16 * 16)
    img.pixels.foreach_set(px)
    img.pack()
    return img


def _sheer_material(alpha):
    mat = bpy.data.materials.new("sheer_%s" % alpha)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = _alpha_texture(alpha)
    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    mat.blend_method = 'HASHED'
    mat.diffuse_color = (0.2, 0.3, 0.8, 1.0)
    return mat


def _cube(name, location, material):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    ob = bpy.context.object
    ob.name = name
    if material is not None:
        ob.data.materials.append(material)
    return ob


def _camera():
    bpy.ops.object.camera_add(location=(3.6, -3.0, 2.4))
    cam = bpy.context.object
    direction = -cam.location.normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = 50.0
    bpy.context.scene.camera = cam
    return cam


def _render(skip_transparent):
    scene = bpy.context.scene
    lf = scene.lf
    lf.skip_transparent_faces = skip_transparent
    lf.alpha_threshold = 0.5
    lf.supersample = 1
    renderer._LAST.clear()
    rgba = renderer.render(bpy.context, W, H)
    stats = renderer.last_stats()
    lines = renderer.last_lines()
    covered = int((rgba[..., 3] > 1e-3).sum())
    xs = [p[0] for ln in lines for p in ln["points"]]
    return stats, covered, xs


def main():
    import lineforge
    from lineforge import nodes, renderer  # noqa: F401
    globals()["nodes"] = nodes
    globals()["renderer"] = renderer
    try:
        lineforge.unregister()
    except Exception:
        pass
    lineforge.register()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = W
    scene.render.resolution_y = H

    sheer = _sheer_material(0.05)
    opaque = bpy.data.materials.new("opaque")
    opaque.use_nodes = True
    opaque.diffuse_color = (0.8, 0.2, 0.2, 1.0)

    # The sheer cube sits in front of the opaque one and hides it completely.
    _cube("front_sheer", (0.0, 0.0, 0.0), sheer)
    _cube("back_opaque", (-0.9, 0.5, -1.2), opaque)
    # Above the cutoff (0.7 > 0.5), so this one must stay visible.
    _cube("edge_sheer", (1.5, 0.9, 0.7), _sheer_material(0.7))
    _camera()

    bpy.ops.lf.create_tree()
    tree = scene.lf.node_tree
    # One line set only (OBJECT), so the comparison is easy to reason about.
    for n in nodes.active_sets(tree):
        n.enabled = (n.line_type == 'OBJECT')

    stats_on, covered_on, xs_on = _render(True)
    stats_off, covered_off, xs_off = _render(False)
    print("SKIP_ON", stats_on["lines"], "tris", stats_on.get("tris"), "covered", covered_on)
    print("SKIP_OFF", stats_off["lines"], "tris", stats_off.get("tris"), "covered", covered_off)

    assert stats_off["lines"] >= 2, stats_off
    assert stats_on["lines"] < stats_off["lines"], (stats_on["lines"], stats_off["lines"])
    assert covered_on < covered_off, (covered_on, covered_off)
    assert xs_off and xs_on, (len(xs_off), len(xs_on))

    # A fully transparent cube must leave nothing behind in the G-buffer, while the
    # 0.7-alpha cube (above the 0.5 cutoff) stays in.
    snap = __import__("lineforge.scene_extract", fromlist=["x"]).extract(
        bpy.context, W, H, skip_transparent=True)
    skip = list(snap.tri_skip)
    skipped = sum(1 for s in skip if s)
    print("SKIPPED_TRIS", skipped, "of", len(skip))
    assert skipped == 12, skipped

    # Whitelisting by material name keeps the sheer cube in the pass.
    snap_keep = __import__("lineforge.scene_extract", fromlist=["x"]).extract(
        bpy.context, W, H, skip_transparent=True, transparent_keep=("sheer_0.05",))
    print("WHITELIST_SKIP", sum(1 for s in snap_keep.tri_skip if s))
    assert sum(1 for s in snap_keep.tri_skip if s) == 0, "whitelist must disable skipping"

    # Coverage scoring: the peak term keeps a triangle that contains some opaque ink,
    # while a uniformly transparent triangle is dropped.
    import numpy as np
    from lineforge import scene_extract

    corners = np.array([
        [[0.1, 0.1], [0.1, 0.2], [0.2, 0.1]],     # all transparent
        [[0.8, 0.8], [0.8, 0.9], [0.9, 0.8]],     # all opaque
        [[0.45, 0.5], [0.9, 0.5], [0.5, 0.9]],    # partially covered
    ], np.float32)

    def sample(u, v):
        return np.where((u > 0.5) & (v > 0.5), 1.0, 0.2).astype(np.float32)

    score = scene_extract._alpha_coverage(corners, sample)
    print("COVERAGE_SCORE", [round(float(s), 3) for s in score])
    assert score[0] < 0.5, score
    assert score[1] > 0.9, score
    assert score[2] > 0.5, score

    renderer.reset_core()
    print("TRANSPARENT OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
sys.exit(rc)
