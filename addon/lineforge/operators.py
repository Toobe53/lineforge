# LineForge — operators.
# GPL-2.0-or-later.
import os
import tempfile

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from . import nodes as lfnodes
from . import renderer


def _stats_line(stats):
    size = stats.get("size") or (0, 0)
    extra = " | ss=%d" % stats["supersample"] if stats.get("supersample") else ""
    return "lines %d | strokes %d | %dx%d | core %.1f ms | total %.1f ms%s" % (
        stats.get("lines", 0), stats.get("strokes", 0), size[0], size[1],
        stats.get("core_ms", 0.0), stats.get("total_ms", 0.0), extra)


def _record(context, stats):
    lf = context.scene.lf
    lf.stats_text = _stats_line(stats)
    lf.last_error = ""
    return lf.stats_text


def _fail(op, context, exc, prefix):
    """Report a failure to the user (no traceback) and keep the message in the sidebar."""
    lf = context.scene.lf
    msg = str(exc) or type(exc).__name__
    lf.last_error = msg
    op.report({'ERROR'}, "%s: %s" % (prefix, msg.splitlines()[0][:200]))
    return {'CANCELLED'}


def _default_tree(scene):
    tree = scene.lf.node_tree
    if tree is not None and any(n.bl_idname == "LFLineSetNode" for n in tree.nodes):
        return tree
    if tree is None:
        tree = bpy.data.node_groups.new("LineForge", "LFNodeTree")
        scene.lf.node_tree = tree
    tree.nodes.clear()

    out = tree.nodes.new("LFOutputNode")
    out.location = (420, 60)

    specs = [
        ("Outline", 'OBJECT', 3.0, (0.0, 0.0, 0.0, 1.0), (0, 220)),
        ("Crease", 'CREASE', 1.6, (0.05, 0.05, 0.05, 1.0), (0, 40)),
        ("Border", 'BOUNDARY', 1.2, (0.05, 0.05, 0.05, 1.0), (0, -140)),
        ("Intersection", 'INTERSECTION', 2.0, (0.0, 0.0, 0.0, 1.0), (0, -320)),
    ]
    for name, ltype, width, color, loc in specs:
        n = tree.nodes.new("LFLineSetNode")
        n.name = name
        n.label = name
        n.location = loc
        n.line_type = ltype
        n.width = width
        n.color = color
        n.taper_in = 0.0
        n.taper_out = 0.0
    # link every line set to the output, in order
    out_sockets = [s for s in out.inputs if s.bl_idname == "LFLineSetSocket"]
    sets = [n for n in tree.nodes if n.bl_idname == "LFLineSetNode"]
    for i, n in enumerate(sets):
        if i < len(out_sockets):
            tree.links.new(n.outputs[0], out_sockets[i])
    return tree


class LF_OT_create_tree(Operator):
    bl_idname = "lf.create_tree"
    bl_label = "Create LineForge Tree"
    bl_description = "Create a LineForge node tree with a default line set setup"
    bl_options = {'UNDO'}

    def execute(self, context):
        try:
            _default_tree(context.scene)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge: could not create the node tree")
        context.scene.lf.last_error = ""
        self.report({'INFO'}, "LineForge node tree ready")
        return {'FINISHED'}


class LF_OT_add_lineset(Operator):
    bl_idname = "lf.add_lineset"
    bl_label = "Add Line Set"
    bl_description = "Add a line set node to the active LineForge tree"
    bl_options = {'UNDO'}

    def execute(self, context):
        try:
            tree = context.scene.lf.node_tree
            if tree is None:
                tree = _default_tree(context.scene)
            node = tree.nodes.new("LFLineSetNode")
            node.location = (context.space_data.cursor_location if context.space_data else (0, 0))
            node.color = (0.0, 0.0, 0.0, 1.0)
            out = lfnodes.output_node(tree)
            if out is not None:
                socks = [s for s in out.inputs if s.bl_idname == "LFLineSetSocket"]
                free = [s for s in socks if not s.is_linked]
                if free:
                    tree.links.new(node.outputs[0], free[0])
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge: could not add a line set")
        return {'FINISHED'}


class LF_OT_render(Operator):
    bl_idname = "lf.render_still"
    bl_label = "Render With LineForge"
    bl_description = "Render line art and composite it into the scene render"
    bl_options = {'REGISTER'}

    write_file: BoolProperty(name="Save Image", default=False)
    filepath: StringProperty(name="File Path", subtype='FILE_PATH', default="")

    def execute(self, context):
        lf = context.scene.lf
        if not lf.enabled:
            self.report({'WARNING'}, "LineForge is disabled")
            return {'CANCELLED'}
        try:
            renderer._SUPPRESS_HANDLER = True
            path = self.filepath if self.write_file else None
            if path and not path.lower().endswith(('.png', '.exr', '.jpg')):
                path = bpy.path.abspath(path) + ".png"
            renderer.render_still(context, path)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge render failed")
        finally:
            renderer._SUPPRESS_HANDLER = False
        self.report({'INFO'}, _record(context, renderer.last_stats()))
        return {'FINISHED'}


