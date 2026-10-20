"""Recessed-bay geometry (CaseParams.recess, CASE_FRACTAL) and the plug fit gauge.

The collector for a recessed slot bay is a plug: its case face fits inside the recess (between its top and bottom walls,
less plug_clearance) and bears on the divider bars' crowns. In x it spans the cards' slots and the slot between them only:
its side edges stop on the outer bounding bars, short of the outer slots' openings, which stay open. Each card's mouth spans
the bars that bound its two slots; the plug face is solid over the slot between the cards. Duct frame as in hardware.py.
"""
import manifold3d as mf
import numpy as np
import shapely
from shapely.geometry import Polygon, box

from ..params import CollectorParams
from .exhaust import _cs, card_windows, snap_dims, snap_sites


def slot_openings_x(c: CollectorParams) -> list[tuple[float, float]]:
    """x ranges of every slot opening in the bay: the collector's (c.openings) and one more each side (the outer slots)."""
    os_ = sorted(o[:2] for o in c.openings); p = c.slot_pitch
    return [(os_[0][0]-p, os_[0][1]-p), *os_, (os_[-1][0]+p, os_[-1][1]+p)]


def recess_outline(c: CollectorParams, case) -> Polygon:
    """The recess's inner outline at its floor: centred in x on the slot openings' span, its top wall
    recess_top_above_bracket over the bracket top, inner corners rounded."""
    W, H, _, r = case.recess; xs = [v for o in slot_openings_x(c) for v in o]
    xc = (min(xs)+max(xs))/2; y1 = c.bracket_top_y+case.recess_top_above_bracket
    return box(xc-W/2+r, y1-H+r, xc+W/2-r, y1-r).buffer(r, quad_segs=16)


def divider_x(c: CollectorParams) -> list[float]:
    """Centre lines of the divider bars: the gaps between neighbouring slot openings (outer slots included)."""
    edges = slot_openings_x(c); return [(a[1]+b[0])/2 for a, b in zip(edges, edges[1:])]


def card_mouths_plug(c: CollectorParams, case) -> list[tuple[float, float, float, float]]:
    """Each card's mouth on the plug face (x0, x1, y0, y1): between the crowns of the bars bounding its two slots, from the
    end of the openings above the floor band to just over the bracket top."""
    xs = divider_x(c); rec = recess_outline(c, case).bounds
    y0 = rec[1]+case.recess_floor_band; y1 = c.bracket_top_y+.5; out = []
    for cx in (-c.card_pitch/2, c.card_pitch/2):
        inside = [x for x in xs if abs(x-cx) < c.slot_pitch*1.25]   # the bar across the window and the two bounding it
        out.append((min(inside), max(inside), y0, y1))
    return out


