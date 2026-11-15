# Print sheet: <part name>

| Item | Value |
|---|---|
| File(s) | `out/<name>.stl` (one per part or colour) |
| Size | X x Y x Z mm (from `out/<name>.json`) |
| Orientation | as modelled: <which face> on the bed; do not rotate it in the slicer unless noted |
| Handedness | <left / right / symmetric>, stated in real-world terms |
| Material | <PLA / PETG / TPU / ABS / ASA>, nozzle <range> C, bed <range> C |
| Nozzle / layer height | <0.4> mm / <0.2> mm |
| Version | <standard / light / strong>: <walls> walls, <infill> % infill (from `build.py --variants`) |
| Supports | <none> (or: where and why) |
| Brim | <none> (add one if the part is tall and narrow) |
| Printer | <generic / Bambu Lab X2D> (profile `PRINTER`) |
| Colour change | <none> (or: at Z = <h> mm, layer <h / layer height>; confirm in the slicer preview) |
| Colours | <single> (or: one STL per colour: <suffix = colour>; on the X2D the nozzle plan chosen and the other one: "other nozzle: ~X min, Y g") |
| Quantity | <n> |
| Estimate | about <g> g of filament (<m> m), about <min> min (<lo> to <hi> min) including about 6 min of printer preparation; the slicer gives a closer figure. Outside the measured range (not X2D + PLA + 0.4 nozzle + 0.2 layers, supports, or infill above 40 %) add: **rough: outside the measured range, trust the slicer** |
| Other versions | <light: g, min / strong: g, min, and the difference vs standard> (out/variants.md) |
| Fits used | <fits.json from the coupon / default clearances> |
| Accepted printcheck warnings | <list, or "none"> |
| After printing | <clean holes, install inserts, test fit before load> |
| Next step | <your slicer> (or, on the X2D: x2d-print skill with `out/x2d-job.json`) |

Words: **walls** = the outer shell lines, most of the strength; **infill** = the
pattern inside (a percentage); **supports** = throw-away scaffolding under
overhangs; **brim** = a thin ring around the first layer that helps tall narrow
parts stay stuck; **purge** = filament thrown away at each colour change.

Slicing and printing are your steps. Do not leave the printer unattended;
ventilate for ABS/ASA; let parts cool before handling.
