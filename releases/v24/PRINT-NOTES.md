# DUAL CMP 170HX — V24 uniform walls

V24 makes the outer skin a 1.6 mm offset of the rounded air passage. In V21–V23 the bay fillets rounded only the inside, so the square outer skin left 3–5 mm solid wedges along the pocket rims and shoulders. Those wedges are gone. Away from the splitter web, ray-cast wall thickness in the chamber is 1.62 mm median, 1.63 mm p95 and 2.2 mm p99 (V23: 1.68 / 1.94 / 4.3). Excess over a 1.65 mm shell drops from 4.0 to 0.6 cm³. The splitter web near the fan is still one solid web, 0.4–3.5 mm thick, as in V23. Two 1.6 mm skins would use more plastic there.

Shape changes: outer passage edges rounded (6 mm, eased in from the fan face and faded out before the GPU seat); a 3.5 mm fillet where the body meets the fan plate; collars that meet the body flush, with full-round wall ends at the power notch; a rounded connector-return outline (0.8 mm); and a short flat bottom on the groove between the branches instead of a knife edge. The edges beside the splitter stay as sharp as in V23, because rounding them left a cusp against the solid web. The bay fillet radii are smoothed along the length of the duct.

The bores (38.5 x 98.5 mm), 1.6 mm collar wall, 12 mm collar, 60.96 mm pitch, 120 x 120 x 2.4 mm plate with its 105 mm hole pattern, 70 mm chamber and 82 mm print depth are unchanged. The straight plug/latch sweeps have zero collision. Estimated fin-port obstruction is 149.37 mm², the same as V23. The fan face is fully covered and the part is one watertight body. The local 1.3 mm wall beside the latch clearance remains. The body shell is 1.60 mm (V23 dilated by 1.62 mm), and the connector returns reach 0.3 mm further into the shell. Physical fit is untested.

Material: 81.4 cm³, against 85.0 cm³ for V23. Internal air volume: 583.8 cm³, against 583.9 cm³.

Fan face on the bed. P1S / .4 mm / .28 mm PETG / four walls: 182.9 min / 95.3 g with automatic supports and the same without (V23: 195.9 min / 99.8 g). Both slice without warnings. No floating islands in the layer screen. The worst layer overhang is still the return underside at z ≈ 64.5 mm: 2.53 mm² beyond 45°, against 2.46 mm² in V23. Fewer layers are flagged (11 against 21). Physical support-free printing is untested.

CFD (`duct simulate v24-1fan`, one fan @2500 rpm, 250 W/card): 12.444 L/s, peak base rise 77.598 K, duct loss 0.483 Pa and card-face uniformity 0.851, against 12.444 L/s / 77.599 K / 0.486 Pa / 0.851 for V23. Cooling is unchanged; the gain is plastic and print time.

Known cosmetic residue: faint facet streaks from the 3-D offset (under 0.05 mm), and two small jagged marks where the plug-sweep guard grazes the pocket walls just below the returns.

Preview embeds the exact released STL. Python CAD dependencies: numpy, scipy, trimesh, manifold3d, shapely.
