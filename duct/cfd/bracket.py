"""The cards' rear brackets: a solid plate on the bracket plane (z = L + card_envelope) with one open window per card.

From the author's photos of the CMP 170HX bracket (coordinator's estimate from a near-frontal photo scaled by the
120.02 mm full-height bracket, ±10 %, measurement pending): one rectangular window behind a bezel, the fin ends
visible through it; ≈81 mm along the card height (y) × 25 mm across the slot thickness (x), starting ≈8 mm below
the bracket's top edge; across the ≈36 mm bracket it sits ≈3 mm from one long edge and ≈8 mm from the other, the
PCB side unknown. Here the window is centred on each card's fin-port span in x (x_offset 0; ±2.5 mm reproduces
the 3/8 mm edge split either way). The bracket top is duct y = 52.35 mm (CollectorParams.bracket_top_y: CEM
Fig 10-2 and PB-10577 Fig 3).

The ports stop `thickness` short of the bracket plane; a window prism through the plate joins them to what is
downstream: the push-pull collector, or (no collector) a box of still air behind the bracket with a far-field
`exhaust` patch at ambient pressure, so the solver resolves the contraction and the free jet itself.

The case's rear panel (duct.cad.hardware CaseParams, `panel`): the bracket plate rests against the panel's inner face
(hardware.py stack: bracket [z - sheet, z], panel [z, z + panel], no gap), and each card's window straddles the
steel rib between its two chassis slot openings (13.25 mm at 20.32 mm pitch, CEM Fig 9-22). So the panel is a second
plate, `panel` thick, flush on the bracket plate's outer face, open only where the window meets an opening: two
strips per card (window ∩ hardware.openings). The collector's flange and the still-air room start on its outer face.
"""
from dataclasses import dataclass, replace

import manifold3d as mf
import numpy as np

from ..cad import hardware
from ..cad.geometry import cube
from ..params import CollectorParams, GeometryParams
from .domain import DOMAIN, TOL, DomainParams, Rule

BRACKET_TOP_Y = CollectorParams.bracket_top_y  # mm, duct frame


@dataclass(frozen=True)
class BracketWindow:
    length: float = 81.0                # mm, along y (card height)
    width: float = 25.0                 # mm, along x (slot thickness)
    top_offset: float = 8.0             # mm, window top below the bracket top edge
    x_offset: float = 0.0               # mm, window centre from the card's port-span centre, +x
    thickness: float = 1.0              # mm, bracket sheet
    top_y: float = BRACKET_TOP_Y        # mm, bracket top edge (screw-tab end) in duct y
    refine: int = 2                     # snappy level in a box around the windows (1 mm cells at base 4); V23 1 fan:
                                        # Q 10.79 / 10.36 / 10.23 L/s at levels 1 / 2 / 3 (extrapolated ~10.17)
    room_margin: float = 20.0           # mm, still-air box behind the bracket beyond the windows (no collector)
    room_depth: float = 40.0            # mm
    panel: hardware.CaseParams | None = hardware.CASE   # rear panel flush downstream (thickness, slot openings);
                                                        # None: the windows open straight past the plate (runs before the panel)

    @property
    def panel_thickness(self) -> float:
        """mm from the bracket plane to the panel's outer face (where the collector flange and the room start)."""
        return self.panel.panel if self.panel is not None else 0.0

    def rect(self, g: GeometryParams, card: int) -> tuple[float, float, float, float]:
        """(x0, x1, y0, y1) of a card's window, mm."""
        xs = [x for c, _, (x0, x1, _, _) in g.port_boxes if c == card for x in (x0, x1)]
        xc = (min(xs)+max(xs))/2+self.x_offset
        y1 = self.top_y-self.top_offset
        return xc-self.width/2, xc+self.width/2, y1-self.length, y1


BRACKET = BracketWindow()


def windows(g: GeometryParams, b: BracketWindow) -> list[tuple[float, float, float, float]]:
    return [b.rect(g, card) for card in range(len(g.card_x))]


