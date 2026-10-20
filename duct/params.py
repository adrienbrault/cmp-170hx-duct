"""Geometric inputs of the duct. Dimensions in mm; x across the cards, y along them, z from the fan face."""
import ast
from dataclasses import dataclass, fields, replace

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class GeometryParams:
    # Layout
    pitch: float = 60.96                 # card centre-to-centre spacing: 3 slots (one empty slot between the cards); 40.64 = 2 slots (adjacent)
    chamber_length: float = 70.0         # fan face to GPU seating face (L)
    fan_thickness: float = 25.0          # fan front to duct inlet (reported only)

    # Fan plate
    fan_radius: float = 58.4             # fan aperture
    fan_plate: float = 120.0             # square plate; also the outer envelope
    fan_plate_corner_radius: float = 5.0
    flange_thickness: float = 2.4
    fan_hole_offset: float = 52.5        # screw holes at (±offset, ±offset)
    fan_hole_radius: float = 2.25

    # GPU seat: bore, reinforcing collar, lead-in chamfer and power notch
    bore: tuple[float, float] = (38.5, 98.5)
    collar_length: float = 12.0
    collar_wall: float = 1.6
    lead_in_z: tuple[float, float] = (11.4, 12.05)        # above the seat face
    lead_in_bore: tuple[float, float] = (38.9, 98.9)      # bore at lead_in_z[1]
    power_notch: tuple[float, float] = (-3.25, 26.5)      # notch inner x (from card centre), lower y

    # Passage shell
    skin_wall: float = 1.6
    wall_dilation: float = 1.62          # 3-D kernel inradius of the outer shell
    loft_origin_dx: float = 3.0          # polar origin of each branch loft, from card centre

    # Central splitter: elliptical nose, cubic widening to the outlets
    nose_tip_half_width: float = 0.2
    nose_radius_x: float = 0.8
    nose_radius_z: float = 1.6
    splitter_blend_width: float = 12.0   # x band over which the splitter reshapes the section

    # Connector service bay (cable pocket) and its rounded shoulder
    bay_wall_x: float = -0.25            # bay side wall x, from card centre, before narrowing
    bay_wall_narrowing: float = 3.0      # bay wall moves outward by this much ...
    bay_narrow_start: float = 12.0       # ... starting this far below the seat ...
    bay_narrow_length: float = 10.0      # ... over this length
    bay_floor_y: float = 24.9            # bay floor y at the pocket transition end
    bay_ramp_ease: float = 0.06          # ramp end-easing fraction of the bay floor
    pocket_transition: float = 26.0      # bay floor reaches bay_floor_y this far below the seat
    shoulder_radius: float = 10.0        # bay shoulder radius ...
    shoulder_radius_drop: float = 3.0    # ... reduced by this much ...
    shoulder_taper_start: float = 22.0   # ... from this z to the pocket transition end
    shoulder_ease: float = 15.0          # shoulder radius grows from 0 over this z

    # Passage-floor fillet (lower bay corner)
    passage_radius: float = 8.0
    passage_radius_drop: float = 2.0     # reduced over the last passage_taper mm
    passage_taper: float = 15.0
    passage_ease: float = 12.0
    passage_floor_ratio: float = 1.3     # radius <= floor length / ratio

    # Upper-shoulder fillet
    upper_radius: float = 6.0
    upper_outlet_radius: float = 1.5     # tapers to min(this, upper_radius) at the seat
    upper_outlet_taper: float = 20.0
    upper_ease: float = 18.0
    upper_room_ratio: float = 2.5        # radius <= available height / ratio

    # Integral connector returns and service clearances; rects are (x from card centre, y, w, h)
    return_depth: float = 8.0
    return_top_depth: float = 3.2        # air-passage slices protected from the returns
    return_ramp_slope: float = 0.85      # underside lateral advance per mm of height
    return_rect: Rect = (-20.85, 24.9, 19.2, 25.95)
    access_cut: Rect = (-21.0, 27.2, 15.05, 24.0)     # open outer/top rim of each return
    housing_clear: Rect = (-19.55, 27.2, 13.6, 20.6)
    latch_clear: Rect = (-6.55, 33.2, 3.6, 8.6)
    plug: Rect = (-19.25, 27.5, 13.0, 20.0)           # estimated connector housing
    latch: Rect = (-6.25, 33.5, 3.0, 8.0)
    sweep_start: float = 26.0            # straight plug insertion sweep starts this far below the seat
    sweep_length: float = 38.0

    # Card fin-flow ports, (x0, x1, y0, y1) from the card centre: main vent, lower and upper side vents
    fin_ports: tuple[Rect, ...] = ((-5.4, 17.8, -47.4, 47.4), (-17.6, -8.0, -44.5, -13.0), (-17.6, -8.0, -10.5, 22.5))

    # V24 uniform-wall shell and outside blends (zero/off reproduces V23)
    shell_from_air: float = 0.0          # 1: the shell dilates the rounded air volume, so the outer skin follows every inside fillet
    kernel_segments: float = 16.0        # circular segments of the dilation sphere
    shell_simplify: float = .005         # simplification tolerance of the dilated volume (finer: fewer facet streaks, slower)
    section_radius: float = 0.0          # every convex air-section corner rounded to at least this (longitudinal edges) ...
    section_ease: float = 12.0           # ... growing from 0 at the fan face over this z ...
    outlet_fade: float = 24.0            # ... and fading out over this many mm before the returns
    skin_fillet_fade: float = 10.0       # the shell stops following the bay fillets over this many mm before the returns
    splitter_round_length: float = 20.0  # corners beside the splitter stay sharp while it is one solid web, then round over this z
    splitter_groove_radius: float = 0.0  # the web stays solid until the skins part by twice this (no knife-edge groove)
    fillet_smoothing: float = 0.0        # smooth the room-limited bay fillet radii along z over this length (mm)
    return_round: float = 0.0            # inside-corner radius of the connector-return outline (convex corners: half)
    flange_fillet: float = 0.0           # outside fillet radius between the fan plate and the body
    return_frame: float = 0.0            # 1 (V27): the skin follows the bay fillets to the seat, and each return is only the seat frame (collar
                                         # footprint and pocket-floor lip) beyond that rounded shell, with a return_ramp_slope underside
    seat_seal: float = 0.0               # 1 (V28, with return_frame): the seat also covers the card face over the fin stack beside each plug
                                         # pocket (bore - passage - plug/latch clearance): open fin-channel ends there leak

    # Hub fairing behind the push fan (docs/push-aero-plan.md, refinement 1); off reproduces V23-V29 and A29
    hub_fairing: float = 0.0             # 1: a wall_dilation shell of revolution on the fan axis, its base on the fan face, open toward
                                         # the fan (the dead air behind the hub becomes its cavity); the splitter web / shared wall carries it
    hub_fairing_d: float = 50.5          # base outer diameter: the rim lands on the fan's flat rear motor-housing face, about 52 mm across
                                         # (P12 Pro PST CO photo, +-1 mm; duct/cfd/fan.py's 50.3 mm is the front cap)
    hub_fairing_angle: float = 44.0      # steepest flank from vertical: the cavity closes on the axis at this angle (printed fan face down,
                                         # its ceiling is the only overhang)
    hub_fairing_power: float = 1.35      # cavity radius Rc (1 - t^p), t = z / cavity length; Rc = base radius - wall

    # Export
    export_tolerances: tuple[float, ...] = (0.01, 0.02)
    fit_check_height: float = 2.0        # fit gauge: everything above L + this

    def __post_init__(self):
        assert 55 <= self.chamber_length <= 75, "Use a chamber length between 55 and 75 mm"
        assert self.pitch > self.bore[0], "the card bores overlap"

    @property
    def card_x(self) -> tuple[float, float]:
        return (-self.pitch / 2, self.pitch / 2)

    @property
    def shared_wall(self) -> float:
        """Divider between the two bores: 0 when each card has its own inner collar wall (3-slot pitch), else the bore gap
        (pitch - bore width) that the two inner collar walls merge into, one wall that is both cards' inner collar."""
        gap = self.pitch-self.bore[0]
        return gap if gap < 2*self.collar_wall else 0.0

    @property
    def port_boxes(self) -> list[tuple[int, int, Rect]]:
        """(card, port, (x0, x1, y0, y1)) in absolute x."""
        return [(i, j, (cx + x0, cx + x1, y0, y1)) for i, cx in enumerate(self.card_x)
                for j, (x0, x1, y0, y1) in enumerate(self.fin_ports)]


