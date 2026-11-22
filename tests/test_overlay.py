# LineForge — viewport overlay helpers (headless-safe parts).
# GPL-2.0-or-later.
import os
import sys

import numpy as np

sys.path.insert(0, r"C:\LineForge\addon")

from lineforge import overlay, renderer  # noqa: E402


def main():
    pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]], np.float32)
    widths = np.array([2.0, 6.0, 2.0], np.float32)
    tris = overlay._triangle_strip(pts, widths)
    print("STRIP", None if tris is None else tris.shape)
    assert tris is not None and tris.shape == (12, 2), tris
    assert np.isfinite(tris).all()

    # Degenerate input must not crash.
    assert overlay._triangle_strip(np.array([[0.0, 0.0]], np.float32), None) is None
    assert overlay._triangle_strip(pts[:2], np.array([4.0, 4.0], np.float32)).shape == (6, 2)

    # No cached lines -> no groups.
    print("GROUPS", overlay._build(800, 600, 640, 480))
    assert overlay._build(800, 600, 640, 480) == []

    # Off-screen / no GPU context: draw() must return quietly.
    overlay.draw()
    print("DRAW SAFE")

    # Cached lines must be scaled into the region.
    renderer._LAST["lines"] = [{
        "points": np.array([[0.0, 0.0], [320.0, 240.0]], np.float32),
        "widths": np.array([8.0, 8.0], np.float32),
        "color": (0.0, 0.0, 0.0, 1.0),
        "type": 0,
    }]
    groups = overlay._build(640, 480, 320, 240)
    print("GROUP COUNT", len(groups), groups[0][2].shape if groups else None)
    assert len(groups) == 1
    assert groups[0][2].shape == (6, 2)
    arr = groups[0][2]
    assert arr[:, 0].max() <= 660.0 and arr[:, 1].max() <= 500.0, arr
    renderer._LAST["lines"] = []
    print("OVERLAY OK")


if __name__ == "__main__":
    main()
