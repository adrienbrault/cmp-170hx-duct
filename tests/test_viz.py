import base64
import gzip
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from duct import network
from duct.cfd import fan
from duct.print.preview import network_payload, write_preview

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/'work/rounding-study/upper-r6'
STL = ROOT/'releases/v23/dual-170hx-continuous-v23.stl'


def js_port_evaluate(c: dict, s: dict) -> dict:
    """Line-by-line Python mirror of the page's JS network model, fed only the embedded constants."""
    s = {**c['defaults'], **s}
    def static(Q, rpm, count=1, eff=1.0):
        r = rpm/c['chart_rpm']
        q = [v*r for v in c['chart_q']]
        p = [v*r*r*(1+(count-1)*eff) for v in c['chart_p']]
        return -c['beyond_free_delivery_slope']*(Q-q[-1]) if Q > q[-1] else float(np.interp(Q, q, p))
    def total(Q, rpm, count=1, eff=1.0, area=c['fan_annulus_area']):
        return static(Q, rpm, count, eff)+.5*c['fan_rho']*(Q/area)**2
    def grille_k(f):
        return 0 if f >= 1 else (.707*(1-f)**.375+1-f)**2/f**2*(c['fan_area']/c['port_area'])**2
    def system(Q):
        qa = .5*c['rho']*(Q/c['fan_area'])**2
        dp = c['system_a']*Q+c['system_b']*Q*Q+(s['bracket_k']+grille_k(s['grille_open_area']))*qa
        return dp+(s['collector_k']*qa if s['pull_rpm'] else 0)
    def avail(Q):
        return ((total(Q, s['rpm'], s['stacked'], s['stack_efficiency'], s['fan_area']) if s['rpm'] else 0)
                + (static(Q, s['pull_rpm']) if s['pull_rpm'] else 0))
    lo, hi = c['bracket']
    f = lambda Q: avail(Q)-system(Q)  # noqa: E731
    for _ in range(200):
        m = (lo+hi)/2
        lo, hi = (m, hi) if (f(m) > 0) == (f(lo) > 0) else (lo, m)
    Q = (lo+hi)/2
    c0, c1, mm = c['rise_fit']
    src = ([s['rpm']]*s['stacked'] if s['rpm'] else [])+([s['pull_rpm']] if s['pull_rpm'] else [])
    noise = 10*math.log10(sum(10**(50*math.log10(r/c['noise_ref_rpm'])/10) for r in src))+(3 if s['stacked'] > 1 else 0)
    return dict(flow_ls=Q*1e3, pressure_pa=system(Q), peak_base_rise_k=s['power_w']/c['reference_power_w']*(c0+c1*(Q*1e3)**-mm),
                noise_db=noise, extrapolated=Q > c['extrapolation_q'])


def test_network_payload_is_network_py():
    c = network_payload()
    assert c['system_a'] == network.SYSTEM_A and c['system_b'] == network.SYSTEM_B
    assert c['rise_fit'] == [float(v) for v in network.RISE_FIT]
    assert c['chart_q'] == [float(v) for v in fan._Q] and c['chart_p'] == [float(v) for v in fan._P]
    assert c['defaults']['stack_efficiency'] == network.Setup().stack_efficiency
    assert len(c['standard']) == len(network.STANDARD)


def test_embedded_constants_reproduce_standard_setups():
    c = network_payload()
    extra = [dict(setup=dict(rpm=2500, grille_open_area=.65, bracket_k=0.0, label='grille'))]
    extra[0]['result'] = network.evaluate(network.Setup(**extra[0]['setup']))
    for entry in c['standard']+extra:
        got, want = js_port_evaluate(c, entry['setup']), entry['result']
        for k in ('flow_ls', 'pressure_pa', 'peak_base_rise_k'):
            assert got[k] == pytest.approx(want[k], rel=1e-6), (entry['setup']['label'], k)
        assert got['noise_db'] == pytest.approx(want['noise_db'], abs=1e-9)
        assert got['extrapolated'] == want['extrapolated']


