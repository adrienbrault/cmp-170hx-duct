"""`duct` command-line entry point."""
import argparse
import sys
from pathlib import Path

from . import env
from .cfd.profiles import FIDELITIES
from .params import PRESETS


def cmd_doctor(_args) -> int:
    checks = env.doctor()
    for c in checks:
        print(f"{'ok ' if c.ok else 'MISSING'}  {c.name:14s} {c.detail}")
    return 0 if all(c.ok for c in checks if c.name == "openfoam") else 1


def cmd_cad(args) -> int:
    from .cache import build_duct, export_duct   # duct.cache: an unchanged design is not rebuilt
    from .params import PRESETS, parse_overrides
    export_duct(build_duct(parse_overrides(args.param or [], PRESETS[args.preset])), args.out)
    print((args.out / "generation.log").read_text(), end="")
    return 0


def cmd_verify(args) -> int:
    import json
    from .env import BAMBU
    from .params import COLLECTOR_V1, COLLECTOR_V2, PRESETS, parse_overrides
    from .print import printability
    from .print.verify import verify
    if args.fast:
        return _verify_fast(args)
    if args.draft:
        print("verify: --draft is a --fast preview option (draft geometry is not checked for release)", file=sys.stderr)
        return 2
    if args.stl is None:
        print("verify: an STL is required (or --fast to preview the gates of a preset/--param design)", file=sys.stderr)
        return 2
    try:
        if args.part == "collector":
            from .cache import build_collector
            from .print.verify import verify_collector
            c = {"v1": COLLECTOR_V1, "v2": COLLECTOR_V2}[args.collector]
            checks = verify_collector(args.stl, build_collector(c))
            spec = printability.collector_spec(c)
        else:
            from .cache import build_duct
            g = parse_overrides(args.param or [], PRESETS[args.preset])
            checks = verify(args.stl, g, build_duct(g))
            spec = printability.duct_spec(g)
        print(json.dumps(checks, indent=2))
    except AssertionError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    slicer = None
    if args.no_slice:
        print("printability: slicer gate skipped (--no-slice)")
    elif not BAMBU.exists():
        print(f"printability: slicer gate skipped (no Bambu Studio at {BAMBU})")
    else:
        slicer = dict(out_dir=Path("runs") / f"verify-slice-{args.stl.stem}")
    gates = printability.run_gates(args.stl, spec, slicer=slicer)
    if args.json:
        args.json.write_text(json.dumps(gates, indent=2))
    print(f"printability: {printability.summary_line(gates)}")
    for line in printability.failure_lines(gates):
        print(f"  {line}")
    return 0 if gates["passed"] else 1


def _verify_fast(args) -> int:
    """duct verify --fast: the printability gates at preview resolution (duct.print.fast). NOT a release check."""
    import json
    from .env import BAMBU
    from .params import COLLECTOR_V1, COLLECTOR_V2, PRESETS, parse_overrides
    from .print import fast, printability
    name = args.stl.stem if args.stl else (f"collector-{args.collector}" if args.part == "collector" else args.preset+"-draft"*args.draft)
    slicer = None if args.no_slice or not BAMBU.exists() else dict(out_dir=Path("runs") / f"verify-fast-slice-{name}")
    if args.part == "collector":
        if args.draft:
            print("verify --fast --draft: draft builds are for the duct only", file=sys.stderr)
            return 2
        gates = fast.preview_collector({"v1": COLLECTOR_V1, "v2": COLLECTOR_V2}[args.collector], args.stl,
                                       version=f"collector-{args.collector}", slicer=slicer)
    else:
        g = parse_overrides(args.param or [], PRESETS[args.preset])
        if args.draft:
            if args.stl is not None:
                print("verify --fast --draft previews a draft build of the preset/--param design, not an STL", file=sys.stderr)
                return 2
            g = fast.draft(g)
        gates = fast.preview_duct(g, args.stl, version="draft" if args.draft else "preview" if args.param else args.preset, slicer=slicer)
    if args.json:
        args.json.write_text(json.dumps(gates, indent=2))
    print(fast.LABEL)
    if gates.get("draft"): print(fast.DRAFT_LABEL)
    for k in ("plug_latch_collisions_mm3", "bay_collisions_mm3"):
        if k in gates: print(f"cad: {k} {gates[k]}")
    print(f"printability preview ({gates['preview']['triangles']} triangles, slicer {gates['preview']['slicer']}, "
          f"{gates['preview']['seconds']} s): "
          f"{printability.summary_line(gates)}")
    for line in printability.failure_lines(gates):
        print(f"  {line}")
    return 0 if gates["passed"] else 1


def cmd_slice(args) -> int:
    import json
    from .print.slice import slice_stl
    print(json.dumps(slice_stl(args.stl, args.out or args.stl.parent / "sliced", supports=not args.no_supports), indent=2))
    return 0


