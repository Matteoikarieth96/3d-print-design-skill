# Versions of coaster

| Version | What changes | Filament | Print time | vs standard | Checks |
|---|---|---|---|---|---|
| standard | 3 walls, 15% infill: the everyday choice for a functional part | ~19.8 g PLA (6.64 m), of which 2.2 g purge | ~36 min (30 min to 55 min) | - | pass |
| light | 2 walls, 10% infill: fastest, least filament; for looks or light use | ~18.5 g PLA (6.2 m), of which 2.2 g purge | ~34 min (25 min to 55 min) | -2 min, -1.3 g | pass |
| strong | 4 walls, 40% infill: slower, more filament; for loads, screws and clips | ~24.2 g PLA (8.11 m), of which 2.2 g purge | ~41 min (30 min to 1 h 05 min) | +5 min, +4.4 g | pass |

- standard, other nozzle choice (black on the right nozzle (external spool)): ~41 min, 18.7 g

Estimates before slicing. Measured field: Bambu Lab X2D, PLA, 0.4 mm nozzle, 0.2 mm layers, no supports, infill up to 40 %; there every calibration and holdout slice fell inside the range shown. Outside it the range is wider and marked rough. The slicer gives a closer figure. Build one with `build.py --variant NAME`.
