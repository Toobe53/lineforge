// LineForge core — CPU line-rendering engine (Blender 5.2 integration).
// GPL-2.0-or-later.
#include "core.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <limits>
#include <random>
#include <unordered_map>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace lf {
namespace {

constexpr float kInf = std::numeric_limits<float>::infinity();

inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
inline float smoothstepf(float t) { t = clampf(t, 0.f, 1.f); return t * t * (3.f - 2.f * t); }

struct ProjVert {
    float x = 0.f, y = 0.f, d = 0.f;
    bool ok = false;
};

struct EdgePrim {
    int v0 = 0, v1 = 0;
    int type = 0;
    int mat = -1;
};

class Canvas {
public:
    Canvas(int w, int h) : w_(w), h_(h) {
        depth_.assign(size_t(w) * h, kInf);
        faceid_.assign(size_t(w) * h, -1);
        objid_.assign(size_t(w) * h, -1);
        cov_.assign(size_t(w) * h, 0.f);
        pal_.assign(size_t(w) * h, 0);
        covh_.assign(size_t(w) * h, 0.f);
        palh_.assign(size_t(w) * h, 0);
        palette_.push_back(Rgba{0.f, 0.f, 0.f, 0.f});
    }

    uint16_t add_color(const Rgba& c) {
        palette_.push_back(c);
        return uint16_t(palette_.size() - 1);
    }

