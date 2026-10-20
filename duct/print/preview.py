"""Self-contained three.js preview: templates/preview.html with the meshes embedded and version text filled in.

The page always carries the fan network model's constants (taken from duct.network when the page is
written, so the JS port never holds its own copy). An optional CFD velocity export
(duct.viz.export.AirflowExport) adds the live airflow particles; an optional exhaust collector STL
adds the push-pull assembly (collector shell and pull fan).

Meshes are embedded indexed and lossless: unique float32 vertices and uint32 triangle indices, each
byte-shuffled, gzipped and base64-encoded (the page inflates them with DecompressionStream, as the
airflow field). That is ~8× smaller than the base64 STL.
"""
import base64
import gzip
import html
import json
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np

TEMPLATE = Path(__file__).resolve().parents[2]/'templates/preview.html'
KEYS = ('version', 'prev_version', 'headline', 'features', 'note', 'section_title', 'section_text', 'section_alt')


def network_payload() -> dict:
    """Everything the page's JS port of duct.network needs, plus the six STANDARD results for parity checks."""
    from .. import network
    from ..cfd import fan
    return dict(
        chart_rpm=fan.CHART_RPM, chart_q=[float(v) for v in fan._Q], chart_p=[float(v) for v in fan._P],
        beyond_free_delivery_slope=fan._BEYOND_FREE_DELIVERY_SLOPE,
        fan_rho=fan.RHO, fan_annulus_area=fan.ANNULUS_AREA,           # dynamic head at the fan outlet
        rho=network.RHO, fan_area=network.FAN_AREA,                    # bracket/collector loss velocity head
        port_area=network.PORT_AREA,                                   # optional perforated grille
        system_a=float(network.SYSTEM_A), system_b=float(network.SYSTEM_B),
        rise_fit=[float(v) for v in network.RISE_FIT], reference_power_w=network.REFERENCE_POWER_W,
        extrapolation_q=network.EXTRAPOLATION_Q, bracket=[1e-5, .08], noise_ref_rpm=2500.0,
        defaults=asdict(network.Setup()),
        standard=[dict(setup=asdict(s), result={k: (v if isinstance(v, str) else bool(v) if isinstance(v, bool) else float(v))
                                                 for k, v in network.evaluate(s).items()}) for s in network.STANDARD],
    )


def _shuffle(a: np.ndarray) -> bytes:
    """Byte planes of a little-endian array: all byte 0s, then all byte 1s, ... (gzips much better)."""
    return a.view(np.uint8).reshape(-1, a.dtype.itemsize).T.tobytes()


def stl_triangles(stl) -> np.ndarray:
    """(n, 3, 3) float32 triangle vertices of a binary STL, in file order."""
    raw = Path(stl).read_bytes()
    n = int(np.frombuffer(raw, '<u4', 1, 80)[0])
    rec = np.frombuffer(raw, np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]), n, 84)
    return rec['v'].copy()


def mesh_payload(stl, offset=(0., 0., 0.)) -> dict:
    """Indexed, lossless mesh of a binary STL: gzip(shuffled float32 vertices + shuffled uint32 indices), base64.
    offset (mm) is applied by the page (e.g. the collector's print frame to the duct frame)."""
    return triangles_payload(stl_triangles(stl), offset)


def triangles_payload(tri: np.ndarray, offset=(0., 0., 0.)) -> dict:
    """mesh_payload of (n, 3, 3) triangle vertices. Only bit-identical vertices share an index: the triangles are kept
    exactly (no welding, so touching but separate parts stay separate)."""
    tri = np.asarray(tri, np.float32)
    verts, idx = np.unique(tri.reshape(-1, 3), axis=0, return_inverse=True)
    data = _shuffle(verts.astype('<f4').ravel())+_shuffle(idx.astype('<u4').ravel())
    return dict(faces=len(tri), vertices=len(verts), offset=[float(v) for v in offset],
                encoding='gzip:float32 xyz byte-shuffled vertices+uint32 byte-shuffled triangle indices',
                data=base64.b64encode(gzip.compress(data, 9, mtime=0)).decode())


def decode_mesh(payload: dict) -> np.ndarray:
    """(faces, 3, 3) float32 triangles of a mesh_payload (offset not applied): the page's decoder in numpy."""
    raw = gzip.decompress(base64.b64decode(payload['data']))
    nv, nf = payload['vertices'], payload['faces']
    unshuffle = lambda b, n, dt: np.frombuffer(np.frombuffer(b, np.uint8).reshape(np.dtype(dt).itemsize, n).T.tobytes(), dt)  # noqa: E731
    v = unshuffle(raw[:12*nv], 3*nv, '<f4').reshape(-1, 3)
    i = unshuffle(raw[12*nv:12*nv+12*nf], 3*nf, '<u4').reshape(-1, 3)
    return v[i]


