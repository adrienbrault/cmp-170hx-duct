# DUAL CMP 170HX — exhaust collector v2 (push-pull)

> **Untested.** No exhaust collector has been printed or fitted to a real case yet. The fit, the seal and the airflow gain are model results only. Print the fit gauge first, check every measurement below, and report what you find.

v2 is collector-v1 refitted around the case hardware at the cards' rear. v1's flange landed on the slot ledge, the bracket tabs and the slot screws, which all sit **outside** the case just above the slot openings (see collector-v1 PRINT-NOTES, *Case hardware fit*). v2 clears every modelled part and leaves every slot screw reachable with the collector fitted. Its gasket runs on steel all the way round. Walls stay a uniform 1.2 mm; the fan, the magnets and the print orientation are unchanged.

> **v2 needs the slot between the two cards closed.** Its single gasket loop encloses all five slots from −2 to +2. If the middle slot is open, as in the author's case, the fan pulls case air through the whole 13.25 × 100.7 mm opening. That is 1,309 mm² inside the loop, about 786 mm² effective. At the CFD suction (−24.6 Pa) it passes about 5.0 L/s, roughly a quarter of the fan's flow (bypass fraction 0.26; 0.18 at 10 Pa), all of it from inside the case rather than through the fins. Before fitting v2, screw a **solid** blank into that slot or cover it with aluminium tape from outside. The author's case also has slots ±3 open (no covers anywhere). v2's groove then runs about 1 mm over each of them, leaving 2.0 mm of foam on steel. Its four upper magnets (x ±60.55) sit over those open slots and hold nothing; only the lower pair holds. Covers in slots −3, 0 and +3 (`CASE_COVERED`) restore the assumptions below. Otherwise use **collector-v3**, which seals each card separately and keeps the middle slot under its flange (`releases/collector-v3/PRINT-NOTES.md`). The fit and bypass numbers below assume solid covers in slots −3, 0 and +3 (`CASE_COVERED`); `CASE` now defaults to no covers.

**Nothing has been measured or fitted.** The hardware is CEM-standard geometry plus labelled assumptions (`CaseParams` / `BracketParams` in `duct/cad/hardware.py`; unknowns in the table below). **Print the fit gauge first** (`dual-170hx-collector-v2-fit-gauge.stl`, about 4 g). It must slide flat under the slot ledge; the ▲ arrow now hangs inside the window, pointing at the bracket tops.

## What changed from v1

| | v1 | v2 | Why |
|---|---|---|---|
| Mouth y | −53.68…48.03 (chassis openings ±0.5) | **−58.0…44.85** | The top stops 0.5 mm above the 170HX vent window (top 8 mm below the bracket top, from the photo). The mouth must leave both 81 × 25 mm vent windows open (`vents`), not the full chassis openings. |
| +y flange edge | 57.0 (on the ledge and screws) | **50.19** | 0.5 mm under the ledge underside (y 50.69). |
| Gasket groove | 6.4 × 1.2, lip 1.2 | **3.0 × 1.2, lip 0.8** | Fits under the ledge. The band straddles the chassis-opening tops (y 45.65…48.65 vs 47.53), pressing the plate-to-panel slits there shut. |
| Fan axis y | −2.83 (window centre) | **−17.4** (10.8 below the mouth centre) | The fan bore top (41.0) is 3.85 mm below the mouth top, so the top wall leans in and passes under the slot-screw tips. |
| Loft easing | smoothstep | near-linear ramp (`geometry.ramp`, e = 0.08) | The top wall starts leaning right at the flange. Steepest air wall: 31.7° on the corner diagonal (v1: 46°). |
| Flange fillet | 3.5 mm | **1.5 mm** | A 3.5 mm fillet reaches the screw tips. |
| −y flange overlap | 16 | **20** | The lowered fan plate's ears and their 45° chamfers stand on the flange (no slicer support). |
| Mounts, cable notch | y from the fan axis | y from the mouth centre | Same as v1 when the fan is centred. |

