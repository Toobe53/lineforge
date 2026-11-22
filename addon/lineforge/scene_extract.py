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
        "strand_pts", "strand_offsets", "strand_radius", "nstrands",
    )

    def __init__(self):
        self.strand_pts = None
        self.strand_offsets = None
        self.strand_radius = None
        self.nstrands = 0


def _curves_arrays(cv):
    """Position/radius/topology of a hair curves datablock, or None when empty."""
    npts = len(cv.points)
    if npts == 0 or len(cv.curves) == 0:
        return None
    pos = np.empty(npts * 3, np.float32)
    try:
        cv.points.foreach_get("position", pos)
    except Exception:  # noqa: BLE001 - attribute API differs across 4.x/5.x
        attr = cv.attributes.get("position")
        if attr is None:
            return None
        attr.data.foreach_get("vector", pos)
    rad = np.full(npts, 0.0025, np.float32)
    try:
        rattr = cv.attributes.get("radius")
        if rattr is not None:
            rattr.data.foreach_get("value", rad)
    except Exception:  # noqa: BLE001 - radius is optional
        pass
    nc = len(cv.curves)
    first = np.empty(nc, np.int32)
    length = np.empty(nc, np.int32)
    try:
        cv.curves.foreach_get("first_point_index", first)
        cv.curves.foreach_get("points_length", length)
    except Exception:  # noqa: BLE001 - fall back to sequential strands
        return None
    return pos.reshape(-1, 3), rad, first, length


def _resample_run(pts, rad, limit):
    """Stride a long strand down to `limit` points, keeping both endpoints."""
    if len(pts) <= limit:
        return pts, rad
    idx = np.linspace(0.0, float(len(pts) - 1), limit).astype(np.int32)
    return pts[idx], rad[idx]


def _is_helper_material(name):
    """Inverted-hull outline meshes (VRM 'MToon Outline', custom hulls) are helper geometry:
    they exist to fake outlines in the real renderer and only pollute the line pass."""
    n = name.casefold()
    return ("outline" in n) or n.endswith("_hull") or ("hull" in n and "outline" in n)


def _is_shell_modifier(mod):
    """True for modifier stacks that exist only to build a thick outline shell.

    VRM imports (MToon) put a Geometry Nodes modifier named "MToon Outline (...)" on the
    same object as the visible surface. The shell is pushed along the normals, so its
    silhouette sits outside the real mesh and produced the large ghost outline in the demo
    render. Evaluating the mesh without those modifiers keeps the visible surface intact.
    """
    name = (mod.name or "").casefold()
    if "outline" in name or "hull" in name:
        return True
    if mod.type == 'NODES':
        group = getattr(mod, "node_group", None)
        gname = (getattr(group, "name", "") or "").casefold()
        return "outline" in gname or "hull" in gname
    return False


def _hide_shell_modifiers(depsgraph):
    """Disable outline-shell modifiers; returns a restore list (empty when nothing changed)."""
    restore = []
    for ob in depsgraph.objects:
        if ob.type != 'MESH':
            continue
        orig = ob.original
        if orig is None:
            continue
        for mod in orig.modifiers:
            if mod.show_viewport or mod.show_render:
                if _is_shell_modifier(mod):
                    restore.append((mod, mod.show_viewport, mod.show_render))
                    mod.show_viewport = False
                    mod.show_render = False
    return restore


def _find_alpha_source(mat, max_nodes=64):
    """Locate the image texture (and channel) that drives Principled Alpha, or None.

    Returns (image, channel) with channel 0..2 for R/G/B and 3 for alpha.
    """
    if mat is None or not mat.use_nodes:
        return None
    tree = mat.node_tree
    if tree is None:
        return None
    start = None
    for node in tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            sock = node.inputs.get("Alpha")
            if sock is not None and sock.is_linked:
                start = sock.links[0].from_socket
            break
    if start is None:
        return None
    stack = [start]
    seen = 0
    while stack and seen < max_nodes:
        sock = stack.pop()
        seen += 1
        node = getattr(sock, "node", None)
        if node is None:
            continue
        if node.type == 'TEX_IMAGE' and node.image is not None:
            name = (sock.name or "").upper()
            channel = {"R": 0, "G": 1, "B": 2}.get(name, 3)
            return node.image, channel
        for inp in node.inputs:
            for link in inp.links:
                stack.append(link.from_socket)
    return None


def _image_pixels(img, cache):
    key = img.name
    if key in cache:
        return cache[key]
    arr = None
    try:
        w, h = img.size
        if w > 0 and h > 0:
            buf = np.empty(w * h * 4, np.float32)
            img.pixels.foreach_get(buf)
            arr = buf.reshape(h, w, 4)
    except Exception:  # noqa: BLE001 - unreadable images just disable the feature
        arr = None
    cache[key] = arr
    return arr