def text_polygon(s: str, height: float, at=(0., 0.), angle: float = 0.0, anchor: str = 'center') -> shapely.Geometry:
    """`s` as filled outlines (DejaVu Sans Bold), cap height `height` mm, centred (or anchored) at `at`, rotated `angle` deg."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    fp = FontProperties(family='DejaVu Sans', weight='bold'); cap = TextPath((0, 0), 'H', size=100, prop=fp).get_extents().height
    tp = TextPath((0, 0), s, size=100*height/cap, prop=fp)
    g = shapely.Polygon()
    for ring in tp.to_polygons(closed_only=True):
        if len(ring) >= 3: g = g.symmetric_difference(Polygon(ring).buffer(0))   # even-odd: glyph counters become holes
    x0, y0, x1, y1 = g.bounds
    g = shapely.affinity.translate(g, -(x0+x1)/2, -(y0+y1)/2)
    g = shapely.affinity.rotate(g, angle, origin=(0, 0))
    return shapely.affinity.translate(g, *at).buffer(0)


GAUGE = dict(clearance=.5, plate=1.4, deboss=.56, cap=7.0, ab_cap=3.5, corner=2.0,   # plate: 5 layers of 0.28; labels 2 deep
             tongue=(1.6, 16.0), hook=2.4, bridge=4.0, bridge_overlap=1.5, catch_deg=40.0, hook_gap=.3)
# One-piece gauge, printed outer face down: each snap site gets a spring hook. A tongue (tongue: width, length) in the plate,
# printed flat so its layers run along it, bends in the plate's plane and carries a hook post (hook: thick across the window)
# up to a barb; a rigid bridge ties the tongue's root to the plate's side strip. The barb's catch face leans catch_deg from
# the hook's axis (the collector clip's 55 deg would overhang in this print orientation; 40: a firm pull releases it).


def gauge_hooks(c: CollectorParams, case) -> tuple[mf.Manifold, list[Polygon]]:
    """The spring hooks in the gauge frame (h: depth toward the case from the gauge face, which rests on the bare bar crowns;
    the plate is h in [-plate, 0]). Each hook's catch lies the clip's catch_gap behind the bracket plate at the window edge,
    as the plug collector's clips (plug_params). Returns (hooks as solids at (x, y, plate + h): build_plug_gauge turns them
    into the print frame, footprints in duct xy)."""
    from .exhaust import _extrude
    from .geometry import union
    from .hardware import BRACKET
    G = GAUGE; T = G['plate']; cp = plug_params(c, case); k = snap_dims(cp); w = k['width']
    ua = k['u_arm'][1]; ub = k['barb_u']; ui = ua-G['hook']; tw, L = G['tongue']; bw = G['bridge']
    h_catch = case.divider[1]+BRACKET.sheet+cp.snap_catch_gap        # the catch face meets the window edge (u 0) here
    kk = 1/np.tan(np.radians(G['catch_deg'])); h_b = h_catch+ub*kk; h_flat = h_b+.3
    h_tip = h_flat+(ub-ua)/np.tan(np.radians(cp.snap_lead_deg))
    prof = Polygon([(ui, -T/2), (ua, -T/2), (ua, h_catch+ua*kk), (ub, h_b), (ub, h_flat), (ua, h_tip), (ui+.4, h_tip), (ui, h_tip-.4)])
    hook = mf.Manifold.extrude(_cs(prof), w).translate([0, 0, -w/2])                                     # (u, h, v)
    hook = hook.transform(np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0]], dtype=float))            # -> (u, v, h)
    mouths = card_mouths_plug(c, case); solids, foot = [], []
    for st in snap_sites(cp):
        m = mouths['AB'.index(st['card'])]; reach = abs((m[0] if st['out'] < 0 else m[1])-st['edge_x'])+G['bridge_overlap']
        away = 1 if st['y'] > (card_windows(cp)[0][2]+card_windows(cp)[0][3])/2 else -1   # the tongue runs toward the window's end
        v0 = away*(w/2-.5); v1 = away*(w/2+L); v2 = v1+away*bw; v1o = v1-away*.5   # the pieces overlap 0.5 mm (one solid)
        flat = shapely.unary_union([box(ui-.1, -w/2-.1, ua+.1, w/2+.1), box(ua-tw, min(v0, v1), ua, max(v0, v1)),   # post foot, tongue, bridge:
                                    box(ui, min(v1o, v2), reach, max(v1o, v2))])                      # one flat piece, the post above
        place = lambda m_: (m_.mirror([1, 0, 0]) if st['out'] < 0 else m_).translate([st['edge_x'], st['y'], T])  # noqa: E731
        solids += [place(hook), place(_extrude(flat, -T, T))]   # the post starts inside its foot (0.1 mm larger): no shared faces
        foot.append(shapely.affinity.translate(shapely.affinity.scale(flat, st['out'], 1, origin=(0, 0)),
                                               st['edge_x'], st['y']))
    return union(*solids), foot


def plug_face_x(c: CollectorParams, margin: float) -> tuple[float, float]:
    """The plug's side edges: on the outer bounding bars, `margin` short of the outer slots' openings (left open)."""
    ops = slot_openings_x(c); return ops[0][1]+margin, ops[-1][0]-margin


def gauge_outline(c: CollectorParams, case) -> Polygon:
    """The gauge plate's outline: the plug's (y: the recess less the clearance; x: plug_face_x), corners rounded."""
    G = GAUGE; rec = recess_outline(c, case).bounds; x0, x1 = plug_face_x(c, PLUG['edge_margin']); r = PLUG['corner']
    return box(x0+r, rec[1]+G['clearance']+r, x1-r, rec[3]-G['clearance']-r).buffer(r, quad_segs=16)


def plug_gauge_parts(c: CollectorParams, case, layout: str = '5-SLOT') -> dict:
    """The gauge's 2-D layers (duct xy, as seen from outside the case): plate (the plug outline less the card mouths),
    labels (cut into the case-side face: each glyph mirrored about its centre, so it reads from that side), the hooks'
    footprints."""
    G = GAUGE; out = gauge_outline(c, case)
    mouths = card_mouths_plug(c, case); r = G['corner']; _, hooks = gauge_hooks(c, case)
    holes = [box(x0+r, y0+r, x1-r, y1-r).buffer(r, quad_segs=8) for x0, x1, y0, y1 in mouths]
    plate = out.difference(shapely.unary_union(holes)).buffer(0)
    xb, yb = out.bounds[0], out.bounds[3]; pads = [(xb, mouths[0][0]), (mouths[0][1], mouths[1][0]), (mouths[1][1], out.bounds[2])]
    yt = yb-1.5-G['cap']/2; ybot = out.bounds[1]+3   # labels: upright near the top, the layout vertical below
    col = lambda i: (pads[i][0]+pads[i][1])/2  # noqa: E731
    yab = (out.bounds[1]+mouths[0][2])/2   # A / B in the band under each mouth (the side strips are too narrow)
    labels = [text_polygon(k, G['ab_cap'], ((m[0]+m[1])/2, yab)) for k, m in zip('AB', mouths)]
    labels += [text_polygon('TOP', 6.0, (col(1), yt-12)), Polygon([(col(1)-4.5, yt-6), (col(1)+4.5, yt-6), (col(1), yt+3.5)])]
    t = text_polygon(layout, 6.0, angle=90); labels.append(shapely.affinity.translate(t, col(1), ybot+(t.bounds[3]-t.bounds[1])/2))
    lab = shapely.unary_union([shapely.affinity.scale(g, -1, 1, origin='center') for g in labels])
    assert lab.within(plate.buffer(-.8)), 'a label leaves the plate'
    return dict(outline=out, plate=plate, labels=lab, mouths=mouths, holes=shapely.unary_union(holes), pads=pads, hooks=hooks)


def build_plug_gauge(c: CollectorParams, case, layout: str = '5-SLOT') -> mf.Manifold:
    """One piece, in the print frame: the outer face on the bed (z 0), the plate up to the gauge face (z plate) with the labels
    cut into it, and the spring hooks standing up from it toward the case. The part as fitted turned 180 deg about x
    (y -> -y, z toward the case)."""
    G = GAUGE; p = plug_gauge_parts(c, case, layout); t = G['plate']; hooks, _ = gauge_hooks(c, case)
    ext = lambda g, z, h: mf.Manifold.extrude(_cs(g), h).translate([0, 0, z])  # noqa: E731
    return ((ext(p['plate'], 0, t)+hooks)-ext(p['labels'], t-G['deboss'], 1)).mirror([0, 1, 0])   # (x, y, plate + h) -> print


def to_print_xy(g):
    """A duct-xy polygon in the gauge's print frame (build_plug_gauge: y -> -y)."""
    return shapely.affinity.scale(g, 1, -1, origin=(0, 0))