v1's code path is unchanged: the released v1 STL still matches the build byte for byte.

## Fit against the case hardware

The collector sits with its flange face on the panel's outer face, 0.8 mm beyond the bracket plane. `inlet_z` stays on the bracket plane (z = L + 267), the CFD convention. Numbers below are from `fit_check(COLLECTOR_V2, V27, CASE_COVERED)`, with clearances from dense surface samples (about ±0.2 mm).

| Part | Intersection | Min. clearance |
|---|---|---|
| Slot ledge (0.8 mm, 12 mm deep, sharp fold) | 0 | 0.5 mm (inside fold radius 0.3 / 0.5 mm: 0.22 / 0.05 mm; 0.8 / 1.2 mm: 0.7 / 6.4 mm³ overlap) |
| Bracket plates and tabs, middle blank, side covers | 0 | 0.8 mm (the panel thickness) |
| Slot-screw heads (6-32 pan, Ø6.86 × 2.46) | 0 | 2.16 mm |
| Slot-screw tips (6-32 × 1/4", 4.69 mm under the ledge) | 0 | **0.37 mm** (3/16" screws: 1.03 mm) |
| Bezel Torx heads (photo estimate: Ø4, 0.2 mm past the panel face) | 2.1 mm³ | — |

- **Sweep:** the intersection stays 0 across ledge depths of 10, 12 and 15 mm, with or without a 4 mm down-lip, with pan or thumb screws, and with 1/4" or 3/16" screws. Hard-part clearance is about 0.4–0.5 mm.
- **Panel-to-ledge fold:** the model's fold is a sharp corner. A press-brake fold has an inside radius of about one sheet thickness, and that radius sits right at the flange's +y edge (y 50.19). With a radius of 0.8 mm or more, the flange edge rides up on the bend and the top of the flange lifts off the panel. If yours is that round, lower `flange_overlap[2]`: 4.74 clears a 0.8 mm radius by 0.3 mm, but leaves only a 0.94 mm outer land beside the groove. The gauge shows it: it won't lie flat under the ledge.
- **Screw access:** every one of the 7 slot screws (cards A and B, three blanks) is outside the case. Their axes are 5.58 mm out from the panel face. A Ø7 mm driver column (pan heads) or a Ø20 mm finger column (thumb screws) above each head is completely free of the collector and the fan. **A card can be unscrewed with the collector in place.** Pulling the card out still needs the collector off, because the mouth covers the bracket.
- **Gasket path (centreline, 419.5 mm):** 353.5 mm runs on flush panel. That is the ribs outside slots ±2 on the x sides, the panel below the openings, and the strip above the opening tops. The other 66.0 mm runs on the recessed bracket and blank plates where the band crosses the opening tops, with ten 0.8 mm steps. Nothing is over an open hole, the ledge zone, or off the panel.
- **Magnets:** the lower pair (y −64.3) sits on flush panel. The other four (x ±60.55) sit entirely on the side slots' covers, 0.8 mm behind the panel face. Expect roughly half the zero-gap pull there, and nothing if those slots are open.
- **Vent windows:** both are fully inside the mouth. In each, 572.7 mm² (28 %) lies behind the 7.07 mm panel rib between the card's two CEM-minimum openings. A real case's openings may be wider; measure. This is a CFD question; the CFD's window is fully open.

## Bypass: air that reaches the collector without crossing the fins

The operating point is the v27 push-pull CFD (`runs/v27-pushpull`, `pressure_breakdown`): plenum static −24.6 Pa (bracketDown) against the case air, and 14.46 L/s through the fins. The two vent windows are 2 × 2025 = 4050 mm².

The model is `bypass_leaks` in `duct/cad/hardware.py`:
- **Slits:** laminar flow through a slit plus 1.5 dynamic heads of entry and exit loss.
- **Effective area:** the ideal orifice area that would pass the same flow.
- **Bypass fraction:** leak / (fin flow + leak), at fixed suction.

