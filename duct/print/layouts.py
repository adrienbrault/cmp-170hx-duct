"""Slot layouts of the released designs, derived from the releases directory and the presets (no hand-kept table).

A duct release is releases/<name>/dual-170hx-continuous-<name>.stl with a preset of that name; its slot layout follows
the preset's card pitch (duct.params.slot_layout): 60.96 mm spans 5 slots (one empty between the cards), 40.64 mm spans
4 (adjacent cards). A collector release is releases/collector-v<N>[-<n>slot]/; without a suffix it is for 5 slots
(v1-v3 predate the 4-slot layout). Designs of the same generation share their number across layouts: v29 / a29,
collector-v4-5slot / collector-v4-4slot. The preview's layout switcher and releases/index.html are built from this.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASES = ROOT/'releases'


@dataclass(frozen=True)
class Release:
    name: str            # release directory: v29, a29, collector-v4-5slot
    kind: str            # 'duct' or 'collector'
    slots: int           # slots the two cards span: 5 or 4
    number: int          # design generation: 29, 4
    path: Path

    @property
    def layout_label(self) -> str:
        return layout_label(self.slots)

    @property
    def stl(self) -> Path:
        return self.path/(f'dual-170hx-continuous-{self.name}.stl' if self.kind == 'duct' else f'dual-170hx-{self.name}.stl')

    @property
    def preview(self) -> Path | None:
        p = self.path/'preview.html'
        return p if p.exists() else None


def layout_label(slots: int, short: bool = False) -> str:
    """'5-slot · one empty slot', '4-slot · adjacent' (short: '5-slot · 1 empty', for phones)."""
    empty = slots-4
    if short: return f"{slots}-slot · " + ('adjacent' if empty == 0 else f'{empty} empty')
    return f"{slots}-slot · " + ('adjacent' if empty == 0 else 'one empty slot' if empty == 1 else f'{empty} empty slots')


def _duct_slots(name: str) -> int | None:
    from ..params import PRESETS, slot_layout
    g = PRESETS.get(name)
    return len(slot_layout(g.pitch)['span']) if g else None


def releases(root: Path = RELEASES) -> list[Release]:
    """Every duct and collector release under root, newest generation first (ducts before collectors)."""
    out = []
    for d in sorted(Path(root).iterdir()) if Path(root).exists() else []:
        if not d.is_dir():
            continue
        if (d/f'dual-170hx-continuous-{d.name}.stl').exists() and (m := re.fullmatch(r'[a-z]+(\d+)', d.name)):
            slots = _duct_slots(d.name)
            if slots:
                out.append(Release(d.name, 'duct', slots, int(m[1]), d))
        elif (m := re.fullmatch(r'collector-v(\d+)(?:-(\d)slot)?', d.name)) and (d/f'dual-170hx-{d.name}.stl').exists():
            out.append(Release(d.name, 'collector', int(m[2] or 5), int(m[1]), d))
    return sorted(out, key=lambda r: (r.kind != 'duct', -r.number, -r.slots))


def latest(kind: str, slots: int, root: Path = RELEASES) -> Release | None:
    return next((r for r in releases(root) if r.kind == kind and r.slots == slots), None)


def siblings(name: str, root: Path = RELEASES) -> list[Release]:
    """The design `name` and its counterparts in the other slot layouts (same kind and generation), 5-slot first;
    [] when it has none (older designs exist in one layout only)."""
    rs = releases(root)
    me = next((r for r in rs if r.name == name), None)
    if me is None:
        return []
    same = [r for r in rs if r.kind == me.kind and r.number == me.number]
    return sorted(same, key=lambda r: -r.slots) if len(same) > 1 else []


def layout_links(name: str, out_html, root: Path = RELEASES) -> list[dict]:
    """Switcher entries for the preview page of release `name` written to out_html: {label, short, href, current}; hrefs are
    relative to out_html and point at each sibling's page of the same name (e.g. preview-flat.html: the same case view)
    when it has one (duct.viz.web.release_pages), else at its preview.html."""
    from ..viz.web import release_pages
    out = Path(out_html); here = out.resolve().parent
    page = lambda r: r.path/out.name if r.name == name or out.name in release_pages(r.name) else r.path/'preview.html'  # noqa: E731
    return [dict(label=r.layout_label, short=layout_label(r.slots, True), href=Path(os.path.relpath(page(r).resolve(), here)).as_posix(), current=r.name == name)
            for r in siblings(name, root)]
