# DUAL CMP 170HX — A29: adjacent slots (2-slot pitch)

**Which duct do you need?**

- **A29 (this one): adjacent slots, 2-slot pitch.** The two cards sit in four consecutive PCIe slots, with no empty slot between them (e.g. slots 1–2 and 3–4). Card centres are 40.64 mm apart.
- **V29 (`releases/v29/`): one empty slot between the cards, 3-slot pitch.** The cards are e.g. in slots 1–2 and 4–5. Card centres are 60.96 mm apart.

The two do not fit each other's layouts. A29 is V29 with only the pitch changed (`duct/params.py`: `A29 = replace(V29, pitch=40.64)`). It keeps V29's bores (38.5 × 98.5 mm), outer collars, sealed seat, plug pockets, lever-shaped latch notch (see `releases/v29/PRINT-NOTES.md`), 1.2 mm walls, 62 mm chamber (74 mm print depth) and the 120 × 120 × 2.4 mm fan plate with its 105 mm hole pattern for one 120 mm fan centred between the cards.

## The wall between the cards

Pulling the cards 20.32 mm closer leaves 40.64 − 38.5 = **2.14 mm** between the two bores. That is less than two 1.2 mm collar walls, so the two inner collar walls become **one shared 2.14 mm wall**:

- The wall slides into the gap between the two cards. The measured card is 38.4 mm thick (V6–V8 notes), so the real shroud-to-shroud gap is 40.64 − 38.4 = 2.24 mm. That leaves the wall the same 0.05 mm per side as the bore everywhere else. The CEM dual-slot maximum (2.67 + 34.80 = 37.47 mm) would give a 3.17 mm gap.
- Both bores and the wall are one rigid comb. In V29 each bore centres on its own card; here any error in the card-to-card distance (slot or bracket tolerance, a tilted card) uses up the 0.05 mm per side directly. The lead-in chamfer (38.9 mm bore at the collar top) narrows the wall's tip to 1.74 mm over its last 0.65 mm. If the fit gauge binds, the fix would be a separate, larger clearance on the inner bore faces, which would be a new parameter.
- Below the seat, the same wall is the splitter web. The web's half width never reaches a wall thickness, so it never parts into two skins as V29's does. It runs solid from the fan face to the top of the collars: about 11.2 cm³ and five 0.4 mm lines wide. It is not a whole number of perimeters (5 × 0.4 = 2.0). Making it 2.0 mm would mean widening only the inner faces of the bores. It stays at pitch − bore, and the slicer lays it as about five lines.
- At the bottom end (−y) of the collars, the wall meets the outer collar wall flush. The two inner walls' rounded corners would otherwise have left a 0.66 mm V-groove there.
- Over the power-plug end (+y, above y 26.5), card B's inner collar wall is notched for its plug, as in V29. There, the wall between the cards is card A's 1.2 mm collar wall alone, and card B's plug pocket opens against it.

## Card B's plug next to card A

Both cards have their 8-pin plug on the −x side of the card. Card A's (the −x card's) plug faces outward, as in V29. Card B's plug now faces card A:

- Card B's plug housing starts at its bore edge, x = 1.07 mm. Card A's collar and shell outer face is at x = 0.13 mm, so there is **0.94 mm of clearance**.
- The housing-clearance cut starts at x = 0.77 mm. On that side the pocket wall is card A's shell itself, at x = 0.13 mm, so the pocket is 0.64 mm wider than the clearance box there; that gap is open space, not material.
- **Measure before printing:** the plug model starts exactly at the card's shroud edge. If the real 8-pin housing, or its cable, sticks out past card B's shroud edge towards card A by more than 0.94 mm, it hits card A's collar. In V29 that side is open.
- Card B's cable leaves the pocket towards +y (the card's top edge), through the power notch. In V29 it can also leave sideways into the gap between the branches, which does not exist here.
- The latch is on the plug's +x side, towards card B's centre, so latch access and the release swing are as V29's.
- The plug and latch insertion sweeps have zero collision on both cards (0.0 / 0.0 mm³).

## Checks (gated release, no override)

- **seat_coverage:** 0.0 mm² uncovered on each card. The open area through the connector clearances is 21.48 mm² per card, the same as V29 and within the 24 mm² budget. The seat seals the whole card face over the fin stack except the plug-housing and latch clearances. This includes card B's face beside the shared wall.
- **Overhang and seal:** no overhang beyond 45°, no void and no leak (seal gate).
- **Slicer:** Bambu Studio with automatic supports adds 0 g of support.
- **Solid material:** in the fan plate and flange fillet as before, and in the **shared collar wall between adjacent cards**, a named, param-derived allowlist entry. Also in V29's seat seal pieces (about 191 mm³ per card) and the seat-corner fill (about 30 mm³, card A; card B's merges into the shared wall).
- **Fan-face coverage:** 0.000001 mm² uncovered. Fin-port obstruction is as V29's (149.4 mm²). Exported with V29's 0.0025 mm simplification tolerance; the STL is about 308k triangles.
- **Fit-check STL:** the top 10 mm of the duct (both GPU openings and collars), as V29's, but now one piece, because the shared wall joins the collars. Print it first. The shared wall must slide between the two installed cards.

Material: 55.3 cm³. P1S / .4 mm / .28 mm PETG: 134.8 min / 64.7 g, the same with or without automatic supports (V29: 143.9 min / 67.7 g).

## CFD (single fan, 2500 rpm, actuator disk, bracket windows)

These numbers come from A28, which was A29's predecessor on this branch: V28 at the 2-slot pitch. V29 changes only the latch notch at the seat, outside the air passage, so the air passage and the CFD model are the same. `duct simulate a28-1fan --preset a28` gave the following, against V28's run with the same model (`runs/v28-1fan`, not rerun on this branch):

| | V28 (3-slot) | A28 = A29's passage (2-slot) |
|---|---|---|
| Flow | 10.290 L/s | 10.368 L/s (+0.8 %) |
| Per card (A / B) | 5.151 / 5.140 L/s | 5.194 / 5.174 L/s |
| Duct total-pressure loss | 0.51 Pa | 0.46 Pa |
| Peak base rise, 250 W per card | 81.55 K | 81.51 K |

The difference is within the mesh noise. No CFD code needed changing for the pitch: the ports, bracket windows, porous zones and exit faceZones all follow `GeometryParams.port_boxes`. The `--shoulder-refine` boxes now follow the card centres too.

The thermal model treats each card as its own fin/base model with adiabatic shroud walls, and has no card-to-card heat path. So it does not show what the empty slot gives in the 3-slot layout: some free convection over card B's PCB back side and card A's shroud. Here those face each other across about 2.2 mm of mostly still air, with the shared wall closing the gap's front 12 mm. Expect card B (whose back faces card A) to run somewhat warmer than the model says. This is not modelled.

Physical fit and printing are untested.
