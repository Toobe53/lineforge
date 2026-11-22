# LineForge — render pipeline (scene -> native core -> image/compositor).
# GPL-2.0-or-later.
import fnmatch
import os
import platform
import sys
import tempfile
import time

import bpy
import numpy as np

from . import nodes as lfnodes
from .errors import LineForgeError
from .scene_extract import extract, scene_dict

ADDON_VERSION = "0.4.0"
_CORE = None
_CORE_INFO = {"available": False, "path": "", "version": "", "error": "not initialised"}
_SUPPRESS_HANDLER = False
_RENDERING = False
_LAST = {"lines": [], "stats": {}, "image": None, "size": (0, 0), "render_id": 0}
_RENDER_ID = 0


# ------------------------------------------------------------------ core ---

def platform_tag():
    """Directory name of the native binary for this interpreter ('win64', 'linux-x64', ...)."""
    machine = (platform.machine() or "").lower()
    if sys.platform == "win32":
        return "win64" if machine in ("amd64", "x86_64", "") else "win-arm64"
    if sys.platform.startswith("linux"):
        return "linux-arm64" if machine in ("aarch64", "arm64") else "linux-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    return "unknown"


def _binary_names():
    if sys.platform == "win32":
        return ("lineforge_core.pyd",)
    return ("lineforge_core.so", "lineforge_core.dylib", "lineforge_core.pyd")


def _candidate_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    bindir = os.path.join(here, "bin")
    return [os.path.join(bindir, platform_tag()), bindir]


def core():
    """Import the native core, or raise LineForgeError with an actionable message."""
    global _CORE
    if _CORE is not None:
        return _CORE

    tried = []
    error = None
    for directory in _candidate_dirs():
        found = [os.path.join(directory, n) for n in _binary_names() if os.path.isfile(os.path.join(directory, n))]
        if not found:
            tried.append(directory)
            continue
        if directory not in sys.path:
            sys.path.insert(0, directory)
        sys.modules.pop("lineforge_core", None)
        try:
            import lineforge_core  # type: ignore
        except ImportError as exc:  # ABI mismatch, missing DLL, wrong arch
            error = "%s (%s)" % (exc, os.path.basename(directory) or directory)
            continue
        _CORE = lineforge_core
        version = getattr(lineforge_core, "__version__", "")
        _CORE_INFO.update(available=True, path=found[0], version=str(version), error="")
        if version and version != ADDON_VERSION:
            _CORE_INFO["error"] = "core %s != add-on %s" % (version, ADDON_VERSION)
        return _CORE

    _CORE_INFO.update(available=False, path="", version="", error=error or "binary not found")
    hint = (
        "LineForge: native core for '%s' was not found or failed to load.\n"
        "Looked in: %s\n"
        "Build it with 'python tools/build.py' (or build.ps1 on Windows) and copy\n"
        "the result into addon/lineforge/bin/%s/."
        % (platform_tag(), ", ".join(tried) or "addon/lineforge/bin", platform_tag())
    )
    if error:
        hint += "\nLast import error: %s" % error
    raise LineForgeError(hint)


def reset_core():
    """Forget the cached module/status so the next core() retries the import.

    A transient failure (file being replaced, a network profile path not mounted yet)
    must not latch the add-on into "unavailable" for the rest of the session.
    """
    global _CORE
    _CORE = None
    _CORE_INFO.update(available=False, path="", version="", error="not initialised")


def core_info():
    """Status of the native core for the UI (never raises)."""
    global _CORE_INFO
    if _CORE is None and _CORE_INFO.get("error") == "not initialised":
        try:
            core()
        except LineForgeError as exc:
            _CORE_INFO["error"] = str(exc)
    return dict(_CORE_INFO)


def last_lines():
    return _LAST["lines"]


def last_stats():
    return _LAST["stats"]


def last_render_id():
    return int(_LAST.get("render_id", 0))


def last_hidden():
    """Hidden-stroke AOV of the last render (H, W, 4 premultiplied) or None."""
    return _LAST.get("hidden")


def last_depth():
    """Depth AOV of the last render (H, W float view depth, 0 = background) or None."""
    return _LAST.get("depth")


