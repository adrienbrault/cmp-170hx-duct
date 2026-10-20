# DUAL CMP 170HX — V23 upper shoulders

New upper shoulder blends: 6 mm requested maximum, limited by available space locally, tapering to 1.5 mm at the GPU face. Existing lower 6–8 mm blends remain. Same nominal 38.5 x 98.5 mm bores, 1.6 mm collar walls, 120 x 120 x 2.4 mm plate, 70 mm chamber, 82 mm print depth. Straight plug/latch sweeps and estimated fin-port clearance pass. Serialized collar section deviates from V18 by at most 0.0069 mm after mesh simplification. Physical fit remains untested.

Additional local fillet material versus V22: 0.44 cm³. The rest remains a thin shell.

Fan face on the bed. P1S / .4 mm / .28 mm PETG / four walls: 195.9 min / 99.8 g with automatic supports; 195.6 min / 99.7 g without. Both slice without warnings. No floating islands in the layer screen; small local return overhangs remain. Physical support-free printing is untested.

The 0/3/6/9 mm radius study is running. Radius sizes are geometric requests subject to local space and outlet clearance. No optimality or physical cooling gain is established. See rounding-study-v23.html.

Preview embeds the exact released STL. Preview normal weighting was updated for tiny triangulation facets; actual rounding is also verified in exported STL sections. Python CAD dependencies: numpy, trimesh, manifold3d, shapely.
