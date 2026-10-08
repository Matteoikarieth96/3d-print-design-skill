# Print sheet: <part name>

| Item | Value |
|---|---|
| File(s) | `out/<name>.stl` (one per part or colour) |
| Size | X x Y x Z mm (from `out/<name>.json`) |
| Orientation | as modelled: <which face> on the bed; do not rotate it in the slicer unless noted |
| Handedness | <left / right / symmetric>, stated in real-world terms |
| Material | <PLA / PETG / TPU / ABS / ASA>, nozzle <range> C, bed <range> C |
| Nozzle / layer height | <0.4> mm / <0.2> mm |
| Walls / infill | <3 walls, 20 to 40 % infill> |
| Supports | <none> (or: where and why) |
| Brim | <none> (add one if the part is tall and narrow) |
| Colour change | <none> (or: at Z = <h> mm, layer <h / layer height>; confirm in the slicer preview) |
| Quantity | <n> |
| Mass estimate | up to <g> g at 100 % infill; the slicer gives the real value |
| Fits used | <fits.json from the coupon / default clearances> |
| Accepted printcheck warnings | <list, or "none"> |
| After printing | <clean holes, install inserts, test fit before load> |

Slicing and printing are your steps. Do not leave the printer unattended;
ventilate for ABS/ASA; let parts cool before handling.
