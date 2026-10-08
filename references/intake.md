# Intake questions

Ask in the user's language. Skip anything already answered. With
`AskUserQuestion`: at most 4 questions per call, 2 to 4 options, recommended
option first and labelled "(Recommended)". Never more than 2 rounds before you
show progress; fill the rest with the defaults below and say which you used.

| # | Topic | Why it matters | Typical options | Default if skipped |
|---|---|---|---|---|
| 1 | What the part does and where it lives | Decides the shape, the load path and the print orientation | free text, ask for a photo or sketch | none: always ask |
| 2 | Critical dimensions, measured with calipers, and which ones are critical | A printed part is only as right as its input numbers; non-critical sizes can be rounded | measured values; "critical: yes/no" per value | ask the user to measure; mark guesses `default` in the table |
| 3 | Mating parts and fit type | Clearance per side differs a lot between fits | press (does not come apart), snug (by hand, no play), sliding (moves, little play), free (loose) | snug for lids and plugs, free for screw shanks |
| 4 | Load, heat, outdoor or UV exposure | Material choice and layer orientation; PLA softens around 55 to 60 C and creeps | light / moderate / heavy; indoor / near heat / outdoors | light, indoor, room temperature |
| 5 | Printer model, build volume, nozzle diameter | Bed fit check, minimum wall (2 x nozzle), overhang behaviour | e.g. "220 x 220 x 250, 0.4 nozzle" | 220 x 220 x 250 mm, 0.4 mm nozzle, 0.2 mm layers |
| 6 | Material | Fits, strength, temperature, flex for snaps | PLA (easy, stiff) / PETG (tougher, heat to about 75 C) / TPU (flexible) / ABS or ASA (heat, outdoor) only with ventilation | PLA indoors, PETG for clips and outdoor-ish, ASA for full sun with ventilation |
| 7 | Colours | Single colour, a colour change at a layer, or several materials changes how you split the model | single / colour change at a height / multi-material (one STL per colour) | single colour |
| 8 | Quantity | Many copies favour short print time and no supports | 1 / a few / many | 1 |
| 9 | Looks vs strength | Sets wall count, infill, chamfers vs sharp edges, visible seams | looks first / balanced / strength first | balanced |
| 10 | Supports allowed | Without supports every overhang must be designed out | no supports (Recommended for functional parts) / supports OK / only easy-to-remove | no supports |
| 11 | Orientation constraints | Layers are the weak direction; a face may need to be smooth or flat | "this face must be smooth", "hook must not snap" | choose the orientation where loads run along layers |
| 12 | Deadline | Decides whether a calibration coupon print fits in the schedule | today / this week / no rush | no rush: offer the coupon when fits matter |
| 13 | Real person's face or likeness? | Consent and privacy | yes / no | if yes, ask for the person's consent before going on |

## Suggested first round (one `AskUserQuestion` call)

1. Printer and nozzle: "220 x 220 bed, 0.4 nozzle (Recommended)", "smaller bed (180 or less)", "larger bed (250+)".
2. Material: "PETG (Recommended for clips and functional parts)", "PLA", "TPU", "ABS/ASA (needs ventilation)".
3. Supports: "No supports (Recommended)", "Supports are fine".
4. Fit for the mating part: "Snug (Recommended)", "Press", "Sliding", "Free".

Ask for critical measurements in plain text alongside (they are numbers, not
options), and ask for a photo or a sketch with dimensions if the shape is not
obvious.

## Closing summary

"Here is what I will build: a <part> for <use>, about <W x D x H> mm, printed
<orientation> in <material> on a <bed> bed with a <nozzle> nozzle, <supports>,
fits: <fit type> using <clearance source>. Shall I go ahead?"
