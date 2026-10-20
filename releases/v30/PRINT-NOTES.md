# DUAL CMP 170HX — V30 hub fairing behind the fan

Layout: one empty slot between the cards (3-slot pitch, 60.96 mm between card centres). For two cards in four consecutive slots (adjacent, 2-slot pitch) use `releases/a30/`.

## The fan's rear hub (measured)

The fairing's rim is 50.5 mm across and must land on the flat rear face of the fan's motor housing (the round centre of the fan's outlet side, where the struts meet). On an Arctic P12 Pro PST CO that face measures about 52 mm across, from a square-on photo scaled by the 105 mm mounting-hole spacing (±1 mm). The rim therefore sits about 0.75 mm inside the face's edge and doesn't overhang the blade annulus.

- If your fan is a different model, or calipers give a hub face smaller than about 51 mm, set `hub_fairing_d` in `duct/params.py` to fit (V30 is `replace(V29, hub_fairing=1.0)`), then rebuild and re-gate with `uv run duct release v30`.
- V29 is the same duct without the fairing.

## What changed, and why

V30 is V29 with one addition: a hub fairing on the fan axis, behind the push fan's motor hub. The fan moves no air through its hub, so V29 has a slow, recirculating core behind the motor: about 18 cm³ of reverse flow within 45 mm of the fan axis. The fairing fills that core with a smooth body that the air from the blade annulus can follow.

- Shape: a hollow ogive (a rounded cone) with a 1.2 mm wall, 50.5 mm across at the fan face and tapering toward a point 34.8 mm downstream. The splitter web runs whole through it: the fairing stops at the web's two skins on each side, which carry it (no struts), and nothing of it reaches into the gap between the skins, so that gap is the same as V29's (the first V30 build had the fairing's tip standing in it).
- Printing (fan face down, as all the ducts): the cavity inside is open toward the fan, split by the web into two half cones, and each closes with a ceiling at most 44° from vertical. It is never a flat roof. The outside slopes outward going down. Neither needs support.
- Everything else is V29: the 62 mm fan-to-GPU distance, bores, collars, pitch, fan plate, 1.2 mm walls, sealed seat and the lever-shaped latch notch.

## CFD (single fan at 2500 rpm, 600 iterations, legacy main-path-only fin heat coupling)

| | V29 | V30 | change |
|---|---|---|---|
| Flow | 9.128 L/s | 9.127 L/s | 0.0% |
| Peak GPU rise | 87.17 K | 87.17 K | −0.00 K |
| Duct loss (fan to 1 mm above the card) | 0.229 Pa | 0.223 Pa | −2.6% |
| Reverse-flow volume, hub core (r < 45 mm) | 18.0 cm³ | 7.5 cm³ | −59% |
| Main-port flow CoV | 0.0997 | 0.0998 | +0.0001 |

Two more paired comparisons:

- On a second mesh (base cell 3.9 mm instead of 4.0 mm): core reverse flow −61%, duct loss −0.5%, flow −0.14%, peak rise −0.01 K.
- With a rounded (6 mm) inlet lip on the fan's room side of the CFD domain: core reverse flow −52%, duct loss −0.1%, flow −0.01%, peak rise +0.015 K.

The dead-core reduction is robust. The flow and temperature changes are within the mesh's own scatter: changing the base cell alone moves V29's flow by 0.06 L/s and its peak rise by 1.1 K. This is a clean-up of the flow, not a cooling upgrade.

With the fairing, the slow-air area at the outer wall grows (periphery reverse area 0.096 → 0.111). That outer-wall reverse flow is mostly an artefact of the sharp-edged inlet in the CFD domain. With the rounded lip it drops from 27 to 5 cm³, with or without the fairing.

## Checks (gated release, no override)

- No overhang beyond 45° (largest island 0.07 mm², below the 0.25 mm² limit), no void or leak (seal gate), seat coverage as V29. Solid material only where named in the allowlist. The fairing adds one entry, where its root meets the splitter web's skins. Bambu Studio with automatic supports adds 0 g of support: the automatic-support and no-support slices are identical.
- Fan-face coverage: 0.0007 mm² uncovered. The rim is a full ring at the fan face. Export simplification 0.0025 mm, as V29.
- Material: 61.9 cm³ (V29: 58.1). P1S / .4 mm / .28 mm PETG: 156.1 min / 72.1 g (V29: 143.9 min / 67.7 g).

The fit-check STL is the top 10 mm of the duct (both GPU openings and collars), the same as V29's. Physical fit and printing are untested.
