# LineForge — scene extraction (Blender -> flat buffers for the native core).
# GPL-2.0-or-later.
import numpy as np
import bpy
from mathutils import Vector

from .errors import LineForgeError


def _mat4_to_np(m):
    out = np.zeros((4, 4), np.float32)
    for r in range(4):
        for c in range(4):
            out[r, c] = m[r][c]
    return out


def _normal_matrix(mw):
    m3 = np.array([[mw[r][c] for c in range(3)] for r in range(3)], np.float64)
    try:
        inv = np.linalg.inv(m3)
    except np.linalg.LinAlgError:
        inv = np.eye(3)
    return np.ascontiguousarray(inv.T, np.float32)


def _material_key(ob, slot_index):
    if 0 <= slot_index < len(ob.material_slots):
        mat = ob.material_slots[slot_index].material
        if mat is not None:
            return mat.name, mat
    return "__none__", None


def _edge_table(tri):
    """Unique triangle edges with up to two adjacent triangle indices."""
    n = tri.shape[0]
    if n == 0:
        empty = np.zeros((0, 2), np.int32)
        return empty, empty.copy()
    e = np.concatenate((tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]), axis=0)
    e = np.sort(e, axis=1)  # canonical (min,max) so shared edges collapse
    tidx = np.tile(np.arange(n, dtype=np.int64), 3)
    order = np.lexsort((e[:, 1], e[:, 0]))
    es = e[order]
    ts = tidx[order]
    same = (es[1:, 0] == es[:-1, 0]) & (es[1:, 1] == es[:-1, 1])
    starts = np.concatenate(([0], np.nonzero(~same)[0] + 1))
    counts = np.diff(np.concatenate((starts, [len(es)])))
    edges = es[starts].astype(np.int32)
    t0 = ts[starts].astype(np.int32)
    t1 = np.full(starts.shape[0], -1, np.int32)
    has_two = counts > 1
    if np.any(has_two):
        t1[has_two] = ts[starts[has_two] + 1].astype(np.int32)
    return edges, np.stack((t0, t1), axis=1)


class Snapshot:
    __slots__ = (
        "width", "height", "verts", "tris", "tri_normals", "tri_mat", "tri_obj", "tri_skip",
        "edges", "edge_tris", "obj_names", "mat_names", "mat_colors", "mvp", "proj",
        "view", "cam_pos", "cam_name", "visible_objects", "cam_ortho", "cam_ortho_scale",
    )


def _is_helper_material(name):
    """Inverted-hull outline meshes (VRM 'MToon Outline', custom hulls) are helper geometry:
    they exist to fake outlines in the real renderer and only pollute the line pass."""
    n = name.casefold()
    return ("outline" in n) or n.endswith("_hull") or ("hull" in n and "outline" in n)