def last_passes():
    """Files written by the last save_passes() call."""
    return list(_LAST.get("passes", []))


# -------------------------------------------------------------- settings ---

def _style_from_node(node, scene, scale):
    color = tuple(node.color)
    width = max(0.05, float(node.width) * scale)
    lf = scene.lf
    simplify = float(node.simplify_px) if bool(node.simplify_override) else -1.0
    return {
        "enabled": True,
        "width": width,
        "world_space": bool(node.world_space),
        "color": [float(color[0]), float(color[1]), float(color[2]), float(color[3])],
        "taper_in": float(node.taper_in),
        "taper_out": float(node.taper_out),
        "random_width": float(node.random_width),
        "distance_fade": float(node.distance_fade),
        "fade_start": float(node.fade_start),
        "pattern": PATTERN_INDEX.get(node.pattern, 0),
        "pattern_period": max(2.0, float(node.pattern_period) * scale),
        "pattern_duty": float(node.pattern_duty),
        "texture": TEXTURE_INDEX.get(node.texture, 0),
        "texture_scale": float(node.texture_scale),
        "simplify_px": simplify * scale if simplify >= 0.0 else -1.0,
    }


PATTERN_INDEX = {"SOLID": 0, "DASH": 1, "DOT": 2}
TEXTURE_INDEX = {"NONE": 0, "CHARCOAL": 1, "PENCIL": 2, "INK": 3}


def _empty_styles():
    return [{"enabled": False, "width": 1.0, "color": [0, 0, 0, 1]} for _ in range(5)]


def build_settings(snap, node, scene, width, height, scale_mul=1.0):
    lf = scene.lf
    out = lfnodes.output_node(lf.node_tree) if lf.node_tree else None
    scale = float(lf.line_scale) * float(scale_mul)
    styles = _empty_styles()
    idx = lfnodes.LINE_TYPE_INDEX[node.line_type]
    styles[idx] = _style_from_node(node, scene, scale)
    if getattr(snap, "cam_ortho", False) and styles[idx].get("world_space"):
        if bool(getattr(lf, "ortho_width_falloff", False)):
            # Keep world-space widths: the core multiplies by focal/depth, and for an ortho
            # camera proj[5] = 2/ortho_scale, so focal = height/ortho_scale (pixels per world
            # unit). Geometry further from the camera plane therefore draws thinner lines,
            # matching the perspective behaviour the user asked for.
            pass
        else:
            # Constant scale (parallel projection semantics): convert here, hand screen widths.
            ortho = max(1e-6, float(getattr(snap, "cam_ortho_scale", 1.0)))
            styles[idx]["width"] = styles[idx]["width"] * (float(height) / ortho)
            styles[idx]["world_space"] = False
    crease = float(lf.crease_angle)
    if node.line_type == 'CREASE' and node.crease_override:
        crease = float(node.crease_angle)
    settings = {
        "width": int(width),
        "height": int(height),
        "want_image": True,
        "crease_angle_deg": crease,
        "depth_bias": float(out.depth_bias) if out else 0.0015,
        "simplify_px": float(out.simplify_px) if out else 0.6,
        "seed": int(lf.seed),
        "use_material_color": bool(out.use_material_color) if out else False,
        "material_colors": [list(c) for c in snap.mat_colors],
        "intersection_depth_tol": float(lf.intersection_tol),
        "hidden_lines": bool(lf.hidden_lines),
        "hidden_alpha": float(lf.hidden_alpha),
        "hidden_width": float(lf.hidden_width),
        "cull_backfaces": {"OFF": 0, "BACK": 2, "FRONT": 1}.get(
            str(getattr(lf, "cull_backfaces", "BACK")), 2),
        # Hair strands follow the object-outline pass so they are never drawn twice.
        "draw_strands": bool(getattr(lf, "hair_lines", True)) and str(node.line_type) == 'OBJECT',
        "strand_width_scale": float(getattr(lf, "hair_width", 1.0)),
        "strand_min_px": 0.6,
        "strand_color": list(styles[idx].get("color", [0.0, 0.0, 0.0, 1.0])),
        "styles": styles,
        "brush": {
            "profile": _brush_profile(node),
            "repeat": float(getattr(node, "texture_repeat", node.brush_repeat)),
            "width_amp": _brush_width_amp(node),
            "alpha_amp": float(node.brush_alpha_amp),
            "offset_random": float(node.brush_offset_random),
        },
    }
    return settings


