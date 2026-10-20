# Exhaust collector: design constraints and objectives

This is the brief that every pull-side collector design (v4 and later) is generated from and judged against, for **both slot layouts** (see *Two slot layouts*). Part A lists hard limits; a design that breaks one is rejected, whatever its CFD. Part B lists the objectives the CFD ranks the remaining designs on.

## Frame and sources

- **Frame:** the duct frame. x runs across the cards (card A at −x, card B at +x). +y points to the card's top edge (the bracket tab end). z runs along the card axis.
- **Bracket plane:** z_b = chamber length + 267 (V27: 337; V28, V29 and A29: 329). `CollectorParams.for_duct(g)` sets `inlet_z` and `card_pitch` from the duct. The presets keep 337, the released STLs' frame; the STL is in the print frame either way.
- **Rear panel:** 0.8 mm thick, from z_b to z_b + 0.8. The collector's flange lies on its outer face.
- **CFD air volume:** starts at `inlet_z` = z_b (CFD convention). The physical part sits 0.8 mm further out (`hardware.placed`).
- **Sources:**
  - Hardware model: `duct/cad/hardware.py` (`CaseParams`, `BracketParams`), checked with `fit_check`, `gasket_band` and `bypass_leaks`.
  - Numbers marked *assumption* or *photo* are unmeasured. The fit gauge, or measuring the case, settles them.
- **The author's case:** `CASE`, with **no slot covers**. Every slot without a card is open: slots −3, 0 and +3 (5-slot) or −2.5 and +2.5 (4-slot). `CASE_COVERED` (covers in −3, 0 and +3) is the old v1/v2 assumption, kept only for their tests; `case.for_pitch(p).covered()` covers every empty slot of either layout.

## Two slot layouts

The slot layout follows the duct's card pitch (`GeometryParams.pitch`; `params.slot_layout`, `CaseParams.card_pitch`, `build_hardware(g, …)`). Slot positions are counted in 20.32 mm slot pitches from the midpoint between the cards (x = 0). The tables in A2, A4, A5 and A6 below are for the **5-slot** layout; the **4-slot** values are here.

