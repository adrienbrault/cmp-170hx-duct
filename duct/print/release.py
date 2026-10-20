"""Assemble releases/<version>/: STL, fit gauge, checks, slicer numbers, print notes and preview (duct) or the exhaust collector."""
import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import trimesh

from ..cad.exhaust import build_collector
from ..cad.export import collector_names, export_collector, export_duct, fit_check_name, stl_name
from ..cad.geometry import build_duct
from ..params import CollectorParams, GeometryParams
from . import printability
from .slice import slice_stl
from .verify import mesh_quality, normal_audit, verify, verify_collector

CFD_STATUS = 'Controlled 0/3/6/9 mm upper-shoulder radius screening is running; no optimality claim.'

NOTES = {'v23': dict(
    version='V23', prev_version='V22', headline='rounded upper shoulders', features='Upper shoulder blends · rounded splitter · hollow shell',
    note='V23 also blends the marked upper shoulders into the passage roofs. The requested 6 mm radius is constrained locally and tapers to 1.5 mm near the GPU face, keeping the modeled fin openings clear. The earlier lower 6–8 mm blends remain. The local changes add 0.44 cm³ of material versus V22; nominal shell and collar dimensions remain. P1S/PETG: {minutes:.0f} min / {grams:.1f} g. A controlled radius sweep is running; 6 mm is not an established airflow optimum.',
    section_title='upper shoulder blends',
    section_text='The newly marked upper corners have broad blends, tapering near the GPU to preserve the vent openings. These sections compare the actual V22 and V23 STL geometry at 40 mm from the fan. The geometry alone does not establish a cooling improvement.',
    section_alt='Actual exported V22 and V23 sections: upper sharp corner replaced by a broad blend'),
    'v24': dict(
    version='V24', prev_version='V23', headline='uniform 1.6 mm walls', features='Uniform shell · rounded edges · flange fillet · flush collars',
    note='V24 derives the outer skin from the rounded air passage, so the V21–V23 fillets no longer leave 3–5 mm solid wedges in the walls. Convex passage edges are rounded (6 mm, fading before the GPU seat), the plate-to-body junction has a 3.5 mm fillet and the collars meet the body flush. Bores, collars, plate, sweeps and port clearance are unchanged. P1S/PETG: {minutes:.0f} min / {grams:.1f} g. No airflow change is claimed.',
    section_title='uniform walls',
    section_text='V23 rounded only the inside of the bay corners; the outer skin stayed square, which left solid wedges. V24 offsets the shell from the rounded air volume, so the wall stays at about 1.6 mm around every fillet. The geometry alone does not establish a cooling change.',
    section_alt='Actual exported V23 and V24 sections: corner wedges replaced by a uniform wall'),
    'v25': dict(
    version='V25', prev_version='V24', headline='1.2 mm walls', features='Three-perimeter shell · V24 shape',
    note='V25 is V24 with a 1.2 mm shell and collar wall, so the slicer lays exactly three 0.4 mm perimeters instead of four. Shape, bores, collar position, plate, sweeps and port clearance are unchanged. P1S/PETG: {minutes:.0f} min / {grams:.1f} g. No airflow change: the air passage is identical to V24.',
    section_title='three-perimeter walls',
    section_text='The same rounded air passage as V24, offset by 1.2 mm instead of 1.6 mm.',
    section_alt='Actual exported V24 and V25 sections: the same passage with a thinner shell'),
    'v27': dict(
    version='V27', prev_version='V25', headline='support-free connector returns', features='Rounded skin to the seat · chamfered seat frame · no wedges',
    note='V27 lets the outer skin follow the rounded bay corners all the way to the GPU seat, so the 1.2 mm wall no longer thickens into solid wedges beside the power-plug pockets. The square connector returns are replaced by a small seat frame (collar footprint and pocket-floor lip) whose underside grows out of the rounded shell at 40 degrees: it prints without support, leaves no cavity, and the slicer adds 0 g of support (V25: 1.75 g under the latch-wall tips). Air passage, bores, collars, plate and plug/latch clearance are unchanged from V25. P1S/PETG: {minutes:.0f} min / {grams:.1f} g.',
    section_title='support-free returns',
    section_text='The same air passage and 1.2 mm shell as V25; only the connector returns and the skin next to them change.',
    section_alt='Actual exported V25 and V27 sections'),
    'v28': dict(
    version='V28', prev_version='V27', headline='sealed seat, 8 mm shorter', features='Sealed card face beside the plug pockets · 62 mm fan-to-GPU · support-free',
    note='V28 closes the card face that V27 left exposed at the GPU seat beside each power-plug pocket, between the plug housing clearance and the rounded bay wall. The fin channels run across the card, so an open channel end there let the pressurized air escape. The seat now covers everything over the fin stack except the plug and latch clearances, grown from the bay-wall shell at 40 degrees so it still prints without support. The fan-to-GPU distance is also cut from 70 to 62 mm (total depth 74 mm); CFD shows no airflow cost from the shorter chamber. P1S/PETG: {minutes:.0f} min / {grams:.1f} g.',
    section_title='sealed seat',
    section_text='The V27 passage, compressed from 70 to 62 mm, with the seat closed beside the plug pockets.',
    section_alt='Actual exported V27 and V28 sections'),
    'v29': dict(
    version='V29', prev_version='V28', headline='tighter seal at the power latch', features='Latch notch shaped to the lever · 40% less open card face · support-free',
    note='V29 narrows the latch notch beside each power-plug housing from 3.0 x 8.6 mm to 1.6 x 7.2 mm past the housing clearance, sized to the Molex Mini-Fit Jr plug (9.6 mm body, 11.6 mm over the latch) and the 6 mm latch notch of the card housing: the lever pad stands 0.4 mm proud of the housing, the hook swings 1.2 mm out to unlatch, plus 0.3 mm clearance. Exposed card face per card at the seat drops from 35.8 to 21.5 mm2. The housing clearance stays 0.3 mm per side. Everything else is V28. These latch numbers are estimated from the datasheet and photos: check the plug latches and unlatches before relying on it. P1S/PETG: {minutes:.0f} min / {grams:.1f} g.',
    section_title='tighter latch notch',
    section_text='The same passage as V28; only the seat beside the plug latch changes.',
    section_alt='Actual exported V28 and V29 sections'),
    'a29': dict(
    version='A29', prev_version='V29', headline='adjacent slots (2-slot pitch)', features='Cards in four consecutive slots · 40.64 mm pitch · one shared 2.14 mm wall between the cards',
    note='A29 is V29 for two cards in adjacent slots (four consecutive slots, 2-slot pitch: 40.64 mm between card centres) instead of one empty slot between them (V29, 3-slot pitch: 60.96 mm). The bores are only 2.14 mm apart, so the two inner collar walls become one shared 2.14 mm wall that slides between the cards and is also the splitter web from the fan face to the collar top. Bores, outer collars, seat seal, plug pockets, 1.2 mm walls and the 62 mm chamber are V29\'s, including its lever-shaped latch notch; the plug and latch sweeps have zero collision, including the inner plug next to the shared wall. P1S/PETG: {minutes:.0f} min / {grams:.1f} g.',
    section_title='shared wall between the cards',
    section_text='The V29 passages, pulled 20.32 mm closer together: the splitter web never parts into two skins and continues through the seat as one wall between the two cards.',
    section_alt='Actual exported V29 and A29 sections'),
    'v30': dict(
    version='V30', prev_version='V29', headline='hub fairing behind the fan', features='Ogive fairing behind the motor hub · 59% less dead core · support-free',
    note='V30 adds a hub fairing to V29: a hollow 1.2 mm shell of revolution on the fan axis, 50.5 mm across where it meets the fan and tapering toward a point 35 mm downstream; the splitter web runs whole through it and carries it, and nothing of it stands in the gap between the two web skins. Behind the fan motor the air has nowhere to come from, so V29 holds a slowly recirculating core there; the fairing fills it. Its inside is open toward the fan and closes as two 44 degree half cones either side of the web, so it prints fan-face down without support. CFD, single fan, same mesh: reverse-flow volume in the hub core 18.0 to 7.5 cm3 (-59%), duct loss 0.229 to 0.223 Pa; flow (9.13 L/s) and peak GPU rise (87.2 K) are unchanged. On a second mesh and with a rounded fan inlet in the model the core reduction holds (52-61%) but the loss change shrinks to almost nothing: a cleaner flow, not a cooling gain. The rim lands on the flat rear face of the fan motor housing: about 52 mm across on a P12 Pro PST CO (measured from a photo against the 105 mm hole spacing, ±1 mm), so the 50.5 mm rim sits about 0.75 mm inside its edge. Everything else is V29. P1S/PETG: {minutes:.0f} min / {grams:.1f} g.',
    section_title='hub fairing',
    section_text='The V29 passage with the fairing on the fan axis: the splitter web\'s two skins meet at its tip.',
    section_alt='Actual exported V29 and V30 sections'),
    'a30': dict(
    version='A30', prev_version='A29', headline='hub fairing behind the fan (adjacent slots)', features='Ogive fairing behind the motor hub · 65% less dead core · 2-slot pitch',
    note='A30 is A29 (adjacent cards, 40.64 mm pitch) with the V30 hub fairing: a hollow 1.2 mm shell of revolution on the fan axis, 50.5 mm across at the fan, tapering to a point 35 mm downstream inside the shared wall. It fills the slowly recirculating core behind the fan motor. Its inside is open toward the fan and closes as a 44 degree cone, so it prints fan-face down without support. CFD, single fan, same mesh: reverse-flow volume in the hub core 23.8 to 8.2 cm3 (-65%), duct loss 0.198 to 0.188 Pa; flow (9.13 L/s) and peak GPU rise (87.5 K) are unchanged. On a second mesh and with a rounded fan inlet in the model the core reduction holds (57-63%) and the loss drops 2-3%: a cleaner flow, not a cooling gain. The rim lands on the flat rear face of the fan motor housing: about 52 mm across on a P12 Pro PST CO (measured from a photo against the 105 mm hole spacing, ±1 mm), so the 50.5 mm rim sits about 0.75 mm inside its edge. Everything else is A29. P1S/PETG: {minutes:.0f} min / {grams:.1f} g.',
    section_title='hub fairing',
    section_text='The A29 passages with the fairing on the fan axis, merging into the shared wall.',
    section_alt='Actual exported A29 and A30 sections')}