def plug_gauge_spec(c: CollectorParams, case, layout: str = '5-SLOT'):
    """Printability spec: a flat plate with two through cutouts and labels cut into its top (case-side) face, four spring
    hooks standing up from it (tongue, bridge and hook post: solid by design)."""
    from ..print.printability import Allowed, Opening, PartSpec
    G = GAUGE; p = plug_gauge_parts(c, case, layout); F = 300.0; t = G['plate']; d = G['deboss']
    return PartSpec('plug fit gauge', wall=t, solid_allowed=(Allowed('gauge plate and hooks', (-F, -F, -1), (F, F, F),
                    f"{t} mm flat plate and the spring hooks: solid by design"),),
                    openings=(Opening('card mouth cutout', (0, t), region=to_print_xy(p['holes']), tol=.1),
                              Opening('label cut in the case-side face', (t-d, t), region=to_print_xy(p['labels']), tol=.1)))


def plug_gauge_facts(c: CollectorParams, case) -> dict:
    p = plug_gauge_parts(c, case); W, H, D, r = case.recess
    return dict(recess_mm=dict(width=W, height=H, depth=D, corner_r=r), plug_clearance_top_bottom=GAUGE['clearance'],
                plug_edge_margin_to_outer_slots=PLUG['edge_margin'],
                outline_bounds=[round(v, 2) for v in p['outline'].bounds], divider_x=[round(x, 2) for x in divider_x(c)],
                mouths=[[round(v, 2) for v in m] for m in p['mouths']], card_windows=[[round(v, 2) for v in w] for w in card_windows(c)],
                snap_arms=[dict(card=s['card'], y=round(s['y'], 2), window_edge_x=round(s['edge_x'], 2)) for s in snap_sites(c)],
                pads_x=[[round(a, 2), round(b, 2)] for a, b in p['pads']], plate_area_mm2=round(p['plate'].area, 1))


