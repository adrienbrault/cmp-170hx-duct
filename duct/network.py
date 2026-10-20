"""Lumped airflow/thermal network: fan curves against the calibrated system curve.

This is the fast tool for fan decisions (RPM, stacking, push-pull). CFD calibrates it
and checks shape-dependent questions; it does not need to run for every fan option.

Calibration source: work/cooling-final/results.json at tag `pre-restructure`, cases
reference2000 / reference55 / reference3000 (V8-derived 55 mm duct, 250 W per card, no bracket plate) for
the system curve; the bracket, collector and peak-rise terms from the V28 runs with the case's rear panel (bracket
windows behind the chassis slot openings, collector v2) below.
"""
from dataclasses import dataclass
import math
import warnings

import numpy as np
from scipy.optimize import brentq, curve_fit

from .cfd import fan, porous
from .params import V23

RHO = 1.2
FAN_AREA = fan.ANNULUS_AREA  # P12 Pro annulus, m²
REFERENCE_POWER_W = 250.0

# (rpm, inlet Q m³/s, peak base rise K at 250 W/card). The 3000 rpm case missed only the
# old strict gates; its Q and peak drifted < 0.01 % and < 0.003 K over its last window.
CALIBRATION = [
    (2000, 0.00930747117, 87.24707038700001),
    (2500, 0.0123708482, 77.83740362700001),
    (3000, 0.0154902353, 72.42997410700002),
]


# (run, inlet Q m³/s, peak base rise K at 250 W/card): V28, actuator-disk fans, bracket windows behind the rear panel
# (1 fan @2500, 2 stacked @2500, push-pull 2500/2500 with collector v1 and v2, 3000/3000 v2; middle slot closed).
# The panel's rib sits over each card's main fin path, so the side paths take more of the flow (main share 0.83 ->
# 0.79): at equal Q these run 1.0-1.6 K hotter than the window-only fit below. Stacked and push-pull, v1 and v2,
# fall on one curve (residuals < 0.05 K).
BRACKET_RISE = [
    ("v28-1fan-panel", 0.00912963807, 87.193295757),
    ("v28-2stacked-panel", 0.01155955999, 79.249532748),
    ("v28-pushpull-panel-v1", 0.01251212133, 77.047323334),
    ("v28-pushpull-panel-closed", 0.01246514965, 77.078015836),
    ("v28-pushpull-panel-3000-closed", 0.01528325266, 72.332081696),
]

# The windows alone, no panel: V25, boundary fans (1 fan @2500, 2 stacked @2500, push-pull 2500/2500, 2177/2177,
# 3000/3000). The bracket shifts flow toward the fins, so at equal Q these run 1.0-2.0 K cooler than the reference
# fit; stacked and push-pull fall on one curve (residuals < 0.05 K).
WINDOW_RISE = [
    ("v25b-1fan", 0.01035579757, 81.291949124),
    ("v25b-pushpull-2177", 0.01231480721, 76.384119303),
    ("v25b-2stacked", 0.01320191954, 74.601241091),
    ("v25b-pushpull", 0.01451249416, 72.557959234),
    ("v25b-pushpull-3000", 0.0179326969, 68.619644112),
]


def _rise_fit(points) -> tuple[float, float, float]:
    q, t = np.array([c[1] for c in points]), np.array([c[2] for c in points])
    with warnings.catch_warnings():  # three reference points, three parameters: covariance undefined
        warnings.simplefilter("ignore")
        (c0, c1, m), _ = curve_fit(lambda Q, c0, c1, m: c0 + c1 * (Q * 1e3) ** -m, q, t, p0=(50, 300, 1))
    return c0, c1, m


def _fit():
    q = np.array([c[1] for c in CALIBRATION])
    # The total pressure those runs applied: their fan table used the legacy 17 mm hub annulus.
    p = np.array([fan.total_pressure(qi, rpm, area=fan.LEGACY_ANNULUS_AREA) for rpm, qi, _ in CALIBRATION])
    (a, b), _ = curve_fit(lambda Q, a, b: a * Q + b * Q * Q, q, p)
    return a, b


SYSTEM_A, SYSTEM_B = _fit()
RISE_FIT_REFERENCE = _rise_fit(CALIBRATION)   # no bracket plate (the reference runs)
RISE_FIT = _rise_fit(BRACKET_RISE)            # bracket windows behind the rear panel: every setup
RISE_FIT_WINDOW = _rise_fit(WINDOW_RISE)      # bracket windows alone (the V23/V25 runs)
EXTRAPOLATION_Q = max(c[1] for c in BRACKET_RISE) * 1.02

