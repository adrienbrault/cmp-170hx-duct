# DUAL CMP 170HX — exhaust collector v4, 5-slot layout (concept A)

> **Untested.** No exhaust collector has been printed or fitted to a real case yet. The fit, the seal and the airflow gain are model results only. Print the fit gauge first, check every measurement below, and report what you find.

**Layout: 5-slot.** This is for the V29 duct: two dual-slot cards 60.96 mm apart (3-slot pitch), with one empty slot between them. Slots −3 … +3. The cards use −2/−1 and +1/+2, and slots −3, 0 and +3 are open (no covers in the author's case). For adjacent cards (A29, 4-slot) use `releases/collector-v4-4slot/`; the two parts are not interchangeable.

**Mounting: 7 magnets, 10 × 3 mm N52 discs** (2.3 kg pull each at zero gap). Glue them into the pockets on the case face, all with the same pole facing out. Every magnet sits on flush panel steel, whether or not slot covers are fitted.

**Nothing has been measured or fitted.** Print the fit gauge first (`dual-170hx-collector-v4-5slot-fit-gauge.stl`, 5.0 g, 26 min) and go through *Measure before printing*.

Source: `COLLECTOR_V4A.for_duct(V29)` (`duct/params.py`), `duct/cad/exhaust.py`. Plan: `docs/collector-v4-plan.md` (revision after the curves requirement).

## What v4 is

v4 keeps v3's per-card seal: one gasket loop per card on the panel ribs, so no open slot is ever inside a loop. Around it, everything is reshaped for fan-inlet uniformity, with curves instead of a box, and every curve prints flange-down within 45°.

- **Fan position:** the plenum is 45 mm deep, and the fan's frame bottom sits on the system-board plane (y −55.86): fan axis (0.72, 4.14). v3's frame was 13.3 mm lower; the frame now reaches 0 mm past the board plane. The fan stands 70 mm behind the rear panel (45 + 25 frame), the limit.
- **One mouth per chassis opening (4):** each is the opening ± 0.5 mm in x, at y −53.68 … 44.6: x −47.05…−32.80, −26.73…−12.48, 13.92…28.17 and 34.24…48.49.
- **Rib fins:** one per card, standing on the 6.07 mm flange strip over the rib between that card's two openings. Each feeds one channel per opening up to 32 mm from the panel, then leans 6 mm outward toward the bore's edge.
- **Centre fin:** stands on the 26.4 mm web between the cards (over slot 0, as v3), up to 6.4 mm below the fan face, on the fan axis.
- **Open slots stay open:** the flange reaches 15 mm past slots ±3, with a window (opening + 1 mm, corners r 4) over each, so they vent to the room. The fan cable drops through a window; there is no cable notch.
- **Magnets on flush steel:** two in each outer column, beyond the open slots, and three in a row below the openings.

## The curves, with their numbers

| Curve | Value | Notes |
|---|---|---|
| Inlet lip (sides and bottom of each outer mouth edge) | rolls out 2.5 mm, from 1 mm above the panel face to ≈ 7 mm, end radius ≈ 2.5 | None on the top edge: the slot-screw tips are at y 46.0, 3.8–7.3 mm out, and the air top stays ≤ 44.6. **Shape only, ≈ 0 Pa:** the orifice is the steel opening edge, not the mouth. |
| Mouth corners | bottom 6 (per-opening mouths), outer top 4, inner top 5, rib-side top 1.2 | The plenum section corners start at 12 (bottom) / 5 / 4 and grow to 12 by mid-depth. The disc around the fan axis then rounds them onto the bore. |
| Fin roots | rib fins: S-curve from the mouth edges into the 1.2 mm fin over 5.9 mm, minimum radius 2.4. Centre fin: quarter-round fillet r 2.4. | The 26.4 mm web's top edges get a 2.4 mm quarter round at the inner mouths. |
| Fin tops | full round, r 0.6 | |
| Walls from mouth to bore | eased ramp (e 0.25); x walls ≤ 38.8°, bottom ≤ 37.2° | |
| Top wall | holds 1 mm under the mouth top to 15 mm out (ledge lip), then rises 18.9 mm at 34.5° mean, 40.6° peak (e 0.2) | |
| Bell into the bore | the ramp's end easing: the walls arrive at the plate at 0.2–4.7° from vertical, then 2.4 mm of straight Ø116.8 bore through the plate | No corner at the blade tips. |
| Outside | uniform 1.2 mm shell, so every inside curve shows outside | Body–flange fillet 3.7 (1.5 on the +y side, under the screw tips); flange corners r 15; window corners r 4; 1 mm round on the flange's outer top edge (the window edges stay square: the strip above each window is 1.4 mm wide); fan-plate corners r 5 (as the push duct); rounded magnet bosses. |

Correction (Codex review, 2026-10): the 40.6° above came from the section's bounding-box slopes, which miss a corner moving in x and y at once. Measured from triangle normals, the steepest plenum air wall is 47.8° (`checks.json` → `v4.plenum_wall_deg`), above the 45° design limit: a few up-facing faces at the bottom corners (10 mm², at the flange-top level inside the bottom fillet). These faces look up, so the air widens there and the inner skin supports itself. The overhanging air walls (faces looking down) peak at 40.0°, and no exterior face in the plenum band exceeds 45° outside the ear-chamfer blocks. The overhang gate and the slicer pass. The collector STL is unchanged; this release is for the CEM flat-panel case, not the Fractal recess.

## Seal and open slots (`gasket_band`, `bypass_leaks`, `open_slot_vent_area`)

- **Gasket loops:** as v3. One loop per card, lip 1.535 mm on the sides and bottom and 0.8 mm on top; groove 3.0 × 1.2 mm, with a 1.6 mm roof. Side bands are 2.035 mm clear of the openings on both sides. 0 mm² of groove over any open hole; 114 mm² over recessed bracket plate along the tops, as in v3.
- **Open slots:** none inside a loop. The foam has 5.0 mm of land on steel before the nearest open slot.
  - **Slots −3 and +3:** 1,334.2 of 1,334.4 mm² open at the panel face (99.98 %) under the flange windows.
  - **Slot 0 (between the cards):** under the flange web, outside both loops, as in v3. It cannot vent: the plenum is above it, and a window there would let case air into the plenum.
- **Bypass at −24.6 Pa:**
  - Plate-to-panel slits: 0.35 L/s (2.4 %) at a 0.3 mm gap.
  - Open slots: 0.
  - Gasket gaps and the eight panel steps: < 0.01 L/s each.
- **CFD:** `duct.cfd.collector.open_slots` finds no open slot under the mouths.

## Fit against the case hardware (`fit_check`, `fit_sweep`)

| Part | Intersection | Min. clearance |
|---|---|---|
| Slot ledge | 0 | 0.75 mm (flange top edge y 49.94) |
| Bracket plates | 0 | 0.8 mm (panel thickness) |
| Slot-screw heads | 0 | 2.46 mm |
| Slot-screw tips (6-32 × 1/4") | 0 | 0.37 mm |

- **Sweep:** across 24 case variants (ledge 10/12/15 mm, a 4 mm down-lip, pan or thumb screws, 1/4" or 3/16" screws), the intersection stays 0 and the minimum clearance is 0.40 mm.
- **Screw access:** every slot screw's driver or finger column is 0 mm³ blocked, with pan or thumb screws, and with or without covers.
- **Magnets:** all 7 are 100 % on flush panel, under `CASE` and `CASE.covered()`.
  - Columns at x −74.27 and +75.71, y −30 and +35. They are 7.4 mm past the outer open slots' edges, and each pocket keeps a 1.2 mm wall to its window.
  - Row at x −35, 0 and +35, y −65.
- **Vent windows:** the live part (outside the panel ribs) is entirely inside the mouths: 0.001 mm² outside, which is rounding.

## Fins

| Fin | x | Top (from the panel) | Root | Lean | Ends |
|---|---|---|---|---|---|
| centre | 0.72 (fan axis) | 38.6 mm (6.4 below the fan face) | fillet r 2.4 | 0 | 2 mm off the top and bottom walls |
| rib A | −29.76 | 32.0 mm | S-curve 5.9 mm, r ≥ 2.4 | 6 mm outward (steepest 21°) | 2 mm off the walls |
| rib B | 31.2 | 32.0 mm | same | 6 mm outward | 2 mm off the walls |

All fins are 1.2 mm thick above their roots, and free at both ends (no T-junction with the walls). The CFD sees them: `build_collector(c).inner` is the air minus the fins.

## Printability and print

- **Gates:** all pass with no override: unsupported overhang, solid regions, seal, seat coverage, and the slicer support gate.
  - **Slicer support:** 0 g unexplained. The 1.32 g that remains is designed bridges: the gasket groove roof and the magnet pocket ceilings.
  - **Solid regions:** the designed solids are the flange, its fillet, the fan plate and its ear chamfer blocks, and 0.2 cm³ at each rib-fin root (the S-curve widening into the 6 mm strip).
- **Fan-screw pilots:** 3.4 mm, blind, 6.4 mm deep from the fan face. They stay inside the ear chamfers, so no crescent breaks out of the chamfer's underside. Choose fan screws that end 4–6 mm past the fan's mounting face: no more than 6.4 mm.
- **Print (P1S / 0.4 mm / 0.28 mm PETG):** flange down, as oriented (STL z = duct z − 337).
  - No supports: 189 min / 87.8 g.
  - Automatic supports: 195 min / 89.1 g.
- **Mesh and walls:** one watertight body, 66,902 triangles. Wall 1.212 / 1.222 / 1.254 mm (p5 / p50 / p95 of the plain skin). Fan holes measure 105.000 × 105.000 mm.
- **Areas:** the mouths total 5,521 mm², against a fan annulus of 8,672 mm² and a bore of 10,715 mm².

## CFD contract

- **Air volume:** `build_collector(COLLECTOR_V4A.for_duct(V29)).inner` is genus 0, from z = `inlet_z` (the bracket plane), where its section is the four mouths.
- **Bore:** centred on `fan_axis` (0.72, 4.14) at `inlet_z + 45`.
- **Placement:** in the case, the flange sits on the panel's outer face, 0.8 mm further out (`hardware.placed`).
- **CFD kinds:** `v4a` / `v4b`.
- **Variants:** sliced and gated in scratch only, all passing: `COLLECTOR_V4B`, `COLLECTOR_V4A_LEAN0`, `COLLECTOR_V4A_D40` (frame 4.8 mm under the board plane) and `COLLECTOR_V4A_FILL`.

## Measure before printing

1. **Gauge:** it lies flat under the slot ledge; each chassis opening shows inside its own mouth outline; slots ±3 show inside the flange windows.
2. **Flush steel beyond the outermost openings:** the magnet columns need ≥ 13.8 mm of flat panel past slots ±3 (bosses out to x −80.6 and +82.1). The flange reaches 15 mm past them.
3. **Flat panel below the openings:** the magnet row sits at y −65, 9.1 mm below the board plane, and the flange reaches y −73.7 (17.8 mm below it). Check that this is flat panel, with no feet, standoffs or I/O there.
4. **The ribs either side of each card:** they need about 7 mm of flat steel (CEM minimum 7.07 mm), as v3.
5. **Behind the case:** the fan's back face is 70 mm behind the rear panel. The frame top (y 64.1) is 13.5 mm above the slot ledge's underside, at 42.6–70 mm out; check there is nothing above.
6. **Slot-screw tip depth under the ledge** (0.37 mm with 1/4" 6-32), and the vent-window top (the mouth top is 0.25 mm above the photo estimate), as v3.
7. **Opening widths:** CEM minimum is assumed. Wider openings eat the rib margins and the 1 mm window margin.

## Deviations from the plan, and trade-offs

- **Magnet row at y −65, not −61.5.**
  - At −61.5 the pockets would cut into the gasket grooves (groove bottom −58.2, pocket + 0.8 mm keep-out r 5.95).
  - The row needs y ≤ −64.2, so the flange's −y edge moves to −73.7, 17.8 mm below the board plane.
- **Magnet columns at x −74.27 / +75.71, not ±75.2.** They are placed 7.4 mm from each open slot's edge, so each pocket keeps a 1.2 mm wall to the window (opening + 1 mm). The layout is asymmetric because the openings are.
- **Fan-screw pilots are blind (6.4 mm).** With r 5 plate corners, the through pilots broke out of the 45° chamfer into small unsupported specks. The slicer's no-support pass flagged them as floating.
- **Slot 0 stays covered** by the flange web (see *Seal*).
- **Web fill is not in this release.** `COLLECTOR_V4A_FILL` (5-slot only: inner walls lean ≤ 30° into the centre fin, merge radius ≥ 14) passes every gate. But it adds 40 cm³ of solid ridge (127 vs 87.5 cm³) and 19 min of print. Wait for the CFD (R7) before adopting it.
- **Material:** v4A is 87 cm³ (v3: 59). The 20 mm extra depth and the rib fins account for most of it; B is 75 cm³.
- **Lip:** it costs nothing measurable and gains nothing measurable at the inlet. It is there because the author asked for curves, and it sets the body–flange fillet (3.7 mm).

Files: `dual-170hx-collector-v4-5slot.stl`, `dual-170hx-collector-v4-5slot-fit-gauge.stl`, `checks.json`, `slicer-checks.json`. Renders: `runs/hardware/v4-5slot-*.png` (`runs/hardware/render_v4.py`). Tests: `tests/test_collector_v4.py`.
