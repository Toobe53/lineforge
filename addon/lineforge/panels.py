# LineForge — UI panels.
# GPL-2.0-or-later.
import bpy

from . import nodes as lfnodes
from . import renderer


class LF_PT_main(bpy.types.Panel):
    bl_label = "LineForge"
    bl_idname = "LF_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LineForge"

    def draw(self, context):
        layout = self.layout
        lf = context.scene.lf
        row = layout.row()
        row.prop(lf, "enabled", text="Enable LineForge")
        if not lf.enabled:
            return

        info = renderer.core_info()
        if not info["available"]:
            box = layout.box()
            box.label(text="Native core not available", icon='ERROR')
            box.label(text="Platform: " + renderer.platform_tag())
            for line in str(info["error"]).splitlines()[:6]:
                box.label(text=line[:96])
            return
        if info.get("error"):
            layout.label(text=info["error"], icon='ERROR')

        tree = lf.node_tree
        if tree is None:
            layout.operator("lf.create_tree", icon='ADD')
            return

        col = layout.column(align=True)
        col.operator("lf.preview", icon='PLAY')
        col.operator("lf.render_still", icon='RENDER_STILL')
        col.operator("lf.render_composite", icon='IMAGE_DATA')
        row = layout.row(align=True)
        row.operator("lf.save_pass", icon='FILE_IMAGE')
        row.prop(lf, "overlay_enabled", text="", icon='HIDE_OFF' if lf.overlay_enabled else 'HIDE_ON')

        box = layout.box()
        box.label(text="Line Sets", icon='NODETREE')
        out = lfnodes.output_node(tree)
        for node in lfnodes.active_sets(tree):
            row = box.row(align=True)
            row.prop(node, "enabled", text="")
            sub = row.row(align=True)
            sub.prop(node, "line_type", text="")
            sub.prop(node, "width", text="")
            row.prop(node, "color", text="")
        if not any(True for _ in lfnodes.active_sets(tree)):
            box.label(text="No line set linked to the output node", icon='ERROR')

        row = layout.row(align=True)
        row.operator("lf.add_lineset", text="Add Line Set", icon='ADD')
        row.operator("lf.open_tree", text="Nodes", icon='NODE_TREE')

        box = layout.box()
        box.label(text="Settings", icon='PREFERENCES')
        col = box.column(align=True)
        col.prop(lf, "line_scale")
        col.prop(lf, "supersample")
        cam = getattr(getattr(context, "scene", None), "camera", None)
        if cam is not None and getattr(cam.data, "type", "") == 'ORTHO':
            col.prop(lf, "ortho_width_falloff")
        col.prop(lf, "crease_angle")
        col.prop(lf, "intersection_tol")
        col.prop(lf, "seed")
        col.prop(lf, "exclude_objects")
        if lf.last_error:
            err = layout.box()
            err.label(text="Last Error", icon='ERROR')
            for line in lf.last_error.splitlines()[:8]:
                err.label(text=line[:96])
        if lf.stats_text:
            box = layout.box()
            box.label(text="Last Render", icon='INFO')
            for part in lf.stats_text.split("|"):
                box.label(text=part.strip())


class LF_PT_output(bpy.types.Panel):
    bl_label = "Output"
    bl_idname = "LF_PT_output"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "LineForge"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and getattr(space, "tree_type", "") == 'LFNodeTree'

    def draw(self, context):
        layout = self.layout
        lf = context.scene.lf
        tree = lf.node_tree
        if tree is not None:
            n = lfnodes.output_node(tree)
            if n is not None:
                n.draw_buttons(context, layout)
        layout.prop(lf, "line_scale")


CLASSES = (LF_PT_main, LF_PT_output)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
