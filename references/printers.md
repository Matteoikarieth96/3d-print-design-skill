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
- **Two nozzles.** Left: direct drive, fed by the AMS (up to 4 colours per AMS), the
  fast one. Right: Bowden, fed by the external spool, **no TPU**, and slower: Bambu
  Studio's X2D process prints its outer walls at 50 mm/s against 200 mm/s on the left
  nozzle, with a tenth of the acceleration. Changing colour on the same nozzle costs
  about 2 minutes and 0.7 g of purge each time. A second nozzle saves that purge: it costs
  about 4.5 minutes once, then about 24 s and 0.1 g for each layer the colours share. So
  the **main colour stays on the left nozzle and the accent goes on the external spool**.
  Measured, total (of which purge): a 40 x 40 x 10 mm block takes 17 min and 6.9 g in one
  colour; with a 10 mm stripe in a second colour on the other nozzle 42 min and 12.6 g
  (of which 5.2 g purge); with both colours on one nozzle 2 h 04 min and 43.5 g (of which
  36.1 g purge, 49 colour changes). A hollow 60 mm ball with a logo inlay in 111 of its
  357 layers: 59 min and 14.4 g in one colour; 1 h 47 min and 28.5 g (14.2 g purge) with
  the logo on the right nozzle; 2 h 13 min and 28.5 g with the body on the right nozzle;
  4 h 48 min and 87.8 g (73.5 g purge) with both colours on the left nozzle.
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
2. **Nozzle plan chosen by time, when colours share layers.** The layers that hold two
   colours are counted over every part on the plate. The build then estimates three
   plans: all colours on the left nozzle (AMS, a purge on every shared layer); the main
   colour, the one spanning the most layers, on the left nozzle and the largest accent
   on the right one (external spool, little purge); and the main colour on the right
   nozzle with the accents in the AMS. It suggests the fastest (equal minutes: the one
   with less filament) and records them all, with minutes and grams, in
   `design.nozzle_options`; the build output and the print sheet show the next one
   ("other nozzle choice: ~X min, Y g"). With two colours the accent on the right nozzle
   was the fastest plan in every object measured, even with few shared layers (the
   two-colour coaster, 3 of 20: 34 min, against 37 all left and 41 with the base on the
   right nozzle). The main colour on the right nozzle can still win with three or more
   colours, when it is the only colour every layer needs. Set `EXTERNAL_SPOOL = False` in
   `build.py` when no spool can go on the external holder: everything then stays on the
   left nozzle. When colours only change by height (no layer holds two colours)
   everything stays on the left: one change per boundary. One colour: left nozzle only.
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
- `settings`: the print settings of the chosen version as Bambu Studio strings
  (`layer_height`, `wall_loops`, `sparse_infill_density`, `top_shell_layers`,
  `bottom_shell_layers`, `enable_support`), so the .3mf prints what was estimated.
- `variants` (after `build.py --variants`): the other versions, each with `name`, `about`,
  `settings`, `estimate` and, when its geometry differs, `stl` (replacement STLs under
  `variants/<name>/`). x2d-print can slice them all and show the real numbers side by side.
- `design` (format 2): printer, material, layer and nozzle, the chosen `variant`,
  `quantity`, `first_print`, each part's height range and layer count, how many layers mix
  colours (over all parts), `suggested_nozzles` **keyed by colour name**,
  `external_spool`, `nozzle_options` (each plan with its nozzles, minutes and grams), the pre-slice `estimate` (grams,
  metres, minutes, range, `in_calibration`), the notes printed by the build, and a `todo` list for x2d-print.
- **A rebuild keeps what x2d-print filled in** (template path, filament numbers, nozzles)
  as long as every STL keeps its name and colour; if colours change they are reset and
  the build says so.

The person (or Claude in the next skill) opens the x2d-print skill in the same `out/`
folder: the STLs and the draft job are already side by side, and x2d-print writes the
`.3mf` inside that folder.
