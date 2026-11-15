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

**Calibration (34 rows, `set = calibration`):** the coefficients were fitted on 32 of
these; the coaster's light and strong versions were sliced together with its standard
version and are listed here rather than as holdout.
Seven shapes (plate 60 x 24 x 4, cubes 20 and 40, cylinder 50 x 30, tube 40 mm with a 3 mm
wall and 60 mm high, slab 100 x 80 x 10, disc 90 x 4) at 2/10 %, 2/15 %, 3/15 % and 4/40 %
walls/infill; a 40 x 40 x 10 mm block in one colour, with a second-colour stripe on the
same nozzle (49 swaps, 2 h 04 min, 43.5 g of which 36.1 g purge) and on the other nozzle
(42 min, 12.6 g of which 5.2 g purge); the two-colour coaster example in its three versions
(black on the right nozzle). Model against slicer: **time within 13 % (mean 3 %), grams
within 10 % (mean 4 %).**

**Holdout (19 rows, `set = holdout`):** parts never used for fitting, made with this skill
(design build) and sliced through x2d-print exactly as a person would: the cable clip
(3 versions), the calibration coupon, a 15 x 15 x 80 mm post, pins 12 x 70 and 8 x 50, a
10 x 10 x 40 post, a 180 x 120 x 3 plate, three separate pucks on one plate, an open box,
a knob at 40 % infill, an L bracket with holes, an 80 x 80 x 3 plate with 25 holes, a
tapered tower, two separate discs in two colours (both nozzle plans), the coaster with
both colours on the left nozzle, and a T shelf with supports. Model against slicer on the
18 rows inside the measured field: **time within 32 % (mean 8 %), grams within 16 %
(mean 7 %).** All 19 rows are inside the range shown.

Two holdout rows changed the model, and say so in their `note`: the 15 x 15 x 80 post
took 61 min against 39 estimated, which added Bambu Studio's minimum layer time (8 s,
"slow down for better layer cooling" in Generic PLA); the 12 x 70 pin then came out too
slow, which capped that by the 20 mm/s minimum speed. The coefficients were refitted on
the calibration rows only; the post and the pin are no longer out of sample, so the other
16 rows are the strict holdout (same maximum errors: 32 % time, 16 % grams).

## The range shown, and why it is asymmetric

Inside the measured field the build shows the estimate and a range of **15 % below to
50 % above** for time and **15 % below to 10 % above** for grams (`TIME_SPREAD`,
`GRAMS_SPREAD`), rounded outwards to 5 minutes. The time range was widened upwards after
the holdout: parts with many small features print slower than the model says (the
calibration coupon took 41 min against 28 estimated, the plate with 25 holes 35 against
28). Grams lean the other way: the model is usually a little high (more so on small
parts, by up to 15 %).

## What is NOT covered

The estimate is measured only for: **Bambu Lab X2D, PLA, 0.4 mm nozzle, 0.2 mm layers, no
supports, infill up to 40 %**. Outside that field `estimate()` sets `in_calibration` to
false, widens the range to 35 % below and 80 % above (45 % below and 120 % above for TPU)
and every output says "rough: outside the measured range, trust the slicer":
- other printers (the `generic` profile is a guess, never measured);
- PETG, TPU, ABS, ASA and other filaments (densities are used for grams, speeds are not
  measured);
- other nozzles and layer heights;
- supports: **not counted** in grams or time (the T shelf used 20 % more filament and
  48 % more time than the model);
- infill above 40 %, other infill patterns, other wall or top/bottom settings than the
  preset's line widths;
- three or more colours, several AMS units, the external spool feeding the left nozzle;
- several plates, very large parts near the bed limits, brims, rafts, ironing, fuzzy skin,
  vase mode, and "by object" print order.
