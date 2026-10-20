"""releases/index.html: the landing page. One card per slot layout (the latest duct and collector for it, key numbers,
links to the preview and the STLs), then the older releases. Built from the releases directory (duct.print.layouts),
each release's slicer-checks.json and PRINT-NOTES.md, the airflow its preview page embeds and, when that run's
directory is present, its thermal summary. `duct index` writes it; rerun it after a release.
"""
import html
import json
import re
from pathlib import Path

from .layouts import RELEASES, ROOT, Release, latest, layout_label, releases

LAYOUTS = (5, 4)   # card order: the 5-slot layout (one empty slot between the cards), then adjacent cards


def _run_roots() -> list[Path]:
    """runs/ of this checkout and, from a git worktree, of the main checkout (runs/ is not versioned)."""
    roots = [ROOT/'runs']
    git = ROOT/'.git'
    if git.is_file() and (m := re.match(r'gitdir:\s*(.+)', git.read_text().strip())):
        main = Path(m[1]).resolve().parents[2]   # <main>/.git/worktrees/<name>
        roots.append(main/'runs')
    return roots


def headline(r: Release) -> str:
    """The PRINT-NOTES.md title without the 'DUAL CMP 170HX — ' prefix and the release name ('V29 tighter seal ...')."""
    p = r.path/'PRINT-NOTES.md'
    first = p.read_text().split('\n', 1)[0] if p.exists() else ''
    t = re.sub(r'^#\s*(DUAL CMP 170HX\s*[—-]\s*)?', '', first).strip()
    return re.sub(rf'^{re.escape(r.name)}\b[:\s—-]*', '', t, flags=re.I) or t or r.name


def print_stats(r: Release) -> dict | None:
    """minutes and grams of the supported slice (slicer-checks.json), plus the fit gauge's for a collector."""
    p = r.path/'slicer-checks.json'
    if not p.exists():
        return None
    sc = json.loads(p.read_text())
    a = sc.get('automatic_supports') or {}
    return dict(minutes=a.get('minutes'), grams=a.get('grams'), gauge=sc.get('fit_gauge'))


def cfd(r: Release) -> dict | None:
    """The CFD run the release's preview page shows: run name, flow (L/s), fans; peak fin rise (K) from that run's
    thermal acceptance when its directory is present and the thermal result was accepted."""
    if not r.preview:
        return None
    m = re.search(r'<script type="application/json" id="airflowData">(.*?)</script>', r.preview.read_text(), re.S)
    a = json.loads(m[1]) if m and m[1].strip() else None
    if not a or not a.get('meta', {}).get('flow_m3s'):
        return None
    meta = a['meta']
    out = dict(run=meta.get('case') or meta.get('label'), flow_lps=meta['flow_m3s']*1000, rpm=meta.get('rpm'), pull_rpm=meta.get('pull_rpm'))
    for root in _run_roots():
        s = root/str(out['run'])/'summary.json'
        if s.exists():
            t = json.loads(s.read_text()).get('thermal_acceptance') or {}
            if t.get('accepted') and t.get('peak_rise_K') is not None:
                out['peak_rise_K'] = t['peak_rise_K']
            break
    return out


def _fans(c: dict) -> str:
    rpm = f"{c['rpm']:.0f}" if c.get('rpm') else ''
    if c.get('pull_rpm'):
        return f"push-pull {rpm}/{c['pull_rpm']:.0f} rpm"
    return f"one fan, {rpm} rpm" if rpm else 'one fan'


def _href(p: Path, out_dir: Path) -> str:
    return html.escape(p.resolve().relative_to(out_dir.resolve()).as_posix(), quote=True)


def _stats_html(r: Release) -> str:
    s = print_stats(r)
    if not s or s['minutes'] is None:
        return ''
    h, m = divmod(round(s['minutes']), 60)
    return f'<div class="stat"><b>{h} h {m:02d}</b><span>print</span></div><div class="stat"><b>{s["grams"]:.0f} g</b><span>PETG</span></div>'


def _cfd_html(r: Release) -> str:
    c = cfd(r)
    if not c:
        return '<p class="muted">No CFD on this release page yet.</p>'
    rise = f'<div class="stat"><b>{c["peak_rise_K"]:.1f} K</b><span>peak fin rise</span></div>' if 'peak_rise_K' in c else ''
    return (f'<div class="stats"><div class="stat"><b>{c["flow_lps"]:.1f} L/s</b><span>CFD flow</span></div>{rise}</div>'
            f'<p class="muted">CFD run {html.escape(str(c["run"]))}: {html.escape(_fans(c))}.</p>')