# ---------------------------------------------------------------------------------------------------------------------
# The plug collector (flange_mode 'plug'): B-style plenum (per-card mouths, centre fin), hub fairing, snap clips.
#
# Stack (z outward, z_b = the bracket plates' outer face): plates [z_b - sheet, z_b] | recess floor (panel) [z_b, z_b + panel] |
# divider bars to z_b + divider[1] | border plane z_b + panel + depth. face 'crown' (default): the plug face is flat, foam_gap
# over the bars' crowns (thin foam on the crowns of the bars bounding each card: the side runs; a thicker strip on the face over
# the floor band below the openings: the bottom run, foam_gap + crown - panel compressed); face 'floor': the face foam_gap over
# the floor with a channel over every bar (roof foam_gap over the crown). The top is sealed by a dam (top_dam): foam on the
# bracket plates' top band, above the window bezels, under the face. The slot openings run on past the bracket tops to the
# recess's top wall, open to the case; the dam keeps them out of the mouths (a lateral run against the top wall would not). In x
# the plug stops on the outer bounding bars (plug_face_x: edge_margin short of the outer slots' openings, which stay open to the
# room; the crown foam on those bars is the side seal) and is solid over the slot between the cards. The mouths expose each
# card's vent window + mouth_margin; everything else under the face is bracket plate. corner: the plug outline's corner radius
# (small, so the outer crown foam stays on the face to the plug's top).

PLUG = dict(face='crown', pocket_skin=1.6, clearance=.5, top_clearance=1.0, foam_gap=1.0, channel_clearance=.3, mouth_margin=2.0, bar_end_overrun=.5,
            dam_width=3.0, dam_margin=.5, edge_margin=.5, corner=1.5)


def top_dam(c: CollectorParams, case, **kw) -> tuple[float, float]:
    """y range of the top dam: foam on the bracket plates' top band, between the window bezels' (and their Torx heads') top
    edge and the plates' top edge, under the flat plug face. It closes the openings above the bracket tops (they run on to
    the recess's top wall, open to the case) off from the mouths, dam_margin inside the plate edge."""
    from .hardware import BRACKET
    P_ = {**PLUG, **kw}; wy1 = card_windows(c)[0][3]; bw = BRACKET.bezel[0]
    clear = max(wy1+bw, wy1+bw/2+BRACKET.torx_head[0]/2)                         # bezel ring and corner screw heads
    y1 = c.bracket_top_y-P_['dam_margin']; y0 = y1-P_['dam_width']
    assert y0 >= clear+P_['dam_margin'] and y0 >= c.mouth_y[1]+P_['dam_margin'], (y0, clear, c.mouth_y)
    return y0, y1