V23 = GeometryParams()
V24 = replace(V23, shell_from_air=1.0, kernel_segments=32.0, shell_simplify=.002, wall_dilation=1.6, section_radius=6.0, splitter_groove_radius=0.15, flange_fillet=3.5, fillet_smoothing=3.0, return_round=0.8,
              return_rect=(-20.85, 24.9, 19.5, 25.95))   # returns reach 0.3 mm into the shell: no tangent seam at its top
V25 = replace(V24, wall_dilation=1.2, collar_wall=1.2)  # three 0.4 mm perimeters instead of four
V27 = replace(V25, return_frame=1.0)   # the skin follows the bay fillets to the seat; returns are only the chamfered seat frame
V28 = replace(V27, seat_seal=1.0, chamber_length=62.0,  # sealed seat beside the plug pockets; 8 mm shorter, the bay floor ramp stays ~45 deg with the 26 mm plug sweep
              export_tolerances=(0.004, 0.01, 0.02))  # at 0.005+ simplification pulls the splitter web's ends 20 um off the fan-aperture rim
# V29: the latch notch shaped to the lever. Molex Mini-Fit Jr 5557 (9.6 mm body, 11.6 mm over the latch) in the card housing's
# 6.0 mm latch notch: the pad 0.4 mm proud of the housing plus 1.2 mm hook swing to unlatch, 0.3 mm clearance (V23-V28: a 3 x 8 mm
# estimate). Export: 0.0028-0.006 leave a 3-edge T-junction crack at card B's seal ramp, 0.008+ the fan-rim sliver.
V29 = replace(V28, latch=(-6.25, 34.2, 1.6, 6.6), latch_clear=(-6.55, 33.9, 2.2, 7.2), export_tolerances=(0.0025, 0.002))

