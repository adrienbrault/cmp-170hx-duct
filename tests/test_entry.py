"""Duct-flow metrics (duct.cfd.entry) on synthetic fields, and the seatUp split of the pressure breakdown."""
import numpy as np
import pytest

from duct.cfd import breakdown, case, entry
from duct.cfd.porous import FINS
from duct.params import A29, V29


def _cells(L=62.0, h=1.0, R=58.0):
    """1 mm cube cells filling a cylinder of radius R from z = -5 to L + 5 (beyond the duct on both ends)."""
    g = np.arange(-R+h/2, R, h); z = np.arange(-5+h/2, L+5, h)
    x, y, zz = (a.ravel() for a in np.meshgrid(g, g, z, indexing='ij'))
    keep = np.hypot(x, y) < R
    return np.c_[x[keep], y[keep], zz[keep]], np.full(keep.sum(), h**3)


def test_reverse_volumes_split_core_and_periphery():
    c, v = _cells()
    r = np.hypot(c[:, 0], c[:, 1]); z = c[:, 2]
    uz = np.ones(len(c))
    assert entry.reverse_volumes(c, v, uz, 62.0)['reverse_cm3'] == 0.0
    core = (r < 20) & (z > 0) & (z < 30); ring = (r > 55) & (z > 0) & (z < 10); outside = (r < 20) & (z < 0)
    uz[core | ring | outside] = -1.0   # the reverse cells before the fan face are not in the duct
    rv = entry.reverse_volumes(c, v, uz, 62.0)
    assert rv['core_reverse_cm3'] == pytest.approx(core.sum()*1e-3) == pytest.approx(np.pi*20**2*30*1e-3, rel=.01)
    assert rv['periphery_reverse_cm3'] == pytest.approx(ring.sum()*1e-3)
    assert rv['reverse_cm3'] == pytest.approx((core.sum()+ring.sum())*1e-3)
    assert rv['air_cm3'] == pytest.approx(((z > 0) & (z < 62)).sum()*1e-3)
    assert rv['reverse_fraction'] == pytest.approx(rv['reverse_cm3']/rv['air_cm3'])


def test_plane_regions():
    g = np.arange(-57.75, 58, .5); x, y = (a.ravel() for a in np.meshgrid(g, g)); keep = np.hypot(x, y) < 58
    xy = np.c_[x[keep], y[keep]]; r = np.hypot(*xy.T)
    uz = np.where(r < 20, 0.1, 1.0); uz[r > 55] = -0.2
    p = entry.plane_regions(xy, uz)
    mean = uz.mean()
    assert p['uz_mean_mps'] == pytest.approx(mean)
    assert p['slow_fraction'] == pytest.approx(((r < 20) | (r > 55)).mean())   # 0.1 and -0.2 are below half the mean
    assert p['slow_fraction_core'] == pytest.approx((r < 20).sum()/(r < 45).sum())
    assert p['slow_fraction_periphery'] == pytest.approx((r > 55).sum()/(r > 50).sum())
    assert p['periphery_reverse_fraction'] == pytest.approx((r > 55).mean()) == pytest.approx(p['reverse_fraction'])


def test_core_fill_length():
    zs = np.arange(1., 62.)
    sec = np.ones_like(zs)
    assert entry.core_fill_length(zs, np.clip(zs/40, 0, 1), sec) == 20.0            # reaches 0.5 at z = 20 and stays
    assert entry.core_fill_length(zs, np.clip(zs/40, 0, 1), sec, .8) == 32.0
    dip = np.clip(zs/40, 0, 1); dip[zs == 30] = .4                                     # a later dip moves it past the dip
    assert entry.core_fill_length(zs, dip, sec) == 31.0
    assert entry.core_fill_length(zs, np.full_like(zs, .9), sec) == 1.0
    assert entry.core_fill_length(zs, np.full_like(zs, .1), sec) is None


