import pytest

from duct import network
from duct.cfd import fan
from duct.network import CALIBRATION, Setup, evaluate, flow, peak_base_rise


def test_calibration_points_reproduced():
    # reference55: no bracket plate, fan table on the legacy 17 mm hub annulus
    for rpm, q, rise in CALIBRATION:
        assert flow(Setup(rpm=rpm, bracket_k=0, fan_area=fan.LEGACY_ANNULUS_AREA)) == pytest.approx(q, rel=2e-3)
        assert peak_base_rise(q, fit=network.RISE_FIT_REFERENCE) == pytest.approx(rise, abs=0.05)


def test_more_fan_pressure_means_more_flow():
    one = flow(Setup())
    assert flow(Setup(stacked=2)) > one
    assert flow(Setup(pull_rpm=2500)) > one
    assert flow(Setup(pull_rpm=2500, collector_k=10)) < flow(Setup(pull_rpm=2500, collector_k=0))


def test_rise_scales_with_power():
    q = CALIBRATION[1][1]
    assert peak_base_rise(q, 125) == pytest.approx(peak_base_rise(q) / 2)


def test_noise_rules():
    assert network.noise_delta_db(Setup()) == pytest.approx(0)
    assert network.noise_delta_db(Setup(pull_rpm=2500)) == pytest.approx(3.01, abs=0.01)
    assert evaluate(Setup(stacked=2))["noise_db"] == pytest.approx(6.01, abs=0.01)


def test_bracket_in_every_setup():
    assert network.BASELINE.bracket_k == network.BRACKET_K > network.bracket_k_estimate() > 0
    assert flow(Setup()) < flow(Setup(bracket_k=0))
    assert all(s.bracket_k == network.BRACKET_K for s in network.STANDARD)
    assert network.grille_k() == 0 and network.grille_k(0.5) > network.grille_k(0.65) > network.grille_k(0.8)
    assert flow(Setup(grille_open_area=0.65)) < flow(Setup())


def test_bracket_rise_fit():
    for _, q, rise in network.BRACKET_RISE:
        assert peak_base_rise(q) == pytest.approx(rise, abs=0.1)
    for _, q, rise in network.WINDOW_RISE:
        assert peak_base_rise(q, fit=network.RISE_FIT_WINDOW) == pytest.approx(rise, abs=0.1)
    q = 0.0104   # the panel's rib starves the main fin path: hotter at equal Q than the windows alone, which beat no bracket
    assert peak_base_rise(q) > peak_base_rise(q, fit=network.RISE_FIT_WINDOW) + 1
    assert peak_base_rise(q, fit=network.RISE_FIT_WINDOW) < peak_base_rise(q, fit=network.RISE_FIT_REFERENCE) - 1


def test_v25_set_matches_cfd():
    # V25, boundary fans, bracket windows alone (no panel): (setup, CFD Q m³/s) from runs/v25b-*, window-only terms
    w = dict(bracket_k=network.BRACKET_K_WINDOW, collector_k=network.COLLECTOR_K_WINDOW)
    for s, q in [(Setup(**w), 0.01035580), (Setup(stacked=2, **w), 0.01320192), (Setup(pull_rpm=2500, **w), 0.01451249),
                 (Setup(rpm=2177, pull_rpm=2177, **w), 0.01231481), (Setup(rpm=3000, pull_rpm=3000, **w), 0.01793270)]:
        assert flow(s) == pytest.approx(q, rel=0.005)


def test_window_runs_match_cfd():
    for s, q, rise in network.WINDOW_CFD:
        assert flow(s) == pytest.approx(q, rel=0.01)
        assert peak_base_rise(flow(s), fit=network.RISE_FIT_WINDOW) == pytest.approx(rise, abs=0.5)


def test_one_fan_bracket_matches_cfd():
    for s, q, rise in network.BRACKET_CFD:
        assert flow(s) == pytest.approx(q, rel=0.005)
        assert peak_base_rise(flow(s)) == pytest.approx(rise, abs=0.3)


def test_push_pull_matches_cfd():
    for s, q, rise in network.PUSH_PULL_CFD:
        assert flow(s) == pytest.approx(q, rel=0.01)
        assert peak_base_rise(flow(s)) == pytest.approx(rise, abs=0.3)