def _alpha_sampler(mat, image_cache):
    """Return f(u, v) -> alpha (float) for a material, or None when not texture driven."""
    src = _find_alpha_source(mat)
    if src is None:
        return None
    img, channel = src

    def _sample(u, v):
        arr = _image_pixels(img, image_cache)
        if arr is None:
            return 1.0
        h, w = arr.shape[:2]
        xi = np.clip((u % 1.0) * w, 0, w - 1).astype(np.int32)
        yi = np.clip((v % 1.0) * h, 0, h - 1).astype(np.int32)
        return arr[yi, xi, channel]

    return _sample


def _uv_tri_corners(me):
    """Per-triangle corner UVs as an (E, 3, 2) array, or None when the mesh has no UV layer."""
    if me.uv_layers.active is None:
        return None
    uv = me.uv_layers.active
    uvarr = np.empty(len(me.loops) * 2, np.float32)
    try:
        uv.uv.foreach_get("vector", uvarr)
    except Exception:  # noqa: BLE001 - older API
        uv.data.foreach_get("uv", uvarr)
    uvarr = uvarr.reshape(-1, 2)
    loops = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("loops", loops)
    return uvarr[loops.reshape(-1, 3)]


# Barycentric sample points per triangle: centroid, three edge midpoints and a
# corner-biased point. Sampling several points (instead of the centroid only)
# keeps thin features (lashes, glasses, painted strands) from being dropped just
# because the single sample happened to land in a transparent gap.
_COVERAGE_BARY = np.array(
    [[1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0],
     [0.5, 0.5, 0.0],
     [0.5, 0.0, 0.5],
     [0.0, 0.5, 0.5],
     [0.7, 0.2, 0.1],
     [0.2, 0.7, 0.1],
     [0.1, 0.1, 0.8]], np.float32)


def _alpha_coverage(corners, sample):
    """Per-triangle alpha score in 0..1: mean and peak of the sampled points."""
    values = []
    for bary in _COVERAGE_BARY:
        uvw = corners[:, 0, :] * bary[0] + corners[:, 1, :] * bary[1] + corners[:, 2, :] * bary[2]
        values.append(np.asarray(sample(uvw[:, 0], uvw[:, 1]), np.float32))
    stack = np.stack(values, axis=0)
    # A triangle that is mostly transparent but contains a bit of opaque ink is kept
    # (peak term), while a uniformly sheer triangle is dropped (mean term).
    return 0.5 * stack.mean(axis=0) + 0.5 * stack.max(axis=0)


def _transparent_skip_mask(me, tri, tmat_local, samplers, threshold):
    """Triangles whose material alpha is see-through, scored over the whole UV triangle."""
    if not samplers:
        return None
    corners = _uv_tri_corners(me)
    if corners is None:
        return None
    skip = np.zeros(tri.shape[0], bool)
    for slot, sample in samplers.items():
        if sample is None:
            continue
        sel = tmat_local == slot
        if not sel.any():
            continue
        score = _alpha_coverage(corners[sel], sample)
        skip[sel] = score < threshold
    return skip if skip.any() else None


