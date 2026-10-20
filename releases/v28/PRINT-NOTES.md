# DUAL CMP 170HX — V28 sealed seat, 62 mm

Layout: one empty slot between the cards (3-slot pitch, 60.96 mm between card centres). For two cards in four consecutive slots (adjacent, 2-slot pitch) use `releases/a29/` (V29 is the current 3-slot release).

V28 is V27 with two changes: the GPU seat is sealed again beside each power-plug pocket, and the fan-to-GPU distance is 62 mm instead of 70 (74 mm print depth). The bores (38.5 x 98.5 mm), collars, 60.96 mm pitch, 120 x 120 x 2.4 mm fan plate with its 105 mm hole pattern, 1.2 mm walls and the plug/latch insertion sweeps (zero collision) are V27's. The air passage is V27's, compressed to 62 mm. CFD on the same model shows no airflow cost from the shorter chamber (55–70 mm within 0.06 K).

What was sealed, and why:

- V27 left part of the card's end face uncovered at the seat: about 33 mm² per card, between the plug-housing clearance (card-local x −5.95) and the rounded bay wall (x ≈ −2.9), from the pocket floor (y 27.2) to the top of the fin stack (y 47.4), around the latch clearance. That area is over the fin stack. The fins are horizontal plates whose channels run across the card, so air pushed into a channel from the passage could leave through its open end there: a leak. V25's square latch-side return covered it; V27 had removed that return.
- V28's seat covers every part of the bore over the fin stack (|y| ≤ 47.4, the extent of the card's port boxes) that is neither passage nor plug-housing or latch clearance. Only those two clearances stay open, because the plug and its latch move through them. Above the housing clearance (y 47.8–49.25) the bore is past the fin stack and stays open, as in V25.
- The new seat piece beside each latch is a 3.1 mm cantilever from the shell's bay wall. Its underside is one 40° plane rising from that wall to the housing clearance's edge, about 4 mm deep at the wall. It prints without support, and there is no cavity under it. A thinner sloped skin would have enclosed a cavity for about the same material.

Checks (gated release, no override):

- seat_coverage: 0.0 mm² uncovered on each card (V27: 32.7 / 32.4 mm²; V25: 0.14 / 0.12 mm²).
- No overhang beyond 45°, no void or leak (seal gate). Bambu Studio with automatic supports adds 0 g of support.
- Solid material only in the seat-corner fills (about 31 mm³ per card) and the new latch-side seal pieces (about 114 mm³ per card), all within 4 mm of the seat. Both are named in the solid allowlist with their reasons.
- Fan-face coverage: 0.00001 mm² uncovered. V28 is exported with a 0.004 mm simplification tolerance (V27: 0.01). At 0.005 mm and above, simplification pulls the splitter web's ends about 20 µm off the fan-aperture rim, which left 0.017 mm² of the fan face uncovered in the STL (not in the CAD). The STL is about 243k triangles, 12 MB.

Material: 58.1 cm³. P1S / .4 mm / .28 mm PETG: 143.8 min / 67.6 g, the same with or without automatic supports (V27 at 70 mm: 153.8 min / 73.3 g). Physical fit and printing are untested.

The fit-check STL is the top 10 mm of the duct (both GPU openings and collars), the same as V27's.
