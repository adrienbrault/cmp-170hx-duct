"""Simulate fidelities (duct.cfd.profiles) and the re-run guard: no OpenFOAM."""
from argparse import Namespace
from dataclasses import replace

import pytest

from duct import cli
from duct.cfd import gates, profiles
from duct.cfd.bracket import BRACKET
from duct.cfd.case import CaseOptions, planes
from duct.params import PRESETS


def test_fine_fidelity_is_the_reference_mesh_and_gates():
    f = profiles.fidelity("fine")
    o = CaseOptions()
    assert (f.base_cell, f.bracket_refine, f.wall_layers, f.cells_between_levels) == (
        o.base_cell, BRACKET.refine, o.wall_layers, o.cells_between_levels)
    assert (f.gate_window, f.gate_limit, f.solver, f.thermal_couplings) == (gates.WINDOW, 5e-3, "screen", {})


def test_screen_fidelity_is_coarser_and_fits_the_planes():
    f = profiles.fidelity("fine")
    for s in (profiles.fidelity("screen"), profiles.fidelity("draft")):
        assert s.base_cell >= f.base_cell and s.wall_layers <= f.wall_layers and s.gate_window <= f.gate_window
        assert s.iterations < f.iterations and s.thermal_couplings["maxCouplingIterations"] < 1000
        for name in ("v28", "v29", "a29"):
            planes(PRESETS[name], CaseOptions(base_cell=s.base_cell, bracket=replace(BRACKET, refine=s.bracket_refine)))
    d, s = profiles.fidelity("draft"), profiles.fidelity("screen")
    assert d.wall_layers < s.wall_layers and d.cells_between_levels <= s.cells_between_levels


def test_unknown_fidelity():
    with pytest.raises(ValueError, match="choose from"):
        profiles.fidelity("ultra")


def _sim_args(**kw):
    a = dict(base_cell=None, rpm=2500.0, fans=1, stack_efficiency=0.7, fan_model="disk", swirl=0.0,
             grille_open_area=None, bracket=True, panel=True, covered_slots=None, pull_rpm=None, collector="auto")
    return Namespace(**(a | kw))


def test_case_options_follow_the_fidelity():
    g, s = PRESETS["v28"], profiles.fidelity("screen")
    o = cli._case_options(_sim_args(), g, s)
    assert (o.base_cell, o.bracket.refine, o.wall_layers, o.cells_between_levels) == (
        s.base_cell, s.bracket_refine, s.wall_layers, s.cells_between_levels)
    assert o.bracket.panel == BRACKET.panel
    assert cli._case_options(_sim_args(base_cell=4.0), g, s).base_cell == 4.0  # explicit --base-cell wins
    assert cli._case_options(_sim_args(bracket=False), g, s).bracket is None
    assert cli._case_options(_sim_args(), g) == CaseOptions(fan_model="disk")  # no fidelity: the old defaults


def test_simulate_refuses_an_existing_case(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs/old/321").mkdir(parents=True)
    assert cli.main(["simulate", "old", "--preset", "v28"]) == 2
    assert "--force" in capsys.readouterr().err
    assert (tmp_path / "runs/old/321").exists()


def test_fresh_case_force_clears(tmp_path):
    case = tmp_path / "c"
    (case / "0").mkdir(parents=True)
    assert cli._fresh_case(case, False)
    assert cli._fresh_case(case, True) is None and not case.exists()
    case.mkdir()
    assert cli._fresh_case(case, False) is None      # an empty directory is fine
