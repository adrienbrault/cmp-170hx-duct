"""Preview page with the live airflow: the release model viewer plus a CFD velocity export.

`duct airflow CASE --out X.html [--version v24] [--collector auto|on|off] [--label TEXT] [--badge TEXT]`.
The duct STL, version text and the push-pull collector follow the case (case.json geometry and options)
unless overridden.

`duct preview VERSION`: every preview page of a release (RELEASE_PAGES). From V30 a release has one page per case rear:
preview.html, the author's Fractal case (a recessed slot bay) with the plug collector, and preview-flat.html, a flat CEM
rear panel with the slot layout's released flat-panel collector; a segmented control switches between them. The
collector is drawn whenever one applies to the layout, with or without a CFD field.
"""
import json
import re
from pathlib import Path

import numpy as np

from ..print.preview import bore_text, wall_context, write_preview
from .export import SPACING_MM, export_case, geometry_preset

ROOT = Path(__file__).resolve().parents[2]
COLLECTORS = ("v1", "v2", "v3", "v3l")   # duct.params COLLECTOR_<V>; released ones in releases/collector-<v>/
V4_PARAMS = "COLLECTOR_V4A"              # releases/collector-v4-<n>slot: COLLECTOR_V4A.for_duct (their PRINT-NOTES)
FLAT = {5: "v3", 4: "v4-4slot"}          # the flat-panel collector a case-view release's preview-flat.html draws, by slot layout
PLUG_DRAFT = "plug collector for the Fractal recessed bay: DRAFT, photo estimates, not released"
# The plug collectors for the Fractal recessed bay (the CFD kinds of the same name): version -> duct.params base, page label.
PLUGS = {"plug": ("COLLECTOR_PLUG_BASE", "plug collector (DRAFT)"),
         "plug140": ("COLLECTOR_PLUG_140", "plug collector, 140 mm fan (DRAFT)")}

# Case views of a release: page -> the case rear it shows (preview.html is the author's own case).
CASE_PAGES = {"preview.html": "fractal", "preview-flat.html": "flat"}
# releases/<version>/<page> -> the CFD run (runs/<name>) whose field the page embeds; None: none (geometry only, said on the
# page). Releases before V30 keep their single page; a release not listed here gets both case pages without a field.
RELEASE_PAGES = {
    "v23": {"preview.html": "v23-1fan"}, "v24": {"preview.html": "v24-1fan"}, "v25": {"preview.html": "v25b-1fan-disk"},
    "v27": {"preview.html": "v27-pushpull"}, "v28": {"preview.html": "v28-pp-v3"}, "v29": {"preview.html": "v28-pp-v3"},
    "a29": {"preview.html": "a29-pp-plug", "preview-flat.html": "a29-pp-v4a"},
    "v30": {"preview.html": "v30-pp-plug", "preview-flat.html": "v30-pp-v3"},
    "a30": {"preview.html": "a30-pp-plug", "preview-flat.html": "a30-pp-v4a"},
}


def release_pages(version: str) -> dict[str, str | None]:
    """The preview pages of release `version` and the run each embeds (RELEASE_PAGES; default: both case pages, no field)."""
    return RELEASE_PAGES.get(version, dict.fromkeys(CASE_PAGES))


def slots(g) -> int:
    """Slots the two cards span: 5 (3-slot pitch, one empty between them) or 4 (adjacent)."""
    from ..params import slot_layout
    return len(slot_layout(g.pitch)["span"])


def release_notes(version: str = "v23") -> tuple[Path, dict]:
    """(released STL, preview notes) for a release directory, with the slicer numbers filled into `note`."""
    from ..print.release import NOTES
    rel = ROOT/"releases"/version
    notes = dict(NOTES[version])
    sc = rel/"slicer-checks.json"
    if sc.exists():
        a = json.loads(sc.read_text())["automatic_supports"]
        notes["note"] = notes["note"].format(minutes=a["minutes"], grams=a["grams"])
    return rel/f"dual-170hx-continuous-{version}.stl", notes


