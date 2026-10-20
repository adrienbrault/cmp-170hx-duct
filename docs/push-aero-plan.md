# Push duct aerodynamic refinement: diagnosis and plan

This plan was written with the strongest model on 2026-10-16. It is built from the V28 (= V29 air passage) and A29 single-fan CFD fields: `runs/v28-1fan-panel` at time 254, and `runs/a29-1fan-panel` at time 261 in the integration worktree.

## Diagnosis

- **Duct total-pressure loss:** 0.41 Pa (V28) and 0.36 Pa (A29), out of a 32.5 Pa fan total pressure, i.e. 1.2 %.
  - ~0.16 Pa is the card face's own contraction (bore 3792 mm² → ports 2820 mm²).
  - ~0.13 Pa is the 62 mm chamber.
  - ~0.10 Pa is the last 3 mm before the seat.
- **What removing all of it would buy:** removing every duct-attributable loss is worth ≈ 0.035 L/s, about 0.1 K. That is below the model's resolution, so the refinements are "cleaner flow at no cost", not measurable thermal gains. The author wants them anyway: aerodynamic and clean.
- **Fin-face uniformity is not a lever:** the row-flow CoV is 0.031–0.036 and the peak row carries 1.00× the mean flow. The model credits heat only in the main fin path.

### Hub dead core (the one real flow structure)
- **Where:** behind the fan hub, the flow at r < 20 mm is stagnant (slightly reverse at z 15–20) and fills only by z ≈ 40–50.
- **Size:** reverse-flow volume in the duct is 42.6 cm³, 8.5 % of the air volume (A29: 46.3 cm³, 9.2 %). The core accounts for ~20–25 cm³ of it.
- **Splitter nose:** sits in this dead air for |y| < 25.

### Other findings
- **Peripheral reverse ring:** ~18 % of the section at z 2–10 has reverse flow at r > 55. It's mostly a model artefact: the sharp-edged approach annulus. The fix is a rounded approach lip in the CFD domain (`DomainParams.approach_lip`); the duct can't fix it.
- **Corners:** no corner vortices with reversal. The slow area is 6–8 % of the section near the seat, mostly the outer −y bore corners, which lie 11.6 mm outside the fan circle and are filled at ≤ 11.5°. The air corners fade from r 6 to square over z 54–62.
- **Bay ramp:** converging at 43°, no separation, ~0.02 Pa flow-weighted.
- **Splitter nose:** clean stagnation where the flow reaches it, no separation. Its 0.4 mm knife edge is a print-quality item only.

## Refinements, ranked

### 1. Hub fairing behind the push fan (recommended)
- **Shape:** a 1.2 mm shell of revolution on the fan axis, open toward the fan. Its base is at the fan face. It is carried by the splitter web (V29) or the shared wall (A29).
- **Parameters** (all default off; V28/V29/A29 stay byte-identical):
  - `hub_fairing` (0 = off, 1 = on)
  - `hub_fairing_d` = 50.5, the base outer diameter (the rear hub face measures about 52 mm: the rim lands 0.75 mm inside it)
  - `hub_fairing_angle` = 44°, the steepest flank from vertical
  - `hub_fairing_power` = 1.35; cavity radius r = R·(1 − t^p)
  - Resulting length ≈ 35 mm, tip at z ≈ 35.
- **Printing fan-face-down:** the outer narrows going up, so it never overhangs. The overhanging face is the **cavity ceiling**, so:
  - specify the cavity profile and close it as a cone at ≤ the angle down to the axis, never a flat ceiling. The collector's `hub_fairing` closes its cavity with a flat disc, which is fine flange-down but a ~56° bridge fan-face-down;
  - make the outer = cavity ⊕ the 1.2 mm kernel, so the wall is exactly 1.2 and the tip is rounded by the dilation;
  - extend the cavity to z −2 so the mouth stays open, then trim at z = 0;
  - first layer: a Ø50.5 × 1.2 ring on the bed, joined to the web. This also removes the knife-edge nose for |y| < R.
- **Gate allowances:**
  - `Allowed('hub fairing root on the splitter web', …)`
  - `Opening('hub fairing cavity', …)`
  - In A29 the junction already lies inside the shared-wall allowance.
- **Hardware prerequisite (done 2026-10-18):** the rear hub face of a P12 Pro PST CO measures about 52 mm across (photo against the 105 mm hole spacing, ±1 mm), so 50.5 mm stands. Original ask: measure the P12 Pro's **rear** hub, i.e. the motor-housing diameter at the rear face, the strut-root diameter, and how far the hub face is recessed. The fairing rim must land on the flat rear face of the housing. The Ø50.3 in duct/cfd/fan.py is the *front* cap. Then set `DomainParams.hub_radius` = `hub_fairing_d`/2 in the CFD.
- **Expected:** removes the core recirculation by construction and takes the splitter nose out of dead air. ΔQ is within ±0.02 L/s, i.e. unmeasurable.

