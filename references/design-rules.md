# FDM design rules

Starting values for a typical 0.4 mm nozzle and 0.2 mm layers. Every printer,
material and slicer profile differs: treat the numbers as a first guess and
replace them with your own measurements (calibration coupon, see
[calibration.md](calibration.md)). Units are millimetres.

## 1. Tolerances (clearance PER SIDE)

"Per side" means the gap between one wall and its mate. A 6.00 mm peg in a
hole with 0.15 mm per side needs a 6.30 mm hole.

| Fit | Behaviour | Starting range per side |
|---|---|---|
| Press | pushed in with force, stays put | 0.00 to 0.10 |
| Snug | by hand, no visible play | 0.10 to 0.15 |
| Sliding | moves with a light push, little play | 0.15 to 0.25 |
| Free | drops in, rattles, rotates freely | 0.25 to 0.40 |

- Measure your own printer with the coupon and record the result in
  `fits.json`; the template then uses `FITS["press"|"snug"|"sliding"|"free"]`.
- Fits printed in the XY plane (a vertical peg in a vertical hole) are the
  most repeatable. Gaps stacked in Z (print-in-place, a lid resting on a
  ledge) need at least one full layer, usually 0.2 to 0.3 mm.
- TPU stretches: press fits can use 0 or slightly negative clearance.
- Large parts shrink as they cool (PLA about 0.2 to 0.5 %, ABS and ASA about
  0.5 to 0.8 %): on long mating features add that to the clearance.

## 2. Holes print undersize

Three effects stack: the CAD circle is a polygon whose flats sit inside the
nominal circle, the slicer's perimeter path rounds corners inward, and the
plastic shrinks. Small holes suffer most.

- `cad.hole()` and the other cutters size the polygon by its circumradius so
  the flats sit on the nominal diameter (`cad.poly_radius`).
- Segment count: about one chord per nozzle width (`cad.segments_for`). Very
  small holes (under 3 mm) behave better with fewer, larger flats.
- Compensation: if you have no coupon data, add 0.1 to 0.2 mm to small hole
  diameters. Clearances from your own coupon already include the shrink: do
  not add both.
- Precise holes (bearings, shafts): print 0.2 to 0.3 mm undersize and drill or
  ream to size.
- printcheck warns for holes narrower than 3 mm (`--min-hole`).

## 3. Elephant foot

The first layer is squashed onto the bed and spreads by 0.1 to 0.4 mm.
- Chamfer the bottom outside edge 0.3 to 0.5 mm at 45 degrees
  (`cad.chamfered_extrude(..., bottom=0.4)`).
- Holes that start on the bed get a matching flare (`cad.hole(..., foot=0.4)`),
  and pegs that mate with something get the same bottom chamfer, otherwise the
  first layer alone makes the fit tight.

## 4. Overhangs (about 45 degrees from vertical)

A downward-facing surface prints without support up to roughly 45 degrees
from vertical; good cooling and PLA can reach 50 to 60. The coupon's fins
(30, 40, 45, 50, 60) show your limit. Designing around it:
- **Chamfers, not fillets, on the underside.** A fillet starts horizontal at
  its tangent point; a 45 degree chamfer prints clean. Fillets are fine on
  top edges and on vertical edges.
- **Teardrop holes** for horizontal holes: a circle with a 45 degree roof
  (`cad.teardrop_hole`, optionally flat-topped so the bridge is only a few mm).
- **Rotate or split** the part so the big flat face is on the bed; join halves
  with pins, screws or glue.
- **45 degree gussets** under ledges and shelves.
- printcheck reports the area of downward faces steeper than the limit
  (excluding faces on the bed), where they are, and how much is flat.

## 5. Bridging

A flat span held at both ends prints in the air if it is short: up to about
10 mm is reliable on most printers, 20 mm or more with tuning; expect 0.2 to
0.5 mm of sag. printcheck counts flat ceilings that are held on most of their
outline and no wider than `--max-bridge` (default 10 mm) as bridges, not
overhangs. A cantilever (held on one side, like the arm of a T) is not a bridge.

## 6. Walls and small features

- Minimum wall: 2 extrusion widths, about 2 x nozzle (0.8 mm for 0.4).
  Functional walls: 3 to 4 perimeters (1.2 to 1.6 mm) or more.
- Features narrower than the nozzle disappear in the slicer.
- printcheck's optional ray-cast sampling (`--thin-walls N`) warns below 2 x
  nozzle. Knife edges (acute corners) show up there too.