def collector_version(case: Path, fan_face: dict | None = None, g=None) -> str | None:
    """Which collector a CFD run modelled: 'plug' / 'plug140' (duct.cad.plug in CASE_FRACTAL), 'v4-4slot' / 'v4-5slot' (COLLECTOR_V4A
    on duct g's layout), 'v1', 'v2', 'v3', 'v3l' or 'bare' (the pull fan straight on the panel).
    From case.json collector.source ('duct.cad.exhaust COLLECTOR_V3', '... bare_fan_air ...'); for older runs from the run
    name (v28-pp-v3 -> v3, v28-pp-v3l -> v3l, v28-pp-bare -> bare, a30-pp-plug -> plug); else the collector whose fan face is
    the run's (on the panel, or on the bracket plane as the pre-panel runs had it); None if none matches."""
    src = ""
    cj = Path(case)/"case.json"
    if cj.exists():
        src = (json.loads(cj.read_text()).get("collector") or {}).get("source") or ""
    name = Path(case).name
    v4 = f"v4-{slots(g)}slot" if g is not None else None
    if kind := source_kind(src, g):
        return kind
    if m := re.search(r"-(plug(?:140)?)(?=-|$)", name):
        return m[1]
    if re.search(r"-v4a(?=-|$)", name):
        return v4
    if m := re.search(r"-(v\d+l?|bare)(?=-|$)", name):
        return m[1]
    if fan_face:
        from ..cad.hardware import build_hardware
        for v in COLLECTORS:
            c = collector_params(v, g); hw = build_hardware(g, c)
            for z0 in (hw.panel_face, hw.z_b):
                if _offset(fan_face, c.fan_axis, z0+c.plenum_depth) is None:
                    return v
    return None


def source_kind(source: str | None, g=None) -> str | None:
    """collector_version of a case.json collector.source string alone (None when it names none of ours)."""
    src = source or ""
    if "duct.cad.plug" in src:
        return "plug140" if re.search(r"\bCOLLECTOR_PLUG_140\b", src) else "plug"
    if "bare" in src:
        return "bare"
    if re.search(rf"\b{V4_PARAMS}\b", src):
        return f"v4-{slots(g)}slot" if g is not None else "v4"
    if m := re.search(r"COLLECTOR_(V\d+L?)\b", src):
        return m[1].lower()
    return None


def collector_params(version: str, g=None):
    """COLLECTOR_<VERSION>, on duct g's pitch and bracket plane (CollectorParams.for_duct) when g is given. 'plug': the plug
    collector for the Fractal recessed bay (duct.cad.plug.plug_params(COLLECTOR_PLUG_BASE.for_duct(g), CASE_FRACTAL), the CFD
    kind 'plug'; 'plug140': COLLECTOR_PLUG_140's); 'v4-4slot' / 'v4-5slot': the released v4 (COLLECTOR_V4A)."""
    from .. import params
    if version in PLUGS:
        from ..cad.hardware import CASE_FRACTAL
        from ..cad.plug import plug_params
        g = g or params.GeometryParams()
        return plug_params(getattr(params, PLUGS[version][0]).for_duct(g), CASE_FRACTAL.for_pitch(g.pitch))
    c = getattr(params, V4_PARAMS if version.startswith("v4-") else f"COLLECTOR_{version.upper()}")
    return c.for_duct(g) if g is not None else c


def collector_fits(g, version: str = "v3") -> bool:
    """Whether collector `version` exists for duct g's slot layout: the plug fits either layout's bay; 'v4-<n>slot' is for n
    slots; v1-v3 (and the bare fan) were designed for the cards three slots apart (5 slots)."""
    if version in PLUGS:
        return True
    if m := re.fullmatch(r"v4-(\d)slot", version):
        return slots(g) == int(m[1])
    return slots(g) == 5


def plug_note(g) -> str:
    """The plug's page note: the draft warning, and for the 4-slot layout the bay offset the model does not have."""
    note = PLUG_DRAFT
    if slots(g) == 4:
        from ..cad.hardware import CASE_FRACTAL
        half = CASE_FRACTAL.slot_pitch/2
        note += (f". 4-slot: the model centres the six slot positions in the seven-slot bay, so the real cards sit half a slot "
                 f"({half:.1f} mm) to one side of the mouths drawn here (and in the CFD run)")
    return note


def _offset(fan_face: dict, centre, z, tol=.5) -> list | None:
    """CFD fan face minus the drawn one (x, y, z), or None when they agree within tol (mm)."""
    d = [fan_face["centre"][0]-centre[0], fan_face["centre"][1]-centre[1], fan_face["z"]-z]
    return d if max(map(abs, d)) > tol else None


def _triangles(m) -> np.ndarray:
    raw = m.to_mesh64()
    return np.asarray(raw.vert_properties)[:, :3][np.asarray(raw.tri_verts)]


