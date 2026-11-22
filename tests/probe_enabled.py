import sys, bpy
sys.path.insert(0, r"C:\LineForge\addon")
import lineforge
from lineforge import nodes, renderer
try: lineforge.unregister()
except Exception: pass
lineforge.register()
bpy.ops.lf.create_tree()
tree = bpy.context.scene.lf.node_tree
for n in tree.nodes:
    print("NODE", n.bl_idname, n.name, getattr(n, "line_type", None), getattr(n, "enabled", "NOATTR"))
def only(tree, keep):
    for n in tree.nodes:
        if n.bl_idname == "LFLineSetNode":
            n.enabled = (n.line_type == keep)
only(tree, "INTERSECTION")
print("AFTER", [(n.name, getattr(n,"enabled",None)) for n in tree.nodes if n.bl_idname=="LFLineSetNode"])
print("ACTIVE", [n.name for n in nodes.active_sets(tree)])
