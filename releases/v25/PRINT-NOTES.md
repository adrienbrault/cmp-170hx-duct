# DUAL CMP 170HX — V25 three-perimeter walls

V25 is V24 with a 1.2 mm shell and collar wall instead of 1.6 mm, so a 0.4 mm nozzle lays exactly three perimeters instead of four (Arachne; slicing with wall_loops 3 or 4 gives the same result). The rounded air passage, bores (38.5 x 98.5 mm), collar position and length, 60.96 mm pitch, 120 x 120 x 2.4 mm fan plate with its 105 mm hole pattern, 70 mm chamber, 82 mm print depth, plug/latch sweeps (zero collision) and estimated fin-port obstruction (149.37 mm²) are all unchanged from V24. Airflow is therefore the same as V24's CFD result: 12.444 L/s at 2500 rpm, peak base rise 77.6 K.

Ray-cast wall thickness: 1.21 mm median, 1.19 mm at the thinnest 0.5 %, nothing under 1.0 mm. The fan plate stays 2.4 mm. The collars are more flexible than V24's; they may slide on more easily and grip slightly less.

Material: 64.1 cm³ (V24: 81.4 cm³). Fan face on the bed. P1S / .4 mm / .28 mm PETG: 164.5 min / 76.2 g with automatic supports, 159.5 min / 74.5 g without (V24: 182.9 min / 95.3 g). Both slice without warnings. Physical fit and support-free printing are untested.

The fit-check STL is the top 10 mm of the duct (both GPU openings and collars); print it first if your previous duct was older than V23.
