# How the time and filament estimate was measured

`scripts/estimate.py` guesses grams and minutes before slicing. On the Bambu Lab X2D its
numbers come from real slices; every slice is in
[estimate-calibration.csv](estimate-calibration.csv), one row each, so anyone can check
them. `tests/test_estimate_calibration.py` rebuilds every box-like calibration row from its
parameters (no slicer) and fails if the code no longer gives the CSV's model columns, and
fails if any row falls outside the range the current spreads show.

## How the slices were made

- **Slicer:** Bambu Studio 02.09.01.70 on macOS, its command line, run by x2d-print's
  `bambu_project.py build --check` (it builds a .3mf from the STLs and slices it in a
  temporary folder; nothing is sent to a printer). One slice at a time.
- **Profile:** a template saved from Bambu Studio: printer "Bambu Lab X2D 0.4 nozzle",
  process "0.20mm Standard @BBL X2D" (5 top and 3 bottom layers, sparse infill pattern of
  the preset), filament "Generic PLA @BBL X2D 0.4 nozzle" in five colours, Textured PEI
  Plate. Only `wall_loops`, `sparse_infill_density` and, for one row, `enable_support` were
  changed per slice.
- **Real figures** are the slicer's own: total print time, total grams and the purge part
  of it (prime tower and flushes). "Total (of which purge)": `slicer_g` is the total,
  `slicer_purge_g` the purge inside it.
- **Model figures** are `estimate.estimate()` on the same geometry and settings.
  `err_*_pct` = (model - slicer) / slicer: negative means the slicer took longer or used
  more than the model said.

## Two sets

**Calibration (43 rows, `set = calibration`):** 34 rows from the first run and 9 from the
2026-11 run (below). The speed and volume coefficients were fitted on 32 of the first 34;
the coaster's light and strong versions were sliced together with its standard version
and are listed here rather than as holdout. The second-nozzle numbers were refitted on
the 9 rows of the 2026-11 run.
Seven shapes (plate 60 x 24 x 4, cubes 20 and 40, cylinder 50 x 30, tube 40 mm with a 3 mm
wall and 60 mm high, slab 100 x 80 x 10, disc 90 x 4) at 2/10 %, 2/15 %, 3/15 % and 4/40 %
walls/infill; a 40 x 40 x 10 mm block in one colour, with a second-colour stripe on the
same nozzle (49 swaps, 2 h 04 min, 43.5 g of which 36.1 g purge) and on the other nozzle
(42 min, 12.6 g of which 5.2 g purge); the two-colour coaster example in its three versions
(black on the right nozzle); and, from the 2026-11 run, the block, the coaster and a
hollow 60 mm ball with a logo inlay, each with the accent on the right nozzle, with the
body on the right nozzle and in one colour on the right nozzle. Model against slicer:
**time within 13 % (mean 3 %), grams within 10 % (mean 4 %).**

**Holdout (24 rows, `set = holdout`):** parts never used for fitting, made with this skill
(design build) and sliced through x2d-print exactly as a person would: the cable clip
(3 versions), the calibration coupon, a 15 x 15 x 80 mm post, pins 12 x 70 and 8 x 50, a
10 x 10 x 40 post, a 180 x 120 x 3 plate, three separate pucks on one plate, an open box,
a knob at 40 % infill, an L bracket with holes, an 80 x 80 x 3 plate with 25 holes, a
tapered tower, two separate discs in two colours (both nozzle plans), the coaster with
both colours on the left nozzle, a T shelf with supports, and the left-nozzle slices of
the 2026-11 run (block, coaster and ball in one colour; coaster and ball with both
colours on the left nozzle). Model against slicer on the 23 rows inside the measured
field: **time within 32 % (mean 7 %), grams within 16 % (mean 7 %).** All 24 rows are
inside the range shown.

Two holdout rows changed the model, and say so in their `note`: the 15 x 15 x 80 post
took 61 min against 39 estimated, which added Bambu Studio's minimum layer time (8 s,
"slow down for better layer cooling" in Generic PLA); the 12 x 70 pin then came out too
slow, which capped that by the 20 mm/s minimum speed. The coefficients were refitted on
the calibration rows only; the post and the pin are no longer out of sample, so the other
21 rows are the strict holdout (same maximum errors: 32 % time, 16 % grams).

## The second nozzle (2026-11 run)

The first model charged the second nozzle about 10 minutes once and nothing for its
speed, and it suggested the main colour on the right nozzle. A hollow ball planned that
way sliced at 2 h 13 min against 1 h 32 min estimated. The cause is in the process preset
itself ("0.20mm Standard @BBL X2D", as Bambu Studio 02.09.01.70 saves it in a project):
the right nozzle is a Bowden one and is limited to 50 mm/s on outer walls against
200 mm/s on the left nozzle, 200 against 300 on inner walls, 200 against 270 on sparse
infill, and 1,000 mm/s2 of acceleration against 10,000.

Three objects were sliced in five plans each, with a later template (same Bambu Studio,
process and Generic PLA; 2 walls for the block and the ball, 3 for the coaster, 15 %
infill). Time, total grams:

| Object (layers with both colours) | One colour, left | One colour, right | Accent right | Body right | Both left |
|---|---|---|---|---|---|
| Block 40 x 40 x 10, 10 mm stripe (50 of 50) | 17.1 min, 6.9 g | 22.1 min | 43.2 min, 12.6 g | 43.8 min, 12.6 g | 112.2 min, 35.0 g (not in the CSV) |
| Coaster example (3 of 20) | 29.1 min, 16.6 g | 34.7 min | 34.4 min, 17.6 g | 40.7 min, 17.6 g | 37.2 min, 18.9 g |
| Hollow ball 60 mm, logo inlay (111 of 357) | 58.5 min, 14.4 g | 70.5 min | 107.2 min, 28.5 g | 132.8 min, 28.5 g | 287.9 min, 87.8 g |

