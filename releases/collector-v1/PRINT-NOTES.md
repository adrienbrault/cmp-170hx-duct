# DUAL CMP 170HX — exhaust collector v1 (push-pull)

> **Untested.** No exhaust collector has been printed or fitted to a real case yet. The fit, the seal and the airflow gain are model results only. Print the fit gauge first, check every measurement below, and report what you find.

A collector that bolts a second Arctic P12 Pro over the two cards' rear brackets and pulls their exhaust out of the case. A rounded-rectangle mouth covers all five slot positions: card A's two slots, the blank middle slot and card B's two slots. It lofts over 25 mm to the fan's round 116.8 mm bore under a 120 × 120 × 2.4 mm fan plate with the 105 mm hole pattern. As in V24, the shell is the 3-D dilation of the rounded air volume, so the walls are a uniform 1.2 mm, three 0.4 mm lines (measured: 1.214 mm median, 1.207–1.224 mm p5–p95 away from the corner chamfers). The fan plate is 2.4 mm and the flange 2.8 mm. The flange sits on the rear panel, with a foam-gasket groove on its case face and six 10 × 3 mm magnet pockets.

**Nothing about this part has been measured, fitted or tested.** No hardware dimensions were supplied. Every hardware number below is a published standard value, a derivation from one, or an estimate, and each is labelled as such. **Print the fit gauge first** (`dual-170hx-collector-v1-fit-gauge.stl`, about 3 g) and hold it against the case before printing the real part.

## Before you print: fit gauge

The gauge is a 0.84 mm (3-layer) outline of the flange as it meets the case. Hold it flat against the case's rear panel over the slot brackets, with the ▲ arrow toward the cards' top edge (the bracket screw-tab end), and check:

1. **Window.** The inner rectangle is the collector mouth. Every vent hole of both cards' brackets must be inside it. The short ticks mark the five chassis openings derived from the PCIe CEM spec; your case's real openings should fall between them.
2. **Hub circle.** The 51 mm circle is the fan hub. It should sit over the middle (blank) slot.
3. **Flange edge.** Nothing on the rear panel may stand inside the outer outline: the I/O shield edge, the PSU, case feet, slot-cover retention bars, thumb screws or cable glands. The +y edge (arrow side) is deliberately short, because bracket tabs and external slot screws sit just beyond the bracket top.
4. **Fan outline.** The 120 mm square and its four hole rings are the fan's footprint, 25 mm out from the panel. Check that a 120 × 120 × 25 mm fan has room there.
5. **Mount points.** Each x side has three ring pairs. The round ring is a magnet pocket and the slot is the screw-mode slot. Magnets must land on steel; check with a magnet. In screw mode, a screw must be able to go into the panel there.
6. **Cable notch.** The gap in the +x band is where the fan cable passes the flange. Below it lies the adjacent slot's opening.

If anything is off, change `CollectorParams` (in `duct/params.py`) and regenerate. Don't scale the STL.

## Hardware assumptions

The frame is the duct's: x across the cards, y along the card height (+y = card top edge = bracket screw-tab end), z along the card axis. The bracket plane is at z = 70 + 267 = 337 mm (V24 chamber length + `DomainParams.card_envelope`).