def _downloads(r: Release, out_dir: Path) -> str:
    files = sorted(r.path.glob('*.stl'), key=lambda p: ('fit' in p.name or 'gauge' in p.name, p.name))
    links = [f'<a href="{_href(p, out_dir)}" download>{html.escape(p.name)}</a>' for p in files]
    if (r.path/'PRINT-NOTES.md').exists():
        links.append(f'<a href="{_href(r.path/"PRINT-NOTES.md", out_dir)}">PRINT-NOTES.md</a>')
    return '<div class="files">' + ''.join(links) + '</div>'


UNTESTED = ('<p class="flag"><b>Untested.</b> No exhaust collector has been printed or fitted to a real case yet: '
            'the fit, the seal and the airflow gain are model results only. Print the fit gauge first and check every '
            'measurement in the print notes.</p>')


def _card(slots: int, root: Path, out_dir: Path) -> str:
    duct, coll = latest('duct', slots, root), latest('collector', slots, root)
    if not duct and not coll:
        return ''
    parts = [f'<section class="card"><h2>{html.escape(layout_label(slots))}</h2>']
    if duct:
        preview = (f'<a class="btn primary" href="{_href(duct.preview, out_dir)}">Open the 3D preview →</a>' if duct.preview else '')
        if (flat := duct.path/'preview-flat.html').exists():   # case-view releases: the Fractal bay first, then the flat panel
            preview = (preview.replace('Open the 3D preview →', 'Open the 3D preview · your Fractal case, plug collector (draft) →')
                       + f'<a class="btn" href="{_href(flat, out_dir)}">Flat rear panel · untested collector →</a>')
        parts.append(f'<div class="part"><h3>Duct {html.escape(duct.name.upper())}</h3><p class="lead">{html.escape(headline(duct))}</p>'
                     f'<div class="stats">{_stats_html(duct)}</div>{_cfd_html(duct)}{preview}{_downloads(duct, out_dir)}</div>')
    if coll:
        parts.append(f'<div class="part"><h3>Exhaust collector {html.escape(coll.name.removeprefix("collector-"))}</h3>'
                     f'<p class="lead">{html.escape(headline(coll))}</p>{UNTESTED}<div class="stats">{_stats_html(coll)}</div>{_downloads(coll, out_dir)}</div>')
    else:
        parts.append('<div class="part"><h3>Exhaust collector</h3><p class="muted">None for this layout yet.</p></div>')
    return ''.join(parts)+'</section>'


def _own_case(root: Path, out_dir: Path) -> str:
    """Parts made for the author's own case (releases/fractal-*): its slot bay is recessed, so the flat-panel
    collectors in the layout cards don't fit it."""
    dirs = sorted(d for d in Path(root).glob('fractal-*') if d.is_dir())
    if not dirs:
        return ''
    parts = ['<section class="card"><h2>Your case: Fractal, recessed slot bay</h2>'
             '<p class="muted">The exhaust collectors in the layout cards below need a flat rear panel and don\'t fit'
             ' this case. Its collector plugs into the recess over the two cards and the middle slot, leaving slots 1 and 7 open;'
             ' print the fit gauge first.</p><p class="flag"><b>Untested draft.</b> The plug collector is sized from photos;'
             ' it has not been printed or fitted, and it is not released until the gauge and the bay measurements confirm it.</p>']
    for d in dirs:
        r = Release(d.name, 'collector', 5, 0, d)
        parts.append(f'<div class="part"><h3>{html.escape(d.name)}</h3><p class="lead">{html.escape(headline(r))}</p>'
                     f'<div class="stats">{_stats_html(r)}</div>{_downloads(r, out_dir)}</div>')
    return ''.join(parts)+'</section>'


def _older(rs: list[Release], out_dir: Path) -> str:
    rows = []
    for r in rs:
        s = print_stats(r)
        stats = f'{round(s["minutes"])} min · {s["grams"]:.0f} g' if s and s['minutes'] is not None else ''
        links = ([f'<a href="{_href(r.preview, out_dir)}">preview</a>'] if r.preview else []) + \
                [f'<a href="{_href(r.stl, out_dir)}" download>STL</a>'] + \
                ([f'<a href="{_href(r.path/"PRINT-NOTES.md", out_dir)}">notes</a>'] if (r.path/'PRINT-NOTES.md').exists() else [])
        rows.append(f'<li><div><b>{html.escape(r.name)}</b> <span class="muted">{html.escape(headline(r))}</span>'
                    f'<div class="meta">{html.escape(layout_label(r.slots, True))}{" · "+stats if stats else ""}</div></div>'
                    f'<div class="links">{"".join(links)}</div></li>')
    return '<ul class="older">' + ''.join(rows) + '</ul>'