# ------------------------------------------------------- brush textures ---

_PROFILE_CACHE = {}


def _image_fingerprint(img):
    """Cheap identity of an image's pixels (size + a few sampled values)."""
    w, h = int(img.size[0]), int(img.size[1])
    if w <= 0 or h <= 0:
        return (img.name, w, h)
    px = img.pixels
    n = w * h * 4
    samples = []
    for k in range(8):
        idx = (k * 7919 * 4) % n
        try:
            samples.append(round(float(px[idx]), 4))
        except Exception:  # noqa: BLE001
            break
    return (img.name, w, h, tuple(samples))


def _image_profile(img, channel='LUMA', invert=False, samples=256):
    """Collapse an image into a 1-D stroke profile (0..1 width multipliers)."""
    key = (_image_fingerprint(img), channel, bool(invert), int(samples))
    cached = _PROFILE_CACHE.get(key)
    if cached is not None:
        return cached
    w, h = int(img.size[0]), int(img.size[1])
    if w <= 0 or h <= 0:
        return []
    buf = np.empty(w * h * 4, np.float32)
    try:
        img.pixels.foreach_get(buf)
    except Exception:  # noqa: BLE001 - packed/generated images still expose foreach_get
        return []
    pix = buf.reshape(h, w, 4)
    if channel == 'ALPHA':
        data = pix[..., 3]
    elif channel == 'RED':
        data = pix[..., 0]
    elif channel == 'GREEN':
        data = pix[..., 1]
    elif channel == 'BLUE':
        data = pix[..., 2]
    else:  # luminance
        data = pix[..., :3].mean(axis=2)
    # Average over rows, then box-reduce the columns to `samples`.
    column = data.mean(axis=0)
    n = max(1, min(int(samples), w))
    edges = np.linspace(0, w, n + 1).astype(np.int64)
    profile = []
    for i in range(n):
        i0, i1 = edges[i], max(edges[i] + 1, edges[i + 1])
        profile.append(float(column[i0:i1].mean()))
    lo, hi = min(profile), max(profile)
    span = hi - lo
    if span > 1e-5:
        profile = [(v - lo) / span for v in profile]
    else:
        profile = [1.0] * n
    if invert:
        profile = [1.0 - v for v in profile]
    # A profile of zeros would erase the line; keep a visible floor.
    profile = [max(0.05, v) for v in profile]
    _PROFILE_CACHE[key] = profile
    return profile


def _brush_profile(node):
    img = getattr(node, "texture_image", None)
    if img is not None:
        prof = _image_profile(img, getattr(node, "texture_channel", 'LUMA'),
                              bool(getattr(node, "texture_invert", False)))
        if prof:
            return prof
    return lfnodes.brush_profile(node.brush_preset)


def _brush_width_amp(node):
    if getattr(node, "texture_image", None) is not None:
        return float(getattr(node, "texture_amp", 0.6))
    return float(node.brush_width_amp)


def _glob_patterns(value):
    """Split a comma separated glob list into a lowercase tuple."""
    return tuple(s.strip().casefold() for s in (value or "").split(",") if s.strip())


def _matches_any(name, patterns):
    return any(fnmatch.fnmatchcase(name, pat) or pat in name for pat in patterns)


def _filter_names(names, keep, skip):
    """Boolean mask over `names` honouring keep (empty = all) and skip globs."""
    mask = np.ones(len(names), bool)
    if keep:
        folded = [n.casefold() for n in names]
        mask[:] = [_matches_any(n, keep) for n in folded]
    if skip:
        folded = [n.casefold() for n in names]
        mask &= [not _matches_any(n, skip) for n in folded]
    return mask


