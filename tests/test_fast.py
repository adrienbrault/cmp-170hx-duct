"""The fast gate preview (duct.print.fast, `duct verify --fast`): labelled as no release check, never used by the release,
and in agreement with the full gates on the released parts."""
from dataclasses import replace
from pathlib import Path

import manifold3d as mf
import pytest

from duct.params import COLLECTOR_V1, COLLECTOR_V2, COLLECTOR_V3, PRESETS
from duct.print import fast
from duct.print import printability as P

REL = Path(__file__).resolve().parents[1]/'releases'


def _tube(tmp_path):
    """A 1.2 mm walled conduit: passes every gate."""
    tube = (mf.Manifold.cylinder(12, 10, circular_segments=96)-mf.Manifold.cylinder(14, 8.8, circular_segments=96).translate([0, 0, -1]))
    spec = P.PartSpec('tube', wall=1.2, openings=(P.Opening('bore', (0, 12), min_area=100, max_count=1, end_opening=True),),
                      passage_seeds=((0, 0, 6),), caps=((.1, -.25), (11.9, 12.25)))
    stl = tmp_path/'tube.stl'; P.export_stl(tube, stl)
    return stl, spec


def test_preview_is_labelled_and_runs_every_geometric_gate(tmp_path):
    stl, spec = _tube(tmp_path)
    r = fast.preview_gates(stl, spec)
    assert r['passed'] and r['release_check'] is False and 'NOT A RELEASE CHECK' in r['label']
    assert set(r['gates']) == {'unsupported_overhang', 'solid_regions', 'seal', 'seat_coverage'}
    assert r['thresholds']['voxel'] == fast.PREVIEW.voxel and r['preview']['slicer'] == 'not run'
    assert fast.PREVIEW.voxel*2 <= 1.2   # still two voxels across the thinnest wall


def test_release_runs_the_full_gates(monkeypatch):
    """The release gate always uses the full thresholds, whatever the preview uses."""
    from duct.print import release
    seen = []
    monkeypatch.setattr(release.printability, 'run_gates', lambda stl, spec, t=P.Thresholds(), slicer=None, **_: (
        seen.append(t), dict(passed=False, failed=['seal'], gates={'seal': dict(passed=False, failures=[])}))[1])
    with pytest.raises(release.PrintabilityError):
        release._gate('x.stl', None, None, None)
    assert seen == [P.Thresholds()] and seen[0] != fast.PREVIEW


def test_cli_fast_flag(monkeypatch, capsys):
    from duct import cli
    assert cli.main(['verify']) == 2     # the full check needs an STL
    calls = []
    monkeypatch.setattr(fast, 'preview_duct', lambda g, stl=None, version=None, slicer=None: (calls.append((g, stl, version, slicer)), dict(
        passed=True, preview=dict(triangles=1, seconds=0.1, slicer='not run'), gates={'seal': dict(passed=True, failures=[])},
        plug_latch_collisions_mm3=[0.0, 0.0]))[1])
    assert cli.main(['verify', '--fast', '--no-slice', '--preset', 'v29', '--param', 'upper_radius=5']) == 0
    assert calls == [(replace(PRESETS['v29'], upper_radius=5.0), None, 'preview', None)]
    out = capsys.readouterr().out
    assert 'NOT A RELEASE CHECK' in out and 'seal pass' in out


def test_draft_is_never_released(monkeypatch):
    """draft(g): only the shell dilation is coarser, under its own type (its own cache key); release refuses it before
    building, and `duct verify --fast --draft` previews it labelled as draft."""
    from duct import cache
    from duct.params import V29
    from duct.print import release
    d = fast.draft(V29)
    assert isinstance(d, fast.DraftParams) and d != V29 and replace(d, upper_radius=1.0).__class__ is fast.DraftParams
    assert {f for f in V29.__dataclass_fields__ if getattr(d, f) != getattr(V29, f)} == set(fast.DRAFT)
    roots = cache._KINDS['duct'][2]
    assert cache.key('duct', d, roots) != cache.key('duct', V29, roots)
    monkeypatch.setattr(release, 'build_duct', lambda g: pytest.fail('release built draft params'))
    with pytest.raises(ValueError, match='draft'):
        release.release(d, 'releases/never', release.NOTES['v29'], slice_=False)
    from duct import cli
    calls = []
    monkeypatch.setattr(fast, 'preview_duct', lambda g, stl=None, version=None, slicer=None: (calls.append((g, version)), dict(
        passed=True, draft=True, preview=dict(triangles=1, seconds=0.1, slicer='not run'), gates={'seal': dict(passed=True, failures=[])}))[1])
    assert cli.main(['verify', '--fast', '--draft', '--no-slice', '--preset', 'v29']) == 0
    assert calls == [(fast.draft(V29), 'draft')] and type(calls[0][0]) is fast.DraftParams
    assert cli.main(['verify', '--draft', '--preset', 'v29', 'x.stl']) == 2              # never on the full check
    assert cli.main(['verify', '--fast', '--draft', '--part', 'collector']) == 2


# --- agreement with the full gates on the released parts (slow) --------------------------------------------------------

PARTS = [('v25', 'continuous-v25', 'duct'), ('v27', 'continuous-v27', 'duct'), ('v28', 'continuous-v28', 'duct'),
         ('v29', 'continuous-v29', 'duct'), ('a29', 'continuous-a29', 'duct'),
         ('collector-v1', 'collector-v1', COLLECTOR_V1), ('collector-v2', 'collector-v2', COLLECTOR_V2),
         ('collector-v3', 'collector-v3', COLLECTOR_V3)]
# The full gates on the released STLs: V25's return tips, pocket wedges and 3 x 8.6 mm latch notch; V27's exposed pocket
# corners; V28's latch notch over the open-area budget (V29 narrowed it).
EXPECTED_FAILS = {'v25': {'unsupported_overhang', 'solid_regions', 'seat_coverage'}, 'v27': {'seat_coverage'}, 'v28': {'seat_coverage'}}


@pytest.mark.parametrize('name, stem, part', PARTS, ids=[p[0] for p in PARTS])
def test_preview_agrees_with_the_full_gates(name, stem, part):
    stl = REL/name/f'dual-170hx-{stem}.stl'
    spec = P.duct_spec(PRESETS[name]) if part == 'duct' else P.collector_spec(part)
    full = P.run_gates(stl, spec); preview = fast.preview_gates(stl, spec)
    verdicts = lambda r: {k: (g['passed'], len(g['failures'])) for k, g in r['gates'].items()}  # noqa: E731
    assert verdicts(preview) == verdicts(full)   # the same gates fail, with as many findings
    assert set(full['failed']) == EXPECTED_FAILS.get(name, set())