def bounding_bars(c: CollectorParams) -> list[tuple[float, float]]:
    """Per card, the centre lines of the two bars bounding its two slots."""
    xs = divider_x(c); out = []
    for cx in (-c.card_pitch/2, c.card_pitch/2):
        near = [x for x in xs if abs(x-cx) < c.slot_pitch*1.25]
        out.append((min(near), max(near)))
    return out


def plug_params(c: CollectorParams, case, **kw) -> CollectorParams:
    """`c` (a v4 collector, B-style) turned into the plug for `case` (recess, divider): every plug dimension from the case."""
    from dataclasses import replace
    P_ = {**PLUG, **kw}; depth = case.recess[2]; rec = recess_outline(c, case).bounds; cl = P_['clearance']
    bw, crown = case.divider; face = P_['face']; assert face in ('crown', 'floor'), face
    tf = case.panel+depth-_face_z(case, P_)                                      # the plug's top flush with the border plane
    outline = (*plug_face_x(c, P_['edge_margin']), rec[1]+cl, rec[3]-P_['top_clearance'], P_['corner'])
    y_bar0 = rec[1]+case.recess_floor_band                                      # the bars end with the openings, above the floor band
    chans = tuple((x-bw/2-P_['channel_clearance'], x+bw/2+P_['channel_clearance'], y_bar0-P_['bar_end_overrun'], outline[3]+1.0)
                  for x in divider_x(c) if outline[0] < x < outline[1]) if face == 'floor' else ()   # every bar under the plug
    m = P_['mouth_margin']; wins = card_windows(c)
    mouth_x = tuple((w[0]-m, w[1]+m) for w in wins); mouth_y = (wins[0][2]-m, wins[0][3]+m)
    for (a, b), (x0, x1) in zip(bounding_bars(c), mouth_x) if chans else ():   # a printable wall between each mouth and its channels
        assert x0-(a+bw/2+P_['channel_clearance']) >= c.wall and (b-bw/2-P_['channel_clearance'])-x1 >= c.wall, (a, b, x0, x1)
    from .hardware import BRACKET
    fields = dict(flange_mode='plug', plug_outline=outline, plug_channels=chans, plug_channel_depth=crown-case.panel,
                  mouth_x=mouth_x, mouth_y=mouth_y, flange_thickness=tf, plenum_depth=c.plenum_depth+(tf-c.flange_thickness),
                  lip=0.0, top_dip=(0.0, *c.top_dip[1:]), fan_offset_x=(mouth_x[0][1]+mouth_x[1][0])/2,
                  mount='snap', plug_pocket_skin=P_['pocket_skin'],
                  mouth_corners=tuple(min(r_, m*np.sqrt(2)/(np.sqrt(2)-1)-.3) for r_ in c.mouth_corners),   # each window corner inside
                  magnet_columns_y=(), magnet_row_x=(), cable_notch=(), snap_catch_depth=_face_z(case, P_)+BRACKET.sheet)
    return replace(c, **(fields | {k: v for k, v in kw.items() if k not in PLUG}))   # CollectorParams overrides win


def _face_z(case, P_=PLUG) -> float:
    """The plug face above the bracket plates' outer face: foam_gap over the bar crowns ('crown') or over the floor ('floor')."""
    return (case.divider[1] if P_['face'] == 'crown' else case.panel)+P_['foam_gap']


