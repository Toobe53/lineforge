# LineForge — visual check: hidden (occluded) lines drawn faint behind the cube.
# GPL-2.0-or-later.
import os
import sys

import bpy

ADDON = r"C:\LineForge\addon"
OUT = r"C:\LineForge\build\hidden_cube.png"

sys.path.insert(0, ADDON)
bpy.ops.wm.read_factory_settings(use_empty=True)

import importlib
import lineforge
importlib.reload(lineforge)
lineforge.register()

bpy.ops.mesh.primitive_cube_add(size=2.0)
cube = bpy.context.object
cube.data.materials.clear()
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(-1.28, -0.96, -1.44))
rear = bpy.context.object
rear.data.materials.clear()
bpy.ops.object.camera_add(location=(4.2, -3.4, 3.0))
cam = bpy.context.object
import mathutils
cam.rotation_euler = (mathutils.Vector((0, 0, 0)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
bpy.context.scene.camera = cam

scene = bpy.context.scene
bpy.ops.lf.create_tree()
tree = scene.lf.node_tree
from lineforge import nodes
for node in nodes.active_sets(tree):
    if node.line_type != 'OBJECT':
        node.enabled = False
    else:
        node.width = 5.0
scene.lf.hidden_lines = True
scene.lf.hidden_alpha = 0.45
scene.lf.hidden_width = 0.8
scene.render.resolution_x = 480
scene.render.resolution_y = 360

from lineforge import renderer
rgba = renderer.render(bpy.context)
img = renderer.write_pass_image(bpy.context, rgba)
img.filepath_raw = OUT
img.file_format = 'PNG'
img.save()
print("STATS", renderer.last_stats())
print("SAVED", os.path.getsize(OUT))
lineforge.unregister()
