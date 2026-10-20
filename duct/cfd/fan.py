"""Fan curves (ARCTIC P12 Pro, P14 Pro Reverse), affinity/series scaling and the operating point.

All public functions take SI units (Q in m³/s, pressure in Pa) and accept numpy arrays; `model` (a FanModel) picks the
chart, default the P12 Pro (the intake fan, and the exhaust fan of every 120 mm collector).
The manufacturer chart gives fan static pressure, rated with a free outlet: p_sF = p_s,out - p_t,in.
OpenFOAM's `fanPressure` table therefore gets p_sF + ½ρ(Q/A)², A being the patch the fan acts on
(the fan annulus by default; series fans share one exit, so the term is added once):

- direction in (intake): the patch total pressure is p0 + table, and the fan's outlet total pressure
  is p_sF + p_v,out.
- direction out (exhaust to ambient): on outflow faces the patch *static* pressure is p0 - table
  (totalPressure drops ½|U|² only on inflow). The rating puts the fan-inlet total pressure at -p_sF, so
  static = -p_sF - ½ρ(Q/A)²: the same total table, not the static one. Check: a lossless annulus tube
  with an open inlet must deliver free flow (p_sF = 0); a static table would stop where p_sF = p_v.
  The exhaust velocity head is lost to ambient through p_sF's own definition, as in network.py.
"""
import math
from dataclasses import dataclass, replace

import numpy as np

# Manufacturer PQ chart at 3000 rpm: (CFM, mmH2O static).
P12_PRO_3000 = (
    (0.0, 6.9), (10.0, 5.95), (20.0, 5.0), (30.0, 4.1), (35.0, 3.78), (40.0, 3.65), (45.0, 3.48),
    (50.0, 3.2), (55.0, 2.77), (60.0, 2.17), (65.0, 1.52), (70.0, 0.9), (75.0, 0.22), (77.0, 0.0),
)
CHART_RPM = 3000.0
CFM = 0.00047194745  # m³/s
MMH2O = 9.80665  # Pa
RHO = 1.2  # kg/m³, the incompressible CFD density
# Fan annulus, the one source for the CFD domain (DomainParams), the BC tables and network.py.
# Tip: ARCTIC's 117 mm bore cut-out. Hub: measured Ø50.3 mm on a front photo of the P12 Pro (hwcooling.net review,
# arctic-p12-pro-03: 240 px across the hub cap against 500.6 px between the 105 mm mounting-hole centres; the cap
# stands slightly proud of the frame, so this reads a little high) and Ø≈51 mm scaled off ARCTIC's 2D drawing.
TIP_RADIUS = 0.0585  # m
HUB_RADIUS = 0.02525  # m
ANNULUS_AREA = math.pi * (TIP_RADIUS**2 - HUB_RADIUS**2)
# The reference runs (reference55 at 2000/2500/3000 rpm) applied their fan table on a 17 mm hub annulus.
LEGACY_HUB_RADIUS = 0.017
LEGACY_ANNULUS_AREA = math.pi * (TIP_RADIUS**2 - LEGACY_HUB_RADIUS**2)
SYSTEM_A = 1117.7  # Pa·s/m³, fitted from accepted 2000/2500/3000 rpm runs (legacy annulus)
SYSTEM_B = 94207.0  # Pa·s²/m⁶


@dataclass(frozen=True)
class FanModel:
    """A fan: its manufacturer PQ chart ((CFM, mmH2O static) at chart_rpm) and its annulus (m)."""
    name: str
    pq: tuple[tuple[float, float], ...]
    chart_rpm: float
    tip_radius: float
    hub_radius: float

    @property
    def area(self) -> float:
        return math.pi*(self.tip_radius**2-self.hub_radius**2)


P12_PRO = FanModel("ARCTIC P12 Pro", P12_PRO_3000, CHART_RPM, TIP_RADIUS, HUB_RADIUS)
# ARCTIC's P/Q curve for the P14 Pro Reverse (ACFAN00329A; 140 x 140 x 30 mm, 400-2650 rpm, 98 CFM, 5.1 mmH2O), digitized
# from the vector path in its spec sheet (arctic.de Spec_Sheet_P14_Pro_Reverse_EN.pdf, 2025), endpoints snapped to the
# rated 5.1 mmH2O and 98 CFM. The sheet does not label the curve's rpm: taken as the 2650 rpm maximum (its free-delivery
# end is the rated maximum airflow). Near-linear, without the P12 Pro's knee.
P14_PRO_REVERSE_2650 = (
    (0.0, 5.1), (5.0, 4.85), (10.0, 4.6), (15.0, 4.34), (20.0, 4.07), (25.0, 3.77), (30.0, 3.57), (35.0, 3.37),
    (40.0, 3.05), (45.0, 2.71), (50.0, 2.38), (55.0, 2.23), (60.0, 2.02), (65.0, 1.86), (70.0, 1.59), (75.0, 1.26),
    (80.0, 0.99), (85.0, 0.59), (90.0, 0.39), (95.0, 0.16), (98.0, 0.0),
)
# Annulus: the bore and hub of COLLECTOR_PLUG_140 (estimates; for_collector takes them from the collector).
P14_PRO_REVERSE = FanModel("ARCTIC P14 Pro Reverse", P14_PRO_REVERSE_2650, 2650.0, .068, .028)
MODELS = {m.name: m for m in (P12_PRO, P14_PRO_REVERSE)}


