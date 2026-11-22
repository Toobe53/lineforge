# LineForge — node tree UI (line sets, brushes, output).
# GPL-2.0-or-later.
import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, PointerProperty, StringProperty,
)
from bpy.types import Node, NodeSocket, NodeTree

LINE_TYPES = (
    ('OBJECT', "Outline", "Object silhouette / outline", 0),
    ('CREASE', "Crease", "Interior crease lines above the angle threshold", 1),
    ('BOUNDARY', "Border", "Open mesh borders", 2),
    ('MATERIAL', "Material Boundary", "Boundaries between materials", 3),
    ('INTERSECTION', "Intersection", "Object-object intersection lines (depth buffer)", 4),
)
LINE_TYPE_INDEX = {t[0]: t[3] for t in LINE_TYPES}
TYPE_KEYS = [t[0] for t in LINE_TYPES]

SOURCES = (
    ('SCENE', "Whole Scene", "Every renderable mesh object", 0),
    ('COLLECTION', "Collection", "Objects in a collection", 1),
    ('OBJECT', "Object", "A single object", 2),
)

BRUSH_PRESETS = (
    ('SOLID', "Solid", "Constant width", 0),
    ('INK', "Ink", "Pressure-like swell in the middle", 1),
    ('TAPER', "Taper", "Thin ends", 2),
    ('CALLIGRAPHY', "Calligraphy", "Broad-nib oscillation", 3),
    ('ZIPPER', "Zipper", "Dashed rhythm", 4),
)


def brush_profile(name):
    if name == 'INK':
        return [0.55, 0.85, 1.0, 0.95, 0.8, 0.6]
    if name == 'TAPER':
        return [0.25, 0.6, 1.0, 0.6, 0.25]
    if name == 'CALLIGRAPHY':
        return [1.0, 0.35, 0.95, 0.3, 0.9, 0.4]
    if name == 'ZIPPER':
        return [1.0, 1.0, 0.05, 0.05]
    return [1.0]


class LFLineSetSocket(NodeSocket):
    bl_idname = "LFLineSetSocket"
    bl_label = "Line Set"

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return (0.35, 0.85, 0.95, 1.0)


class LFLineSetNode(Node):
    """One line set: a line type + a style + a source selection."""
    bl_idname = "LFLineSetNode"
    bl_label = "Line Set"
    bl_icon = 'OUTLINER_OB_CURVE'

    enabled: BoolProperty(name="Enabled", default=True)
    source_type: EnumProperty(name="Source", items=SOURCES, default='SCENE')
    collection: PointerProperty(name="Collection", type=bpy.types.Collection)
    object: PointerProperty(name="Object", type=bpy.types.Object)
    line_type: EnumProperty(name="Line Type", items=LINE_TYPES, default='OBJECT')

    width: FloatProperty(name="Width", default=2.0, min=0.01, soft_max=32.0, subtype='PIXEL')
    world_space: BoolProperty(name="World Space Width", default=False)
    color: FloatVectorProperty(
        name="Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.0, 1.0)
    )
    taper_in: FloatProperty(name="Taper In", default=0.0, min=0.0, soft_max=200.0, subtype='PIXEL')
    taper_out: FloatProperty(name="Taper Out", default=0.0, min=0.0, soft_max=200.0, subtype='PIXEL')
    random_width: FloatProperty(name="Random Width", default=0.0, min=0.0, max=1.0)
    distance_fade: FloatProperty(name="Distance Fade", default=0.0, min=0.0, soft_max=100.0)
    fade_start: FloatProperty(name="Fade Start", default=0.0, min=0.0, soft_max=100.0)

    crease_override: BoolProperty(name="Override Crease Angle", default=False)
    crease_angle: FloatProperty(name="Crease Angle", default=60.0, min=0.0, max=180.0, subtype='ANGLE')

    brush_preset: EnumProperty(name="Brush", items=BRUSH_PRESETS, default='SOLID')
    brush_repeat: FloatProperty(name="Brush Repeat", default=1.0, min=0.01, soft_max=20.0)
    brush_width_amp: FloatProperty(name="Brush Width", default=0.0, min=0.0, max=1.0)
    brush_alpha_amp: FloatProperty(name="Brush Alpha", default=0.0, min=0.0, max=1.0)
    brush_offset_random: FloatProperty(name="Random Phase", default=0.0, min=0.0, max=1.0)

    pattern: EnumProperty(
        name="Pattern",
        items=(('SOLID', "Solid", "Continuous stroke"),
               ('DASH', "Dash", "Dashed stroke"),
               ('DOT', "Dot", "Dotted stroke")),
        default='SOLID',
    )
    pattern_period: FloatProperty(
        name="Period", default=16.0, min=2.0, soft_max=120.0, subtype='PIXEL',
        description="Length of one dash cycle",
    )
    pattern_duty: FloatProperty(
        name="Duty", default=0.55, min=0.05, max=0.95,
        description="Fraction of the cycle that is drawn",
    )
    texture: EnumProperty(
        name="Texture",
        items=(('NONE', "None", "Uniform stroke"),
               ('CHARCOAL', "Charcoal", "Coarse, clumpy width variation"),
               ('PENCIL', "Pencil", "Fine grain"),
               ('INK', "Ink", "Mostly solid with occasional breaks")),
        default='NONE',
    )
    texture_scale: FloatProperty(name="Texture Scale", default=1.0, min=0.1, soft_max=8.0)
    simplify_override: BoolProperty(name="Override Simplify", default=False)
    simplify_px: FloatProperty(
        name="Simplify", default=0.6, min=0.0, soft_max=10.0, subtype='PIXEL',
        description="Polyline simplification tolerance for this line set",
    )

    filter_objects: StringProperty(
        name="Objects",
        default="",
        description="Comma separated object name globs to keep (empty = every object); "
                    "e.g. 'Body*, Hair*'",
    )
    filter_materials: StringProperty(
        name="Materials",
        default="",
        description="Comma separated material name globs to keep (empty = every material); "
                    "e.g. '*_SKIN, *_CLOTH_01'",
    )
    exclude_objects: StringProperty(
        name="Skip Objects",
        default="",
        description="Comma separated object name globs to drop from this line set",
    )
    exclude_materials: StringProperty(
        name="Skip Materials",
        default="",
        description="Comma separated material name globs to drop from this line set",
    )

    def init(self, context):
        self.outputs.new("LFLineSetSocket", "Line Set")

    def draw_buttons(self, context, layout):
        row = layout.row()
        row.prop(self, "enabled", text="")
        row.prop(self, "line_type", text="")
        col = layout.column(align=True)
        col.prop(self, "source_type", text="")
        if self.source_type == 'COLLECTION':
            col.prop(self, "collection", text="")
        elif self.source_type == 'OBJECT':
            col.prop(self, "object", text="")
        if self.line_type == 'CREASE':
            col.prop(self, "crease_override")
            if self.crease_override:
                col.prop(self, "crease_angle")
        fbox = layout.box()
        fbox.label(text="Filters")
        fbox.prop(self, "filter_objects")
        fbox.prop(self, "exclude_objects")
        fbox.prop(self, "filter_materials")
        fbox.prop(self, "exclude_materials")

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)
        box = layout.box()
        box.label(text="Style")
        box.prop(self, "width")
        box.prop(self, "world_space")
        box.prop(self, "color")
        row = box.row(align=True)
        row.prop(self, "taper_in")
        row.prop(self, "taper_out")
        box.prop(self, "random_width")
        row = box.row(align=True)
        row.prop(self, "distance_fade")
        row.prop(self, "fade_start")
        box = layout.box()
        box.label(text="Brush")
        box.prop(self, "brush_preset")
        box.prop(self, "brush_repeat")
        box.prop(self, "brush_width_amp")
        box.prop(self, "brush_alpha_amp")
        box.prop(self, "brush_offset_random")
        box = layout.box()
        box.label(text="Pattern")
        box.prop(self, "pattern", text="")
        if self.pattern != 'SOLID':
            row = box.row(align=True)
            row.prop(self, "pattern_period")
            row.prop(self, "pattern_duty")
        box.prop(self, "texture", text="")
        if self.texture != 'NONE':
            box.prop(self, "texture_scale")
        row = box.row(align=True)
        row.prop(self, "simplify_override")
        row.prop(self, "simplify_px")


