# DUAL CMP 170HX — V31 2.4 mm collars, sealed latch notch

Layout: one empty slot between the cards (3-slot pitch, 60.96 mm between card centres). For two cards in four consecutive slots (adjacent, 2-slot pitch) use `releases/a31/`.

## What changed, and why

V31 is V30 with two fixes from the printed A30.

**Thicker collars.** The printed A30's collar broke off along the layer line where the 1.2 mm skin bends into it, about 12 mm from the card end. Printed fan face down, that bend is a single layer plane, and a three-line wall bending across layer lines is where PETG is weakest.

- Every collar is now 2.4 mm thick (six 0.4 mm lines, about four times the bending strength), from 6 mm under the seat to the card end.
- The extra 1.2 mm is added outward only, so the bore, the lead-in and the card fit are V30's.
- The band's foot grows out of the collar at 34° from vertical and fills the outside of the bend. It stays within the shell's outline grown upward at that angle, so it stands on skin everywhere and needs no support.
- It stops 2.5 mm short of each power notch. There the skin turns into the plug-pocket floor, which could not carry it.

**Latch notch wall.** The wall on the far side of each power-plug latch notch moves 1 mm toward the plug: the notch is now 1.2 mm wide past the housing clearance instead of 2.2 mm.

- The old wall left about 1 mm of the card's fin tunnel (which starts 5.4 mm from the card centre) open beside the lever, so pressurized air leaked out there.
- Open card face at each seat drops from 21.5 to 14.3 mm².
- The resting lever pad (0.4 mm proud of the housing) keeps 0.5 mm of clearance, and the plug/latch sweep collision stays 0.
- The hook can no longer swing out to unlatch inside the notch. **Pull the duct off before unplugging a card.**
- The lever numbers are datasheet and photo estimates (Molex Mini-Fit Jr). Check the duct slides on over a latched plug before relying on it.

Everything else is V30: the air passage (same internal air volume, 489 cm³), hub fairing, 62 mm fan-to-GPU distance, fan plate and 1.2 mm walls. The airflow is V30's, so the preview pages embed V30's CFD runs.

## Checks (gated release, no override)

- No overhang beyond 45° (as V30), no void or leak (seal gate), seat fully covered except the plug and latch clearances. Solid material only where named in the allowlist: one new entry, the reinforced collar band. Bambu Studio with automatic supports adds 0 g of support: the automatic-support and no-support slices are identical.
- Plug/latch sweep collision 0 mm³ on both cards.
- Material: 70.7 cm³ (V30: 61.9). P1S / .4 mm / .28 mm PETG: 172.4 min / 82.7 g (V30: 156.1 min / 72.1 g).

The fit-check STL is the top 10 mm of the duct: both GPU openings with the new 2.4 mm collars. Physical fit and printing are untested. If the collar still cracks, print PETG hotter with less part cooling for better layer bonding.
