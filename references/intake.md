# Intake questions

Ask in the user's language. Skip anything already answered. With
`AskUserQuestion`: at most 4 questions per call, 2 to 4 options, recommended
option first and labelled "(Recommended)". Never more than 2 rounds before you
show progress; fill the rest with the defaults below and say which you used.

| # | Topic | Why it matters | Typical options | Default if skipped |
|---|---|---|---|---|
| 1 | What the part does and where it lives | Decides the shape, the load path and the print orientation | free text, ask for a photo or sketch | none: always ask |
| 0 | First print? | A beginner needs plain words, the safe defaults and the full step-by-step guide later | first print / printed a few times / experienced | first print: explain every term the first time you use it ([glossary](glossary.md)) |
| 2 | Critical dimensions and which ones are critical | A printed part is only as right as its input numbers; non-critical sizes can be rounded | measured values; "critical: yes/no" per value. No calipers: a ruler to 1 mm, or a photo of the object next to a ruler or a coin (a 1 euro coin is 23.25 mm) | ask the user to measure; mark guesses `default` in the table and add 0.5 mm of room where it must fit |
| 3 | Mating parts and fit type (only if something fits into or onto it) | Clearance per side differs a lot between fits | press (does not come apart), snug (by hand, no play), sliding (moves, little play), free (loose) | snug for lids and plugs, free for screw shanks |
| 4 | Load, heat, outdoor or UV exposure | Material choice and layer orientation; PLA softens around 55 to 60 C and creeps | light / moderate / heavy; indoor / near heat / outdoors | light, indoor, room temperature. **Parts that carry load (hook, bracket, shelf support, holder): never skip, ask the weight in kg and how it pulls, and never recommend the light version** |
| 5 | Which printer they own (model name) | Bed fit check, minimum wall (2 x nozzle, the opening the plastic comes out of), overhang behaviour; a printer with a profile (Bambu Lab X2D) sets these and adds a hand-off | "Bambu Lab X2D", another model by name; a beginner rarely knows the bed size, so ask the model, not the numbers | the `generic` profile: 220 x 220 x 250 mm, 0.4 mm nozzle, 0.2 mm layers |
| 5b | Which filament they have now (material and colours) | A design in colours they do not own cannot be printed today | "PLA: black, white, yellow"; "I don't know, use the lab's PLA" | PLA, one colour they can see on the spool |
| 5c | X2D and **more than one colour** only: which colour is the main one, and can a spool go on the external holder? | The X2D's second nozzle is fed only by the external holder; it sets `EXTERNAL_SPOOL` | "yes, black on the holder"; "AMS only" | `EXTERNAL_SPOOL = True`; the build picks the faster nozzle plan |
| 6 | Material | Fits, strength, temperature, flex for snaps | PLA (easy, stiff) / PETG (tougher, heat to about 75 C) / TPU (flexible) / ABS or ASA (heat, outdoor) only with ventilation | what they already have, usually PLA; suggest PETG only for heat, sun or clips that flex |
| 7 | Colours | Single colour, a colour change at a layer, or several materials changes how you split the model | single / colour change at a height / multi-material (one STL per colour); on the X2D, 5c only if more than one | single colour |
| 7b | Logo, text or a picture on it? | The skill has no SVG, image or font import and no text helper | a simple shape (star, heart, arrow) raised, engraved or in a second colour / a flat pocket for a sticker / text added later in the slicer (Bambu Studio has a text tool) | no mark |
| 7c | Hollow or solid (parts that carry no load) | A thin shell around a real cavity uses less filament and time than a solid with infill | hollow shell / solid with infill / stronger shell | hollow, without asking; say it in the plan. Never for load, fits, threads or screw bosses ([design rules](design-rules.md), section 15) |
| 8 | Quantity | Many copies favour short print time and no supports | 1 / a few / many | 1 |
| 9 | Looks vs strength, and how much time and filament | Sets the version (walls, infill), chamfers vs sharp edges; the build compares light / standard / strong with grams and minutes | looks first / balanced / strength first; "fast" or "no hurry" | balanced (standard), and show all three versions anyway |
| 10 | Supports allowed | Without supports every overhang must be designed out | no supports (Recommended for functional parts) / supports OK / only easy-to-remove | no supports |
| 11 | Orientation constraints | Layers are the weak direction; a face may need to be smooth or flat | "this face must be smooth", "hook must not snap" | choose the orientation where loads run along layers |
| 12 | Deadline | Decides whether a calibration coupon print fits in the schedule | today / this week / no rush | no rush: offer the coupon when fits matter |
| 13 | Real person's face or likeness? | Consent and privacy | yes / no | if yes, ask for the person's consent before going on |

## Suggested first round (one `AskUserQuestion` call)

1. Experience: "First print (Recommended if unsure)", "A few prints", "Experienced".
2. Printer: "Bambu Lab X2D", "Another model (type its name)". If the person already named it, skip this and use its profile.
3. Filament they have now: "PLA (Recommended)", "PETG", "TPU", "I don't know, use the lab's PLA": then ask the colours in plain text. Only if they want more than one colour (and the printer is an X2D), ask in a short second step which colour is the main one and whether a spool can go on the external holder.
4. Only if something fits into or onto the part: "Snug (Recommended): by hand, no play", "Press: does not come apart", "Sliding: moves", "Free: loose". Otherwise ask about supports: "No supports (Recommended): nothing to snap off later", "Supports are fine".

Explain each term in the option text itself the first time (a beginner does not
know "supports" or "nozzle"); [glossary.md](glossary.md) has one-line wordings.

Ask for critical measurements in plain text alongside (they are numbers, not
options), and ask for a photo or a sketch with dimensions if the shape is not
obvious.

## One confirmation: summary and dimension table together

Do not confirm twice. Send one message with the summary and the measurements
table of SKILL.md Step 2, and one question at the end:

"Here is what I will build: a <part> for <use>, about <W x D x H> mm, printed
<orientation> in <material> on a <bed> bed with a <nozzle> nozzle, <supports>,
fits: <fit type> using <clearance source>, colours: <colours and nozzle plan if
any>.

| Measure | Value (mm) | Source | Critical |
|---|---|---|---|
| ... | ... | measured / derived / default | yes / no |

After the first build I will show you the versions (light, standard, strong; for
a part that carries load only standard and strong) with the grams of filament and
the print time of each, so you can choose. Shall I build it like this?"