def openings(g: GeometryParams, b: BracketWindow) -> list[list[tuple[float, float, float, float]]]:
    """Per card, the panel's open strips behind its window (x0, x1, y0, y1): window ∩ each chassis slot opening
    (duct.cad.hardware.openings, in the collector frame with the duct's card pitch). No panel: the whole window."""
    if b.panel is None:
        return [[w] for w in windows(g, b)]
    ops = hardware.openings(replace(CollectorParams(), card_pitch=g.pitch), b.panel.for_pitch(g.pitch)).values()
    out = []
    for x0, x1, y0, y1 in windows(g, b):
        rects = [(max(x0, a), min(x1, e), max(y0, c), min(y1, d)) for a, e, c, d in ops]
        out.append([r for r in rects if r[1]-r[0] > 1e-9 and r[3]-r[2] > 1e-9])
    return out


def open_area(g: GeometryParams, b: BracketWindow) -> list[float]:
    """Open exhaust area per card, mm²: the panel strips (or the bare window without a panel)."""
    return [sum((x1-x0)*(y1-y0) for x0, x1, y0, y1 in card) for card in openings(g, b)]


def bounds(g: GeometryParams, b: BracketWindow, margin: float) -> tuple[float, float, float, float]:
    r = np.array(windows(g, b))
    return r[:, 0].min()-margin, r[:, 1].max()+margin, r[:, 2].min()-margin, r[:, 3].max()+margin


def parts(g: GeometryParams, b: BracketWindow, d: DomainParams = DOMAIN,
          room: bool = True) -> tuple[tuple[mf.Manifold, ...], tuple[Rule, ...]]:
    """Window prisms through the plate, the panel's open strips past it (plus the still-air box behind the panel when
    `room`), and patch rules: the box's sides and far face -> exhaust; every face from the bracket plane to the
    panel's outer face (the rib behind each window, the strip sides facing it, the box floor) -> walls. The ports' cut
    ends (the plate's inner face) fall to the default walls; the window sides, and the strip sides flush with them
    (one face through plate and panel), to cardWalls."""
    z = g.chamber_length+d.card_envelope; zp = z+b.panel_thickness
    solids = tuple(cube([x1-x0, y1-y0, b.thickness+.005], [x0, y0, z-b.thickness-.005]) for x0, x1, y0, y1 in windows(g, b))
    if b.panel is not None:
        solids += tuple(cube([x1-x0, y1-y0, zp-z+.005], [x0, y0, z-.005]) for card in openings(g, b) for x0, x1, y0, y1 in card)
    zm, zpm = z*.001, zp*.001
    rules = (("walls", lambda t: (t[:, :, 2].min(1) > zm-TOL) & (t[:, :, 2].max(1) < zpm+TOL)),)
    if not room:
        return solids, rules
    x0, x1, y0, y1 = bounds(g, b, b.room_margin)
    solids += (cube([x1-x0, y1-y0, b.room_depth], [x0, y0, zp]),)
    return solids, (("exhaust", lambda t: t[:, :, 2].max(1) > zpm+TOL),)+rules


def refinement(g: GeometryParams, b: BracketWindow, d: DomainParams = DOMAIN) -> tuple[list[float], list[float]]:
    """Refinement box (m) around both windows: the plate edges, the contraction upstream and the jet's start."""
    z = g.chamber_length+d.card_envelope
    x0, x1, y0, y1 = bounds(g, b, 3.0)
    return [x0*.001, y0*.001, (z-6)*.001], [x1*.001, y1*.001, (z+6)*.001]


def contraction_coefficient(f: float) -> float:
    """Jet contraction coefficient of a thin sharp-edged orifice for area ratio f = A_window/A_approach:
    ε = 0.57 + 0.043/(1.1 - f) (Idelchik, Handbook of Hydraulic Resistance, 3rd ed., ch. 4, thin-walled orifice)."""
    return 0.57+0.043/(1.1-f)


def exit_loss_heads(f: float) -> float:
    """Total-pressure loss of a sharp-edged window exhausting to free space, in approach velocity heads: the whole
    vena-contracta jet head, (1/(ε f))² (no loss accelerating into the contraction, the jet's head lost outside)."""
    return 1/(contraction_coefficient(f)*f)**2


def plenum_loss_heads(f: float, f_plenum: float) -> float:
    """The same window discharging into a plenum (f_plenum = A_approach/A_plenum): Borda-Carnot expansion from the
    vena contracta to the plenum velocity, (1/(ε f) - f_plenum)², in approach velocity heads."""
    return (1/(contraction_coefficient(f)*f)-f_plenum)**2