def page_dims(g) -> dict:
    """The duct dimensions the page draws and prints (mm), from the GeometryParams the STL was built from:
    the cards seat at z = chamber, the rear brackets (and the push-pull collector inlet) at z = chamber + card."""
    from ..cfd.domain import DOMAIN
    return dict(chamber=g.chamber_length, collar=g.collar_length, depth=g.chamber_length+g.collar_length,
                bore=[float(v) for v in g.bore], pitch=g.pitch, card=DOMAIN.card_envelope, fan_thickness=g.fan_thickness,
                plate=g.fan_plate, flange=g.flange_thickness, hole_pitch=2*g.fan_hole_offset,
                passage_radius=[g.passage_radius-g.passage_radius_drop, g.passage_radius], nose_edge=2*g.nose_tip_half_width)


def wall_context(g) -> dict:
    """Page context from the release's GeometryParams: shell and collar wall text for the dimension table
    (V24+ shells are a uniform dilation of the air passage) and the dimensions the page draws (page_dims)."""
    return dict(shell_wall=f'{g.wall_dilation:g}' if getattr(g, 'shell_from_air', 0) else '1.6–1.7', collar_wall=f'{g.collar_wall:g}',
                dims=page_dims(g))


def bore_text(dims: dict) -> str:
    """'38.5 × 98.5' from page_dims."""
    return ' × '.join(f'{v:g}' for v in dims['bore'])


def _dims_fill(d: dict) -> dict:
    """Template placeholders of the dimension table and fields (DIM_*), and the JSON the scene is built from."""
    g = lambda v: f'{v:g}'  # noqa: E731
    return {'DIMS_JSON': _script_json(d), 'DIM_CHAMBER': g(d['chamber']), 'DIM_COLLAR': g(d['collar']), 'DIM_DEPTH': g(d['depth']),
            'DIM_BORE': bore_text(d), 'DIM_PITCH': g(d['pitch']), 'DIM_HALF_PITCH': f"{d['pitch']/2:.1f}", 'DIM_CARD': g(d['card']), 'DIM_CARD_FACE': g(d['fan_thickness']+d['chamber']),
            'DIM_PLATE': f"{g(d['plate'])} × {g(d['plate'])} × {g(d['flange'])}", 'DIM_HOLES': f"{g(d['hole_pitch'])} × {g(d['hole_pitch'])}",
            'DIM_BLEND': '–'.join(g(v) for v in d['passage_radius']), 'DIM_NOSE': g(d['nose_edge'])}


def _switch_html(layouts: list[dict], name: str | None = None, cls: str = 'layout-switch') -> str:
    """A segmented control of plain links: the slot-layout switcher, or (cls 'layout-switch case-switch') the case-rear one.
    The page script adds the current view to the hash of the data-layout ones on click. An entry with layout=False is a
    plain link (older pages: to releases/index.html)."""
    if not layouts: return ''
    esc = lambda t: html.escape(str(t), quote=True)  # noqa: E731
    cur = ' aria-current="page"'
    segs = ''.join(f'<a class="seg{" active" if l.get("current") else ""}" href="{esc(l["href"])}"{cur if l.get("current") else ""}'
                   f'{" data-layout" if l.get("layout", True) else ""}>'
                   f'<span class="long">{esc(l["label"])}</span><span class="short">{esc(l.get("short") or l["label"])}</span></a>' for l in layouts)
    name = name or ('Slot layout' if any(l.get('layout', True) for l in layouts) else 'Releases')
    return f'<nav class="{cls}" aria-label="{name}">{segs}</nav>'


def _case_bar(case: dict | None, links: list[dict] | None) -> str:
    """Over the model: the case-rear switcher and the case line (which case and collector; the plug's DRAFT warning)."""
    note = (case or {}).get('note') or ''
    if not note and not links: return ''
    return ('<div class="casebar">'+_switch_html(links or [], 'Case rear', 'layout-switch case-switch')+
            (f'<p class="case-note">{html.escape(note)}</p>' if note else '')+'</div>')


def _script_json(data) -> str:
    """JSON safe to inline in a <script type="application/json"> element."""
    return json.dumps(data, separators=(',', ':')).replace('</', '<\\/')


