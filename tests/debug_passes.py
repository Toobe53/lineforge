# LineForge — per-line-type debug render of the smoke cube.
# GPL-2.0-or-later.
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "build"))

import lineforge_core as core  # noqa: E402

sys.path.insert(0, HERE)
from smoke_core import cube_scene  # noqa: E402


def render_one(scene, width, height, which):
    styles = [dict(enabled=False, width=2.0, color=(0, 0, 0, 1)) for _ in range(5)]
    styles[which] = dict(enabled=True, width=3.0, color=(0, 0, 0, 1))
    settings = dict(width=width, height=height, want_image=True, crease_angle_deg=30.0, styles=styles)
    return core.render_scene(scene, settings)


def main():
    w, h = 320, 240
    sc = cube_scene(w, h)
    names = {core.LT_OBJECT: "OBJECT", core.LT_CREASE: "CREASE", core.LT_BOUNDARY: "BOUNDARY",
             core.LT_MATERIAL: "MATERIAL", core.LT_INTERSECTION: "INTERSECTION"}
    for which, name in names.items():
        out = render_one(sc, w, h, which)
        lines = out["lines"]
        pts = [tuple(np.round(np.array(pl["points"]).mean(axis=0), 1)) for pl in lines]
        print(name, "strokes", out["stats"]["stroke_count"], "chains", len(lines))
        for pl, p in zip(lines, pts):
            print("   chain n=", len(pl["points"]), "centroid", p)
        cov = float((np.asarray(out["image"])[..., 3] > 0).mean())
        print("   coverage", round(cov, 5))


if __name__ == "__main__":
    main()