def cmd_release(args) -> int:
    from .params import PRESETS
    from .print.release import NOTES, PrintabilityError, release
    try:
        release(PRESETS[args.version], Path("releases") / args.version, NOTES[args.version], slice_=not args.no_slice,
                override=args.override_printability)
    except PrintabilityError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_index(args) -> int:
    from .print.index import write_index
    print(write_index(args.out))
    return 0


def cmd_preview(args) -> int:
    from .viz.web import write_release_pages
    for p in write_release_pages(args.version, runs=tuple(args.runs or ()) or None, fields=not args.no_fields):
        print(p)
    return 0


def cmd_airflow(args) -> int:
    from .viz.web import write_airflow_preview
    print(write_airflow_preview(args.case, args.out, version=args.version, badge=args.badge, label=args.label,
                               collector=args.collector))
    return 0


def cmd_video(args) -> int:
    from .viz.streamlines import render_video
    render_video(args.case, args.stl, args.out, frames=args.frames)
    print(args.out)
    return 0


def _inlet(args):
    from .cfd.run import Inlet
    if args.inlet.startswith("fixed:"):
        return Inlet("fixed", pressure_pa=float(args.inlet[6:]), rpm=args.rpm, count_series=args.fans,
                     series_efficiency=args.stack_efficiency)
    return Inlet(args.inlet, rpm=args.rpm, count_series=args.fans, series_efficiency=args.stack_efficiency,
                 pull_rpm=args.pull_rpm)


def _collector_kind(v: str) -> str:
    """--collector: one of duct.cfd.collector.KINDS, or a plug kind with CollectorParams overrides (plug:plenum_depth=55)."""
    import argparse
    from .cfd.collector import KINDS, is_plug, split_kind
    try:
        ok = v in KINDS or is_plug(v) and split_kind(v) is not None
    except ValueError:
        ok = False
    if not ok:
        raise argparse.ArgumentTypeError(f"{v!r}: one of {', '.join(KINDS)}, or plug[-nohub|-slit|140]:K=V,...")
    return v


def _case_options(args, g, fidelity=None):
    """CaseOptions from the CLI. --pull-rpm adds the exhaust collector: duct.cad.exhaust when present,
    else the development placeholder. `fidelity` (duct.cfd.profiles.Fidelity) sets the mesh; an explicit
    --base-cell still wins."""
    from .cfd.case import CaseOptions
    from dataclasses import replace
    from .cfd.porous import FINS
    base_cell = args.base_cell if args.base_cell is not None else fidelity.base_cell if fidelity else 4.0
    kw = dict(base_cell=base_cell, rpm=args.rpm, shoulder_refine=getattr(args, "shoulder_refine", False),
              fans=args.fans, stack_efficiency=args.stack_efficiency, fan_model=args.fan_model, swirl=args.swirl)
    side_coupling = getattr(args, 'side_port_coupling', 1.0)
    kw['fins'] = replace(FINS, port_coupling=(1.0, side_coupling, side_coupling))
    if fidelity:
        kw |= dict(wall_layers=fidelity.wall_layers, cells_between_levels=fidelity.cells_between_levels)
    if args.grille_open_area is not None:
        kw["grille_open_area"] = args.grille_open_area
    from dataclasses import replace
    from .cfd.domain import DOMAIN
    domain = DOMAIN
    if g.hub_fairing:   # the fan's hub ends in the fairing: the approach annulus starts at its base
        domain = replace(domain, hub_radius=g.hub_fairing_d/2)
    if getattr(args, "domain", None):
        import ast
        domain = replace(domain, **{k.strip(): float(ast.literal_eval(v.strip())) for k, v in (a.split("=", 1) for a in args.domain)})
    if domain != DOMAIN:
        kw["domain"] = domain
    if not args.bracket:
        kw["bracket"] = None
    elif not args.panel:
        from dataclasses import replace
        from .cfd.bracket import BRACKET
        kw["bracket"] = replace(BRACKET, panel=None)
    elif args.covered_slots is not None:
        from dataclasses import replace
        from .cfd.bracket import BRACKET
        covers = tuple(int(v) if v.is_integer() else v   # slot positions: half-integers in the 4-slot layout
                       for v in (float(k) for k in args.covered_slots.split(",") if k.strip()))
        kw["bracket"] = replace(BRACKET, panel=replace(BRACKET.panel.for_pitch(g.pitch), covers=covers))
    if fidelity and kw.get("bracket", CaseOptions.bracket) is not None:
        from dataclasses import replace
        kw["bracket"] = replace(kw.get("bracket", CaseOptions.bracket), refine=fidelity.bracket_refine)
    if args.pull_rpm:
        from .cfd.collector import default
        from .cfd.collector import is_plug, plug_air, plug_fan, plug_panel
        if is_plug(args.collector):   # the plug in the recessed bay: its air layer, the slits, no open slots under it
            from .cfd.bracket import BRACKET
            from .cfd import fan
            kw["collector"], source, ss, sr, _ = plug_air(g, kind=args.collector)
            if (pf := plug_fan(g, args.collector)) != fan.P12_PRO:   # a 120 mm fan stays on the domain's annulus
                kw["exhaust_fan"] = pf
            kw["extra_solids"], kw["extra_rules"] = kw.get("extra_solids", ())+ss, kw.get("extra_rules", ())+sr
            b = kw.get("bracket", CaseOptions.bracket) or BRACKET
            kw["bracket"] = replace(b, panel=plug_panel(g))
        else:
            kw["collector"], source = default(g, kind=args.collector)
        kw["collector_source"] = source
        kw["pull_rpm"] = args.pull_rpm
        print(f"collector: {source}", file=sys.stderr)
    return CaseOptions(**kw)