def for_collector(c) -> FanModel:
    """The exhaust fan of a collector (duct.params.CollectorParams) by its fan_size: 120 the P12 Pro, 140 the P14 Pro
    Reverse on the collector's bore (fan_radius) and hub (fan_hub_diameter)."""
    if c.fan_size == 120.0:
        return P12_PRO
    assert c.fan_size == 140.0, f"no fan model for a {c.fan_size:g} mm fan"
    return replace(P14_PRO_REVERSE, tip_radius=c.fan_radius*1e-3, hub_radius=c.fan_hub_diameter*.5e-3)


# Fraction of the ideal static-pressure gain per extra stacked (touching) fan: an assumption, shared by the CFD
# case builder and network.py. The first two-fan CFD (runs/v23-2fans) used 1.0.
STACK_EFFICIENCY = 0.7
_BEYOND_FREE_DELIVERY_SLOPE = 1e6  # Pa per m³/s past the chart's zero-pressure end

_Q = np.array([q for q, _ in P12_PRO_3000]) * CFM
_P = np.array([p for _, p in P12_PRO_3000]) * MMH2O


def _table(model: FanModel) -> tuple[np.ndarray, np.ndarray]:
    return np.array([q for q, _ in model.pq]) * CFM, np.array([p for _, p in model.pq]) * MMH2O


def series_factor(count_series: int = 1, series_efficiency: float = 1.0) -> float:
    """Static-pressure multiplier for N identical fans stacked in series."""
    return 1.0 + (count_series - 1) * series_efficiency


def chart(rpm: float, count_series: int = 1, series_efficiency: float = 1.0,
          model: FanModel = P12_PRO) -> tuple[np.ndarray, np.ndarray]:
    """(Q m³/s, static Pa) table scaled by affinity laws (Q ∝ n, P ∝ n²) and series count."""
    r = rpm / model.chart_rpm
    q, p = _table(model)
    return q * r, p * r**2 * series_factor(count_series, series_efficiency)


def static_pressure(Q, rpm: float, count_series: int = 1, series_efficiency: float = 1.0, model: FanModel = P12_PRO):
    """Static pressure rise; extrapolates steeply negative beyond free delivery."""
    q, p = chart(rpm, count_series, series_efficiency, model)
    Q = np.asarray(Q, dtype=float)
    out = np.interp(Q, q, p)
    out = np.where(Q > q[-1], -_BEYOND_FREE_DELIVERY_SLOPE * (Q - q[-1]), out)
    return out if out.ndim else float(out)


def dynamic_pressure(Q, area: float = ANNULUS_AREA):
    return 0.5 * RHO * (np.asarray(Q, dtype=float) / area) ** 2


def total_pressure(Q, rpm: float, count_series: int = 1, series_efficiency: float = 1.0, area: float = ANNULUS_AREA,
                   model: FanModel = P12_PRO):
    out = static_pressure(Q, rpm, count_series, series_efficiency, model) + dynamic_pressure(Q, area)
    return out if np.ndim(out) else float(out)


def system_pressure(Q, a: float = SYSTEM_A, b: float = SYSTEM_B):
    return a * np.asarray(Q, dtype=float) + b * np.asarray(Q, dtype=float) ** 2


def operating_point(rpm: float, count_series: int = 1, series_efficiency: float = 1.0,
                    a: float = SYSTEM_A, b: float = SYSTEM_B, area: float = LEGACY_ANNULUS_AREA) -> float:
    """Q (m³/s) where the fan's total pressure meets ΔP = a·Q + b·Q² (bisection); the default system curve
    was fitted on the legacy annulus."""
    def f(q):
        return total_pressure(q, rpm, count_series, series_efficiency, area) - system_pressure(q, a, b)
    lo, hi = 0.0, chart(rpm)[0][-1]
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return 0.5 * (lo + hi)


def fan_pressure_bc(rpm: float, count_series: int = 1, series_efficiency: float = 1.0,
                    direction: str = "in", area: float = ANNULUS_AREA, model: FanModel = P12_PRO) -> str:
    """OpenFOAM `fanPressure` patch entry: kinematic (Pa/ρ) static curve plus the velocity pressure on
    `area`, the fan patch (module docstring). The initial value is the patch pressure at zero flow."""
    assert direction in ("in", "out"), direction
    q, _ = chart(rpm, count_series, series_efficiency, model)
    pk = total_pressure(q, rpm, count_series, series_efficiency, area, model) / RHO
    table = " ".join(f"({qi:.9g} {pi:.9g})" for qi, pi in zip(q, pk))
    value = pk[0] if direction == "in" else -pk[0]
    return (f"{{type fanPressure; fanCurve table ({table}); direction {direction}; "
            f"p0 uniform 0; value uniform {value:.6g};}}")


def fan_jump_bc(rpm: float, count_series: int = 1, series_efficiency: float = 1.0, model: FanModel = P12_PRO) -> str:
    """OpenFOAM `fan` cyclic-baffle entry (actuator disk): kinematic total-pressure rise against the volume
    flow through the disk (velocity pressure on the model's annulus). With equal areas either side the static jump
    is the total rise, p_sF + p_v."""
    q, _ = chart(rpm, count_series, series_efficiency, model)
    pk = total_pressure(q, rpm, count_series, series_efficiency, model.area, model) / RHO
    table = " ".join(f"({qi:.9g} {pi:.9g})" for qi, pi in zip(q, pk))
    return (f"{{type fan; patchType cyclic; mode volumeFlowRate; jumpTable table ({table}); "
            "jump uniform 0; value uniform 0;}")


def total_pressure_bc(pressure_pa: float) -> str:
    """OpenFOAM fixed `totalPressure` patch entry from a pressure in Pa."""
    pk = pressure_pa / RHO
    return f"{{type totalPressure; p0 uniform {pk:.12g}; value uniform {pk:.12g};}}"
