"""Porous fin zones: a Shah–London laminar rectangular-channel model per card port. SI units.

Each port box is a bank of straight fins along z. The main vent holds the 27-channel heatsink;
the side vents are modelled as 7-channel banks. The model yields anisotropic Darcy–Forchheimer
coefficients (axial only; transverse flow blocked) and the volumetric fin–air conductance Hvol
that chtFinBase uses.
"""
import math
from dataclasses import dataclass

from ..params import GeometryParams

AIR_K = .026      # W/m/K
COPPER_K = 380.0  # W/m/K, fin material


def channel(n: int, w: float, h: float, t: float, K: float, length: float) -> dict[str, float]:
    """n channels across width w between n+1 fins of thickness t and height h; K: entry+exit loss coefficient."""
    gap = (w-(n+1)*t)/n; eps = n*gap/w; dh = 2*gap*h/(gap+h); a = min(gap, h)/max(gap, h)
    Po = 96*(1-1.3553*a+1.9467*a*a-1.7012*a**3+.9564*a**4-.2537*a**5)
    Nu = 7.541*(1-2.610*a+4.970*a*a-5.119*a**3+2.702*a**4-.548*a**5)
    hc = Nu*AIR_K/dh; m = (2*hc/(COPPER_K*t))**.5; eta = math.tanh(m*h)/(m*h)
    area_density = (2*n*h*eta+n*gap)/(w*h)
    return dict(gap=gap, porosity=eps, dh=dh, D=Po/(2*dh*dh*eps), F=K/(length*eps*eps), h=hc, Hvol=hc*area_density, fin_eta=eta)


@dataclass(frozen=True)
class FinModel:
    channels: tuple[int, ...] = (27, 7, 7)     # per fin port (main, lower side, upper side)
    loss_K: tuple[float, ...] = (2.5, 4.0, 4.0)
    fin_thickness: float = .00045
    start: float = .008                        # porous zone starts this far past the seat face
    length: float = .230
    resistance: float = 1.0                    # scales D and F in porosityProperties
    heat_scale: float = 1.0                    # scales the thermal Hvol
    port_coupling: tuple[float, ...] = (1.0, 1.0, 1.0)  # connected fraction of each bank's effective area

    def __post_init__(self):
        if len(self.port_coupling) != len(self.channels) or any(
                not math.isfinite(v) or not 0 <= v <= 1 for v in self.port_coupling):
            raise ValueError('port_coupling must have one finite fraction in [0, 1] per port')


FINS = FinModel()


def zones(g: GeometryParams, f: FinModel = FINS) -> list[dict]:
    """Per (card, port): name, box (m) and unscaled channel coefficients. The bank width runs along y, height along x.

    Port sizes are rounded to 1e-9 mm before scaling so float noise in the mm differences doesn't
    reach the coefficients (both cards identical, bit-equal to the old builder's literals)."""
    out = []
    z0 = g.chamber_length*.001+f.start
    for card, port, (x0, x1, y0, y1) in g.port_boxes:
        px0, px1, py0, py1 = g.fin_ports[port]
        w, h = round(py1-py0, 9)*.001, round(px1-px0, 9)*.001
        par = channel(f.channels[port], w, h, f.fin_thickness, f.loss_K[port], f.length)
        out.append(dict(zone=f"card{card}path{port}", side=card, path=port,
                        box=[[x0*.001, y0*.001, z0], [x1*.001, y1*.001, z0+f.length]], **par))
    return out


def thermal_hvol(zs: list[dict], f: FinModel = FINS) -> float:
    """Legacy scalar main-path coefficient; retained for old case dictionaries."""
    return zs[0]["Hvol"]*f.heat_scale


def thermal_path_hvol(zs: list[dict], f: FinModel = FINS) -> list[float]:
    """h times each port's fin-efficiency-weighted area per gross volume.

    The connected fraction scales thermal exchange only, including the exposed base
    area in channel(). It does not allocate extra GPU power or change flow resistance.
    Full coupling is the nominal connected-fin-bank assumption; (1, 0, 0) is legacy.
    See docs/thermal-side-ports.md for the hardware uncertainty.
    """
    return [z['Hvol']*f.heat_scale*f.port_coupling[z['path']] for z in zs if z['side'] == 0]


# Bracket grille: each card's exit vent as a thin perforated plate. The real vent pattern is
# unknown; 65 % open area is mid-range for stamped PCIe bracket vents (round-hole and hex patterns run ~50-70 %).
GRILLE_OPEN_AREA = .65


def perforated_plate_k(open_area: float) -> float:
    """Loss coefficient of a thin sharp-edged perforated plate, referred to the approach (superficial) velocity:
    K = (0.707·(1-f)^0.375 + 1 - f)² / f², Idelchik, Handbook of Hydraulic Resistance, 3rd ed., diagram 8-1
    (Re_hole > 1e5; lower hole Reynolds numbers raise K somewhat). f = 1 gives 0."""
    assert 0 < open_area <= 1, open_area
    f = open_area
    return (.707*(1-f)**.375+1-f)**2/f**2
