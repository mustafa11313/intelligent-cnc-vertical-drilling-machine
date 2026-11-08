"""Electrical enclosure layout for the drilling machine.

    python3 electrical_box.py      # step/electrical_box.step + electrical_box.png

Replaces the open wooden board (electronics/README.md, problem 1). Everything
in electronics/diagrams/6_system_overview.png goes into one earthed steel
wall box, with the mains and VFD side kept apart from the signal side
(problem 4, EMI). Parts are boxes with the real outside dimensions of the
named parts (from their datasheets; check the ones you buy, sizes vary by
seller and by VFD rating).

Frame: x to the right, y up, z out of the mounting plate towards the door,
origin at the bottom-left corner of the plate's front face. The script
checks that no two parts overlap on the plate, that every part clears the
door and the door devices, and works out the heat rise.
"""
import os

import cadquery as cq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------- enclosure
BOX_W, BOX_H, BOX_D = 400.0, 500.0, 210.0      # steel wall box, IP55/IP66, e.g. 40x50x21 cm
WALL = 1.2
PLATE_W, PLATE_H, PLATE_T = 360.0, 460.0, 2.5  # galvanised mounting plate
PLATE_OFF = 12.0                               # standoffs behind the plate
PX0, PY0 = (BOX_W - PLATE_W) / 2, (BOX_H - PLATE_H) / 2       # plate in box coordinates
Z_DOOR = BOX_D - WALL - (WALL + PLATE_OFF + PLATE_T)           # inner door face, from the plate face: 193.1

DIN = 35.0                                      # TS35 rail
GAP = 2.0                                       # minimum gap between parts on the plate

# name, label, x, y, w, h, d, group. (x, y) = bottom-left on the plate, d = height above the plate.
# group: mains (230 V), drive (VFD output / motor power), signal (5-24 V), duct, earth
PARTS = []


def part(name, label, x, y, w, h, d, group):
    PARTS.append(dict(name=name, label=label, x=x, y=y, w=w, h=h, d=d, group=group))


# wiring ducts, 40 x 40 slotted
part("duct_top", "duct", 0, 425, 360, 35, 40, "duct")
part("duct_mid", "duct", 0, 288, 360, 35, 40, "duct")
part("duct_low", "duct", 0, 108, 360, 35, 40, "duct")
part("duct_split", "duct", 228, 143, 25, 145, 40, "duct")      # vertical: separates VFD/PSU from signal

# DIN rail row (rail centre y 375): incoming mains on the left, then control
ROW = 375.0
part("din_rail", "TS35 rail", 5, ROW - DIN / 2, 350, DIN, 7.5, "earth")
x = 8.0
for name, label, w, h, d, g in [
    ("X1_mains", "X1 mains in\nL N PE", 3 * 5.2, 45, 47, "mains"),
    ("Q1_mcb", "Q1 MCB 2P\nC10", 36, 85, 70, "mains"),
    ("K1_contactor", "K1 contactor\n24VDC coil\n3NO+1NO", 45, 58, 57, "mains"),
    ("PE_bar", "PE bar", 6 * 6.2, 45, 47, "earth"),
    ("F1_fuse", "F1 24V\n5A", 18, 81, 60, "signal"),
    ("F2_fuse", "F2 5V\n1A", 18, 81, 60, "signal"),
    ("X2_ctrl", "X2 control\nE-stop, Start\nVFD MA/MC", 10 * 5.2, 45, 47, "signal"),
]:
    part(name, label, x, ROW - h / 2, w, h, d, g)
    x += w + 6
ROW_END = x

# power zone, middle left
part("U1_vfd", "U1 VFD\nYaskawa J1000\n0.55 kW 1-ph\n(size: check its label)", 6, 152, 108, 128, 138, "drive")
part("G1_psu", "G1 PSU\n24V 100W\n(e.g. LRS-100-24)", 122, 150, 97, 129, 30, "mains")

# signal zone, middle right
part("A1_grbl", "A1 Nano\nGRBL\n(DIN carrier)", 260, 222, 45, 60, 25, "signal")
part("A2_daq", "A2 Nano\nDAQ\n(DIN carrier)", 310, 222, 45, 60, 25, "signal")
part("K2_relay", "K2 relay\nspindle run", 260, 182, 45, 34, 20, "signal")
part("K3_relay", "K3 relay\nlight", 310, 182, 45, 34, 20, "signal")
part("U2_pwm", "U2 PWM\nto 0-10 V", 260, 148, 45, 28, 18, "signal")
part("U3_buck", "U3 LM2596\n24 to 5 V", 310, 148, 45, 28, 18, "signal")