What was fitted, by least squares on the nine right-nozzle slices (what each adds over
the same object in one colour on the left nozzle):

- using both nozzles: 275 s once (`second_nozzle_s`, was 621 s) and 0.16 g;
- each switch to the other nozzle: 23.9 s and 0.103 g (`switch_s`, `switch_g`; were
  16.7 s and 0.09 g);
- parts on the right nozzle: walls take 1.54 times as long, the rest 1.08 times
  (`right_wall_x`, `right_other_x`);
- the prime tower is printed from the first layer up to the last colour change: each of
  its layers with no change costs 0.0315 g (`tower_layer_g`), and 12 s more when the
  right nozzle prints it (`right_tower_layer_s`);
- a print on the right nozzle alone: 182 s more preparation (`right_only_s`).

The fit gives the nine extras within 44 s each. Against the whole model the nine rows
are within 12 % in time (the largest is the ball, whose one-colour time is itself 14 %
low) and 7 % in grams. The older two-nozzle rows moved by less than 3 minutes and stay
in range. The five left-nozzle slices of this run fitted no coefficient (the one-colour
ones are the baseline the extras were measured from) and are listed as holdout.

What follows for the design: with two colours, the accent on the right nozzle was the
fastest plan for all three objects; the main colour on the right nozzle costs the same
purge and 0.6 to 26 minutes more. `printers.nozzle_options` now estimates the three
plans and `suggest_nozzles` picks the fastest.

One slice of this run is **not in the CSV**: the block with both colours on the left
nozzle, in white and light blue, took 112.2 min and 35.0 g (27.6 g of purge in 50 swaps,
0.55 g each). The same block in the first run's colour pair took 124 min and 43.5 g
(36.1 g in 49 swaps, 0.74 g each), and the model, fitted on that pair, says 44 g. The
ball in red and white purged 0.66 g per swap. Purge on one nozzle depends on the colour
pair, which the model does not know (see below).

## The range shown, and why it is asymmetric

Inside the measured field the build shows the estimate and a range of **15 % below to
50 % above** for time and **15 % below to 10 % above** for grams (`TIME_SPREAD`,
`GRAMS_SPREAD`), rounded outwards to 5 minutes. The time range was widened upwards after
the holdout: parts with many small features print slower than the model says (the
calibration coupon took 41 min against 28 estimated, the plate with 25 holes 35 against
28). So "every row inside the range" says how wide the range had to be, not that an
independent test confirmed it. Grams lean the other way: the model is usually a little high (more so on small
parts, by up to 15 %).

## Layer height (0.28 mm) check

Two extra real slices (Bambu Studio 02.09.01.70, X2D, PLA, 3 walls, 15 % infill, same
process with only `layer_height` changed), not in the CSV because they are outside the
measured field:

| Part | 0.20 mm | 0.28 mm | Model at 0.28 |
|---|---|---|---|
| coaster base, 100 mm across, 4 mm tall | 30.9 min, 16.9 g | 34.1 min, 20.0 g | 32.9 min (-3.5 %) |
| cylinder 40 x 80 mm | 66.5 min, 34.2 g | 50.7 min, 33.5 g | 48.4 min (-4.5 %) |

Thicker layers print walls and sparse infill at about the same mm/s, so faster per mm3,
while top and bottom solid layers do not speed up and get thicker (5 x 0.28 mm instead
of 5 x 0.20 mm). The model scales the walls' and the infill's time by 0.20 / layer and
leaves the solid layers as they are: at 0.20 mm nothing changes. Two slices are not a
calibration: outside 0.20 mm the estimate stays "rough".

## What is NOT covered

The estimate is measured only for: **Bambu Lab X2D, PLA, 0.4 mm nozzle, 0.2 mm layers, no
supports, infill up to 40 %, 2 to 4 walls, 5 top and 3 bottom layers, one or two colours**.
Outside that field `estimate()` sets `in_calibration` to false, widens the range to 35 %
below and 80 % above (45 % below and 120 % above for TPU), lists the reasons in
`outside_because`, and every output says "rough: outside the measured range, trust the
slicer". The code checks these cases:
- other printers (the `generic` profile is a guess, never measured);
- PETG, TPU, ABS, ASA and other filaments (densities are used for grams, speeds are not
  measured);
- other nozzles and layer heights;
- supports: **not counted** in grams or time (the T shelf used 20 % more filament and
  48 % more time than the model);
- infill above 40 %;
- fewer than 2 or more than 4 walls, top/bottom layers other than 5/3;
- three or more colours.

Not measured either, but **not detected by the code** (the estimate keeps its normal
range, so check the slicer's figure in these cases): other filament presets, even of the
same material (two parts sliced 17 and 19 % faster with "Bambu PLA Basic" than with
"Generic PLA", whose flow limit is lower), other infill patterns, the purge
for a particular colour pair (dark to light purges more; three pairs were sliced, 0.55 to
0.74 g per swap, and the model uses 0.72), the prime tower's "Saving" mode,
several AMS units, the external spool feeding the left nozzle, several plates, very large
parts near the bed limits, brims, rafts, ironing, fuzzy skin, vase mode, and "by object"
print order.
