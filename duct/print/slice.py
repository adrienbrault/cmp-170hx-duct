"""Bambu Studio CLI wrapper: slice an STL with the repo's P1S / 0.4 mm / 0.28 mm PETG profiles."""
import json
import subprocess
from pathlib import Path

from ..env import BAMBU

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT/'profiles/slicer'
DATADIR = ROOT/'runs/bambu-datadir'


def slice_stl(stl, out_dir, supports: bool = True, process_overrides: dict | None = None) -> dict:
    """Slice with or without automatic supports; return {minutes, grams, triangle_count, warning}. Gcode, result.json and slice.log land in out_dir.

    process_overrides: process-profile keys to change (e.g. {'bridge_no_support': '1'}); the merged profile is written to out_dir.
    """
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True); DATADIR.mkdir(parents=True, exist_ok=True)
    process = PROFILES/('process-028.json' if supports else 'process-no-supports.json')
    if process_overrides:
        merged = {**json.loads(process.read_text()), **process_overrides}
        process = out/'process.json'; process.write_text(json.dumps(merged, indent=2))
    cmd = [str(BAMBU), '--datadir', str(DATADIR), '--load-settings', f'{PROFILES/"machine.json"};{process}', '--load-filaments', str(PROFILES/'filament.json'),
           '--orient', '0', '--arrange', '1', '--slice', '0', '--outputdir', str(out), str(Path(stl).resolve())]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out/'slice.log').write_text(r.stdout)
    d = json.loads((out/'result.json').read_text())
    p = d['sliced_plates'][0]
    assert d['return_code'] == 0 and not p['warning_message'], (d['error_string'], p['warning_message'])
    return dict(minutes=p['total_predication']/60, grams=p['filaments'][0]['total_used_g'], triangle_count=p['triangle_count'], warning=p['warning_message'])