    void raster_tris(const std::vector<ProjVert>& pv, const SceneView& sv) {
        for (int i = 0; i < sv.ntris; ++i) {
            // Helper geometry (outline hulls, transparent guides) is flagged by the
            // extractor and must not take part in the G-buffer at all.
            if (sv.tri_skip && sv.tri_skip[i]) continue;
            const ProjVert& A = pv[sv.tris[3 * i + 0]];
            const ProjVert& B = pv[sv.tris[3 * i + 1]];
            const ProjVert& C = pv[sv.tris[3 * i + 2]];
            if (!A.ok || !B.ok || !C.ok) continue;
            const float x0 = A.x, y0 = A.y, x1 = B.x, y1 = B.y, x2 = C.x, y2 = C.y;
            const float minx = std::min({x0, x1, x2}), maxx = std::max({x0, x1, x2});
            const float miny = std::min({y0, y1, y2}), maxy = std::max({y0, y1, y2});
            if (maxx < 0.f || maxy < 0.f || minx >= w_ || miny >= h_) continue;
            const int ix0 = std::max(0, int(std::floor(minx)));
            const int ix1 = std::min(w_ - 1, int(std::ceil(maxx)));
            const int iy0 = std::max(0, int(std::floor(miny)));
            const int iy1 = std::min(h_ - 1, int(std::ceil(maxy)));
            if (ix1 < ix0 || iy1 < iy0) continue;
            const float area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
            if (std::fabs(area) < 1e-9f) continue;
            const float inv = 1.f / area;
            const int oid = sv.tri_obj ? sv.tri_obj[i] : 0;
            for (int y = iy0; y <= iy1; ++y) {
                const float py = y + 0.5f;
                float* drow = depth_.data() + size_t(y) * w_;
                int32_t* frow = faceid_.data() + size_t(y) * w_;
                int32_t* orow = objid_.data() + size_t(y) * w_;
                for (int x = ix0; x <= ix1; ++x) {
                    const float px = x + 0.5f;
                    const float w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) * inv;
                    if (w0 < -1e-5f) continue;
                    const float w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) * inv;
                    if (w1 < -1e-5f) continue;
                    const float w2 = 1.f - w0 - w1;
                    if (w2 < -1e-5f) continue;
                    const float iw = w0 / std::max(1e-4f, A.d) + w1 / std::max(1e-4f, B.d) +
                                     w2 / std::max(1e-4f, C.d);
                    if (iw <= 1e-8f) continue;
                    const float d = 1.f / iw;
                    if (d < drow[x]) {
                        drow[x] = d;
                        frow[x] = i;
                        orow[x] = oid;
                    }
                }
            }
        }
    }

    void draw_capsule(Vec2 a, Vec2 b, float wa, float wb, float da, float db, uint16_t pal,
                      float bias, bool depth_test, uint16_t pal_hidden = 0,
                      bool hidden_pass = false) {
        const float wmax = std::max(wa, wb) * 0.5f + 1.5f;
        const int ix0 = std::max(0, int(std::floor(std::min(a.x, b.x) - wmax)));
        const int ix1 = std::min(w_ - 1, int(std::ceil(std::max(a.x, b.x) + wmax)));
        const int iy0 = std::max(0, int(std::floor(std::min(a.y, b.y) - wmax)));
        const int iy1 = std::min(h_ - 1, int(std::ceil(std::max(a.y, b.y) + wmax)));
        if (ix1 < ix0 || iy1 < iy0) return;
        const float vx = b.x - a.x, vy = b.y - a.y;
        const float L2 = vx * vx + vy * vy;
        const float invL2 = L2 > 1e-8f ? 1.f / L2 : 0.f;
        const float ida = 1.f / std::max(1e-4f, da);
        const float idb = 1.f / std::max(1e-4f, db);
        for (int y = iy0; y <= iy1; ++y) {
            const float py = y + 0.5f;
            for (int x = ix0; x <= ix1; ++x) {
                const float px = x + 0.5f;
                float t = ((px - a.x) * vx + (py - a.y) * vy) * invL2;
                t = clampf(t, 0.f, 1.f);
                const float cx = a.x + vx * t, cy = a.y + vy * t;
                const float ddx = px - cx, ddy = py - cy;
                const float dist = std::sqrt(ddx * ddx + ddy * ddy);
                const float half = (wa + (wb - wa) * t) * 0.5f;
                float cov = half + 0.5f - dist;
                if (cov <= 0.f) continue;
                if (cov > 1.f) cov = 1.f;
                const size_t idx = size_t(y) * w_ + x;
                bool occluded = false;
                if (depth_test) {
                    const float sd = depth_[idx];
                    if (std::isfinite(sd)) {
                        const float d = 1.f / ((1.f - t) * ida + t * idb);
                        if (d > sd * (1.f + bias) + 1e-4f) occluded = true;
                    }
                }
                if (hidden_pass) {
                    if (!occluded) continue;
                    if (cov > covh_[idx]) {
                        covh_[idx] = cov;
                        palh_[idx] = pal_hidden;
                    }
                    continue;
                }
                if (occluded) continue;
                if (cov > cov_[idx]) {
                    cov_[idx] = cov;
                    pal_[idx] = pal;
                }
            }
        }
    }

    void composite(std::vector<float>& image) const {
        image.assign(size_t(w_) * h_ * 4, 0.f);
        for (size_t i = 0; i < cov_.size(); ++i) {
            float hr = 0.f, hg = 0.f, hb = 0.f, ha = 0.f;
            const float ch = covh_[i];
            if (ch > 0.f) {
                const Rgba& hc = palette_[palh_[i]];
                ha = ch * hc.a;
                hr = hc.r * ha;
                hg = hc.g * ha;
                hb = hc.b * ha;
            }
            const float c = cov_[i];
            if (c <= 0.f) {
                if (ha > 0.f) {
                    image[i * 4 + 0] = hr;
                    image[i * 4 + 1] = hg;
                    image[i * 4 + 2] = hb;
                    image[i * 4 + 3] = ha;
                }
                continue;
            }
            const Rgba& col = palette_[pal_[i]];
            const float a = c * col.a;
            const float inv = 1.f - a;
            image[i * 4 + 0] = col.r * a + hr * inv;
            image[i * 4 + 1] = col.g * a + hg * inv;
            image[i * 4 + 2] = col.b * a + hb * inv;
            image[i * 4 + 3] = a + ha * inv;
        }
    }

    int width() const { return w_; }
    int height() const { return h_; }
    const std::vector<float>& depth() const { return depth_; }
    const std::vector<int32_t>& objid() const { return objid_; }

private:
    int w_, h_;
    std::vector<float> depth_;
    std::vector<int32_t> faceid_;
    std::vector<int32_t> objid_;
    std::vector<float> cov_;
    std::vector<uint16_t> pal_;
    std::vector<float> covh_;
    std::vector<uint16_t> palh_;
    std::vector<Rgba> palette_;
};

float brush_sample(const Brush& br, float phase) {
    if (br.profile.empty()) return 1.f;
    const int n = int(br.profile.size());
    if (n == 1) return br.profile[0];
    const float p = phase - std::floor(phase);
    const float f = p * n;
    const int i0 = int(f) % n;
    const int i1 = (i0 + 1) % n;
    const float t = f - std::floor(f);
    return br.profile[i0] * (1.f - t) + br.profile[i1] * t;
}

