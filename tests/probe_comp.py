import bpy
sc = bpy.context.scene
print("HAS_use_nodes", hasattr(sc, "use_nodes"))
print("COMP_ATTRS", [a for a in dir(sc) if "comp" in a.lower() or "node" in a.lower()])
ng = bpy.data.node_groups.new("LFComp", "CompositorNodeTree")
print("NG_OK", ng.bl_idname, ng.interface is not None)
try:
    sc.compositing_node_group = ng
    print("ASSIGN_OK", sc.compositing_node_group.name)
except Exception as e:
    print("ASSIGN_FAIL", e)
rl = ng.nodes.new("CompositorNodeRLayers")
print("RL_OK", rl.name, [o.name for o in rl.outputs][:3])
ao = ng.nodes.new("CompositorNodeAlphaOver")
print("AO_OK", [i.name for i in ao.inputs])
out = ng.nodes.new("NodeGroupOutput")
print("OUT_OK", [i.name for i in out.inputs])
try:
    ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    print("IFACE_OK", [s.name for s in ng.interface.items_tree])
except Exception as e:
    print("IFACE_FAIL", e)
