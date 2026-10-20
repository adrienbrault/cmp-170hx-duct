# DUAL CMP 170HX — A30 hub fairing behind the fan (adjacent slots)

Layout: two cards in four consecutive slots (adjacent, 2-slot pitch, 40.64 mm between card centres). For one empty slot between the cards (3-slot pitch) use `releases/v30/`.

## The fan's rear hub (measured)

The fairing's rim is 50.5 mm across and must land on the flat rear face of the fan's motor housing (the round centre of the fan's outlet side, where the struts meet). On an Arctic P12 Pro PST CO that face measures about 52 mm across, from a square-on photo scaled by the 105 mm mounting-hole spacing (±1 mm). The rim therefore sits about 0.75 mm inside the face's edge and doesn't overhang the blade annulus.

- If your fan is a different model, or calipers give a hub face smaller than about 51 mm, set `hub_fairing_d` in `duct/params.py` to fit (A30 is `replace(A29, hub_fairing=1.0)`), then rebuild and re-gate with `uv run duct release a30`.
- A29 is the same duct without the fairing.

## What changed, and why

A30 is A29 with the V30 hub fairing on the fan axis, behind the push fan's motor hub. The fan moves no air through its hub, so A29 has a slow, recirculating core behind the motor: about 24 cm³ of reverse flow within 45 mm of the fan axis. The fairing fills that core with a smooth body that the air from the blade annulus can follow.

- Shape: a hollow ogive (a rounded cone) with a 1.2 mm wall, 50.5 mm across at the fan face and tapering to a point 34.8 mm downstream. It sits across the shared 2.14 mm wall between the cards, which carries it. The cavity is cut through the shared wall where they overlap, so the inside is one clean cone.
- Printing (fan face down): the cavity is open toward the fan and closes as a cone whose ceiling is 44° from vertical at its steepest. It is never a flat roof. The outside slopes outward going down. Neither needs support.
- Everything else is A29: the 62 mm fan-to-GPU distance, bores, outer collars, the shared wall, fan plate, 1.2 mm walls, sealed seat and the lever-shaped latch notch.

## CFD (single fan at 2500 rpm, 600 iterations, legacy main-path-only fin heat coupling)

| | A29 | A30 | change |
|---|---|---|---|
| Flow | 9.134 L/s | 9.139 L/s | +0.05% |
| Peak GPU rise | 87.48 K | 87.46 K | −0.02 K |
| Duct loss (fan to 1 mm above the card) | 0.198 Pa | 0.188 Pa | −5.0% |
| Reverse-flow volume, hub core (r < 45 mm) | 23.8 cm³ | 8.2 cm³ | −65% |
| Main-port flow CoV | 0.0886 | 0.0879 | −0.0007 |

Two more paired comparisons:

- On a second mesh (base cell 3.9 mm instead of 4.0 mm): core reverse flow −63%, duct loss −3.4%, flow −0.03%, peak rise +0.00 K.
- With a rounded (6 mm) inlet lip on the fan's room side of the CFD domain: core reverse flow −57%, duct loss −2.1%, flow +0.01%, peak rise +0.01 K.

The dead-core reduction is robust. The flow and temperature changes are within the mesh's own scatter: changing the base cell alone moves A29's flow by 0.05 L/s and its peak rise by 0.7 K. This is a clean-up of the flow, not a cooling upgrade.

## Checks (gated release, no override)

- No overhang beyond 45° (largest island 0.002 mm², as A29), no void or leak (seal gate), seat coverage as A29. Solid material only where named in the allowlist. Inside the fairing the shared wall is hollowed by the cavity, so the allowed solid there drops from 11.2 to 10.1 cm³. Bambu Studio with automatic supports adds 0 g of support: the automatic-support and no-support slices are identical.
- Fan-face coverage: 0.00002 mm² uncovered. The rim is a full ring at the fan face. Export simplification 0.0025 mm, as A29.
- Material: 58.0 cm³ (A29: 55.3). P1S / .4 mm / .28 mm PETG: 145.6 min / 67.8 g (A29: 134.8 min / 64.7 g).

The fit-check STL is the top 10 mm of the duct (both GPU openings and the collars joined by the shared wall), the same as A29's. Physical fit and printing are untested.
