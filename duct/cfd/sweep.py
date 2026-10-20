"""`duct sweep`: screen many design variants on the coarse mesh, rank them, confirm the best on the fine mesh.

A spec is JSON: a list of variants, or {"defaults": {...}, "variants": [...], "matrix": {...}}. A variant is a dict of
`duct simulate` settings (FIELDS) plus `name` and `params` (GeometryParams overrides); `matrix` expands the cartesian
product of its value lists on top of the defaults (and of each listed variant, when both are given). The CLI builds
the same structure from --variant "name=v3,collector=v3,param.chamber_length=60" and --matrix collector=v2,v3.

Every variant runs as its own `duct simulate` process into runs/SWEEP/<fidelity>/<name>, so the core pool
(duct.cfd.scheduler) decides how many solve at once. Results land in runs/SWEEP/sweep.json and sweep.md.

How far to trust the screen ranking (duct.cfd.profiles.FIDELITIES["screen"]): against the fine V28 push-pull runs it
reads fin flow 0.13-0.29 L/s high and peak rise 0.5-1.0 K low, and that offset varies by up to TIE_BAND between
designs. Screen differences inside the band are ties for the fine re-run to settle.
"""
import itertools
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# variant key -> (simulate flag, kind); kind "flag" means a boolean that emits the flag when False (--no-*)
FIELDS = {
    "preset": ("--preset", str), "collector": ("--collector", str), "rpm": ("--rpm", float),
    "pull_rpm": ("--pull-rpm", float), "fans": ("--fans", int), "stack_efficiency": ("--stack-efficiency", float),
    "covered_slots": ("--covered-slots", str), "fan_model": ("--fan-model", str), "swirl": ("--swirl", float),
    "grille_open_area": ("--grille-open-area", float), "panel": ("--no-panel", "flag"),
    "bracket": ("--no-bracket", "flag"), "iterations": ("--iterations", int),
    "side_port_coupling": ("--side-port-coupling", float),
}
# objective -> (summary path, sense); sense +1: higher is better
OBJECTIVES = {
    "flow": (("flow", "window", "fin_q_lps"), +1),
    "peak": (("thermal", "peak_rise_K"), -1),
    "cov": (("fan_inlet", "uz_cov"), -1),
    "reverse": (("fan_inlet", "reverse_area_fraction"), -1),
}
DEFAULT_OBJECTIVES = ("flow", "peak", "cov", "reverse")
# Design-to-design spread of the screen - fine offset on the V28 validation set (fin flow L/s, peak rise K)
TIE_BAND = {"flow": 0.16, "peak": 0.5}


@dataclass(frozen=True)
class Variant:
    name: str
    settings: dict = field(default_factory=dict)        # FIELDS keys
    params: dict = field(default_factory=dict)          # GeometryParams overrides

    def argv(self, run_name: str, fidelity: str) -> list[str]:
        """`duct simulate` arguments for this variant."""
        out = ["simulate", run_name, "--fidelity", fidelity, "--no-page"]
        for k, v in self.settings.items():
            flag, kind = FIELDS[k]
            if kind == "flag":
                if not _bool(v):
                    out.append(flag)
            else:
                out += [flag, str(kind(v))]
        for k, v in self.params.items():
            out += ["--param", f"{k}={v}"]
        return out


def _bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off")
    return bool(v)