def cmd_cfd_build(args) -> int:
    import json
    from .cfd.case import build
    from .params import PRESETS, parse_overrides
    g = parse_overrides(args.param or [], PRESETS[args.preset])
    info = build(args.out, g, _case_options(args, g))
    print(json.dumps({k: info[k] for k in ("patch_areas_m2",) if k in info} or {"case": str(args.out)}, indent=2))
    return 0


def cmd_cfd_mesh(args) -> int:
    import json
    from .cfd.mesh import mesh
    print(json.dumps(mesh(args.case), indent=2))
    return 0


def cmd_cfd_run(args) -> int:
    import json
    from .cfd.run import run
    st = run(args.case, args.profile or "screen", args.np, _inlet(args), args.iterations or 3000, args.strict,
             min_iterations=args.min_iterations)
    print(json.dumps(st, indent=2, default=str))
    return 0 if st.get("stage") == "converged" else 1


def cmd_cfd_inlet(args) -> int:
    import json
    from .cfd.inlet import update_summary
    for case in args.case:
        s = update_summary(case)
        print(case, json.dumps(s["fan_inlet"]))
    return 0


def cmd_cfd_entry(args) -> int:
    import json
    from .cfd.entry import update_summary
    for case in args.case:
        d = update_summary(case)
        print(case, json.dumps(dict(reverse=d["reverse"], core_fill_mm={k: v for k, v in d["core_fill"].items() if k.startswith("length")},
                                    periphery_reverse_fraction=d["periphery_reverse_fraction"], loss_pa=d["loss_pa"],
                                    main_port_uz_cov=d["card_entry"]["main_uz_cov"], main_row_cov=d["card_entry"]["main_row_cov"])))
    return 0


def cmd_thermal(args) -> int:
    from .thermal.run import acceptance, run
    result = acceptance([run(args.case, args.reference_time)])
    print(f"peak rise {result['peak_rise_K']:.3f} K, undershoot {result['undershoot_K']:.3f} K")
    print(result["verdict"])
    return 0 if result["accepted"] else 1


def _fresh_case(out: Path, force: bool) -> str | None:
    """None when `out` is free (or --force cleared it); else why simulate refuses: a re-run into an old case
    trips createBaffles on its stale time folders and would resume the old flow."""
    import shutil
    if not out.exists() or not any(out.iterdir()):
        return None
    if not force:
        return (f"{out} already holds a case; pass --force to delete it and start over (or pick another name; "
                f"`duct cfd run {out}` resumes its flow)")
    shutil.rmtree(out)
    return None