| Path | Leak at 24.6 Pa | Eff. area | vs windows | Bypass (24.6 Pa) | Bypass (10 Pa) |
|---|---|---|---|---|---|
| Plate-to-panel slits, 0.1 mm gap | 0.03 L/s | 4 mm² | 0.1 % | 0.2 % | 0.1 % |
| — 0.3 mm gap | 0.53 L/s | 82 mm² | 2.0 % | **3.5 %** | 1.7 % |
| — 0.5 mm gap | 1.32 L/s | 205 mm² | 5.1 % | 8.3 % | 4.8 % |
| Vented middle blank (400 mm² of holes, Cd 0.6) | 1.54 L/s | 240 mm² | 5.9 % | **9.6 %** | 6.4 % |
| **No middle blank** (open slot, 1,309 mm² inside the loop, Cd 0.6) | 5.03 L/s | 786 mm² | 19.4 % | **25.8 %** | 18.2 % |
| Gasket, 0.05 mm average gap over 419 mm | < 0.01 L/s | 0.3 mm² | — | 0.01 % | — |
| Gasket over the ten 0.8 mm steps | 0.01 L/s | 1.7 mm² | — | 0.08 % | — |

- **Slits:** the bracket and cover plates rest against the panel's inner face but are not sealed to it. Every chassis-opening edge inside the gasket loop leaks across the plate's overlap: 2.6 mm on the sides to the 1.9 mm gap between neighbouring brackets, and 7.2–7.4 mm at the bottom to the plate's lower end. In v2 that is six side edges of 98.8 mm and five bottom edges of 13.25 mm, 659 mm in all. Edges between one bracket's two openings stay inside the plenum. The top edges are under the gasket band. No spec gives the gap; 0.3 mm is a guess for a bracket held at its top screw and bottom tongue.
- **What the gasket must do:** form a closed loop on steel all round. That means the ribs outside slots ±2, the panel below the openings, and, at the top, the 3.2 mm strip between the opening tops and the ledge, crossing onto the bracket plates. Use **closed-cell** foam (EPDM or neoprene sponge), 3 mm wide and at least 3 mm thick, so it fills the 0.8 mm recess where it crosses the plates. Open-cell foam leaks through its body; that leak isn't quantified here.
- **Extending or reshaping the flange can't close the side and bottom slits.** They lie at every opening edge inside any loop that encloses the vent windows, and the gasket can only press shut the top ones. It already does that in v2. If your brackets stand off the panel (a 0.3 mm gap costs about 3.5 %), run aluminium tape along the vertical and bottom edges of the five openings inside the mouth, bridging plate to panel, before fitting the collector.
- **The middle slot must be closed with a solid blank**, or taped. With no blank, about a quarter of the flow is case air. A vented blank still lets through about 10 % of the fin flow. v3 avoids both.

## Hardware assumptions (`duct/cad/hardware.py`)

