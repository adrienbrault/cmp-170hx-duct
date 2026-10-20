# Exhaust collector v4: diagnosis, concepts, CFD matrix, implementation plan

This plan was written with the strongest model on 2026-10-16, from `docs/collector-constraints.md` and the V28 push-pull comparison runs (`runs/v28-pp-*`). It applies to both slot layouts: 5-slot (V29, pitch 60.96) and 4-slot (A29, pitch 40.64).

**Frame:** the duct frame. x runs across the cards, +y toward the bracket tabs and ledge, z along the card axis. The bracket plane is at z_b = 329 for V29 and A29.

## User requirements added after the analysis (binding)

- **Curves, not a box.** The author looked at v3 and asked: "For the collector, should there not be curves? Seems like a plain box?" v4 needs smooth, curved internal flow geometry:
  - a radiused entry where each mouth meets the flange;
  - smoothly curving channel and diffuser walls from each mouth to the fan bore;
  - generous internal corner radii and no sharp internal corners;
  - a smooth merge of the card channels;
  - a bell or fillet into the fan bore at the fan plate;
  - a rounded outside to match the push duct.

  Every curve must still print flange-down within the ≤ 45° overhang gate. Where a curve conflicts with a hard constraint, show the trade-off; don't silently drop it.
- **Noise.** The author values noise. Fan-inlet uniformity (CoV and reverse-flow area) and the rpm needed at equal cooling are first-class objectives.
- **Aesthetics:** rounded and flush with few sharp corners; no knife-edges or wedges; 1.2 mm walls; no STL without the gates.

## 1. Diagnosis

### 1.1 What limits fin flow

v3 at 12.50 L/s, mass-weighted station values from `runs/v28-pp-v3/summary.json`:

| Station | Static (Pa) | Total (Pa) | Note |
|---|---|---|---|
| cardExit (fins' exit) | **−3.16** | +2.0 | The suction the fins actually see. |
| bracketDown (one cell past the panel) | −27.45 | −4.06 | 23.4 Pa of jet dynamic head. The four vent strips (1452 mm² per card, sharp-edged, vena contracta ~0.65) issue jets of ~6–7 m/s. |
| exit (fan inlet station) | −25.64 | −10.88 | 14.8 Pa of dynamic head is still present at the blade plane. A uniform inlet would carry 1.2 Pa. |

- **Total-pressure losses are small:** 6.0 Pa in the contraction into the strips, 6.8 Pa in the plenum. The jets' kinetic energy isn't lost in the plenum; it passes through the fan and is dumped into the room.
- **So the pull fan's 27 Pa goes almost entirely into accelerating the strip jets,** and the fins see only −3.2 Pa. The bare fan's cardExit static is +3.2 Pa, which explains 10.99 vs 12.50 L/s.
- **Fan static is not the lever; card-exit static is.**

The only way a collector raises fin flow is by **recovering jet head as static pressure between the strip and the fan**: a channel or diffuser downstream of each strip, which lowers the card-exit static.
- **Ceiling:** the no-panel case, 14.46 L/s.
- **Realistic estimate:** +4–8 Pa at the card exit, +0.5–1.0 L/s (4–8 %), about −1.5 to −3 K. This is the hypothesis the CFD must confirm.
- **Depth alone recovers nothing:** v3L (a sudden expansion either way) shows it.

### 1.2 What drives v3's reverse flow (41 % of the fan inlet, CoV 1.93)

- **Under-spread jets:** four jets at ~6.5 m/s (5× the 1.44 m/s annulus mean) reach the fan 25 mm away having spread only ~5 mm per side.
- **Recirculation:** behind the sudden expansions (bottom wall 32°, x walls 28°) the flow recirculates, so Uz < 0 over 41 % of the station.
- **Hub shadow:** the inner strips lie partly under the hub (374 mm² at 5-slot, 832 mm² at 4-slot), so those jets impinge on it.
- **Fin wake:** the splitter fin ends 6.4 mm below the blade plane, and its wake reaches the hub region.
- **v3L's imbalance:** v3L's 8.2 % imbalance is a bistable merge under the hub, which steady RANS can't average.

### 1.3 What the CFD can and cannot resolve

- **Actuator disk:** a uniform static jump, no response to inlet distortion. It overstates the fin flow of a distorted-inlet design like v3 and understates the benefit of a uniform inlet. Tonal noise is proxies only.
- **Porous fins:** flow distribution is resolved at zone scale.
- **Steady RANS k-ω SST:** jets and short diffusers come out qualitatively right; bistable merges show up as non-convergence or imbalance.
- **Mesh:** a mesh step changes Q by ~1.3 %/level, so decision thresholds are ≥ 0.3 L/s.
- **Fan-inlet CoV and reverse-flow fraction are not computed anywhere yet.** A `fan_inlet_profile(case)` that samples Uz on the `exhaustFanUpstream` faceZone is a prerequisite: CoV, the area fraction with Uz < 0, and the dynamic head, written into summary.json.
- **B7 is geometric only:** open slots under a windowed flange leave the CFD domain.

## 2. Concepts

### Shared by all concepts (both layouts, every hard constraint)

- **Per-card gasket loops on the ribs,** as in v3. In the 4-slot layout the two loops share one 3 mm band on the central rib. No open slot is inside a loop in either layout.
- **Mouth top and top wall:**
  - mouth top at 44.6;
  - the top wall dips 1 mm within 1.7 mm of the flange and holds until z = 15 (ledge lip);
  - then it rises at a bounded angle.
- **Windowed flange with the magnets on flush steel:**
  - **Cutout:** a rectangular cutout over each outer open slot (5-slot: slots ±3; 4-slot: ±2.5) leaves it fully open as a vent and serves as the fan-cable path.
  - **Magnet columns:** 10 × 3 N52 magnets in two columns on the outer flush band, at x = ±75.2 (5-slot) or ±65.0 (4-slot), y ≈ −35, 5, 40.
  - **Bottom row:** below the openings at y ≈ −60.5, x = 0, ±35.
  - **Fallback:** `mount='screws'`.
- **Flange and screw access:** the flange +y edge is at 49.94. The screwdriver columns are cleared; the thumb-screw columns need the fan frame at z ≥ 15.6.
- **Fan position** is set by the top-wall angle budget. With the frame bottom at the board plane (−55.86), the fan axis is at y = 4.14:
  - D = 40 at α = 40°;
  - D = 45 at α = 34.5°;
  - D = 50 at α = 30°.

  Protrusion D + 25 ≤ 70, so D ≤ 45 without the author's OK.

### Concept table

| | v3 | **A (recommended)** | **B (control)** |
|---|---|---|---|
| Plenum depth D | 25 | 40 (variants 45, 50) | 40 (45) |
| Fan below the board plane | 13.3 mm | ≈ 0–1 mm | same as A |
| Protrusion | 50 | 65 (70) | 65 |
| Mouths | 1 per card | **1 per chassis opening (4)**, each opening + 0.5 mm, each feeding its own curved diffuser channel | 1 per card |
| Fins (1.2 mm, blunt, ≥ 2 mm off walls) | centre splitter | centre splitter + **one rib fin per card** on the 6.07 mm flange strip over the rib behind each window (x ±29.76 at 5-slot, ±19.6 at 4-slot), up to z ≈ 28–32, leaning outward 0–8 mm | centre splitter only |
| Web step | open plenum | inner walls start at the mouths' inner edges and curve toward the centre fin (filled step), merge fillet r ≥ 3 | open |
| Expected | baseline | card-exit static −3 → −8…−12 Pa; +0.5–1.0 L/s; fan-inlet dynamic head 14.8 → < 5 Pa; reverse area 41 % → < 15 % | ≈ v3 flow; reverse area improves with depth only |

- **C (rejected):** a tilted or x-offset fan, two 80 mm fans, a hub cone (fails solid or seal), hooks over the ledge (floating island).
- **Why A rather than fully separate tubes:** separate tubes merging at the bore failed the gates repeatedly in v3. A keeps one genus-0 air volume with free-standing fins subtracted (`_split_air` + `splitter_fin`, `FIN_END_GAP` 2). Variant A0 is A without the step fill, if the merge ridge resists the gates.

### New `CollectorParams` fields

All default off, so v1–v3 rebuild byte-identical.

```
plenum_depth 40.0; top_dip=(1.0, 1.7, 15.0); ease_ramp 0.1
max_wall_angle: float = 45.0      # builder asserts steepest air wall <= this
fan_y_at_board: bool = False      # derive fan_offset_y so the frame bottom sits frame_below_board under the board plane
frame_below_board: float = 1.0
per_opening_mouths: bool = False
rib_fins: bool = False; rib_fin_end: float = 30.0; rib_fin_lean: float = 6.0; rib_fin_thickness: float = 1.2
fill_web: bool = False; merge_fillet: float = 3.0
flange_mode: str = 'overlap'|'windowed'; flange_reach_x: float = 15.0; slot_windows: bool
magnet_columns_y=(-35., 5., 40.); magnet_row_y=-60.5; magnet_row_x=(-35., 0., 35.)
cable_notch: () when windowed
+ curve parameters (mouth entry radius, channel wall curvature / diffuser half-angle, bore bell radius, internal corner radius)
```

`COLLECTOR_V4 = replace(COLLECTOR_V3, …)`. The 4-slot part is `COLLECTOR_V4.for_duct(A29)`; everything derives from `card_pitch`.

## 3. CFD matrix

**Decision rule** (written before running):
- Adopt the fins only if Q_fins(A) − Q_fins(B) ≥ 0.3 L/s in **both** layouts, card balance ≤ 5 %, and CoV / reverse fraction are no worse.
- Pick the shallowest D within 0.15 L/s of the deepest.

**Conditions:** push 2500 / pull 2500 rpm, panel, every empty slot open.

**5-slot (V29; reuse v28-pp-bare 10.99 and v28-pp-v3 12.50):**
1. B, D40
2. A, D40, lean 0
3. A, D40, lean 6
4. A, D45, best lean
5. A0 if the gates force it; otherwise A, D40, lean 6 at 2000/2000
6. The winner at the pull rpm that matches the bare baseline's flow (noise at equal flow)
7. The winner with window refinement level 3 (mesh check)

**4-slot (A29):**
1. Bare fan
2. B, D40
3. A, D40, lean 0
4. A, D40, lean 6
5. A, D45
6. The winner at matched-flow rpm
7. Level-3 mesh check

**Report for each run:**
- cardExit flux and static per card, imbalance, peak rise;
- caseAir flux (must be 0);
- fan static and exit dynamic head;
- `fan_inlet_profile` (CoV, reverse area);
- geometry: fin end ≥ 4 mm from the blade plane, frame below board, protrusion, open-slot vent area left.

## 4. Implementation steps

1. **`duct/params.py`:** the new fields and `COLLECTOR_V4`.
2. **`duct/cad/exhaust.py`:**
   - `mouths(c)`, per card or per opening;
   - `split_top` with a bounded rise;
   - `fan_y_at_board`;
   - `split_section` with `fill_web` and the `merge_fillet` concave fillet;
   - `rib_fins(c)` like `splitter_fin`, subtracted from `inner`;
   - the windowed `flange_outline` (holes) and `mount_points` columns + row;
   - the curves above.
3. **`duct/cad/export.py` `collector_checks`:** `frame_bottom_below_board_mm`, `open_slot_vent_area_left_mm2`, fin geometry, `steepest_air_wall_deg` vs `max_wall_angle`.
4. **`duct/cad/hardware.py`:** every magnet in `fit_check` has `flush == 1.0`; add `open_slot_vent_area`.
5. **`duct/print/printability.py` `collector_spec`:** the plenum Opening gets `max_count` 4 and one passage seed per mouth; a param-derived `Allowed('channel merge ridge')` only when `fill_web`.
6. **CFD:**
   - `duct/cfd/collector.py`: KINDS gets v4/v4b, using `preset.for_duct(g)`;
   - `fan_inlet_profile(case)` → summary.json.
7. **`duct/cli.py`:** `--collector v4|v4b`.
8. **Tests:** `tests/test_collector_v4.py`, parametrised over (V29, A29).
9. **Release:** `release_collector` for `collector-v4-5slot` and `collector-v4-4slot`, with PRINT-NOTES per layout.
10. **Run the matrix** and record it in `docs/collector-v4.md`.

### Deterministic checks (both layouts)

- **No open slot enclosed:**
  - `gasket_band`: `open_slots_inside_loops == []`, groove over open slots = 0, over_open = 0, foam land ≥ 3.0;
  - the `bypass_leaks` open-slot row is 0;
  - `duct.cfd.collector.open_slots` returns no rows;
  - `open_slot_vent_area` ≥ 95 % of each open slot.
- **Magnets on steel:** every magnet has `flush == 1.0` and lies inside `hw.panel_2d`, including under `covered()`.
- **Screwdriver access:**
  - every `access_column_blocked_mm3 == 0`, for CASE, thumb screws, `covered()` and `fit_sweep`;
  - total intersection 0;
  - clearances: ledge ≥ 0.5, heads ≥ 1.5, shanks ≥ 0.2.
- **Fan budget:** frame below board ≤ 2 (hard ≤ 13.3); behind the panel ≤ 70.
- **Vents:** `openings_blocked_mm2 < .01`; `outside_mouth_mm2 == 0`.
- **CFD contract:** `inner.genus() == 0`; mouths at z0 + 0.5; bore centred on `fan_axis` at z0 + D.
- **Gates:** all pass, slicer support 0 g, no override; wall p1 > 1.15, median 1.2 ± 0.05; fin ends full 1.2 mm and ≥ 2 mm off walls.

### Risks and user measurements

- **Room past the ledge (+y):** at z ≥ 41 the frame top is ~13 mm past the ledge.
- **Steel around the openings:** whether there is ≥ 15 mm of flush steel beyond the outermost openings, and whether there is a flat panel below the board plane (≥ 12 mm, for the magnet row).
- **Opening widths:** assumed CEM minimum. The fit gauge settles them.
- **Clearance behind the case at 65–70 mm,** and whether the case needs the open slots as vents.
- **Gates at the merge ridge:** build the rib fins first, the step fill second, and gate each. Fall back to A0/B.
- **CFD limits:**
  - steady RANS on jets;
  - a mesh step of 1.3 %/level;
  - the actuator disk can't score a distorted inlet, so the v4-vs-v3 gain is a lower bound.
- **Magnet hold through the foam stand-off:** consider pockets 0.5 mm shallower.

## Revision after the curves requirement (supersedes the sections above where they differ)

### 1. Each curve, with its numbers

**Inlet lip at each mouth.**
- **Shape:** a diffuser flare. The mouth edge rolls outward with r_lip = 2–3 mm from the panel face, tangent into the loft wall.
- **Edges:** sides and bottom only. The top edge gets **no lip** (screw tips at y 46.0, z 4.6–8.1; air top ≤ 44.6).
- **Narrow webs:** at the 4-slot central web and the 6.07 mm rib-fin strips, r ≤ 2.4 each side.
- **Gasket groove:** keeps ≥ 1.4 mm of roof.
- **Printing:** the air widens going up, so the flare is never an overhang. The body–flange fillet must be ≥ r_lip + wall (4.5 for a 3 mm lip; 1.5–2 on the top side).
- **Effect:** ≈ 0 Pa. The orifice is the steel strip edge, not the mouth. This is shape only; the PRINT-NOTES must say so honestly.

**Walls from mouth to bore.**
- **Profile:** eased ramp, e = 0.2–0.3, mean angle ≤ 32°, peak ≤ 41°.
- **Top wall:** holds at 43.6 (1 mm dip) until s = 15 (ledge lip), then rises.
- **Depth:** 45 mm in the default design (see item 3 below).

**Section corners.**
- **At the mouths:** top-outer ≤ 4, top-inner ≤ 5, bottom 12 (per-corner radii).
- **Further in:** they grow to ≥ 12 by mid-depth and on to the bore.
- **Per-opening cutouts:** rib-side top corners r 1.2, softened above the flange by a 2.4 mm fin-root fillet.

**Channel merge.**
- One genus-0 air volume with free fins.
- The splitter fin gets a full-round top edge (r 0.6) and ends ≥ 4 mm below the plate.
- Optional `web_fill` (5-slot only): each card's inner wall leans toward the fin at ≤ 30°, joined by a fillet with r_merge ≥ 4. It needs the param-derived `Allowed('channel merge ridge')`.

**Bore entry.** The ramp's end easing is the bell: the walls arrive vertical, with an effective radius of ≈ 12–15 mm. The last ~3 mm before the plate are a straight Ø117 bore. Zero slope at the plate avoids a corner eddy at the blade tips, which is good for noise.

**Outside.**
- Uniform 1.2 mm shell, so every inside curve shows on the outside.
- Body–flange fillet 3.5–4.5 (1.5–2 on the +y side).
- Flange corners ≥ 15, slot-window corners ≥ 4, plate corners 5 to match the push duct.
- Rounded magnet bosses, a 1 mm round on the flange's top edge, no bottom-edge round.

### 2. Trade-off: curves cost depth

| D | Fan frame bottom below the board plane | Protrusion |
|---|---|---|
| 40 | 4.8 mm | 65 |
| **45** | **0 mm** (mean angle 34.4°, peak 40.6°) | **70 (the limit)** |
| 50 | 0 mm | 75 (needs the author's OK) |

### 3. Default depth is D = 45

### 4. Mounts: 7 magnets
- **Bottom band** (y −56…−68): 3 magnets at y ≈ −61.5.
- **Two outer columns:** reach flush steel through flange windows over the open slots (cutout = opening + 1 mm, corners r 4). 2 magnets each, at x = ±75.2 (5-slot) or ±65.0 (4-slot), y ≈ −30 and +35.
- **Cable:** drops through a slot window.

### 5. Presets
- `COLLECTOR_V4A`: concept A.
- `COLLECTOR_V4B`: the control.
- Use them via `.for_duct(V29)` and `.for_duct(A29)`.
- Add a `frame_bottom_below_board_mm` property.

### 6. CFD matrix
**5-slot:**
- R1 bare (reuse);
- R2 v3 (reuse);
- R3 B D45;
- R4 A D45, lean 0;
- R5 A D45, lean 6;
- R6 A D40 (best lean);
- R7 A D45 with web_fill;
- R8 the best at the pull rpm matching the bare fan's 10.99 L/s;
- R9 the best at refinement level 3.

**4-slot:**
- R1 bare;
- R2 B D45;
- R3 A D45, lean 0;
- R4 A D45, lean 6;
- R5 A D40;
- R6 the best at matched-flow rpm;
- R7 level-3 check;
- optional R8: both layouts' best at 2000/2000.

**4-slot note:** the hub shadow is 832 mm² (29 % of the live strips) whatever the fan's y. Depth is the only lever.

### 7. CFD kind names
`v4a` and `v4b`. `duct verify --collector v4a|v4b`.

## Correction: fan-inlet numbers from `fan_inlet_profile`

These come from `duct/cfd/inlet.py`, which samples every design on the same band, and supersede the ad-hoc figures in §1.2.

**V28, push-pull 2500:**

| Collector | CoV | Reverse area |
|---|---|---|
| v2 | 1.01 | 23 % |
| v3 | 1.47 | 36 % |
| v3L | 1.39 | 32 % |
| bare fan | 1.50 | 37 % |

**v3 card-exit static:** −3.31 / −3.00 Pa (A / B).

**4-slot baselines (A29):**

| Setup | Fin flow | Peak rise A / B | Notes |
|---|---|---|---|
| 1 fan | 9.14 L/s | — | |
| Bare fan | 9.58 L/s | 90.8 / 82.3 K | 41 % of the fan's flow is case air, through slots ±2.5. Card A's main fin path is starved (share 0.70). |

At 4-slot, a sealing collector matters more than at 5-slot.