def cmd_simulate(args) -> int:
    """CAD -> case -> mesh -> flow -> thermal -> airflow preview, in runs/NAME, at a fidelity (duct.cfd.profiles),
    holding cores from the shared pool (duct.cfd.scheduler): one for the serial phases, one per rank for the flow."""
    import json
    import time
    from . import env
    from .cfd import profiles, scheduler
    from .cfd.case import build
    from .cfd.mesh import mesh
    from .cfd.run import run
    from .params import PRESETS, parse_overrides
    from .thermal.run import acceptance
    from .thermal.run import run as thermal
    import signal
    # SIGTERM (a sweep stopping its children, kill) unwinds like Ctrl-C, so duct.cfd.run stops the MPI solver it
    # started in its own session instead of leaving the ranks running
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    out = Path("runs") / args.name
    if why := _fresh_case(out, args.force):
        print(f"REFUSED: {why}", file=sys.stderr)
        return 2
    fid = profiles.fidelity(args.fidelity)
    solver = profiles.get(args.profile or fid.solver)
    nprocs = args.np or solver.nprocs or env.perf_cores()
    pool = scheduler.Pool(total=args.cores)
    timing, t_all = {}, time.time()

    def lap(key: str, t0: float) -> float:
        timing[key] = round(time.time() - t0, 1)
        return time.time()

    try:
        timing["wait_s"] = round(pool.acquire(1, label=args.name), 1)
        t = time.time()
        g = parse_overrides(args.param or [], PRESETS[args.preset])
        meta = build(out, g, _case_options(args, g, fid))
        t = lap("build_s", t)
        mesh(out)
        t = lap("mesh_s", t)
        timing["wait_s"] += round(pool.resize(nprocs, label=args.name), 1)
        t = time.time()
        st = run(out, solver, nprocs, _inlet(args), args.iterations or fid.iterations, gate_window=fid.gate_window,
                 gate_limit=fid.gate_limit, gate_split_limit=fid.gate_split_limit, min_iterations=args.min_iterations)
        t = lap("flow_s", t)
        pool.resize(1)
        summary = dict(flow=st)
        if "planes_mm" in meta:  # bracket/collector cases: pressure along the flow path and the network collector_k
            from .cfd import breakdown
            summary["pressure_breakdown"] = breakdown.run(out)
            import importlib.util
            if importlib.util.find_spec("pyvista"):   # duct loss, card-entry uniformity and the hub wake (duct.cfd.entry)
                from .cfd.entry import duct_flow
                summary["duct_flow"] = duct_flow(out, summary["pressure_breakdown"]["total_pressure_drops_pa"])
            else:
                print("duct_flow skipped: needs the viz extra (uv sync --extra viz); later: duct cfd entry", file=sys.stderr)
        if args.pull_rpm:   # how evenly the air reaches the exhaust fan (duct.cfd.inlet)
            from .cfd.inlet import fan_inlet_profile
            summary["fan_inlet"] = fan_inlet_profile(out)
        t = lap("post_s", t)
        th = thermal(out, couplings=fid.thermal_couplings or None)
        lap("thermal_s", t)
    finally:
        pool.release()
    timing["total_s"] = round(time.time() - t_all, 1)
    verdict = acceptance([th])
    summary |= dict(thermal=th.__dict__, thermal_acceptance=verdict, timing=timing,
                    fidelity=dict(name=fid.name, solver=solver.name, nprocs=nprocs, base_cell_mm=meta["options"]["base_cell_mm"],
                                  bracket_refine=(meta.get("bracket") or {}).get("refine"),
                                  wall_layers=meta["options"]["wall_layers"],
                                  cells_between_levels=meta["options"]["cells_between_levels"],
                                  gate_window=fid.gate_window, gate_limit=fid.gate_limit,
                                  gate_split_limit=fid.gate_split_limit,
                                  thermal_couplings=fid.thermal_couplings))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    if args.page:
        from .viz.web import write_airflow_preview
        print(write_airflow_preview(out, out / "airflow.html", badge=f"{args.name}: {st.get('stage')} at iteration {st.get('iteration')}"))
    w = st.get("window") or {}
    print(f"flow: {st.get('stage')} at iteration {st.get('iteration')}, Q {st.get('q_lps') or 0:.3f} L/s "
          f"(fins {w.get('fin_q_lps') or 0:.3f} L/s over the last {w.get('iterations', 0)} iterations)")
    print(verdict["verdict"])
    print("timing: " + ", ".join(f"{k.removesuffix('_s')} {v:.0f} s" for k, v in timing.items()))
    return 0 if st.get("stage") == "converged" and verdict["accepted"] else 1


def cmd_sweep(args) -> int:
    """Screen variants at the screen fidelity, rank them, re-run the best at fine (duct.cfd.sweep)."""
    import json
    import os
    from .cfd import sweep
    defaults = {k: v for k, v in dict(preset=args.preset, collector=args.collector, rpm=args.rpm,
                                       pull_rpm=args.pull_rpm).items() if v is not None}
    if args.param:
        defaults["params"] = dict(p.split("=", 1) for p in args.param)
    try:
        variants = sweep.parse_spec(sweep.spec_from_cli(args.spec, args.variant, args.matrix, defaults))
        objectives = [o.strip() for o in args.objectives.split(",") if o.strip()]
        bad = [o for o in objectives if o not in sweep.OBJECTIVES]
        if bad:
            raise ValueError(f"unknown objectives {bad}; choose from {', '.join(sweep.OBJECTIVES)}")
    except ValueError as e:
        print(f"sweep: {e}", file=sys.stderr)
        return 2
    if args.dry_run:
        for v in variants:
            print("duct " + " ".join(v.argv(f"{args.name}/{args.screen_fidelity}/{v.name}", args.screen_fidelity)))
        return 0
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # unwind: duct.cfd.sweep stops its children
    if args.cores is not None:   # the simulate children read the pool size from the environment
        os.environ["DUCT_CORES"] = str(args.cores)
    result = sweep.sweep(args.name, variants, args.top, objectives, args.force, args.screen_fidelity,
                         args.fine_fidelity)
    print((Path("runs") / args.name / "sweep.md").read_text())
    print(json.dumps({"sweep": str(Path("runs") / args.name / "sweep.json"), "wall_s": result["wall_s"]}))
    return 0 if all(r["metrics"]["ok"] for r in result["screened"] + result["confirmed"]) else 1