def collector_release(fan_face: dict | None = None, g=None, version: str = "v3") -> dict | None:
    """The collector `version` ('v1' ... 'v3l', 'v4-4slot' / 'v4-5slot', 'plug', or 'bare': the pull fan alone) placed in the
    duct frame on the case rear of a duct with GeometryParams g (None: GeometryParams()); None when it does not exist for g's
    slot layout (collector_fits). Flat-panel collectors: the flange on the rear panel's outer face (duct.cad.hardware.placed),
    the pull fan on its fan face. Released ones come from their STL (print frame: STL z = duct z - inlet_z, flange face on
    z = 0); unreleased ones (v3l) are built from their params. The plug (unreleased, built from its params with its snap
    clips): its face on the divider bars' crowns in CASE_FRACTAL's recess (duct.cad.plug.plug_placement), case 'fractal'.
    Adds `params` (CollectorParams for the hardware), `case` ('flat' or 'fractal') and, when the CFD fan face (case.json,
    fan_face) is not this collector's, cfd_offset_mm (CFD minus drawn, x, y, z)."""
    from ..cad.hardware import build_hardware, placed
    from ..params import GeometryParams
    g = g or GeometryParams()
    if not collector_fits(g, version):
        return None
    if version == "bare":   # CFD baseline: the fan frame gasketed onto the panel, where the run put it
        c = collector_params("v2", g)
        if not fan_face:
            return None
        return dict(stl=None, label="bare pull fan", params=c, case="flat", kind="bare",
                    fan=dict(centre=list(fan_face["centre"]), z=fan_face["z"], radius=c.fan_radius, size=c.fan_size, thickness=c.fan_thickness))
    from ..cache import build_collector   # an unchanged design is not rebuilt
    c = collector_params(version, g)
    if version in PLUGS:
        from ..cad.hardware import CASE_FRACTAL, bracket_z
        from ..cad.plug import plug_placement
        from ..cache import collector_export_dir
        from ..print.preview import stl_triangles
        case = CASE_FRACTAL.for_pitch(g.pitch); s = build_collector(c)
        dz = bracket_z(g, case)+plug_placement(c, case)-c.inlet_z   # as duct.cad.plug.plug_fit_check places it
        # the body as a release would export it (print frame: STL z = duct z - inlet_z; ~1/5 of the raw solid's triangles),
        # and the snap clips in place
        stl = collector_export_dir(c, "collector-plug")/"dual-170hx-collector-plug.stl"
        tri = [stl_triangles(stl)+np.float32([0, 0, c.inlet_z+dz])]
        if s.clips is not None: tri.append(_triangles(s.clips.translate([0, 0, dz])).astype(np.float32))
        face = dict(centre=list(c.fan_axis), z=c.inlet_z+dz+c.plenum_depth, radius=c.fan_radius, size=c.fan_size, thickness=c.fan_thickness)
        out = dict(label=PLUGS[version][1], fan=face, params=c, case="fractal", kind=version, note=plug_note(g),
                   stl=None, triangles=np.concatenate(tri))
    else:
        hw = build_hardware(g, c)
        face = dict(centre=list(c.fan_axis), z=hw.panel_face+c.plenum_depth, radius=c.fan_radius, size=c.fan_size, thickness=c.fan_thickness)
        label = (f"collector v4 ({version.removeprefix('v4-').replace('slot', '-slot')})" if version.startswith("v4-")
                 else f"collector {version.replace('l', 'L')}")
        out = dict(label=label, fan=face, params=c, case="flat", kind=version)
        stl = ROOT/"releases"/f"collector-{version}"/f"dual-170hx-collector-{version}.stl"
        if stl.exists():
            out.update(stl=stl, offset=(0., 0., hw.panel_face))
        else:
            out.update(stl=None, triangles=_triangles(placed(build_collector(c), hw)))
    if fan_face and (d := _offset(fan_face, face["centre"], face["z"])):
        out["cfd_offset_mm"] = d
    return out


def case_hardware(g, coll: dict | None) -> tuple[dict, dict]:
    """(hardware meshes, page case info {key, label, keepouts, labels}) of the case rear collector `coll` sits on: CASE_FRACTAL's
    recessed bay for the plug (duct.cad.plug.recess_page_parts: border sheet, floor, divider bars, bracket plates, bezels,
    the louvred blank, keep-out boxes, slot labels), else the flat CEM panel (duct.cad.hardware.hardware_meshes)."""
    from ..cad.hardware import CASE_FRACTAL, hardware_meshes, manifold_meshes
    if coll and coll.get("case") == "fractal":
        from ..cad.plug import recess_page_parts
        p = recess_page_parts(g, coll["params"], CASE_FRACTAL.for_pitch(g.pitch))
        return manifold_meshes(p["parts"]), dict(key="fractal", label="Fractal recessed bay", keepouts=p["keepouts"], labels=p["labels"])
    return (hardware_meshes(g, (coll or {}).get("params") or collector_params("v2", g)),
            dict(key="flat", label="Flat rear panel", keepouts=[], labels=[]))


