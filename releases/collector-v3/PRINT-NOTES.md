# DUAL CMP 170HX — exhaust collector v3 (push-pull, sealed per card)

> **Untested.** No exhaust collector has been printed or fitted to a real case yet. The fit, the seal and the airflow gain are model results only. Print the fit gauge first, check every measurement below, and report what you find.

> **Case update:** the author's case has **no slot covers at all**. Slots −3, 0 and +3 are all open (`CASE`; the old covered case is `CASE_COVERED`). v3's loops keep all three outside: 0 bypass from them, with 5.0 mm of foam on steel before the nearest open slot. Its flange still lies over all three, unsealed, and four of its six magnets have nothing to hold (see *Fit*). The constraints for the next design are in `docs/collector-constraints.md`.

v3 fixes two problems with v2. First, in the author's case the slot between the two cards is open, and v2's single gasket loop enclosed it, so the fan pulled case air through it: about a quarter of its flow (see the v2 PRINT-NOTES). Second, v2's one big plenum added little over a bare fan on the panel. v3 gives **each card its own mouth and its own gasket loop**. Each loop sits on the panel ribs either side of that card's two chassis openings, so the middle slot and the outer slots stay under the solid flange, outside the plenum, whatever they hold (open, blank, vented). A 1.2 mm splitter fin stands on the flange web over the middle slot and divides the plenum per card up to 4 mm below the fan plate. The fan axis is on the fin, so the fin ends behind the hub. The fan also sits 8 mm higher than v2's.

Unchanged from v2: the hardware clearances under the slot ledge, reachable slot screws, 1.2 mm walls, magnets, print orientation, and every printability gate with no override.

**Nothing has been measured or fitted.** Print the fit gauge first (`dual-170hx-collector-v3-fit-gauge.stl`, 4.2 g). It must lie flat under the slot ledge, and each card's vent windows must show inside its own mouth outline.

## What changed from v2

| | v2 | v3 | Why |
|---|---|---|---|
| Mouths | one, x −50.8…50.8, y −58.0…44.85 | **two**: card A x −47.05…−12.48, card B x 13.92…48.49; both y −55.18…44.6 | Each spans its card's two chassis openings (CEM minimum) ±0.5 mm. |
| Gasket | one loop around all five slots −2…+2 | **one loop per card**, lip 1.535 mm on the sides and bottom, 0.8 mm on top; groove 3.0 × 1.2 | The straight side bands sit on the 7.07 mm ribs: 2.035 mm from the openings on each side. |
| Middle slot | inside the loop: needs a solid blank | **under the flange web**, outside both loops | Case air can't get in, whatever the slot holds. |
| Plenum | one loft | one loft from both mouths, with a **1.2 mm splitter fin** on the flange web at x = 0.72 up to z 18.6 (6.4 mm below the fan face) | Each card's air stays on its own side until the fan. |
| Fan axis | (0, −17.4) | **(0.72, −9.125)**, on the fin | The fin ends behind the hub. The frame bottom is 13.3 mm below the board plane (v2: 21.5). |
| Top wall | leans in all the way | mouth top 0.25 mm above the vent window; then a **1 mm dip** within 1.7 mm of the flange; level until 14 mm out, then rising to the bore | Clears the slot-screw tips just past the flange, and a ledge with a downturned lip. |
| Plenum depth | 25 | 25 (**v3L: 45**, a parameter: `plenum_depth`) | See *Depth variants*. |

The v1 and v2 code paths are unchanged. Both released STLs still match their builds byte for byte.

## Gasket loops on the ribs (`gasket_band`, `fit_check`)

Render: `runs/hardware/v3-gasket-loops-on-ribs.png`.

- **Side bands:** each runs on a rib, 2.035 mm clear of the opening edge on each side (CEM-minimum openings). There is 0 mm² of groove over any chassis opening.
- **Bottom band:** 3.5 mm below the opening bottoms on the straight run; 1.97 mm at the corners.
- **Top band:** y 45.4…48.4. It straddles the card's own opening tops (47.53) onto the recessed bracket plate, 0.8 mm behind the panel face: 114 mm² in total over steel, 4 steps per loop. That presses the plate-to-panel slits shut along the top, as in v2.
- **Open holes:** the groove covers 0 mm² of open hole anywhere. The nearest is the vent-window top, 1.05 mm inside the top band.
- **Centreline:** 565 mm in all, 513 mm on flush panel and 52 mm on the recessed bracket plates. Nothing is over the ledge, off the panel, or over an open hole.

**If your openings are wider than the CEM minimum**, the side bands lose margin one for one. At more than 2 mm extra per side, a band starts to cross an opening; measure them (gauge).

