# LineForge core smoke test — builds cube scenes in memory and renders them.
# GPL-2.0-or-later.
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "build"))

import lineforge_core as core  # noqa: E402


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye = np.asarray(eye, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    view = np.eye(4)
    view[0, :3] = s
    view[1, :3] = u
    view[2, :3] = -f
    view[0, 3] = -np.dot(s, eye)
    view[1, 3] = -np.dot(u, eye)
    view[2, 3] = np.dot(f, eye)
    return view


def perspective(fov_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fov_deg) * 0.5)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


QUADS = [
    (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
]


def cube_geometry(center=(0.0, 0.0, 0.0), size=1.0):
    """Unit cube (half extent = size) as 12 triangles with outward normals."""
    base = np.array(
        [
            [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
            [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
        ],
        dtype=np.float32,
    )
    verts = base * np.float32(size) + np.asarray(center, dtype=np.float32)
    tris, tri_normals = [], []
    for a, b, c, d in QUADS:
        for idx in ((a, b, c), (a, c, d)):
            p0, p1, p2 = verts[list(idx)]
            n = np.cross(p1 - p0, p2 - p0)
            n /= np.linalg.norm(n)
            tris.append(idx)
            tri_normals.append(n)
    return verts, np.array(tris, dtype=np.int32), np.array(tri_normals, dtype=np.float32)


def edge_table(tris):
    edge_map = {}
    for ti, t in enumerate(tris):
        for k in range(3):
            a, b = int(t[k]), int(t[(k + 1) % 3])
            key = (min(a, b), max(a, b))
            edge_map.setdefault(key, []).append(ti)
    keys = sorted(edge_map)
    edges = np.array(keys, dtype=np.int32)
    edge_tris = np.array(
        [[edge_map[k][0], edge_map[k][1] if len(edge_map[k]) > 1 else -1] for k in keys],
        dtype=np.int32,
    )
    return edges, edge_tris


def scene_dict(vertices, tris, normals, tri_obj, width, height, camera=(3.2, 2.4, 3.6)):
    edges, edge_tris = edge_table(tris)
    proj = perspective(40.0, width / height, 0.1, 100.0)
    view = look_at(camera, (0, 0, 0))
    return {
        "verts": vertices.reshape(-1, 3).astype(np.float32),
        "tris": tris.astype(np.int32),
        "tri_normals": normals.reshape(-1, 3).astype(np.float32),
        "tri_mat": np.zeros(len(tris), dtype=np.int32),
        "tri_obj": np.asarray(tri_obj, dtype=np.int32),
        "edges": edges,
        "edge_tris": edge_tris,
        "mvp": (proj @ view).astype(np.float32),
        "proj": proj.astype(np.float32),
        "cam_pos": np.asarray(camera, dtype=np.float32),
    }


def cube_scene(width, height):
    verts, tris, normals = cube_geometry()
    return scene_dict(verts, tris, normals, np.zeros(len(tris)), width, height)


def two_cube_scene(width, height):
    """Front cube at the origin plus a second cube tucked behind it."""
    v0, t0, n0 = cube_geometry((0.0, 0.0, 0.0), 1.0)
    v1, t1, n1 = cube_geometry((-1.28, -0.96, -1.44), 1.0)
    verts = np.vstack([v0, v1])
    tris = np.vstack([t0, t1 + np.int32(8)])
    normals = np.vstack([n0, n1])
    tri_obj = np.array([0] * len(t0) + [1] * len(t1), dtype=np.int32)
    return scene_dict(verts, tris, normals, tri_obj, width, height)


def base_styles(**kw):
    styles = [dict(enabled=False, width=2.0, color=(0, 0, 0, 1)) for _ in range(5)]
    styles[core.LT_OBJECT] = dict(enabled=True, **kw)
    return styles


def main():
    width, height = 320, 240
    scene = cube_scene(width, height)

    styles = [dict(enabled=False, width=2.0, color=(0.0, 0.0, 0.0, 1.0)) for _ in range(5)]
    styles[core.LT_OBJECT] = dict(enabled=True, width=2.5, color=(0.05, 0.05, 0.05, 1.0))
    styles[core.LT_CREASE] = dict(enabled=True, width=1.5, color=(0.2, 0.1, 0.6, 1.0))
    settings = dict(width=width, height=height, want_image=True, crease_angle_deg=30.0, styles=styles)

    out = core.render_scene(scene, settings)
    stats = out["stats"]
    img = out["image"]
    print("stats", dict(stats))
    print("image", None if img is None else (img.shape, img.dtype))
    print("lines", len(out["lines"]))
    if out["lines"]:
        types = {}
        for pl in out["lines"]:
            types[int(pl["type"])] = types.get(int(pl["type"]), 0) + 1
        print("line types", types)
        print("first line pts", out["lines"][0]["points"].shape)

    if img is not None:
        cov = float((img[..., 3] > 0.0).mean())
        print("coverage", round(cov, 4))
        assert cov > 0.0, "image is empty"
    assert stats["tri_count"] == 12, stats
    assert len(out["lines"]) > 0, "no strokes emitted"

    # Second pass without image to check the cheap path.
    settings2 = dict(settings)
    settings2["want_image"] = False
    out2 = core.render_scene(scene, settings2)
    print("no-image stats", dict(out2["stats"]))
    assert out2["image"] is None
    print("SMOKE OK")


if __name__ == "__main__":
    main()