### 2. CFD model hygiene: rounded approach lip
- **What:** `DomainParams.approach_lip` (mm), a quarter-round flare on the approach annulus's outer edge, plus an `intake_rules` wall classification. Try 6 mm.
- **Rule:** all compared rows share the setting.
- **What it is:** a fidelity change, not a design gain.

### 3. Optional (expected ~0; adopt only if the gates pass and nothing gets worse)
- `section_radius=8` (an existing field).
- New `outlet_radius` (≤ 1.45): keeps the air corners rounded to the seat, with per-corner seat fills and an `Allowed('seat corner fills')`.
- `bay_ramp_ease=0.15` (an existing field).

### Rejected
- **Port nozzles:** the ports are unmeasured. At this plan's baseline the model credited no heat to the side ports;
  [the configurable side-port closure](thermal-side-ports.md) now makes that thermal assumption explicit.
- **Splitter nose changes:** not needed.
- **Longer chamber:** L was shortened to 62 deliberately.

## CFD

### Metrics
New `duct/cfd/entry.py`, written to `summary["duct_flow"]`:
- **Duct-only loss:** a new `seatUp` station at z = L−1. Split `intake_duct` into `duct` and `card_face`.
- **Card-entry uniformity:** CoV per port, port shares, main-port y-profile, row-flow CoV.
- **Hub wake:** reverse-flow volume split at r < 45 (core) and r > 50 (periphery), the core fill length, and the slow-area fraction at z 30/45/58 per region.
- **Bay-quadrant pt deficit.**

### Noise floor first
Two runs per layout: the baseline at base_cell 4.0 and at 3.8, or `DomainParams.simplify` .002 vs .0021. Their difference is the detection threshold.

### Rows (≤ 8 per layout, every row with the same lip setting)

| Layout | Rows |
|---|---|
| V29 | B0, B0' (perturbed), F1 (fairing default), F2 (measured d), L1 (lip), FL (fairing + lip), S1 (`section_radius` 8), O1 (`outlet_radius` 1.4) |
| A29 | B0, B0', F1/F2, FL, O1 |

- **Run length:** ~5 min per single-fan run at 6 ranks. With other matrices running, use `--np 3`.
- **Iterations:** use `--profile final` or a fixed `--iterations 600`.
- **Thermal:** keep the thermal step on every row.

### Decision rule
Adopt the fairing into V30/A30 only if all of these hold, in both layouts:
- every gate passes with no override;
- duct loss is no worse than baseline + the noise floor;
- Q is no lower than baseline − the floor;
- peak rise is no higher than baseline + 0.1 K;
- main-port CoV is no worse by more than 0.01;
- core reverse volume drops by at least 50 %;
- the rear-hub measurement allows the rim.

## Implementation
1. **`duct/params.py`:** the fields. Add `V30 = replace(V29, hub_fairing=1.0)` and `A30` only after the matrix.
2. **`duct/cad/geometry.py` `build_duct`:**
   - a shared shell-of-revolution helper (shared with `exhaust.hub_fairing`, with the cavity-apex fix);
   - `inner -= fairing_outer` before the fan-face coverage assertion, and fix the `_fan_half` expected area;
   - `final = union(…, fairing_outer) − inner − cavity`.
3. **`duct/cfd/domain.py`:** with the fairing on, the bridging disk becomes an annulus. Optionally add `approach_lip`, plus the rule in `disk.intake_rules`. In `cli._case_options`, set `hub_radius`.
4. **CFD stations and metrics:** the `seatUp` station in case.py and breakdown.py; the new entry.py.
5. **`printability.duct_spec`:** the cavity Opening and the root Allowed (plus the corner-fill Allowed if `outlet_radius` is used).
6. **`verify.py`:** fan-aperture coverage subtracts the cavity disc, and the splitter-width rows move off y = 0 for z < tip. `export.checks` gets a `hub_fairing` dict.
7. **Tests:**
   - V28/V29/A29 rebuild byte-identical;
   - V29 and A29 with the fairing: flank slope ≤ angle including the apex, cavity open, no fluid at r < R at z = 0, `run_gates` passes;
   - a `breakdown` `seatUp` test and an `entry.py` unit test.
8. **Release:** only after the matrix and the rear-hub measurement.

## Risks
- **Rear-hub geometry:** the only hard risk.
- **Manifold boolean robustness at V29's 0.4 mm web stubs:** keep the web locally solid up to R+1.
- **2-D loft:** `even_loft` can't absorb the fairing as a 2-D section bite, so it has to be a 3-D boolean.
- **Steady-RANS bistability on a recirculating core:** compare runs against the noise pair.

## What the CFD can't resolve
- **Actuator disk:** no blade wake, tip jet or swirl. The hub is a flat disc 5 mm upstream, with no struts.
- **Porous fins:** zone scale only.
- **Fin ports:** estimates.

Real-world gains from the fairing (swirl, blade-root wake) could be larger than modelled, but this model can't show them.
