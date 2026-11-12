# Printer profiles and the hand-off to a printer skill

The design skill works for any FDM printer. A **printer profile** (`PRINTER` in
`build.py`, defined in `scripts/printers.py`) gives the build volume and the facts the
checks need. Profiles with a matching printer skill also write a **draft job file** next
to the STLs, so the next skill starts from what the design already knows.

The skills stay separate: the design skill never runs the printer skill, never opens a
slicer and never contacts a printer. It only writes a JSON file in `out/`.

| Profile | Printer | Build volume checked | Hand-off |
|---|---|---|---|
| `generic` (default) | any | 220 x 220 x 250 mm, or `PRINTER_BED` | none: the print sheet only |
| `bambu-x2d` | Bambu Lab X2D | 256 x 256 x 261 mm; 235.5 x 256 x 256 mm with two or more colours | `out/x2d-job.json` for the **x2d-print** skill |

`PRINTER_BED = (X, Y, Z)` always overrides the profile (any other printer, or a smaller
area on purpose).

## Bambu Lab X2D (`PRINTER = "bambu-x2d"`)

Numbers from Bambu Studio's own machine profile "Bambu Lab X2D 0.4 nozzle". x2d-print
checks them again against the person's Bambu Studio when it builds the project.

- **Build volume:** 256 x 256 mm plate, 261 mm high with the left nozzle. The right
  nozzle reaches only x from 20.5 to 256 mm and 256 mm high, so with two or more colours
  the design is checked against **235.5 x 256 x 256 mm**, plus the usual 5 mm margin.
  The prime tower (35 mm wide) also takes plate space in a multicolour print: a part near
  the full width may need its own plate.
- **Two nozzles.** Left: direct drive, fed by the AMS (up to 4 colours per AMS). Right:
  Bowden, fed by the external spool, **no TPU**. Switching nozzle wastes almost nothing;
  changing colour on the same nozzle purges about 0.35 to 0.5 g each time.
- **Defaults:** 0.4 mm nozzle, 0.20 mm layers (process "0.20mm Standard @BBL X2D"),
  Textured PEI Plate (the bottom face takes its texture; the Cool Plate is not supported).
- **One material per print.** PLA with PETG bonds poorly. All colours of one build use
  `MATERIAL`.

### Designing for X2D colours (most important first)

1. **One STL per colour, all in one coordinate frame.** Return `{suffix: solid}` from
   `build_part()` and set `ASSEMBLY = True`: the parts are then checked joined together
   (on the bed, overhangs, build volume) and must touch without overlapping. Cut each
   accent out of the base with the same outline (`cad.difference(base, accent)`), as in
   `examples/two-colour-coaster`.
2. **Dominant colour on its own nozzle.** Two colours on the X2D cost almost no purge:
   one per nozzle. The hand-off suggests the colour that spans the most layers for the
   right nozzle (external spool), the accents for the left (AMS).
3. **Accents in few layers.** Inlays on top (flush, 3 layers deep) or face down in the
   first 3 to 5 layers. With three or more colours, every layer that holds more colours
   than there are nozzles costs a purge: the `colour_layers` check counts them and warns
   above 10.
4. **Colour parts at least 3 layers thick** (0.6 mm at 0.2 mm layers), or the colour
   beneath shows through: `colour_thickness` warns.
5. **Colour boundaries on layer boundaries:** heights in multiples of `LAYER`.
6. **Accent width at least 2 x nozzle** (0.8 mm) or it disappears: `thin_walls` on each
   colour part measures widths only.
7. **TPU:** left nozzle only, and soft TPU is not for the AMS. Single colour, or ask the
   person how they feed it.

## The hand-off file (`out/x2d-job.json`)

Written after a successful build when the profile has a hand-off. It is a draft in the
x2d-print job format, with an extra `design` block:

- `objects` / `parts`: one object with every colour part when `ASSEMBLY = True`, else one
  object per STL. Each part has `stl`, `colour` (from `COLOUR_NAME`) and `colour_hex`
  (from `COLOR`).
- `template` and each `filament` are **left empty on purpose**: they come from the Bambu
  Studio template that the person saves in x2d-print (step 3), because only that file
  knows which colour is in which AMS slot. x2d-print refuses the job until they are set.
- `settings`: `enable_support` when supports are allowed, otherwise empty.
- `design`: printer, material, layer and nozzle, each part's height range and layer
  count, how many layers mix colours, the suggested nozzle per STL, the notes printed by
  the build, and a `todo` list for x2d-print.

The person (or Claude in the next skill) opens the x2d-print skill in the same `out/`
folder: the STLs and the draft job are already side by side, and x2d-print writes the
`.3mf` inside that folder.
