"""Run a prepared porousSimpleFoam case: profile dictionaries, decomposition, live gate monitoring.

The solver runs as one process per segment while this module polls the flux/residual function
objects; once the flow gates pass it drops a STOP file that the `abort` function object turns
into a clean write-and-exit. Re-running on the same case resumes from its latest time.
"""
import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .. import env
from . import fan, foamdict, gates, profiles

UPWIND = "bounded Gauss upwind"
WRITE_INTERVAL = 100


def _flux(patch: str, region: str = "patch") -> str:
    return (f"{{type surfaceFieldValue; libs (fieldFunctionObjects); regionType {region}; name {patch}; "
            "operation sum; fields (phi); writeFields false; log false; writeControl timeStep; writeInterval 1;}")


_TAIL = ("residuals {type solverInfo; libs (utilityFunctionObjects); fields (U p k omega); "
         "writeControl timeStep; writeInterval 1;} "
         'stopFile {type abort; libs (utilityFunctionObjects); file "<case>/STOP"; action writeNow;}}')
# The run owns the case's function objects: patch fluxes and residuals feed the gates, and
# the abort object stops the solver cleanly when this module writes <case>/STOP.
FUNCTIONS = f"{{inletFlow {_flux('inlet')} leftFlow {_flux('outletLeft')} rightFlow {_flux('outletRight')} "+_TAIL
# With a collector the card exits are internal: per-card flux through the +z-oriented cardExit
# faceZones (duct.cfd.case.topo_set), plus the exhaust patch for the record.
COLLECTOR_FUNCTIONS = (f"{{inletFlow {_flux('inlet')} leftFlow {_flux('cardExit0', 'faceZone')} "
                       f"rightFlow {_flux('cardExit1', 'faceZone')} exhaustFlow {_flux('exhaust')} "+_TAIL)
FLUX_FOS = {"q_in": "inletFlow", "q_left": "leftFlow", "q_right": "rightFlow"}


def case_meta(case: Path) -> dict:
    p = Path(case) / "case.json"
    return json.loads(p.read_text()) if p.exists() else {}


def functions(case: Path) -> str:
    patches = case_meta(case).get("patches", {})
    if "exhaust" not in patches:
        return FUNCTIONS
    if "caseAir" in patches:  # the open middle slot: case air into the collector, for the record
        return COLLECTOR_FUNCTIONS.replace(" residuals ", f" caseAirFlow {_flux('caseAir')} residuals ", 1)
    return COLLECTOR_FUNCTIONS


@dataclass(frozen=True)
class Inlet:
    """How the inlet is driven on a cold start. `case`: keep the case's BC (the case builder
    writes fanPressure); `fixed`: totalPressure at pressure_pa; `fan`: native fanPressure;
    `match`: legacy outer loop adjusting a fixed totalPressure to the fan curve.
    rpm 0: no intake fan (open inlet, totalPressure 0). `pull_rpm` (fan mode): also rewrite a
    collector case's exhaust fanPressure; otherwise the exhaust keeps the case's BC. Match and the
    gates only use the inlet and per-card fluxes, so they hold with either outlet."""
    mode: str = "case"
    pressure_pa: float | None = None
    rpm: float = 2500.0
    count_series: int = 1
    series_efficiency: float = fan.STACK_EFFICIENCY
    direction: str = "in"  # fanPressure direction: in (push) / out (pull)
    pull_rpm: float | None = None

    def __post_init__(self):
        if self.mode not in ("case", "fixed", "fan", "match"):
            raise ValueError(f"unknown inlet mode {self.mode!r}")
        if self.mode == "fixed" and self.pressure_pa is None:
            raise ValueError("fixed inlet needs pressure_pa")
        if self.mode == "match" and self.rpm == 0:
            raise ValueError("match needs an intake fan (rpm > 0)")

    def operating_pressure(self) -> float:
        q = fan.operating_point(self.rpm, self.count_series, self.series_efficiency)
        return fan.total_pressure(q, self.rpm, self.count_series, self.series_efficiency)


# --- case queries ----------------------------------------------------------------------------

