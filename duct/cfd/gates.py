"""Convergence gates over a windowed flow history plus thermal calls (docs/PLAN.md#gates)."""
from dataclasses import dataclass, field

import numpy as np

WINDOW = 200


@dataclass
class History:
    """Patch fluxes (m³/s, inlet negative) by iteration, and initial residuals by field."""
    iteration: np.ndarray
    q_in: np.ndarray
    q_left: np.ndarray
    q_right: np.ndarray
    residuals: dict[str, np.ndarray] = field(default_factory=dict)

    def tail(self, n: int) -> "History":
        last = self.iteration[-1] if len(self.iteration) else 0
        m = self.iteration > last - n
        return History(self.iteration[m], self.q_in[m], self.q_left[m], self.q_right[m], self.residuals)


@dataclass
class Gate:
    value: float
    limit: float

    @property
    def ok(self) -> bool:
        return bool(np.isfinite(self.value) and self.value < self.limit)


@dataclass
class Report:
    gates: dict[str, Gate]

    @property
    def passed(self) -> bool:
        return all(g.ok for g in self.gates.values())

    def failures(self) -> list[str]:
        return [f"{k} {g.value:.3g} >= {g.limit:g}" if np.isfinite(g.value) else f"{k} not measured"
                for k, g in self.gates.items() if not g.ok]

    def as_dict(self) -> dict:
        return {k: {"value": g.value, "limit": g.limit, "ok": g.ok} for k, g in self.gates.items()}


def _range(x: np.ndarray) -> float:
    return float((x.max() - x.min()) / abs(x.mean()))


def flow(h: History, strict: bool = False, window: int = WINDOW, limit: float = 5e-3,
         split_limit: float | None = None) -> Report:
    """Flow gates; nan (failing) until a full window of samples exists. `limit`: the default set's inlet range bound
    over the window, and its split drift bound unless `split_limit` is given."""
    w = h.tail(window)
    full = len(h.iteration) > 1 and h.iteration[-1] - h.iteration[0] + 1 >= window
    nan = float("nan")
    q = np.abs(w.q_in)
    mass = float(np.abs(w.q_in[-1] + w.q_left[-1] + w.q_right[-1]) / q[-1]) if full else nan
    if strict:
        drift = h.tail(100)
        res = max(float(v[-1]) for v in h.residuals.values()) if h.residuals else nan
        return Report({
            "flow_drift": Gate(_range(np.abs(drift.q_in)) if full else nan, 1e-3),
            "flow_residuals": Gate(res, 1e-4),
            "mass": Gate(mass, 1e-4),
        })
    split = w.q_left / (w.q_left + w.q_right)
    return Report({
        "inlet_q_range": Gate(_range(q) if full else nan, limit),
        "split_drift": Gate(_range(split) if full else nan, limit if split_limit is None else split_limit),
        "mass": Gate(mass, 1e-4),
    })


def window_mean(h: History, window: int = WINDOW) -> dict[str, float]:
    """Inlet and fin (both card exits) flow in L/s averaged over the last `window` iterations, and the inlet range
    there: a loosely gated or oscillating case is read at its mean, not at a random point of its cycle."""
    w = h.tail(window)
    if not len(w.iteration):
        return {}
    q, fin = np.abs(w.q_in), np.abs(w.q_left)+np.abs(w.q_right)
    return {"q_lps": float(q.mean()*1e3), "fin_q_lps": float(fin.mean()*1e3), "q_range": _range(q),
            "split": float(np.mean(np.abs(w.q_left)/fin)), "iterations": int(len(w.iteration))}


def thermal(results: list, strict: bool = False) -> Report:
    """Thermal gates from one or two ThermalResult-like calls (latest last). The default set
    checks the answer (peak settled across coupling iterations and calls, heat accounted for);
    strict adds the solver's own pointwise air-convergence objective."""
    last = results[-1]
    gates = {
        "energy": Gate(last.energy_error, 1e-4 if strict else 1e-3),
        "exchange": Gate(last.exchange_energy_error, 1e-4 if strict else 1e-3),
        "coupling": Gate(last.base_change_K, 1e-4 if strict else 5e-3),
    }
    if len(results) > 1:
        gates["peak_stability"] = Gate(abs(last.peak_rise_K - results[-2].peak_rise_K), 0.05)
    if strict:
        gates |= {
            "thermal_objective": Gate(0.0 if last.objective_converged else 1.0, 0.5),
            "velocity_change": Gate(last.relative_velocity_change if last.relative_velocity_change >= 0
                                    else float("nan"), 1e-3),
        }
        gates.setdefault("peak_stability", Gate(float("nan"), 0.05))
    return Report(gates)


def combine(*reports: Report) -> Report:
    return Report({k: g for r in reports for k, g in r.gates.items()})