# Two families, by the slot pitch between the cards:
#   V* (v23-v30): one empty slot between the cards (3-slot pitch, 60.96 mm), e.g. slots 1-2 and 4-5;
#   A* (a29-a30): adjacent cards in four consecutive slots (2-slot pitch, 40.64 mm), e.g. slots 1-2 and 3-4.
# A29 is V29 at the 2-slot pitch. The bores (38.5 mm fit envelope) are 2.14 mm apart, so the two inner collar walls
# merge into one shared 2.14 mm divider (GeometryParams.shared_wall) that seats between the cards and is also the
# splitter web, solid from the fan face to the collar top.
A29 = replace(V29, pitch=40.64)
# V30 / A30: V29 / A29 with the hub fairing, a 1.2 mm ogive shell behind the push fan's motor hub (hub_fairing_d 50.5 mm
# against a measured ~52 mm rear hub face: the rim lands 0.75 mm inside its edge). See docs/push-aero-plan.md for the CFD matrix.
V30 = replace(V29, hub_fairing=1.0)
A30 = replace(A29, hub_fairing=1.0)


def _coerce(name: str, value):
    """Every parameter is a float or a (nested) tuple of floats."""
    if name not in {f.name for f in fields(GeometryParams)}:
        raise KeyError(f"unknown geometry parameter {name!r}")
    floats = lambda v: tuple(map(floats, v)) if isinstance(v, (list, tuple)) else float(v)  # noqa: E731
    return floats(value)


PRESETS = {"v23": V23, "v24": V24, "v25": V25, "v27": V27, "v28": V28, "v29": V29, "a29": A29, "v30": V30, "a30": A30}


def from_toml(data: dict, base: GeometryParams = V23) -> GeometryParams:
    """Override `base` with a flat mapping, e.g. the [geometry] table of duct.toml."""
    return replace(base, **{k: _coerce(k, v) for k, v in data.items()})


def parse_overrides(items: list[str], base: GeometryParams = V23) -> GeometryParams:
    """Apply CLI `k=v` strings; values are Python literals (`upper_radius=3`, `bore=(39,99)`)."""
    pairs = dict(item.split("=", 1) for item in items)
    return from_toml({k.strip(): ast.literal_eval(v.strip()) for k, v in pairs.items()}, base)


def _slot(v: float):
    """Slot position as an int when it is one (the 3-slot pitch: -3 ... 3), else the half-integer float (2-slot: +-0.5 ...)."""
    return int(v) if v == int(v) else v


def slot_layout(card_pitch: float, slot_pitch: float = 20.32) -> dict:
    """Expansion-slot layout of two dual-slot cards at `card_pitch` (GeometryParams.pitch), in slot pitches from the midpoint
    between the cards (x = 0): 'cards' = each card's two slots, 'span' = card A's first to card B's last slot (what a
    collector over both cards covers), 'slots' = the span plus one neighbour each side (the case model's slots).

    3-slot pitch (60.96, one empty slot between the cards): cards (-2, -1) / (1, 2), span -2 ... 2, slots -3 ... 3.
    2-slot pitch (40.64, adjacent cards): cards (-1.5, -0.5) / (0.5, 1.5), span -1.5 ... 1.5, slots -2.5 ... 2.5."""
    n = round(card_pitch/slot_pitch*2)/2
    assert n >= 2 and n == int(n) and abs(card_pitch-n*slot_pitch) < 1e-6, f'card pitch {card_pitch} is not a whole number (>= 2) of {slot_pitch} mm slots'
    a = -n/2                                             # card A's centre, in slot pitches
    span = tuple(a-.5+i for i in range(int(n)+2))
    return dict(cards=((_slot(a-.5), _slot(a+.5)), (_slot(-a-.5), _slot(-a+.5))), span=span,
                slots=tuple(_slot(v) for v in (span[0]-1, *span, span[-1]+1)))