class LFOutputNode(Node):
    """Terminal node. Only line sets linked here are rendered (if any)."""
    bl_idname = "LFOutputNode"
    bl_label = "LineForge Output"
    bl_icon = 'OUTPUT'

    resolution_scale: FloatProperty(
        name="Resolution Scale", default=100.0, min=5.0, max=400.0, subtype='PERCENTAGE'
    )
    use_material_color: BoolProperty(name="Use Material Colors", default=False)
    simplify_px: FloatProperty(name="Simplify", default=0.6, min=0.0, soft_max=5.0)
    depth_bias: FloatProperty(name="Depth Bias", default=0.0015, min=0.0, max=0.05)

    def init(self, context):
        self.inputs.new("LFLineSetSocket", "Line Set")
        self.inputs.new("LFLineSetSocket", "Line Set")
        self.inputs.new("LFLineSetSocket", "Line Set")
        self.inputs.new("LFLineSetSocket", "Line Set")

    def draw_buttons(self, context, layout):
        layout.prop(self, "resolution_scale")
        layout.prop(self, "use_material_color")
        layout.prop(self, "simplify_px")
        layout.prop(self, "depth_bias")


class LFNodeTree(NodeTree):
    bl_idname = "LFNodeTree"
    bl_label = "LineForge"
    bl_icon = 'NODETREE'
    bl_description = "LineForge line-art node tree"


NODE_CLASSES = (LFLineSetSocket, LFLineSetNode, LFOutputNode, LFNodeTree)


def register():
    for cls in NODE_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(NODE_CLASSES):
        bpy.utils.unregister_class(cls)


# ---------------------------------------------------------------- helpers ---

def active_sets(tree):
    """Line set nodes in display order; filtered by the Output node links."""
    if tree is None:
        return []
    sets = [n for n in tree.nodes if n.bl_idname == "LFLineSetNode" and n.enabled]
    outs = [n for n in tree.nodes if n.bl_idname == "LFOutputNode"]
    if not outs:
        return sorted(sets, key=lambda n: (n.location.y * -1.0, n.location.x))
    linked = set()
    for out in outs:
        for sock in out.inputs:
            for link in sock.links:
                if link.from_node.bl_idname == "LFLineSetNode":
                    linked.add(link.from_node)
    if not linked:
        return []
    keep = [n for n in linked if n.enabled]
    return sorted(keep, key=lambda n: (n.location.y * -1.0, n.location.x))


def output_node(tree):
    if tree is None:
        return None
    for n in tree.nodes:
        if n.bl_idname == "LFOutputNode":
            return n
    return None