class PrintabilityError(RuntimeError):
    """A part failed the printability/seal gates (duct.print.printability) and no override was given."""


def _gate(stl, spec, gcode, override: str | None, sliced=None) -> dict:
    """Run every printability gate (the slicer gate on the automatic-supports G-code, when there is one, once `sliced()`
    returns: the slice may still be running); raise PrintabilityError on a failure unless `override` gives the reason,
    which is then appended to PRINT-NOTES.md."""
    gates = printability.run_gates(stl, spec, slicer=None if gcode is None else dict(gcode=gcode), slicer_after=sliced)
    if gcode is None: gates['slicer_support'] = 'not run (no slice)'
    if not gates['passed']:
        lines = printability.failure_lines(gates)
        if not override:
            raise PrintabilityError(f'{Path(stl).name}: {printability.summary_line(gates)}\n  '+'\n  '.join(lines)+
                                    '\nFix the geometry, or pass an explicit override reason (noted in PRINT-NOTES.md).')
        gates['override'] = override
    return gates


def _note_override(notes_md: Path, gates: dict):
    if 'override' not in gates: return
    text = notes_md.read_text() if notes_md.exists() else ''
    entry = (f"\n## Printability override\n\nReleased although these gates fail: {', '.join(gates['failed'])}. "
             f"Reason: {gates['override']}\n\n"+'\n'.join(f'- {x}' for x in printability.failure_lines(gates))+'\n')
    if entry not in text: notes_md.write_text(text.rstrip('\n')+'\n'+entry)


