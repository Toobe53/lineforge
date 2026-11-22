# LineForge — inspect a .blend file's scene contents (headless).
# GPL-2.0-or-later.
import sys

import bpy

path = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None
print("FILE", bpy.data.filepath)
scenes = list(bpy.data.scenes)
print("SCENES", [(s.name, s.render.resolution_x, s.render.resolution_y, s.render.engine) for s in scenes])
for sc in scenes:
    meshes = [o for o in sc.objects if o.type == 'MESH']
    tris = 0
    for o in meshes:
        me = o.data
        tris += sum(max(0, len(p.vertices) - 2) for p in me.polygons)
    cams = [o for o in sc.objects if o.type == 'CAMERA']
    print("SCENE", sc.name, "objects", len(sc.objects), "meshes", len(meshes),
          "tris", tris, "cameras", [c.name for c in cams], "active_cam", sc.camera.name if sc.camera else None)
    for o in meshes[:12]:
        print("  MESH", o.name, o.data.name, len(o.data.vertices), len(o.data.polygons),
              "mats", [m.name for m in o.data.materials if m])