def extract(context, width, height, use_render_visibility=True, exclude=()):
    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()

    exclude = tuple(s.strip().casefold() for s in exclude if s and s.strip())

    cam = scene.camera
    if cam is None:
        raise LineForgeError("LineForge: the scene has no camera (set scene.camera or use the Render Line Art PNG operator)")
    cam_eval = cam.evaluated_get(depsgraph)

    verts_chunks = []
    tri_chunks = []
    nrm_chunks = []
    skip_chunks = []
    mat_chunks = []
    obj_chunks = []
    mat_ids = {}
    mat_names = []
    mat_colors = []
    obj_names = []
    offset = 0

    for ob in depsgraph.objects:
        if ob.type != 'MESH':
            continue
        orig = ob.original
        if use_render_visibility:
            if orig.hide_render or not orig.visible_get():
                continue
        if exclude and any(pat in orig.name.casefold() for pat in exclude):
            continue
        ev = ob.evaluated_get(depsgraph)
        try:
            me = ev.to_mesh()
        except Exception:  # noqa: BLE001 - broken modifiers must not kill the whole pass
            continue
        if me is None:
            continue
        try:
            if len(me.polygons) == 0:
                continue
            me.calc_loop_triangles()
            nt = len(me.loop_triangles)
            if nt == 0:
                continue

            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3).astype(np.float64)

            mw = _mat4_to_np(ev.matrix_world).astype(np.float64)
            world = co @ mw[:3, :3].T + mw[:3, 3]
            world32 = np.ascontiguousarray(world, np.float32)

            tri = np.empty(nt * 3, np.int32)
            me.loop_triangles.foreach_get("vertices", tri)
            tri = tri.reshape(-1, 3).astype(np.int32)

            tpoly = np.empty(nt, np.int32)
            me.loop_triangles.foreach_get("polygon_index", tpoly)
            poly_mat = np.empty(len(me.polygons), np.int32)
            me.polygons.foreach_get("material_index", poly_mat)
            tmat_local = poly_mat[tpoly]

            pn = np.empty(len(me.polygons) * 3, np.float32)
            me.polygons.foreach_get("normal", pn)
            pn = pn.reshape(-1, 3)
            tn = pn[tpoly] @ _normal_matrix(mw).T
            if float(np.linalg.det(mw[:3, :3])) < 0.0:  # mirrored object: normals flip with the transform
                tn = -tn
            lens = np.linalg.norm(tn, axis=1, keepdims=True)
            lens[lens < 1e-9] = 1.0
            tn = np.ascontiguousarray(tn / lens, np.float32)

            # global material ids (union across objects)
            local_to_global = np.empty(tmat_local.shape, np.int32)
            local_skip = np.zeros_like(tmat_local, np.uint8)
            for slot in np.unique(tmat_local):
                key, mat = _material_key(ev, int(slot))
                if _is_helper_material(key):
                    local_skip[tmat_local == slot] = 1
                gid = mat_ids.get(key)
                if gid is None:
                    gid = len(mat_names)
                    mat_ids[key] = gid
                    mat_names.append(key)
                    col = (0.8, 0.8, 0.8, 1.0)
                    if mat is not None:
                        try:
                            c = mat.diffuse_color
                            col = (float(c[0]), float(c[1]), float(c[2]), float(c[3]))
                        except Exception:
                            pass
                    mat_colors.append(col)
                local_to_global[tmat_local == slot] = gid

            oid = len(obj_names)
            obj_names.append(orig.name)

            # degenerate / NaN triangles would produce garbage normals and stray lines
            p0 = world[tri[:, 0]]
            p1 = world[tri[:, 1]]
            p2 = world[tri[:, 2]]
            cross = np.cross(p1 - p0, p2 - p0)
            area2 = np.linalg.norm(cross, axis=1)
            bad = (area2 < 1e-12) | ~np.isfinite(area2) | ~np.isfinite(tn).all(axis=1)
            if bad.any():
                local_skip[bad] = 1

            verts_chunks.append(np.ascontiguousarray(world32 + np.float32(0)))
            tri_chunks.append(tri + offset)
            nrm_chunks.append(tn)
            mat_chunks.append(np.ascontiguousarray(local_to_global, np.int32))
            skip_chunks.append(np.ascontiguousarray(local_skip, np.uint8))
            obj_chunks.append(np.full(nt, oid, np.int32))
            offset += len(me.vertices)
        finally:
            ev.to_mesh_clear()

    if not tri_chunks:
        raise LineForgeError("LineForge: no renderable mesh geometry in the scene "
                             "(check visibility and Exclude Objects)")

    verts = np.ascontiguousarray(np.concatenate(verts_chunks, axis=0), np.float32)
    tris = np.ascontiguousarray(np.concatenate(tri_chunks, axis=0), np.int32)
    tri_normals = np.ascontiguousarray(np.concatenate(nrm_chunks, axis=0), np.float32)
    tri_mat = np.ascontiguousarray(np.concatenate(mat_chunks, axis=0), np.int32)
    tri_obj = np.ascontiguousarray(np.concatenate(obj_chunks, axis=0), np.int32)
    tri_skip = np.ascontiguousarray(np.concatenate(skip_chunks, axis=0), np.uint8)

    edges, edge_tris = _edge_table(tris)

    # camera matrices
    cam_loc = cam_eval.matrix_world.translation
    view = np.linalg.inv(_mat4_to_np(cam_eval.matrix_world).astype(np.float64))
    try:
        proj = cam_eval.calc_matrix_camera(
            depsgraph, x=width, y=height, scale_x=1.0, scale_y=1.0
        )
    except TypeError:
        proj = cam_eval.calc_matrix_camera(depsgraph, x=width, y=height)
    proj = _mat4_to_np(proj).astype(np.float64)
    mvp = proj @ view

    snap = Snapshot()
    snap.width = int(width)
    snap.height = int(height)
    snap.verts = verts
    snap.tris = tris
    snap.tri_normals = tri_normals
    snap.tri_mat = tri_mat
    snap.tri_obj = tri_obj
    snap.tri_skip = tri_skip
    snap.edges = edges
    snap.edge_tris = edge_tris
    snap.obj_names = obj_names
    snap.mat_names = mat_names
    snap.mat_colors = mat_colors
    snap.mvp = np.ascontiguousarray(mvp, np.float32)
    snap.proj = np.ascontiguousarray(proj, np.float32)
    snap.view = np.ascontiguousarray(view, np.float32)
    snap.cam_pos = np.array([cam_loc[0], cam_loc[1], cam_loc[2]], np.float32)
    snap.cam_name = cam.name
    snap.cam_ortho = (cam_eval.data.type == 'ORTHO')
    snap.cam_ortho_scale = float(getattr(cam_eval.data, 'ortho_scale', 1.0) or 1.0)
    if snap.cam_ortho:
        # An orthographic camera has no eye point: the view direction is constant.
        # Push the pseudo eye far behind the camera so "facing the camera" tests
        # stay meaningful (~parallel projection) for every vertex.
        fwd = -(cam_eval.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0)))
        far = cam_loc - fwd * 1.0e5
        snap.cam_pos = np.array([far[0], far[1], far[2]], np.float32)
    snap.visible_objects = set(obj_names)
    return snap


def scene_dict(snap, edge_sel=None, obj_sel=None):
    d = {
        "verts": snap.verts,
        "tris": snap.tris,
        "tri_normals": snap.tri_normals,
        "tri_mat": snap.tri_mat,
        "tri_obj": snap.tri_obj,
        "tri_skip": snap.tri_skip,
        "edges": snap.edges,
        "edge_tris": snap.edge_tris,
        "mvp": snap.mvp,
        "proj": snap.proj,
        "view": snap.view,
        "cam_pos": snap.cam_pos,
    }
    if edge_sel is not None:
        d["edge_sel"] = np.ascontiguousarray(edge_sel, np.uint8)
    if obj_sel is not None:
        d["obj_sel"] = np.ascontiguousarray(obj_sel, np.uint8)
    return d