# bottom: stepper drivers, fins vertical, and the field terminals
for i, ax in enumerate("XYZ"):
    part(f"D{i + 1}_tb6600", f"D{i + 1} TB6600\n{ax} axis", 10 + i * 77, 6, 71, 96, 37, "drive")
part("X3_field", "X3 field\nmotors,\nsensors,\nDS18B20,\nADXL345", 240, 8, 16 * 7.0, 90, 47, "signal")

# door devices, in plate coordinates (centre x, y, head diameter, depth behind the door)
DOOR = [
    ("S0_estop", "S0 E-stop\n2 NC, latching", 300, 380, 40, 70, "#c62828"),
    ("S1_start", "S1 Start (NO)", 300, 330, 30, 50, "#2e7d32"),
    ("H1_lamp", "H1 Power", 255, 330, 22, 45, "#f9a825"),
]

# glands in the bottom wall: x along the box, diameter, use
GLANDS = [
    (40, 25, "M25 mains in"),
    (80, 20, "M20 EMC: VFD to spindle\n(shield 360 deg)"),
    (150, 20, "M20 X motor"),
    (185, 20, "M20 Y motor"),
    (220, 20, "M20 Z motor"),
    (265, 16, "M16 sensors"),
    (300, 16, "M16 spindle sensors"),
    (345, 25, "M25 split gland\n2x USB"),
]

# heat sources (W) for the temperature rise
LOSSES = {"VFD 0.55 kW (~6 %)": 35.0, "3 TB6600 at 1.5 A": 15.0, "PSU at ~50 W": 8.0,
          "contactor coil, Nanos, relays": 5.0}
K_STEEL = 5.5                                   # W/m2K, painted steel, still air


# ---------------------------------------------------------------- checks
def overlaps(a, b):
    return not (a["x"] + a["w"] + GAP <= b["x"] or b["x"] + b["w"] + GAP <= a["x"]
                or a["y"] + a["h"] + GAP <= b["y"] or b["y"] + b["h"] + GAP <= a["y"])


def check():
    ok = True
    for i, a in enumerate(PARTS):
        if a["x"] < 0 or a["y"] < 0 or a["x"] + a["w"] > PLATE_W or a["y"] + a["h"] > PLATE_H:
            print(f"  {a['name']} is off the plate"); ok = False
        for b in PARTS[i + 1:]:
            if "din_rail" in (a["name"], b["name"]):
                continue                                         # the row parts clip onto it
            if a["group"] == b["group"] == "duct":
                continue                                         # ducts join
            if overlaps(a, b):
                print(f"  {a['name']} overlaps {b['name']}"); ok = False
        if a["d"] > Z_DOOR - 10:
            print(f"  {a['name']} is {a['d']} deep, door at {Z_DOOR:.0f}"); ok = False
    for name, _, cx, cy, dia, depth, _ in DOOR:
        r = max(dia, 30) / 2                                     # contact blocks ~30 mm square
        for a in PARTS:
            under = a["x"] - r < cx < a["x"] + a["w"] + r and a["y"] - r < cy < a["y"] + a["h"] + r
            if under and a["d"] + depth > Z_DOOR - 10:
                print(f"  {name} ({depth} deep) hits {a['name']} ({a['d']} deep)"); ok = False
    if ROW_END > PLATE_W - 5:
        print(f"  the DIN row is {ROW_END:.0f} mm long"); ok = False
    return ok


def heat():
    p = sum(LOSSES.values())
    w, h, d = BOX_W / 1000, BOX_H / 1000, BOX_D / 1000
    area = w * h + 2 * h * d + 2 * w * d                         # wall-mounted: the back does not count
    dt = p / (K_STEEL * area)
    flow = 3.1 * p / 10.0                                        # m3/h for a 10 K rise
    return p, area, dt, flow


# ------------------------------------------------------------------ STEP
def to_box(x, y, z=0.0):
    """Plate coordinates to enclosure coordinates (origin at the back-bottom-left corner)."""
    return (PX0 + x, PY0 + y, WALL + PLATE_OFF + PLATE_T + z)


