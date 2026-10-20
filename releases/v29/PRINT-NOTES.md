# DUAL CMP 170HX — V29 tighter seal at the power latch

Layout: one empty slot between the cards (3-slot pitch, 60.96 mm between card centres). For two cards in four consecutive slots (adjacent, 2-slot pitch) use `releases/a29/`.

V29 is V28 with one change: the notch for the power plug's latch lever, beside each plug pocket at the GPU seat, is narrowed to the lever's own envelope. Everything else is V28: the 62 mm fan-to-GPU distance, the bores (38.5 x 98.5 mm), collars, 60.96 mm pitch, the 120 x 120 x 2.4 mm fan plate, 1.2 mm walls, the air passage, the sealed seat beside the pockets, and the 0.3 mm plug-housing clearance.

What changed, and why:

- The photos of the printed V28 show a dark gap between the duct's pocket wall and the card's 8-pin housing. That gap is the latch notch: 3.0 x 8.6 mm of card face beyond the housing clearance, sized from a 3 x 8 mm latch estimate. Air in the fin channels can leave there.
- The cable plug is a Molex Mini-Fit Jr 5557 dual-row receptacle (Molex catalog K-38: 8 circuits, 18.00 mm along the row, 9.60 mm across the rows, 11.60 mm over the latch, 19.60 mm tall). The latch therefore stands 2.0 mm proud of the plug body. The card housing (measured from the photo at the 4.2 mm pin pitch) has a 1.6 mm wall beside the plug, with a 6.0 mm long notch where the latch sits. So the latch pad stands about 0.4 mm proud of the housing.
- V29 lets the latch envelope reach 1.6 mm past the housing: the 0.4 mm pad plus 1.2 mm for the hook to swing out over the header's ramp when the latch is pressed. The envelope is 6.6 mm long (the 6.0 mm notch plus 0.3 mm each end). The clearance around it stays 0.3 mm per side. The duct's notch is now 2.2 x 7.2 mm (V28: 3.6 x 8.6), or 1.6 x 7.2 mm beyond the housing clearance.
- The housing clearance is unchanged at 0.3 mm per side. That gap is not where the visible leak is. Going to 0.25 mm would close only about 1.5 mm² per card and risks a tight fit with a ±0.15 mm print tolerance.

Open card face at the seat, per card, beyond the card's own housing: V28 35.8 mm², V29 21.5 mm² (−40%). Of that, 10.0 mm² is the 0.3 mm ring around the housing and 11.5 mm² is the latch notch (V28: 25.8 mm²). With a plug in, the lever fills part of the notch. The gap left beside it is about 1.5 x 7.2 mm.

Plug and latch:

- Checked against the Mini-Fit Jr envelope swept straight from 26 mm below the seat: the plug body, the latch at rest, and the latch swung out to release all have zero collision with the duct, on both cards.
- The thumb pad sits below the seat, where the bay is open. The room from the pad to the nearest duct wall is the same as V28: 3.1 mm at 4 mm below the seat, 5.2 mm at 9 mm, 6.0 mm from 12 mm down.
- The latch numbers come from the datasheet and the photos, not from a measured part. Before relying on V29, plug the cable in and press the latch with the duct mounted. If the hook catches on the notch wall, measure how far the lever stands out from the housing with calipers. `latch` and `latch_clear` in `duct/params.py` set the notch.

Checks (gated release, no override):

- seat_coverage: 0.0 mm² uncovered on each card. Open area through the connector clearances is 21.5 mm² per card, within the new 24 mm² budget (V23–V28: 35.4–35.8 mm², which now fail it).
- No overhang beyond 45°, no void or leak (seal gate). Bambu Studio with automatic supports adds 0 g of support.
- Solid material only in the seat-corner fills (61.6 mm³ total) and the latch-side seal pieces (382 mm³ total; V28: 228 mm³). The narrower notch leaves more seal beside the latch, all within 4 mm of the seat and named in the solid allowlist.
- Fan-face coverage: 0.000001 mm² uncovered. V29 is exported with a 0.0025 mm simplification tolerance (V28: 0.004). From 0.0028 to 0.006 mm, simplification leaves a 3-edge crack at card B's seal ramp. From 0.008 mm up, it leaves the fan-rim sliver. The STL is about 323k triangles, 16 MB.

Material: 58.1 cm³. P1S / .4 mm / .28 mm PETG: 143.9 min / 67.7 g, the same with or without automatic supports (V28: 143.8 min / 67.6 g).

Optional, not built: a soft gasket for the gap left beside the lever. Use an adhesive-backed closed-cell silicone sponge strip, 1.5 mm thick, about 7 x 3 mm. Stick it to the outer wall of each latch notch, the side facing away from the plug. It closes most of the remaining ~11 mm² against the lever, and it is soft enough that the hook can push into it when you press the latch. If pressing the latch gets noticeably stiffer, remove the strip.

The fit-check STL is the top 10 mm of the duct (both GPU openings and collars), the same as V28's. Physical fit and printing are untested.
