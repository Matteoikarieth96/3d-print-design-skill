# Calibration coupon: print, read, record

The coupon measures what fits YOUR printer, material and slicer profile
actually produce, so the design numbers stop being guesses.

![coupon](../docs/calibration-coupon.png)

## Build it

```
cd <project folder>
"$SKILL/.venv/bin/python" -P "$SKILL/scripts/calibration_coupon.py" build --out out --peg 6
```

Outputs `out/calibration-coupon.stl` (4 bodies on one plate: the plate, two
round pegs, one square bar) and `out/calibration-coupon.json` with a `legend`.
printcheck warns about overhangs on purpose: the 50 and 60 degree fins are
meant to show where your printer starts to fail.

## Print it

- Same material, nozzle, layer height and slicer profile you will use for the
  real part. Changing any of them means a new coupon.
- No supports, no brim on the pegs (the bottom chamfers already handle
  elephant foot), 3 walls, 20 % infill.
- About 30 to 45 minutes on a typical printer.

## Read it (no text on the coupon, count notches)

Each hole has V notches on the plate edge next to it:
- **shallow notch = 1 step, deep notch = 5 steps, one step = 0.05 mm per side**;
- no notch = 0.00, one shallow = 0.05, three shallow = 0.15, one deep = 0.25,
  one deep + three shallow = 0.40.

Round holes are along the front edge (the long edge nearest the pegs) and are
counted with the notches on that edge; square holes are along the back edge
with their own notches. Peg and bar are the nominal size (6 mm by default).

| Record as | How to find it |
|---|---|
| `--press` | the tightest ROUND hole the peg enters fully with firm hand pressure (it should stay put) |
| `--snug` | the first ROUND hole where the peg turns by hand with no visible play |
| `--sliding` | the first SQUARE hole the bar slides through with a light push |
| `--free` | the first hole where the peg or bar drops through under its own weight |
| `--overhang` | the steepest fin with a clean underside; fins from front to back are 30, 40, 45, 50, 60 degrees |

## Record it

```
"$SKILL/.venv/bin/python" -P "$SKILL/scripts/calibration_coupon.py" record \
  --press 0.10 --snug 0.15 --sliding 0.20 --free 0.30 --overhang 45 \
  --printer "my printer" --material PETG --nozzle 0.4 --layer 0.2
```

This writes `fits.json` in the current folder (atomically, never through a symlink):

```json
{
  "printer": "my printer",
  "material": "PETG",
  "nozzle_mm": 0.4,
  "layer_mm": 0.2,
  "measured": "2026-10-08",
  "clearance_per_side": {"press": 0.1, "snug": 0.15, "sliding": 0.2, "free": 0.3},
  "overhang_ok_deg": 45
}
```

Every `build.py` in the same folder loads it through `cad.load_fits()` and
exposes it as `FITS`; the metadata JSON records which source was used. Copy
`fits.json` into other project folders that use the same printer and material.
A sample lives in `templates/fits.example.json`.
