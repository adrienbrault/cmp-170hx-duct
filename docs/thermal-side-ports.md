# Fin heat exchange in all card paths

## Previous coupling

`duct/cfd/porous.py` makes three Darcy–Forchheimer zones per card. Its
`channel()` closure already calculates a separate Shah–London heat-transfer
coefficient and fin efficiency for every port, but `thermal_hvol()` returned
only the main port's coefficient. `duct/cfd/case.py` wrote that scalar `Hvol`.
`solvers/chtFinBase/chtFinBase.C` assigned it only to `card*path0` cells.

Each card receives 250 W on one 94.8 x 230 mm, 2 mm thick copper-base grid:
80% normalized Gaussian (sigma 21 x 30 mm, centre at 48% of the active length)
and 20% uniform. The grid spreads heat in y/z with adiabatic outer edges.
Bilinear interpolation supplies the local base temperature to the 3D air;
its transpose returns the air-temperature term to the base. The air source
is `Hvol/(rhoCp) * (Tb - T)`; the base loses the identical exchange in watts.
Only path0 participated. Side ports had molecular air diffusion and hydraulic
resistance, but no direct fin/base exchange. They could still warm through air
diffusion outside the banks. All power had to leave through the main bank.

The C++ solver itself writes `thermal-results.json`, `base-coupling.json` and
`temperature-convergence.json`. `duct/thermal/run.py` reads
`thermal-results.json` and `temperature-convergence.json`, computes boundary
energy error, and passes the result
to the acceptance gates; `duct simulate` embeds the thermal result in
`summary.json`.

## Hardware evidence and nominal assumption

`GeometryParams.fin_ports` defines a 23.2 x 94.8 mm main vent and two
9.6 x 31.5/33 mm side vents. `porous.py` and
[the original method](../outputs/170hx-duct/cooling-integrated-method.txt)
model these as 27, 7 and 7 straight fin channels, respectively, all 230 mm long.
These are photo estimates, not a measured fin drawing. The method explicitly
says that secondary board-to-air transfer was unresolved.