def extract(context, width, height, use_render_visibility=True, exclude=(), skip_shells=True,
            skip_transparent=True, alpha_threshold=0.5, transparent_keep=(),
            hair=True, hair_max_strands=4000, hair_points=32):
    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()

    exclude = tuple(s.strip().casefold() for s in exclude if s and s.strip())
    transparent_keep = tuple(s.strip().casefold() for s in transparent_keep if s and s.strip())

    cam = scene.camera
    if cam is None:
        raise LineForgeError("LineForge: the scene has no camera (set scene.camera or use the Render Line Art PNG operator)")
    cam_eval = cam.evaluated_get(depsgraph)

    restore = _hide_shell_modifiers(depsgraph) if skip_shells else []
    if restore:
        try:
            bpy.context.view_layer.update()
        except Exception:  # noqa: BLE001 - background contexts may not need it
            pass
        depsgraph = context.evaluated_depsgraph_get()
        cam_eval = cam.evaluated_get(depsgraph)

    try:
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
        image_cache = {}
        strand_chunks = []
        strand_offsets = [0]
        strand_radius = []
        strand_total = 0

        for ob in depsgraph.objects:
            if ob.type not in ('MESH', 'CURVE'):
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

                # see-through geometry (sheer overskirts, alpha-cutout cards) would add
                # outlines the beauty render never shows
                if skip_transparent:
                    obj_keep = bool(transparent_keep) and any(
                        pat in orig.name.casefold() for pat in transparent_keep)
                    samplers = {}
                    for slot in np.unique(tmat_local):
                        key, mat = _material_key(ev, int(slot))
                        keep = obj_keep or (bool(transparent_keep) and any(
                            pat in key.casefold() for pat in transparent_keep))
                        samplers[int(slot)] = None if keep else _alpha_sampler(mat, image_cache)
                    tskip = _transparent_skip_mask(me, tri, tmat_local, samplers, alpha_threshold)
                    if tskip is not None:
                        local_skip[tskip] = 1

                verts_chunks.append(np.ascontiguousarray(world32 + np.float32(0)))
                tri_chunks.append(tri + offset)
                nrm_chunks.append(tn)
                mat_chunks.append(np.ascontiguousarray(local_to_global, np.int32))
                skip_chunks.append(np.ascontiguousarray(local_skip, np.uint8))
                obj_chunks.append(np.full(nt, oid, np.int32))
                offset += len(me.vertices)
            finally:
                ev.to_mesh_clear()

        # Hair curves: strand polylines carry their own radius, so they are drawn as
        # capsules instead of being tessellated into triangles (a cap of ~4k strands
        # keeps the cost bounded while still reading as hair).
        if hair and hair_max_strands > 0:
            max_strands = int(hair_max_strands)
            per_strand = max(2, int(hair_points))
            for ob in depsgraph.objects:
                if len(strand_chunks) >= max_strands or strand_total >= 200000:
                    break
                if ob.type != 'CURVES':
                    continue
                orig = ob.original
                if use_render_visibility:
                    if orig.hide_render or not orig.visible_get():
                        continue
                if exclude and any(pat in orig.name.casefold() for pat in exclude):
                    continue
                ev = ob.evaluated_get(depsgraph)
                cv = getattr(ev, "data", None)
                if cv is None:
                    continue
                arr = _curves_arrays(cv)
                if arr is None:
                    continue
                pos, rad, first, length = arr
                mw = _mat4_to_np(ev.matrix_world).astype(np.float64)
                scale = float(np.linalg.norm(mw[:3, :3], axis=0).mean()) or 1.0
                world = pos.astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]
                for c in range(len(first)):
                    f = int(first[c])
                    n = int(length[c])
                    if n < 2 or f < 0 or f + n > len(world):
                        continue
                    pts, rr = _resample_run(world[f:f + n], rad[f:f + n], per_strand)
                    strand_chunks.append(np.ascontiguousarray(pts, np.float32))
                    strand_radius.append(np.ascontiguousarray(
                        np.clip(rr * scale, 1e-4, 0.5), np.float32))
                    strand_offsets.append(strand_offsets[-1] + len(pts))
                    strand_total += len(pts)
                    if len(strand_chunks) >= max_strands or strand_total >= 200000:
                        break

        if not tri_chunks and not strand_chunks:
            raise LineForgeError("LineForge: no renderable mesh or curve geometry in the scene "
                                 "(check visibility and Exclude Objects)")
    finally:
        for mod, vp, rn in restore:
            mod.show_viewport = vp
            mod.show_render = rn
        if restore:
            try:
                bpy.context.view_layer.update()
            except Exception:  # noqa: BLE001 - scene state is already restored
                pass

    if tri_chunks:
        verts = np.ascontiguousarray(np.concatenate(verts_chunks, axis=0), np.float32)
        tris = np.ascontiguousarray(np.concatenate(tri_chunks, axis=0), np.int32)
        tri_normals = np.ascontiguousarray(np.concatenate(nrm_chunks, axis=0), np.float32)
        tri_mat = np.ascontiguousarray(np.concatenate(mat_chunks, axis=0), np.int32)
        tri_obj = np.ascontiguousarray(np.concatenate(obj_chunks, axis=0), np.int32)
        tri_skip = np.ascontiguousarray(np.concatenate(skip_chunks, axis=0), np.uint8)
    else:  # curves-only scene: no surface to rasterise, strands only
        verts = np.zeros((0, 3), np.float32)
        tris = np.zeros((0, 3), np.int32)
        tri_normals = np.zeros((0, 3), np.float32)
        tri_mat = np.zeros((0,), np.int32)
        tri_obj = np.zeros((0,), np.int32)
        tri_skip = np.zeros((0,), np.uint8)

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
    if strand_chunks:
        snap.strand_pts = np.ascontiguousarray(np.concatenate(strand_chunks, axis=0), np.float32)
        snap.strand_radius = np.ascontiguousarray(np.concatenate(strand_radius, axis=0), np.float32)
        snap.strand_offsets = np.ascontiguousarray(strand_offsets, np.int32)
        snap.nstrands = len(strand_chunks)
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
    if snap.strand_pts is not None:
        d["strand_pts"] = snap.strand_pts
        d["strand_offsets"] = snap.strand_offsets
        d["strand_radius"] = snap.strand_radius
    return d
