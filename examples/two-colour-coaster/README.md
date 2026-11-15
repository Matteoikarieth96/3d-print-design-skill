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
- Colours meet in 3 of 20 layers (the star sits in a pocket, so those layers
  hold black and yellow). The build estimates both nozzle plans: all on the
  left nozzle (AMS, 3 colour changes) at about 36 min and 19.8 g, and black on
  the right nozzle (external spool, about 10 min once to heat it) at about
  41 min and 18.7 g. With so few shared layers **all on the left is faster**,
  so the hand-off suggests black and yellow both on the left; the other plan
  is in `design.nozzle_options` and in the build output. `EXTERNAL_SPOOL = True`
  only allows the right nozzle; `False` would rule it out.

**Build:**

Copy it into a fresh project folder first (never build inside the repository):

```
S=~/.claude/skills/3d-print-design
mkdir -p ~/3d-print-design/coaster && cp "$S/examples/two-colour-coaster/build.py" ~/3d-print-design/coaster/
cd ~/3d-print-design/coaster
PRINT3D_SKILL_DIR="$S" "$S/.venv/bin/python" -P build.py --variants
```

Output in `out/`: `coaster-base.stl`, `coaster-star.stl`, their `.json`
metadata, and `x2d-job.json`, the draft job for x2d-print. In x2d-print the
template is set and each part gets the number of the template filament with
its colour. `--variants` also writes `variants.md` / `variants.json` and the
light and strong STLs under `variants/`; it estimates light, standard and
strong at about 18.5, 19.8 and 24.2 g and 34, 36 and 41 minutes.

Local slicing checks of this example in Bambu Studio 02.09.01.70 (x2d-print
`build --check`), total (of which purge): all on the left nozzle 38 min and
19.7 g (of which 3.1 g purge); black on the right nozzle 41 min and 17.6 g (of
which 1.0 g purge). Both are inside the estimate's range; the second plan saves
2 g of filament for about 2 more minutes.
