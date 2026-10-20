import json
from pathlib import Path

import pytest

from duct.env import BAMBU
from duct.params import V23
from duct.print.preview import write_preview
from duct.print.release import NOTES
from duct.print.slice import slice_stl
from duct.print.verify import verify

REL = Path(__file__).resolve().parents[1]/'releases/v23'
STL = REL/'dual-170hx-continuous-v23.stl'


@pytest.fixture(scope='module')
def result():
    return verify(STL, V23)


def test_verify_matches_released_checks(result):
    released = json.loads((REL/'checks.json').read_text())
    for k, v in result.items(): assert released[k] == v, k
    assert result['fan_face_uncovered_area_mm2'] < .01
    assert result['layer_audit']['floating_layers'] == []


def test_verify_rejects_tampered_stl(tmp_path):
    import trimesh
    m = trimesh.load(STL); m.update_faces([i != 0 for i in range(len(m.faces))])
    bad = tmp_path/'bad.stl'; m.export(bad)
    with pytest.raises(AssertionError): verify(bad, V23)


def test_preview_embeds_stl(tmp_path):
    import re
    import numpy as np
    from duct.print.preview import decode_mesh, stl_triangles
    out = write_preview(STL, {**NOTES['v23'], 'note': 'n'}, tmp_path/'p.html')
    meshes = json.loads(re.search(r'<script type="application/json" id="meshData">(.*?)</script>', out.read_text(), re.S)[1])
    assert meshes['collector'] is None
    np.testing.assert_array_equal(decode_mesh(meshes['duct']), stl_triangles(STL))  # lossless, file order
    assert (REL/'preview.html').read_text().count('@@') == 0


def test_preview_dimensions_follow_params(tmp_path):
    """Chamber, collar, depth and card placement come from the GeometryParams, not template constants."""
    import re
    import numpy as np
    from dataclasses import replace
    from duct.print.preview import wall_context
    from duct.viz.web import collector_release
    g = replace(V23, chamber_length=62.0)
    html = write_preview(STL, {**NOTES['v23'], 'note': 'n'}, tmp_path/'p.html', collector=collector_release(None, g),
                         context=wall_context(g)).read_text()
    dims = json.loads(re.search(r'id="dimsData">(.*?)</script>', html, re.S)[1])
    assert (dims['chamber'], dims['collar'], dims['depth'], dims['card']) == (62, 12, 74, 267)
    assert '<span>Chamber depth</span><strong>62</strong>' in html and '<strong id="totalVal">74</strong>' in html
    assert '<span>Fan front → card face</span><strong>87</strong>' in html
    meshes = json.loads(re.search(r'id="meshData">(.*?)</script>', html, re.S)[1])
    if meshes['collector']: assert meshes["collector"]["offset"][2] == pytest.approx(62+267+.8)  # collector flange on the rear panel (0.8 mm) at the bracket plane
    from duct.cad.hardware import hardware_meshes
    from duct.params import COLLECTOR_V2
    from duct.print.preview import decode_mesh
    hw = hardware_meshes(g, COLLECTOR_V2)
    html = write_preview(STL, {**NOTES['v23'], 'note': 'n'}, tmp_path/'h.html', context=wall_context(g), hardware=hw).read_text()
    got = json.loads(re.search(r'id="meshData">(.*?)</script>', html, re.S)[1])['hardware']
    assert set(got) == set(hw)
    for k, m in hw.items(): np.testing.assert_array_equal(decode_mesh(got[k]), m.vertices[m.faces].astype(np.float32))  # not welded
    assert hw['rear_panel'].bounds[0][2] == pytest.approx(62+267)
    default = json.loads(re.search(r'id="dimsData">(.*?)</script>', write_preview(STL, {**NOTES['v23'], 'note': 'n'}, tmp_path/'q.html').read_text(), re.S)[1])
    assert (default['chamber'], default['depth']) == (70, 82)


@pytest.mark.skipif(not BAMBU.exists(), reason='Bambu Studio not installed')
def test_slice_matches_released(tmp_path):
    got = slice_stl(STL, tmp_path, supports=True)
    want = json.loads((REL/'slicer-checks.json').read_text())['automatic_supports']
    assert got['triangle_count'] == want['triangle_count'] and got['warning'] == ''
    assert got['minutes'] == pytest.approx(want['minutes'], rel=1e-3)