@pytest.mark.parametrize('g', [V29, A29])
def test_port_uniformity(g):
    gx = np.arange(-60.25, 60.5, .5); x, y = (a.ravel() for a in np.meshgrid(gx, gx)); xy = np.c_[x, y]
    u = entry.port_uniformity(xy, np.ones(len(xy)), g)
    areas = [(x1-x0)*(y1-y0) for _, _, (x0, x1, y0, y1) in g.port_boxes[:3]]
    for c in u['cards']:
        assert [p['share'] for p in c['ports']] == pytest.approx([a/sum(areas) for a in areas], rel=1e-3)
        assert all(p['uz_cov'] < 1e-9 and p['row_cov'] < 1e-9 and len(p['rows']) == FINS.channels[p['port']] for p in c['ports'])
    # a linear y profile in the main port: rows follow it, the CoV of the row means is that of the band centres
    x0, x1, y0, y1 = g.port_boxes[0][2]
    uz = 1+.2*xy[:, 1]/y1
    u = entry.port_uniformity(xy, uz, g)
    rows = np.array(u['cards'][0]['ports'][0]['rows'])
    n = FINS.channels[0]; centres = y0+(np.arange(n)+.5)*(y1-y0)/n; expect = 1+.2*centres/y1
    assert rows == pytest.approx(expect/expect.mean(), abs=2e-3)
    assert u['main_row_cov'] == pytest.approx(expect.std()/expect.mean(), rel=.02)


def test_bay_deficit():
    gx = np.arange(-60.25, 60.5, .5); x, y = (a.ravel() for a in np.meshgrid(gx, gx)); xy = np.c_[x, y]
    pt = np.full(len(xy), 30.0); uz = np.ones(len(xy))
    for cx in V29.card_x:
        pt[(xy[:, 0] < cx) & (xy[:, 1] > 0) & (np.sign(xy[:, 0]) == np.sign(cx))] = 29.0   # each card's bay quadrant
    b = entry.bay_deficit(xy, uz, pt, V29)
    for c in b['cards']:
        assert c['bay_quadrant_flow_share'] == pytest.approx(.25, abs=.01)
        s = c['bay_quadrant_flow_share']
        assert c['deficit_pa'] == pytest.approx((1-s)*30+s*29-29.0)


def test_seat_up_station_plane():
    for g in (V29, A29):
        for b in (4.0, 3.9):
            p = case.planes(g, case.CaseOptions(base_cell=b, fan_model='disk'))
            z = p.duct_stations(g.chamber_length)['seatUp']
            assert g.chamber_length-case.SEAT_UP-b < z <= g.chamber_length-case.SEAT_UP+1e-9
            assert any(abs(z-p.at(k)) < 1e-9 for k in range(200))     # on a grid plane: a flat faceZone


def test_breakdown_splits_the_intake_duct_at_seat_up(tmp_path):
    q = .009; pts = dict(intakeFanDownstream=32.5, seatUp=32.1, cardEntry0=32.0, cardEntry1=32.0, cardBracket0=15.8,
                        cardBracket1=15.8, cardExit0=15.8, cardExit1=15.8, bracketDown=12.3, exhaust=9.1)
    lines = []
    for region, pt in pts.items():
        qi = q/2 if region[-1] in '01' else q
        lines += [f'    sum({region}) of phi = {qi}', f'    weightedAverage({region}) of p = {(pt-1)/1.2}',
                  f'    weightedAverage({region}) of pt = {pt/1.2}']
    log = tmp_path/'log.breakdown'; log.write_text('\n'.join(lines)+'\n')
    meta = dict(planes_mm=dict(seatUp=60.625, bracketDown=332.625), patches=dict(inlet={}, exhaust={}, walls={}),
                options=dict(fan_model='disk', rpm=2500))
    d = breakdown.parse(log, ['exhaust'], meta, 'intakeFanDownstream')['total_pressure_drops_pa']
    assert d['duct'] == pytest.approx(.4) and d['card_face'] == pytest.approx(.1)
    assert d['intake_duct'] == pytest.approx(d['duct']+d['card_face'])
    del meta['planes_mm']['seatUp']   # a case built before the station: no split
    assert 'duct' not in breakdown.parse(log, ['exhaust'], meta, 'intakeFanDownstream')['total_pressure_drops_pa']