The [first-hand teardown](https://niconiconi.neocities.org/tech-notes/nvidia-cmp-170hx-review/#appendix-1-teardown)
shows a copper fin stack attached to the component side and a separable rear
chassis/backplane. It supports a common spreader for that copper stack, but
does **not** establish that the two small modeled vents see that same stack
rather than a separate rear/board passage. The x separation of the port boxes
alone does not establish a thermal bond. No measured side-bank-to-GPU
conductance is available. This change therefore cannot claim to identify the
real card's side-port thermal connection.

The nominal model now treats all three *assumed fin banks* as connected to the
same spreader, at their physical y/z positions (x is collapsed in this reduced
model). Full coupling (1) is the consistent default **conditional on that
existing fin-bank assumption**: each side bank gets only its own smaller
fin-efficiency-weighted surface area, not another main bank's area. It is not
a calibrated hardware value. If inspection shows separate rear passages,
use 0 for those ports; partial connection is an explicit sensitivity input.
There is no arbitrary additional power source in the side banks, and no
resolved transverse thermal resistance or second backplate temperature.

## Configuration and conservation

`FinModel.port_coupling=(1, 1, 1)` is the fraction of each bank's effective
connected exchange area (including exposed base area). Values must be finite
and between 0 and 1. Python callers can set ports independently with
`dataclasses.replace(FINS, port_coupling=(1, lower, upper))`.

`duct simulate ... --side-port-coupling 0` or
`duct cfd build ... --side-port-coupling 0` reproduces the previous thermal
closure; the flag defaults to 1 and applies to both side ports. Existing flags
retain their meaning. Flow coefficients and geometry are unchanged.

New cases write `pathHvol (main lower upper)` in `thermalProperties`; JSON
metadata retains the numerical list and the fractions under `options.fins`.
The scalar `Hvol` remains for compatibility. When `pathHvol` is absent the
solver uses `(Hvol 0 0)`, so old case dictionaries retain their old behavior.
For a port with N channels of gap b, height H, width w and length L:

```
A_effective = (2*N*H*eta + N*b)*L
Hvol_path = fraction * heat_scale * h * A_effective / (w*H*L)
```

Every coupled cell uses its own `Hvol_path*cellVolume` in **all** base matrix,
air source, exported coefficient, heat-balance and convergence calculations.
The same bilinear weights are used on both sides. Molecular air diffusivity
continues inside every porous passage, including disabled side banks.

`thermal-results.json` now adds `cards[].paths[]` with path index, effective
Hvol, integrated conductance, exchanged heat, zone volume and volume-averaged
axial flow. The last quantity is a zone diagnostic, not an exit face integral.
The existing `main_Q_m3s`, `flow_by_y_m3s` and `row_volumes_m3` retain their
main-path meaning. Total input remains 500 W. The existing exchange/boundary
energy and temperature-convergence thresholds are unchanged.

`duct estimate` uses empirical temperature fits in `duct/network.py` calibrated
on the previous closure. Those fits have not been recalibrated by this change;
they remain estimates of the old thermal model. A single new CFD point is not
enough to replace their flow-dependent calibration.

## Verification

Run `uv run pytest tests/test_thermal.py tests/test_domain.py tests/test_gates.py`.
The thermal tests construct six straight passages and execute the actual C++
solver when OpenFOAM is installed. They check independently scaled side banks,
zero side coupling, per-card power, global boundary energy, interpolation
identities and the exported spatial base equation. This catches inconsistent
use of main-path Hvol on either side of the exchange.

Rebuild using the repository's native builder:

```
uv run python -c 'from duct.thermal.build import build; print(build(force=True))'
uv run duct simulate v28-1fan-panel-heat --preset v29 --np 3
```

The builder copies the canonical sources into `runs/.build/chtFinBase`, invokes
OpenFOAM v2606 `wmake`, and installs `runs/.bin/chtFinBase`. Flow uses three MPI
ranks; thermal exchange runs serially on the reconstructed mesh.

## Full-case validation (2026-10-17)

`uv run duct simulate v28-1fan-panel-heat --preset v29 --np 3` completed:
mesh OK, flow converged at iteration 256, thermal objective converged at
iteration 66, CLI exit 0. The generated fluid STL has exactly the same SHA-256
as `runs/v28-1fan-panel/case.json`.
The baseline used six flow ranks; this run used the requested three.

| Metric | Supplied baseline | All paths, fractions (1, 1, 1) |
| --- | ---: | ---: |
| Peak base rise, K | 87.193296 | 74.796685 |
| Inlet flow, L/s | 9.129638 | 9.128392 |
| Boundary energy, W (500 W input) | 499.999403 | 499.998154 |
| Relative boundary energy error | 1.19e-6 | 3.69e-6 |
| Relative exchange energy error | 1.18e-7 | 1.19e-7 |

The peak drops 12.396611 K under the nominal connected-bank assumption.
Integrated fin-to-air exchange is 499.999940 W. Per-path exchange is:

| Card | Main path0, W | Lower side path1, W | Upper side path2, W | Total, W |
| --- | ---: | ---: | ---: | ---: |
| 0 | 207.692 | 19.937 | 22.371 | 250.000 |
| 1 | 207.776 | 19.988 | 22.236 | 250.000 |

Both side banks together carry 16.9065% of the 500 W input. A separate
thermal solve on the identical flow, with `pathHvol (15394.4 0 0)`, converged
to 87.164915 K peak rise: 0.028381 K below the supplied baseline, and
12.368230 K above the all-path result. Its boundary energy was 499.999474 W
and exchange error 1.22e-7. It used a copy of the nominal air temperature as
an initial guess, with independent temperature writes and shared read-only
flow/mesh inputs. All source power leaves through path0 when the side
fractions are zero. The same-flow control and machine-readable metrics are recorded in
[`work/thermal-side-ports/validation.json`](../work/thermal-side-ports/validation.json).

The 12 thermal tests passed, including three actual OpenFOAM cases. Domain
and gate tests: 31 passed, two fixture-dependent skips. The final generated
case-dictionary assertions were also rerun and passed. Default flow/thermal
acceptance and the solver's thermal objective passed. The strict continuation
checks for velocity change and peak stability were not measured by this
single-run command; their reported failures remain visible in `summary.json`.
