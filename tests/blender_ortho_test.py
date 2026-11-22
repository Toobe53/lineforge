# Orthographic camera + world-space width: constant mode vs. depth falloff.
# Run: blender -b --factory-startup --python tests/blender_ortho_test.py
import sys
import numpy as np
import bpy

sys.path.insert(0, r"C:\LineForge\addon")
import lineforge  # noqa: E402
from lineforge import renderer  # noqa: E402

if not hasattr(bpy.types.Scene, "lf"):
    lineforge.register()


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 320, 240
    scene.render.resolution_percentage = 100
    cam_data = bpy.data.cameras.new("OrthoCam")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = 8.0
    cam = bpy.data.objects.new("OrthoCam", cam_data)
    cam.location = (0.0, 0.0, 6.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def add_cube(name, z):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, z))
    obj = bpy.context.active_object
    obj.name = name
    return obj


def line_widths():
    stats = []
    for ln in renderer.last_lines():
        w = np.asarray(ln["widths"], np.float32)
        if w.size:
            stats.append(float(w.mean()))
    return np.asarray(stats, np.float32)


def main():
    scene = fresh()
    add_cube("NearCube", 2.0)   # 4 units from the camera plane
    add_cube("FarCube", -2.0)   # 8 units from the camera plane
    bpy.ops.lf.create_tree()
    tree = scene.lf.node_tree
    sets = [n for n in tree.nodes if n.bl_idname == "LFLineSetNode"]
    for n in sets:
        n.enabled = (n.line_type == 'OBJECT')
    outline = [n for n in sets if n.line_type == 'OBJECT'][0]
    outline.world_space = True
    outline.width = 0.25          # world units

    scene.lf.supersample = 1
    scene.lf.ortho_width_falloff = False
    rgba = renderer.render(bpy.context)
    assert np.isfinite(rgba).all()
    flat = line_widths()
    assert flat.size >= 2, "expected strokes from both cubes, got %d" % flat.size
    spread_flat = float(flat.max() / max(1e-6, flat.min()))
    print("FLAT lines", flat.size, "min", round(float(flat.min()), 3),
          "max", round(float(flat.max()), 3), "spread", round(spread_flat, 3))
    assert spread_flat < 1.05, "constant mode must not fade with depth (spread %.3f)" % spread_flat

    scene.lf.ortho_width_falloff = True
    rgba = renderer.render(bpy.context)
    assert np.isfinite(rgba).all()
    faded = line_widths()
    spread_faded = float(faded.max() / max(1e-6, faded.min()))
    print("FALLOFF lines", faded.size, "min", round(float(faded.min()), 3),
          "max", round(float(faded.max()), 3), "spread", round(spread_faded, 3))
    # near cube (depth 4) vs far cube (depth 8): width ratio should be about 2x
    assert spread_faded > 1.4, "falloff should thin distant lines (spread %.3f)" % spread_faded

    scene.lf.ortho_width_falloff = False
    print("ORTHO_WIDTH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
