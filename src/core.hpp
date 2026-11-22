// LineForge core — CPU line-rendering engine (Blender 5.2 integration).
// GPL-2.0-or-later.
#pragma once

#include <cstdint>
#include <cmath>
#include <vector>
#include <string>

namespace lf {

struct Vec2 { float x = 0.f, y = 0.f; };
struct Vec3 { float x = 0.f, y = 0.f, z = 0.f; };
struct Mat4 { float m[16] = {0}; };

inline Vec3 m3(const Mat4& a, const Vec3& v) {
    Vec3 r;
    r.x = a.m[0] * v.x + a.m[1] * v.y + a.m[2] * v.z + a.m[3];
    r.y = a.m[4] * v.x + a.m[5] * v.y + a.m[6] * v.z + a.m[7];
    r.z = a.m[8] * v.x + a.m[9] * v.y + a.m[10] * v.z + a.m[11];
    return r;
}

inline float dot3(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline Vec3 sub3(const Vec3& a, const Vec3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }

struct Rgba { float r = 0, g = 0, b = 0, a = 1; };

enum LineType : int {
    LT_OBJECT = 0,        // silhouette / object outline
    LT_CREASE = 1,        // interior crease (edge angle)
    LT_BOUNDARY = 2,      // mesh open border
    LT_MATERIAL = 3,      // material boundary
    LT_INTERSECTION = 4,  // object-object intersection (G-buffer)
    LT_COUNT = 5
};

struct Style {
    bool enabled = false;
    float width = 2.0f;        // pixels (or world units when world_space)
    bool world_space = false;
    Rgba color{0.f, 0.f, 0.f, 1.f};
    float taper_in = 0.f;      // pixels
    float taper_out = 0.f;     // pixels
    float random_width = 0.f;  // 0..1 amplitude
    float distance_fade = 0.f; // fade length in view units, 0 = off
    float fade_start = 0.f;    // view distance where fade begins
};

struct Brush {
    std::vector<float> profile; // 0..1 width multipliers
    float repeat = 1.0f;        // cycles per 256 px
    float width_amp = 0.f;      // 0..1
    float alpha_amp = 0.f;      // 0..1
    float offset_random = 0.f;  // 0..1 random phase per stroke
};

struct Settings {
    int width = 1920;
    int height = 1080;
    bool want_image = true;
    bool hidden_lines = false;
    float hidden_alpha = 0.25f;
    float hidden_width = 0.5f;
    float crease_angle_deg = 60.f;
    float depth_bias = 0.0015f; // relative to view depth
    float simplify_px = 0.6f;

    Style styles[LT_COUNT];
    Brush brush;
    bool use_material_color = false;
    std::vector<Rgba> material_colors;

    float intersection_depth_tol = 0.01f;
    int seed = 12345;
};

struct SceneView {
    const float* verts = nullptr;
    int nverts = 0;
    const int32_t* tris = nullptr;
    int ntris = 0;
    const float* tri_normals = nullptr;
    const int32_t* tri_mat = nullptr;
    const int32_t* tri_obj = nullptr;
    const int32_t* edges = nullptr;
    int nedges = 0;
    const int32_t* edge_tris = nullptr; // 2 per edge, -1 when missing
    const uint8_t* edge_sel = nullptr;  // optional per-edge keep flag
    const uint8_t* tri_skip = nullptr;  // optional per-triangle skip flag (helper hulls)
    const uint8_t* obj_sel = nullptr;   // optional per-object keep flag (intersections)
    int nobj = 0;
    Mat4 mvp;
    Mat4 proj;
    const float* view = nullptr; // optional world->camera matrix (row-major), enables true w/depth
    Vec3 cam_pos;
};

struct Polyline {
    std::vector<Vec2> pts;      // screen space (px, origin top-left)
    std::vector<float> widths;  // px per point
    Rgba color;
    int type = 0;
};

struct Result {
    int width = 0;
    int height = 0;
    std::vector<float> image; // RGBA premultiplied, row-major, top-left origin
    std::vector<Polyline> lines;
    int tri_count = 0;
    int edge_count = 0;
    int stroke_count = 0;
    double time_ms = 0.0;
};

Result render(const SceneView& sv, const Settings& s);

} // namespace lf