class LF_OT_render_composite(Operator):
    bl_idname = "lf.render_composite"
    bl_label = "Render Line Art PNG"
    bl_description = "Render the beauty and the line pass and save one merged PNG without using the compositor"
    bl_options = {'REGISTER'}

    filepath: StringProperty(name="File", subtype='FILE_PATH', default="")

    def execute(self, context):
        path = self.filepath
        if path and not path.lower().endswith('.png'):
            path = bpy.path.abspath(path) + ".png"
        try:
            renderer._SUPPRESS_HANDLER = True
            out, st = renderer.render_composite(context, path or None)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge composite failed")
        finally:
            renderer._SUPPRESS_HANDLER = False
        _record(context, st)
        self.report({'INFO'}, "Saved " + out)
        return {'FINISHED'}


class LF_OT_preview(Operator):
    bl_idname = "lf.preview"
    bl_label = "Preview Lines"
    bl_description = "Render the line pass and show it in an Image Editor"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            rgba = renderer.render(context)
            img = renderer.write_pass_image(context, rgba)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge preview failed")
        try:
            for area in context.screen.areas if context.screen else []:
                if area.type == 'IMAGE_EDITOR':
                    area.spaces.active.image = img
                    break
        except Exception:  # noqa: BLE001 - background mode has no screen
            pass
        _record(context, renderer.last_stats())
        self.report({'INFO'}, "Rendered line pass: " + img.name)
        return {'FINISHED'}


class LF_OT_save_pass(Operator):
    bl_idname = "lf.save_pass"
    bl_label = "Save Line Pass PNG"
    bl_description = "Write the line pass to a PNG next to the blend file"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            rgba = renderer.render(context)
            img = renderer.write_pass_image(context, rgba)
            base = bpy.data.filepath or os.path.join(tempfile.gettempdir(), "lineforge")
            out = os.path.splitext(base)[0] + "_lineforge.png"
            img.filepath_raw = out
            img.file_format = 'PNG'
            img.save()
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge: saving the line pass failed")
        _record(context, renderer.last_stats())
        self.report({'INFO'}, "Saved " + out)
        return {'FINISHED'}


class LF_OT_save_passes(Operator):
    bl_idname = "lf.save_passes"
    bl_label = "Save Passes"
    bl_description = (
        "Render once and write every enabled pass: <name>_lines.png, "
        "<name>_hidden.png and <name>_depth.exr"
    )
    bl_options = {'REGISTER'}

    filepath: StringProperty(
        name="Base Path",
        subtype='FILE_PATH',
        description="Output base path; the pass suffixes are appended to it",
    )

    def execute(self, context):
        try:
            base = self.filepath
            if not base:
                blend = bpy.data.filepath
                base = (os.path.splitext(blend)[0] if blend
                        else os.path.join(tempfile.gettempdir(), "lineforge")) + "_passes.png"
            written = renderer.save_passes(context, base)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge: saving the passes failed")
        _record(context, renderer.last_stats())
        self.report({'INFO'}, "Saved %d pass(es)" % len(written))
        return {'FINISHED'}


class LF_OT_open_tree(Operator):
    bl_idname = "lf.open_tree"
    bl_label = "Edit LineForge Nodes"
    bl_description = "Show the LineForge node tree in a Node Editor"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            tree = context.scene.lf.node_tree or _default_tree(context.scene)
            context.scene.lf.node_tree = tree
        except Exception as exc:  # noqa: BLE001
            return _fail(self, context, exc, "LineForge: could not open the node tree")
        done = False
        for area in context.screen.areas if context.screen else []:
            if area.type != 'NODE_EDITOR':
                continue
            space = area.spaces.active
            try:
                space.tree_type = 'LFNodeTree'
            except Exception:  # noqa: BLE001
                pass
            for attr in ("node_tree", "edit_tree"):
                try:
                    setattr(space, attr, tree)
                    done = True
                    break
                except Exception:  # noqa: BLE001
                    continue
            if done:
                break
        if not done:
            self.report({'INFO'}, "Open a Node Editor and pick 'LineForge' in its header")
        return {'FINISHED'}


class LF_OT_toggle_overlay(Operator):
    bl_idname = "lf.toggle_overlay"
    bl_label = "Toggle Viewport Overlay"
    bl_options = {'REGISTER'}

    def execute(self, context):
        lf = context.scene.lf
        lf.overlay_enabled = not lf.overlay_enabled
        return {'FINISHED'}


class LF_OT_check_core(Operator):
    bl_idname = "lf.check_core"
    bl_label = "Check Native Core"
    bl_description = "Verify that the compiled core for this platform is present and loadable"
    bl_options = {'REGISTER'}

    def execute(self, context):
        renderer.reset_core()  # "Check" must retry, not replay a stale failure
        info = renderer.core_info()
        lf = context.scene.lf
        if info["available"]:
            lf.last_error = ""
            lf.last_core_status = "core %s  |  %s" % (info["version"] or "?", info["path"])
            self.report({'INFO'}, "LineForge core " + str(info["version"]))
            return {'FINISHED'}
        lf.last_error = str(info["error"])
        self.report({'ERROR'}, "LineForge core unavailable for " + renderer.platform_tag())
        return {'CANCELLED'}


CLASSES = (
    LF_OT_create_tree, LF_OT_add_lineset, LF_OT_render, LF_OT_render_composite,
    LF_OT_preview, LF_OT_save_pass, LF_OT_save_passes, LF_OT_open_tree,
    LF_OT_toggle_overlay, LF_OT_check_core,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
