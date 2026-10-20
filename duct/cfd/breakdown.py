"""Mass-weighted pressure breakdown of a solved aligned case, latest time.

Stations: the inlet (fan patch, or the faceZone a base cell past an intake actuator disk), seatUp (whole duct section
just before the seat face, when the case has it), the per-card cuts
written by duct.cfd.case.topo_set (cardEntry upstream of the fins, cardBracket upstream of the bracket plate or
grille slab, cardExit the per-card flux cut), bracketDown (whole section a base cell past the bracket plane) and
the exit (exhaust fan patch or disk station, still-air far field, or the legacy card outlet patches). Each
station's static and total pressure is averaged with phi weights; cards combine by flow. Pressures in Pa (the
case's kinematic values × fan.RHO).

network.py terms (fan-annulus velocity heads): its system curve ends at static 0 on the card exits, so the bracket
term is the static pressure upstream of the bracket over ambient, and the push-pull collector term is that static
pressure less the exhaust fan's inlet total pressure (-p_sF), less the bracket term.
"""
import re
from pathlib import Path

from .. import env, network
from . import fan
from .collector import CASE_AIR
from .run import case_meta, latest_time

PLANES = ("cardEntry", "cardBracket", "cardExit")
WHOLE_SECTION = ("seatUp", "bracketDown")   # whole-section faceZones (case.Planes.duct_stations / stations), when the case has them


def _fo(name: str, region: str, kind: str) -> str:
    common = f"type surfaceFieldValue; libs (fieldFunctionObjects); regionType {kind}; name {region}; writeFields false;"
    return (f" {name}Avg {{{common} operation weightedAverage; weightField phi; fields (p pt);}}\n"
            f" {name}Q {{{common} operation sum; fields (phi);}}\n")


def run(case: Path) -> dict:
    """Run the breakdown postProcess on the reconstructed latest time (serial) and parse it."""
    case = Path(case)
    meta = case_meta(case)
    inlet, exits = stations(meta)
    fos = " ptot {type pressure; libs (fieldFunctionObjects); mode total; rho rhoInf; rhoInf 1; result pt;}\n"
    kind = lambda r: "faceZone" if r.startswith(("intakeFan", "exhaustFan")) else "patch"  # noqa: E731
    fos += _fo(inlet, inlet, kind(inlet))
    for plane in PLANES:
        for card in (0, 1):
            fos += _fo(f"{plane}{card}", f"{plane}{card}", "faceZone")
    for name in (meta.get("planes_mm") or {}):
        if name in WHOLE_SECTION:
            fos += _fo(name, name, "faceZone")
    for e in exits:
        fos += _fo(e, e, kind(e))
    if CASE_AIR in meta["patches"]:
        fos += _fo(CASE_AIR, CASE_AIR, "patch")
    (case / "system/breakdownDict").write_text(
        "FoamFile {version 2.0; format ascii; class dictionary; object breakdownDict;}\nfunctions\n{\n" + fos + "}\n")
    log = case / "log.breakdown"
    env.foam(f"postProcess -dict system/breakdownDict -time {latest_time(case)} -fields '(p U phi)'", cwd=case, log=log)
    return parse(log, exits, meta, inlet)


def stations(meta: dict) -> tuple[str, list[str]]:
    """Inlet and exit regions: the fan patches, or with actuator disks the faceZones a base cell downstream of the
    intake disk and upstream of the exhaust disk (the far fields sit outside the fans)."""
    from .disk import EXHAUST, INTAKE, STATIONS  # noqa: PLC0415
    opts, patches = meta.get("options", {}), meta["patches"]
    disk = opts.get("fan_model") == "disk"
    inlet = STATIONS[INTAKE][0] if disk and opts.get("rpm") else "inlet"
    if disk and opts.get("pull_rpm"):
        return inlet, [STATIONS[EXHAUST][0]]
    return inlet, ["exhaust"] if "exhaust" in patches else ["outletLeft", "outletRight"]


