# LineForge — scene level settings.
# GPL-2.0-or-later.
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

from .nodes import LFNodeTree


class LFSceneProps(PropertyGroup):
    enabled: BoolProperty(name="Enable LineForge", default=True)
    node_tree: PointerProperty(name="Node Tree", type=LFNodeTree)

    overlay_enabled: BoolProperty(name="Viewport Overlay", default=True)
    auto_composite: BoolProperty(name="Composite Into Render", default=True)
    auto_render_on_f12: BoolProperty(name="Render On F12", default=True)

    crease_angle: FloatProperty(
        name="Crease Angle", default=60.0, min=0.0, max=180.0, subtype='ANGLE'
    )
    intersection_tol: FloatProperty(
        name="Intersection Tolerance", default=0.01, min=0.0001, max=0.5
    )
    seed: IntProperty(name="Seed", default=12345)
    hidden_lines: BoolProperty(name="Hidden Lines", default=False)
    hidden_alpha: FloatProperty(name="Hidden Alpha", default=0.25, min=0.0, max=1.0)
    hidden_width: FloatProperty(name="Hidden Width", default=0.5, min=0.01, max=8.0)

    pass_image: StringProperty(name="Pass Image", default="LineForge Pass")
    exclude_objects: StringProperty(
        name="Exclude Objects",
        default="",
        description="Comma separated object name substrings to leave out of the line pass "
                    "(useful for helper shells and inverted-hull outlines)",
    )
    line_scale: FloatProperty(
        name="Line Scale", default=1.0, min=0.05, soft_max=8.0,
        description="Global multiplier applied to every line width",
    )
    supersample: IntProperty(
        name="Supersampling", default=2, min=1, max=4,
        description="Render the line pass at N times the resolution, then box-filter down "
                    "(1 = off, 2 = good, 3-4 = very smooth but slower)",
    )
    ortho_width_falloff: BoolProperty(
        name="Ortho Width Falloff",
        default=False,
        description="With an orthographic camera, scale world-space line widths by distance "
                    "instead of using one constant screen width (nearer geometry draws thicker)",
    )
    skip_outline_shells: BoolProperty(
        name="Skip Outline Shells",
        default=True,
        description="Temporarily disable outline-shell modifiers (e.g. VRM/MToon 'Outline' "
                    "geometry nodes, inverted hulls) while extracting geometry, so their "
                    "inflated shells do not add a second, larger outline to the line pass",
    )
    skip_transparent_faces: BoolProperty(
        name="Skip See-through Faces",
        default=True,
        description="Leave out faces whose material alpha texture is transparent at the face "
                    "center (sheer overskirts, alpha-cutout helper cards), which would "
                    "otherwise add outlines the beauty render never shows",
    )
    alpha_threshold: FloatProperty(
        name="Alpha Cutoff",
        default=0.5,
        min=0.0,
        max=1.0,
        description="Faces whose sampled material alpha is below this value are skipped",
    )

    stats_text: StringProperty(name="Stats", default="")
    last_error: StringProperty(name="Last Error", default="")
    last_core_status: StringProperty(name="Core Status", default="")

    def tree(self):
        return self.node_tree


def register():
    bpy.utils.register_class(LFSceneProps)
    bpy.types.Scene.lf = PointerProperty(type=LFSceneProps)


def unregister():
    del bpy.types.Scene.lf
    bpy.utils.unregister_class(LFSceneProps)