def release(params: GeometryParams, out_dir, notes: dict, slice_: bool = True, override: str | None = None) -> dict:
    """Build, verify, gate and (optionally) slice; write STLs, checks.json, slicer-checks.json and preview.html to out_dir.

    notes: the write_preview keys; `note` may use {minutes} and {grams} from the supports slice.
    The printability gates (duct.print.printability) must pass, or nothing is written: PrintabilityError. `override`
    releases anyway and appends the reason and the failures to PRINT-NOTES.md, which is otherwise hand-written and not
    touched.
    """
    from .fast import DraftParams
    if isinstance(params, DraftParams): raise ValueError('draft geometry (duct.print.fast.draft) is for iteration only: release the real params')
    out = Path(out_dir)
    solids = build_duct(params)
    with tempfile.TemporaryDirectory() as tmp:
        export_checks = export_duct(solids, tmp, out.name)
        stl_tmp = Path(tmp)/stl_name(out.name)
        m = trimesh.load(stl_tmp)
        result = {**export_checks, **verify(stl_tmp, params, solids), 'mesh_quality': mesh_quality(m), 'normal_audit': normal_audit(m, params), 'CFD_status': CFD_STATUS}
        runs = out.parents[1]/'runs' if slice_ else None
        with ThreadPoolExecutor(2) as pool:   # both slices run alongside the geometric gates
            jobs = dict(automatic_supports=pool.submit(slice_stl, stl_tmp, runs/f'slice-{out.name}', True),
                        no_supports_trial=pool.submit(slice_stl, stl_tmp, runs/f'slice-{out.name}-no-supports', False)) if slice_ else {}
            result['printability'] = _gate(stl_tmp, printability.duct_spec(params), runs/f'slice-{out.name}'/'plate_1.gcode' if slice_ else None,
                                           override, jobs['automatic_supports'].result if slice_ else None)
            sc = {k: f.result() for k, f in jobs.items()} if slice_ else None
        out.mkdir(parents=True, exist_ok=True)
        for name in (stl_name(out.name), fit_check_name(out.name)): shutil.copy2(Path(tmp)/name, out/name)
    (out/'checks.json').write_text(json.dumps(result, indent=2))
    if sc is not None:
        (out/'slicer-checks.json').write_text(json.dumps(sc, indent=2))
        a = sc['automatic_supports']
        notes = {**notes, 'note': notes['note'].format(minutes=a['minutes'], grams=a['grams'])}
    _note_override(out/'PRINT-NOTES.md', result['printability'])
    # the preview pages with the collector for the layout and its case rear (no CFD field yet: `duct preview` adds the runs')
    from ..viz.web import write_release_pages
    write_release_pages(out.name, fields=False, out_dir=out, notes=notes, g=params)
    return result