def parse(log: Path, exits: list[str], meta: dict, inlet: str = "inlet") -> dict:
    text = Path(log).read_text()
    val = lambda op, region, field: float(re.findall(  # noqa: E731
        rf"^\s*{op}\({region}\) of {field} = (\S+)", text, re.M)[-1])

    def station(regions: list[str]) -> dict:
        qs = [val("sum", r, "phi") for r in regions]
        q = sum(qs)
        avg = lambda f: sum(qi * val("weightedAverage", r, f) for qi, r in zip(qs, regions)) / q * fan.RHO  # noqa: E731
        cards = lambda f: [val("weightedAverage", r, f) * fan.RHO for r in regions] if len(regions) > 1 else None  # noqa: E731
        return dict(q_m3s=abs(q), p_pa=avg("p"), pt_pa=avg("pt"), q_cards_m3s=qs if len(qs) > 1 else None,
                    p_cards_pa=cards("p"), pt_cards_pa=cards("pt"))

    st = {"inlet": station([inlet])}
    planes_mm = meta.get("planes_mm") or {}
    if "seatUp" in planes_mm:
        st["seatUp"] = station(["seatUp"])
    for plane in PLANES:
        st[plane] = station([f"{plane}0", f"{plane}1"])
    if "bracketDown" in planes_mm:
        st["bracketDown"] = station(["bracketDown"])
    st["exit"] = station(exits)
    if CASE_AIR in meta["patches"]:   # the open middle slot: case air the exhaust fan draws past the fins
        st[CASE_AIR] = station([CASE_AIR])
    Q = st["inlet"]["q_m3s"]
    pt = {k: v["pt_pa"] for k, v in st.items()}
    down = "bracketDown" if "bracketDown" in st else "cardExit"
    drops = dict(intake_duct=pt["inlet"] - pt["cardEntry"], cards=pt["cardEntry"] - pt["cardBracket"],
                 bracket=pt["cardBracket"] - pt[down], downstream=pt[down] - pt["exit"])
    if "seatUp" in st:   # intake_duct = duct (fan side to seatUp, the duct's own loss) + card_face (seatUp to cardEntry)
        drops |= dict(duct=pt["inlet"] - pt["seatUp"], card_face=pt["seatUp"] - pt["cardEntry"])
    q_ann = 0.5 * network.RHO * (Q / network.FAN_AREA) ** 2
    p_up = st["cardBracket"]["p_pa"]
    calib = dict(q_annulus_pa=q_ann, upstream_pa=pt["inlet"] - p_up,
                 upstream_system_curve_pa=network.SYSTEM_A * Q + network.SYSTEM_B * Q * Q)
    exhaust = meta.get("exhaust") or {}
    if exits == ["exhaustFanUpstream"]:  # actuator disk: the station's own total pressure
        fan_inlet_pt = pt["exit"]
    elif exits == ["exhaust"] and exhaust.get("area_m2") and exhaust.get("rpm"):
        # fanPressure out fixes a uniform static pressure; the fan curve assumed the uniform velocity head on the
        # exhaust patch, so the modelled fan-inlet total pressure (= -p_sF) is static + that head. A peaked
        # fan-face profile carries more kinetic energy out than that: a collector loss ("exhaust_profile").
        fan_inlet_pt = st["exit"]["p_pa"] + 0.5 * fan.RHO * (Q / exhaust["area_m2"]) ** 2
        drops["exhaust_profile"] = pt["exit"] - fan_inlet_pt
    else:  # no exhaust fan: ambient static past the bracket (still air) or the legacy outlets
        fan_inlet_pt = None
        calib["bracket_k"] = p_up / q_ann
    if fan_inlet_pt is not None:
        calib |= dict(fan_inlet_pt_pa=fan_inlet_pt, collector_k_station_with_bracket=(p_up - fan_inlet_pt) / q_ann)
    else:
        calib["bracket_k_station"] = calib.pop("bracket_k")
    # network.py's terms are flow-consistent: the heads that make network.evaluate() reproduce this Q with these
    # fans (the plate also redistributes flow among the porous paths upstream of the bracket stations, so the
    # station values above are diagnostics). The network has no path past the fins: with the middle slot open the
    # exhaust fan carries the case air too, and its collector term is not a calibration.
    opts = meta.get("options", {})
    s0 = network.Setup(rpm=opts.get("rpm", 2500), stacked=opts.get("fans", 1),
                       stack_efficiency=opts.get("stack_efficiency", fan.STACK_EFFICIENCY), pull_rpm=opts.get("pull_rpm"),
                       bracket_k=0.0, collector_k=0.0, grille_open_area=1.0)
    pull_fan = fan.MODELS[(meta.get("exhaust") or {}).get("model") or fan.P12_PRO.name]
    k_flow = (network.available_pressure(Q, s0, pull_fan) - network.system_pressure(Q, s0)) / q_ann
    if opts.get("pull_rpm"):
        calib |= dict(collector_k_with_bracket=k_flow, bracket_k=network.BRACKET_K,
                      collector_k=k_flow - network.BRACKET_K)
    else:
        calib["bracket_k"] = k_flow
    grille = None
    if grilles := meta.get("grille_zones"):
        a_ports = sum((hi[0] - lo[0]) * (hi[1] - lo[1]) for lo, hi in (z["box"] for z in meta["zone_coefficients"]))
        grille = dict(open_area=grilles[0]["open_area"], K=grilles[0]["K"],
                      model_drop_pa=grilles[0]["K"] * 0.5 * fan.RHO * (Q / a_ports) ** 2)
    return dict(q_m3s=Q, stations=st, total_pressure_drops_pa=drops, grille=grille, network=calib)
