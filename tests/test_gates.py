from types import SimpleNamespace

import numpy as np
import pytest

from duct.cfd import gates


def history(n=400, q=0.0124, noise=0.0, split=0.5, leak=0.0, residual=1e-5, seed=0):
    rng = np.random.default_rng(seed)
    it = np.arange(1, n + 1)
    qin = q * (1 + noise * rng.standard_normal(n))
    return gates.History(it, -qin, qin * split, qin * (1 - split) * (1 - leak), {"p": np.array([residual])})


def thermal(peak=77.8, energy=1e-6, objective=True, du=1e-4, base_change=1e-6, exchange=1e-7):
    return SimpleNamespace(peak_rise_K=peak, energy_error=energy, exchange_energy_error=exchange,
                           base_change_K=base_change, objective_converged=objective, relative_velocity_change=du)


def test_steady_history_passes():
    assert gates.flow(history()).passed


def test_not_enough_iterations_fails():
    r = gates.flow(history(n=150))
    assert not r.passed and np.isnan(r.gates["inlet_q_range"].value)


def test_inlet_range_over_window():
    assert not gates.flow(history(noise=0.003)).passed  # ~6 sigma range over 200 samples > 0.5 %
    assert gates.flow(history(noise=0.0002)).passed


def test_only_last_window_counts():
    h = history()
    h.q_in[:150] *= 1.5  # early transient outside the last 200 iterations
    assert gates.flow(h).passed


def test_split_drift():
    h = history()
    ramp = np.linspace(0, 0.01, len(h.iteration))
    total = h.q_left + h.q_right
    h.q_left, h.q_right = total * (0.5 + ramp), total * (0.5 - ramp)
    r = gates.flow(h)
    assert not r.gates["split_drift"].ok and r.gates["inlet_q_range"].ok


def test_mass_imbalance():
    assert not gates.flow(history(leak=1e-3)).gates["mass"].ok
    assert gates.flow(history(leak=1e-5)).gates["mass"].ok


def test_strict_needs_residuals_and_tight_drift():
    assert not gates.flow(history(residual=2e-4), strict=True).passed
    assert not gates.flow(history(noise=0.0003), strict=True).passed  # passes default, fails 0.1 %
    assert gates.flow(history(noise=0.0003)).passed
    assert gates.flow(history(), strict=True).passed


def test_thermal_gates():
    assert gates.thermal([thermal()]).passed
    assert not gates.thermal([thermal(energy=2e-3)]).passed
    assert gates.thermal([thermal(77.80), thermal(77.84)]).passed
    assert not gates.thermal([thermal(77.80), thermal(77.86)]).passed
    assert not gates.thermal([thermal(base_change=0.01)]).passed  # coupling still moving
    assert not gates.thermal([thermal(exchange=2e-3)]).passed


def test_default_thermal_ignores_solver_objective():
    r = gates.thermal([thermal(objective=False)])
    assert r.passed and not gates.thermal([thermal(objective=False), thermal(objective=False)], strict=True).passed


def test_failures_name_the_gate():
    assert gates.thermal([thermal(energy=2e-3)]).failures() == ["energy 0.002 >= 0.001"]


def test_strict_thermal_requires_two_calls_and_objective():
    assert not gates.thermal([thermal()], strict=True).passed
    assert gates.thermal([thermal(), thermal()], strict=True).passed
    assert not gates.thermal([thermal(), thermal(objective=False)], strict=True).passed
    assert not gates.thermal([thermal(), thermal(du=2e-3)], strict=True).passed


def test_combine():
    r = gates.combine(gates.flow(history()), gates.thermal([thermal(energy=1.0)]))
    assert set(r.gates) == {"inlet_q_range", "split_drift", "mass", "energy", "exchange", "coupling"} and not r.passed


def test_flow_gate_limit_and_window():
    it = np.arange(1, 301)
    q = 0.0124*(1+0.004*np.sin(it/5))         # ~0.8 % range: fails 0.5 %, passes 1 %
    h = gates.History(it, -q, q/2, q/2, {})
    assert not gates.flow(h).passed
    assert gates.flow(h, window=100, limit=1e-2).passed
    assert not gates.flow(gates.History(it[:90], -q[:90], q[:90]/2, q[:90]/2), window=100, limit=1e-2).passed


def test_window_mean_reads_an_oscillation_at_its_mean():
    it = np.arange(1, 401)
    q = 0.012*(1+0.05*np.sin(2*np.pi*it/50))
    w = gates.window_mean(gates.History(it, -q, q*.4, q*.6), 200)
    assert w["q_lps"] == pytest.approx(12.0, rel=1e-3) and w["fin_q_lps"] == pytest.approx(12.0, rel=1e-3)
    assert w["split"] == pytest.approx(.4) and w["iterations"] == 200 and w["q_range"] > .09


def test_split_limit_is_separate():
    it = np.arange(1, 301)
    q = np.full(300, 0.0124)
    split = 0.5+0.004*np.sin(it/20)               # ~1.6 % split range, steady total
    h = gates.History(it, -q, q*split, q*(1-split), {})
    assert not gates.flow(h, window=100, limit=1e-2).passed
    r = gates.flow(h, window=100, limit=1e-2, split_limit=2e-2)
    assert r.passed and r.gates["split_drift"].limit == 2e-2 and r.gates["inlet_q_range"].limit == 1e-2