def cmd_estimate(args) -> int:
    from . import network
    common = {"power_w": args.power}
    if args.grille_open_area is not None:
        common["grille_open_area"] = args.grille_open_area
    if args.bracket_k is not None:
        common["bracket_k"] = args.bracket_k
    if args.rpm is None and args.stacked == 1 and args.pull_rpm is None:
        setups = network.STANDARD
    else:
        custom = dict(rpm=2500 if args.rpm is None else args.rpm, stacked=args.stacked, pull_rpm=args.pull_rpm,
                      label="custom")
        if args.collector_k is not None:
            custom["collector_k"] = args.collector_k
        setups = [network.Setup(**custom)]
    setups = [network.Setup(**{**s.__dict__, **common}) for s in setups]
    base_setup = network.Setup(**{**network.BASELINE.__dict__, **common})
    base = network.evaluate(base_setup)
    bracket = f"bracket windows (k {base_setup.bracket_k:.2f})" if base_setup.bracket_k else "no bracket"
    if base_setup.grille_open_area < 1:
        bracket += f", perforated grille {base_setup.grille_open_area:.0%} open"
    print(f"Baseline (vs column): {base_setup.label}, {bracket}: {base['flow_ls']:.2f} L/s, "
          f"peak rise {base['peak_base_rise_k']:.1f} K. Every row exhausts through the same bracket.")
    print(f"{'setup':18s} {'flow L/s':>9s} {'dP Pa':>7s} {'peak rise K':>12s} {'vs 1@2500':>10s} {'noise dB':>9s}")
    for r in map(network.evaluate, setups):
        flag = "  (extrapolated)" if r["extrapolated"] else ""
        print(f"{r['label']:18s} {r['flow_ls']:9.2f} {r['pressure_pa']:7.1f} {r['peak_base_rise_k']:12.1f} "
              f"{base['peak_base_rise_k'] - r['peak_base_rise_k']:+9.1f}K {r['noise_db']:+8.1f}{flag}")
    print("Peak rise: modeled heat-spreader base above intake, not GPU/HBM temperature. "
          "Noise: rule of thumb vs one fan @2500.")
    return 0


GRILLE_HELP = "optional perforated-plate grille in the card ports, open-area ratio (default 1: none)"
BRACKET_HELP = ("no card bracket plate: the ports open straight onto ambient (the reference cases); default: the "
                "solid bracket with one window per card (duct.cfd.bracket)")
PANEL_HELP = ("no case rear panel past the bracket: the whole window opens onto the collector or room (runs before the "
              "panel); default: the panel, open only where the window meets the chassis slot openings")
COVERED_HELP = ("chassis slots with a solid cover, comma-separated, as --covered-slots=-3,0,3 (0: between the cards, -3 and 3 "
                "either side; default: duct.cad.hardware's, none); a collector draws case air through the uncovered ones "
                "under its mouth")
COLLECTOR_HELP = ("with --pull-rpm: duct.cad.exhaust COLLECTOR_V2 (auto, v2), COLLECTOR_V3 / V3L / V4A / V4B (v3, v3l, "
                  "v4a, v4b), the superseded COLLECTOR_V1 (v1), the bare pull fan on the panel (bare), the CFD placeholder, or the "
                  "plug in CASE_FRACTAL's recessed bay (plug: top dam, hub fairing; plug-nohub; plug-slit: no dam, the openings "
                  "above the bracket tops draw case air; plug140: COLLECTOR_PLUG_140, the 140 mm P14 Pro Reverse pull fan), each "
                  "plug kind with CollectorParams overrides as plug:plenum_depth=55")


FIDELITY_CHOICES = sorted(FIDELITIES)
FIDELITY_HELP = ("fine: the reference mesh and gates; screen: base 5 mm with looser gates, a few minutes a run; "
                 "draft: screen without wall layers, coarser still (duct.cfd.profiles.FIDELITIES)")
CORES_HELP = ("size of the core pool shared by concurrent simulate runs (default: $DUCT_CORES, else "
              "duct.cfd.scheduler.DEFAULT_CORES; 0: no pool)")
DOMAIN_HELP = "duct.cfd.domain.DomainParams override, repeatable (e.g. simplify=.0021: a mesh perturbation)"
FAN_MODEL_HELP = ("boundary: fan curves on the inlet/exhaust patches (the network calibration); disk: actuator-disk "
                  "baffles inside the flow with still-air rooms before the intake and after the exhaust fan")
