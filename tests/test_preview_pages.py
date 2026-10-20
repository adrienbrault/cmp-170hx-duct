"""Release preview pages: the collector is drawn whenever one applies to the layout, with or without a CFD field, and an
embedded field is the run the page declares (duct.viz.web.RELEASE_PAGES) for the collector it draws."""
import json
import re
from pathlib import Path

import pytest

from duct.params import A29, A30, PRESETS, V29, V30
from duct.print.layouts import RELEASES, releases
from duct.viz.web import CASE_PAGES, FLAT, PLUG_DRAFT, collector_fits, collector_version, release_pages, slots, source_kind

FIRST_PUSH_PULL = 27   # v23-v25 are single-fan pages from before the case rear and the collector


def _page(path: Path) -> dict:
    text = path.read_text()
    blob = lambda k: re.search(rf'<script type="application/json" id="{k}">(.*?)</script>', text, re.S)[1]  # noqa: E731
    return dict(text=text, meshes=json.loads(blob('meshData')), airflow=json.loads(blob('airflowData') or 'null'))


DUCTS = [r for r in releases() if r.kind == 'duct']
PAGES = [(r.name, page, run) for r in DUCTS for page, run in release_pages(r.name).items()]


def test_every_preview_page_is_declared():
    on_disk = {(p.parent.name, p.name) for r in DUCTS for p in r.path.glob('preview*.html')}
    assert on_disk == {(v, p) for v, p, _ in PAGES}


@pytest.mark.parametrize('version', [r.name for r in DUCTS if r.number >= FIRST_PUSH_PULL])
def test_preview_draws_the_collector(version):
    """Every page of a push-pull-era release draws a collector shell (not just the pull fan) and the case rear it sits on.
    Case-view releases: preview.html is the Fractal bay with the plug, labelled DRAFT; preview-flat.html the flat panel with
    the layout's released collector."""
    g = PRESETS[version]; pages = release_pages(version)
    for page in pages:
        m = _page(RELEASES/version/page)['meshes']
        coll, hw = m['collector'], m['hardware']
        assert coll and coll.get('faces', 0) > 1000 and coll.get('fan'), (version, page)
        assert hw and (hw.get('bracket_A') or hw.get('bracket_plates')), (version, page)
        if set(pages) != set(CASE_PAGES):
            continue
        case = m['case']
        if CASE_PAGES[page] == 'fractal':
            assert coll['kind'] == 'plug' and 'DRAFT' in coll['label'] and case['key'] == 'fractal'
            assert {'divider_bars', 'floor', 'rear_panel'} <= set(hw) and 'slot_ledge' not in hw
            assert {k['name'] for k in case['keepouts']} == {'hex vent', 'PSU face', 'PSU inlet and cable', 'I/O shield cables'}
            assert case['note'].startswith(PLUG_DRAFT)
            assert ('half a slot' in case['note']) == (slots(g) == 4)
            text = _page(RELEASES/version/page)['text']
            assert PLUG_DRAFT in text and 'class="layout-switch case-switch"' in text
        else:
            assert coll['kind'] == FLAT[slots(g)] and case['key'] == 'flat' and 'slot_ledge' in hw


@pytest.mark.parametrize('version,page,run', PAGES)
def test_embedded_field_is_the_declared_run(version, page, run):
    """The field is the declared run's (or none), the run modelled the collector the page draws, and the drawn collector's
    fan face is where the run put it (else the badge says so)."""
    p = _page(RELEASES/version/page); af = p['airflow']
    if run is None:
        assert af is None
        if (p['meshes'].get('case') or {}).get('note'):
            assert 'no CFD run for this view yet' in p['meshes']['case']['note']
        return
    assert af and af['meta']['case'] == run
    g = PRESETS[version]
    src = (af['meta'].get('collector') or {}).get('source')
    kind = source_kind(src, g) if src else collector_version(Path(run), None, g)   # older pages: from the run name
    coll = p['meshes']['collector']
    if kind and coll and coll.get('kind'):
        assert coll['kind'] == kind, (version, page, kind, coll['kind'])
    if af['meta'].get('collector') and coll and coll.get('kind'):
        assert "field's exhaust fan face is" not in af['meta']['badge']