void rdp_simplify(const std::vector<Vec2>& pts, int i0, int i1, float eps, std::vector<int>& keep) {
    if (i1 <= i0 + 1) return;
    const Vec2& a = pts[i0];
    const Vec2& b = pts[i1];
    const float vx = b.x - a.x, vy = b.y - a.y;
    const float L = std::sqrt(vx * vx + vy * vy);
    float best = -1.f;
    int best_i = -1;
    for (int i = i0 + 1; i < i1; ++i) {
        const float px = pts[i].x - a.x, py = pts[i].y - a.y;
        float d;
        if (L < 1e-6f) d = std::sqrt(px * px + py * py);
        else d = std::fabs(px * vy - py * vx) / L;
        if (d > best) { best = d; best_i = i; }
    }
    if (best > eps && best_i > 0) {
        rdp_simplify(pts, i0, best_i, eps, keep);
        keep.push_back(best_i);
        rdp_simplify(pts, best_i, i1, eps, keep);
    }
}

std::vector<Vec2> chaikin(const std::vector<Vec2>& pts, int iters) {
    std::vector<Vec2> cur = pts;
    for (int it = 0; it < iters && cur.size() >= 2; ++it) {
        std::vector<Vec2> out;
        out.reserve(cur.size() * 2);
        out.push_back(cur.front());
        for (size_t i = 0; i + 1 < cur.size(); ++i) {
            const Vec2& p = cur[i];
            const Vec2& q = cur[i + 1];
            out.push_back({0.75f * p.x + 0.25f * q.x, 0.75f * p.y + 0.25f * q.y});
            out.push_back({0.25f * p.x + 0.75f * q.x, 0.25f * p.y + 0.75f * q.y});
        }
        out.push_back(cur.back());
        cur.swap(out);
    }
    return cur;
}

} // namespace