def resolve_selection(node, snap):
    """Return (edge_sel, obj_sel) numpy masks, or (None, None) when nothing is filtered.

    Filters combine the source (scene/collection/object) with the per-line-set object
    and material glob lists. `obj_sel` restricts G-buffer intersection detection; the
    edge mask also drops edges whose both adjacent triangles are filtered out.
    """
    names = None
    if node.source_type == 'COLLECTION' and node.collection is not None:
        names = {ob.name for ob in node.collection.all_objects if ob.type in ('MESH', 'CURVES')}
    elif node.source_type == 'OBJECT' and node.object is not None:
        names = {node.object.name}

    keep_obj = _glob_patterns(getattr(node, "filter_objects", ""))
    skip_obj = _glob_patterns(getattr(node, "exclude_objects", ""))
    keep_mat = _glob_patterns(getattr(node, "filter_materials", ""))
    skip_mat = _glob_patterns(getattr(node, "exclude_materials", ""))

    obj_mask = None
    if names is not None:
        obj_mask = np.array([n in names for n in snap.obj_names], bool)
    if keep_obj or skip_obj:
        extra = _filter_names(list(snap.obj_names), keep_obj, skip_obj)
        obj_mask = extra if obj_mask is None else (obj_mask & extra)

    tri_allowed = None
    if obj_mask is not None:
        tri_allowed = obj_mask[snap.tri_obj]

    if keep_mat or skip_mat:
        mat_mask = _filter_names(list(snap.mat_names), keep_mat, skip_mat)
        tri_mat_ok = mat_mask[snap.tri_mat]
        tri_allowed = tri_mat_ok if tri_allowed is None else (tri_allowed & tri_mat_ok)

    if tri_allowed is None:
        return None, None

    t0 = snap.edge_tris[:, 0]
    t1 = snap.edge_tris[:, 1]
    ok0 = np.where(t0 >= 0, tri_allowed[np.maximum(t0, 0)], False)
    ok1 = np.where(t1 >= 0, tri_allowed[np.maximum(t1, 0)], False)
    edge_sel = np.logical_or(ok0, ok1).astype(np.uint8)
    obj_sel = None if obj_mask is None else obj_mask.astype(np.uint8)
    return edge_sel, obj_sel


# -------------------------------------------------------------- pipeline ---

def _alpha_over(dst, src):
    a = src[..., 3:4]
    dst[..., :3] = src[..., :3] + dst[..., :3] * (1.0 - a)
    dst[..., 3:4] = a + dst[..., 3:4] * (1.0 - a)
    return dst


def render(context, width=None, height=None):
    global _RENDERING
    lf = context.scene.lf
    tree = lf.node_tree
    if _RENDERING:
        raise LineForgeError("LineForge: a render is already running")
    if not lf.enabled:
        raise LineForgeError("LineForge is disabled")
    if tree is None:
        raise LineForgeError("LineForge: no node tree assigned to the scene")

    sets = lfnodes.active_sets(tree)
    if not sets:
        raise LineForgeError("LineForge: no enabled line set connected to the output")

    scene = context.scene
    pct = scene.render.resolution_percentage / 100.0
    if width is None:
        width = max(1, int(round(scene.render.resolution_x * pct)))
    if height is None:
        height = max(1, int(round(scene.render.resolution_y * pct)))
    if width < 1 or height < 1 or width > 16384 or height > 16384:
        raise LineForgeError(
            "LineForge: unsupported resolution %dx%d (must be 1..16384)" % (width, height))

    _RENDERING = True
    try:
        return _render_impl(context, scene, lf, sets, int(width), int(height))
    except LineForgeError:
        raise
    except MemoryError:
        raise LineForgeError(
            "LineForge: out of memory at %dx%d (try lowering Supersampling to 1)" % (width, height))
    except Exception as exc:  # noqa: BLE001 - surface any core/extraction failure with context
        raise LineForgeError("LineForge: render failed (%s: %s)" % (type(exc).__name__, exc)) from exc
    finally:
        _RENDERING = False


_SCENE_VERSION = 0
_SNAP_CACHE = {"key": None, "snap": None}


def mark_scene_changed():
    """Invalidate cached extraction (called from the depsgraph handler)."""
    global _SCENE_VERSION
    if _RENDERING:  # our own temporary modifier toggles must not invalidate the snapshot
        return
    _SCENE_VERSION += 1