CSS = """
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;color:#e9eef4;background:#10151c}
*{box-sizing:border-box}body{margin:0;background:#10151c;-webkit-text-size-adjust:100%}
header{padding:22px 16px 16px;border-bottom:1px solid #2a3441}header>*{max-width:1080px;margin-left:auto!important;margin-right:auto!important}h1{font-size:21px;letter-spacing:-.3px;margin:0}
header p{margin:6px 0 0;color:#9caebf;font-size:14px;line-height:1.5}
main{padding:16px;max-width:1080px;margin:0 auto}
.cards{display:grid;gap:16px}
.card{border:1px solid #2f3c4b;border-radius:14px;background:#151c25;padding:16px}
.card h2{margin:0 0 4px;font-size:18px;letter-spacing:-.2px}
.part{border-top:1px solid #2a3441;margin-top:14px;padding-top:14px}.card h2+.part{border-top:0;margin-top:6px;padding-top:6px}
h3{margin:0;font-size:15px;color:#d6e7f6}.lead{margin:4px 0 10px;color:#b8c8d8;font-size:14px;line-height:1.45}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}.stats:empty{display:none}
.stat{background:#1b2430;border:1px solid #2a3441;border-radius:9px;padding:7px 11px;min-width:84px}
.stat b{display:block;font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}.stat span{font-size:11.5px;color:#9caebf}
.flag{margin:4px 0 10px;padding:8px 11px;border:1px solid #8a6a1f;border-radius:9px;background:#2a2212;color:#f1d58e;font-size:13px;line-height:1.5}
.muted{color:#8fa2b5;font-size:13px;line-height:1.5;margin:4px 0 10px}
.btn{display:flex;align-items:center;justify-content:center;min-height:44px;border-radius:10px;text-decoration:none;font-weight:600;font-size:15px;margin:10px 0}
.btn.primary{background:#d6e7f6;color:#142332}.btn.primary:hover{background:#eaf4fc}
.btn:not(.primary){border:1px solid #3b4a5c;color:#dce7f2;font-size:14px}.btn:not(.primary):hover{background:#1f2a36}
.files{display:flex;flex-wrap:wrap;gap:6px}.files a{display:inline-flex;align-items:center;min-height:36px;padding:6px 10px;border:1px solid #33414f;border-radius:8px;color:#9fd2ff;font-size:12.5px;text-decoration:none;overflow-wrap:anywhere}
.files a:hover,.links a:hover{background:#1f2a36}
h2.section{font-size:15px;margin:28px 0 8px;color:#b8c8d8}
.older{list-style:none;margin:0;padding:0;border:1px solid #2a3441;border-radius:12px;overflow:hidden}
.older li{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;justify-content:space-between;padding:10px 12px;border-top:1px solid #222c38;font-size:14px}
.older li:first-child{border-top:0}.older .muted{font-size:13px;margin:0}.older .meta{font-size:12px;color:#8597a9;margin-top:2px}
.links{display:flex;gap:4px}.links a{display:inline-flex;align-items:center;min-height:36px;padding:0 10px;border-radius:8px;color:#9fd2ff;font-size:13px;text-decoration:none}
footer{padding:20px 16px 32px;color:#6f8396;font-size:12px;text-align:center}
@media (min-width:760px){header{padding:26px 30px 20px}h1{font-size:23px}main{padding:22px 30px}.cards{grid-template-columns:1fr 1fr}}
"""


def write_index(out_html=None, root: Path = RELEASES) -> Path:
    """Write the landing page (default releases/index.html); links are relative to it, so out_html must be inside root."""
    root = Path(root)
    out = Path(out_html) if out_html else root/'index.html'
    out_dir = out.resolve().parent
    rs = releases(root)
    cards = ''.join(_card(n, root, out_dir) for n in LAYOUTS)
    shown = {r.name for n in LAYOUTS for r in (latest('duct', n, root), latest('collector', n, root)) if r}
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#10151c"><title>Dual 170HX releases</title><style>{CSS}</style></head>
<body><header><h1>Dual 170HX · 120 mm duct</h1><p>Two CMP 170HX cards, one ARCTIC P12 Pro PST CO. Pick the card spacing in your case: one empty slot between the cards (5 slots), or adjacent cards (4 slots).</p></header>
<main>{_own_case(root, out_dir)}<div class="cards" style="margin-top:16px">{cards}</div>
<h2 class="section">Older releases</h2>{_older([r for r in rs if r.name not in shown], out_dir)}</main>
<footer>Generated by <code>duct index</code> from releases/.</footer></body></html>
"""
    out.write_text(page)
    return out


if __name__ == '__main__':
    print(write_index())