@dataclass(frozen=True)
class CollectorParams:
    """Push-pull exhaust collector over the rear slot brackets (duct/cad/exhaust.py).

    Same frame as GeometryParams: x across the cards (card centres at +-card_pitch/2), y along the card height
    (+y = the card's top edge, the bracket's screw-tab end), z along the card axis. The inlet face lies on the
    bracket plane and the part extends to +z; the pull fan blows further to +z, away from the case.

    No hardware has been measured for this part. Every hardware number is an assumption whose source is in
    its comment (CEM = PCI Express CEM r3.0; PB-10577 = NVIDIA A100 80GB PCIe product brief); PRINT-NOTES
    lists which ones to measure. Print the fit gauge first.
    """
    # Frame (shared with the duct and the CFD domain)
    inlet_z: float = 70.0+267.0          # bracket plane: chamber_length + DomainParams.card_envelope (267 mm card). The presets keep
                                         # V24-V27's 70 mm (the released STLs' frame); for_duct(g) places a collector on any duct
    card_pitch: float = 60.96            # GeometryParams.pitch: 60.96 = three slots (one empty between the cards), 40.64 = two (adjacent)

    # Slots and chassis openings
    slot_pitch: float = 20.32            # 0.800 in, CEM Fig 1-3 and ATX 2.2 Fig 3
    slots: tuple[float, ...] = ()        # slot positions the window covers, in slot pitches from the midpoint between the cards;
                                         # () = card A's first to card B's last slot at card_pitch (slot_layout: -2 ... 2 or -1.5 ... 1.5)
    opening_width: float = 13.25         # chassis opening per slot, minimum (CEM Fig 9-22); starts at the PCB plane
    opening_height: float = 100.71       # chassis opening height, minimum (CEM Fig 9-22)
    opening_top_drop: float = 4.82       # opening top below the bracket top, maximum (CEM Fig 9-22)
    # Bracket top in duct y. The bracket top is 108.21 mm above the system board (CEM Fig 10-2); the card top edge is
    # assumed 104.86 mm above it (A100 height from the connector datum, PB-10577 Fig 3) with the measured 98.0 mm
    # cooler end flush with that edge, so the cooler centre (duct y = 0) is 55.86 mm above the board.
    bracket_top_y: float = 108.21-(104.86-98.0/2)
    component_side: float = 1.0          # +1: each card's cooler lies on the +x side of its PCB (towards higher slot numbers)
    pcb_side_reach: tuple[float, float] = (2.67, 34.80)      # secondary / component side reach from the PCB (CEM Fig 1-3)
    window_margin_y: float = 0.5         # window beyond the chassis opening at both y ends (export tolerance, no slivers)
    window_corner_radius: float = 2.5    # below the 2.8 mm x margin: small enough to keep every derived opening corner inside the window
    mouth_y: tuple[float, ...] = ()      # (y0, y1): the mouth's y extent instead of the chassis opening (v2: the bracket vent window)
    vents: tuple[tuple[float, float, float, float], ...] = ()   # (x0, x1, y0, y1) that must stay open (absolute); () = vent_window,
                                                                 # else the chassis openings
    vent_window: tuple[float, ...] = ()  # (length y, width x, top below the bracket top) of each card's bracket vent window, centred on
                                         # the card (hardware.BracketParams.window; 170HX: 81 x 25, 8 below, user photo): it follows card_pitch
    vents_on_openings: bool = False      # vent_window only where it passes a chassis opening (the rest of the window is behind a rib)
    fan_offset_y: float = 0.0            # fan axis below (-) / above (+) the window centre
    fan_offset_x: float = 0.0            # fan axis beside the slot-block centre (split: on the web, between the mouths)
    ease_ramp: float = 0.0               # 0: smoothstep loft (v1); > 0: bounded-slope ramp with this end fraction (duct.cad.geometry.ramp)
    gauge_arrow_inside: bool = False     # fit gauge: draw the +y arrow inside the window (the flange band is too short for it)
    # Split collector (v3): one mouth per card, each sealed by its own gasket loop on the panel ribs; the middle slot (and
    # anything outside the loops) stays under the bare flange web, outside the plenum. A splitter fin divides the plenum.
    split: bool = False
    split_margin: float = 0.5            # each mouth beyond its card's two chassis openings
    gasket_lip_top: float = -1.0         # flange land above the mouth before the groove (< 0: gasket_lip)
    fin_thickness: float = 1.2           # splitter fin between the two cards' halves of the plenum
    fin_end: float = 4.0                 # the fin stops this far below the fan plate: one round passage at the blades
    top_dip: tuple[float, float, float] = (1.0, 1.7, 14.0)  # top wall: drops this much within this far above the flange, holds
    #                                                         until this distance from the bracket plane (slot-screw tips, ledge lip)
    top_rise_ease: float = .3            # ramp end fraction of the top wall's rise to the bore (peak slope = mean / (1 - e))

    # v4 (docs/collector-v4-plan.md); every field off by default, so v1-v3 rebuild byte-identical
    fan_y_at_board: bool = False         # fan axis y from the board plane: the frame bottom sits frame_below_board under it
    frame_below_board: float = 0.0
    max_wall_angle: float = 45.0         # design limit for every overhanging wall from vertical (collector_checks reports against it)
    lip: float = 0.0                     # inlet lip: each mouth's sides and bottom roll outward this much (smoothstep from lip_start,
    lip_start: float = 1.0               # end radius ~lip; none on top: slot-screw tips). Starts this far above the panel face (groove roof)
    web_round: float = 0.0               # quarter round on a wide web's top edges at the inner mouths (5-slot centre web, no fill)
    mouth_corners: tuple[float, ...] = ()   # per card mouth (outer-bottom, inner-bottom, inner-top, outer-top); () = window_corner_radius
    corner_end: float = 8.0              # plenum section corners grow to this by corner_reach of the depth (then the bore disc rounds them)
    corner_reach: float = 1.0
    per_opening_mouths: bool = False     # one mouth per chassis opening (x +- split_margin, y mouth_y) instead of per card
    rib_corners: tuple[float, float] = (6.0, 1.2)   # per-opening mouths: bottom corners, rib-side top corners (vent strip 0.25 / 0.5 inside)
    vane_style: str = 'v3'               # 'v3': the plain splitter fin; 'v4': vanes with filleted roots and full-round tops
    vane_root: float = 2.4               # vane root fillet / S-curve end radius on a narrow web (6.07 mm rib strips, 4-slot centre web)
    rib_fins: bool = False               # one fin per card on the strip between its two mouths (per_opening_mouths)
    rib_fin_end: float = 32.0            # rib fin top, from the bracket plane
    rib_fin_lean: float = 6.0            # rib fins lean outward (away from the centre) this much by their top
    fill_web: bool = False               # the inner walls lean from the inner mouths to the centre fin (fills the web step)
    fill_angle: float = 30.0             # their steepest lean from vertical
    merge_fillet: float = 4.0            # minimum radius where they meet the centre fin
    plug_outline: tuple[float, ...] = ()   # flange_mode 'plug' (a recessed slot bay, duct.cad.plug): x0, x1, y0, y1, corner r
    plug_channels: tuple[tuple[float, float, float, float], ...] = ()   # face channels over the divider bars: x0, x1, y0, y1
    plug_channel_depth: float = 0.0
    mouth_x: tuple[tuple[float, float], ...] = ()   # per-card mouth x (x0, x1) instead of its openings + split_margin
    plug_pocket_skin: float = 0.0        # > 0: the plug is hollowed from its top down to this face skin, clear of the body (0: solid)
    flange_mode: str = 'overlap'         # 'windowed': the flange reaches flange_reach_x past the outer open slots, with a window over each
    flange_reach_x: float = 15.0
    slot_window_margin: float = 1.0      # window = open slot opening + this, corners slot_window_radius
    slot_window_radius: float = 4.0
    flange_top_round: float = 0.0        # round on the flange's top edge (outside and windows)
    flange_fillet_top: float = -1.0      # body-flange fillet on the +y side (< 0: flange_fillet)
    magnet_columns_y: tuple[float, ...] = ()   # windowed: magnets beyond each outer open slot (x = slot edge + magnet_column_dx), at these y
    magnet_column_dx: float = 6.9
    magnet_row_y: float = -65.0          # and a row below the openings, clear of the gasket grooves, at magnet_row_x
    magnet_row_x: tuple[float, ...] = ()
    # mount 'snap' (v4): tool-free clips, printed separately (lying on their side: the layers run along the arm) and glued into
    # dovetail slots in posts that fill the mouth corners over the bracket plate; each arm reaches through the chassis opening
    # into its card's vent window, along the window's outer x edge, and hooks behind the plate (and the bezel, as modelled)
    snap_arm_y: tuple[float, ...] = (-18.0, 22.0)   # arm centres along each window's outer x edge, from the window centre (2 per card)
    snap_arm_thickness: float = 1.6
    snap_arm_length: float = 13.0        # free length: the slot floor (clamp) to the catch
    snap_barb: float = 1.0               # barb depth = the arm's deflection on the way in
    snap_clearance: float = .2           # arm to the window edge
    snap_catch_depth: float = 2.46       # flange face to the catch: panel .8 + bracket plate .86 + bezel .8 (modelled on the card side)
    snap_catch_gap: float = .1
    snap_lead_deg: float = 45.0          # lead-in ramp from the arm axis
    snap_release_deg: float = 55.0       # catch face from the arm axis (90: locking; < 73 at mu .3: a firm tug releases it)
    snap_tenon: tuple[float, float] = (3.5, 2.0)   # half-dovetail neck width, depth; the arm is as wide as the tenon's far end
    snap_tenon_flank_deg: float = 40.0   # its one flank from the print vertical (the clip prints on its side, the flat flank down)
    snap_base_length: float = 7.0        # tenon length in the slot
    snap_slot_clearance: float = .15
    hub_fairing: bool = False            # a 1.2 mm shell of revolution on the fan axis, open toward the fan, carried by the centre fin:
    hub_fairing_d: float = 51.0          # base diameter (the fan hub), just below the fan plate
    hub_fairing_angle: float = 44.0      # its steepest flank from vertical (at the tip; vertical at the base: an ogive)
    hub_fairing_power: float = 1.35      # radius = R (1 - t^p), t from the base (0) to the tip (1)
    hub_fairing_tip: float = 1.0         # blunt tip radius

    # Flange on the rear panel, with a perimeter foam-gasket groove on its case face
    flange_thickness: float = 2.8        # 10 layers of 0.28 mm
    boss_height: float = 4.2             # magnet bosses: 3.2 mm pocket under a 1.0 mm cap (15 layers)
    boss_wall: float = 1.2               # = wall
    flange_overlap: tuple[float, float, float] = (20.5, 16.0, 9.0)   # flange edge beyond the window: x sides, -y, +y (short: the
                                                                      # bracket tabs and any external slot screws sit just past +y)
    flange_corner_radius: float = 10.0
    gasket_width: float = 6.4            # groove for a 6 mm wide soft foam strip
    gasket_depth: float = 1.2
    gasket_lip: float = 1.2              # flange land between the window edge and the groove

    # Plenum: rounded-rectangle mouth over the window, lofted to the round fan bore
    plenum_depth: float = 25.0           # bracket plane to fan face: about the fan hub radius (see PRINT-NOTES)
    fan_end_corner_radius: float = 58.4  # = fan_radius: the last section is the round bore

    # Fan: Arctic P12 Pro (ACFAN00305A), 120 x 120 x 25 mm, 105 mm hole spacing, 4.3 mm holes, 117 mm cut-out (Arctic 2D drawing)
    fan_size: float = 120.0
    fan_radius: float = 58.4             # bore, as GeometryParams.fan_radius (Arctic: cut-out 117 mm)
    fan_hole_offset: float = 52.5
    fan_hole_radius: float = 1.7         # 3.4 mm pilot through plate and ear chamfer: long #6-32 / M4 screws through the fan thread into it
    fan_plate_thickness: float = 2.4
    fan_plate_corner_radius: float = 14.0
    fan_hub_diameter: float = 51.0       # scaled off the Arctic 1:1 drawing (about 50-52 mm); reported only
    fan_thickness: float = 25.0          # reported only (protrusion)

    # Shell (V24 conventions)
    wall: float = 1.2                    # 3-D dilation of the rounded air volume: 3 x 0.4 mm lines (V24's duct: 1.6)
    kernel_segments: float = 32.0
    shell_simplify: float = .002
    loft_points: int = 512               # air volume; the dilation tool uses half
    loft_rings: int = 41
    flange_fillet: float = 3.5           # concave fillet between body and flange (V24 flange_fillet)
    ear_support_angle: float = 45.0      # the fan-plate corner ears rest on a chamfer this far from vertical
    pilot_depth: float = 0.0             # fan-screw pilots: blind, this deep from the fan face (0: through the ear chamfer)

    # Fan cable: U-notch through an x-side flange band, outside the gasket, between two mount points. It opens over the
    # adjacent slot's chassis opening, so the cable can drop into that slot (cover removed) outside the sealed window.
    cable_notch: tuple[float, float, float] = (1.0, 18.0, 8.0)   # (x band: +1 / -1, y from the window centre, width)

    # Mounting: 'magnets' (steel rear panel / slot covers) or 'screws' (z-axis screws into the rear panel)
    mount: str = 'magnets'
    # Mount points on both x bands, y from the window centre. The x bands lie over the adjacent slots' openings (their covers
    # sit ~1 mm behind the panel face), so the lowest pair sits below those openings, on solid panel, in the -y corners.
    mount_y: tuple[float, ...] = (-57.7, -10.0, 30.0)
    magnet_diameter: float = 10.0        # 10 x 3 mm N52 disc magnets (2.3 kg pull, ~0.45 kg shear at zero gap)
    magnet_thickness: float = 3.0
    magnet_clearance: float = .15        # radial clearance of the pocket (glue the magnet in)
    screw_offset: float = 15.0           # screw slot centre beyond the window x edge: the thumb-screw head clears the body
    screw_slot_width: float = 3.8        # #6-32 / M3.5 clearance
    screw_slot_length: float = 8.0       # elongated along y for adjustment
    thumb_head_diameter: float = 14.0    # 12 mm knurled thumb-screw head + 1 mm all round
    thumb_head_height: float = 10.0

    # Fit gauge
    gauge_thickness: float = 0.84        # 3 layers of 0.28 mm: about 10 min of printing
    gauge_line: float = 1.6

    export_tolerances: tuple[float, ...] = (0.01, 0.02)

    def __post_init__(self):
        assert self.mount in ('magnets', 'screws', 'snap'), self.mount
        if self.mount == 'screws' and self.flange_mode == 'windowed':   # the screw pattern sits on the x bands the windows cut away
            raise ValueError("mount='screws' needs a solid flange: with flange_mode='windowed' use 'magnets' or 'snap'")

    @property
    def slot_positions(self) -> tuple[float, ...]:
        return tuple(self.slots) or slot_layout(self.card_pitch, self.slot_pitch)['span']

    @property
    def window_x(self) -> tuple[float, float]:
        return (min(self.slot_positions)*self.slot_pitch-self.slot_pitch/2, max(self.slot_positions)*self.slot_pitch+self.slot_pitch/2)

    @property
    def vent_rects(self) -> list[tuple[float, float, float, float]]:
        """The bracket vents that must stay open: `vents`, else each card's vent_window (clipped to the chassis openings
        when vents_on_openings), else none."""
        if self.vents or not self.vent_window: return [tuple(v) for v in self.vents]
        L, W, top = self.vent_window; y1 = self.bracket_top_y-top
        wins = [(cx-W/2, cx+W/2, y1-L, y1) for cx in (-self.card_pitch/2, self.card_pitch/2)]
        if not self.vents_on_openings: return wins
        return [(max(w[0], o[0]), min(w[1], o[1]), max(w[2], o[2]), min(w[3], o[3])) for w in wins
                for o in self.openings if min(w[1], o[1]) > max(w[0], o[0])]

    def for_duct(self, g: GeometryParams, card_length: float = 267.0) -> 'CollectorParams':
        """This collector on duct `g`: its card pitch (slot layout, openings, vents) and bracket plane (inlet_z = chamber
        length + card length; DomainParams.card_envelope, hardware.CaseParams.card_length)."""
        return replace(self, card_pitch=g.pitch, inlet_z=g.chamber_length+card_length)

    @property
    def window_y(self) -> tuple[float, float]:
        if self.mouth_y: return tuple(self.mouth_y)
        top = self.bracket_top_y-self.opening_top_drop
        return (top-self.opening_height-self.window_margin_y, top+self.window_margin_y)

    @property
    def board_y(self) -> float:
        """The system-board plane: 108.21 mm below the bracket top (CEM Fig 10-2)."""
        return self.bracket_top_y-108.21

    @property
    def fan_axis(self) -> tuple[float, float]:
        """The fan is centred on the window in x, so its hub covers the middle (blank) slot; fan_offset_y moves it in y
        (fan_y_at_board: the frame bottom frame_below_board under the board plane)."""
        if self.fan_y_at_board: return (sum(self.window_x)/2+self.fan_offset_x, self.board_y-self.frame_below_board+self.fan_size/2)
        return (sum(self.window_x)/2+self.fan_offset_x, sum(self.window_y)/2+self.fan_offset_y)

    @property
    def fan_dy(self) -> float:
        """The fan axis's y offset from the window centre (fan_offset_y, or derived from the board plane)."""
        return self.fan_axis[1]-sum(self.window_y)/2 if self.fan_y_at_board else self.fan_offset_y

    @property
    def frame_bottom_below_board_mm(self) -> float:
        return self.board_y-(self.fan_axis[1]-self.fan_size/2)

    @property
    def must_open(self) -> list[tuple[float, float, float, float]]:
        """What the mouth must leave open: the given vents, else the derived chassis openings."""
        return self.vent_rects or self.openings

    @property
    def openings(self) -> list[tuple[float, float, float, float]]:
        """Derived chassis openings (x0, x1, y0, y1): each starts at its card's PCB plane, the cooler being centred on the card envelope."""
        s = self.component_side; sec, comp = self.pcb_side_reach
        pcb = -self.card_pitch/2-s*(comp-sec)/2      # card A's PCB secondary face
        y1 = self.bracket_top_y-self.opening_top_drop; y0 = y1-self.opening_height; out = []
        for k, _ in enumerate(sorted(self.slot_positions)):
            a = pcb+s*k*self.slot_pitch; b = a+s*self.opening_width
            out.append((min(a, b), max(a, b), y0, y1))
        return out