def invalidate_snapshot():
    _SNAP_CACHE["key"] = None
    _SNAP_CACHE["snap"] = None


def _geometry_signature(context, scene):
    """Cheap fingerprint of the scene's geometry.

    The depsgraph handler already invalidates on normal edits, but scripts can poke
    mesh data without an event; a strided vertex checksum catches those.
    """
    parts = [scene.name, int(scene.frame_current)]
    layer = context.view_layer.name if context.view_layer else ""
    parts.append(layer)
    for ob in scene.objects:
        if ob.type not in ('MESH', 'CURVE', 'CURVES'):
            continue
        me = getattr(ob, "data", None)
        if me is None:
            continue
        parts.append(ob.name)
        m = ob.matrix_world.translation
        parts.append((round(m.x, 4), round(m.y, 4), round(m.z, 4)))
        nv = len(getattr(me, "vertices", ()) or ())
        parts.append(nv)
        if nv:
            co = np.empty(nv * 3, np.float32)
            try:
                me.vertices.foreach_get("co", co)
            except Exception:  # noqa: BLE001 - never break a render over a cache hint
                continue
            stride = max(1, nv // 48)
            parts.append(tuple(np.round(co.reshape(-1, 3)[::stride].sum(axis=0), 4).tolist()))
    return tuple(parts)


def _render_impl(context, scene, lf, sets, width, height):
    t0 = time.perf_counter()
    _LAST["cache_hit"] = False
    exclude = [s for s in getattr(scene.lf, "exclude_objects", "").split(",") if s.strip()]
    ss = max(1, min(4, int(getattr(scene.lf, "supersample", 1))))
    skip_shells = bool(getattr(scene.lf, "skip_outline_shells", True))
    skip_transparent = bool(getattr(scene.lf, "skip_transparent_faces", True))
    alpha_threshold = float(getattr(scene.lf, "alpha_threshold", 0.5))
    keep_names = [s for s in getattr(scene.lf, "skip_transparent_whitelist", "").split(",") if s.strip()]
    hair = bool(getattr(scene.lf, "hair_lines", True))
    hair_max = int(getattr(scene.lf, "hair_max_strands", 4000))
    hair_points = int(getattr(scene.lf, "hair_points", 32))
    want_hidden = bool(getattr(scene.lf, "pass_hidden", False))
    want_depth = bool(getattr(scene.lf, "pass_depth", False))
    rw = width * ss
    rh = height * ss
    sig = _geometry_signature(context, scene)
    key = (int(scene.frame_current), _SCENE_VERSION, sig, rw, rh, tuple(exclude),
           bool(skip_shells), bool(skip_transparent), float(alpha_threshold),
           tuple(keep_names), bool(hair), hair_max, hair_points,
           scene.name, context.view_layer.name if context.view_layer else "")
    snap = _SNAP_CACHE["snap"] if _SNAP_CACHE["key"] == key else None
    if snap is None:
        snap = extract(context, rw, rh, exclude=exclude, skip_shells=skip_shells,
                       skip_transparent=skip_transparent, alpha_threshold=alpha_threshold,
                       transparent_keep=keep_names, hair=hair,
                       hair_max_strands=hair_max, hair_points=hair_points)
        _SNAP_CACHE["key"] = key
        _SNAP_CACHE["snap"] = snap
        _LAST["cache_hit"] = False
    else:
        _LAST["cache_hit"] = True
    accum = np.zeros((rh, rw, 4), np.float32)
    hidden_accum = np.zeros((rh, rw, 4), np.float32) if want_hidden else None
    depth_image = None
    all_lines = []
    total_strokes = 0
    total_ms = 0.0
    raster_ms = 0.0
    stroke_ms = 0.0
    composite_ms = 0.0
    mod = core()

    for index, node in enumerate(sets):
        edge_sel, obj_sel = resolve_selection(node, snap)
        data = scene_dict(snap, edge_sel, obj_sel)
        settings = build_settings(snap, node, scene, rw, rh, scale_mul=ss)
        settings["want_hidden_image"] = want_hidden
        # Depth is scene geometry, not per line set: only the first pass needs it.
        settings["want_depth"] = want_depth and index == 0
        res = mod.render_scene(data, settings)
        img = res["image"]
        if img is not None:
            img = np.asarray(img, np.float32).reshape(rh, rw, 4)
            _alpha_over(accum, img)
        if hidden_accum is not None and res.get("hidden_image") is not None:
            hid = np.asarray(res["hidden_image"], np.float32).reshape(rh, rw, 4)
            _alpha_over(hidden_accum, hid)
        if depth_image is None and res.get("depth_image") is not None:
            depth_image = np.asarray(res["depth_image"], np.float32).reshape(rh, rw)
        all_lines.extend(res["lines"])
        st = res["stats"]
        total_strokes += int(st["stroke_count"])
        total_ms += float(st["time_ms"])
        raster_ms += float(st.get("raster_ms", 0.0))
        stroke_ms += float(st.get("stroke_ms", 0.0))
        composite_ms += float(st.get("composite_ms", 0.0))

    if ss > 1:
        accum = accum.reshape(height, ss, width, ss, 4).mean(axis=(1, 3))
        if hidden_accum is not None:
            hidden_accum = hidden_accum.reshape(height, ss, width, ss, 4).mean(axis=(1, 3))
        if depth_image is not None:
            d = depth_image.reshape(height, ss, width, ss)
            valid = d > 0.0
            count = valid.sum(axis=(1, 3))
            total = np.where(valid, d, 0.0).sum(axis=(1, 3))
            depth_image = np.where(count > 0, total / np.maximum(count, 1), 0.0)
        inv = 1.0 / float(ss)
        for ln in all_lines:
            pts = np.asarray(ln["points"], np.float32)
            ln["points"] = np.ascontiguousarray(pts * inv)
            ln["widths"] = np.asarray(ln["widths"], np.float32) * inv

    elapsed = (time.perf_counter() - t0) * 1000.0
    global _RENDER_ID
    _RENDER_ID += 1
    _LAST["render_id"] = _RENDER_ID
    _LAST["lines"] = all_lines
    _LAST["image"] = accum
    _LAST["hidden"] = hidden_accum
    _LAST["depth"] = depth_image
    _LAST["size"] = (width, height)
    _LAST["stats"] = {
        "lines": len(all_lines),
        "strokes": total_strokes,
        "core_ms": total_ms,
        "raster_ms": raster_ms,
        "stroke_ms": stroke_ms,
        "composite_ms": composite_ms,
        "extract_ms": elapsed - total_ms,
        "total_ms": elapsed,
        "tris": int(snap.tris.shape[0]),
        "edges": int(snap.edges.shape[0]),
        "sets": len(sets),
        "size": (width, height),
        "supersample": ss,
        "cache_hit": bool(_LAST.get("cache_hit", False)),
        "frame": int(scene.frame_current),
    }
    if depth_image is not None:
        valid = depth_image[depth_image > 0.0]
        _LAST["stats"]["depth_min"] = float(valid.min()) if valid.size else 0.0
        _LAST["stats"]["depth_max"] = float(valid.max()) if valid.size else 0.0
        _LAST["stats"]["depth_coverage"] = float((depth_image > 0.0).mean())
    return accum


# ------------------------------------------------------------------ image ---

def write_pass_image(context, rgba, name=None):
    """Write premultiplied RGBA float into a packed Blender image (straight alpha)."""
    lf = context.scene.lf
    name = name or lf.pass_image or "LineForge Pass"
    h, w = rgba.shape[0], rgba.shape[1]
    img = bpy.data.images.get(name)
    if img is not None and (img.size[0] != w or img.size[1] != h):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True)
        img.generated_color = (0.0, 0.0, 0.0, 0.0)
    img.colorspace_settings.name = 'sRGB'
    img.alpha_mode = 'STRAIGHT'

    a = rgba[..., 3:4]
    straight = np.zeros_like(rgba)
    nz = a[..., 0] > 1e-6
    rgb = np.where(nz[..., None], rgba[..., :3] / np.maximum(a, 1e-6), 0.0)
    straight[..., :3] = rgb
    straight[..., 3:4] = a
    # Blender images are bottom-up
    buf = np.ascontiguousarray(straight[::-1].reshape(-1), np.float32)
    img.pixels.foreach_set(buf)
    img.update()
    return img


