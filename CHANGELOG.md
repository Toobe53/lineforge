# Changelog

## 0.2.1 — 2026-11-22

* **See-through faces are skipped.** For every material whose Principled *Alpha* is driven by an
  image texture, the alpha is sampled at each triangle's UV centroid; triangles under
  `Alpha Cutoff` (default 0.5) are dropped from the G-buffer *and* from the line pass. This removes
  the "ghost cone" around semi-transparent garment layers: the VRM demo used to draw a ring
  40–70 px outside the skirt silhouette because sheer cloth was rasterised as an opaque solid.
  New settings: `Skip See-through Faces` (default on) and `Alpha Cutoff` (0…1).
* **Outline shells are skipped.** Materials named like `outline` and `MToon Outline (...)` geometry
  node modifiers are excluded while the depsgraph mesh is evaluated (`Skip Outline Shells`,
  default on); modifiers are restored in a `finally:` block even when extraction raises.
* **Fixed**: skipping a triangle used to turn its border into a "boundary" edge, which drew a fake
  rim around every skipped face (zig-zag hem on the demo). Skipped neighbours no longer produce
  boundary or silhouette lines (`src/core.cpp`).
* Demo numbers at 1080p / 2× supersampling: 1516 polylines / 19,958 segments, core 0.50 s,
  extract 1.98 s, total 2.48 s (was 2200 / 24,400, 1.28 s / 3.8 s before the transparent geometry
  was filtered out). `docs/composite_1080p.png` regenerated.
* New `tests/blender_transparent_test.py`: a 0.05-alpha cube is dropped from the G-buffer and the
  line pass (1 line vs 2 with the toggle off), while a 0.7-alpha cube above the 0.5 cutoff stays
  in (`SKIPPED_TRIS 12 of 36`).

## 0.2.0 — 2026-11-22

* **Orthographic cameras now work.** The core used to treat clip-space `z` as the perspective
  divisor, which is only approximately true for perspective projections and collapses completely
  for ortho (`w == 1`, `z < 0`). Projection now uses the real clip-space `w` and occlusion uses
  view-space depth (optional `view` matrix in the scene dict; the old behaviour is kept when it is
  absent). Verified against `world_to_camera_view` (identical pixel coordinates) and by
  `tests/blender_robustness.py` (ortho cube yields its 6 silhouette strokes).
* New scene setting **Ortho Width Falloff** (shown while the scene camera is orthographic):
  off = world-space widths become one constant screen width (parallel projection semantics);
  on = widths keep the `focal / depth` scaling, so nearer geometry draws thicker lines.
  Covered by `tests/blender_ortho_test.py` (constant spread 1.00 vs. falloff spread 2.14 on a
  near/far cube pair).
* **CI**: `.github/workflows/build.yml` builds the core on Ubuntu, Windows (MSVC via vswhere) and
  macOS, merges the three platform binaries into one add-on zip, and attaches it to a GitHub
  release when a `v*` tag is pushed. `tools/package.py` is the single cross-platform packager
  (`package.ps1` now calls it), and `tools/build.py` gained MSVC support.
* **Errors are UI messages, not tracebacks.** New `lineforge.errors.LineForgeError`; every operator
  reports it in the status bar and in the *Last Error* panel box, and returns `CANCELLED`.
* **Core status + Check Native Core.** The sidebar shows whether the native module is loaded, from
  which path and with which version; `lf.check_core` lists the platform tag and the exact load error.
* **Portable packaging.** One zip, native binary under `bin/<platform_tag>/`; the loader probes
  `bin/<tag>` then `bin`, tries every plausible extension and explains the platform mismatch.
  Version reported as `ADDON_VERSION`.
* **Cross-platform build**: `tools/build.py` (stdlib only: finds python3 headers, pybind11, any C++17
  compiler; `--cxx/--python-home/--pybind11/--clean/--no-copy/--debug`) and `CMakeLists.txt` with
  `pybind11_add_module`; both copy into `addon/lineforge/bin/<tag>/`.
* **Hardening**: re-entrancy guard in `render()`, resolution guard (1…16384), `MemoryError` →
  `LineForgeError`, degenerate/NaN triangles dropped during extraction, mirrored objects flip their
  normals, `to_mesh()` failures and scenes without a camera or renderable meshes produce readable
  messages instead of exceptions.

## 0.1.3 — 2026-11-22

* New scene setting **Supersampling** (1–4, default 2): the line pass is rasterised at N× the
  output resolution and box-filtered down. Removes staircase artefacts on thin and steep lines;
  widths are scaled along with the resolution so the look is resolution independent.
  Measured on the VRM demo (1920×1080): RMSE against a 4× reference drops from 0.0132 (SSAA 1)
  to 0.0044 (SSAA 2). Cost: core 1.28 s / total 3.8 s at SSAA 2 versus 0.28 s / 0.83 s at SSAA 1.
* `render()` reports the chosen factor in `stats["supersample"]` and converts every polyline back
  to output pixels, so the viewport overlay stays aligned.
* Tests: `tests/blender_aa_test.py` compares SSAA 1/2/4 output against the 4× reference and checks
  timing, image size and polyline coordinates.

## 0.1.2 — 2026-11-22

* New scene setting **Exclude Objects** (comma separated name substrings) — drops helper shells,
  proxies and inverted-hull outline objects from the line pass.
* Inverted-hull outline materials (names containing `outline`) are skipped in the G-buffer and in
  edge classification, so they can no longer occlude the real surface or add fake silhouettes.
* Core ABI addition: optional per-triangle `tri_skip` mask in the scene dict (backwards compatible).
* Docs: English and Chinese READMEs document both mechanisms.

## 0.1.1 — 2026-11-22

* New operator **Render Line Art PNG** (`lf.render_composite`): renders the beauty with the Standard
  view transform, renders the line pass, and merges them in display space (straight-alpha over).
  Works in background mode and needs no compositor node group.
* `lineforge_core.__version__` now tracks the add-on version.
* Demo numbers refreshed (1779 polylines / 19,817 segments, 0.28 s core on the VRM scene).

## 0.1.0 — 2026-11-22

* First release: C++17 / pybind11 CPU line renderer (`lineforge_core.pyd`), Blender 5.2 add-on.
* Five line types (object silhouette, crease, border, material boundary, object intersection),
  per-line-set style (width, world space, colour, taper, random width, distance fade, brush),
  hidden lines, node tree UI, viewport overlay, F12 auto render, compositor path.
* Tools: `build.ps1` (MinGW w64devkit), `tools/get-toolchain.ps1`, `package.ps1`, test suite
  (`smoke_core`, `test_style`, `test_overlay`, `blender_addon_test`, `blender_scene_pass`,
  `blender_install_keep`, `blender_composite_op`).