COLLECTOR_V1 = CollectorParams()

# v2 fits around the slot ledge, bracket tabs and slot screws, which sit OUTSIDE the case just above the slot openings
# (duct/cad/hardware.py: CEM Fig 9-5 / 9-13 top tab, the ledge under it assumed 0.8 mm). The flange's +y edge stays
# 0.5 mm under the ledge (y 50.69), so the mouth stops 0.5 mm above the 170HX vent window (top 8 mm below the bracket top,
# user photo); the 3 mm gasket straddles the chassis-opening tops, pressing the plate-to-panel slits there shut. The
# top wall then leans in (the fan bore top is 3.85 mm lower), clearing the slot-screw tips that poke 4.7 mm under the
# ledge (6-32 x 1/4"), and the flange fillet is 1.5 mm there. The fan sits 10.8 mm below the mouth centre; the mouth
# reaches 4.8 mm below the chassis openings and the near-linear loft keeps the -y wall at about 41 deg; the flange reaches
# 20 mm below the mouth so the fan plate's lower ears and their chamfers stand on it.
COLLECTOR_V2 = replace(COLLECTOR_V1, mouth_y=(-58.0, 44.85), vent_window=(81.0, 25.0, 8.0),
                       fan_offset_y=-10.825, ease_ramp=.08, gasket_width=3.0, gasket_lip=.8, flange_overlap=(20.5, 20.0, 5.34),
                       flange_fillet=1.5, gauge_arrow_inside=True)

