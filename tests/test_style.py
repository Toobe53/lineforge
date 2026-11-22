# LineForge — style features (taper, brush, random width, world space) checks.
# GPL-2.0-or-later.
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "build"))
sys.path.insert(0, HERE)

import lineforge_core as core  # noqa: E402
from smoke_core import base_styles, cube_scene, two_cube_scene  # noqa: E402


def render(scene, styles, **over):
    w, h = 320, 240
    settings = dict(width=w, height=h, want_image=True, crease_angle_deg=30.0,
                    styles=styles, hidden_lines=False)
    settings.update(over)
    return core.render_scene(scene, settings)



def check_taper(scene):
    out = render(scene, base_styles(width=4.0, taper_in=40.0, taper_out=40.0))
    widths = np.concatenate([np.asarray(pl["widths"]) for pl in out["lines"]])
    print("TAPER min/max/mean", round(float(widths.min()), 3), round(float(widths.max()), 3),
          round(float(widths.mean()), 3))
    assert widths.min() < 0.35 * widths.max(), "taper does not reach thin ends"


def check_brush(scene):
    out = render(scene, base_styles(width=8.0), brush=dict(
        profile=[1.0, 1.0, 0.05, 0.05], repeat=2.0, width_amp=0.9, alpha_amp=0.0, offset_random=0.0))
    widths = np.concatenate([np.asarray(pl["widths"]) for pl in out["lines"]])
    print("ZIPPER min/max", round(float(widths.min()), 3), round(float(widths.max()), 3))
    assert widths.max() > 2.0 * max(widths.min(), 0.05), "brush amplitude has no effect"


def check_random(scene):
    a = render(scene, base_styles(width=4.0, random_width=1.0), seed=1)
    b = render(scene, base_styles(width=4.0, random_width=1.0), seed=1)
    c = render(scene, base_styles(width=4.0, random_width=1.0), seed=7)
    wa = np.concatenate([np.asarray(pl["widths"]) for pl in a["lines"]])
    wb = np.concatenate([np.asarray(pl["widths"]) for pl in b["lines"]])
    wc = np.concatenate([np.asarray(pl["widths"]) for pl in c["lines"]])
    print("RANDOM std", round(float(wa.std()), 4), "seed-stable", bool(np.allclose(wa, wb)),
          "seed-diff", not bool(np.allclose(wa, wc)))
    assert wa.std() > 0.1, "random width is static"
    assert np.allclose(wa, wb), "random width is not seed-stable"


def check_world_space(scene):
    thin = render(scene, base_styles(width=0.05, world_space=True))
    thick = render(scene, base_styles(width=0.05, world_space=False))
    wt = np.concatenate([np.asarray(pl["widths"]) for pl in thin["lines"]])
    wf = np.concatenate([np.asarray(pl["widths"]) for pl in thick["lines"]])
    print("WORLD min/max", round(float(wt.min()), 2), round(float(wt.max()), 2),
          "| SCREEN min/max", round(float(wf.min()), 2), round(float(wf.max()), 2))
    # world-space widths must vary with depth across a cube seen in perspective
    assert wt.max() - wt.min() > 0.5, "world-space width does not scale with depth"


def check_fade(scene):
    near = render(scene, base_styles(width=3.0, distance_fade=0.0))
    faded = render(scene, base_styles(width=3.0, distance_fade=1.0, fade_start=0.0))
    cov_n = float((np.asarray(near["image"])[..., 3] > 0.2).mean())
    cov_f = float((np.asarray(faded["image"])[..., 3] > 0.2).mean())
    print("FADE coverage", round(cov_n, 5), "->", round(cov_f, 5))
    assert cov_f < cov_n, "distance fade has no effect"


def check_hidden():
    # Two cubes: the rear cube is partly hidden behind the front one.
    scene = two_cube_scene(320, 240)
    off = render(scene, base_styles(width=3.0), hidden_lines=False)
    on = render(scene, base_styles(width=3.0), hidden_lines=True, hidden_alpha=0.5,
                hidden_width=0.7)
    a_off = np.asarray(off["image"])[..., 3]
    a_on = np.asarray(on["image"])[..., 3]
    cov_off = float((a_off > 0.01).mean())
    cov_on = float((a_on > 0.01).mean())
    new_px = (a_on > 0.01) & (a_off <= 0.01)
    print("HIDDEN coverage", round(cov_off, 5), "->", round(cov_on, 5),
          "new", int(new_px.sum()), "new alpha max", round(float(a_on[new_px].max()) if new_px.any() else 0.0, 3))
    assert cov_on > cov_off * 1.2, "hidden lines add no geometry"
    assert new_px.any(), "hidden lines drew nothing new"
    assert float(a_on[new_px].max()) < 0.9, "hidden lines are not translucent"


def main():
    scene = cube_scene(320, 240)
    check_taper(scene)
    check_brush(scene)
    check_random(scene)
    check_world_space(scene)
    check_fade(scene)
    check_hidden()
    print("STYLE OK")


if __name__ == "__main__":
    main()
