"""Validate the CI-built add-on zip: install, enable, load core, render a cube."""
import bpy
import sys
import traceback

ZIP = r"C:\LineForge\build\ci-artifacts\lineforge-0.2.0.zip"


def main():
    bpy.ops.preferences.addon_install(filepath=ZIP, overwrite=True)
    print("INSTALL OK")
    bpy.ops.preferences.addon_enable(module="lineforge")
    print("ENABLE OK")
    bpy.ops.wm.save_userpref()

    import lineforge
    from lineforge import renderer

    info = renderer.core_info()
    print("CORE_INFO", info)
    assert info["available"], info.get("error")
    assert info["version"] == "0.2.0", info["version"]
    assert "win64" in info["path"].replace("\\", "/"), info["path"]

    import mathutils

    scene = bpy.context.scene
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
    bpy.ops.object.camera_add(location=(4.0, -4.0, 3.2))
    cam = bpy.context.object
    cam.rotation_euler = (-cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    tree = bpy.data.node_groups.new("CITree", "LFNodeTree")
    scene.lf.node_tree = tree
    res = bpy.ops.lf.create_tree()
    print("CREATE_TREE", res)
    tree = scene.lf.node_tree
    scene.lf.supersample = 1
    scene.render.resolution_x = 320
    scene.render.resolution_y = 240

    img = renderer.render(bpy.context, 320, 240)
    stats = renderer.last_stats()
    print("STATS", {k: stats[k] for k in ("lines", "strokes", "tris", "edges")})
    print("IMAGE", img.shape, float(img[..., 3].sum()))
    assert stats["lines"] > 0 and stats["tris"] >= 12, stats
    assert img.shape == (240, 320, 4), img.shape
    print("CI ZIP OK")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