# The cards' rear bracket (duct.cfd.bracket): a solid plate with one ~81 x 25 mm window per card, in every setup,
# and the case's rear panel flush past it: each window straddles the 7.07 mm steel rib between the card's two chassis
# slot openings (duct.cad.hardware), leaving 1452 of its 2025 mm² open (two strips). The reference runs above had
# neither (their card ports opened straight onto ambient), so the system curve adds BRACKET_K fan-annulus velocity
# heads, defined flow-consistently: the k that makes evaluate() reproduce the CFD flow with the same fan
# (duct.cfd.breakdown `bracket_k`). Calibrated on runs/v28-1fan-panel (V28, actuator-disk fan @2500, bracket
# windows at refine 2 behind the panel: Q 9.130 L/s): 22.46. The disk fan runs ~0.7 % off the boundary fan curve the
# network uses (V23); that is folded in. The station drop across bracket and panel alone is 21.36 heads, Idelchik's
# sharp-edged exit-orifice estimate on the open area, bracket_k_estimate() = 19.5. The window size is ±10 % and the
# panel geometry is CEM minimum openings, unmeasured.
# BRACKET_K_WINDOW: the windows alone, no panel (runs/v23b-1fan, V23, boundary fan: Q 10.356 L/s): 11.10; the
# V23/V25 bracket-window runs below check against it.
PORT_AREA = sum((x1 - x0) * (y1 - y0) for _, _, (x0, x1, y0, y1) in V23.port_boxes) * 1e-6  # both cards, m²
BRACKET_K = 22.46
BRACKET_K_WINDOW = 11.10


def bracket_k_estimate(window_area: float | None = None) -> float:
    """Idelchik: a thin sharp-edged window exhausting to free space loses the vena-contracta jet head,
    (1/(ε f))² approach heads (duct.cfd.bracket.exit_loss_heads), less the port exit head the system curve
    already counts; in fan-annulus heads. window_area (m², both cards): default the open area past the rear panel
    (duct.cfd.bracket.open_area: each window less the panel rib behind it)."""
    from .cfd import bracket  # noqa: PLC0415
    if window_area is None:
        window_area = sum(bracket.open_area(V23, bracket.BRACKET)) * 1e-6
    return (bracket.exit_loss_heads(window_area / PORT_AREA) - 1) * (FAN_AREA / PORT_AREA) ** 2


def grille_k(open_area: float = 1.0) -> float:
    """Optional perforated-plate grille (duct.cfd.porous) in fan-annulus velocity heads; 1: none (the default)."""
    return porous.perforated_plate_k(open_area) * (FAN_AREA / PORT_AREA) ** 2 if open_area < 1 else 0.0


# Push-pull collector, past the bracket, in fan-annulus velocity heads: collector and fan-face velocity profile
# losses net of the jet head the collector recovers, relative to BRACKET_K's free jets (hence negative).
# Flow-consistent like BRACKET_K (duct.cfd.breakdown `collector_k`): from runs/v28-pushpull-panel-closed (V28,
# actuator-disk fans 2500/2500, COLLECTOR_V2 on the rear panel, middle slot closed: Q 12.465 L/s)
# 22.18 - BRACKET_K = -0.29. The network has one path, through the fins: it models a collector sealed to the cards.
# With an empty slot under its mouth (v2 over slot 0; duct.cfd.collector.open_slots) the exhaust fan also draws case
# air, which it does not model; COLLECTOR_V3 seals per card and checks it: runs/v28-pp-v3, 12.504 L/s (estimate 12.47).
# The calibration runs predate the collector-mouth refinement and the covers flag; rebuild them with
# --covered-slots=-3,0,3 (v2 old vs new mesh: 0.1 % on Q).
# COLLECTOR_K_WINDOW: windows alone, no panel, COLLECTOR_V1 (runs/v23b-pushpull, V23, boundary fans: Q 14.521 L/s)
# 9.898 - BRACKET_K_WINDOW = -1.20; the pull-only run (runs/v23b-pull, 10.370 L/s) gives -1.11.
COLLECTOR_K = -0.29
COLLECTOR_K_WINDOW = -1.20


@dataclass(frozen=True)
class Setup:
    rpm: float = 2500                # intake fan; 0: none (pull only, open intake)
    stacked: int = 1                 # intake fans in series, touching
    stack_efficiency: float = fan.STACK_EFFICIENCY  # fraction of ideal pressure gain per extra stacked fan
    pull_rpm: float | None = None    # exhaust fan on the collector (push-pull)
    collector_k: float = COLLECTOR_K  # collector loss past the grille, velocity heads at the fan annulus
    bracket_k: float = BRACKET_K     # bracket window loss, fan-annulus heads; 0: none (the reference runs)
    grille_open_area: float = 1.0    # optional perforated-plate grille; 1: none
    fan_area: float = FAN_AREA       # intake annulus of the fan table (fan.LEGACY_ANNULUS_AREA: the reference runs)
    power_w: float = 250.0           # per card
    label: str = ""