def solid_box(x, y, z, w, h, d):
    return cq.Workplane("XY").box(w, h, d, centered=False).translate((x, y, z))


DOOR_ANGLE = -105.0                             # door swung open about its left hinge


def _place(w, x, y, z=0.0, R=None):
    """Workplane in a part's local frame -> box coordinates (part origin at plate point x, y, z)."""
    import numpy as np
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    bx, by, bz = to_box(x, y, z)
    R = np.eye(3) if R is None else np.asarray(R, float)
    t = gp_Trsf()
    t.SetValues(*map(float, (R[0, 0], R[0, 1], R[0, 2], bx, R[1, 0], R[1, 1], R[1, 2], by,
                             R[2, 0], R[2, 1], R[2, 2], bz)))
    return BRepBuilderAPI_Transform(w.val().wrapped, t, True).Shape()


R_OUT = {"-y": [[1, 0, 0], [0, 0, -1], [0, 1, 0]], "-x": [[0, 0, -1], [0, 1, 0], [1, 0, 0]],
         "+x": [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]}


def build_parts():
    """Every part as a real shape in box coordinates: [(name, TopoDS_Shape, rgb)]."""
    import elec_parts as E
    out = []

    def add(items, x, y, z=0.0, R=None, prefix=""):
        for n, w, c in items:
            out.append((prefix + n, _place(w, x, y, z, R), c))

    # enclosure: body with folded front lip, gland holes, fan cut-outs
    shell = solid_box(0, 0, 0, BOX_W, BOX_H, BOX_D - 20).cut(
        solid_box(WALL, WALL, WALL, BOX_W - 2 * WALL, BOX_H - 2 * WALL, BOX_D))
    shell = shell.edges("|Z").fillet(4)
    for gx, gd, _ in GLANDS:
        shell = shell.cut(cq.Workplane("XZ").center(gx, BOX_D / 2).circle(gd / 2 + 0.5).extrude(-5).translate((0, -1, 0)))
    for x0 in (-1, BOX_W - WALL - 1):
        y0 = PY0 + 20 if x0 < 0 else BOX_H - PY0 - 145
        shell = shell.cut(solid_box(x0, y0, BOX_D / 2 - 62.5, WALL + 2, 125, 125))
    out.append(("enclosure 400x500x210 RAL7035", shell.val().wrapped, (0.86, 0.86, 0.84)))
    out.append(("mounting plate galvanised", solid_box(PX0, PY0, WALL + PLATE_OFF, PLATE_W, PLATE_H, PLATE_T)
                .val().wrapped, (0.72, 0.74, 0.76)))
    for x, y in ((PX0 + 10, PY0 + 10), (BOX_W - PX0 - 10, PY0 + 10), (PX0 + 10, BOX_H - PY0 - 10),
                 (BOX_W - PX0 - 10, BOX_H - PY0 - 10)):
        out.append(("plate standoff", cq.Workplane("XY").center(x, y).polygon(6, 11.5).extrude(PLATE_OFF)
                    .translate((0, 0, WALL)).val().wrapped, (0.7, 0.7, 0.72)))

    # ducts
    for a in PARTS:
        if a["group"] == "duct":
            add(E.duct(a["w"], a["h"], a["d"], vertical=a["h"] > a["w"]), a["x"], a["y"])
    # DIN rails: main row and the short rails under the signal modules
    add(E.din_rail(350), 5, ROW - DIN / 2)
    for yc in (252.0, 199.0, 162.0):
        add(E.din_rail(108), 255, yc - DIN / 2)

    builders = {
        "X1_mains": lambda a: E.terminal(3, [(0.55, 0.36, 0.2), E.BLUE_T, E.GY_GREEN]),
        "Q1_mcb": lambda a: E.mcb_2p(),
        "K1_contactor": lambda a: E.contactor(),
        "PE_bar": lambda a: E.pe_bar(),
        "F1_fuse": lambda a: E.fuse_holder(),
        "F2_fuse": lambda a: E.fuse_holder(),
        "X2_ctrl": lambda a: E.terminal(10, [(0.62, 0.63, 0.65)] * 9 + [(0.62, 0.63, 0.65)]),
        "U1_vfd": lambda a: E.vfd_j1000(),
        "G1_psu": lambda a: E.psu_lrs(),
        "A1_grbl": lambda a: E.nano_carrier(),
        "A2_daq": lambda a: E.nano_carrier(),
        "K2_relay": lambda a: E.relay_module(),
        "K3_relay": lambda a: E.relay_module(),
        "U2_pwm": lambda a: E.small_module(kind="pwm"),
        "U3_buck": lambda a: E.small_module(kind="buck"),
        "X3_field": lambda a: E.terminal(16, [(0.62, 0.63, 0.65), (0.62, 0.63, 0.65), E.BLUE_T, E.GY_GREEN],
                                         pitch=7.0, h=90),
    }
    for a in PARTS:
        n = a["name"]
        z0 = 7.5 if n in ("X1_mains", "Q1_mcb", "K1_contactor", "PE_bar", "F1_fuse", "F2_fuse", "X2_ctrl") else 0.0
        if n.endswith("tb6600"):
            add(E.tb6600(), a["x"], a["y"], prefix=n + " ")
        elif n in builders:
            if n in ("A1_grbl", "A2_daq", "K2_relay", "K3_relay", "U2_pwm", "U3_buck"):
                z0 = 7.5
            add(builders[n](a), a["x"], a["y"], z0, prefix=n + " ")

    # cable glands on the bottom, fan and exhaust filter on the side walls
    for gx, gd, label in GLANDS:
        for n, w, c in E.cable_gland(gd):
            from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
            out.append((n, _place(w, gx - PX0, -PY0, BOX_D / 2 - (WALL + PLATE_OFF + PLATE_T), R_OUT["-y"]), c))
    fz = BOX_D / 2 - (WALL + PLATE_OFF + PLATE_T)
    add([(n, w.translate((-62.5, -62.5, 0)), c) for n, w, c in E.filter_fan()],
        -PX0, PY0 + 20 + 62.5 - PY0, fz, R_OUT["-x"])
    add([(n, w.translate((-62.5, -62.5, 0)), c) for n, w, c in E.filter_fan() if "grille" in n],
        BOX_W - PX0, BOX_H - 2 * PY0 - 145 + 62.5, fz, R_OUT["+x"])

    # door: a folded panel on two hinges, with the operator devices; drawn open
    door_parts = [("door", solid_box(0, 0, BOX_D - 20, BOX_W, BOX_H, 20).cut(
        solid_box(WALL, WALL, BOX_D - 20 - 1, BOX_W - 2 * WALL, BOX_H - 2 * WALL, 20)), (0.86, 0.86, 0.84))]
    for name, _, cx, cy, dia, depth, _ in DOOR:
        bx, by, _ = to_box(cx, cy)
        door_parts[0] = (door_parts[0][0], door_parts[0][1].cut(
            cq.Workplane("XY").center(bx, by).circle(11.25).extrude(30).translate((0, 0, BOX_D - 25))), door_parts[0][2])
        items = (E.estop(dia) if "estop" in name else
                 E.pushbutton((0.15, 0.6, 0.2)) if "start" in name else
                 E.pushbutton((0.95, 0.75, 0.1), d=22, lamp=True))
        for n, w, c in items:
            door_parts.append((n, w.translate((bx, by, BOX_D)), c))
    door_parts.append(("door handle", solid_box(BOX_W - 30, BOX_H / 2 - 40, BOX_D, 14, 80, 18)
                       .edges().fillet(3), (0.15, 0.15, 0.16)))
    door_parts.append(("door seal", solid_box(8, 8, BOX_D - 21, BOX_W - 16, BOX_H - 16, 3).cut(
        solid_box(14, 14, BOX_D - 22, BOX_W - 28, BOX_H - 28, 5)), (0.1, 0.1, 0.1)))
    for y in (60, BOX_H - 100):
        door_parts.append(("hinge", cq.Workplane("XZ").center(-4, BOX_D - 4).circle(4).extrude(-40)
                           .translate((0, y, 0)), (0.3, 0.3, 0.32)))
    for n, w, c in door_parts:
        w = w.rotate((0, 0, BOX_D), (0, 1, BOX_D), DOOR_ANGLE) if n != "hinge" else w
        out.append((n, w.val().wrapped, c))

    # wiring: the bundles that leave the ducts (inside the ducts they are hidden by the covers)
    gz = BOX_D / 2 - (WALL + PLATE_OFF + PLATE_T)
    cables = [
        ("mains cable 3G1.5", [(20, -30, gz), (20, -8, gz), (-1, 8, 80), (-1, 140, 80), (-9, 160, 40),
                               (-9, 300, 25), (14, 305, 25), (14, 345, 30)], 8.0, (0.15, 0.15, 0.15)),
        ("VFD motor cable, shielded 4G1.5", [(40, 154, 50), (4, 140, 60), (4, 12, 60), (60, -8, gz),
                                             (60, -30, gz)], 9.0, (0.25, 0.25, 0.27)),
        ("USB cable to PC", [(325, -30, gz), (325, -8, gz), (366, 0, 40), (366, 268, 40), (282, 290, 34),
                             (282, 276, 30)], 4.5, (0.1, 0.1, 0.1)),
        ("USB cable to PC", [(335, -30, gz), (335, -8, gz), (370, 0, 45), (370, 300, 45), (332, 300, 34),
                             (332, 276, 30)], 4.5, (0.1, 0.1, 0.1)),
    ]
    for i, gxp in enumerate((130, 165, 200)):
        cx = 10 + i * 77 + 35.5
        cables.append((f"motor cable {'XYZ'[i]} 4x0.75", [(cx, 6, 33), (cx, -4, 45), (gxp, -8, gz), (gxp, -30, gz)],
                       6.0, (0.20, 0.20, 0.22)))
    for gxp, xt in ((245, 270), (280, 310)):
        cables.append(("sensor cable", [(gxp, -30, gz), (gxp, -8, gz), (xt, 2, 50), (xt, 8, 44)], 5.0,
                       (0.20, 0.20, 0.22)))
    for name, pts, d, c in cables:
        w = E.wire([to_box(*p) for p in pts], d)
        if w is not None:
            out.append((name, w.val().wrapped, c))
    # single cores from the DIN row into the top and middle ducts
    core = {"X1_mains": [(0.55, 0.36, 0.2), (0.15, 0.35, 0.75), (0.25, 0.65, 0.25)],
            "Q1_mcb": [(0.55, 0.36, 0.2), (0.15, 0.35, 0.75)], "K1_contactor": [(0.55, 0.36, 0.2), (0.15, 0.35, 0.75),
                                                                              (0.85, 0.1, 0.1)],
            "F1_fuse": [(0.85, 0.1, 0.1)], "F2_fuse": [(0.85, 0.1, 0.1)],
            "X2_ctrl": [(0.85, 0.1, 0.1), (0.15, 0.35, 0.75), (0.9, 0.9, 0.9), (0.85, 0.1, 0.1)],
            "PE_bar": [(0.25, 0.65, 0.25)] * 3}
    for a in PARTS:
        for k, c in enumerate(core.get(a["name"], [])):
            x = a["x"] + (k + 0.5) * a["w"] / len(core[a["name"]])
            if a["name"] == "K1_contactor":
                x = a["x"] + (13.0, 31.0, 39.0)[k]   # L to the VFD passes through the current sensor
            top, bot = a["y"] + a["h"], a["y"]
            for y0, y1 in ((top, 428), (bot, 320)):
                w = E.wire([to_box(x, y0 + (2 if y1 > y0 else -2), 50), to_box(x, y1, 30)], 1.8)
                if w is not None:
                    out.append(("wire", w.val().wrapped, c))
            if a["name"] == "K1_contactor" and k == 0:
                # SCT-013-005 clipped round the L conductor to the VFD (DAQ A0, electronics §3.4).
                # The conductor runs from z 50 at the contactor to z 30 at the duct: centre it on that line.
                yc = bot - 9.0
                zc = 50 - 20 * (bot - 2 - yc) / (bot - 2 - 320)
                for n, wp, col in E.sct013():
                    out.append((n, wp.translate(to_box(x, yc, zc)).val().wrapped, col))
                lead = E.wire([to_box(x, yc, zc + 46), to_box(x, yc - 6, zc + 52), to_box(x + 9, 334, zc + 52),
                               to_box(x + 9, 330, 32), to_box(x + 9, 322, 30)], 3.2)
                if lead is not None:
                    out.append(("SCT-013 lead to DAQ A0", lead.val().wrapped, (0.15, 0.15, 0.16)))
    for a in PARTS:                                  # VFD / PSU / signal modules into the nearest duct
        if a["name"] in ("U1_vfd", "G1_psu", "A1_grbl", "A2_daq", "K2_relay", "K3_relay", "U2_pwm", "U3_buck"):
            for k in range(3):
                x = a["x"] + a["w"] * (0.3 + 0.2 * k)
                y0 = a["y"] + a["h"]
                y1 = 290 if y0 < 290 else 300
                if y1 - y0 > 2:
                    w = E.wire([to_box(x, y0 + 1, min(a["d"], 30)), to_box(x, y1, 20)], 1.5)
                    if w is not None:
                        out.append(("wire", w.val().wrapped, [(0.85, 0.1, 0.1), (0.1, 0.1, 0.1), (0.9, 0.9, 0.9)][k]))
    return out


