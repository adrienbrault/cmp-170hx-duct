"""Write the printable STL, fit gauge, profiles and checks for a built duct or exhaust collector."""
import json
from pathlib import Path

import manifold3d as mf
import numpy as np
import shapely
import trimesh
from shapely.geometry import Point, box

from ..params import GeometryParams
from .exhaust import flange_outline, section_at
from .geometry import DuctSolids

def stl_name(version='v23'): return f'dual-170hx-continuous-{version}.stl'
def fit_check_name(version='v23'): return f'dual-170hx-{version}-fit-check.stl'


STL = stl_name(); FIT_CHECK = fit_check_name()


def to_tri(s):
    assert s.status() == mf.Error.NoError and not s.is_empty()
    v = s.to_mesh64()
    return trimesh.Trimesh(vertices=np.asarray(v.vert_properties)[:, :3], faces=np.asarray(v.tri_verts), process=True)


def _export_stl(final, tolerances, path):
    """Simplify by the smallest tolerance whose serialized float32 STL is one watertight, consistently wound body.

    Bounded simplification removes collapsed microscopic triangles while staying well below print resolution.
    """
    # Last resort: keep the zero-height triangles. Dropping one whose three vertices are collinear opens a T-junction crack
    # (seen in the L = 55 mm shell); kept, it is a zero-area face that keeps the mesh closed.
    for keep_degenerate in (False, True):
        for tol in tolerances:
            cleaned = final.set_tolerance(tol).simplify(tol)
            export_mesh = cleaned.to_mesh64()
            m = trimesh.Trimesh(vertices=np.asarray(export_mesh.vert_properties)[:, :3].astype(np.float32).astype(np.float64), faces=np.asarray(export_mesh.tri_verts), process=False)
            m.merge_vertices(digits_vertex=6)
            if not keep_degenerate: m.update_faces(m.nondegenerate_faces(height=1e-8))
            m.update_faces(m.unique_faces()); m.remove_unreferenced_vertices()
            if not (m.is_watertight and m.is_winding_consistent and len(m.split()) == 1): continue
            m.export(path)
            check = trimesh.load(path)
            if check.is_watertight and check.is_winding_consistent and len(check.split()) == 1:
                return m, tol
    raise ValueError(f'No watertight float32 export within {tolerances[-1]} mm simplification tolerance')


