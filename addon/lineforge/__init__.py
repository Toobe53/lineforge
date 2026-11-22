# LineForge — Blender 5.2 line-art renderer.
# GPL-2.0-or-later.
bl_info = {
    "name": "LineForge",
    "author": "LineForge contributors",
    "version": (0, 2, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > LineForge",
    "description": "CPU line-art renderer: silhouette, crease, border, material and intersection lines",
    "category": "Render",
}

import bpy

from . import nodes, properties, operators, panels, overlay, renderer


def _render_pre(scene, *_args):
    if renderer._SUPPRESS_HANDLER:
        return
    lf = getattr(scene, "lf", None)
    if lf is None or not lf.enabled or not lf.auto_render_on_f12:
        return
    if lf.node_tree is None:
        return
    try:
        ctx = bpy.context
        rgba = renderer.render(ctx)
        img = renderer.write_pass_image(ctx, rgba)
        renderer.setup_compositor(ctx, img)
        st = renderer.last_stats()
        lf.stats_text = "lines %d | strokes %d | %dx%d | total %.1f ms" % (
            st.get("lines", 0), st.get("strokes", 0),
            st["size"][0], st["size"][1], st.get("total_ms", 0.0))
        lf.last_error = ""
    except Exception as exc:  # noqa: BLE001 - never break F12 because of the line pass
        lf.last_error = str(exc) or type(exc).__name__
        print("[LineForge] render_pre failed:", exc)


def _depsgraph_update(scene, *_args):
    overlay.mark_dirty()


_MODULES = (nodes, properties, operators, panels)


def register():
    for mod in _MODULES:
        mod.register()
    overlay.register()
    if _render_pre not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(_render_pre)
    if _depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update)


def unregister():
    if _depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update)
    if _render_pre in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(_render_pre)
    overlay.unregister()
    for mod in reversed(_MODULES):
        mod.unregister()
