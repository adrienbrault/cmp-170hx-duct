"""Run chtFinBase on a reconstructed flow case and parse its outputs."""
import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .. import env
from ..cfd import foamdict, gates
from .build import build

# Scalar transport entries the thermal solver needs, merged into the flow dictionaries.
# `bounded` removes T*div(phi): with a screen-tolerance pressure solve the local continuity
# error otherwise undershoots the air below the inlet temperature (0.3 K on V23). The smooth
# cubic limiter replaces the min/max one, whose switching kept the coupling in a limit cycle.
SCHEMES = {"divSchemes/div(phi,T)": "bounded Gauss linearUpwind grad(T)",
           "gradSchemes/grad(T)": "cellLimited<cubic> 1.5 Gauss linear 1"}
SOLVER = {"solvers/T": "{solver PBiCGStab; preconditioner DILU; tolerance 1e-10; relTol 0;}"}
OK_EXIT = (0, 2)  # 2: finished but the solver's own thermal objective was not met


@dataclass
class ThermalResult:
    flow_time: str
    peak_rise_K: float
    peak_base_K: list[float]
    energy_error: float  # |boundary enthalpy - 2P| / 2P
    exchange_energy_error: float
    base_change_K: float  # largest base-temperature change over the last coupling iteration
    undershoot_K: float  # how far the coldest air cell sits below the inlet temperature
    iterations: int
    objective_converged: bool
    relative_velocity_change: float  # vs referenceFlowTime, -1 when not requested
    patch_flux: dict[str, float]
    exit_code: int
    raw: dict = field(repr=False)


def run(case: Path, reference_time: str | None = None, couplings: dict | None = None,
        log: str = "log.thermal") -> ThermalResult:
    """Solve the thermal model on the latest time. `couplings` overrides
    maxCouplingIterations / couplingRelaxation in constant/thermalProperties."""
    case = Path(case)
    exe = build()
    props = {"referenceFlowTime": reference_time if reference_time is not None else foamdict.REMOVE}
    props |= couplings or {}
    foamdict.edit(case, [("system/fvSchemes", k, v) for k, v in SCHEMES.items()]
                  + [("system/fvSolution", k, v) for k, v in SOLVER.items()]
                  + [("constant/thermalProperties", k, v) for k, v in props.items()])
    for f in ("thermal-results.json", "temperature-convergence.json"):
        (case / f).unlink(missing_ok=True)
    proc = env.foam(f"{shlex.quote(str(exe))} -latestTime", cwd=case, log=case / log, check=False)
    if proc.returncode not in OK_EXIT or not (case / "thermal-results.json").exists():
        raise RuntimeError(f"chtFinBase failed (exit {proc.returncode}); see {case / log}")
    return parse(case, proc.returncode, log)


def parse(case: Path, exit_code: int = 0, log: str = "log.thermal") -> ThermalResult:
    case = Path(case)
    raw = json.loads((case / "thermal-results.json").read_text())
    conv = json.loads((case / "temperature-convergence.json").read_text())
    peaks = [c["peak_base_K"] for c in raw["cards"]]
    flux = {n: float(q) for n, q in re.findall(r"^PATCH (\w+) Q (\S+)", (case / log).read_text(), re.MULTILINE)}
    two_p = 2 * raw["power_each_W"]
    return ThermalResult(
        flow_time=raw["flow_time"], peak_rise_K=max(peaks) - raw["inlet_T_K"], peak_base_K=peaks,
        energy_error=abs(raw["boundary_energy_W"] - two_p) / two_p,
        exchange_energy_error=raw["exchange_energy_error"], base_change_K=raw["base_change_K"],
        undershoot_K=max(0.0, raw["inlet_T_K"] - raw["air_min_K"]),
        iterations=raw["iterations"], objective_converged=conv["thermal_objective_converged"],
        relative_velocity_change=raw["relative_velocity_change_from_reference"],
        patch_flux=flux, exit_code=exit_code, raw=raw)


def acceptance(results: list[ThermalResult]) -> dict:
    """Default gates decide acceptance; the strict set is reported alongside, not gated on."""
    default, strict = gates.thermal(results), gates.thermal(results, strict=True)
    verdict = "accepted" if default.passed else f"not accepted ({'; '.join(default.failures())})"
    verdict = f"thermal: {verdict}; strict {'passed' if strict.passed else 'failed: ' + ', '.join(strict.failures())}"
    return {"accepted": default.passed, "verdict": verdict, "peak_rise_K": results[-1].peak_rise_K,
            "undershoot_K": results[-1].undershoot_K, "gates": default.as_dict(), "strict": strict.as_dict()}