def plug_foam(c: CollectorParams, case, seal: str = 'bars', **kw) -> list[dict]:
    """The foam strips that seal the plug (c: plug_params output): name, surface, width, compressed thickness, length, and for
    the strips under the face their `box` (x0, x1, y0, y1, duct frame). seal 'bars' (default, released): per card, on the
    crowns of the two bars bounding it, the bottom run on the floor band, and the top dam on the bracket plates' top band
    (two soft blocks from crown foam to crown foam, riding over the bar flanks, and a short crown piece over the mid bar)
    closing the openings above the bracket tops; slot 0 is closed by the plug face itself, the outer slots lie outside it.
    'bars-lateral' (superseded: the openings above the bracket tops leak into the mouths): a lateral top run on the plug's
    top side against the recess's top wall instead of the dam."""
    assert seal in ('bars', 'bars-lateral'), seal
    P_ = {**PLUG, **kw}; fg = P_['foam_gap']; x0, x1, y0, y1, _ = c.plug_outline; rec = recess_outline(c, case).bounds
    bw, crown = case.divider; crown_above_floor = crown-case.panel; y_bar0 = rec[1]+case.recess_floor_band
    bottom_gap = fg+crown_above_floor if P_['face'] == 'crown' else fg   # the floor band lies this far under the face
    top = dict(name='top run (lateral, on the plug top side, against the recess top wall)', surface='plug top side',
               width=round(c.flange_thickness-1.0, 1), compressed=round(rec[3]-y1, 2), length=round(x1-x0, 1))
    bw_ = round(min(4.0, y_bar0-y0-1.0), 1); by = round(y_bar0-.5-bw_/2, 2)
    bottom = dict(name='bottom run (on the face, over the floor band)', surface='plug face', width=bw_,
                  compressed=round(bottom_gap, 2), length=round(x1-x0-2, 1), y=by, box=(x0+1, x1-1, by-bw_/2, by+bw_/2))
    cw = round(min(3.0, bw/2), 1)
    bars = [dict(name=f'card {"AB"[i]} bar crown at x {x:+.2f}', surface='plug face (over the crown)', width=cw,
                 compressed=round(fg, 2), length=round(y1-y_bar0, 1), x=round(x, 2), box=(x-cw/2, x+cw/2, y_bar0, y1))
            for i, pair in enumerate(bounding_bars(c)) for x in pair]
    if seal == 'bars-lateral':
        return [top, bottom, *bars]
    d0, d1 = top_dam(c, case, **kw); dam = []
    for i, (a, b) in enumerate(bounding_bars(c)):
        mids = sorted(x for x in divider_x(c) if a < x < b); edges = [a, *mids, b]
        for e0, e1 in zip(edges, edges[1:]):   # a block from crown foam to crown foam: soft, it rides over both bars' flanks
            dam.append(dict(name=f'card {"AB"[i]} top dam block x {e0+cw/2:+.1f}..{e1-cw/2:+.1f}', surface='plug face (over the plate top band)',
                            width=round(d1-d0, 1), compressed=round(fg+crown, 2), length=round(e1-e0-cw, 1),
                            box=(e0+cw/2, e1-cw/2, d0, d1)))
        dam += [dict(name=f'card {"AB"[i]} top dam crown piece at x {x:+.2f}', surface='plug face (over the crown)', width=round(d1-d0, 1),
                     compressed=round(fg, 2), length=cw, x=round(x, 2), box=(x-cw/2, x+cw/2, d0, d1)) for x in mids]
    return [bottom, *bars, *dam]


def plug_placement(c: CollectorParams, case, **kw) -> float:
    """dz from the collector frame (s = 0 at inlet_z, the bracket plane) to the case: the plug face as fitted."""
    return _face_z(case, {**PLUG, **kw})


LOUVRE = dict(inset=2.0, height=2.5, pitch=6.0, top=10.0)   # the louvred blank's slits: schematic (photo shows louvres, none measured)