def write_hidden_image(context, rgba=None, name=None):
    """Write the hidden-stroke AOV into its own Blender image (straight alpha)."""
    lf = context.scene.lf
    rgba = _LAST.get("hidden") if rgba is None else rgba
    if rgba is None:
        return None
    name = name or getattr(lf, "pass_hidden_image", "") or "LineForge Hidden"
    img = write_pass_image(context, rgba, name=name)
    _LAST["hidden_image"] = img
    return img


def write_depth_image(context, depth=None, name=None):
    """Write the depth AOV as an RGBA float image (depth in RGB, 1.0 in alpha).

    Depth stays raw view-space units, so keep the image Non-Color (and save it as
    OpenEXR) or the numbers will be tone-mapped.
    """
    lf = context.scene.lf
    depth = _LAST.get("depth") if depth is None else depth
    if depth is None:
        return None
    name = name or getattr(lf, "pass_depth_image", "") or "LineForge Depth"
    h, w = depth.shape[0], depth.shape[1]
    img = bpy.data.images.get(name)
    if img is not None and (img.size[0] != w or img.size[1] != h):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    img.alpha_mode = 'STRAIGHT'
    rgba = np.empty((h, w, 4), np.float32)
    rgba[..., 0] = depth
    rgba[..., 1] = depth
    rgba[..., 2] = depth
    rgba[..., 3] = 1.0
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1].reshape(-1), np.float32))
    img.update()
    _LAST["depth_image"] = img
    return img