| Quantity | Value used | Source | Measure? |
|---|---|---|---|
| Slot pitch | 20.32 mm (0.800 in) | PCIe CEM r3.0 Fig 1-3; ATX 2.2 Fig 3 | no |
| Slots covered | 5 (card A ×2, blank, card B ×2): window x = ±50.8 mm | cards at 60.96 mm = 3 slots (GeometryParams.pitch) | no |
| Chassis opening per slot | 13.25 × 100.71 mm minimum, starting at the PCB plane; top ≤ 4.82 mm below the bracket top | CEM Fig 9-22 | **yes**: the real openings' height and position |
| Bracket top above system board | 108.21 mm | CEM Fig 10-2 (standard rear panel) | no |
| Card top edge above connector datum | 104.86 mm (A100 PCIe; the 170HX uses the A100 40GB PCIe board) | NVIDIA PB-10577 Fig 3; it-still-boots.github.io/cmp-170hx-docs | **yes** |
| Cooler end | 98.0 mm tall, assumed flush with the card's top edge, centred at duct y = 0 | measured card end (V6–V9 bores 38.5 × 98.5) + assumption | **yes**: where the bracket vents sit relative to the cooler |
| Derived bracket top | y = +52.35 mm, so the window spans y = −53.68…+48.03 (100.71 mm opening + 0.5 mm each end) and the fan axis is at y = −2.83 | derived from the three rows above | **yes** (the gauge checks it) |
| Card envelope from the PCB | 2.67 mm secondary side, 34.80 mm component side; cooler assumed centred on it | CEM Fig 1-3 | no |
| Cooler side | +x (`component_side = +1`): toward higher slot numbers, i.e. toward the bottom of a standard tower | CEM geometry + normal tower mounting | check; the window covers both cases |
| Derived openings | x = [−46.5, −33.3], [−26.2, −13.0], [−5.9, 7.3], [14.4, 27.7], [34.7, 48.0] mm. The window margin is ≥ 2.8 mm | derived | via the gauge ticks |
| 170HX bracket vent window | **not published**. CEM Fig 9-13's two-slot "I/O connector/thermal venting window" (about 13–95 mm below the bracket top, scaled off the figure) fits inside the window | CEM Fig 9-13 (proxy only) | **yes** |
| 170HX display outputs | none | thefpsreview.com CMP 170HX test; TechPowerUp | no |
| Shroud sides | probably closed ("enclosed" aluminium shroud; plain box in NVIDIA's drawings). Side vents are **not ruled out** | VideoCardz; PB-10577 Fig 1/2 | **yes**, look at the card |
| Fan | Arctic P12 Pro 120 × 120 × 25 mm, holes 105.00 mm apart, Ø4.30 mm; cut-out Ø117 | Arctic P12 Pro 2D drawing and mounting pattern | no |
| Fan hub | Ø ≈ 51 mm | scaled off Arctic's 1:1 drawing (50–52 mm) | estimate |
| Thumb-screw head (screw mode) | 12 mm knurled head, clearance 14 mm, 10 mm tall | typical retail 6-32 thumb screw | if you use screw mode |
| Magnets | 10 × 3 mm N52: 2.3 kg pull, about 0.45 kg shear, both at zero gap on thick steel | supermagnete.de S-10-03-N52N | no |
| Rear panel | steel (magnetic), flat around the slots | assumption | **yes** |

## What to measure, in order

1. Print the gauge and do the six checks above.
2. Check the 170HX shroud for side vents. If it has any, see the risk below.
3. Measure the bracket vent area of one card: its y range relative to the bracket top. If it is outside the window, change `bracket_top_y`, `opening_height` or `opening_top_drop`.
4. Check that the rear panel and slot covers are magnetic where the six magnet rings land. If not, use screw mode (`mount='screws'`).

## Required setup

- **Fit a solid (non-vented) blank in the middle slot**, between the cards, and seal gaps. The window covers the middle slot so a vented blank there can't short-circuit the fan, but the fan would then still pull room air from inside the case through that blank instead of through the coolers. Tape over any vents or gaps inside the gasket line that aren't the cards' own bracket vents.
- **Fan orientation: blowing outward, away from the case.** The fan's intake face goes against the collector plate. On Arctic fans the air leaves on the side with the motor struts and the frame's airflow arrow, so the struts face away from the case.
- **Fan screws.** The P12 Pro's own short screws do not fit this layout. Use four long screws through the fan's corner holes into the 3.4 mm pilots: #6-32 (radiator screws) or M4, about 32 mm long (25 mm fan + ~7 mm thread). A 35 mm screw pokes ~2.5 mm out of the 45° chamfer under each corner; harmless, but don't overtighten. Check that the fan's corner holes go through the full 25 mm frame.
- **Gasket.** Use 6 mm wide soft foam strip (open-cell PU or EPDM sponge), about 3 mm thick, in the 6.4 × 1.2 mm groove. Soft foam matters: firm foam pushes back harder than six magnets can hold.
- **Magnets (default).** Glue six 10 × 3 mm disc magnets flush into the pockets on the case face (CA or epoxy). Polarity doesn't matter on steel. The part hangs in shear: the ideal capacity is 6 × 0.45 ≈ 2.7 kg against a collector of 48 g plus the fan. The two lowest magnets (−y corners) land on solid panel below the slot openings. The other four lie over the adjacent slots' openings, so they grip those slots' covers about 1 mm behind the panel face, or nothing if a slot is open. Thin sheet steel, paint, that recess and the foam all reduce the hold, possibly by several times. Weigh your fan and test the hold with the gauge rings and loose magnets first.
- **Screw mode (`mount='screws'`).** Six 3.8 × 8 mm slots, elongated along y, for z-axis screws into the rear panel: existing holes, or self-tapping screws into holes you drill using the gauge. The build asserts that a 14 mm thumb-screw head sits on the bare flange clear of the body. **This differs from the original idea of reusing the bracket screws:** the bracket screws stand on a horizontal tab (axis along y), so an external flange can't clamp them. (Correction: this note first said the tab is bent into the case. It points out of the case, over the panel's top edge; see *Case hardware fit* below.)
- **Fan cable.** The U-notch in the +x flange band (outside the gasket) lets the cable pass the flange without being pinched. Below it is the adjacent slot's opening: remove that slot's cover and drop the cable in, or route it to any other opening. Anything outside the gasket line is outside the sealed plenum.

