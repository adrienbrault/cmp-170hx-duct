# DUAL CMP 170HX — V27 support-free connector returns

V27 is V25 with redesigned connector returns. The air passage, bores (38.5 x 98.5 mm), collars, 60.96 mm pitch, 120 x 120 x 2.4 mm fan plate with its 105 mm hole pattern, 70 mm chamber, 82 mm print depth, 1.2 mm walls and the plug/latch insertion sweeps (zero collision) are unchanged, so airflow is V25's (= V24's).

What changed, beside each power-plug pocket:

- The outer skin now follows the rounded bay corners (the 6–8 mm passage and upper fillets) all the way to the GPU seat. V25 squared the skin off over the last 18 mm to carry the square returns, which left solid corner wedges of about 250 mm³ per card (card-local x ≈ −18, y 19–26 and x ≈ +2, y ≈ 49, z 52–70). In V27 the wall is a uniform 1.2 mm there.
- The square returns are gone. All that remains is a small seat frame:
  - the collar's footprint where it overhangs the rounded shell;
  - the seat face between the rounded air corner and the square bore;
  - a lip flush with the plug-pocket floor (y 27.2).
- The frame's underside grows out of the rounded shell at 40° from vertical, so it is never deeper than about 4 mm (z ≥ 65.9). The latch side of the pocket is the shell's own 1.2 mm bay wall, 0.1 mm from the latch clearance. The old 4.3 mm solid latch-side return is gone. Below the collar's underside (z 69.6) the frame's outer faces step in by 0.1 mm, a deliberate offset that keeps them off the dilated shell wall for a clean mesh; it does not show in print.

Printability (fan face on the bed):

- Bambu Studio with automatic supports adds 0 g of support. V25 added 1.75 g under the latch-side return tips, which stuck 0.4 mm past the 1.2 mm shell because `return_rect` was sized for V24's 1.6 mm wall.
- No overhang beyond 45° anywhere (layer gate), and no void or leak in any layer or in 3-D (seal gate).
- Solid material (where a 1.6 mm ball fits): none below z 66.9 (L − 3.1). V25 had 53–62 mm² per layer from z 56 up and 228 mm² per layer at z 66–70. What remains is the seat-corner fill (about 15 mm³ per card, at most 2.7 mm wide, z 66.9–69.7) and the 2.3 mm pocket-floor lip. Both are needed: the seat face must close between the rounded air corner and the square bore, and the collar must be carried without a cavity or a hanging ledge.

Material: 63.1 cm³ (V25: 64.1 cm³). P1S / .4 mm / .28 mm PETG: 153.8 min / 73.3 g, the same with or without automatic supports (V25: 164.5 min / 76.2 g with supports, 159.5 min / 74.5 g without). Physical fit and printing are untested.

The fit-check STL is the top 10 mm of the duct (both GPU openings and collars), the same as V25's.

A 55 mm variant (`V27S`, chamber_length 55) builds with the same frame and also slices with 0 g of support (133.4 min / 62.1 g). Its internal bay-floor ramp is steeper (up to 56°, z 2–27) because the 26 mm plug sweep compresses the pocket transition, so it is not released here.