def _times(d: Path) -> list[float]:
    out = []
    for p in d.iterdir() if d.exists() else []:
        try:
            out.append(float(p.name))
        except ValueError:
            continue
    return sorted(out)


def latest_time(case: Path) -> str:
    t = _times(case)
    return f"{t[-1]:g}" if t else "0"


def _read_dat(fo_dir: Path) -> tuple[list[str], dict[int, list[str]]]:
    """Column header and rows by iteration across restarts (later files win)."""
    header: list[str] = []
    rows: dict[int, list[str]] = {}
    for f in sorted(fo_dir.glob("*/*.dat"), key=lambda p: (float(p.parent.name), p.stat().st_mtime)):
        for line in f.read_text().splitlines():
            if line.startswith("#"):
                header = line[1:].split()
            elif line.strip():
                parts = line.split()
                rows[round(float(parts[0]))] = parts
    return header, rows


def history(case: Path) -> gates.History:
    pp = Path(case) / "postProcessing"
    series = {k: _read_dat(pp / fo)[1] for k, fo in FLUX_FOS.items()}
    its = sorted(set.intersection(*map(set, series.values())))
    q = {k: np.array([float(s[i][1]) for i in its]) for k, s in series.items()}
    head, res = _read_dat(pp / "residuals")
    last = res[max(res)] if res else []
    residuals = {n.removesuffix("_initial"): np.array([float(last[j])])
                 for j, n in enumerate(head) if n.endswith("_initial") and j < len(last)}
    return gates.History(np.array(its, dtype=int), q["q_in"], q["q_left"], q["q_right"], residuals)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=float))
    os.replace(tmp, path)


# --- solver segments --------------------------------------------------------------------------

def _inlet_edits(case: Path, bc: str, patch: str = "inlet") -> list[tuple[str, str, str]]:
    """Set a patch's p BC at the latest time, in the reconstructed and any decomposed copy."""
    t = latest_time(case)
    files = [f"{t}/p"] + [f"{p.name}/{t}/p" for p in sorted(case.glob("processor*")) if (p / t).exists()]
    return [(f, f"boundaryField/{patch}", bc) for f in files]


def _decompose(case: Path, nprocs: int) -> None:
    proc = case / "processor0"
    if (len(list(case.glob("processor*"))) == nprocs and _times(proc)
            and _times(proc)[-1] >= float(latest_time(case))):
        return  # resume from the decomposed state
    env.foam("decomposePar -force -latestTime", cwd=case, log=case / "log.decomposePar")