def write_preview(stl, notes: dict, out_html, airflow=None, collector=None, context: dict | None = None, hardware: dict | None = None,
                  layouts: list[dict] | None = None, case: dict | None = None, case_links: list[dict] | None = None) -> Path:
    """notes: version ('V23'), prev_version ('V22'), headline, features, note, section_title, section_text, section_alt.
    airflow: None, a duct.viz.export.AirflowExport, or its payload() dict.
    collector: None or dict(stl=path or None, or triangles=(n, 3, 3) array, or neither (pull fan only),
               offset=(x, y, z) mm into the duct frame, label=str,
               fan=dict(centre, z, radius)): the exhaust collector shell and the pull fan on its face.
    hardware: None or {name: trimesh.Trimesh} in the duct frame (duct.cad.hardware.hardware_meshes: the case rear panel,
              slot ledge, brackets, covers, screws and window bezels), drawn as the "Case rear" group.
    context: optional page text: subtitle (after 'ARCTIC P12 Pro PST CO · '), tag, source (model provenance line),
             shell_wall, collar_wall (mm), and dims (page_dims of the GeometryParams the STL was built from;
             default: GeometryParams() defaults). wall_context(params) gives the walls and dims.
    layouts: the slot-layout switcher, [{label, href, current}]; None: derived from the releases directory
             for a page inside releases/ (duct.print.layouts.layout_links: the same design in the other slot layout,
             e.g. v29 / a29), else none; [] for none.
             A page inside releases/ also links releases/index.html.
    case: None or the case rear's page info (duct.viz.web.case_hardware): key ('flat' / 'fractal'), label, note (shown over
          the model), keepouts ([{name, min, max}] mm, drawn as faint boxes), labels ([{text, pos}] mm).
    case_links: the case-rear switcher, [{label, short, href, current}] (duct.viz.web.case_links); None / []: none."""
    missing = set(KEYS)-set(notes)
    if missing: raise KeyError(f'missing preview notes: {sorted(missing)}')
    if airflow is not None and not isinstance(airflow, dict): airflow = airflow.payload()
    from ..params import GeometryParams
    ctx = dict(context or {})
    dims = ctx.pop('dims', None) or page_dims(GeometryParams())
    ctx = {'subtitle': f"{notes['version']} · {bore_text(dims)} mm fit · open connector access",
           'tag': f"{notes['version']} · {notes['headline']}",
           'source': f"Actual {notes['version']} duct STL", 'shell_wall': '1.6–1.7', 'collar_wall': '1.6', **ctx}
    meshes = dict(duct=mesh_payload(stl), collector=None,
                  hardware={k: triangles_payload(m.vertices[m.faces]) for k, m in hardware.items()} if hardware else None)
    if collector:
        off = collector.get('offset', (0, 0, 0))
        shell = (mesh_payload(collector['stl'], off) if collector.get('stl') else
                 triangles_payload(collector['triangles'], off) if collector.get('triangles') is not None else {})
        meshes['collector'] = dict(shell, label=collector.get('label', 'exhaust collector'), fan=collector.get('fan'), kind=collector.get('kind'))
    if case:
        meshes['case'] = {k: case.get(k) for k in ('key', 'label', 'note', 'keepouts', 'labels')}
    from .layouts import RELEASES, layout_links
    out = Path(out_html)
    in_releases = out.resolve().is_relative_to(RELEASES.resolve())
    if layouts is None: layouts = layout_links(notes['version'].lower(), out) if in_releases else []
    fill = {'LAYOUT_SWITCH': _switch_html(layouts) or (_switch_html([dict(label='All releases · latest →', href='../index.html', layout=False)]) if in_releases else ''),
            'CASE_BAR': _case_bar(case, case_links),
            'INDEX_LINK': '<a class="link" href="../index.html">All releases · both slot layouts →</a><br>' if in_releases else '',
            'MESH_JSON': _script_json(meshes), 'VERSION_LC': notes['version'].lower(), 'PREV_VERSION_LC': notes['prev_version'].lower(),
            'NETWORK_JSON': _script_json(network_payload()), 'AIRFLOW_JSON': _script_json(airflow and {k: v for k, v in airflow.items() if k != 'data'}),
            'AIRFLOW_FIELD': (airflow or {}).get('data') or '',
            **_dims_fill(dims), **{k.upper(): notes[k] for k in KEYS}, **{f'CTX_{k.upper()}': str(v) for k, v in ctx.items()}}
    html = TEMPLATE.read_text()
    for k, v in sorted(fill.items(), key=lambda kv: -len(kv[0])): html = html.replace(f'@@{k}@@', v)
    assert not re.search(r'@@[A-Z_]+@@', html), 'unfilled placeholder'
    out = Path(out_html); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(html)
    return out