## Plenum depth and area ratios

The plenum is 25 mm deep, from the bracket plane to the fan face. That is about the hub radius (25.5 mm): the hub shadows the whole middle opening and each card's inner opening (x 13–26 mm from centre) in its middle 51 mm of height, so that air must move up to about 25 mm sideways to reach the blades. A depth of about one hub radius lets it turn with wall angles no steeper than 32° at the mid-sides and 46° along the corner diagonals, where the mouth's corners pull in to the bore. Areas: mouth 10,328 mm², fan bore 10,715 mm² (1.04 × mouth), fan annulus outside the hub 8,672 mm² (0.84 × mouth, 1.30 × the 6,672 mm² of derived chassis openings). The section is close to 1:1 from mouth to blades. A shallower plenum would put the hub's dead zone directly on the inner openings; a deeper one only adds protrusion. This is a geometric argument; no airflow has been computed. The network model's `collector_k = 3.0` is an unvalidated placeholder.

**Protrusion behind the rear panel:** 25 mm collector + 25 mm fan = 50 mm, plus about 0.5–1 mm of compressed gasket.

## Print

Print it flange (case face) down: the STL is already in that orientation, with z = duct z − 337. Use no supports. P1S / 0.4 mm / 0.28 mm PETG: 108.6 min / 48.4 g without supports, with no slicer warnings. Automatic supports add 8.5 min and 2.1 g, all under the four fan-screw pilot holes and in the groove/pockets, and aren't needed. The gasket groove (6.4 mm span) and magnet-pocket ceilings (10.3 mm) print as short bridges; the layer screen flags them (2,512 mm² at the groove's roof layer) by construction. With those filled, the worst layer overhang is 0.44 mm² and there are no floating islands. The four corners of the fan plate rest on 45° chamfers, and the fan-screw pilots pass through them. Fit gauge: 18.7 min / 3.2 g in Bambu's estimate, which includes about 6 min of printer start routine and the profile's brim (about 10 min of actual printing). Use PETG for fit trials. The cards' exhaust is hot, so ASA (as for the duct) is the safer final material.

Material: 50.3 cm³. Air volume: 269.5 cm³. Mesh: one watertight body, 45,448 triangles. Its only folded edges are where the four vertical pilots leave the 45° chamfers. Fan holes measured from the STL: 105.000 × 105.000 mm. The mouth leaves every derived opening fully open, and the fan bore is unobstructed.

## Risks