class Run:
    def __init__(self, case: Path, profile: profiles.Profile, nprocs: int, inlet: Inlet, strict: bool,
                 gate_window: int = gates.WINDOW, gate_limit: float = 5e-3, gate_split_limit: float | None = None,
                 min_iterations: int = 0):
        self.case, self.profile, self.nprocs, self.inlet, self.strict = Path(case), profile, nprocs, inlet, strict
        self.gate_window, self.gate_limit, self.gate_split_limit = gate_window, gate_limit, gate_split_limit
        self.min_iterations = min_iterations   # the gates do not stop the solver before this iteration (fixed-length runs)
        self.t0 = time.time()
        self.status_path = self.case / "status.json"
        self.segments: list[dict] = []
        self.report = gates.Report({})

    def status(self, stage: str, **extra) -> dict:
        h = history(self.case)
        data = dict(case=self.case.name, stage=stage, profile=self.profile.name, nprocs=self.nprocs, min_iterations=self.min_iterations,
                    inlet=asdict(self.inlet), strict=self.strict, elapsed_s=round(time.time() - self.t0, 1),
                    iteration=int(h.iteration[-1]) if len(h.iteration) else None,
                    q_lps=float(abs(h.q_in[-1]) * 1e3) if len(h.q_in) else None,
                    gates=self.report.as_dict(), passed=self.report.passed and bool(self.report.gates),
                    gate_window=self.gate_window, window=gates.window_mean(h, self.gate_window),
                    segments=self.segments, **extra)
        _write_json(self.status_path, data)
        return data

    def check(self, h: gates.History) -> gates.Report:
        return gates.flow(h, self.strict, self.gate_window, self.gate_limit, self.gate_split_limit)

    def prepare(self, iterations: int, extra: list) -> None:
        start = latest_time(self.case)
        end = int(float(start)) + iterations
        end += -end % WRITE_INTERVAL
        edits = [("system/fvSolution", k, v) for k, v in self.profile.fvSolution.items()]
        edits += [("system/controlDict", k, v) for k, v in {
            "startFrom": "latestTime", "stopAt": "endTime", "endTime": end, "writeControl": "timeStep",
            "writeInterval": WRITE_INTERVAL, "purgeWrite": 2, "runTimeModifiable": "true",
            "writeFormat": "binary", "writeCompression": "off", "functions": functions(self.case)}.items()]
        edits += [("system/decomposeParDict", k, v) for k, v in
                  {"numberOfSubdomains": self.nprocs, "method": "scotch"}.items()]
        if "libs" in (self.case / "system/controlDict").read_text():  # archived Metal backend
            edits.append(("system/controlDict", "libs", foamdict.REMOVE))
        foamdict.edit(self.case, edits + extra)

    def segment(self, iterations: int, since: int | None = None, edits: list = ()) -> gates.Report:
        """Apply `edits` with the profile, then run until the flow gates pass or the budget ends."""
        start = int(float(latest_time(self.case)))
        upwind_until, scheme, edits = 0, None, list(edits)
        if start == 0 and self.profile.upwind_iterations:
            scheme = foamdict.get(self.case, "system/fvSchemes", ["divSchemes/div(phi,U)"])["divSchemes/div(phi,U)"]
            edits.append(("system/fvSchemes", "divSchemes/div(phi,U)", UPWIND))
            upwind_until = self.profile.upwind_iterations
        self.prepare(iterations, edits)
        since = start if since is None else since
        if self.nprocs > 1:
            _decompose(self.case, self.nprocs)
        cmd = (f"mpirun -np {self.nprocs} porousSimpleFoam -parallel" if self.nprocs > 1 else "porousSimpleFoam")
        stop = self.case / "STOP"
        stop.unlink(missing_ok=True)
        seg = {"start": start, "wall_s": None, "end": None, "stopped_by": "endTime"}
        self.segments.append(seg)
        t_seg = time.time()
        with open(self.case / f"log.flow.{start}", "w") as log:
            proc = subprocess.Popen([str(env.openfoam_launcher()), "-c", cmd], cwd=self.case,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while proc.poll() is None:
                    time.sleep(2.0)
                    h = history(self.case)
                    it = int(h.iteration[-1]) if len(h.iteration) else start
                    if upwind_until and it >= upwind_until:
                        foamdict.edit(self.case, [("system/fvSchemes", "divSchemes/div(phi,U)", scheme)])
                        since, upwind_until = it, 0
                    self.report = self.check(_since(h, since))
                    if self.report.passed and not upwind_until and it >= self.min_iterations and not stop.exists():
                        stop.write_text("action=writeNow\n")
                        seg["stopped_by"] = "gates"
                    self.status("flow", segment_start=start)
            finally:
                if proc.poll() is None:  # interrupted: stop mpirun and its ranks too
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait()
                stop.unlink(missing_ok=True)
                if scheme and upwind_until:  # stopped during upwind: restore the case scheme
                    foamdict.edit(self.case, [("system/fvSchemes", "divSchemes/div(phi,U)", scheme)])
        if proc.returncode:
            self.status("failed", error=f"solver exit {proc.returncode}; see log.flow.{start}")
            raise RuntimeError(f"porousSimpleFoam failed (exit {proc.returncode}) in {self.case}")
        if self.nprocs > 1:
            env.foam("reconstructPar -latestTime", cwd=self.case, log=self.case / "log.reconstructPar")
        h = history(self.case)
        self.report = self.check(_since(h, since))
        seg.update(end=int(h.iteration[-1]), wall_s=round(time.time() - t_seg, 1), passed=self.report.passed)
        return self.report


def _since(h: gates.History, it: int) -> gates.History:
    m = h.iteration > it
    return gates.History(h.iteration[m], h.q_in[m], h.q_left[m], h.q_right[m], h.residuals)


def run(case: Path, profile: str | profiles.Profile = "screen", nprocs: int | None = None,
        inlet: Inlet | None = None, iterations: int = 3000, strict: bool = False,
        match_tolerance_pa: float = 0.01, match_rounds: int = 8,
        gate_window: int = gates.WINDOW, gate_limit: float = 5e-3, gate_split_limit: float | None = None,
        min_iterations: int = 0) -> dict:
    """Run the flow to its gates or `iterations` more (rounded up to the write interval); the gates stop it no earlier
    than iteration `min_iterations` (= iterations: a fixed-length run, so compared rows share one stopping rule).
    Returns the final status, also written to <case>/status.json. `gate_window` / `gate_limit` /
    `gate_split_limit`: the default flow gates' window and bounds (duct.cfd.gates.flow)."""
    prof = profiles.get(profile) if isinstance(profile, str) else profile
    inlet = inlet or Inlet()
    r = Run(case, prof, nprocs or prof.nprocs or env.perf_cores(), inlet, strict, gate_window, gate_limit,
            gate_split_limit, min_iterations)
    if inlet.mode in ("fan", "match") and case_meta(r.case).get("options", {}).get("fan_model") == "disk":
        raise ValueError(f"--inlet {inlet.mode} rewrites the inlet patch; with actuator disks the inlet is the "
                         "far field and the fans are baffles: use --inlet case")
    # the inlet patch's annulus (the case may pin a legacy hub)
    area = case_meta(r.case).get("fan", {}).get("fan_reference_area_m2", fan.ANNULUS_AREA)
    if inlet.mode != "match":
        edits = []
        if latest_time(r.case) == "0":  # a resumed case keeps its BC: rewriting it kicks the flow
            if inlet.mode == "fan":
                edits = _inlet_edits(r.case, fan.total_pressure_bc(0.0) if inlet.rpm == 0 else
                                     fan.fan_pressure_bc(inlet.rpm, inlet.count_series, inlet.series_efficiency,
                                                         direction=inlet.direction, area=area))
                exhaust = case_meta(r.case).get("exhaust")
                if inlet.pull_rpm and exhaust:
                    edits += _inlet_edits(r.case, fan.fan_pressure_bc(inlet.pull_rpm, direction="out",
                                                                      area=exhaust["area_m2"],
                                                                      model=fan.MODELS[exhaust["model"]]), "exhaust")
            elif inlet.mode == "fixed":
                edits = _inlet_edits(r.case, fan.total_pressure_bc(inlet.pressure_pa))
        report = r.segment(iterations, edits=edits)
        return r.status("converged" if report.passed else "budget_exhausted")

    # Legacy outer loop (work/duct-v13/fan_match.py): fixed total pressure, relaxed toward the
    # fan curve at the converged flow, until the mismatch is below tolerance.
    p0 = inlet.pressure_pa if inlet.pressure_pa is not None else inlet.operating_pressure()
    budget, since, matches = iterations, None, []
    for _ in range(match_rounds):
        start = int(float(latest_time(r.case)))
        r.segment(budget, since, _inlet_edits(r.case, fan.total_pressure_bc(p0)))
        budget -= int(float(latest_time(r.case))) - start
        q = float(abs(history(r.case).q_in[-1]))
        mismatch = fan.total_pressure(q, inlet.rpm, inlet.count_series, inlet.series_efficiency, area) - p0
        matches.append({"iteration": int(float(latest_time(r.case))), "q_m3s": q, "applied_pa": p0,
                        "mismatch_pa": mismatch})
        if abs(mismatch) < match_tolerance_pa and r.report.passed:
            return r.status("converged", fan_match=matches)
        if budget <= 0:
            break
        p0 += 0.8 * mismatch
        since = int(float(latest_time(r.case)))
    return r.status("unmatched", fan_match=matches)
