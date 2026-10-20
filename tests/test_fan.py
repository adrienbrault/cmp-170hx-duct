import re

import numpy as np
import pytest

from duct.cfd import fan

ACCEPTED_Q = 0.0123712535  # reference55, fan-matched CFD
ACCEPTED_TOTAL_PA = 28.2409  # applied total pressure at that flow


def test_chart_at_3000_rpm_matches_manufacturer_table():
    q, p = fan.chart(3000)
    assert q[-1] == pytest.approx(77 * fan.CFM)
    assert p[0] == pytest.approx(6.9 * fan.MMH2O)


def test_affinity_scaling():
    q3, p3 = fan.chart(3000)
    q, p = fan.chart(1500)
    np.testing.assert_allclose(q, q3 / 2)
    np.testing.assert_allclose(p, p3 / 4)


def test_series_doubles_static_term_only():
    Q = 0.01
    one, two = fan.static_pressure(Q, 2500), fan.static_pressure(Q, 2500, count_series=2)
    assert two == pytest.approx(2 * one)
    assert fan.total_pressure(Q, 2500, count_series=2) == pytest.approx(2 * one + fan.dynamic_pressure(Q))
    assert fan.static_pressure(Q, 2500, count_series=2, series_efficiency=0.5) == pytest.approx(1.5 * one)


def test_beyond_free_delivery_is_strongly_negative():
    q_free = fan.chart(2500)[0][-1]
    assert fan.static_pressure(q_free * 1.01, 2500) < -100


def test_arrays_accepted():
    out = fan.total_pressure(np.array([0.0, 0.01]), 2500)
    assert out.shape == (2,)


def test_total_pressure_matches_legacy_fan_match():
    # work/duct-v13/fan_match.py gave 28.2399 Pa at the accepted flow. It interpolated the
    # total-pressure table linearly (as the OpenFOAM fanPressure table does); the exact
    # velocity-pressure term differs by ~5 mPa between chart points.
    assert fan.total_pressure(ACCEPTED_Q, 2500, area=fan.LEGACY_ANNULUS_AREA) == pytest.approx(28.2399, abs=0.01)


def test_operating_point_single_fan_2500():
    q = fan.operating_point(2500)
    assert q == pytest.approx(ACCEPTED_Q, rel=1e-3)
    assert fan.total_pressure(q, 2500, area=fan.LEGACY_ANNULUS_AREA) == pytest.approx(ACCEPTED_TOTAL_PA, rel=1e-3)


def test_operating_point_two_fans_moves_up():
    assert fan.operating_point(2500, count_series=2) > 1.2 * fan.operating_point(2500)


def test_fan_pressure_bc_is_kinematic():
    bc = fan.fan_pressure_bc(2500)
    assert "type fanPressure" in bc and "direction in" in bc
    pairs = [tuple(map(float, m)) for m in re.findall(r"\(([\d.e+-]+) ([\d.e+-]+)\)", bc)]
    q, p = zip(*pairs)
    np.testing.assert_allclose(p, fan.total_pressure(np.array(q), 2500) / fan.RHO, rtol=1e-8)


def _table(bc):
    return np.array([tuple(map(float, m)) for m in re.findall(r"\(([\d.e+-]+) ([\d.e+-]+)\)", bc)])


def test_exhaust_bc_is_static_rating_plus_patch_velocity_head():
    # fanPressure `out` fixes the patch *static* pressure at -table; the free-outlet static rating puts the
    # fan-inlet total pressure at -p_sF, so the table is p_sF + ½ρ(Q/A)² on the exhaust patch.
    bc = fan.fan_pressure_bc(2500, direction="out")
    assert "direction out" in bc and re.search(r"value uniform -[\d.]+;", bc)
    t = _table(bc)
    np.testing.assert_allclose(t[:, 1], fan.total_pressure(t[:, 0], 2500) / fan.RHO, rtol=1e-8)
    area = 0.0096
    t = _table(fan.fan_pressure_bc(2500, direction="out", area=area))
    expected = (fan.static_pressure(t[:, 0], 2500) + 0.5 * fan.RHO * (t[:, 0] / area) ** 2) / fan.RHO
    np.testing.assert_allclose(t[:, 1], expected, rtol=1e-8)


