# Fractal plug fit gauge (photo estimates)

A flat test plate shaped like the face of the planned plug collector for your case: it sits inside the recessed slot bay, over the two cards and the middle slot only. Slots 1 and 7 stay open. It is built from photo estimates (±8 %), not measurements. Print it first and check the fit; your observations plus the measurement list then fix the real collector.

## Print

- `fractal-plug-fit-gauge.stl`: one piece, 108 × 124 × 7.6 mm. A 1.4 mm plate, with four spring hooks standing up from it.
- Print it as exported: the plain face on the bed, hooks pointing up. No supports. PETG.
- 0.28 mm layers: about 18.5 min of printing, plus about 7 min of printer start sequence. 7.6 g.
- All printability gates pass, and the slicer adds no support and reports no unsupported overhang (see `checks.json`).
- **The hooks:** each one is a short post with a barb, on a thin tongue printed flat into the plate. The tongue is the spring: it bends sideways in the plate's plane, so its layers run along it and it doesn't snap. The barbs are a gauge version of the collector's clips: they sit at the same spot behind the bracket plate, but their catch face is a little shallower so they print without support, and a firm straight pull releases them.

## Use

1. **Which face goes in:** the face with the hooks and the cut-in letters goes against the case. The letters read correctly on that face: "TOP ▲" points toward the bracket tops and the hex vent, "A" goes on the I/O side and "B" on the PSU side. Check this before you turn it round to fit it.
2. **Fit:** top to bottom, the plate should drop into the recess with a small gap at the top and bottom walls (designed: 0.5 mm each). Its side edges don't touch the recess walls: each one stops on a raised divider bar, the bar between card A and slot 1 and the bar between card B and slot 7.
   - If it won't go in top to bottom, measure how much it overlaps the wall.
   - If it rattles top to bottom, measure the gap.
   - Note whether it stops on the divider bars or on the recess floor.
3. **Card cutouts:** each long cutout's two side edges should run along the middle of a raised divider bar. You should see half of each bar inside the cutout and one more bar crossing the middle of the card's vent window. Note any offset, in mm and to which side.
4. **Middle slot and outer slots:** the solid strip under TOP should completely hide the middle slot, with no opening peeking out beside or below it. Slot 1 (the louvred blank) and slot 7 stay fully visible beside the plate. Each side edge should sit on its bar, about 0.5 mm short of the slot 1 or slot 7 opening, and must not overhang it.
5. **Top and bottom:** at the top of each cutout you should just see the top edge of the card bracket. The bottom edge of each cutout should sit at the end of the slot openings, on the flat floor band of the recess.
6. **Hooks:** press the gauge straight in. Each hook should slide into its card's vent window right at the window's outer edge, flex inward, and click behind the bracket plate. It should then hold the gauge flat on the bars with almost no play. The posts allow for the 1 mm of foam the real plug will have, so this matches the real latch position.
   - If a hook lands on the bezel or a screw instead of in the window, note how far off it is and in which direction.
   - Note whether each hook won't go in, clicks but is loose (how much play), or holds.
   - To take the gauge off, pull it straight out firmly, or push each hook toward the middle of its window.
7. **Photo:** take a photo square-on, with a ruler in frame, and send it along with the measurements.