def write_all_passes(context):
    """Materialise every enabled pass (line / hidden / depth) as Blender images."""
    lf = context.scene.lf
    images = {}
    rgba = _LAST.get("image")
    if rgba is not None:
        images["lines"] = write_pass_image(context, rgba)
    if getattr(lf, "pass_hidden", False):
        img = write_hidden_image(context)
        if img is not None:
            images["hidden"] = img
    if getattr(lf, "pass_depth", False):
        img = write_depth_image(context)
        if img is not None:
            images["depth"] = img
    _LAST["pass_images"] = images
    return images


def save_passes(context, filepath):
    """Render and write the enabled passes next to `filepath`.

    Produces `<base>_lines.png`, `<base>_hidden.png` and `<base>_depth.exr`;
    returns the list of files that were written.
    """
    lf = context.scene.lf
    if not filepath:
        raise LineForgeError("LineForge: choose an output path for the passes")
    render(context)
    images = write_all_passes(context)
    base = os.path.splitext(bpy.path.abspath(filepath))[0]
    written = []
    specs = (
        ("lines", base + "_lines.png", 'PNG'),
        ("hidden", base + "_hidden.png", 'PNG'),
        ("depth", base + "_depth.exr", 'OPEN_EXR'),
    )
    for key, path, fmt in specs:
        img = images.get(key)
        if img is None:
            continue
        img.filepath_raw = path
        img.file_format = fmt
        if fmt == 'OPEN_EXR':
            img.save()
        else:
            img.save()
        written.append(path)
    _LAST["passes"] = written
    return written