# v3 seals per card: each card's two chassis openings get their own mouth and gasket loop, whose side bands sit centred
# on the 7.07 mm panel ribs either side of the card (2.035 mm from each opening edge), so the open middle slot and the
# outer slots stay under the bare flange, outside the plenum. One plenum lofts from both mouths to the fan bore; a 1.2 mm
# fin standing on the flange web over the middle slot splits it per card up to 4 mm below the fan plate, in line with
# the hub (fan axis on the fin). The mouth tops stop 0.25 mm above the vent windows (v2: 0.5) for the slot-screw tips
# just past the flange; the top wall then dips 1 mm within 1.7 mm of the flange (slot-screw tips) and rises only
# after 14 mm (a ledge with a downturned lip), so the fan sits 13 mm below the board plane (v2: 22). V3L: 20 mm deeper,
# the fan 4 mm higher still.
# What must stay open: each vent window where it passes a chassis opening (vents_on_openings; the rest is behind the rib)
COLLECTOR_V3 = replace(COLLECTOR_V2, split=True, mouth_y=(-55.18, 44.6), vents_on_openings=True, gasket_lip=1.535,
                       gasket_lip_top=.8, fan_offset_x=.72, fan_offset_y=-3.835, ease_ramp=.2, flange_overlap=(20.5, 17.0, 5.34))