SWIRL_HELP = ("disk model: fan swirl as a multiple of the Euler-equation swirl (sign: + counter-clockwise seen from "
              "the intake side); 0: none")
# simulate: actuator disks by default (V23: +22 % cells for 1 fan, +44 % push-pull, similar solve time; Q within
# 0.7 % of the boundary fans); swirl stays opt-in (its sign is unverified and steady RANS does not settle with it)
SIMULATE_FAN_MODEL, SIMULATE_SWIRL = "disk", 0.0
STACK_EFFICIENCY = 0.7  # duct.cfd.fan.STACK_EFFICIENCY, without importing numpy at CLI start
PRESET_HELP = ("duct preset: v* = one empty slot between the cards (3-slot pitch, 60.96 mm), "
               "a* = adjacent cards in four consecutive slots (2-slot pitch, 40.64 mm)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="duct")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check external tools").set_defaults(func=cmd_doctor)
    cad = sub.add_parser("cad", help="build and export the duct STL, fit gauge and profiles")
    cad.add_argument("--out", type=Path, required=True)
    cad.add_argument("--param", action="append", metavar="K=V", help="GeometryParams override, repeatable")
    cad.add_argument("--preset", default="v24", choices=sorted(PRESETS), help=PRESET_HELP)
    cad.set_defaults(func=cmd_cad)
    ver = sub.add_parser("verify", help="print-readiness, fit, printability and seal checks for an STL (non-zero on failure)")
    ver.add_argument("stl", type=Path, nargs="?", help="the STL to check (optional with --fast: then the preset/--param design, "
                     "built through the build cache)")
    ver.add_argument("--param", action="append", metavar="K=V")
    ver.add_argument("--preset", default="v24", choices=sorted(PRESETS), help=PRESET_HELP)
    ver.add_argument("--part", default="duct", choices=["duct", "collector"], help="collector: the exhaust collector")
    ver.add_argument("--collector", default="v2", choices=["v1", "v2"], help="with --part collector: the collector preset")
    ver.add_argument("--no-slice", action="store_true", help="skip the slicer support gate")
    ver.add_argument("--json", type=Path, help="write the full printability gate results here")
    ver.add_argument("--fast", action="store_true", help="design-iteration preview, NOT a release check: the printability gates "
                     "on a coarser mesh and voxel grid, plus the slicer gate, without the CAD-vs-STL checks (duct.print.fast); `duct release` "
                     "still runs the full gates")
    ver.add_argument("--draft", action="store_true", help="with --fast: preview a DRAFT build of the design (coarser shell "
                     "dilation, several times faster; NOT the release geometry, `duct release` refuses it)")
    ver.set_defaults(func=cmd_verify)
    sl = sub.add_parser("slice", help="slice an STL with Bambu Studio (P1S, 0.28 mm PETG)")
    sl.add_argument("stl", type=Path)
    sl.add_argument("--out", type=Path)
    sl.add_argument("--no-supports", action="store_true")
    sl.set_defaults(func=cmd_slice)
    rel = sub.add_parser("release", help="build, verify, slice and package releases/VERSION")
    rel.add_argument("version", help=PRESET_HELP)
    rel.add_argument("--no-slice", action="store_true")
    rel.add_argument("--override-printability", metavar="REASON",
                     help="release although printability gates fail; the reason and failures go into PRINT-NOTES.md")
    rel.set_defaults(func=cmd_release)
    idx = sub.add_parser("index", help="write releases/index.html: both slot layouts' latest duct and collector, older releases")
    idx.add_argument("--out", help="default releases/index.html")
    idx.set_defaults(func=cmd_index)
    pv = sub.add_parser("preview", help="rewrite a release's preview pages (duct.viz.web.RELEASE_PAGES: from V30 the Fractal bay "
                                        "with the plug and the flat panel), each with its declared CFD run's field")
    pv.add_argument("version", choices=sorted(PRESETS))
    pv.add_argument("--runs", type=Path, action="append", help="directory holding the runs (repeatable; default: runs/ of this checkout and, from a worktree, of the main one)")
    pv.add_argument("--no-fields", action="store_true", help="geometry only, no CFD field (said on the page)")
    pv.set_defaults(func=cmd_preview)
    air = sub.add_parser("airflow", help="preview page with live airflow from a CFD case")
    air.add_argument("case", type=Path)
    air.add_argument("--out", type=Path, required=True)
    air.add_argument("--version", choices=sorted(PRESETS), help="duct release (STL and text); default: nearest to the case geometry")
    air.add_argument("--collector", default="auto", choices=["auto", "on", "off"],
                     help="exhaust collector and pull fan: auto (when the case has one), on, off")
    air.add_argument("--label", default="", help="case label shown with the field (default: the case name)")
    air.add_argument("--badge", default="", help="provenance shown with the field")
    air.set_defaults(func=cmd_airflow)
    vid = sub.add_parser("video", help="render a streamline mp4 from a CFD case")
    vid.add_argument("case", type=Path)
    vid.add_argument("--out", type=Path, required=True)
    vid.add_argument("--stl", type=Path, default=Path("releases/v23/dual-170hx-continuous-v23.stl"))
    vid.add_argument("--frames", type=int, default=150)
    vid.set_defaults(func=cmd_video)
    def fan_args(p):
        p.add_argument("--rpm", type=float, default=2500.0, help="intake fan; 0: none (pull only)")
        p.add_argument("--fans", type=int, default=1, help="intake fans stacked in series")
        p.add_argument("--stack-efficiency", type=float, default=STACK_EFFICIENCY,
                       help="fraction of the ideal pressure gain per extra stacked fan (shared with duct estimate)")
        p.add_argument("--pull-rpm", type=float, help="exhaust fan on a collector over the bracket (push-pull)")
        p.add_argument("--inlet", default="case", help="case | fan | match | fixed:PA")
        p.add_argument("--profile", help="solver profile: screen | final | legacy (default: screen; simulate: the "
                       "fidelity's)")
        p.add_argument("--np", type=int, help="MPI ranks (default: performance cores)")
        p.add_argument("--iterations", type=int, help="flow iteration budget (default: 3000; simulate: the "
                       "fidelity's)")
        p.add_argument("--min-iterations", type=int, default=0,
                       help="the flow gates stop the solver no earlier than this iteration (= --iterations: fixed-length runs)")
    cfd = sub.add_parser("cfd", help="CFD case tools").add_subparsers(dest="cfd_command", required=True)
    b = cfd.add_parser("build", help="write an OpenFOAM case from the CAD")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--param", action="append", metavar="K=V")
    b.add_argument("--preset", default="v24", choices=sorted(PRESETS), help=PRESET_HELP)
    b.add_argument("--base-cell", type=float, default=4.0)
    b.add_argument("--rpm", type=float, default=2500.0, help="intake fan; 0: none (pull only)")
    b.add_argument("--fans", type=int, default=1, help="intake fans stacked in series")
    b.add_argument("--stack-efficiency", type=float, default=STACK_EFFICIENCY)
    b.add_argument("--fan-model", default="boundary", choices=["boundary", "disk"], help=FAN_MODEL_HELP)
    b.add_argument("--swirl", type=float, default=0.0, help=SWIRL_HELP)
    b.add_argument("--side-port-coupling", type=float, default=1.0,
                   help="connected fraction of each side fin bank's effective area, 0..1 (default 1; 0: legacy)")
    b.add_argument("--pull-rpm", type=float, help="exhaust fan on a collector over the bracket (push-pull)")
    b.add_argument("--grille-open-area", type=float, help=GRILLE_HELP)
    b.add_argument("--no-bracket", dest="bracket", action="store_false", help=BRACKET_HELP)
    b.add_argument("--no-panel", dest="panel", action="store_false", help=PANEL_HELP)
    b.add_argument("--covered-slots", metavar="K,K", help=COVERED_HELP)
    b.add_argument("--collector", default="auto", type=_collector_kind,
                     help=COLLECTOR_HELP)
    b.add_argument("--shoulder-refine", action="store_true")
    b.add_argument("--domain", action="append", metavar="K=V", help=DOMAIN_HELP)
    b.set_defaults(func=cmd_cfd_build)
    fi = cfd.add_parser("inlet", help="exhaust-fan inlet profile (and per-card statics) into a solved case's summary.json")
    fi.add_argument("case", type=Path, nargs="+")
    fi.set_defaults(func=cmd_cfd_inlet)
    en = cfd.add_parser("entry", help="duct loss, card-entry uniformity and hub-wake metrics into a solved case's summary.json")
    en.add_argument("case", type=Path, nargs="+")
    en.set_defaults(func=cmd_cfd_entry)
    m = cfd.add_parser("mesh", help="blockMesh, snappyHexMesh, checkMesh, topoSet")
    m.add_argument("case", type=Path)
    m.set_defaults(func=cmd_cfd_mesh)
    r = cfd.add_parser("run", help="solve the flow to its gates (MPI)")
    r.add_argument("case", type=Path)
    r.add_argument("--strict", action="store_true", help="old strict gates")
    fan_args(r)
    r.set_defaults(func=cmd_cfd_run)
    th = sub.add_parser("thermal", help="run the fin/air/base thermal model on a solved case")
    th.add_argument("case", type=Path)
    th.add_argument("--reference-time")
    th.set_defaults(func=cmd_thermal)
    sim = sub.add_parser("simulate", help="CAD to airflow page in one go: runs/NAME")
    sim.add_argument("name")
    sim.add_argument("--param", action="append", metavar="K=V")
    sim.add_argument("--preset", default="v24", choices=sorted(PRESETS), help=PRESET_HELP)
    sim.add_argument("--base-cell", type=float, help="background cell, mm (default: the fidelity's)")
    sim.add_argument("--fidelity", default="fine", choices=FIDELITY_CHOICES, help=FIDELITY_HELP)
    sim.add_argument("--force", action="store_true", help="delete an existing runs/NAME first (default: refuse)")
    sim.add_argument("--cores", type=int, help=CORES_HELP)
    sim.add_argument("--no-page", dest="page", action="store_false")
    sim.add_argument("--grille-open-area", type=float, help=GRILLE_HELP)
    sim.add_argument("--no-bracket", dest="bracket", action="store_false", help=BRACKET_HELP)
    sim.add_argument("--no-panel", dest="panel", action="store_false", help=PANEL_HELP)
    sim.add_argument("--covered-slots", metavar="K,K", help=COVERED_HELP)
    sim.add_argument("--fan-model", default=SIMULATE_FAN_MODEL, choices=["boundary", "disk"], help=FAN_MODEL_HELP)
    sim.add_argument("--swirl", type=float, default=SIMULATE_SWIRL, help=SWIRL_HELP)
    sim.add_argument("--side-port-coupling", type=float, default=1.0,
                     help="connected fraction of each side fin bank's effective area, 0..1 (default 1; 0: legacy)")
    sim.add_argument("--domain", action="append", metavar="K=V", help=DOMAIN_HELP)
    sim.add_argument("--collector", default="auto", type=_collector_kind,
                     help=COLLECTOR_HELP)
    fan_args(sim)
    sim.set_defaults(func=cmd_simulate)
    sw = sub.add_parser("sweep", help="screen design variants on the coarse mesh, rank them, re-run the best fine: "
                                      "runs/NAME/sweep.md")
    sw.add_argument("name")
    sw.add_argument("--spec", type=Path, help="JSON: a list of variants or {defaults, variants, matrix} (duct.cfd.sweep)")
    sw.add_argument("--variant", action="append", default=[], metavar="K=V,...",
                    help="one variant, e.g. name=v3,collector=v3,pull_rpm=2177,param.chamber_length=60; repeatable")
    sw.add_argument("--matrix", action="append", default=[], metavar="K=V1,V2",
                    help="cartesian product over values, e.g. collector=v2,v3,v3l; repeatable")
    sw.add_argument("--preset", choices=sorted(PRESETS), help="default preset for every variant")
    sw.add_argument("--collector", help="default collector kind")
    sw.add_argument("--rpm", type=float, help="default intake rpm")
    sw.add_argument("--pull-rpm", type=float, help="default exhaust rpm")
    sw.add_argument("--param", action="append", metavar="K=V", help="default GeometryParams override, repeatable")
    sw.add_argument("--objectives", default="flow,peak,cov,reverse",
                    help="ranking objectives, mean rank: flow (fin flow, up), peak (rise, down), cov and reverse "
                         "(exhaust-fan inlet CoV and reverse-flow area, down; push-pull only)")
    sw.add_argument("--top", type=int, default=2, help="re-run this many best variants at the fine fidelity")
    sw.add_argument("--screen-fidelity", default="screen", choices=FIDELITY_CHOICES)
    sw.add_argument("--fine-fidelity", default="fine", choices=FIDELITY_CHOICES)
    sw.add_argument("--cores", type=int, help=CORES_HELP)
    sw.add_argument("--force", action="store_true",
                    help="re-run variants that already have a summary.json (default: reuse them: a sweep resumes)")
    sw.add_argument("--dry-run", action="store_true", help="print the simulate commands and exit")
    sw.set_defaults(func=cmd_sweep)
    est = sub.add_parser("estimate", help="fast fan/system/thermal network estimate")
    est.add_argument("--rpm", type=float)
    est.add_argument("--stacked", type=int, default=1, help="intake fans in series")
    est.add_argument("--pull-rpm", type=float, help="add an exhaust fan (push-pull)")
    est.add_argument("--collector-k", type=float, help="collector loss past the bracket, velocity heads at the fan "
                     "annulus (default: CFD-calibrated, network.COLLECTOR_K)")
    est.add_argument("--grille-open-area", type=float, help=GRILLE_HELP)
    est.add_argument("--bracket-k", type=float, help="bracket window loss, fan-annulus velocity heads (default: "
                     "CFD-calibrated, network.BRACKET_K; 0: no bracket)")
    est.add_argument("--power", type=float, default=250.0, help="W per card")
    est.set_defaults(func=cmd_estimate)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