def release_collector(params: CollectorParams, out_dir, slice_: bool = True, override: str | None = None) -> dict:
    """Build, verify, gate and (optionally) slice the exhaust collector; write its STL, fit gauge, checks.json and slicer-checks.json.

    The printability gates must pass (see release). PRINT-NOTES.md is hand-written and not touched, except for an
    override note. There is no preview page (the template is the duct's).
    """
    out = Path(out_dir)
    solids = build_collector(params)
    with tempfile.TemporaryDirectory() as tmp:
        cad = export_collector(solids, tmp, out.name)
        stl_tmp, gauge_tmp = (Path(tmp)/n for n in collector_names(out.name))
        result = {**cad, **verify_collector(stl_tmp, solids)}
        g = trimesh.load(gauge_tmp)
        assert g.is_watertight and len(g.split()) == 1
        result['fit_gauge'].update(watertight=True, one_body=True)
        runs = out.parents[1]/'runs' if slice_ else None
        with ThreadPoolExecutor(3) as pool:   # the slices run alongside the geometric gates
            jobs = dict(automatic_supports=pool.submit(slice_stl, stl_tmp, runs/f'slice-{out.name}', True),
                        no_supports_trial=pool.submit(slice_stl, stl_tmp, runs/f'slice-{out.name}-no-supports', False),
                        fit_gauge=pool.submit(slice_stl, gauge_tmp, runs/f'slice-{out.name}-gauge', False)) if slice_ else {}
            result['printability'] = _gate(stl_tmp, printability.collector_spec(params), runs/f'slice-{out.name}'/'plate_1.gcode' if slice_ else None,
                                           override, jobs['automatic_supports'].result if slice_ else None)
            sc = {k: f.result() for k, f in jobs.items()} if slice_ else None
        if 'snap_clip' in cad:   # mount 'snap': the clips are their own print, gated the same way
            clip = Path(tmp)/cad['snap_clip']['file']
            if slice_: sc['snap_clip'] = slice_stl(clip, runs/f'slice-{out.name}-snap-clip', True)
            result['snap_clip_printability'] = _gate(clip, printability.snap_clip_spec(params), runs/f'slice-{out.name}-snap-clip'/'plate_1.gcode' if slice_ else None, override)
        out.mkdir(parents=True, exist_ok=True)
        for p in Path(tmp).iterdir(): shutil.copy2(p, out/p.name)
    (out/'checks.json').write_text(json.dumps(result, indent=2))
    if sc is not None: (out/'slicer-checks.json').write_text(json.dumps(sc, indent=2))
    _note_override(out/'PRINT-NOTES.md', result['printability'])
    return result