## Fit against the case hardware

`fit_check(COLLECTOR_V3, V27)`, with the middle slot open (the author's case):

| Part | Intersection | Min. clearance |
|---|---|---|
| Slot ledge (0.8 mm, 12 mm deep, sharp fold) | 0 | 0.5–0.75 mm, sampling-dependent; the flange top edge is at y 49.94, 0.75 mm under the ledge (0.5 mm fold radius: 0.26 mm) |
| Bracket plates, side covers | 0 | 0.8 mm (the panel thickness) |
| Slot-screw heads | 0 | 2.16 mm |
| Slot-screw tips (6-32 × 1/4") | 0 | **0.32–0.36 mm** (±0.2 mm sampling; v2: 0.37) |
| Bezel Torx heads (photo estimate) | 2.0 mm³ | — (as v2) |

- **Sweep:** the intersection stays 0 with pan or thumb screws, a 15 mm ledge with a 4 mm down-lip, a 0.5 mm fold radius, and with or without a middle blank.
- **Screw access:** every slot screw is reachable with the collector fitted: cards A and B, the side covers, and a middle blank if fitted. Each one's access column is 0 mm³ blocked.
- **Magnets: only 2 of 6 hold in the author's case.** The lower pair (y −63.0) sits on flush panel. The other four (x ±61.3, y −15.3 / 24.7) sit over slots ±3, which are **open** in the author's case (no slot covers). They hold nothing there. Fit covers in slots ±3, or hold the collector some other way; the next design moves the mounts onto flush steel (`docs/collector-constraints.md`, A5).
- **Vent windows:** fully inside the mouths. `must_open` is each window ∩ chassis opening. The rest of each window is behind the rib in any case.

## Bypass (`bypass_leaks`, −24.6 Pa plenum suction, 14.46 L/s through the fins)

| Path | Leak | Eff. area | Bypass (24.6 Pa) | Bypass (10 Pa) |
|---|---|---|---|---|
| Plate-to-panel slits, 0.1 mm gap | 0.02 L/s | 3 mm² | 0.1 % | 0.05 % |
| — 0.3 mm gap | 0.35 L/s | 55 mm² | **2.4 %** | 1.1 % |
| — 0.5 mm gap | 0.88 L/s | 138 mm² | 5.8 % | 3.3 % |
| Open slots −3, 0, +3 (or any cover, vented or solid) | 0 | 0 | **0** | 0 |
| Gasket, 0.05 mm average gap | < 0.01 L/s | 0.4 mm² | 0.02 % | — |
| Gasket over the eight 0.8 mm steps | 0.01 L/s | 1.4 mm² | 0.06 % | — |

v2 with the middle slot open: 5.03 L/s, 25.8 %. The remaining slits are the side edges of the four card openings (98 mm each) and their bottoms (13.25 mm each), 445 mm in all (v2: 659 mm with a blank). If the brackets stand off the panel, tape those edges as in v2.

## Splitter fin

- **Shape:** 1.2 mm thick, rooted 0.5 mm into the flange web. It runs from the flange (z 2.8) to 4 mm below the fan plate (z 18.6), centred at x 0.72 over the middle slot.
- **End gaps:** its ends stay 2.0 mm off the plenum's top and bottom walls and follow their slope. A T-junction of two 1.2 mm walls fails the solid-regions gate, so the ends are left free.
- **Cross-flow:** the channels are therefore not fully separate. The two end gaps total about 63 mm² over the fin's height, against 6,888 mm² of mouth.
- **Flow:** both channels end in one round passage 4 mm before the blades. Air from each card crosses the 26 mm flange web between the mouths, a backward-facing step over the middle slot, before the fin takes over.
- **Why not two separate lofts:** fully separate channel lofts that merge at the bore were tried first. Across many iterations they kept failing the overhang, solid-region and seal gates at the web tips under the bore.
- **CFD:** `build_collector(c).inner` includes the fin as a cut-out, so the CFD sees it.

## Depth variants and fan position

| Variant | Plenum | Fan axis | Frame bottom below the board plane | Material | Air | Slicer (auto supports) | Gates |
|---|---|---|---|---|---|---|---|
| v2 | 25 | (0, −17.4) | 21.5 mm | 50.5 cm³ | 273 cm³ | 117 min / 50.1 g | pass |
| **v3** | 25 | (0.72, −9.125) | **13.3 mm** | 59.2 cm³ | 250 cm³ | 135 min / 60.0 g | **pass** |
| v3L (`COLLECTOR_V3L`, not released) | 45 | (0.72, −5.125) | **9.3 mm** | 73.2 cm³ | 454 cm³ | 162 min / 74.7 g | pass (scratch release, 0 g unexplained support) |
| bare fan baseline (`bare_fan_air`, CFD only) | 2 (panel + gasket) | (0.72, −14.5) | 18.6 mm | — | 26.8 cm³ | — | — |

**v3L** is the same design, 20 mm deeper. The longer plenum lets the fan sit 4 mm higher still. The fin is 20 mm taller, so each card's air stays separate longer, and the loft walls are gentler (steepest air wall 41° vs 46°). It costs 20 mm more protrusion: 70 mm behind the rear panel with the fan.

**Bare fan baseline:** the fan frame gasketed straight onto the panel, with no plenum. The 116 mm gasket square encloses slots −2…+2, including the middle slot. Its top is held at y 45.5, under the screw tips. It is CFD geometry only, the comparison for "just stick the fan outside the case".

## Printability and print

- **Gates:** all pass with no override (`release_collector`; `checks.json` → `printability`): unsupported overhang, solid regions, seal, seat coverage, and the slicer support gate. Unexplained slicer support is 0 g. Designed bridges total 1.67 g: the gasket groove roof, the fan-screw pilot exits and the magnet pocket ceilings, as in v2.
- **Print (P1S / 0.4 mm / 0.28 mm PETG):** 127.2 min / 58.4 g with no supports. The automatic-supports slice is 135.0 min / 60.0 g. Fit gauge: 22.4 min / 4.2 g. Print flange down; the STL is already oriented, with z = duct z − 337.
- **Mesh and walls:** one watertight body, 42,938 triangles. Wall 1.175–1.232 mm (p0–p95, plain skin, excluding the fin). Steepest air wall 46.4°, on 2.2 mm² at the lower corner of card A's mouth (gates pass).
- **Fan holes and areas:** fan holes measured from the STL are 105.000 × 105.000 mm, at (0.72 ± 52.5, −9.125 ± 52.5). Mouths total 6,888 mm²; the fan bore is 10,715 mm² (1.56 × mouths).

## CFD contract

- **Same as v1 and v2:** `build_collector(COLLECTOR_V3).inner` is the air volume, starting at z = `inlet_z`, the bracket plane. Its section there is the two card mouths. The bore is centred on `fan_axis` (0.72, −9.125) at z = `inlet_z + plenum_depth`.
- **Placement:** in the case, the flange sits on the panel's outer face, 0.8 mm past the bracket plane (`hardware.placed`).
- **Middle slot:** with v3, the slot ∩ mouth is empty, so `duct.cfd.collector.middle_slot` adds no case-air patch.
- **Not simulated:** no CFD has been run with v3, v3L or the bare-fan baseline.

## Measure before printing

1. Gauge: it lies flat under the ledge, and each card's vent windows show inside its own mouth outline.
2. The ribs either side of each card: the gasket bands need about 7 mm of flat steel between the openings (CEM minimum: 7.07 mm). Wider openings eat the 2 mm margins.
3. The slot-screw tip depth under the ledge (v3 clears 1/4" 6-32 by 0.32 mm). Also the vent window's top edge: the mouth top has 0.25 mm over the photo estimate (v2: 0.5 mm).
4. As v2: the ledge fold radius, Torx heads, and whether the side covers are fitted (magnets).

## Risks

- **Side margins:** the gasket side margins (2.035 mm) assume CEM-minimum openings.
- **Mouth top:** 0.25 mm over the photo-estimated vent top. A window 0.5 mm higher loses about 4.5 mm² of its open strips per card (0.25 mm × 17.9 mm).
- **Cross-flow:** the fin's end gaps (63 mm²) and the 6.4 mm above it let the two cards' streams mix before the blades. That is by design (one fan); the CFD will show whether it matters.
- **Fan position:** the fan frame still reaches 13.3 mm past the board plane toward the motherboard-tray side; check room behind the case.

Files: `dual-170hx-collector-v3.stl`, `dual-170hx-collector-v3-fit-gauge.stl`, `checks.json`, `slicer-checks.json`. Renders: `runs/hardware/v3-*.png` and `v3l-*.png` (`runs/hardware/render_v3.py`). Source: `duct/cad/exhaust.py` (`split_section`, `splitter_fin`, `gasket_loops`, `bare_fan_air`), `duct/cad/hardware.py` (`gasket_band`, `CaseParams.covers`, `CASE_COVERED`), `COLLECTOR_V3` / `COLLECTOR_V3L` in `duct/params.py`, `tests/test_hardware.py`.