def test_collector_recognised_from_run_and_source():
    assert source_kind('duct.cad.plug COLLECTOR_PLUG_BASE in CASE_FRACTAL (photo estimates), top dam', V30) == 'plug'
    assert source_kind('duct.cad.exhaust COLLECTOR_V4A', A30) == 'v4-4slot'
    assert source_kind('duct.cad.exhaust COLLECTOR_V4A', V30) == 'v4-5slot'
    assert source_kind('duct.cad.exhaust COLLECTOR_V4B', V30) is None        # not a released collector
    assert source_kind('duct.cad.exhaust COLLECTOR_V3', V30) == 'v3'
    assert collector_version(Path('a30-pp-plug'), None, A30) == 'plug'
    assert source_kind('duct.cad.plug COLLECTOR_PLUG_140 in CASE_FRACTAL (photo estimates), top dam', V30) == 'plug140'
    assert collector_version(Path('v30-pp-plug140'), None, V30) == 'plug140'
    assert collector_version(Path('v30-pp-plug-r2'), None, V30) == 'plug'
    assert collector_version(Path('a30-pp-v4a'), None, A30) == 'v4-4slot'
    assert collector_version(Path('v28-pp-v3'), None, V29) == 'v3'


def test_collectors_per_layout():
    assert collector_fits(V29, 'plug') and collector_fits(A29, 'plug')
    assert collector_fits(A29, 'v4-4slot') and not collector_fits(V29, 'v4-4slot')
    assert collector_fits(V29, 'v3') and not collector_fits(A29, 'v3')
    for g in (V29, A29):
        assert (RELEASES/f'collector-{FLAT[slots(g)]}'/f'dual-170hx-collector-{FLAT[slots(g)]}.stl').exists()


def test_layout_switch_keeps_the_case_view(tmp_path):
    """The slot-layout switcher of a case page links the sibling's page of the same case when it has one."""
    from duct.print.layouts import layout_links
    for d in ('v29', 'a29', 'v30', 'a30'):
        (tmp_path/d).mkdir(); (tmp_path/d/f'dual-170hx-continuous-{d}.stl').write_text('')
    hrefs = lambda name, page: [l['href'] for l in layout_links(name, tmp_path/name/page, tmp_path)]  # noqa: E731
    assert hrefs('a30', 'preview-flat.html') == ['../v30/preview-flat.html', 'preview-flat.html']
    assert hrefs('v30', 'preview.html') == ['preview.html', '../a30/preview.html']
    assert hrefs('a29', 'preview-flat.html') == ['../v29/preview.html', 'preview-flat.html']   # v29 has one page


def test_recess_page_parts():
    """The Fractal bay as drawn: the border is a sheet (not the fit check's solid block), the louvred blank is in slot -3 of
    the 5-slot layout (no such slot in the 4-slot model), the keep-outs are boxes and the empty slots are labelled."""
    from duct.cad.hardware import CASE_FRACTAL
    from duct.cad.plug import build_recess_hardware, recess_page_parts
    from duct.viz.web import collector_params
    for g, expect in ((V30, {'slot -3 · louvred blank', 'slot 0 · open', 'slot +3 · open'}),
                      (A30, {'slot -2.5 · open', 'slot +2.5 · open'})):
        c = collector_params('plug', g); case = CASE_FRACTAL.for_pitch(g.pitch)
        p = recess_page_parts(g, c, case); hw = build_recess_hardware(g, c, case)
        assert ('vented_covers' in p['parts']) == (slots(g) == 5)
        assert p['parts']['rear_panel'].volume() < hw['parts']['border'].volume()/5
        assert p['parts']['rear_panel'].bounding_box()[5] == pytest.approx(hw['border_plane'])
        assert {l['text'] for l in p['labels'] if l['text'].startswith('slot')} == expect
        assert all(k['max'][2] > k['min'][2] >= hw['border_plane']-1e-6 for k in p['keepouts'])
        if 'vented_covers' in p['parts']:   # behind the floor: nothing of the plug can reach it
            assert p['parts']['vented_covers'].bounding_box()[5] <= hw['z_b']+1e-6


def test_release_page_without_a_field_draws_the_collector(tmp_path):
    """No run: the page still draws the collector for the layout and says it has no field (a new release's path)."""
    from duct.viz.web import write_release_preview
    for version, collector in (('a29', 'plug'), ('a29', 'v4-4slot')):
        m = _page(write_release_preview(version, tmp_path/f'{collector}.html', collector))
        assert m['airflow'] is None and m['meshes']['collector']['kind'] == collector
        assert 'no CFD run for this view yet' in m['meshes']['case']['note']
