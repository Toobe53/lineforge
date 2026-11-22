# LineForge — viewport overlay (camera view) using cached polylines.
# GPL-2.0-or-later.
import math

import bpy
import numpy as np

from . import renderer

_HANDLE = None
_DIRTY = {"value": True}
_SHADER = {"obj": None, "name": None, "failed": False}


def mark_dirty(*_args, **_kwargs):
    _DIRTY["value"] = True


def _shader():
    if _SHADER["failed"]:
        return None
    if _SHADER["obj"] is not None:
        return _SHADER["obj"]
    try:
        import gpu
    except Exception:
        _SHADER["failed"] = True
        return None
    for name in ("UNIFORM_COLOR", "2D_UNIFORM_COLOR", "FLAT_COLOR", "SMOOTH_COLOR"):
        try:
            _SHADER["obj"] = gpu.shader.from_builtin(name)
            _SHADER["name"] = name
            return _SHADER["obj"]
        except Exception:
            continue
    _SHADER["failed"] = True
    return None


def _triangle_strip(points, widths):
    """Build triangles (screen px, top-left origin) for a variable width polyline."""
    pts = np.asarray(points, np.float32)
    w = np.asarray(widths, np.float32) if widths is not None else np.ones(len(pts), np.float32)
    if pts.shape[0] < 2:
        return None
    n = pts.shape[0]
    # per-point tangent
    tang = np.zeros((n, 2), np.float32)
    tang[1:-1] = pts[2:] - pts[:-2]
    tang[0] = pts[1] - pts[0]
    tang[-1] = pts[-1] - pts[-2]
    lens = np.linalg.norm(tang, axis=1)
    lens[lens < 1e-6] = 1.0
    tang /= lens[:, None]
    nrm = np.stack((-tang[:, 1], tang[:, 0]), axis=1) * (w * 0.5)[:, None]
    left = pts + nrm
    right = pts - nrm
    tris = np.empty(((n - 1) * 6, 2), np.float32)
    for i in range(n - 1):
        a, b = left[i], right[i]
        c, d = left[i + 1], right[i + 1]
        tris[6 * i + 0] = a
        tris[6 * i + 1] = b
        tris[6 * i + 2] = c
        tris[6 * i + 3] = b
        tris[6 * i + 4] = d
        tris[6 * i + 5] = c
    return tris


def _build(region_w, region_h, render_w, render_h):
    lines = renderer.last_lines()
    if not lines:
        return []
    sx = region_w / max(1.0, float(render_w))
    sy = region_h / max(1.0, float(render_h))
    groups = {}
    for pl in lines:
        tris = _triangle_strip(pl["points"], pl["widths"])
        if tris is None:
            continue
        col = tuple(round(float(c), 2) for c in pl["color"][:3])
        alpha = round(float(pl["color"][3]), 2)
        if alpha <= 0.01:
            continue
        t = tris.copy()
        t[:, 0] *= sx
        t[:, 1] = region_h - t[:, 1] * sy
        groups.setdefault((col, alpha), []).append(t)
    out = []
    for (col, alpha), chunks in groups.items():
        arr = np.concatenate(chunks, axis=0)
        out.append((col, alpha, arr))
    return out


def draw():
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except Exception:
        return
    ctx = bpy.context
    scene = ctx.scene
    if scene is None or not hasattr(scene, "lf"):
        return
    lf = scene.lf
    if not lf.enabled or not lf.overlay_enabled:
        return
    space = ctx.space_data
    region = ctx.region
    if space is None or region is None:
        return
    rv3d = space.region_3d
    if rv3d is None or rv3d.view_perspective != 'CAMERA':
        return
    if not space.overlay.show_overlays:
        return
    stats = renderer.last_stats()
    size = stats.get("size") or (0, 0)
    if not stats or size[0] <= 0:
        return
    shader = _shader()
    if shader is None:
        return

    groups = _build(region.width, region.height, size[0], size[1])
    if not groups:
        return
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    try:
        gpu.matrix.load_identity()
    except Exception:
        pass
    try:
        for col, alpha, arr in groups:
            shader.uniform_float("color", (col[0], col[1], col[2], alpha))
            batch = batch_for_shader(shader, 'TRIS', {"pos": arr})
            batch.draw(shader)
    finally:
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('LESS_EQUAL')


def _frame(scene, *_args):
    # Cheap "camera or scene changed" invalidation (rendering is done on demand).
    mark_dirty()


def register():
    global _HANDLE
    if _HANDLE is None:
        _HANDLE = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _HANDLE
    if _HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLE, 'WINDOW')
        _HANDLE = None
