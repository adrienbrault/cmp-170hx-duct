"""`duct sweep` specs, ranking and report (duct.cfd.sweep): no OpenFOAM."""
import json

import pytest

from duct.cfd import sweep


def test_spec_list_and_settings():
    vs = sweep.parse_spec([{"name": "v3", "collector": "v3", "pull_rpm": 2500, "params": {"chamber_length": 60}},
                           {"collector": "bare", "pull_rpm": 2177, "panel": False}])
    assert [v.name for v in vs] == ["v3", "bare-2177-False"]
    assert vs[0].settings == {"collector": "v3", "pull_rpm": 2500} and vs[0].params == {"chamber_length": 60}
    argv = vs[1].argv("s/screen/x", "screen")
    assert argv[:5] == ["simulate", "s/screen/x", "--fidelity", "screen", "--no-page"]
    assert "--no-panel" in argv and argv[argv.index("--pull-rpm")+1] == "2177.0"
    assert vs[0].argv("n", "fine")[-2:] == ["--param", "chamber_length=60"]


def test_spec_defaults_and_matrix():
    vs = sweep.parse_spec({"defaults": {"preset": "v28", "pull_rpm": 2500, "params": {"a": 1}},
                           "matrix": {"collector": ["v2", "v3"], "rpm": [2177, 2500]}})
    assert [v.name for v in vs] == ["v2-2177", "v2-2500", "v3-2177", "v3-2500"]
    assert all(v.settings["preset"] == "v28" and v.params == {"a": 1} for v in vs)
    named = sweep.parse_spec({"variants": [{"name": "wide", "param.chamber_length": 62}],
                              "matrix": {"collector": ["v3"]}})
    assert named[0].name == "wide-v3" and named[0].params == {"chamber_length": 62}


def test_spec_errors():
    with pytest.raises(ValueError, match="unknown variant setting"):
        sweep.parse_spec([{"colector": "v3"}])
    with pytest.raises(ValueError, match="duplicate"):
        sweep.parse_spec([{"name": "a"}, {"name": "a"}])
    with pytest.raises(ValueError, match="unknown spec keys"):
        sweep.parse_spec({"variant": []})


def test_spec_from_cli(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"defaults": {"pull_rpm": 2000}, "variants": [{"name": "a", "collector": "v2"}]}))
    spec = sweep.spec_from_cli(f, ["name=b,collector=v3,param.chamber_length=60.5"], ["rpm=2177,2500"],
                               {"preset": "v28", "pull_rpm": 2500})
    vs = sweep.parse_spec(spec)
    assert [v.name for v in vs] == ["a-2177", "a-2500", "b-2177", "b-2500"]
    assert vs[2].params == {"chamber_length": 60.5} and vs[0].settings["pull_rpm"] == 2000  # the file wins
    with pytest.raises(ValueError, match="KEY=VALUE"):
        sweep.parse_kv("collector")


def _summary(flow, peak, cov=None, rev=None):
    s = {"flow": {"stage": "converged", "iteration": 300, "q_lps": flow, "window": {"fin_q_lps": flow}},
         "thermal": {"peak_rise_K": peak}, "thermal_acceptance": {"accepted": True}}
    if cov is not None:
        s["fan_inlet"] = {"uz_cov": cov, "reverse_area_fraction": rev}
    return s


def test_rank_mean_rank_and_failures():
    rows = [dict(name=n, metrics=sweep.metrics(s)) for n, s in [
        ("bare", _summary(11.0, 82.0, 1.50, .37)), ("v3", _summary(12.5, 77.0, 1.47, .36)),
        ("v2", _summary(12.36, 77.3, 1.01, .23)), ("broken", None)]]
    ranked = sweep.rank(rows, ["flow", "peak"])
    assert [r["name"] for r in ranked] == ["v3", "v2", "bare", "broken"]
    assert ranked[-1]["score"] == float("inf")
    ranked = sweep.rank(rows, ["cov", "reverse"])
    assert ranked[0]["name"] == "v2"


def test_rank_skips_objectives_nobody_has():
    rows = [dict(name=n, metrics=sweep.metrics(_summary(q, p))) for n, q, p in [("a", 9.0, 87.0), ("b", 9.5, 86.0)]]
    ranked = sweep.rank(rows)
    assert [r["name"] for r in ranked] == ["b", "a"] and set(ranked[0]["ranks"]) == {"flow", "peak"}


def test_metrics_fall_back_to_last_flow_sample():
    s = _summary(12.0, 77.0)
    del s["flow"]["window"]
    assert sweep.metrics(s)["flow"] == 12.0


def test_markdown_tables():
    rows = sweep.rank([dict(name="v3", metrics=sweep.metrics(_summary(12.5, 77.0, 1.4, .3)), wall_s=200.0)])
    fine = sweep.rank([dict(name="v3", metrics=sweep.metrics(_summary(12.4, 77.2, 1.4, .3)), wall_s=600.0)])
    md = sweep.markdown(dict(name="t", objectives=["flow", "peak"], screen_fidelity="screen", fine_fidelity="fine",
                             wall_s=800.0, screened=rows, confirmed=fine))
    assert "| 1 | v3 | 12.500 | 77.00 |" in md and "| v3 | -0.100 | +0.20 |" in md