def case_note(coll: dict | None, field: bool) -> str:
    """The page's case line: which case rear and collector it shows, the draft warning for the plug, and whether a CFD field
    comes with it."""
    if coll and coll.get("case") == "fractal":
        text = coll["note"]
    elif coll:
        text = f"Flat CEM rear panel, not your Fractal case · {coll['label']}" + (" (released)" if coll.get("stl") else "")
    else:
        return ""
    return text + ("" if field else " · no CFD run for this view yet: geometry only")


def case_links(version: str, page: str) -> list[dict]:
    """The case-rear switcher of a case-view release's page: {label, short, href, current} per case page (hrefs relative to
    the release directory, where both pages live)."""
    pages = release_pages(version)
    if set(pages) != set(CASE_PAGES):
        return []
    from ..params import PRESETS
    v = FLAT[slots(PRESETS[version])]; fl = "v4" if v.startswith("v4") else v
    text = {"fractal": ("Fractal bay · plug (draft)", "Fractal · plug"), "flat": (f"Flat panel · collector {fl}", f"Flat · {fl}")}
    return [dict(label=text[CASE_PAGES[p]][0], short=text[CASE_PAGES[p]][1], href=p, current=p == page) for p in CASE_PAGES]


def fan_text(meta: dict) -> str:
    """'push-pull · intake + exhaust fan @ 2500 rpm' and the like, from the export metadata."""
    rpm, pull, n = meta.get("rpm") or 0, meta.get("pull_rpm"), meta.get("intake_count", 1)
    intake = f"{n} stacked intake fans" if n > 1 else "intake"
    if pull and rpm:
        same = abs(rpm-pull) < 1
        return (f"push-pull · {intake} + exhaust fan @ {rpm:.0f} rpm" if same
                else f"push-pull · {intake} @ {rpm:.0f} + exhaust fan @ {pull:.0f} rpm")
    if pull:
        return f"pull · exhaust fan @ {pull:.0f} rpm, open intake"
    return f"{intake if n > 1 else '1 intake fan'} @ {rpm:.0f} rpm"


def write_airflow_preview(case, out_html, version: str | None = None, spacing_mm: float = SPACING_MM,
                          label: str = "", badge: str = "", collector: str = "auto", switch: list[dict] | None = None) -> Path:
    """Export `case` (reconstructed OpenFOAM case, latest time) and write the release preview with it embedded.
    version: release preset of the duct STL and text; None: the preset nearest to the case geometry.
    collector: auto (when the case has one), on, off.
    badge: provenance shown with the field, e.g. 'qualitative, V23 upper-r6 @400, not fully converged'.
    switch: the case-rear switcher (case_links)."""
    from ..params import PRESETS
    case = Path(case)
    version = version or geometry_preset(case)["name"]
    g = PRESETS[version]
    stl, notes = release_notes(version)
    exp = export_case(case, spacing_mm, label=label, badge=badge)
    meta = exp.meta
    coll = None
    if collector == "on" or (collector == "auto" and meta.get("collector")):
        ff = (meta.get("collector") or {}).get("fan_face")
        which = collector_version(case, ff, g)
        coll = collector_release(ff, g, which) if which else None
        if coll is None and meta.get("collector") and collector_fits(g):  # a non-release collector (e.g. the CFD placeholder): pull fan only
            ff = meta["collector"]["fan_face"]
            coll = dict(stl=None, fan=dict(centre=ff["centre"], z=ff["z"], radius=ff["radius"])) if ff else None
    hardware = info = None
    if coll or meta.get("collector") or meta.get("bracket"):   # the case rear the collector sits on / the brackets belong to
        hardware, info = case_hardware(g, coll)
    if coll and coll.get("cfd_offset_mm"):   # the field's exhaust fan is not where the drawn collector puts it
        d = coll["cfd_offset_mm"]
        exp.meta["badge"] = (exp.meta.get("badge") or "")+(f" · field's exhaust fan face is ({d[0]:+.1f}, {d[1]:+.1f}, {d[2]:+.1f}) mm from "
                                                         f"the {coll['label']} shown")
    V = notes["version"]
    wc = wall_context(g)
    ctx = dict(wc, subtitle=f"{V} · {bore_text(wc['dims'])} mm fit · {fan_text(meta)}",
               source=f"Actual {V} duct STL")
    if meta.get("pull_rpm"):
        ctx["tag"] = f"{V} · push-pull" + (f" · {coll['label']}" if coll and coll.get("label") else "")
    if coll and (coll.get("stl") or coll.get("triangles") is not None):
        ctx["source"] += f" + {coll['label']}" + (" STL" if coll.get("stl") else " (from its parameters)")
    if info:
        info["note"] = case_note(coll, True) if switch or coll and coll.get("case") == "fractal" else ""
    return write_preview(stl, notes, out_html, airflow=exp, collector=coll, context=ctx, hardware=hardware, case=info,
                         case_links=switch)


