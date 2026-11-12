# Example: two-colour coaster for the Bambu Lab X2D (fictional)

A fictional part to show a multicolour design and the hand-off to the
[x2d-print](https://github.com/Matteoikarieth96/x2d-print-skill) skill. The
sizes are made up for the example.

**Intake answers used:** a 90 mm coaster for mugs, black with a yellow star on
top; Bambu Lab X2D, 0.4 nozzle, 0.2 layers; PLA; two colours, black is the main
one; no supports; quantity 1.

**Design choices (all in the parameter block of `build.py`):**
- `PRINTER = "bambu-x2d"`, `PRINTER_BED = None`: with two colours the part is
  checked against the 235.5 x 256 x 256 mm both X2D nozzles reach.
- Two parts, `base` and `star`, with `ASSEMBLY = True`: the star sits in a
  pocket on top of the base, 3 layers deep (0.6 mm), so yellow covers black.
  The pocket is cut with the star's own outline: the parts touch without
  sharing volume.
- Colours meet in only 3 of 20 layers. Black spans all 20 layers, so the
  hand-off suggests it for the right nozzle (external spool) and the yellow
  star for the left one (AMS): no colour change on the same nozzle.

**Build:**

```
S=~/.claude/skills/3d-print-design
cd examples/two-colour-coaster
PRINT3D_SKILL_DIR="$S" "$S/.venv/bin/python" -P build.py
```

Output in `out/`: `coaster-base.stl`, `coaster-star.stl`, their `.json`
metadata, and `x2d-job.json`, the draft job for x2d-print. In x2d-print the
template is set and each part gets the number of the template filament with
its colour. A local slicing check of this example, with black on the external
spool and yellow in the AMS, gave about 41 minutes, 16 g of model, 1 g of purge
and no colour change on the same nozzle.