| | 5-slot (V29) | 4-slot (A29) |
|---|---|---|
| Card pitch | 60.96 mm (3 slots, one empty slot between the cards) | 40.64 mm (2 slots, adjacent cards) |
| Card slots | A −2, −1; B +1, +2 | A −1.5, −0.5; B +0.5, +1.5 |
| Open slots (the author's case) | −3, **0**, +3 | −2.5, +2.5 (nothing between the cards) |
| Slot block (window x) | ±50.8 | ±40.64 |
| Board plane y | −55.86 | −55.86 |
| Ledge underside, screw tips, heads (y) | 50.69 / 46.0 / 52.35…54.81 | same |

**4-slot openings** (CEM minimum, 13.25 wide, y −53.18…47.53):

| Slot | x | Holds |
|---|---|---|
| −2.5 | −56.705…−43.455 | **open** |
| −1.5 | −36.385…−23.135 | card A |
| −0.5 | −16.065…−2.815 | card A |
| +0.5 | 4.255…17.505 | card B |
| +1.5 | 24.575…37.825 | card B |
| +2.5 | 44.895…58.145 | **open** |

- **Ribs:** each is 7.07 mm wide: −43.455…−36.385, −23.135…−16.065, **−2.815…4.255** (the only rib between the cards), 17.505…24.575, 37.825…44.895. Flush panel lies beyond ±58.15.
- **Brackets:** A spans x −38.97…−0.23, B 1.67…40.41, with the 1.9 mm gap between them over the central rib.
- **Card slot screws:** x −26.52, −6.2 (A) and 14.12, 34.44 (B), 5.58 mm out from the panel face. Cover screws, if covers are fitted: −46.84 and 54.76.
- **Vent windows:** x −32.82…−7.82 and 7.82…32.82. The strips over openings are −32.82…−23.135, −16.065…−7.82, 7.82…17.505 and 24.575…32.82: the same 2,905 mm² as 5-slot.
- **Seal and bypass:** with no slot between the cards, nothing open lies inside either a single loop around both cards (v2-type) or two per-card loops (v3-type). The per-card loops then share one 3 mm band on the central rib, 2.035 mm from each opening. Leaks are plate slits only: 2.4 % at a 0.3 mm gap. A v2-type single loop's groove runs about 1 mm over slots ±2.5 (2.0 mm foam land), as v2 does over ±3.
- **Fan and hub:** the slot block is 81.3 mm wide, so a 120 mm fan overhangs it by 19 mm a side, onto the open slots ±2.5. The v1–v3 presets don't build at this pitch: their mount pattern lands off the flange. v4 must size its flange and mounts per layout.
  - The hub (Ø51) on the window centre sits on the central rib and shadows both cards' inner vents: 834 mm² of v3's 2,905 mm² of open strips (29 %), against 376 mm² at 5-slot (`collector_checks.hub_shadow.live_vents_under_hub_mm2`).
- **Magnets:** flush steel is below y −53.2, on a rib, or beyond x ±58.15. The v1–v3 magnet x (±61.3) would overlap the open slots' outer edge by about 2 mm.

## A. Hard constraints

### A1. Slot ledge (above the openings, outside the case)
- **Underside:** y = **50.69**. Every part of the collector and fan within the ledge's reach stays at least **0.5 mm** below it. v3's flange top edge is at y 49.94, 0.75 mm clear.
- **Ledge depth:** 12 mm out from the bracket plane (*assumption*). Designs must still clear a **15 mm ledge with a 4 mm downturned lip** at its outer edge. The lip reaches down to y 46.7 at z ≈ 15 from the panel face, so v3's top wall stays level until 14 mm out.
- **Fold radius:** the panel-to-ledge fold may have an inside radius up to **0.5 mm**. A round fold at the flange's +y edge lifts the flange. Keep the flange's top edge ≥ 0.75 mm below the ledge, or the gauge will not lie flat.

### A2. Slot screws (6-32, outside the case, above the openings)
- **Card screws only:** x = −36.68, −16.36 (card A) and 24.28, 44.6 (card B). Their axes are **5.58 mm** out from the panel face. The author's case has no covers, so there are no cover screws. A design must still allow cover screws at x −57.0 / 3.96 / 64.9 in case covers are fitted later.
- **Pan heads:** Ø6.86 × 2.46, sitting on the bracket tabs at y 52.35…54.81. Keep ≥ **1.5 mm** clearance (v2/v3: 2.16).
- **Screw tips (1/4" screws):** they reach down to y **46.0**, between z 3.83 and 7.33 from the panel face (Ø3.51 shank). Keep ≥ **0.2 mm** clearance (v3: 0.32–0.36 mm, ±0.2 mm sampling). Any wall within about 8 mm of the panel face must stay below y ≈ 45.8 under the four screws. A 3/16" screw gives about 1 mm more room.
- **Screwdriver access:** a Ø**7 mm** vertical column above each pan head (Ø**20 mm** for thumb screws), from the head up 80 mm. It must be free of the collector **and the fan**: 0 mm³ blocked. A card must be removable from its bracket with the collector in place.

### A3. Bezel Torx heads (card side)
- **Bezel:** each 170HX vent window has a 4 mm-wide bezel with four Ø4 Torx heads at its corners. The heads stand 1.0 mm off the plate, about **0.2 mm past the panel face** (*photo*, unmeasured).
- **Current fit:** the flange land over them overlaps about 2 mm³ (v2/v3). This is reported, not a hard failure. If they prove proud, relieve the flange there (≥ Ø5, 0.4 mm).

### A4. Chassis openings, ribs and gasket bands
- **Openings:** CEM minimum, 13.25 wide, y −53.18…47.53. Measure them: a real case may be wider, which eats every rib margin below one for one.

  | Slot | x | Holds |
  |---|---|---|
  | −3 | −66.865…−53.615 | **open** |
  | −2 | −46.545…−33.295 | card A |
  | −1 | −26.225…−12.975 | card A |
  | 0 | −5.905…7.345 | **open** (between the cards) |
  | +1 | 14.415…27.665 | card B |
  | +2 | 34.735…47.985 | card B |
  | +3 | 55.055…68.305 | **open** |

- **Ribs:** each is **7.07 mm** wide, between adjacent openings.
  - Rib x ranges: −53.615…−46.545, −33.295…−26.225, −12.975…−5.905, 7.345…14.415, 27.665…34.735, 47.985…55.055.
  - Flush panel: beyond ±68.3, and below y −53.18 (30 mm modelled).
  - Above the openings there is only a **3.16 mm strip** (y 47.53…50.69) before the ledge.
- **Gasket bands:** a 3 mm band centred on a rib leaves **2.035 mm** to each opening. That is the only place a vertical seal fits between a card and an open slot. The top band cannot fit on the 3.16 mm strip. It must straddle the card's opening tops onto the recessed bracket plate, 0.8 mm behind the face: closed-cell foam ≥ 3 mm thick, 4 steps of 0.8 mm per loop.
- **Seal rule:** every gasket loop runs on steel all the way round, with 0 mm² of groove over an open hole (`gasket_band`: `over_open_mm2`, `groove_over_open_slots_mm2`). The foam's land on steel between a loop and any open slot is ≥ the gasket width (v3: 5.0 mm, `foam_land_to_open_slots_mm`; v2: 2.0 mm, with its groove over slots ±3).

### A5. Open slots: −3, 0 and +3 (4-slot: −2.5 and +2.5)
- **Inside a loop:** an open slot inside a gasket loop is an orifice straight from the case air into the plenum, bypassing the fins (`bypass_leaks`).
  - v2 encloses slot 0: 1,309 mm² gives **25.8 %** bypass at −24.6 Pa and 18.2 % at 10 Pa.
  - **No design may enclose an open slot**, unless it ducts that slot on purpose and the CFD scores it.
- **Under the flange:** an open slot under the flange but outside the loops costs no bypass. It does block that slot as a case vent: v3's flange (x ±71.3, y −72.2…49.9) lies over all three, unsealed, with roughly a gasket-thickness gap. Whether the case needs those vents is a CFD question (B6). Prefer flanges that leave slots ±3 at least partly open.
- **Magnets:** with slots ±3 open, **4 of the 6 magnets** of v2/v3 (x ±61, y −15 / 25) sit over open holes and hold nothing. Only the lower pair (y ≈ −63) is on flush panel. Magnet pockets must sit on flush steel: below y −53.2, on a rib, or beyond x ±68.3. Otherwise the mount must be screws or clips.

### A6. Vent windows (must stay open)
- **Windows:** the 170HX bracket vent windows are 25 × 81 mm (x −42.98…−17.98 and 17.98…42.98, y −36.65…44.35; *photo*, ±10 %).
- **Strips:** the parts that pass a chassis opening (4 strips: x −42.98…−33.295, −26.225…−17.98, 17.98…27.665, 34.735…42.98) must lie fully inside a mouth: 0 mm² blocked (`must_open`). The rest of each window is behind a rib.
- **Mouth top:** ≥ 0.25 mm above the window top (y 44.35). It cannot rise much further: the mouth top plus its 1.2 mm wall must stay under the screw tips at y 46.0 (A2).

### A7. Fan position: motherboard and PSU side
- **Board plane:** y = bracket top − 108.21 = **−55.86**. Anything below it (−y) protrudes beside the motherboard tray / PSU side of the case's rear face, where the room is unmeasured.
- **Frame bottom below the board plane so far:**

  | Design | Below the board plane |
  |---|---|
  | v1 | about 7 mm |
  | v2 | 21.5 mm |
  | v3 | 13.3 mm |
  | v3L | 9.3 mm |
  | bare fan | 18.6 mm |

  **Budget: ≤ 13.3 mm until the author measures the room; lower is better** (ranked in B5).
- **Fan top:** with a 120 mm fan, the frame top is the axis + 60. Within the ledge's reach (z < 12–15 mm from the panel) it must stay under the ledge (A1). Past the ledge it may rise. That is why a deeper plenum lets the fan sit higher.
- **Protrusion:** behind the rear panel, collector plus fan is 50 mm (v3) or 70 mm (v3L). Anything over 70 mm needs the author's OK.
- **Fan:** 120 × 25 mm, 105 mm hole pitch, bore Ø117 (Arctic P12 Pro). The hub should sit over any splitter's end.

### A8. Printability (no override, ever)
- **Gates:** `release_collector` must pass every gate in `duct/print/printability.py` with **no override**: unsupported_overhang, solid_regions, seal, seat_coverage, and slicer_support with **0 g unexplained support**. Designed bridges are allowed by the spec: the gasket groove roof, magnet-pocket ceilings and fan-screw pilot exits.
- **No STL to the author without the gates.** The author inspects the slices.
- **Print orientation:** flange down. Every air-side and outside wall rises at ≤ 45° from vertical, and even small islands stay ≤ 60° (tier B fails any island steeper than 60° of ≥ 0.002 mm²).
- **Splitters and fins:** a 1.2 mm wall meeting another 1.2 mm wall in a T fails solid_regions. Free-standing fins end ≥ 2 mm off other walls, or are designed with that gate in mind.
- **Walls:** a uniform **1.2 mm** (3 × 0.4 mm perimeters, not 1.6). `verify_collector` checks p1 > 1.15 and a median of 1.2 ± 0.05 on plain skin. The flange is 2.8 mm and the fan plate as specified.

### A9. Aesthetics
- **Shape:** rounded and flush, with few sharp corners: **no knife-edges or wedges**, regardless of any CFD gain.
- **Edges:** fins and splitters end blunt, at full wall thickness, with no feathered tips.
- **Transitions:** smooth, bounded-slope lofts. No visible steps on the outside.

### A10. CFD contract
- **Air volume:** `build_collector(c).inner` is a single genus-0 air volume. It runs from `inlet_z` (the bracket plane), whose section is the mouth(s), to the bore about `fan_axis` at `inlet_z + plenum_depth`.
- **Internal solids:** fins and splitters are subtracted from it, so the CFD sees them.
- **Open slots:** `duct.cfd` treats the open slots as case-air inlets wherever they reach the collector's air.

## B. Objectives (CFD ranking, at equal fan rpm)

Run every candidate, in each layout it targets, with the same intake fans and pull-fan rpm, and with the open slots (5-slot: −3, 0, +3; 4-slot: ±2.5) open to case air at ambient pressure. Rank on the following, in this order of weight:

1. **Fin flow per card:** L/s through each card's fins, A and B. The headline number is the sum; v27 push-pull gives 14.46 L/s at −24.6 Pa plenum suction.
2. **Card balance:** |Q_A − Q_B| / mean, target ≤ 5 %. The hotter card sets the noise floor.
3. **Peak temperature rise:** the hottest card's peak fin or outlet-air rise at the reference heat load, from flow and the CFD's flow distribution over the fin stack (dead zones count).
4. **Bypass:** case air entering the collector without crossing fins, from open slots, plate slits and the gasket, as a fraction of the pull fan's flow. Target 0 from open slots. The plate slits are about 2.4 % at a 0.3 mm gap and can't be designed out.
5. **Fan position:** frame bottom below the board plane (A7), as a tie-breaker. Then protrusion.
6. **Noise at equal rpm, by proxy:**
   - non-uniformity of the axial velocity over the fan inlet annulus (coefficient of variation);
   - the closest obstruction (fin, wall step) to the blade plane (≥ 4 mm);
   - the pull fan's operating point (static pressure across it): lower is quieter at a given rpm.
7. **Case ventilation:** flow out through the open slots that the flange leaves open, versus blocked. Report only, until the author says whether the case needs those vents.

Every candidate's report gives:
- A1–A7 as `fit_check` / `gasket_band` / `bypass_leaks` numbers;
- A8 as gate results with slicer grams;
- B1–B7 from the same CFD setup;
- a bare-fan baseline (`bare_fan_air`) under identical conditions. "Better than just a fan on the panel" must be shown, not assumed.