def write_release_preview(version: str, out_html=None, collector: str | None = None, switch: list[dict] | None = None,
                          stl=None, notes: dict | None = None, g=None) -> Path:
    """A release page without a CFD field, from the released STL and notes: the duct with collector `collector` (default
    the plug: the Fractal bay) and its case rear, said to come without a field. stl / notes / g: for a release being
    assembled outside releases/ (duct.print.release)."""
    from ..params import PRESETS
    g = g or PRESETS[version]
    if stl is None:
        stl, rn = release_notes(version)
        notes = notes or rn
    coll = collector_release(None, g, collector or "plug")
    hardware, info = case_hardware(g, coll)
    info["note"] = case_note(coll, False)
    ctx = wall_context(g)
    if coll:
        ctx["source"] = f"Actual {notes['version']} duct STL + {coll['label']}" + (" STL" if coll.get("stl") else " (from its parameters)")
    return write_preview(stl, notes, out_html or Path(stl).parent/"preview.html", collector=coll, context=ctx, hardware=hardware,
                         case=info, case_links=switch)


def find_run(name: str, runs=None) -> Path | None:
    """runs/<name> (the first of the `runs` directories that has it, with a case.json), or None. runs None: this checkout's
    runs/ and, from a git worktree, the main checkout's (duct.print.index)."""
    from ..print.index import _run_roots
    return next((Path(d)/name for d in (runs or _run_roots()) if (Path(d)/name/"case.json").exists()), None)


def run_badge(run: Path, version: str) -> str:
    """Provenance line for a run's field: the run, the duct it was run on, its convergence, the collector it modelled."""
    s = json.loads((run/"summary.json").read_text()) if (run/"summary.json").exists() else {}
    cj = json.loads((run/"case.json").read_text())
    f = s.get("flow") or {}; fid = (s.get("fidelity") or {}).get("name")
    src = (cj.get("collector") or {}).get("source") or ""
    th = s.get("thermal_acceptance") or {}
    return " · ".join(filter(None, [f"{version.upper()} · duct simulate {run.name}", f"{fid} mesh" if fid else "",
                                    f"{f.get('stage')} at iteration {f.get('iteration')}" if f else "", src,
                                    f"thermal {th['verdict'].removeprefix('thermal: ').split(';')[0]}" if th and not th.get("accepted") else ""]))


def write_release_pages(version: str, runs=None, fields: bool = True, out_dir=None, notes: dict | None = None,
                        g=None) -> list[Path]:
    """Every preview page of release `version` (release_pages). A case-view release: preview.html (the Fractal bay with the
    plug) and preview-flat.html (the flat panel with FLAT's collector), switchable, each with its declared run's field
    (searched in `runs`; a declared run that is missing is an error) or, declared without one or with fields=False, geometry
    only. A single-page release regenerates its page from its run. out_dir / notes / g: a release being assembled
    (duct.print.release, fields=False)."""
    from ..params import PRESETS
    g = g or PRESETS[version]
    out_dir = Path(out_dir) if out_dir else ROOT/"releases"/version
    stl = out_dir/f"dual-170hx-continuous-{version}.stl"
    notes = notes or release_notes(version)[1]
    pages = release_pages(version); multi = set(pages) == set(CASE_PAGES); out = []
    for page, name in pages.items():
        want = ("plug" if CASE_PAGES[page] == "fractal" else FLAT[slots(g)]) if multi else None
        switch = case_links(version, page) if multi else None
        run = find_run(name, runs) if fields and name else None
        if fields and name and run is None:
            where = ", ".join(map(str, runs)) if runs else "runs/ (this checkout and the main one)"
            raise FileNotFoundError(f"{version}/{page} declares run {name}, not found in {where}")
        if run is not None:
            got = collector_version(run, None, g)
            if want and got != want:
                raise ValueError(f"{version}/{page} shows collector {want} but run {name} modelled {got}")
            out.append(write_airflow_preview(run, out_dir/page, version, badge=run_badge(run, version),
                                             collector="on" if want else "auto", switch=switch))
        else:
            out.append(write_release_preview(version, out_dir/page, want, switch, stl, notes, g))
    return out