def build_recess_hardware(g, c: CollectorParams, case) -> dict:
    """The recessed bay as solids (duct frame): the panel around and under it (floor less the slot openings), the divider bars,
    the card brackets' plates (vent windows cut), the window bezels and Torx heads on the plates' outer face, the louvred
    blank (case.vented_covers that are slots of this layout; slits schematic), and the keep-outs (not steel, but nothing of
    ours goes there). Photo-estimate geometry from `case`."""
    from .hardware import BRACKET as b, _bracket, _cs as hcs, bracket_z
    z_b = bracket_z(g, case); rec = recess_outline(c, case); x0, y0, x1, y1 = rec.bounds; W, H, depth, r = case.recess
    zp = z_b+case.panel; zbp = zp+depth
    ext = lambda poly, za, zb: mf.Manifold.extrude(hcs(poly), zb-za).translate([0, 0, za])  # noqa: E731
    y_op0 = y0+case.recess_floor_band; ops = [(a, b_, y_op0, y1) for a, b_ in slot_openings_x(c)]   # the openings run to the top wall
    big = box(x0-160, y0-160, x1+160, y1+160)
    parts = dict(border=ext(big.difference(rec), z_b, zbp),
                 floor=ext(rec.difference(shapely.unary_union([box(a, p, b_, q) for a, b_, p, q in ops])), z_b, zp))
    bw, crown = case.divider; bars = []
    for x in divider_x(c):   # rounded crown (r = half the base, capped by the height)
        rr = min(bw/2, crown)*.9
        prof = box(x-bw/2+rr, z_b-rr, x+bw/2-rr, z_b+crown-rr).buffer(rr, quad_segs=16).intersection(box(x-bw/2, z_b, x+bw/2, z_b+crown))
        m = mf.Manifold.extrude(hcs(prof), y1-y_op0).transform(np.array([[1, 0, 0, 0], [0, 0, 1, y_op0], [0, 1, 0, 0]], dtype=float))
        bars.append(m)
    parts['divider_bars'] = mf.Manifold.batch_boolean(bars, mf.OpType.Add)
    wins = card_windows(c); plates = []; bez = []
    from dataclasses import replace
    cc = replace(c, card_pitch=g.pitch); cs = case.for_pitch(g.pitch)
    for i, slots in enumerate(cs.card_slots):
        solid, _, _ = _bracket(cc, cs, b, slots, z_b, wins[i])
        plates.append(solid.trim_by_plane([0, 0, -1], -z_b))   # the plate only: its tab is inside the case here (no ledge)
        wx0, wx1, wy0, wy1 = wins[i]; bwid, bh = b.bezel
        ring = box(wx0-bwid, wy0-bwid, wx1+bwid, wy1+bwid).difference(box(wx0, wy0, wx1, wy1))
        if case.bezel_side == 'outer':   # on the plate's outer face; under the bars it would clash, so only inside the openings
            ring = ring.intersection(shapely.unary_union([box(a, p, b_, q) for a, b_, p, q in ops]))
            bez.append(ext(ring, z_b, z_b+bh))
            bez += [mf.Manifold.cylinder(b.torx_head[1], b.torx_head[0]/2, circular_segments=32).translate([x, y, z_b])
                    for x in (wx0-bwid/2, wx1+bwid/2) for y in (wy0-bwid/2, wy1+bwid/2)]
    parts['bracket_plates'] = mf.Manifold.batch_boolean(plates, mf.OpType.Add)
    if bez: parts['window_bezels'] = mf.Manifold.batch_boolean(bez, mf.OpType.Add)
    from .hardware import openings
    covers = []
    for k in (k for k in case.vented_covers if k in cs.slots):   # the louvred blank: a single-slot cover plate, louvres schematic
        solid, _, _ = _bracket(cc, cs, b, (k,), z_b)
        ox0, ox1, _, _ = openings(cc, cs)[k]; L = LOUVRE
        slits = [box(ox0+L['inset'], y, ox1-L['inset'], y+L['height'])
                 for y in np.arange(y_op0+L['inset'], c.bracket_top_y-L['top']-L['height'], L['pitch'])]
        covers.append(solid.trim_by_plane([0, 0, -1], -z_b)-ext(shapely.unary_union(slits), z_b-b.sheet-1, z_b+1))
    if covers: parts['vented_covers'] = mf.Manifold.batch_boolean(covers, mf.OpType.Add)
    keep = {}
    for name, xr, a, b_, yr, p, q, za, zb in case.keepouts:
        bx = {'left': x0, 'right': x1, 'centre': (x0+x1)/2}[xr]; by = {'top': y1, 'bottom': y0}[yr]
        keep[name] = ext(box(bx+a, by+p, bx+b_, by+q), zbp+za, zbp+zb)
    return dict(z_b=z_b, floor_face=zp, border_plane=zbp, parts=parts, keepouts=keep, openings=ops, recess=rec)