BASELINE = Setup(label="1 fan @2500")


def system_pressure(Q: float, s: Setup) -> float:
    q_ann = 0.5 * RHO * (Q / FAN_AREA) ** 2
    dp = SYSTEM_A * Q + SYSTEM_B * Q * Q + (s.bracket_k + grille_k(s.grille_open_area)) * q_ann
    if s.pull_rpm:
        dp += s.collector_k * q_ann
    return dp


def available_pressure(Q: float, s: Setup, pull_fan: fan.FanModel = fan.P12_PRO) -> float:
    """Fan pressure at Q; `pull_fan`: the exhaust fan's chart."""
    dp = (fan.total_pressure(Q, s.rpm, count_series=s.stacked, series_efficiency=s.stack_efficiency, area=s.fan_area)
          if s.rpm else 0.0)
    if s.pull_rpm:
        # Exhausting to ambient, the pull fan's exit velocity head is lost: its static curve applies.
        dp += fan.static_pressure(Q, s.pull_rpm, model=pull_fan)
    return dp


def flow(s: Setup) -> float:
    return brentq(lambda Q: available_pressure(Q, s) - system_pressure(Q, s), 1e-5, 0.08)


def peak_base_rise(Q: float, power_w: float = REFERENCE_POWER_W, fit: tuple = RISE_FIT) -> float:
    """Peak modeled heat-spreader rise above intake, K. Linear in power (constant properties). `fit`:
    RISE_FIT (bracket windows behind the panel), RISE_FIT_WINDOW (windows alone) or RISE_FIT_REFERENCE (no bracket)."""
    c0, c1, m = fit
    return power_w / REFERENCE_POWER_W * (c0 + c1 * (Q * 1e3) ** -m)


def noise_delta_db(s: Setup, ref_rpm: float = 2500) -> float:
    """Rule-of-thumb sound level vs one fan at ref_rpm: 50·log10 speed law, +10·log10 per source,
    +3 dB wake interaction for touching stacked fans. Not P12 Pro acoustic data."""
    sources = ([s.rpm] * s.stacked if s.rpm else []) + ([s.pull_rpm] if s.pull_rpm else [])
    power = sum(10 ** (50 * math.log10(r / ref_rpm) / 10) for r in sources)
    return 10 * math.log10(power) + (3.0 if s.stacked > 1 else 0.0)


def evaluate(s: Setup) -> dict:
    Q = flow(s)
    return dict(label=s.label, flow_ls=Q * 1e3, pressure_pa=system_pressure(Q, s),
                peak_base_rise_k=peak_base_rise(Q, s.power_w), noise_db=noise_delta_db(s),
                extrapolated=Q > EXTRAPOLATION_Q)


# CFD checks (V28, actuator-disk fans, bracket windows behind the rear panel): (setup, Q m³/s, peak base rise K).
BRACKET_CFD = [
    (Setup(), 0.009130, 87.19),                             # runs/v28-1fan-panel
    (Setup(stacked=2), 0.011560, 79.25),                    # runs/v28-2stacked-panel
]
PUSH_PULL_CFD = [                                           # COLLECTOR_V2, middle slot closed
    (Setup(pull_rpm=2500), 0.012465, 77.08),                # runs/v28-pushpull-panel-closed
    (Setup(rpm=3000, pull_rpm=3000), 0.015283, 72.33),      # runs/v28-pushpull-panel-3000-closed
]
# The windows alone, no panel (V23, boundary fans), with the window-only terms.
_WINDOW = dict(bracket_k=BRACKET_K_WINDOW, collector_k=COLLECTOR_K_WINDOW)
WINDOW_CFD = [
    (Setup(**_WINDOW), 0.010356, 81.30),                    # runs/v23b-1fan
    (Setup(pull_rpm=2500, **_WINDOW), 0.014521, 72.57),     # runs/v23b-pushpull, COLLECTOR_V1
    (Setup(rpm=0, pull_rpm=2500, **_WINDOW), 0.010370, 81.40),   # runs/v23b-pull: open intake, no fan
]

STANDARD = [
    Setup(label="1 fan @2500"),
    Setup(rpm=3000, label="1 fan @3000"),
    Setup(stacked=2, label="2 stacked @2500"),
    Setup(stacked=2, rpm=3000, label="2 stacked @3000"),
    Setup(pull_rpm=2500, label="push-pull @2500"),
    Setup(rpm=2177, pull_rpm=2177, label="push-pull @2177"),   # equal noise to 1 fan @2500 (50·log10 rule)
    Setup(rpm=0, pull_rpm=2500, label="pull only @2500"),
    Setup(rpm=3000, pull_rpm=3000, label="push-pull @3000"),
]