def test_exhaust_on_lossless_tube_delivers_free_flow():
    # Open inlet (p_t = 0), no losses: patch static = -½ρv² must equal -table(Q) exactly at free delivery.
    t = _table(fan.fan_pressure_bc(2500, direction="out"))
    q_free = fan.chart(2500)[0][-1]
    assert t[-1, 0] == pytest.approx(q_free)
    assert t[-1, 1] * fan.RHO == pytest.approx(fan.dynamic_pressure(q_free), rel=1e-9)


def test_hub_constant():
    assert fan.ANNULUS_AREA == pytest.approx(np.pi * (fan.TIP_RADIUS**2 - fan.HUB_RADIUS**2))
    assert 0.024 < fan.HUB_RADIUS < 0.026 and fan.LEGACY_HUB_RADIUS == 0.017


def test_fan_jump_bc_is_total_curve_against_flow():
    bc = fan.fan_jump_bc(2500, 2, 0.7)
    assert "type fan; patchType cyclic; mode volumeFlowRate" in bc
    t = _table(bc)
    np.testing.assert_allclose(t[:, 1], fan.total_pressure(t[:, 0], 2500, 2, 0.7) / fan.RHO, rtol=1e-8)


def test_p14_pro_reverse_chart():
    """ARCTIC's P14 Pro Reverse chart: 5.1 mmH2O shut-off, 98 CFM free delivery at 2650 rpm; affinity-scaled like the P12."""
    m = fan.P14_PRO_REVERSE
    q, p = fan.chart(2650, model=m)
    assert q[-1] == pytest.approx(98 * fan.CFM) and p[0] == pytest.approx(5.1 * fan.MMH2O) and p[-1] == 0
    assert np.all(np.diff(p) < 0)
    q25, p25 = fan.chart(2500, model=m)
    np.testing.assert_allclose(q25, q * 2500 / 2650)
    np.testing.assert_allclose(p25, p * (2500 / 2650) ** 2)
    assert fan.static_pressure(10 * fan.CFM, 2650, model=m) == pytest.approx(4.6 * fan.MMH2O)
    t = _table(fan.fan_jump_bc(2650, model=m))
    np.testing.assert_allclose(t[:, 1], fan.total_pressure(t[:, 0], 2650, area=m.area, model=m) / fan.RHO, rtol=1e-8)


def test_fan_for_collector():
    from duct import params
    assert fan.for_collector(params.COLLECTOR_PLUG_BASE) is fan.P12_PRO and fan.for_collector(params.COLLECTOR_V3) is fan.P12_PRO
    m = fan.for_collector(params.COLLECTOR_PLUG_140)
    assert m.name == "ARCTIC P14 Pro Reverse" and (m.tip_radius, m.hub_radius) == (0.068, 0.028)
    assert fan.P12_PRO.area == fan.ANNULUS_AREA and fan.MODELS[m.name].pq == m.pq


def test_p12_bcs_unchanged():
    """The default model is the P12 Pro: these strings are what every 120 mm case has been written with."""
    assert fan.fan_jump_bc(2500) == fan.fan_jump_bc(2500, model=fan.P12_PRO)
    assert fan.fan_pressure_bc(2500, direction="out", area=0.0096) == fan.fan_pressure_bc(2500, direction="out", area=0.0096,
                                                                                          model=fan.P12_PRO)
    assert fan.fan_jump_bc(2500).startswith(
        "{type fan; patchType cyclic; mode volumeFlowRate; jumpTable table ((0 39.1584983) (0.00393289542 33.8681622) ")