def recess_page_parts(g, c: CollectorParams, case, margin: float = 40.0) -> dict:
    """The recessed bay as the preview page draws it (duct frame): build_recess_hardware's steel, with the border drawn as the
    pressed sheet it is (the panel at the border plane, `margin` mm round the recess, and the recess walls down to the floor)
    instead of the fit check's solid block; the keep-outs as boxes ({name, min, max}); labels ({text, pos}) for the slots
    that hold no card and for the keep-outs. Returns {parts: {name: Manifold}, keepouts, labels}."""
    from dataclasses import replace
    from .hardware import _cs as hcs, openings
    hw = build_recess_hardware(g, c, case); rec = hw['recess']; x0, y0, x1, y1 = rec.bounds; t = case.panel
    z_b, zbp = hw['z_b'], hw['border_plane']
    ext = lambda poly, za, zb: mf.Manifold.extrude(hcs(poly), zb-za).translate([0, 0, za])  # noqa: E731
    sheet = box(x0-margin, y0-margin, x1+margin, y1+margin).difference(rec)
    parts = dict(rear_panel=ext(sheet, zbp-t, zbp)+ext(rec.buffer(t, quad_segs=16).difference(rec), z_b, zbp),
                 **{k: m for k, m in hw['parts'].items() if k != 'border'})
    keep = [dict(name=k, min=[float(v) for v in m.bounding_box()[:3]], max=[float(v) for v in m.bounding_box()[3:]])
            for k, m in hw['keepouts'].items()]
    cs = case.for_pitch(g.pitch); cards = {k for sl in cs.card_slots for k in sl}; ops = openings(replace(c, card_pitch=g.pitch), cs)
    status = lambda k: 'cover' if k in cs.covers else 'louvred blank' if k in cs.vented_covers else 'open'  # noqa: E731
    labels = [dict(text=f"slot {k:+g} · {status(k)}".replace('+0 ', '0 '), pos=[(ops[k][0]+ops[k][1])/2, y0+case.recess_floor_band+12, z_b+1])
              for k in cs.slots if k not in cards]
    labels += [dict(text=f"keep-out · {k['name']}", pos=[(k['min'][0]+k['max'][0])/2, (k['min'][1]+k['max'][1])/2, k['max'][2]]) for k in keep]
    return dict(parts=parts, keepouts=keep, labels=labels)


def plug_fit_check(s, g, case) -> dict:
    """Intersections of the plug collector (+ its clips) with the bay and the keep-outs, placed as fitted."""
    c = s.params; hw = build_recess_hardware(g, c, case); dz = hw['z_b']+plug_placement(c, case)-c.inlet_z
    col = s.final.translate([0, 0, dz])
    if s.clips is not None: col = col+s.clips.translate([0, 0, dz])
    out = {k: round((col ^ m).volume(), 3) for k, m in {**hw['parts'], **hw['keepouts']}.items()}
    return dict(intersection_mm3=out, total_mm3=round(sum(out.values()), 3), dz=dz, border_plane=hw['border_plane'],
                plug_top_above_border_mm=round(c.inlet_z+dz+c.flange_thickness-hw['border_plane'], 3))


if __name__ == '__main__':
    import json, sys
    from pathlib import Path
    from ..params import COLLECTOR_V4A_SNAP, V29
    from .hardware import CASE_FRACTAL
    from ..print.printability import export_stl
    c = COLLECTOR_V4A_SNAP.for_duct(V29); out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    export_stl(build_plug_gauge(c, CASE_FRACTAL), out/'plug-fit-gauge.stl'); print(json.dumps(plug_gauge_facts(c, CASE_FRACTAL), indent=1))
