// LineForge pybind11 bindings — Blender 5.2 (CPython 3.13) extension module.
// GPL-2.0-or-later.
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstring>
#include <stdexcept>

#include "core.hpp"

namespace py = pybind11;

namespace {

using F32Arr = py::array_t<float, py::array::c_style | py::array::forcecast>;
using I32Arr = py::array_t<int32_t, py::array::c_style | py::array::forcecast>;
using U8Arr = py::array_t<uint8_t, py::array::c_style | py::array::forcecast>;

F32Arr get_f32(const py::dict& d, const char* key, int ndim, int cols = -1) {
    if (!d.contains(key)) throw std::runtime_error(std::string("missing scene field: ") + key);
    F32Arr a = d[key].cast<F32Arr>();
    if (a.ndim() != ndim) throw std::runtime_error(std::string("bad ndim for ") + key);
    if (cols > 0 && a.shape(ndim - 1) != cols)
        throw std::runtime_error(std::string("bad width for ") + key);
    return a;
}

I32Arr get_i32(const py::dict& d, const char* key, int ndim, int cols = -1) {
    if (!d.contains(key)) throw std::runtime_error(std::string("missing scene field: ") + key);
    I32Arr a = d[key].cast<I32Arr>();
    if (a.ndim() != ndim) throw std::runtime_error(std::string("bad ndim for ") + key);
    if (cols > 0 && a.shape(ndim - 1) != cols)
        throw std::runtime_error(std::string("bad width for ") + key);
    return a;
}

lf::Rgba parse_color(const py::handle& h, float default_alpha = 1.f) {
    lf::Rgba c;
    c.a = default_alpha;
    if (py::isinstance<py::tuple>(h) || py::isinstance<py::list>(h)) {
        auto seq = py::reinterpret_borrow<py::sequence>(h);
        const size_t n = seq.size();
        if (n < 3) throw std::runtime_error("color needs >= 3 components");
        c.r = seq[0].cast<float>();
        c.g = seq[1].cast<float>();
        c.b = seq[2].cast<float>();
        if (n > 3) c.a = seq[3].cast<float>();
    } else {
        throw std::runtime_error("color must be a tuple/list");
    }
    return c;
}

lf::Style parse_style(const py::dict& d) {
    lf::Style s;
    s.enabled = d.contains("enabled") ? d["enabled"].cast<bool>() : s.enabled;
    if (d.contains("width")) s.width = d["width"].cast<float>();
    if (d.contains("world_space")) s.world_space = d["world_space"].cast<bool>();
    if (d.contains("color")) s.color = parse_color(d["color"]);
    if (d.contains("taper_in")) s.taper_in = d["taper_in"].cast<float>();
    if (d.contains("taper_out")) s.taper_out = d["taper_out"].cast<float>();
    if (d.contains("random_width")) s.random_width = d["random_width"].cast<float>();
    if (d.contains("distance_fade")) s.distance_fade = d["distance_fade"].cast<float>();
    if (d.contains("fade_start")) s.fade_start = d["fade_start"].cast<float>();
    if (d.contains("pattern")) s.pattern = d["pattern"].cast<int>();
    if (d.contains("pattern_period")) s.pattern_period = d["pattern_period"].cast<float>();
    if (d.contains("pattern_duty")) s.pattern_duty = d["pattern_duty"].cast<float>();
    if (d.contains("texture")) s.texture = d["texture"].cast<int>();
    if (d.contains("texture_scale")) s.texture_scale = d["texture_scale"].cast<float>();
    if (d.contains("simplify_px")) s.simplify_px = d["simplify_px"].cast<float>();
    return s;
}

py::dict line_to_dict(const lf::Polyline& pl) {
    py::dict d;
    const size_t n = pl.pts.size();
    py::array_t<float> pts({py::ssize_t(n), py::ssize_t(2)});
    py::array_t<float> widths(static_cast<py::ssize_t>(n));
    float* pp = pts.mutable_data();
    float* wp = widths.mutable_data();
    for (size_t i = 0; i < n; ++i) {
        pp[2 * i + 0] = pl.pts[i].x;
        pp[2 * i + 1] = pl.pts[i].y;
        wp[i] = pl.widths.empty() ? 1.f : pl.widths[i];
    }
    py::array_t<float> color(4);
    float* cp = color.mutable_data();
    cp[0] = pl.color.r;
    cp[1] = pl.color.g;
    cp[2] = pl.color.b;
    cp[3] = pl.color.a;
    d["points"] = pts;
    d["widths"] = widths;
    d["color"] = color;
    d["type"] = pl.type;
    return d;
}

py::dict render_scene(const py::dict& scene, const py::dict& settings) {
    lf::SceneView sv;
    lf::Settings S;

    F32Arr verts = get_f32(scene, "verts", 2, 3);
    I32Arr tris = get_i32(scene, "tris", 2, 3);
    F32Arr tri_normals = get_f32(scene, "tri_normals", 2, 3);
    I32Arr edges = get_i32(scene, "edges", 2, 2);
    F32Arr mvp = get_f32(scene, "mvp", 2, 4);
    F32Arr proj = get_f32(scene, "proj", 2, 4);

    sv.verts = verts.data();
    sv.nverts = int(verts.shape(0));
    sv.tris = tris.data();
    sv.ntris = int(tris.shape(0));
    sv.tri_normals = tri_normals.data();
    sv.edges = edges.data();
    sv.nedges = int(edges.shape(0));

    F32Arr cam = get_f32(scene, "cam_pos", 1, 3);
    sv.cam_pos = lf::Vec3{cam.data()[0], cam.data()[1], cam.data()[2]};
    std::memcpy(sv.mvp.m, mvp.data(), sizeof(float) * 16);
    std::memcpy(sv.proj.m, proj.data(), sizeof(float) * 16);

    F32Arr view;
    if (scene.contains("view") && !scene["view"].is_none()) {
        view = get_f32(scene, "view", 2, 4);
        sv.view = view.data();
    }

    I32Arr tri_mat, tri_obj, edge_tris;
    U8Arr edge_sel, obj_sel, tri_skip;
    if (scene.contains("tri_mat") && !scene["tri_mat"].is_none()) {
        tri_mat = get_i32(scene, "tri_mat", 1);
        if (tri_mat.shape(0) != sv.ntris) throw std::runtime_error("tri_mat size mismatch");
        sv.tri_mat = tri_mat.data();
    }
    if (scene.contains("tri_obj") && !scene["tri_obj"].is_none()) {
        tri_obj = get_i32(scene, "tri_obj", 1);
        if (tri_obj.shape(0) != sv.ntris) throw std::runtime_error("tri_obj size mismatch");
        sv.tri_obj = tri_obj.data();
    }
    if (scene.contains("edge_tris") && !scene["edge_tris"].is_none()) {
        edge_tris = get_i32(scene, "edge_tris", 2, 2);
        if (edge_tris.shape(0) != sv.nedges) throw std::runtime_error("edge_tris size mismatch");
        sv.edge_tris = edge_tris.data();
    }
    if (scene.contains("tri_skip") && !scene["tri_skip"].is_none()) {
        tri_skip = scene["tri_skip"].cast<U8Arr>();
        if (tri_skip.ndim() != 1 || tri_skip.shape(0) != sv.ntris)
            throw std::runtime_error("tri_skip size mismatch");
        sv.tri_skip = tri_skip.data();
    }
    if (scene.contains("edge_sel") && !scene["edge_sel"].is_none()) {
        edge_sel = scene["edge_sel"].cast<U8Arr>();
        if (edge_sel.ndim() != 1 || edge_sel.shape(0) != sv.nedges)
            throw std::runtime_error("edge_sel size mismatch");
        sv.edge_sel = edge_sel.data();
    }
    if (scene.contains("obj_sel") && !scene["obj_sel"].is_none()) {
        obj_sel = scene["obj_sel"].cast<U8Arr>();
        if (obj_sel.ndim() != 1) throw std::runtime_error("obj_sel must be 1-D");
        sv.obj_sel = obj_sel.data();
        sv.nobj = int(obj_sel.shape(0));
    }

    F32Arr strand_pts, strand_radius;
    I32Arr strand_offsets;
    if (scene.contains("strand_pts") && !scene["strand_pts"].is_none()) {
        strand_pts = get_f32(scene, "strand_pts", 2, 3);
        strand_offsets = get_i32(scene, "strand_offsets", 1);
        if (strand_offsets.shape(0) < 2) throw std::runtime_error("strand_offsets too short");
        sv.strand_pts = strand_pts.data();
        sv.nstrand_pts = int(strand_pts.shape(0));
        sv.strand_offsets = strand_offsets.data();
        sv.nstrands = int(strand_offsets.shape(0)) - 1;
        if (scene.contains("strand_radius") && !scene["strand_radius"].is_none()) {
            strand_radius = get_f32(scene, "strand_radius", 1);
            if (strand_radius.shape(0) != sv.nstrand_pts)
                throw std::runtime_error("strand_radius size mismatch");
            sv.strand_radius = strand_radius.data();
        }
    }

    if (settings.contains("width")) S.width = settings["width"].cast<int>();
    if (settings.contains("height")) S.height = settings["height"].cast<int>();
    if (settings.contains("want_image")) S.want_image = settings["want_image"].cast<bool>();
    if (settings.contains("hidden_lines")) S.hidden_lines = settings["hidden_lines"].cast<bool>();
    if (settings.contains("hidden_alpha")) S.hidden_alpha = settings["hidden_alpha"].cast<float>();
    if (settings.contains("hidden_width")) S.hidden_width = settings["hidden_width"].cast<float>();
    if (settings.contains("want_hidden_image"))
        S.want_hidden_image = settings["want_hidden_image"].cast<bool>();
    if (settings.contains("want_depth")) S.want_depth = settings["want_depth"].cast<bool>();
    if (settings.contains("cull_backfaces")) S.cull_backfaces = settings["cull_backfaces"].cast<int>();
    if (settings.contains("crease_angle_deg"))
        S.crease_angle_deg = settings["crease_angle_deg"].cast<float>();
    if (settings.contains("depth_bias")) S.depth_bias = settings["depth_bias"].cast<float>();
    if (settings.contains("simplify_px")) S.simplify_px = settings["simplify_px"].cast<float>();
    if (settings.contains("seed")) S.seed = settings["seed"].cast<int>();
    if (settings.contains("use_material_color"))
        S.use_material_color = settings["use_material_color"].cast<bool>();
    if (settings.contains("intersection_depth_tol"))
        S.intersection_depth_tol = settings["intersection_depth_tol"].cast<float>();
    if (settings.contains("draw_strands")) S.draw_strands = settings["draw_strands"].cast<bool>();
    if (settings.contains("strand_width_scale"))
        S.strand_width_scale = settings["strand_width_scale"].cast<float>();
    if (settings.contains("strand_min_px"))
        S.strand_min_px = settings["strand_min_px"].cast<float>();
    if (settings.contains("strand_color") && !settings["strand_color"].is_none())
        S.strand_color = parse_color(settings["strand_color"]);

    if (settings.contains("styles") && !settings["styles"].is_none()) {
        auto seq = py::reinterpret_borrow<py::sequence>(settings["styles"]);
        const size_t n = std::min<size_t>(seq.size(), lf::LT_COUNT);
        for (size_t i = 0; i < n; ++i) S.styles[i] = parse_style(seq[i].cast<py::dict>());
    }

    if (settings.contains("material_colors") && !settings["material_colors"].is_none()) {
        auto seq = py::reinterpret_borrow<py::sequence>(settings["material_colors"]);
        S.material_colors.reserve(seq.size());
        for (auto item : seq) S.material_colors.push_back(parse_color(item));
    }

    if (settings.contains("brush") && !settings["brush"].is_none()) {
        const py::dict bd = settings["brush"].cast<py::dict>();
        if (bd.contains("profile") && !bd["profile"].is_none()) {
            auto seq = py::reinterpret_borrow<py::sequence>(bd["profile"]);
            S.brush.profile.reserve(seq.size());
            for (auto v : seq) S.brush.profile.push_back(v.cast<float>());
        }
        if (bd.contains("repeat")) S.brush.repeat = bd["repeat"].cast<float>();
        if (bd.contains("width_amp")) S.brush.width_amp = bd["width_amp"].cast<float>();
        if (bd.contains("alpha_amp")) S.brush.alpha_amp = bd["alpha_amp"].cast<float>();
        if (bd.contains("offset_random"))
            S.brush.offset_random = bd["offset_random"].cast<float>();
    }

    if (S.width <= 0 || S.height <= 0) throw std::runtime_error("invalid render size");

    const lf::Result r = lf::render(sv, S);

    py::dict out;
    py::array_t<float> image;
    if (!r.image.empty()) {
        image = py::array_t<float>({py::ssize_t(r.height), py::ssize_t(r.width), py::ssize_t(4)});
        std::memcpy(image.mutable_data(), r.image.data(), sizeof(float) * r.image.size());
        out["image"] = image;
    } else {
        out["image"] = py::none();
    }

    if (!r.hidden_image.empty()) {
        py::array_t<float> hidden(
            {py::ssize_t(r.height), py::ssize_t(r.width), py::ssize_t(4)});
        std::memcpy(hidden.mutable_data(), r.hidden_image.data(),
                    sizeof(float) * r.hidden_image.size());
        out["hidden_image"] = hidden;
    } else {
        out["hidden_image"] = py::none();
    }

    if (!r.depth_image.empty()) {
        py::array_t<float> depth({py::ssize_t(r.height), py::ssize_t(r.width)});
        std::memcpy(depth.mutable_data(), r.depth_image.data(),
                    sizeof(float) * r.depth_image.size());
        out["depth_image"] = depth;
    } else {
        out["depth_image"] = py::none();
    }

    py::list lines;
    for (const auto& pl : r.lines) lines.append(line_to_dict(pl));
    out["lines"] = lines;

    py::dict stats;
    stats["tri_count"] = r.tri_count;
    stats["edge_count"] = r.edge_count;
    stats["stroke_count"] = r.stroke_count;
    stats["time_ms"] = r.time_ms;
    stats["raster_ms"] = r.raster_ms;
    stats["stroke_ms"] = r.stroke_ms;
    stats["composite_ms"] = r.composite_ms;
    stats["width"] = r.width;
    stats["height"] = r.height;
    out["stats"] = stats;
    return out;
}

} // namespace

PYBIND11_MODULE(lineforge_core, m) {
    m.doc() = "LineForge CPU line-rendering core";
    m.attr("__version__") = "0.4.0";
    m.attr("LT_OBJECT") = int(lf::LT_OBJECT);
    m.attr("LT_CREASE") = int(lf::LT_CREASE);
    m.attr("LT_BOUNDARY") = int(lf::LT_BOUNDARY);
    m.attr("LT_MATERIAL") = int(lf::LT_MATERIAL);
    m.attr("LT_INTERSECTION") = int(lf::LT_INTERSECTION);
    m.attr("LT_COUNT") = int(lf::LT_COUNT);
    m.def("render_scene", &render_scene, py::arg("scene"), py::arg("settings"),
          "Render line art for a prepared scene view; returns image + polylines + stats.");
}