Result render(const SceneView& sv, const Settings& S) {
    const auto t_start = std::chrono::high_resolution_clock::now();
    Result out;
    out.width = S.width;
    out.height = S.height;
    out.tri_count = sv.ntris;
    out.edge_count = sv.nedges;

    Canvas canvas(S.width, S.height);

    std::vector<ProjVert> pv(size_t(sv.nverts));
    const Mat4& M = sv.mvp;
    for (int i = 0; i < sv.nverts; ++i) {
        const Vec3 v{sv.verts[3 * i], sv.verts[3 * i + 1], sv.verts[3 * i + 2]};
        // Full clip-space multiply: the perspective divide needs w (row 3), which is
        // 1 for orthographic projections and -z_view for perspective ones.
        const float cx = M.m[0] * v.x + M.m[1] * v.y + M.m[2] * v.z + M.m[3];
        const float cy = M.m[4] * v.x + M.m[5] * v.y + M.m[6] * v.z + M.m[7];
        const float cw = M.m[12] * v.x + M.m[13] * v.y + M.m[14] * v.z + M.m[15];
        ProjVert& p = pv[i];
        if (!(cw > 1e-6f)) continue;  // behind / on the camera plane
        const float iw = 1.f / cw;
        p.x = (cx * iw * 0.5f + 0.5f) * float(S.width);
        p.y = (0.5f - cy * iw * 0.5f) * float(S.height);
        if (sv.view) {
            const float* V = sv.view;
            p.d = -(V[8] * v.x + V[9] * v.y + V[10] * v.z + V[11]);  // positive view depth
        } else {
            p.d = cw;
        }
        // Vertices almost on the near plane project to astronomically large
        // screen coordinates; one such point turns a polyline into a streak
        // across the frame. Drop anything far outside the canvas.
        const float mx = float(S.width) * 8.f;
        const float my = float(S.height) * 8.f;
        if (p.x < -mx || p.x > float(S.width) + mx || p.y < -my || p.y > float(S.height) + my)
            continue;
        p.ok = true;
    }

    canvas.raster_tris(pv, sv);

    const float focal = 0.5f * float(S.height) * std::fabs(sv.proj.m[5] > 0.f ? sv.proj.m[5] : 1.f);
    const float bias = std::max(1e-5f, S.depth_bias);
    std::mt19937 rng(uint32_t(S.seed));
    std::uniform_real_distribution<float> uni(0.f, 1.f);

    std::vector<EdgePrim> prims;
    prims.reserve(size_t(sv.nedges));
    const float cos_crease = std::cos(S.crease_angle_deg * float(M_PI) / 180.f);

    for (int e = 0; e < sv.nedges; ++e) {
        if (sv.edge_sel && !sv.edge_sel[e]) continue;
        const int v0 = sv.edges[2 * e + 0];
        const int v1 = sv.edges[2 * e + 1];
        if (!pv[v0].ok || !pv[v1].ok) continue;
        int t0 = sv.edge_tris ? sv.edge_tris[2 * e + 0] : -1;
        int t1 = sv.edge_tris ? sv.edge_tris[2 * e + 1] : -1;
        if (sv.tri_skip) {
            if (t0 >= 0 && sv.tri_skip[t0]) t0 = -1;
            if (t1 >= 0 && sv.tri_skip[t1]) t1 = -1;
        }
        if (t0 < 0 && t1 < 0) continue;
        if (t1 < 0 || t0 < 0) {
            // Open rims: only draw the rim of the side that faces the camera.
            // The far side of a shell is either hidden by depth or belongs to
            // geometry the render does not actually show (inner shells, cards,
            // transparent garment layers), which produced ghost outlines.
            const int tf = (t0 >= 0) ? t0 : t1;
            const Vec3 nb{sv.tri_normals[3 * tf], sv.tri_normals[3 * tf + 1], sv.tri_normals[3 * tf + 2]};
            const Vec3 pb{sv.verts[3 * v0], sv.verts[3 * v0 + 1], sv.verts[3 * v0 + 2]};
            if (S.styles[LT_BOUNDARY].enabled && dot3(nb, sub3(sv.cam_pos, pb)) > 0.f)
                prims.push_back({v0, v1, LT_BOUNDARY, -1});
            continue;
        }
        const Vec3 n0{sv.tri_normals[3 * t0], sv.tri_normals[3 * t0 + 1], sv.tri_normals[3 * t0 + 2]};
        const Vec3 n1{sv.tri_normals[3 * t1], sv.tri_normals[3 * t1 + 1], sv.tri_normals[3 * t1 + 2]};
        const Vec3 p0{sv.verts[3 * v0], sv.verts[3 * v0 + 1], sv.verts[3 * v0 + 2]};
        const Vec3 dir = sub3(sv.cam_pos, p0);
        const bool front0 = dot3(n0, dir) > 0.f;
        const bool front1 = dot3(n1, dir) > 0.f;
        if (front0 != front1 && S.styles[LT_OBJECT].enabled)
            prims.push_back({v0, v1, LT_OBJECT, -1});
        if (dot3(n0, n1) < cos_crease && S.styles[LT_CREASE].enabled)
            prims.push_back({v0, v1, LT_CREASE, -1});
        if (sv.tri_mat && sv.tri_mat[t0] != sv.tri_mat[t1] && S.styles[LT_MATERIAL].enabled)
            prims.push_back({v0, v1, LT_MATERIAL, sv.tri_mat[t0]});
    }

    auto emit_chain = [&](const std::vector<int>& verts, int type, int mat) {
        if (verts.size() < 2) return;
        const Style& st = S.styles[type];
        std::vector<Vec2> pts;
        std::vector<float> depths, arcs;
        float s = 0.f;
        for (int vi : verts) {
            const ProjVert& p = pv[vi];
            Vec2 q{p.x, p.y};
            if (!pts.empty()) {
                const Vec2& pp = pts.back();
                s += std::hypot(q.x - pp.x, q.y - pp.y);
            }
            pts.push_back(q);
            depths.push_back(p.d);
            arcs.push_back(s);
        }
        const float total = s;
        if (total < 0.5f) return;

        Rgba col = st.color;
        if (S.use_material_color && type == LT_MATERIAL && mat >= 0 &&
            mat < int(S.material_colors.size())) {
            const Rgba& mc = S.material_colors[size_t(mat)];
            col.r = mc.r; col.g = mc.g; col.b = mc.b;
        }
        const float rnd = 1.f + st.random_width * 0.5f * (uni(rng) * 2.f - 1.f);
        const float hand_phase = uni(rng) * 6.2831853f;
        const float hand_freq = 0.015f + 0.06f * uni(rng);
        const float brush_off = S.brush.offset_random > 0.f ? uni(rng) : 0.f;
        float alpha = col.a;
        if (S.brush.alpha_amp > 0.f && !S.brush.profile.empty())
            alpha *= (1.f - S.brush.alpha_amp * 0.5f);

        Polyline pl;
        pl.type = type;
        pl.color = col;
        pl.color.a = alpha;
        pl.pts = pts;
        pl.widths.resize(pts.size());
        for (size_t i = 0; i < pts.size(); ++i) {
            float w = st.world_space ? st.width * focal / std::max(1e-4f, depths[i]) : st.width;
            w *= rnd;
            if (st.taper_in > 0.f) w *= smoothstepf(arcs[i] / st.taper_in);
            if (st.taper_out > 0.f) w *= smoothstepf((total - arcs[i]) / st.taper_out);
            if (!S.brush.profile.empty() && S.brush.width_amp > 0.f) {
                const float v = brush_sample(S.brush, arcs[i] * S.brush.repeat / 256.f + brush_off);
                w *= (1.f - S.brush.width_amp * (1.f - v));
            }
            if (st.random_width > 0.f)
                w *= std::max(0.05f, 1.f + st.random_width * 0.5f *
                                          std::sin(arcs[i] * hand_freq + hand_phase));
            pl.widths[i] = std::max(0.05f, w);
        }
        if (st.distance_fade > 0.f) {
            const float dmin = *std::min_element(depths.begin(), depths.end());
            const float f = clampf((dmin - st.fade_start) / st.distance_fade, 0.f, 1.f);
            pl.color.a = alpha * (1.f - smoothstepf(f));
        }

        const uint16_t pal = canvas.add_color(pl.color);
        const bool hidden = S.hidden_lines && S.hidden_alpha > 0.f && S.hidden_width > 0.f;
        uint16_t pal_hidden = 0;
        if (hidden) {
            Rgba hc = pl.color;
            hc.a = pl.color.a * S.hidden_alpha;
            pal_hidden = canvas.add_color(hc);
        }
        for (size_t i = 0; i + 1 < pts.size(); ++i) {
            canvas.draw_capsule(pts[i], pts[i + 1], pl.widths[i], pl.widths[i + 1], depths[i],
                                depths[i + 1], pal, bias, true);
            if (hidden)
                canvas.draw_capsule(pts[i], pts[i + 1], pl.widths[i] * S.hidden_width,
                                    pl.widths[i + 1] * S.hidden_width, depths[i], depths[i + 1],
                                    pal, bias + 0.02f, true, pal_hidden, true);
            ++out.stroke_count;
        }
        out.lines.push_back(std::move(pl));
    };

    for (int type = 0; type < LT_COUNT; ++type) {
        if (!S.styles[type].enabled || type == LT_INTERSECTION) continue;
        std::unordered_map<int, std::vector<int>> adj;
        std::vector<int> ids;
        for (int i = 0; i < int(prims.size()); ++i) {
            if (prims[i].type != type) continue;
            ids.push_back(i);
            adj[prims[i].v0].push_back(i);
            adj[prims[i].v1].push_back(i);
        }
        if (ids.empty()) continue;
        std::vector<char> used(prims.size(), 0);
        auto next_edge = [&](int v, int from) -> int {
            auto it = adj.find(v);
            if (it == adj.end()) return -1;
            int found = -1, count = 0;
            for (int pi : it->second) {
                if (used[pi] || pi == from) continue;
                ++count;
                found = pi;
            }
            return count == 1 ? found : -1;
        };
        for (int seed_i : ids) {
            if (used[seed_i]) continue;
            used[seed_i] = 1;
            const EdgePrim ep = prims[seed_i];
            std::vector<int> fwd, bwd;
            int cur_v = ep.v1, cur_p = seed_i;
            while (true) {
                int nxt = next_edge(cur_v, cur_p);
                if (nxt < 0) break;
                used[nxt] = 1;
                int other = (prims[nxt].v0 == cur_v) ? prims[nxt].v1 : prims[nxt].v0;
                fwd.push_back(other);
                cur_v = other;
                cur_p = nxt;
            }
            cur_v = ep.v0;
            cur_p = seed_i;
            while (true) {
                int nxt = next_edge(cur_v, cur_p);
                if (nxt < 0) break;
                used[nxt] = 1;
                int other = (prims[nxt].v0 == cur_v) ? prims[nxt].v1 : prims[nxt].v0;
                bwd.push_back(other);
                cur_v = other;
                cur_p = nxt;
            }
            std::vector<int> chain;
            chain.reserve(bwd.size() + 2 + fwd.size());
            for (auto it = bwd.rbegin(); it != bwd.rend(); ++it) chain.push_back(*it);
            chain.push_back(ep.v0);
            chain.push_back(ep.v1);
            for (int v : fwd) chain.push_back(v);
            emit_chain(chain, type, ep.mat);
        }
    }

    if (S.styles[LT_INTERSECTION].enabled) {
        const int W = S.width, H = S.height;
        std::vector<uint8_t> mask(size_t(W) * H, 0);
        const auto& oid = canvas.objid();
        const auto& dep = canvas.depth();
        for (int y = 0; y < H; ++y) {
            for (int x = 0; x < W; ++x) {
                const size_t i = size_t(y) * W + x;
                const int o = oid[i];
                if (o < 0) continue;
                if (sv.obj_sel && (o >= sv.nobj || !sv.obj_sel[o])) continue;
                for (int k = 0; k < 2; ++k) {
                    const int nx = x + (k == 0 ? 1 : 0), ny = y + (k == 1 ? 1 : 0);
                    if (nx >= W || ny >= H) continue;
                    const size_t j = size_t(ny) * W + nx;
                    if (oid[j] < 0 || oid[j] == o) continue;
                    if (sv.obj_sel && (oid[j] >= sv.nobj || !sv.obj_sel[oid[j]])) continue;
                    const float d0 = dep[i], d1 = dep[j];
                    if (std::fabs(d0 - d1) <= S.intersection_depth_tol * std::min(d0, d1)) {
                        mask[i] = 1;
                        mask[j] = 1;
                    }
                }
            }
        }
        const int dxs[8] = {1, 1, 0, -1, -1, -1, 0, 1};
        const int dys[8] = {0, 1, 1, 1, 0, -1, -1, -1};
        std::vector<uint8_t> visited(mask.size(), 0);
        const Style& ist = S.styles[LT_INTERSECTION];
        const uint16_t pal = canvas.add_color(ist.color);
        for (int y = 0; y < H; ++y) {
            for (int x = 0; x < W; ++x) {
                const size_t s0 = size_t(y) * W + x;
                if (!mask[s0] || visited[s0]) continue;
                // ordered walk from this pixel
                std::vector<Vec2> pts;
                int cx = x, cy = y, pdx = 0, pdy = 0;
                while (true) {
                    const size_t ci = size_t(cy) * W + cx;
                    visited[ci] = 1;
                    pts.push_back({float(cx) + 0.5f, float(cy) + 0.5f});
                    int best = -1;
                    float best_score = -2.f;
                    for (int k = 0; k < 8; ++k) {
                        const int nx = cx + dxs[k], ny = cy + dys[k];
                        if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
                        const size_t ni = size_t(ny) * W + nx;
                        if (!mask[ni] || visited[ni]) continue;
                        float score = 0.f;
                        if (pdx || pdy) {
                            const float len = std::sqrt(float(dxs[k] * dxs[k] + dys[k] * dys[k]));
                            score = (dxs[k] * pdx + dys[k] * pdy) / (len * std::sqrt(float(pdx * pdx + pdy * pdy)));
                        }
                        if (score > best_score) { best_score = score; best = k; }
                    }
                    if (best < 0) break;
                    pdx = dxs[best];
                    pdy = dys[best];
                    cx += pdx;
                    cy += pdy;
                }
                if (pts.size() < 3) continue;
                std::vector<int> keep{0};
                rdp_simplify(pts, 0, int(pts.size()) - 1, std::max(0.4f, S.simplify_px), keep);
                keep.push_back(int(pts.size()) - 1);
                std::sort(keep.begin(), keep.end());
                keep.erase(std::unique(keep.begin(), keep.end()), keep.end());
                std::vector<Vec2> spts;
                for (int k : keep) spts.push_back(pts[k]);
                if (spts.size() >= 3) spts = chaikin(spts, 1);
                Polyline pl;
                pl.type = LT_INTERSECTION;
                pl.color = ist.color;
                pl.pts = spts;
                pl.widths.assign(spts.size(), ist.width);
                for (size_t i = 0; i + 1 < spts.size(); ++i) {
                    canvas.draw_capsule(spts[i], spts[i + 1], ist.width, ist.width, 1.f, 1.f, pal,
                                        bias, false);
                    ++out.stroke_count;
                }
                out.lines.push_back(std::move(pl));
            }
        }
    }

    if (S.want_image) canvas.composite(out.image);
    const auto t_end = std::chrono::high_resolution_clock::now();
    out.time_ms = std::chrono::duration<double, std::milli>(t_end - t_start).count();
    return out;
}

} // namespace lf