COLLECTOR_V3L = replace(COLLECTOR_V3, plenum_depth=45.0, fan_offset_y=.165)

# v4 (docs/collector-v4-plan.md, revision after the curves requirement). Shared (B and A): per-card gasket loops on the
# ribs as v3; D = 45 so the fan frame bottom sits on the board plane (the top wall holds 1 mm under the mouth top to 15 mm
# out, then rises 18.9 mm at 34 deg mean, 40.6 peak); the mouths' sides and bottom roll outward 2.5 mm (inlet lip), the top
# has none (screw tips); per-corner mouth radii (bottom 12, inner top 5, outer top 4) growing to 12 by mid-depth; the
# flange reaches 15 mm past the outer open slots, with a window over each (they stay open), and carries 7 magnets on flush
# steel: two in each outer column, three below the openings; the centre fin has a filleted root and a full-round top.
# B (control): per-card mouths, the centre fin only. A: one mouth per chassis opening and a rib fin per card, leaning 6 mm
# outward, on the strip between its two mouths. Use .for_duct(V29) (5-slot) or .for_duct(A29) (4-slot).
COLLECTOR_V4B = replace(COLLECTOR_V3, plenum_depth=45.0, fan_y_at_board=True, frame_below_board=0.0, fan_offset_y=0.0,
                        mouth_y=(-53.68, 44.6), top_dip=(1.0, 1.7, 15.0), top_rise_ease=.2, ease_ramp=.25, lip=2.5,
                        web_round=2.4, mouth_corners=(12.0, 12.0, 5.0, 4.0), corner_end=12.0, corner_reach=.5, vane_style='v4',
                        flange_mode='windowed', flange_overlap=(20.5, 20.0, 5.34), flange_corner_radius=15.0, flange_fillet=3.7,
                        flange_fillet_top=1.5, flange_top_round=1.0, fan_plate_corner_radius=5.0, magnet_columns_y=(-30.0, 35.0),
                        magnet_row_y=-65.0, magnet_row_x=(-35.0, 0.0, 35.0), magnet_column_dx=7.4, cable_notch=(), pilot_depth=6.4)