| Quantity | Value | Source | Measure? |
|---|---|---|---|
| Bracket plane | z = chamber length + 267 (V27: 337, V28: 329) | `DomainParams.card_envelope`; PB-10577: 267.70 mm card, 268.60 mm with bracket | no |
| Bracket sheet | 0.86 mm | CEM Fig 9-5 note 1 | no |
| Dual bracket | 38.74 wide, 112.93 to the tongue base, tongues 4.11–14.30 and 24.43–34.62 from the edge | CEM Fig 9-13 | no |
| Top tab | reaches 11.43 out from the plate's inner face; U-slots Ø4.42, centres 7.24 from the plate, 12.45 and 32.77 from the edge | CEM Fig 9-5 / 9-13 | which edge the slots measure from (mirroring unresolved, ±6.5 mm in x) |
| Chassis opening | 13.25 × 100.71 min, from the PCB plane, top 4.82 below the bracket top | CEM Fig 9-22 | **yes**: real width and position |
| Rear panel | 0.8 mm steel | assumption (SECC 0.6–1.0) | **yes** |
| Slot ledge | 0.8 mm, 12 mm deep, under the tabs; optional lips | assumption (case-specific) | **yes**: depth, any lip or cover bar |
| Slot screws | 6-32 × 1/4" pan head Ø6.86 × 2.46; thumb Ø12 × 8 as a variant | ASME B18.6.3; retail | **yes**: length (tip depth under the ledge) |
| 170HX vent window | 81 × 25, top 8 below the bracket top, centred on the card | user photo (±10 %) | **yes** |
| Window bezel | 4 mm wide, 0.8 mm, on the card side; 4 Torx heads Ø4, 1.0 mm above the plate | user photo, unmeasured | **yes**: whether the heads stand proud of the panel face |

## Measure before printing

1. Gauge: it must lie flat under the ledge. Both bracket vent windows (inner rectangles) must be inside the mouth outline, and the ▲ arrow points at the bracket tops.
2. Slot screws: how far each tip pokes below the ledge (v2 allows up to about 5 mm), and whether a retention bar or cover plate sits over the screws.
3. The strip between the opening tops and the ledge underside (modelled 3.2 mm): the gasket band needs it. Also check that the fold into the ledge is sharp (inside radius ≤ 0.5 mm), i.e. that the gauge lies flat right up to the ledge.
4. Torx heads on the 170HX bracket: if they stand more than about 0.2 mm proud of the panel face, the top flange land rests on them.
5. Whether the side slots (±3) have steel covers fitted; four of the six magnets rely on them.

## Printability and print

All printability gates pass with no override: unsupported overhang, solid regions, seal, seat coverage, and the slicer support gate (`printability.run_gates` via `release_collector`; `checks.json` → `printability`).

P1S / 0.4 mm / 0.28 mm PETG: 110.4 min / 48.8 g without supports. The automatic-supports slice is 117.4 min / 50.1 g and passes the slicer support gate. Fit gauge: 20.8 min / 3.8 g. Print flange down; the STL is already oriented, with z = duct z − 337.

Material: 50.5 cm³. Air volume: 273.4 cm³. Mesh: one watertight body, 26,936 triangles. Wall 1.199–1.228 mm (p0–p95, plain skin). Fan holes measured from the STL: 105.000 × 105.000 mm, at (±52.5, 35.1 / −69.9). The top two pilots sit beside the mouth and stop at its wall. Areas: mouth 10,444 mm², fan bore 10,715 mm² (1.03 × mouth), annulus 8,672 mm².

`checks.json` naming: `openings_blocked_mm2` and `openings_outside_mouth_mm2` are measured against `must_open`, which in v2 is the two vent windows, not the chassis openings.

## Risks

- The fan frame reaches y −77.4 and the flange y −78.0, 22 mm past the system-board plane toward the motherboard tray side. Check that the case's rear face and anything behind it leave room.
- Screw-tip clearance is 0.37 mm (±0.2 mm sampling) with 1/4" screws; the gauge can't check it. Look at the tips under the ledge.
- Ledge-clearance margin is 0.5 mm against a sharp fold and nothing against a 0.5 mm bend radius (see above).
- Window position: the mouth top has 0.5 mm over the photo-estimated vent top. A window 0.8 mm higher would lose about 15 mm² (0.4 %).
- Not simulated: no CFD has been run with the v2 collector or with any bypass leaks.

Files: `dual-170hx-collector-v2.stl`, `dual-170hx-collector-v2-fit-gauge.stl`, `checks.json`, `slicer-checks.json`. Renders: `runs/hardware/`. Source: `duct/cad/exhaust.py`, `duct/cad/hardware.py`, `COLLECTOR_V2` in `duct/params.py`, `tests/test_hardware.py`.