def _scalar(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def _split(d: dict) -> tuple[dict, dict]:
    """(settings, params) from a flat or nested variant dict; `param.K` keys and a `params` dict both feed params."""
    settings, params = {}, dict(d.get("params") or {})
    for k, v in d.items():
        if k in ("name", "params"):
            continue
        if k.startswith("param."):
            params[k[6:]] = v
        elif k in FIELDS:
            settings[k] = v
        else:
            raise ValueError(f"unknown variant setting {k!r}; use one of {', '.join(FIELDS)} or param.NAME")
    return settings, params


def _auto_name(d: dict) -> str:
    """'v3-2500' from {'collector': 'v3', 'pull_rpm': 2500}: the values, in order."""
    return "-".join(f"{v:g}" if isinstance(v, float) else str(v) for v in d.values()) or "base"


def parse_spec(spec) -> list[Variant]:
    """Variants from a spec (list or dict, see the module doc). Names must be unique; unnamed variants get one built
    from their matrix values (or settings)."""
    if isinstance(spec, list):
        spec = {"variants": spec}
    unknown = set(spec) - {"defaults", "variants", "matrix"}
    if unknown:
        raise ValueError(f"unknown spec keys {sorted(unknown)}")
    defaults = dict(spec.get("defaults") or {})
    matrix = {k: (v if isinstance(v, list) else [v]) for k, v in (spec.get("matrix") or {}).items()}
    bases = spec.get("variants") or [{}]
    out = []
    for base in bases:
        combos = [dict(zip(matrix, vals)) for vals in itertools.product(*matrix.values())] if matrix else [{}]
        for combo in combos:
            d = {**defaults, **base, **combo}
            d["params"] = {**(defaults.get("params") or {}), **(base.get("params") or {})}
            settings, params = _split(d)
            name = base.get("name")
            if combo:
                name = "-".join(filter(None, [name, _auto_name(combo)]))
            elif not name:
                name = _auto_name({k: v for k, v in base.items() if k != "params"})
            out.append(Variant(_safe(name), settings, params))
    names = [v.name for v in out]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError(f"duplicate variant names {sorted(dup)}; name them explicitly")
    if not out:
        raise ValueError("empty sweep")
    return out


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_.=" else "_" for c in str(name))


def parse_kv(text: str) -> dict:
    """'a=1,b=x,param.c=2' -> {'a': 1, 'b': 'x', 'param.c': 2}. A value may not contain commas; quote nothing."""
    out = {}
    for item in filter(None, (s.strip() for s in text.split(","))):
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = _scalar(v.strip())
    return out


def spec_from_cli(spec_path: Path | None, variants: list[str], matrix: list[str], defaults: dict) -> dict:
    """A spec dict from --spec FILE, --variant K=V,... and --matrix K=V1,V2 (CLI pieces override the file's)."""
    spec = json.loads(Path(spec_path).read_text()) if spec_path else {}
    if isinstance(spec, list):
        spec = {"variants": spec}
    spec = dict(spec)
    spec["defaults"] = {**defaults, **(spec.get("defaults") or {})}
    if variants:
        spec["variants"] = list(spec.get("variants") or []) + [parse_kv(v) for v in variants]
    for m in matrix:
        if "=" not in m:
            raise ValueError(f"--matrix expects KEY=V1,V2,..., got {m!r}")
        k, vals = m.split("=", 1)
        spec.setdefault("matrix", {})
        spec["matrix"] = {**spec["matrix"], k.strip(): [_scalar(v.strip()) for v in vals.split(",") if v.strip()]}
    return spec


# --- results and ranking -----------------------------------------------------------------------------------------

def _get(d: dict, path) -> float | None:
    for k in path:
        if not isinstance(d, dict) or d.get(k) is None:
            return None
        d = d[k]
    return float(d)


def metrics(summary: dict | None) -> dict:
    """Objective values from a summary.json (None where absent: a failed run, no exhaust fan), plus run health."""
    if not summary:
        return {k: None for k in OBJECTIVES} | {"ok": False}
    m = {k: _get(summary, path) for k, (path, _) in OBJECTIVES.items()}
    if m["flow"] is None:   # summaries written before the window mean
        m["flow"] = _get(summary, ("flow", "q_lps"))
    flow = summary.get("flow", {})
    m |= {"q_lps": _get(summary, ("flow", "window", "q_lps")) or _get(summary, ("flow", "q_lps")),
          "stage": flow.get("stage"), "iteration": flow.get("iteration"),
          "thermal_accepted": (summary.get("thermal_acceptance") or {}).get("accepted"),
          "wall_s": (summary.get("timing") or {}).get("total_s"), "ok": True}
    return m


def rank(rows: list[dict], objectives=DEFAULT_OBJECTIVES) -> list[dict]:
    """Sort rows (each with `metrics`) by mean per-objective rank, best first; ties by the first objective. An
    objective nobody has (no exhaust fan) is skipped; a run missing one it lacks ranks last there."""
    objectives = [o for o in objectives if any(r["metrics"].get(o) is not None for r in rows)]
    for o in objectives:
        sense = OBJECTIVES[o][1]
        have = sorted((r for r in rows if r["metrics"].get(o) is not None), key=lambda r: -sense*r["metrics"][o])
        for i, r in enumerate(have):
            r.setdefault("ranks", {})[o] = i+1
        for r in rows:
            r.setdefault("ranks", {}).setdefault(o, len(rows))
    for r in rows:
        r["score"] = (sum(r["ranks"][o] for o in objectives)/len(objectives) if objectives and r["metrics"]["ok"]
                      else float("inf"))
    first = objectives[0] if objectives else None
    key = lambda r: (r["score"], -(OBJECTIVES[first][1]*(r["metrics"].get(first) or 0)) if first else 0)  # noqa: E731
    return sorted(rows, key=key)


# --- running -----------------------------------------------------------------------------------------------------

def _launch(v: Variant, sweep: str, fidelity: str, log_dir: Path) -> tuple[subprocess.Popen, Path, float]:
    """Start `duct simulate` for a variant. --force: anything already in its case directory is a leftover of an
    interrupted sweep (finished cases are reused, not relaunched)."""
    run_name = f"{sweep}/{fidelity}/{v.name}"
    argv = v.argv(run_name, fidelity) + ["--force"]
    log = log_dir / f"{fidelity}-{v.name}.log"
    fh = open(log, "w")
    fh.write("duct " + " ".join(argv) + "\n")
    fh.flush()
    proc = subprocess.Popen([sys.executable, "-m", "duct.cli", *argv], stdout=fh, stderr=subprocess.STDOUT,
                            env=os.environ.copy())
    fh.close()
    return proc, Path("runs") / run_name, time.time()


def run_phase(variants: list[Variant], sweep: str, fidelity: str, force: bool = False) -> list[dict]:
    """Run every variant at `fidelity` concurrently (the core pool queues them); returns rows with metrics. A variant
    whose case already has a summary.json is reused unless `force` (so an interrupted sweep resumes)."""
    log_dir = Path("runs") / sweep / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for v in variants:
        case = Path("runs") / sweep / fidelity / v.name
        if not force and (case / "summary.json").exists():
            jobs.append((v, None, case, time.time()))
        else:
            jobs.append((v, *_launch(v, sweep, fidelity, log_dir)))
    try:
        return _collect(jobs, fidelity)
    except BaseException:   # Ctrl-C or a kill: stop every child (each stops its own solver) before leaving
        for _, proc, _, _ in jobs:
            if proc and proc.poll() is None:
                proc.terminate()
        for _, proc, _, _ in jobs:
            if proc:
                proc.wait()
        raise


def _collect(jobs: list, fidelity: str) -> list[dict]:
    rows = []
    for v, proc, case, t0 in jobs:
        code = proc.wait() if proc else None
        s = case / "summary.json"
        summary = json.loads(s.read_text()) if s.exists() and code in (None, 0, 1) else None
        rows.append(dict(name=v.name, settings=v.settings, params=v.params, case=str(case), exit_code=code,
                         reused=proc is None, elapsed_s=round(time.time()-t0, 1), metrics=metrics(summary)))
        print(f"{fidelity} {v.name}: {'reused' if proc is None else f'exit {code}'}, " + _brief(rows[-1]["metrics"]),
              file=sys.stderr, flush=True)
    return rows


def _brief(m: dict) -> str:
    f = lambda k, fmt: "-" if m.get(k) is None else format(m[k], fmt)  # noqa: E731
    return f"fin flow {f('flow', '.3f')} L/s, peak {f('peak', '.2f')} K, CoV {f('cov', '.3f')}, rev {f('reverse', '.3f')}"


def sweep(name: str, variants: list[Variant], top: int = 2, objectives=DEFAULT_OBJECTIVES, force: bool = False,
          screen: str = "screen", fine: str = "fine") -> dict:
    """Screen every variant, rank, re-run the top `top` at `fine`; writes runs/NAME/sweep.json and sweep.md."""
    root = Path("runs") / name
    root.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    screened = rank(run_phase(variants, name, screen, force), objectives)
    by_name = {v.name: v for v in variants}
    best = [r["name"] for r in screened if r["metrics"]["ok"]][:max(0, top)]
    confirmed = rank(run_phase([by_name[n] for n in best], name, fine, force), objectives) if best else []
    result = dict(name=name, objectives=list(objectives), screen_fidelity=screen, fine_fidelity=fine, top=top,
                  wall_s=round(time.time()-t0, 1), screened=screened, confirmed=confirmed)
    (root / "sweep.json").write_text(json.dumps(result, indent=2, default=_json))
    (root / "sweep.md").write_text(markdown(result))
    return result


def _json(x):
    return None if isinstance(x, float) and x != x else str(x)


def markdown(result: dict) -> str:
    def fmt(v, f):
        return "–" if v is None else format(v, f)

    head = ("| # | variant | fin flow L/s | peak rise K | inlet CoV | reverse area | stage | thermal | run s |\n"
            "|---|---|---|---|---|---|---|---|---|\n")

    def table(rows):
        out = head
        for i, r in enumerate(rows, 1):
            m = r["metrics"]
            out += (f"| {i} | {r['name']} | {fmt(m.get('flow'), '.3f')} | {fmt(m.get('peak'), '.2f')} | "
                    f"{fmt(m.get('cov'), '.3f')} | {fmt(m.get('reverse'), '.3f')} | {m.get('stage') or 'failed'} | "
                    f"{'ok' if m.get('thermal_accepted') else '–' if m.get('thermal_accepted') is None else 'no'} | "
                    f"{fmt(m.get('wall_s'), '.0f')} |\n")
        return out

    md = (f"# Sweep {result['name']}\n\nRanked by mean rank over {', '.join(result['objectives'])} (fin flow up; peak "
          f"rise, exhaust-inlet CoV and reverse-flow area down). Total wall time {result['wall_s']:.0f} s.\n\n"
          f"Screen differences under {TIE_BAND['flow']} L/s fin flow or {TIE_BAND['peak']} K peak rise are ties: the "
          f"screen - fine offset varies that much between designs (duct.cfd.sweep).\n\n"
          f"## Screen ({result['screen_fidelity']})\n\n" + table(result["screened"]))
    if result["confirmed"]:
        screen = {r["name"]: r["metrics"] for r in result["screened"]}
        md += f"\n## Top {len(result['confirmed'])} at {result['fine_fidelity']}\n\n" + table(result["confirmed"])
        md += "\n| variant | Δ fin flow L/s (fine − screen) | Δ peak K (fine − screen) |\n|---|---|---|\n"
        for r in result["confirmed"]:
            s, f = screen[r["name"]], r["metrics"]
            d = lambda k: None if s.get(k) is None or f.get(k) is None else f[k]-s[k]  # noqa: E731
            md += f"| {r['name']} | {fmt(d('flow'), '+.3f')} | {fmt(d('peak'), '+.2f')} |\n"
    return md