- Strength comes mostly from perimeters, not infill: 3 to 4 walls with 20 to
  40 % infill suits most functional parts.

## 7. Heights are multiples of the layer height

The slicer can only stop on a layer boundary. Put flat steps, ledges, text
depths and plate thicknesses on multiples of the layer height (4.0 not 4.1 at
0.2 mm). printcheck reports flat faces off the grid.

## 8. Orientation and layer adhesion

Parts are weakest across layers (often 30 to 70 % of the in-plane strength).
- Orient so the main load runs along the layers. A hook printed lying on its
  side is strong; standing up it snaps at a layer line.
- Snap arms and clips flex in the XY plane, never across layers.
- Screw bosses that take axial pull-out load are best vertical.
- The face that must be flat and accurate goes on the bed.

## 9. Snap-fits

- Cantilever arm, printed in the XY plane. Maximum deflection for a constant
  section: `y = strain x L^2 / (1.5 x t)` (L arm length, t thickness).
- Allowed strain (short-term, a few uses): PLA about 1 to 2 %, PETG about 2 to
  4 %, ABS/ASA about 2 to 3 %, TPU very high. Make arms 5 to 10 times longer
  than thick.
- Lead-in ramp 30 to 45 degrees; retention face 60 to 90 degrees (90 = does
  not come apart).
- Round or chamfer the arm root (radius at least half the thickness) to avoid
  a stress crack.
- The example cable clip uses a flexing lip: the opening is about 70 % of the
  bundle diameter and the lip is 10 layers thick in PETG.

## 10. Screws, countersinks, nuts and heat-set inserts

| Feature | Typical starting value | Note |
|---|---|---|
| Clearance hole | nominal + 0.2 to 0.5 (M3: 3.2 to 3.5) | or nominal + 2 x `FITS["free"]` |
| Self-tapping pilot into plastic | 0.8 to 0.9 x nominal (M3: 2.5 to 2.7) | 3+ perimeters around it |
| Countersink | 90 degree included angle for ISO metric flat heads, 82 for many imperial | sink the head 0.1 to 0.2 below the surface (`cad.countersunk_cutter`) |
| Counterbore | head diameter + 0.4 to 0.6, depth head height + 0.2 to 0.5 | `cad.counterbore_cutter` |
| Hex nut trap | across flats + 0.2 to 0.3 | print the flats parallel to the bed edge |
| Heat-set insert hole | usually a little under the insert's knurl diameter (common short M3 inserts: about 4.0 to 4.2), depth insert length + 0.5 to 1 | **check the insert maker's table**; walls at least 1.5 to 2 around; `cad.insert_hole` adds a lead-in |

Install inserts vertically with a soldering iron fitted with an insert tip, at
roughly the material's printing temperature or a bit below, pressing gently.

## 11. Embossed and debossed text or marks

- Raised (embossed): stroke at least 2 x nozzle (0.8 mm), height 0.4 to 0.6
  mm (2 to 3 layers).
- Engraved (debossed): stroke at least 0.5 to 0.6 mm, depth 0.4 to 0.6 mm.
- Legible size: about 5 to 6 mm cap height on vertical faces, 8 mm or more on
  top faces; bold sans-serif fonts.
- These helpers do not render fonts (no font dependency). Use notches, dots
  or symbols as the calibration coupon does, or add text in the slicer.

## 12. TPU and other flexible filaments

- Thicker walls (at least 1.2 mm), simple shapes, no long bridges, no tiny
  retraction-heavy features; slow printing, direct-drive extruders work best.
- Holes shrink more and parts stretch: test fits with the coupon in TPU.
- Hardness (Shore 95A is common) changes how much a press fit grips.

## 13. Chirality: left and right parts, mirrored assemblies

A mirrored part is a different part. A rotated view of a mirror image can look
exactly like the original, so a glance at the viewer is not a check.
- Build the other hand with `cad.mirror(solid, "x")` and give it its own name
  (`bracket-left`, `bracket-right`).
- Lock each hand with probe points in the parameter block: `PROBES_INSIDE`
  (points that must be solid) and `PROBES_OUTSIDE` (points that must be
  empty), chosen on an asymmetric feature, for example "the screw boss is at
  +X when the hook points +Y". printcheck fails the build if the part is the
  wrong hand or a feature moved.
- In the print sheet, state handedness in words tied to the real world ("with
  the flat face on the desk and the cable coming from the front, the boss is on
  the right"), and ask the user to confirm against the real object.