def checks(g: GeometryParams, s: DuctSolids, m: trimesh.Trimesh, tol: float) -> dict:
    L = g.chamber_length; pocket_transition_end = L-g.pocket_transition
    c = dict(export_simplification_tolerance_mm=tol, watertight=m.is_watertight, one_connected_solid=len(m.split()) == 1, volume_mm3=float(m.volume), bounds_mm=m.bounds.tolist(),
                fan_plate_mm=[g.fan_plate, g.fan_plate, g.flange_thickness], inlet_diameter_mm=2*g.fan_radius, collar_wall_mm=g.collar_wall, shell_wall_mm=g.skin_wall,
                wall_method='Verified 1.6 mm outer skin with localized 6-8 mm internal corner fillets; connector-service trims locally reduce thickness',
                GPU_opening_mm=list(g.bore), plug_latch_sweep_collisions_mm3=s.plug_latch_collisions_mm3, connector_bay_collisions_mm3=s.bay_collisions_mm3,
                integral_return_top_depth_mm=g.return_top_depth, return_underside_ramp_start_mm=L-g.return_depth, connector_access="Open outer/top rims; lower and inner returns retained",
                housing_clearance_mm=list(g.housing_clear[2:]), local_latch_aperture_mm=list(g.latch_clear[2:]), physical_fit_tested=False,
                CFD_validation="Separate study; CAD export does not certify performance", chamber_length_mm=L, transition_end_mm=L,
                shoulder_rounding_max_mm=g.shoulder_radius, shoulder_rounding_at_service_end_mm=g.shoulder_radius-g.shoulder_radius_drop,
                passage_wall_fillet_max_mm=g.passage_radius, passage_wall_fillet_at_GPU_mm=g.passage_radius-g.passage_radius_drop,
                connector_service_policy="Contoured pocket around explicit straight plug/latch insertion sweep; oversized rectangular service trim removed",
                shoulder_axial_easing_fraction=g.bay_ramp_ease, pocket_transition_end_mm=pocket_transition_end, splitter_nose_front_width_mm=2*g.nose_tip_half_width,
                splitter_nose_radii_mm=[g.nose_radius_x, g.nose_radius_z], splitter_profile='symmetric cubic widening with elliptical nose',
                shoulder_axial_max_slope=(g.fan_radius-g.bay_floor_y)/(pocket_transition_end*(1-g.bay_ramp_ease)), upper_shoulder_requested_radius_mm=g.upper_radius,
                shape='upper shoulder blends plus broad 6-8 mm fillets at the marked passage-floor to side-wall creases; gentle pocket ramps; rounded central splitter',
                fan_front_to_GPU_face_mm=L+g.fan_thickness)
    if g.shell_from_air:
        c.update(wall_method=f'Uniform {g.wall_dilation} mm shell: the 3-D dilation of the rounded air volume, so every inside fillet is followed outside; connector-service trims locally reduce thickness',
                 shape='every convex air-section corner rounded (>= {0} mm, tapering to the seat); upper and lower bay fillets followed by the outer skin; {1} mm flange fillet; flush collars with rounded notch ends; rounded return outline and splitter groove'.format(g.section_radius, g.flange_fillet),
                 section_rounding_mm=g.section_radius, flange_fillet_mm=g.flange_fillet, splitter_groove_radius_mm=g.splitter_groove_radius, return_outline_radius_mm=g.return_round, collar_wall_mm=g.wall_dilation, shell_wall_mm=g.wall_dilation,
                 internal_air_volume_mm3=float(s.inner.volume()))
    if s.hub_fairing:
        c['hub_fairing'] = dict(s.hub_fairing, carried_by='the shared wall between the cards' if g.shared_wall else 'the splitter web',
                                hardware='the rim lands on the fan\'s flat rear motor-housing face, about 52 mm across (P12 Pro PST CO, photo against the 105 mm hole spacing, +-1 mm): 0.75 mm inside its edge')
    return c


def export_duct(s: DuctSolids, out_dir: Path, version: str = 'v23') -> dict:
    """Write the STL, fit gauge, profile JSONs, checks and generation log. Returns the checks."""
    g = s.params; L = g.chamber_length
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    raw = s.final.to_mesh64()
    v = np.asarray(raw.vert_properties)[:, :3]; f = np.asarray(raw.tri_verts)
    np.savez(out/'final-mesh-cache.npz', v=v, f=f)
    # Validate the serialized float32 STL, not only the in-memory solid; the
    # round trip resets the solid's internal state before simplification.
    final = mf.Manifold(mf.Mesh64(np.array(v, dtype=np.float64, order="C", copy=True), np.array(raw.tri_verts, dtype=np.uint64, order="C", copy=True)))
    m, tol = _export_stl(final, g.export_tolerances, out/stl_name(version))
    log = ' '.join(map(str, ['mesh', m.is_watertight, m.is_winding_consistent, len(m.split()), len(m.faces), 'export tolerance', tol]))+'\n'
    (out/f'{version}-upper-fillet-profile.json').write_text(json.dumps(s.upper_fillet_profile, indent=2))
    (out/f'{version}-passage-fillet-profile.json').write_text(json.dumps(s.passage_fillet_profile, indent=2))
    (out/f'{version}-splitter-profile.json').write_text(json.dumps(s.splitter_profile, indent=2))
    gauge = final.trim_by_plane([0, 0, 1], L+g.fit_check_height).translate([0, 0, -L-g.fit_check_height])
    q = to_tri(gauge)
    if not q.is_watertight:  # trimesh's vertex merge can pinch a thin-collar corner; keep manifold's own topology
        raw_gauge = gauge.to_mesh64()
        q = trimesh.Trimesh(np.asarray(raw_gauge.vert_properties)[:, :3], np.asarray(raw_gauge.tri_verts), process=False)
    assert q.is_watertight and len(q.split()) == (1 if g.shared_wall else 2)   # the shared wall joins the two collars
    q.export(out/fit_check_name(version))
    c = checks(g, s, m, tol)
    (out/f'{version}-checks.json').write_text(json.dumps(c, indent=2))
    (out/f'{version}-section-areas.json').write_text(json.dumps(s.section_areas, indent=2))
    (out/'generation.log').write_text(log+json.dumps(c, indent=2)+'\n')
    return c