- **Shroud side vents.** If the 170HX shroud has side or top vents, the pull fan draws case air through them instead of through the fins. That lowers the fin airflow gain and may starve the push duct's far end. Check the card; tape any vents.
- **Vent window position.** The window's y position is derived from standard drawings and the A100 board height, not from a 170HX bracket. The gauge is the check.
- **Magnet hold.** It is marginal on thin, painted steel or across the slot-cover recess. Test it before trusting the part with a spinning fan.
- **Case-specific obstructions.** The flange is 142.6 × 126.7 mm, overlapping one slot beyond each card, and the +y edge is 4.7 mm past the derived bracket top. Retention bars, slot covers with tabs, or a nearby PSU can collide.
- **Not simulated.** The CFD domain can union `CollectorSolids.inner` (one watertight body, 43,008 triangles, inlet face on z = 337 covering every V24 card port), but no push-pull run exists yet. The fan bore is centred at (0, −2.83) at z = 362; outside r = 58.4 mm the outlet face is covered by the fan frame, not open.

Sources: PCIe CEM r3.0 (third-party mirror; Rev 5.0 keeps the bracket figure); Intel ATX 2.2; NVIDIA A100 80GB PCIe product brief PB-10577; Arctic P12 Pro 2D drawing and mounting pattern (support.arctic.de/products/p12-pro/techdocs/); supermagnete.de S-10-03-N52N; thefpsreview.com CMP 170HX test; it-still-boots.github.io/cmp-170hx-docs.

Files: `dual-170hx-collector-v1.stl` (part), `dual-170hx-collector-v1-fit-gauge.stl`, `checks.json` (CAD and serialized-STL checks), `slicer-checks.json`. Renders: `runs/collector-v1/`. Source: `duct/cad/exhaust.py`, `CollectorParams` / `COLLECTOR_V1` in `duct/params.py`, `release_collector` in `duct/print/release.py`.

## Case hardware fit (added after release: v1 does not fit)

`duct/cad/hardware.py` now models the case and card hardware at the cards' rear: rear panel with seven 13.25 × 100.71 mm slot openings (CEM Fig 9-22), the slot ledge, both 170HX dual brackets (CEM Fig 9-13 outline, 81 × 25 mm vent window from the author's photo), the solid middle blank and the covers either side, and the 6-32 slot screws. `fit_check` places a collector flange-to-panel and measures it; `tests/test_hardware.py` pins the numbers.

- **The bracket's top tab points out of the case.** In CEM Fig 9-5's side view, the card-mount bosses are on one side of the plate and the tab on the other, and the plate sits behind the chassis wall (Fig 9-25 note 1). So the tab reaches over the panel's top edge and rests on the slot ledge outside. The slot screws stand on it 5.6 mm out from the panel face, heads up (+y). **Every slot screw is outside the case**, in a band from 1.7 mm below to 2.5 mm above the bracket top, 0–12 mm out from the panel.
- **v1 lands on that band.** Its +y flange edge (y 57.0) and gasket reach past the ledge underside (y 50.7). Intersection volumes, with an assumed 0.8 mm panel, a 0.8 × 12 mm ledge and pan-head screws:

| Part | Intersection (mm³) |
|---|---|
| Slot ledge | 396.3 |
| Bracket tops | 131.9 |
| Middle blank | 35.4 |
| Side covers | 77.6 |
| Screw heads | 30.4 |
| Screw tips | 68.9 |
| **Total** | **740.5** |

  Across ledge depths of 10–15 mm, with or without a 4 mm down-lip, and with pan or thumb screws, the total ranges from 675 to 1391 mm³. A driver can't reach any screw with v1 fitted. Of the gasket centreline, 106.5 mm runs over the ledge zone and 200.5 mm over recessed cover plates. **Do not print v1; use collector-v2.**
- Magnets: the lower pair sits on flush panel. The other four are 80–94 % over the side slots' covers, 0.8 mm behind the face.
- Vent windows: each 25 mm window straddles the 7.07 mm panel rib between its card's two CEM-minimum openings, so 572.7 mm² of each 2025 mm² window (28 %) is behind steel. The CFD's `BracketWindow` treats it as open. This needs measuring, and is a CFD question.
- Bypass leaks into a sealed collector are covered in collector-v2's PRINT-NOTES. For v1 at 24.6 Pa they are: 3.8 % of the fin flow through 0.3 mm plate-to-panel slits, and 9.6 % through a vented middle blank.

Renders: `runs/hardware/` (`v1-in-place-collision.png`, `v1-cut-at-screw.png`).
