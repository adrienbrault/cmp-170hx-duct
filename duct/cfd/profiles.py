"""Solver profiles as data: foamDictionary entries applied to system/fvSolution.

porousSimpleFoam has no SIMPLEC branch (its pEqn.H ignores SIMPLE/consistent), so every
profile is plain SIMPLE. `nUCorrectors > 0` switches on pressure-implicit porosity, which the
1e9 transverse Darcy coefficients need; all profiles keep it at 2.
"""
from dataclasses import dataclass, field, replace

GAMG = ("solver GAMG; smoother GaussSeidel; cacheAgglomeration true; agglomerator faceAreaPair; "
        "nCellsInCoarsestLevel 20; mergeLevels 1;")
SMOOTH = "solver smoothSolver; smoother symGaussSeidel;"


@dataclass(frozen=True)
class Profile:
    name: str
    nprocs: int | None  # None: one rank per performance core
    fvSolution: dict[str, str] = field(default_factory=dict)
    upwind_iterations: int = 0  # cold starts run bounded upwind U first, then the case's scheme
    note: str = ""

    def with_(self, **changes) -> "Profile":
        fv = changes.pop("fvSolution", {})
        return replace(self, fvSolution={**self.fvSolution, **fv}, **changes)


def _solution(p_tol: str, p_rel: str, p_relax: str, u_relax: str, non_orth: int) -> dict[str, str]:
    return {
        "solvers": (f'{{p {{{GAMG} tolerance {p_tol}; relTol {p_rel};}} '
                    f'"(U|k|omega)" {{{SMOOTH} tolerance 1e-8; relTol 0.1;}}}}'),
        "SIMPLE/nNonOrthogonalCorrectors": str(non_orth),
        "SIMPLE/nUCorrectors": "2",
        "SIMPLE/consistent": "no",
        "SIMPLE/residualControl": "{}",
        "relaxationFactors": f"{{fields {{p {p_relax};}} equations {{U {u_relax}; k {u_relax}; omega {u_relax};}}}}",
    }


_LEGACY = _solution("1e-10", "0.01", "0.15", "0.4", 2)

PROFILES = {
    # The accepted reference55 settings. Its runs used a Metal BiCGStab backend that was only a
    # solver-name swap over the CPU dictionary saved beside it (system/fvSolution.flow-save):
    # GAMG for p and symGaussSeidel smoothSolver for U/k/omega. Legacy restores that CPU choice,
    # including the old driver's 400 upwind iterations from cold.
    "legacy": Profile("legacy", 1, _LEGACY, upwind_iterations=400, note="serial reference55 settings without Metal"),
    # Validated on a cold reference55 rerun. The legacy relaxation beat p 0.3 / U 0.7: that took
    # ~30 % more iterations with fanPressure and biased Q ~0.07 % high (SIMPLE's converged answer
    # depends on relaxation through Rhie-Chow); p 1 / U 0.9 diverged. A loose p tolerance and one
    # non-orthogonal corrector cost no accuracy, and cold linearUpwind needs no upwind start.
    "screen": Profile("screen", None, _solution("1e-6", "0.01", "0.15", "0.4", 1),
                      note="MPI, p tol 1e-6, one non-orthogonal corrector"),
    "final": Profile("final", None, _LEGACY, note="legacy p tolerance and correctors, MPI"),
}


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown profile {name!r}; choose from {', '.join(PROFILES)}") from None


@dataclass(frozen=True)
class Fidelity:
    """A whole-run accuracy level for `duct simulate` / `duct sweep`: mesh, solver profile, flow gates and thermal pass.
    (`Profile` above is only the fvSolution part; the `screen` solver profile is what both fidelities solve with.)"""
    name: str
    base_cell: float                    # mm, CaseOptions.base_cell
    bracket_refine: int                 # snappy level around the bracket windows (BracketWindow.refine)
    wall_layers: int                    # snappy wall layers (CaseOptions.wall_layers)
    cells_between_levels: int           # snappy nCellsBetweenLevels (CaseOptions.cells_between_levels)
    solver: str                         # PROFILES key
    gate_window: int = 200              # iterations, duct.cfd.gates.flow window
    gate_limit: float = 5e-3            # inlet_q_range limit over the window
    gate_split_limit: float = 5e-3      # split_drift limit over the window
    iterations: int = 3000              # flow budget when the gates do not pass
    thermal_couplings: dict = field(default_factory=dict)   # chtFinBase thermalProperties overrides
    note: str = ""


# Screening gates: a 100-iteration window at 1 % inlet range, 2 % split drift (V28 v2's split sloshes +-0.7 % with
# its total flow steady), a 1000-iteration budget, and at most 150 thermal coupling iterations (on the coarse meshes
# chtFinBase's own objective can stall to its 1000-iteration cap with the base settled to 1e-9 K; the acceptance
# gates do not use that objective). Base 5 mm is the coarsest grid planes() accepts (4.5 and 6-6.5 find no offset
# clearing the bracket/panel/fin planes, 7+ leave no room for the measurement planes).
_SCREEN_GATES = dict(gate_window=100, gate_limit=1e-2, gate_split_limit=2e-2, iterations=1000,
                     thermal_couplings={"maxCouplingIterations": 150})

FIDELITIES = {
    # What every V28 reference run used (runs/v28-pp-*): base 4 mm, bracket box level 2, 3 wall layers, default gates.
    "fine": Fidelity("fine", 4.0, 2, 3, 3, "screen", note="the reference mesh and gates"),
    # Validated against the fine V28 push-pull runs at 2500/2500 rpm (legacy side-port thermal coupling), screen -
    # fine: fin flow +0.13 / +0.29 / +0.19 L/s and peak rise -0.49 / -0.78 / -0.97 K for collector v2 / v3 / bare;
    # the order v3 > v2 > bare (flow) and v3 < v2 < bare (peak) holds. ~315k cells vs 527k. (v3L is left out: its fine
    # run diverged transiently, Q 66 L/s at iteration 400, and settled at a 0.52 split; screen puts it level with v3.)
    "screen": Fidelity("screen", 5.0, 2, 3, 3, "screen", **_SCREEN_GATES,
                       note="base 5 mm, otherwise the fine mesh; 100-iteration gates at 1 % (split 2 %)"),
    # Coarser still: no wall layers and 1-cell level buffers, ~205k cells. Same order on the same designs, but a larger
    # and less even offset: fin flow +0.28 / +0.50 / +0.42 L/s, peak -0.37 / -0.98 / -1.58 K (v2 / v3 / bare).
    "draft": Fidelity("draft", 5.0, 2, 0, 1, "screen", **_SCREEN_GATES,
                      note="base 5 mm, no wall layers, 1-cell level buffers; screen's gates"),
}


def fidelity(name: str) -> Fidelity:
    try:
        return FIDELITIES[name]
    except KeyError:
        raise ValueError(f"unknown fidelity {name!r}; choose from {', '.join(FIDELITIES)}") from None