def collector_names(version='collector-v1'):
    return f'dual-170hx-{version}.stl', f'dual-170hx-{version}-fit-gauge.stl'


def collector_checks(s) -> dict:
    """CAD-side numbers of a built collector (duct.cad.exhaust.CollectorSolids): layout, areas, protrusion."""
    c = s.params; D = c.plenum_depth; z0 = c.inlet_z
    mouth, fan = s.sections[0], s.sections[-1]
    bore = np.pi*c.fan_radius**2; hub = np.pi*(c.fan_hub_diameter/2)**2
    openings = sum((x1-x0)*(y1-y0) for x0, x1, y0, y1 in c.openings)
    middle = c.openings[len(c.openings)//2] if len(c.openings) % 2 else None   # 3-slot pitch: the empty slot between the cards
    if c.split: return {**_split_checks(s, mouth, fan, bore, hub, openings, middle), 'inner': dict(volume_mm3=float(s.inner.volume()),
                        triangles=int(s.inner.num_tri()), genus=int(s.inner.genus()))}
    # Steepest air-wall angle from the axis, at the mid-sides and at the window-corner diagonal
    s_ = np.linspace(0, D-c.fan_plate_thickness, 2001); abr = np.array([section_at(c, v) for v in s_])
    diag = np.hypot(abr[:, 0]-abr[:, 2], abr[:, 1]-abr[:, 2])+abr[:, 2]
    slope = lambda r: float(np.degrees(np.arctan(np.max(np.abs(np.gradient(r, s_))))))  # noqa: E731
    return dict(
        frame='duct frame: x across the cards, y along the card height (+y = card top edge / bracket tab end), z along the card axis',
        inlet_plane_z_mm=z0, fan_face_z_mm=z0+D, print_orientation='flange (case face) on the bed; STL z = duct z - inlet_plane_z',
        window_mm=dict(x=list(c.window_x), y=list(c.window_y), corner_radius=c.window_corner_radius), fan_axis_mm=list(c.fan_axis),
        derived_chassis_openings_mm=[list(o) for o in c.openings], bracket_top_y_mm=c.bracket_top_y,
        flange_mm=dict(bounds=list(flange_outline(c).bounds), thickness=c.flange_thickness, overlap_x_minus_y_plus_y=list(c.flange_overlap)),
        gasket_groove_mm=dict(width=c.gasket_width, depth=c.gasket_depth, inner_offset_from_window=c.gasket_lip),
        plenum_depth_mm=D, wall_mm=c.wall, fan_plate_mm=[c.fan_size, c.fan_size, c.fan_plate_thickness], fan_bore_diameter_mm=2*c.fan_radius,
        fan_hole_pitch_mm=2*c.fan_hole_offset, fan_hole_diameter_mm=2*c.fan_hole_radius, fan_hub_diameter_mm=c.fan_hub_diameter,
        areas_mm2=dict(mouth=mouth['area_mm2'], fan_bore=bore, fan_annulus=bore-hub, derived_openings_total=openings, fan_end_section=fan['area_mm2']),
        area_ratios=dict(fan_bore_over_mouth=bore/mouth['area_mm2'], fan_annulus_over_mouth=(bore-hub)/mouth['area_mm2'], fan_annulus_over_openings=(bore-hub)/openings),
        steepest_air_wall_deg=dict(mid_side_x=slope(abr[:, 0]), mid_side_y=slope(abr[:, 1]), corner_diagonal=slope(diag)),
        hub_shadow=_hub_shadow(c, middle),
        protrusion_mm=dict(collector=D, fan=c.fan_thickness, total_behind_rear_panel=D+c.fan_thickness, note='plus the compressed gasket (~0.5-1 mm)'),
        mount=dict(mode=c.mount, points_mm=[list(p) for p in s.features['mount_points']]), cable_notch_bounds_mm=s.features['cable_notch_bounds'],
        inner=dict(volume_mm3=float(s.inner.volume()), triangles=int(s.inner.num_tri()), genus=int(s.inner.genus())),
        physical_fit_tested=False, hardware_measured=False, CFD_status='not run')


def _hub_shadow(c, middle) -> dict:
    """What the fan hub (no flow) sits in front of: the opening between the cards (3-slot pitch: an empty slot), and the live
    vents (must_open) under its disc. At the 2-slot pitch the openings are even in number: the hub sits on the rib between
    the cards and shadows both cards' inner vents."""
    r = c.fan_hub_diameter/2; ax = c.fan_axis[0]; disc = Point(c.fan_axis).buffer(r, quad_segs=64)
    live = shapely.unary_union([box(x0, y0, x1, y1) for x0, x1, y0, y1 in c.must_open]).intersection(disc)
    if middle is not None: live = live.difference(box(middle[0], middle[2], middle[1], middle[3]))   # the empty slot is not a vent
    live = live.area
    out = dict(hub_radius_mm=r)
    if middle is not None:
        out.update(middle_opening_x_mm=[middle[0], middle[1]],
                   hub_covers_middle_opening_width=bool(max(abs(middle[0]-ax), abs(middle[1]-ax)) <= r))
    return {**out, 'live_vents_under_hub_mm2': round(float(live), 1)}


def _split_checks(s, mouth, fan, bore, hub, openings, middle) -> dict:
    """collector_checks for the split collector (per-card mouths, one plenum with a splitter fin)."""
    from .exhaust import card_mouths, gasket_loops, split_end, web_x
    c = s.params; D = c.plenum_depth; z0 = c.inlet_z
    raw = s.inner.to_mesh64(); v = np.asarray(raw.vert_properties)[:, :3]; f = np.asarray(raw.tri_verts)
    n = np.cross(v[f[:, 1]]-v[f[:, 0]], v[f[:, 2]]-v[f[:, 0]]); a = np.linalg.norm(n, axis=1); n = n[a > 1e-9]/a[a > 1e-9, None]
    side = np.abs(n[:, 2]) < .999
    return dict(
        frame='duct frame: x across the cards, y along the card height (+y = card top edge / bracket tab end), z along the card axis',
        inlet_plane_z_mm=z0, fan_face_z_mm=z0+D, print_orientation='flange (case face) on the bed; STL z = duct z - inlet_plane_z',
        layout='split: one mouth and one gasket loop per card; the middle slot lies under the flange web, outside both loops',
        card_mouths_mm=[list(m) for m in card_mouths(c)], gasket_loops_inner_mm=[list(p.bounds) for p in gasket_loops(c)],
        fan_axis_mm=list(c.fan_axis), derived_chassis_openings_mm=[list(o) for o in c.openings], must_open_mm=[list(o) for o in c.must_open],
        bracket_top_y_mm=c.bracket_top_y, flange_mm=dict(bounds=list(flange_outline(c).bounds), thickness=c.flange_thickness,
                                                         overlap_x_minus_y_plus_y=list(c.flange_overlap)),
        gasket_groove_mm=dict(width=c.gasket_width, depth=c.gasket_depth, lip_sides_bottom=c.gasket_lip, lip_top=c.gasket_lip_top),
        splitter_fin_mm=dict(x=web_x(c), thickness=c.fin_thickness, top_z=z0+split_end(c), below_fan_face=D-split_end(c)),
        plenum_depth_mm=D, wall_mm=c.wall, fan_plate_mm=[c.fan_size, c.fan_size, c.fan_plate_thickness], fan_bore_diameter_mm=2*c.fan_radius,
        fan_hole_pitch_mm=2*c.fan_hole_offset, fan_hole_diameter_mm=2*c.fan_hole_radius, fan_hub_diameter_mm=c.fan_hub_diameter,
        fan_frame_below_board_plane_mm=(c.bracket_top_y-108.21)-(c.fan_axis[1]-c.fan_size/2),
        areas_mm2=dict(mouths=mouth['area_mm2'], fan_bore=bore, fan_annulus=bore-hub, derived_openings_total=openings, fan_end_section=fan['area_mm2']),
        area_ratios=dict(fan_bore_over_mouths=bore/mouth['area_mm2'], fan_annulus_over_mouths=(bore-hub)/mouth['area_mm2']),
        steepest_air_wall_deg=float(np.degrees(np.arcsin(np.max(np.abs(n[side, 2]))))) if c.vane_style != 'v4' else None,
        hub_shadow={**_hub_shadow(c, middle), 'fin_x_mm': web_x(c), 'hub_covers_fin': bool(abs(web_x(c)-c.fan_axis[0]) < c.fan_hub_diameter/2)},
        protrusion_mm=dict(collector=D, fan=c.fan_thickness, total_behind_rear_panel=D+c.fan_thickness, note='plus the compressed gasket (~0.5-1 mm)'),
        mount=dict(mode=c.mount, points_mm=[list(p) for p in s.features['mount_points']]), cable_notch_bounds_mm=s.features['cable_notch_bounds'],
        **(dict(steepest_air_face_deg_incl_fin_tops_and_roots=float(np.degrees(np.arcsin(np.max(np.abs(n[side, 2]))))),
                steepest_air_wall_note='v4: the plenum walls are v4.plenum_wall_deg (peak <= max_wall_angle); the raw face maximum includes '
                                       'the fins\' round tops and root fillets, which face up') if c.vane_style == 'v4' else {}),
        **(_v4_checks(s) if c.vane_style == 'v4' or c.flange_mode == 'windowed' else {}),
        physical_fit_tested=False, hardware_measured=False, CFD_status='not run')


def _v4_checks(s) -> dict:
    """collector_checks additions for v4 (docs/collector-v4-plan.md): fan budget, plenum wall angles against max_wall_angle,
    the curves (lip, corner radii, bell), the vanes, the open-slot windows and magnets."""
    from .exhaust import FIN_END_GAP, air_wall_angles, hub_fairing, lip_offset, snap_dims, snap_numbers, snap_sites, mouth_radii, mouths, outer_slots, slot_windows, split_section, split_top, vanes
    c = s.params; D = c.plenum_depth; tf = c.flange_thickness; se = D-c.fan_plate_thickness
    ss = np.linspace(tf, se, 301); b = np.array([split_section(c, v).bounds for v in ss])   # x0, y0, x1, y1
    deg = lambda y: np.degrees(np.arctan(np.abs(np.gradient(y, ss))))  # noqa: E731
    walls = {k: deg(b[:, i]) for k, i in (('x_minus', 0), ('bottom', 1), ('x_plus', 2), ('top', 3))}
    s_hold = c.top_dip[2]; rise = split_top(c, se)-split_top(c, s_hold)
    top = dict(hold_until_s_mm=s_hold, rise_mm=float(rise), mean_deg=float(np.degrees(np.arctan(rise/(se-s_hold)))), peak_deg=float(walls['top'].max()))
    peak = max(float(w.max()) for w in walls.values()); faces = air_wall_angles(c)
    ends = {k: float(w[-5:].max()) for k, w in walls.items()}       # the bell: the walls arrive (near) vertical at the plate
    vs = []
    for name, _, v in vanes(c):
        prof = np.array(v['profile']); cx = (prof[:, 1]+prof[:, 2])/2; body = prof[:, 0] < v['top_s']-c.fin_thickness/2
        lean = np.degrees(np.arctan(np.abs(np.gradient(cx[body], prof[body, 0])))).max() if body.sum() > 2 else 0.0
        vs.append(dict(name=name, x_mm=float(v['x']), thickness_mm=c.fin_thickness, top_from_bracket_plane_mm=float(v['top_s']),
                       top_below_fan_face_mm=float(D-v['top_s']), top='full round r %.1f' % (c.fin_thickness/2), root=v['root'],
                       root_height_mm=round(float(v.get('H', c.vane_root)), 2), root_min_radius_mm=round(float(v.get('min_radius', v.get('radius', 0.0))), 2),
                       lean_mm=float(v.get('lean', 0.0)), steepest_lean_deg=round(float(lean), 1), ends_off_walls_mm=FIN_END_GAP))
    vent = []
    for o, w in zip(outer_slots(c), slot_windows(c) or [None, None]):
        q = box(o[0], o[2], o[1], o[3]); left = q.difference(flange_outline(c)).area
        vent.append(dict(opening_mm=list(o), window_mm=list(w.bounds) if w is not None else None, area_mm2=round(q.area, 1),
                         open_area_left_mm2=round(left, 1), fraction=round(left/q.area, 4)))
    return dict(
        v4=dict(frame_bottom_below_board_mm=round(c.frame_bottom_below_board_mm, 3), board_plane_y_mm=c.board_y,
                protrusion_behind_panel_mm=D+c.fan_thickness, max_wall_angle_deg=c.max_wall_angle,
                plenum_wall_deg=dict(peak=max(faces['ceiling']['peak_deg'], faces['floor']['peak_deg']), faces=faces, section_bounds_peak=peak, top=top,
                                     **{f'{k}_peak': float(w.max()) for k, w in walls.items() if k != 'top'}, at_fan_plate=ends,
                                     note='peak: the steepest air wall from triangle normals (ceiling: faces looking down, the inner '
                                          'skin overhangs; floor: faces looking up, the air widens, an outer skin parallel to it overhangs). '
                                          'section_bounds_peak: the bounding-box slopes, which miss a corner moving in x and y at once'),
                curves=dict(inlet_lip_mm=c.lip, lip_edges='sides and bottom (none on top: slot-screw tips)', lip_offset_at_flange_top_mm=round(lip_offset(c, tf), 3),
                            web_round_mm=c.web_round if c.web_round else None, mouth_corner_radii_mm=[list(r) for r in mouth_radii(c)],
                            section_corners_grow_to_mm=c.corner_end, by_fraction_of_depth=c.corner_reach, ramp_ease=c.ease_ramp, top_rise_ease=c.top_rise_ease,
                            body_flange_fillet_mm=c.flange_fillet, body_flange_fillet_top_mm=c.flange_fillet_top if c.flange_fillet_top >= 0 else c.flange_fillet,
                            flange_corner_radius_mm=c.flange_corner_radius, flange_top_round_mm=c.flange_top_round, slot_window_radius_mm=c.slot_window_radius,
                            fan_plate_corner_radius_mm=c.fan_plate_corner_radius),
                mouths_mm=[list(m) for m in mouths(c)], vanes=vs, open_slot_vent_area=vent,
                hub_fairing=hub_fairing(c)[1] if c.hub_fairing else None,
                magnets=dict(n=len(s.features['mount_points']), size='%g x %g mm N52 disc' % (c.magnet_diameter, c.magnet_thickness)) if c.mount == 'magnets' else None,
                snap=dict(**snap_numbers(c), sites=snap_sites(c), dims={k: v for k, v in snap_dims(c).items() if k != 'profile'},
                          profile_u_s_mm=[[float(a), float(b)] for a, b in snap_dims(c)['profile']]) if c.mount == 'snap' else None))


def export_collector(s, out_dir, version='collector-v1') -> dict:
    """Write the collector STL (print frame) and the fit-gauge STL; return the CAD-side checks plus export facts."""
    c = s.params; out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    stl, gauge = collector_names(version)
    m, tol = _export_stl(s.final.translate([0, 0, -c.inlet_z]), c.export_tolerances, out/stl)
    g, gtol = _export_stl(s.gauge, c.export_tolerances, out/gauge)
    extra = {}
    if getattr(s, 'clips', None) is not None:   # mount 'snap': one clip, print orientation (print 4)
        from .exhaust import snap_clip
        k, _ = _export_stl(snap_clip(c), c.export_tolerances, out/snap_clip_name(version))
        extra['snap_clip'] = dict(file=snap_clip_name(version), count=len(s.features['snap']['sites']), triangles=len(k.faces),
                                  volume_mm3=float(k.volume), bounds_mm=k.bounds.tolist())
    return dict(collector_checks(s), export_simplification_tolerance_mm=tol, triangles=len(m.faces), volume_mm3=float(m.volume), bounds_mm=m.bounds.tolist(),
                fit_gauge=dict(triangles=len(g.faces), volume_mm3=float(g.volume), bounds_mm=g.bounds.tolist(), thickness_mm=c.gauge_thickness), **extra)


def snap_clip_name(version):
    return f'dual-170hx-{version}-snap-clip.stl'