def test_collector_follows_the_run(tmp_path):
    """The preview draws the collector the CFD run modelled: case.json collector.source, else the run name, else the fan face."""
    from duct.params import COLLECTOR_V3, V28
    from duct.viz.web import collector_release, collector_version
    def run(name, collector):
        d = tmp_path/name; d.mkdir(); (d/'case.json').write_text(json.dumps({'collector': collector})); return d
    assert collector_version(run('a', {'source': 'duct.cad.exhaust COLLECTOR_V3'})) == 'v3'
    assert collector_version(run('b', {'source': 'duct.cad.exhaust bare_fan_air (COLLECTOR_V2 fan axis x)'})) == 'bare'
    assert collector_version(run('v28-pp-v3l', {})) == 'v3l' and collector_version(run('v28-pp-v3-2177', {})) == 'v3'
    face = collector_release(None, V28, 'v3')['fan']
    assert face['z'] == pytest.approx(62+267+.8+COLLECTOR_V3.plenum_depth)          # fan face on the panel-mounted collector
    assert collector_version(run('x', {}), dict(face), V28) == 'v3'
    assert 'cfd_offset_mm' not in collector_release(dict(face), V28, 'v3')         # a matching run: no mismatch note
    assert collector_release(dict(face, z=face['z']-.8), V28, 'v3')['cfd_offset_mm'][2] == pytest.approx(-.8)


def test_no_collector_for_a_four_slot_pitch():
    """A flat-panel collector is not drawn on a slot layout it was not designed for (here cards four slots apart): the page
    shows the case rear without it."""
    from dataclasses import replace
    from duct.cad.hardware import hardware_meshes
    from duct.params import V28
    from duct.viz.web import collector_params, collector_release
    g = replace(V28, pitch=81.28)   # cards four slots apart
    assert collector_release(None, g, 'v3') is None
    assert hardware_meshes(g, collector_params('v2', g))['rear_panel'].bounds[0][2] == pytest.approx(62+267)
    assert collector_params('v3', V28).inlet_z == pytest.approx(62+267)


def _hrefs(page: Path, selector: str = '') -> list[str]:
    import re
    text = page.read_text()
    if selector:
        text = ''.join(re.findall(rf'<nav class="{selector}"[^>]*>.*?</nav>', text, re.S))
    return re.findall(r'href="([^"#]+)', text)


def test_layout_switch_links_the_sibling_layout(tmp_path):
    from duct.print.layouts import layout_links, siblings
    for d in ('v28', 'v29', 'a29'):
        (tmp_path/d).mkdir(); (tmp_path/d/f'dual-170hx-continuous-{d}.stl').write_text('')
    assert [r.name for r in siblings('a29', tmp_path)] == ['v29', 'a29']   # 5-slot first
    assert siblings('v28', tmp_path) == []                                # one layout only: no switcher
    links = layout_links('v29', tmp_path/'v29'/'preview.html', tmp_path)
    assert [(l['label'], l['href'], l['current']) for l in links] == [
        ('5-slot · one empty slot', 'preview.html', True), ('4-slot · adjacent', '../a29/preview.html', False)]
    page = write_preview(STL, {**NOTES['v29'], 'note': 'n'}, tmp_path/'p.html', layouts=links)
    assert _hrefs(page, 'layout-switch') == ['preview.html', '../a29/preview.html']*2   # header and sheet
    assert 'class="layout-switch"' not in write_preview(STL, {**NOTES['v23'], 'note': 'n'}, tmp_path/'q.html').read_text()


def test_release_switch_and_index_links_resolve():
    rel = REL.parent
    pages = sorted(rel.glob('*/preview*.html'))   # preview-flat.html too (case-view releases)
    switched = {p.parent.name for p in pages if 'data-layout' in p.read_text()}
    assert {'v29', 'a29'} <= switched
    for p in pages:
        for h in _hrefs(p, 'layout-switch')+_hrefs(p, 'layout-switch case-switch'):
            assert (p.parent/h).resolve().is_file(), (p, h)
    index = rel/'index.html'
    hrefs = _hrefs(index)
    assert 'v29/preview.html' in hrefs and 'a29/preview.html' in hrefs
    for h in hrefs:
        assert (rel/h).resolve().is_file(), h