def _decode(payload: dict) -> dict:
    raw = gzip.decompress(base64.b64decode(payload['data']))
    g = payload['grid']; n = sum(int(np.prod(b['dims'])) for b in g['blocks']); off = 0; out = {}
    for f in g['fields']:
        cnt = n*f['comps']
        b = np.frombuffer(raw, np.uint8, 2*cnt, off).reshape(2, cnt).T.copy()
        out[f['name']] = f['offset']+f['scale']*b.view('<i2').ravel().astype(float)
        off += 2*cnt
    out['mask'] = np.frombuffer(raw, np.uint8, n, off)
    return out


@pytest.fixture(scope='module')
def synthetic():
    pv = pytest.importorskip('pyvista')
    from duct.viz.export import AirflowExport, sample_grid
    box = pv.ImageData(dimensions=(9, 9, 21), spacing=(.005, .005, .005), origin=(-.02, -.02, 0)).cast_to_unstructured_grid()
    pts = box.points
    box.point_data['U'] = np.c_[np.zeros(len(pts)), np.zeros(len(pts)), 1+10*pts[:, 0]]
    box.point_data['p'] = 5-20*pts[:, 2]
    box.point_data['k'] = np.full(len(pts), .01)
    grid = sample_grid(box, spacing_mm=4.0)
    return box, grid, AirflowExport(grid, dict(case='synthetic'))


def test_sample_grid_masks_and_interpolates(synthetic):
    box, grid, _ = synthetic
    assert grid.mask.all() and set(grid.fields) == {'p', 'k'}
    x = grid.origin_mm[0]+np.arange(grid.dims[0])*grid.spacing_mm
    np.testing.assert_allclose(grid.U[..., 2], np.broadcast_to(1+10*x*1e-3, grid.U.shape[:3]), atol=1e-5)
    np.testing.assert_allclose(grid.U[..., :2], 0, atol=1e-6)


def test_payload_round_trip(synthetic):
    _, grid, exp = synthetic
    d = _decode(exp.payload())
    np.testing.assert_allclose(d['U'].reshape(grid.U.shape), grid.U, atol=2e-4)
    np.testing.assert_allclose(d['p'].reshape(grid.mask.shape), grid.fields['p'], atol=1e-3)
    assert d['mask'].all()


def test_hotspots_find_the_gradient(synthetic):
    from duct.viz.analysis import hotspots
    from dataclasses import replace
    _, grid, _ = synthetic
    z = grid.origin_mm[2]+np.arange(grid.dims[2])*grid.spacing_mm
    step = np.broadcast_to(np.where(z > 50, 0.0, 5.0)[:, None, None], grid.mask.shape).astype(np.float32)  # the loss sits at z ≈ 50
    g = replace(grid, fields={**grid.fields, 'p': step})
    hs = hotspots(g, (0, 100), n=1)
    assert abs(hs[0]['xyz_mm'][2]-50) <= g.spacing_mm


def test_preview_embeds_airflow_and_network(tmp_path, synthetic):
    from duct.print.release import NOTES
    _, _, exp = synthetic
    out = write_preview(STL, {**NOTES['v23'], 'note': 'n'}, tmp_path/'p.html', airflow=exp)
    html = out.read_text()
    assert '@@' not in html
    net = json.loads(re.search(r'<script type="application/json" id="networkData">(.*?)</script>', html, re.S)[1])
    flow = json.loads(re.search(r'<script type="application/json" id="airflowData">(.*?)</script>', html, re.S)[1])
    assert net['system_a'] == network.SYSTEM_A and flow['meta']['case'] == 'synthetic'
    plain = write_preview(STL, {**NOTES['v23'], 'note': 'n'}, tmp_path/'q.html').read_text()
    assert '<script type="application/json" id="airflowData">null</script>' in plain


@pytest.mark.skipif(not (CASE/'400').exists(), reason='upper-r6 lab case not present')
def test_export_upper_r6():
    pytest.importorskip('pyvista')
    from duct.viz.export import export_case
    e = export_case(CASE, spacing_mm=4.0)
    a = e.meta['analysis']
    assert e.meta['flow_m3s'] == pytest.approx(.012436, rel=1e-3)
    assert e.meta['porous_z_mm'] == pytest.approx([78, 308])
    assert sum(a['card_split_pct']) == pytest.approx(100) and abs(a['card_split_pct'][0]-50) < 2
    assert 0 < a['duct_loss_pa'] < .1*a['fan_total_pa'] and 0 < a['uniformity'] < 1
    assert len(a['hotspots']) == 3