COLLECTOR_V4A = replace(COLLECTOR_V4B, per_opening_mouths=True, rib_fins=True)
COLLECTOR_V4 = COLLECTOR_V4A                 # the plan's first name for A (CFD kind "v4"); prefer COLLECTOR_V4A
# The CFD matrix's variants (docs/collector-v4-plan.md section 6): A without lean, A at D = 40 (the frame bottom then sits
# 4.8 mm under the board plane to keep the top wall's angle), A with the web step filled (5-slot only: the 4-slot centre
# web is a 6 mm rib strip, already an S-curve root).
COLLECTOR_V4A_LEAN0 = replace(COLLECTOR_V4A, rib_fin_lean=0.0)
COLLECTOR_V4A_D40 = replace(COLLECTOR_V4A, plenum_depth=40.0, frame_below_board=4.8)
COLLECTOR_V4A_FILL = replace(COLLECTOR_V4A, fill_web=True)
# A + a hub fairing (the coordinator's request after the author's 4-slot question): an ogive shell in front of the 51 mm fan
# hub, open toward the fan, on the centre fin; it turns the inner strips' jets outward to the blades instead of onto the hub.
# corner_end 20: the plenum corners round off faster toward the bore (30 thickens the 4-slot top corners past the solid gate).
COLLECTOR_V4A_HUB = replace(COLLECTOR_V4A, hub_fairing=True, corner_end=20.0)
# A with snap clips instead of magnets (the author's idea: arms into each card's vent window, no screws); see mount 'snap'.
COLLECTOR_V4A_SNAP = replace(COLLECTOR_V4A, mount='snap')
# Base of the plug collector for a recessed slot bay (duct.cad.plug.plug_params(COLLECTOR_PLUG_BASE.for_duct(g), CASE_FRACTAL)):
# the B plenum (the v4 CFD: A's rib/channel fins gave +0.03 L/s vs v3, -0.10 vs B) with the hub fairing.
COLLECTOR_PLUG_BASE = replace(COLLECTOR_V4B, hub_fairing=True, corner_end=20.0)
# The plug with a 140 mm pull fan (the author's ARCTIC P14 Pro Reverse: 140 x 140 x 30 mm (ARCTIC spec sheet), 124.5 mm hole spacing, 400-2650 rpm,
# ~98 CFM, 5.1 mmH2O by retailer listings). Bore 136 mm and hub 56 mm are ESTIMATES (measure the fan before printing). The fan
# is centred on the mouths (its frame then runs ~19 mm past the recess top and stays inside it below, unlike the 120's frame on
# the board plane); D 55 keeps every plenum wall within 45 deg as it widens to the larger bore; the smaller tip stays on the fin.
COLLECTOR_PLUG_140 = replace(COLLECTOR_PLUG_BASE, fan_size=140.0, fan_radius=68.0, fan_end_corner_radius=68.0, fan_hole_offset=62.25,
                             fan_hub_diameter=56.0, hub_fairing_d=56.0, hub_fairing_tip=0.8, fan_thickness=30.0,
                             fan_y_at_board=False, fan_offset_y=0.0, plenum_depth=55.0)
