# Restructure plan

Status: started 2026-10-16; kept as the record of the restructure's decisions.

## Goals

1. One obvious pipeline behind a `duct` CLI: CAD → verify/slice → CFD case → mesh → flow → thermal → report → video.
2. CFD runs that are much faster and judged by gates sized to the design decisions being made.
3. Streamline videos from any run.
4. Fan configurations: a single fan, N fans stacked in series, and push-pull with a printable exhaust collector on the rear slot brackets.
5. Shape policy: the duct and collector stay clean, flush and rounded, with few sharp corners. Shape is not traded away for modeled gains.

## Decisions

| Topic | Decision |
|---|---|
| Harness | Python package `duct/` with a `duct` console script (`uv run duct …`) |
| `work/` lab notebook | Removed from the repository once ported |
| Old revisions | V23 was the first preset; the earlier generators are not part of this repository |
| License | MIT for everything except `solvers/` (GPL-3.0, builds against OpenFOAM) |
| OpenFOAM | `brew install --cask gerlero/openfoam/openfoam@2606` → `/Applications/OpenFOAM-v2606.app` |
| Metal GPU backend | Archived (history only); it can't use MPI, and MPI-8 GAMG is about 3× faster |
| Fan BC | Native `fanPressure` replaces the outer fan-match loop, once validated against reference55 |
| Solver | Keep OpenFOAM: porous fin zones and the custom fin/air/base thermal model fit it, it's free and scriptable, and the slowness came from how it was run |
| Tool roles | `duct estimate` (lumped network, `duct/network.py`) is the primary tool for fan decisions: RPM, stacking, push-pull. CFD calibrates it and answers shape questions: collector loss, flow split, local separation. Physical measurements of the printed duct calibrate the heatsink model |

## Target tree

```
pyproject.toml, duct.toml (default params)
duct/
  params.py env.py cli.py
  cad/geometry.py   build_duct(params) -> DuctSolids (pure)
  cad/exhaust.py    build_collector(params) -> CollectorSolids
  cad/export.py     STL, fit gauges, checks.json, preview HTML
  print/verify.py print/slice.py
  cfd/domain.py cfd/case.py cfd/fan.py cfd/porous.py cfd/mesh.py cfd/run.py cfd/gates.py cfd/profiles.py
  thermal/run.py
  report/metrics.py report/html.py
  viz/streamlines.py viz/scene.py
  study/spec.py study/run.py
solvers/chtFinBase/       one canonical thermal solver (GPL-3.0)
templates/case/           OpenFOAM case template
profiles/slicer/          Bambu P1S / 0.28 mm PETG profiles
releases/v23/             released STL, fit gauges, notes, checks, preview
tests/
runs/                     gitignored run outputs
docs/METHOD.md docs/HARDWARE.md
```

## Stages

Each stage ends in a commit with a passing gate.

| # | Stage | Gate |
|---|---|---|
| 0 | `pyproject`, `env.py`, `duct doctor`, permanent OpenFOAM; validation fixtures tarball (reference55 mesh+fields, upper-r6 `flow.stl`) | `duct doctor` green |
| 1 | `cad/geometry.py` + V23 preset + export | STL identical to the released V23, or volume/bounds/collar-section Hausdorff < 0.01 mm |
| 2 | `print/verify.py`, `slice.py`, preview; `releases/v23/` | verify passes; slicer results match `v23-slicer-checks.json` |
| 3 | `cfd/domain.py`, `porous.py`, `case.py`, `mesh.py`, templates, `cardExit0/1` faceZones | fluid surface matches upper-r6 `flow.stl` (patch areas within 1e-4, Hausdorff < 0.01 mm); cell count within 2 % |
| 4 | legacy run profile (serial, totalPressure) + canonical `chtFinBase` + report | warm restart of reference55: Q within 0.1 %, peak within 0.05 K |
| 5 | `screen` profile: MPI-8 + GAMG, `fanPressure`, windowed gates, function-object metrics | cold rerun of reference55: Q within 1 %, peak base rise within 0.5 K; ≥ 4× faster |
| 6 | `viz/` streamline video and stills | mp4 from a validated run |
| 7 | `cad/exhaust.py` (needs hardware measurements), `fan.py` series + push-pull | collector watertight; N=2 and push-pull runs within 3 % of the analytic operating point |
| 8 | `study/`, `git rm -r work/`, README / METHOD / HARDWARE | clean clone + `uv sync` + tests pass |

## Reference numbers

- The accepted reference (`work/duct-v18/reference55`, V8-derived 55 mm, 2500 rpm, 250 W/card): Q = 12.371 L/s, peak base rise 77.837 K.
- The system curve, fitted from accepted runs at 2000/2500/3000 rpm: ΔP = 1117.7·Q + 94207·Q² (Pa, m³/s).

## Gates

The old strict gates (velocity change < 0.1 % over 200 its, residuals < 1e-4) rejected runs whose answers were stable to 1e-4 K. That is three orders of magnitude finer than the design differences being compared. The new default gates are measured over the last 200 iterations:

- inlet Q range < 0.5 %;
- exit-split drift < 0.5 %;
- mass imbalance < 1e-4;
- energy balance < 1e-3;
- |ΔTpeak| < 0.05 K between thermal calls, when two calls are run.

`--strict` keeps the old set.
