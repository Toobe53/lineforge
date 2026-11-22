# LineForge — per-line-set object/material filters must restrict the pass.
# GPL-2.0-or-later.
import math
import sys
import traceback

import bpy

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

W, H = 480, 320


def _mat(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1.0)
    return mat


def _cube(name, x, mat):
    bpy.ops.mesh.primitive_cube_add(size=1.2, location=(x, 0.0, 0.0))
    ob = bpy.context.object
    ob.name = name
    ob.data.materials.append(mat)
    return ob


def _render(nodes, renderer, **filters):
    node = nodes.active_sets(bpy.context.scene.lf.node_tree)[0]
    for key in ("filter_objects", "exclude_objects", "filter_materials", "exclude_materials"):
        setattr(node, key, filters.get(key, ""))
    renderer._LAST.clear()
    rgba = renderer.render(bpy.context, W, H)
    lines = renderer.last_lines()
    xs = [p[0] for ln in lines for p in ln["points"]]
    return len(lines), xs, int((rgba[..., 3] > 1e-3).sum())


def main():
    import lineforge
    from lineforge import nodes, renderer

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

    red, blue = _mat("lf_red", (0.9, 0.1, 0.1)), _mat("lf_blue", (0.1, 0.2, 0.9))
    _cube("cube_a", -1.2, red)
    _cube("cube_b", 1.2, blue)

    bpy.ops.object.camera_add(location=(0.0, -6.0, 0.0), rotation=(math.pi / 2.0, 0.0, 0.0))
    scene.camera = bpy.context.object
    scene.camera.data.lens = 60.0

    bpy.ops.lf.create_tree()
    tree = scene.lf.node_tree
    for n in nodes.active_sets(tree):
        n.enabled = (n.line_type == 'OBJECT')

    total, xs_all, cov_all = _render(nodes, renderer)
    a_only, xs_a, cov_a = _render(nodes, renderer, filter_objects="cube_a")
    b_only, xs_b, cov_b = _render(nodes, renderer, filter_materials="lf_blue")
    mat_wild, xs_w, cov_w = _render(nodes, renderer, filter_materials="lf_*")
    skipped, xs_s, cov_s = _render(nodes, renderer, exclude_objects="cube_a")

    print("TOTAL", total, "A_ONLY", a_only, "B_ONLY", b_only, "WILD", mat_wild, "SKIP_A", skipped)
    print("X_RANGE A", round(min(xs_a), 1), round(max(xs_a), 1),
          "B", round(min(xs_b), 1), round(max(xs_b), 1))

    assert total >= 2, total
    assert a_only and b_only and mat_wild and skipped, (a_only, b_only, mat_wild, skipped)
    assert max(xs_a) < W / 2.0, max(xs_a)          # cube_a is on the left
    assert min(xs_b) > W / 2.0, min(xs_b)          # cube_b is on the right
    assert mat_wild == total and skipped == total - a_only, (mat_wild, total, skipped)
    assert cov_a < cov_all and cov_b < cov_all, (cov_a, cov_b, cov_all)

    print("FILTER OK")
    return 0


try:
    rc = main()
except Exception:
    traceback.print_exc()
    rc = 1
sys.exit(rc)
