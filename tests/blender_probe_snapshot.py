# LineForge — inspect the extracted snapshot of the default cube scene.
# GPL-2.0-or-later.
import sys

import bpy
import numpy as np

ADDON = r"C:\LineForge\addon"
if ADDON not in sys.path:
    sys.path.insert(0, ADDON)

import lineforge  # noqa: E402
from lineforge import scene_extract  # noqa: E402

lineforge.register()
scene = bpy.context.scene
scene.render.resolution_x = 640
scene.render.resolution_y = 480
snap = scene_extract.extract(bpy.context, 640, 480)
print("verts", snap.verts.shape, "tris", snap.tris.shape, "edges", snap.edges.shape)
n = snap.tri_normals
et = snap.edge_tris
cos30 = float(np.cos(np.radians(30.0)))
dot = np.einsum("ij,ij->i", n[et[:, 0]], n[et[:, 1]])
print("edge dot stats", float(dot.min()), float(dot.mean()), float(dot.max()))
print("crease edges (dot<cos30)", int((dot < cos30).sum()))
print("material edges", int((snap.tri_mat[et[:, 0]] != snap.tri_mat[et[:, 1]]).sum()))
cam = np.array(snap.cam_pos, np.float64)
v = snap.verts
e = snap.edges
p0 = v[e[:, 0]]
front = np.einsum("ij,ij->i", n[et[:, 0]], cam - p0) > 0
front1 = np.einsum("ij,ij->i", n[et[:, 1]], cam - v[e[:, 1]]) > 0
print("silhouette edges", int((front != front1).sum()))
print("obj count", len(snap.obj_names), "objs", snap.obj_names)
lineforge.unregister()