def setup_compositor(context, img):
    """Wire a dedicated Render Layers -> Alpha Over -> Group Output compositor for the line pass."""
    scene = context.scene
    if not scene.lf.auto_composite:
        return
    ng = bpy.data.node_groups.get("LineForge Compositor")
    if ng is None or ng.bl_idname != 'CompositorNodeTree':
        ng = bpy.data.node_groups.new("LineForge Compositor", 'CompositorNodeTree')
    outputs = [s for s in ng.interface.items_tree if getattr(s, "in_out", "") == 'OUTPUT']
    if not any(s.name == "Image" for s in outputs):
        ng.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    if getattr(scene, "compositing_node_group", None) != ng:
        scene.compositing_node_group = ng

    def get_or_create(idname, name):
        for n in ng.nodes:
            if n.bl_idname == idname and n.name == name:
                return n
        node = ng.nodes.new(idname)
        node.name = name
        return node

    rl = get_or_create('CompositorNodeRLayers', 'LF Render Layers')
    img_node = get_or_create('CompositorNodeImage', 'LF Line Pass')
    img_node.image = img
    if "Straight Alpha" in img_node.inputs:
        img_node.inputs["Straight Alpha"].default_value = 1.0
    ao = get_or_create('CompositorNodeAlphaOver', 'LF Alpha Over')
    ao.inputs['Factor'].default_value = 1.0
    out = None
    for n in ng.nodes:
        if n.bl_idname in {'NodeGroupOutput', 'CompositorNodeComposite'}:
            out = n
            break
    if out is None:
        out = ng.nodes.new('NodeGroupOutput')

    for sock_index in (1, 2):
        for link in list(ao.inputs[sock_index].links):
            ng.links.remove(link)
    if out.inputs and out.inputs[0].links:
        for link in list(out.inputs[0].links):
            ng.links.remove(link)

    if rl.outputs.get('Image'):
        ng.links.new(rl.outputs['Image'], ao.inputs['Background'])
    if img_node.outputs.get('Image'):
        ng.links.new(img_node.outputs['Image'], ao.inputs['Foreground'])
    if out.inputs:
        ng.links.new(ao.outputs[0], out.inputs[0])
    scene.render.use_compositing = True

def render_still(context, filepath=None):
    rgba = render(context)
    img = write_pass_image(context, rgba)
    setup_compositor(context, img)
    if filepath:
        context.scene.render.filepath = filepath
    bpy.ops.render.render(write_still=bool(filepath))
    return img


def _to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def render_composite(context, filepath=None):
    """Render line pass + beauty and merge them into one PNG without the compositor.

    The beauty is rendered with the Standard view transform so both layers live
    in the same display space; the line pass (linear) is encoded to sRGB before
    the straight-alpha merge. No compositor node group is touched.
    """
    scene = context.scene
    rgba = render(context)
    write_pass_image(context, rgba)
    stats = dict(last_stats())

    tmpdir = tempfile.mkdtemp(prefix="lineforge_")
    beauty_path = os.path.join(tmpdir, "beauty.png")
    saved = (scene.render.use_compositing, scene.render.filepath,
             scene.render.image_settings.file_format, scene.render.image_settings.color_mode,
             scene.view_settings.view_transform, scene.view_settings.look)
    try:
        scene.render.use_compositing = False
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGB'
        scene.render.filepath = beauty_path
        bpy.ops.render.render(write_still=True)
    finally:
        (scene.render.use_compositing, scene.render.filepath,
         scene.render.image_settings.file_format, scene.render.image_settings.color_mode,
         scene.view_settings.view_transform, scene.view_settings.look) = saved

    beauty = bpy.data.images.load(beauty_path)
    w, h = rgba.shape[1], rgba.shape[0]
    try:
        beauty.colorspace_settings.name = 'Non-Color'
        beauty.reload()
        b = np.array(beauty.pixels[:], dtype=np.float32).reshape(h, w, 4)
    finally:
        bpy.data.images.remove(beauty)

    a = rgba[::-1, :, 3:4]
    lin = rgba[::-1, :, :3]
    nz = a[..., 0] > 1e-6
    lin_rgb = np.where(nz[..., None], lin / np.maximum(a, 1e-6), 0.0)
    over = np.empty_like(b)
    over[..., :3] = _to_srgb(lin_rgb) * a + b[..., :3] * (1.0 - a)
    over[..., 3] = 1.0

    if not filepath:
        base = os.path.splitext(bpy.data.filepath)[0] if bpy.data.filepath else os.path.join(tmpdir, "lineforge")
        filepath = base + "_lineforge_composite.png"
    img = bpy.data.images.new("LineForge Composite", w, h, alpha=False, float_buffer=True)
    try:
        img.colorspace_settings.name = 'Non-Color'
        img.pixels.foreach_set(np.ascontiguousarray(over.reshape(-1), np.float32))
        img.filepath_raw = filepath
        img.file_format = 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)
    _LAST["composite"] = filepath
    return filepath, stats