def build_step(path):
    z_up = cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 90)          # box frame Y up -> Z up
    asm = cq.Assembly(name="electrical_box", loc=z_up)
    counts = {}
    for name, shape, col in build_parts():
        k = counts[name] = counts.get(name, 0) + 1
        asm.add(cq.Shape.cast(shape), name=f"{name}_{k}" if k > 1 else name, color=cq.Color(*col))
    asm.save(path)


def parts_for_render():
    return build_parts()


# camera (Z-up render frame: x right, -y towards the viewer, z up)
RENDER_VIEWS = {
    "front_open": ((420, -1250, 700), (200, -100, 250), 32),
    "iso_left": ((-700, -1050, 800), (200, -100, 250), 30),
    "inside_closeup": ((260, -520, 330), (180, -40, 220), 38),
}


# ------------------------------------------------------------------ PNG
def draw(path, p, dt, flow):
    fig = plt.figure(figsize=(17, 12))
    ax = fig.add_axes([0.03, 0.06, 0.55, 0.88])
    colors = {"mains": "#e57373", "drive": "#ffb74d", "signal": "#64b5f6", "duct": "#e0e0e0", "earth": "#81c784"}
    ax.add_patch(Rectangle((-PX0, -PY0), BOX_W, BOX_H, fill=False, lw=2.5, ec="#424242"))
    ax.add_patch(Rectangle((0, 0), PLATE_W, PLATE_H, fc="#fafafa", ec="#9e9e9e", lw=1))
    for a in PARTS:
        hatch = "||" if a["group"] == "duct" else None
        ax.add_patch(Rectangle((a["x"], a["y"]), a["w"], a["h"], fc=colors[a["group"]], ec="#37474f",
                               lw=0.8, hatch=hatch, alpha=0.9 if a["group"] != "duct" else 0.6))
        if a["group"] not in ("duct",) and a["name"] != "din_rail":
            fs = 7 if a["w"] < 25 else 8
            ax.text(a["x"] + a["w"] / 2, a["y"] + a["h"] / 2, a["label"], ha="center", va="center",
                    fontsize=fs, rotation=90 if a["w"] < 25 else 0)
    for name, label, cx, cy, dia, depth, col in DOOR:
        ax.add_patch(Circle((cx, cy), dia / 2, fc=col, ec="k", lw=1, alpha=0.55, ls="--"))
        ax.text(cx, cy - dia / 2 - 3, label + "\n(on the door)", ha="center", va="top", fontsize=7.5,
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.5))
    for gx, gd, label in GLANDS:
        ax.add_patch(Circle((gx - PX0, -PY0 - 6), gd / 2, fc="#bdbdbd", ec="k", lw=0.8))
    ax.text(-PX0 - 6, -PY0 - 6, "glands\n(bottom)", ha="right", va="center", fontsize=8)
    ax.annotate("filter fan 120 mm\n(left wall, intake)", (-PX0, 75), (-PX0 - 95, 40), fontsize=8,
                arrowprops=dict(arrowstyle="->"))
    ax.annotate("exhaust filter\n(right wall)", (BOX_W - PX0, PLATE_H - 70), (BOX_W - PX0 + 10, PLATE_H - 20),
                fontsize=8, arrowprops=dict(arrowstyle="->"))
    ax.plot([240.5, 240.5], [143, 288], color="#7b1fa2", lw=2, ls=":")
    for gx, gd, label in GLANDS:
        ax.text(gx - PX0, -PY0 - 6 - gd / 2 - 3, label.replace("\n", " "), rotation=35, ha="right", va="top",
                fontsize=7)
    ax.text(120, PLATE_H + PY0 + 6, "POWER SIDE (230 V, VFD, motor power)", ha="center", fontsize=10,
            color="#b71c1c", weight="bold")
    ax.text(310, PLATE_H + PY0 + 6, "SIGNAL SIDE (5-24 V)", ha="center", fontsize=10, color="#0d47a1",
            weight="bold")
    ax.set_xlim(-PX0 - 110, BOX_W + 30)
    ax.set_ylim(-PY0 - 95, BOX_H + 10)
    ax.set_aspect("equal")
    ax.set_xlabel("mm (mounting plate origin)")
    ax.set_title(f"Electrical box {BOX_W:.0f} x {BOX_H:.0f} x {BOX_D:.0f} mm, front view with the door open",
                 fontsize=12)

    tx = fig.add_axes([0.6, 0.06, 0.38, 0.88]); tx.axis("off")
    legend = [("mains", "230 V mains / 24 V supply"), ("drive", "VFD and stepper drivers (noisy)"),
              ("signal", "signal: Nanos, relays, fuses, terminals"), ("earth", "PE bar, DIN rail"),
              ("duct", "wiring duct 40 x 40")]
    for i, (g, t) in enumerate(legend):
        tx.add_patch(Rectangle((0, 0.96 - i * 0.035), 0.05, 0.022, fc=colors[g], ec="k", transform=tx.transAxes))
        tx.text(0.07, 0.971 - i * 0.035, t, va="center", fontsize=10, transform=tx.transAxes)
    notes = (
        "Layout rules\n"
        "- Mains and power on the left, signal on the right. In the middle\n"
        "  zone the vertical duct is the boundary (dotted line). Cross it\n"
        "  only at 90 degrees. DIN row: mains, K1, PE bar, then 24 V side.\n"
        "- VFD output (U V W + PE) leaves straight down through the EMC\n"
        "  gland, shield clamped 360 deg. It never enters the signal ducts.\n"
        "- Stepper motor cables: from D1-D3 straight down to their glands.\n"
        "- One star point: the PE bar. PSU 0 V to PE once, at the bar.\n"
        "  Plate, door (braid) and box bolt to PE.\n"
        "- TB6600s and VFD with fins vertical; 20 mm free above each.\n"
        "- USB leaves through a split gland with a ferrite on each cable.\n"
        "\n"
        "Clearances (checked by the script)\n"
        f"- door inner face {Z_DOOR:.0f} mm from the plate; deepest part\n"
        f"  is the VFD at {max(a['d'] for a in PARTS):.0f} mm\n"
        "- E-stop and Start sit in front of the DIN row (70 + 70 mm),\n"
        "  not in front of the VFD\n"
        "- no part overlaps another or the ducts (2 mm minimum)\n"
        "\n"
        "Heat\n"
        + "".join(f"- {k}: {v:.0f} W\n" for k, v in LOSSES.items())
        + f"- total {p:.0f} W -> sealed box rises ~{dt:.0f} K above room.\n"
        f"  At 30 C room that is ~{30 + dt:.0f} C inside; the J1000 is rated\n"
        "  for 50 C ambient in an enclosure. Fit a filter fan\n"
        f"  (>= {flow:.0f} m3/h keeps the rise near 10 K; a 120 mm fan\n"
        "  gives 30-50 m3/h) low on the left, exhaust filter high right.\n"
        "\n"
        "Door: E-stop (red mushroom, 2 NC: one in the K1 coil circuit,\n"
        "one to GRBL A0), Start (green, NO), Power lamp (24 V). All\n"
        "22.5 mm cutouts. Wiring: electronics/diagrams/6_system_overview.png"
    )
    tx.text(0, 0.76, notes, va="top", fontsize=9.5, family="monospace", transform=tx.transAxes)
    fig.savefig(path, dpi=110)


def main():
    print("Layout check:")
    ok = check()
    print("  ok" if ok else "  FAILED")
    p, area, dt, flow = heat()
    print(f"Heat: {p:.0f} W over {area:.2f} m2 -> {dt:.1f} K rise sealed; {flow:.0f} m3/h for 10 K")
    os.makedirs(os.path.join(HERE, "step"), exist_ok=True)
    build_step(os.path.join(HERE, "step", "electrical_box.step"))
    draw(os.path.join(HERE, "electrical_box.png"), p, dt, flow)
    print("wrote step/electrical_box.step and electrical_box.png")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
