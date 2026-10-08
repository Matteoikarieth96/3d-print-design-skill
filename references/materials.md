# Materials

Typical ranges only. The filament maker's label wins; then your own tests.
Temperatures are nozzle / bed in degrees C. "Softens" is a rough heat
deflection guide for a printed part under light load.

| Material | Nozzle | Bed | Softens around | Good for | Watch out for |
|---|---|---|---|---|---|
| PLA | 190 to 220 | 50 to 65 (or cold on textured sheets) | 55 to 60 | indoor brackets, prototypes, decorative parts; stiff and accurate | creeps under constant load, deforms in a hot car or in sun, brittle in snaps |
| PETG | 220 to 250 | 70 to 85 | 70 to 80 | clips, snaps, functional parts, damp places; tougher than PLA | strings, sticks too well to smooth PEI (use a release agent or textured sheet), absorbs moisture (dry it) |
| TPU | 210 to 240 | 30 to 60 | depends on grade | bumpers, feet, gaskets, grips, flexible straps | print slowly, direct drive preferred, absorbs moisture, poor bridging |
| ABS | 230 to 260 | 90 to 110 | 90 to 100 | heat-resistant parts, parts you sand or solvent-smooth | warps and cracks without an enclosure, styrene fumes: ventilation required, yellows in sunlight |
| ASA | 235 to 260 | 90 to 110 | 90 to 100 | outdoor parts in full sun, car interiors | same handling as ABS: enclosure and ventilation required |

## Ventilation and fumes

- Every FDM print releases ultrafine particles and some volatile compounds.
  Print in a ventilated room, not next to where people sleep, and keep
  children and pets away from the machine.
- ABS and ASA release styrene and more particles: only print them in an
  enclosure with extraction to outside or a suitable filter, or in a well
  ventilated space. The skill asks about ventilation before suggesting them.
- Never heat filament above its range to "help" adhesion; burnt plastic fumes
  are worse than the normal ones.

## Food contact

Treat FDM prints as not food safe. Layer lines trap bacteria and cannot be
cleaned reliably, colorants and additives may not be approved for food, and
some brass nozzles contain lead. If the user insists: a filament certified for
food contact, a stainless nozzle, short dry contact only (a cookie cutter, not a
cup), or a food-safe coating, and say these are mitigations, not guarantees.
Nothing for babies or medical use.

## Outdoor use

- UV: ASA is the usual choice; PETG lasts reasonably; PLA and ABS degrade and
  yellow.
- Heat: a dark part in sun can exceed 60 C; PLA will sag.
- Moisture and freeze: thicker walls and higher infill keep water out of the
  part's interior.

## Mass estimate

`out/<name>.json` gives `estimated_mass_g_solid`: volume x density at 100 %
infill, an upper bound. Densities used (g/cm3): PLA 1.24, PETG 1.27, TPU 1.21,
ABS 1.04, ASA 1.07. The slicer's estimate with your walls and infill is the real
figure.
