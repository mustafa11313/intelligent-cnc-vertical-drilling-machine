"""Realistic models of the electrical parts, for electrical_box.py.

Every builder takes the part's footprint (w x h on the plate, d deep) and
returns [(name, Workplane, rgb)] in a local frame: x to the right, y up,
z out of the mounting plate, origin at the bottom-left corner on the plate.
Outlines and details follow the datasheets of the named parts (Schneider
iC60 / LC1K, Phoenix UT terminals, Mean Well LRS, Yaskawa J1000, TB6600,
Arduino Nano on a DIN screw-terminal carrier).
"""
import math

import cadquery as cq

GREY = (0.62, 0.63, 0.65)
LIGHT = (0.90, 0.90, 0.88)
DARK = (0.18, 0.18, 0.20)
BLACK = (0.08, 0.08, 0.09)
STEEL = (0.70, 0.72, 0.74)
ZINC = (0.78, 0.80, 0.82)
BRASS = (0.80, 0.64, 0.30)
COPPER = (0.80, 0.45, 0.25)
GREEN_PCB = (0.10, 0.45, 0.20)
BLUE_PCB = (0.10, 0.25, 0.65)
TERM_GREEN = (0.15, 0.60, 0.25)
RELAY_BLUE = (0.15, 0.35, 0.80)
YASKAWA = (0.22, 0.24, 0.27)
RED = (0.80, 0.10, 0.10)
YELLOW = (0.95, 0.80, 0.10)
ORANGE = (0.95, 0.50, 0.10)
GY_GREEN = (0.25, 0.65, 0.25)
BLUE_T = (0.15, 0.35, 0.75)


def B(x0, y0, z0, w, h, d):
    return cq.Workplane("XY").box(w, h, d, centered=False).translate((x0, y0, z0))


def screw_head(x, y, z, r=2.2):
    """Terminal screw seen from the front: a disc with a slot, axis +z."""
    s = cq.Workplane("XY").circle(r).extrude(0.8).translate((x, y, z))
    return s.cut(B(x - r, y - 0.3, z + 0.4, 2 * r, 0.6, 0.5))


# --------------------------------------------------------------- DIN rail
def din_rail(length):
    """TS35 x 7.5 top-hat rail, 1 mm steel, slotted. Footprint length x 35."""
    prof = [(0, 0), (35, 0), (35, 1), (30, 1), (30, 7.5), (5, 7.5), (5, 1), (0, 1)]
    hat = cq.Workplane("XZ").polyline([(y, z) for y, z in [(0, 0), (5, 0), (5, 6.5), (30, 6.5),
                                                             (30, 0), (35, 0), (35, 1), (31, 1),
                                                             (31, 7.5), (4, 7.5), (4, 1), (0, 1)]]).close()
    del prof
    r = cq.Workplane("YZ").polyline([(0, 6.5), (5, 6.5), (5, 0), (30, 0), (30, 6.5), (35, 6.5), (35, 7.5),
                                     (29, 7.5), (29, 1), (6, 1), (6, 7.5), (0, 7.5)]).close().extrude(length)
    del hat
    r = r.translate((0, 0, 0))
    for i in range(int(length // 25)):
        r = r.cut(B(6 + i * 25, 12.5, -1, 15, 10, 3))
    return [("DIN rail TS35", r, ZINC)]


# ---------------------------------------------------- modular DIN devices
def modular(w, h, d, colour=LIGHT, front_w=None):
    """Classic DIN modular device body: wide base, 45 mm front strip."""
    front_w = front_w or w
    base = B(0, 0, 0, w, h, d - 18)
    front = B(0, h / 2 - 22.5, d - 18, front_w, 45, 18)
    return base.union(front).edges("|Z").fillet(0.8)


def mcb_2p(w=36, h=85, d=70):
    body = modular(w, h, d)
    parts = [("MCB body", body, LIGHT)]
    for i in range(2):
        cx = w / 4 + i * w / 2
        parts.append(("MCB toggle", B(cx - 4, h / 2 - 6, d, 8, 12, 6).edges("|Z").fillet(1.5), BLACK))
        for y in (6, h - 6):
            parts.append(("MCB screw", screw_head(cx, y, d - 18), STEEL))
    parts.append(("MCB label C10", B(2, h / 2 + 10, d - 0.01, w - 4, 8, 0.4), (0.2, 0.3, 0.6)))
    return parts


def fuse_holder(w=18, h=81, d=60):
    body = modular(w, h, d)
    carrier = B(1, h / 2 - 20, d, w - 2, 40, 4).edges("|Z").fillet(1)
    return [("fuse holder", body, DARK), ("fuse carrier", carrier, DARK),
            ("fuse window", B(4, h / 2 - 5, d + 4, w - 8, 10, 0.3), (0.85, 0.75, 0.2)),
            ("screw", screw_head(w / 2, 6, d - 18), STEEL), ("screw", screw_head(w / 2, h - 6, d - 18), STEEL)]


def contactor(w=45, h=58, d=57):
    body = B(0, 0, 0, w, h, d).edges("|Z").fillet(1.5)
    body = body.cut(B(4, h - 10, d - 14, w - 8, 10, 14)).cut(B(4, 0, d - 14, w - 8, 10, 14))     # terminal steps
    parts = [("contactor LC1K", body, (0.30, 0.31, 0.33)),
             ("contactor window", B(w / 2 - 7, h / 2 - 8, d, 14, 16, 2), (0.85, 0.85, 0.8))]
    for x in (9, 18.5, 28, 37):
        for y in (5, h - 5):
            parts.append(("screw", screw_head(x, y, d - 14), STEEL))
    return parts


def terminal(n, colours, pitch=5.2, h=45, d=47):
    parts = []
    for i in range(n):
        x = i * pitch
        prof = B(x, 0, 0, pitch - 0.2, h, d - 12).union(B(x, 8, d - 12, pitch - 0.2, h - 16, 12))
        prof = prof.cut(B(x, 0, d - 10, pitch, 7, 10)).cut(B(x, h - 7, d - 10, pitch, 7, 10))
        parts.append(("terminal", prof, colours[i % len(colours)]))
        for y in (4, h - 4):
            parts.append(("screw", screw_head(x + pitch / 2 - 0.1, y, d - 10, 1.8), STEEL))
        parts.append(("marker", B(x + 0.6, h / 2 - 4, d, pitch - 1.4, 8, 0.4), LIGHT))
    parts.append(("end plate", B(n * pitch, 0, 0, 1.5, h, d - 12), colours[-1]))
    return parts


def pe_bar(n=6, h=45, d=47):
    w = n * 6.2
    parts = [("PE bar insulator", B(0, 0, 0, 5, h, 25), (0.85, 0.75, 0.2)),
             ("PE bar insulator", B(w - 5, 0, 0, 5, h, 25), (0.85, 0.75, 0.2)),
             ("PE bar", B(0, h / 2 - 6, 25, w, 12, 8), BRASS)]
    for i in range(n):
        parts.append(("PE screw", screw_head(3 + i * 6.2, h / 2, 33, 2.4), STEEL))
    return parts


# ---------------------------------------------------------------- big parts
def vfd_j1000(w=108, h=128, d=138):
    body = B(0, 0, 0, w, h, d).edges("|Z").fillet(3).edges(">Z").fillet(2)
    body = body.cut(B(10, 6, d - 3, w - 20, 34, 3))                                    # terminal cover recess
    parts = [("VFD J1000 body", body, YASKAWA)]
    parts.append(("VFD terminal cover", B(11, 7, d - 3, w - 22, 32, 2.6), (0.30, 0.32, 0.36)))
    parts.append(("VFD keypad", B(12, 52, d, w - 24, 66, 1.5), (0.12, 0.13, 0.15)))
    parts.append(("VFD display", B(22, 96, d + 1.5, w - 44, 14, 0.5), (0.70, 0.10, 0.08)))
    for i, x in enumerate((22, 40, 58, 76)):
        parts.append(("VFD key", B(x + 2, 76, d + 1.5, 10, 7, 1.5), (0.6, 0.62, 0.66)))
    parts.append(("VFD RUN key", B(28, 60, d + 1.5, 18, 9, 1.5), (0.15, 0.55, 0.20)))
    parts.append(("VFD STOP key", B(62, 60, d + 1.5, 18, 9, 1.5), RED))
    for i in range(12):                                                                # top vents
        parts.append(("vent", B(10 + i * 7.5, h - 0.5, 20, 4, 0.6, d - 40), BLACK))
    parts.append(("VFD heatsink", B(-0.01, 0, 0, w + 0.02, h, 8), (0.55, 0.57, 0.60)))
    return parts


def psu_lrs(w=97, h=129, d=30):
    """Mean Well LRS-100-24, mounted standing, terminals at the bottom."""
    case = B(0, 18, 0, w, h - 18, d)
    for i in range(6):
        for j in range(10):
            case = case.cut(B(8 + j * 8.5, 40 + i * 12, d - 1, 5, 6, 1))                # perforations
    parts = [("PSU case", case, (0.75, 0.77, 0.79))]
    parts.append(("PSU terminal block", B(2, 0, 0, w - 4, 18, d - 6), BLACK))
    for i in range(7):
        parts.append(("screw", screw_head(9 + i * 13, 9, d - 6, 2.6), STEEL))
    parts.append(("PSU LED", cq.Workplane("XY").circle(1.5).extrude(1).translate((w - 12, 26, d)), (0.2, 0.9, 0.2)))
    parts.append(("PSU label", B(10, 105, d, w - 20, 16, 0.3), (0.35, 0.45, 0.70)))
    return parts


def tb6600(w=71, h=96, d=37):
    """TB6600 driver standing on the plate, fins along y (vertical)."""
    base = B(0, 0, 0, w, h, 8)
    fins = B(3, 0, 8, 2.5, h, d - 14)
    for i in range(1, 9):
        fins = fins.union(B(3 + i * 7.6, 0, 8, 2.5, h, d - 14))
    cover = B(0, 10, d - 6, w, h - 20, 6)                                              # the black cover with the DIP window
    parts = [("TB6600 heatsink", base.union(fins), (0.55, 0.57, 0.60)),
             ("TB6600 cover", cover, BLACK),
             ("TB6600 DIP switch", B(w / 2 - 10, h / 2 - 4, d, 20, 8, 1), (0.85, 0.2, 0.15)),
             ("TB6600 label", B(8, h - 32, d, w - 16, 12, 0.3), LIGHT)]
    for y0, n in ((0, 6), (h - 10, 6)):
        parts.append(("TB6600 terminals", B(6, y0, d - 14, w - 12, 10, 14), TERM_GREEN))
        for i in range(n):
            parts.append(("screw", screw_head(10 + i * (w - 20) / (n - 1), y0 + 5, d, 1.6), STEEL))
    return parts


def nano_carrier(w=45, h=60, d=25, label=""):
    """Arduino Nano on a DIN-rail screw terminal carrier."""
    parts = [("DIN clip housing", B(0, 0, 0, w, h, 10), (0.25, 0.26, 0.28)),
             ("carrier PCB", B(0, 0, 10, w, h, 1.6), GREEN_PCB)]
    for x0 in (1, w - 9):
        parts.append(("carrier terminals", B(x0, 2, 11.6, 8, h - 4, 9), TERM_GREEN))
        for i in range(15):
            parts.append(("screw", screw_head(x0 + 4, 4 + i * (h - 8) / 14, 20.6, 1.2), STEEL))
    parts.append(("Nano PCB", B(w / 2 - 9, 7, 21, 18, 44, 1.6), BLUE_PCB))
    parts.append(("ATmega328P", B(w / 2 - 4, 25, 22.6, 8, 8, 1), BLACK))
    parts.append(("CH340", B(w / 2 - 3, 38, 22.6, 6, 4, 1), BLACK))
    parts.append(("mini USB", B(w / 2 - 4, h - 12, 22.6, 8, 9, 4), STEEL))
    parts.append(("reset button", B(w / 2 - 2, 15, 22.6, 4, 4, 1.5), LIGHT))
    return parts


def relay_module(w=45, h=34, d=20):
    return [("relay PCB", B(0, 0, 6, w, h, 1.6), BLUE_PCB),
            ("DIN clip", B(4, 4, 0, w - 8, h - 8, 6), (0.25, 0.26, 0.28)),
            ("relay SRD-05VDC", B(4, 6, 7.6, 19, 15.5, 15), RELAY_BLUE),
            ("relay terminals", B(w - 16, 4, 7.6, 14, 26, 10), (0.15, 0.4, 0.8)),
            ("relay LED", B(26, h - 8, 7.6, 3, 2, 1), RED)]


def small_module(w=45, h=28, kind="buck"):
    parts = [("module PCB", B(0, 0, 6, w, h, 1.6), BLUE_PCB if kind == "buck" else GREEN_PCB),
             ("DIN clip", B(4, 3, 0, w - 8, h - 6, 6), (0.25, 0.26, 0.28))]
    if kind == "buck":
        parts += [("inductor", cq.Workplane("XY").rect(12, 12).extrude(7).translate((14, 14, 7.6)), DARK),
                  ("capacitor", cq.Workplane("XY").circle(4).extrude(10).translate((30, 9, 7.6)), DARK),
                  ("capacitor", cq.Workplane("XY").circle(4).extrude(10).translate((30, 20, 7.6)), DARK),
                  ("trimmer", B(38, 4, 7.6, 5, 10, 6), RELAY_BLUE)]
    else:
        parts += [("trimmer", B(6, 6, 7.6, 7, 7, 5), RELAY_BLUE),
                  ("IC", B(18, 8, 7.6, 10, 6, 1.5), BLACK),
                  ("terminals", B(32, 3, 7.6, 10, 22, 9), TERM_GREEN)]
    return parts


# ------------------------------------------------------------------ ducts
def duct(w, h, d=40, vertical=False):
    """Slotted wiring duct with cover: fingers 4 mm wide on 8 mm pitch."""
    t = 1.6
    body = B(0, 0, 0, w, h, d)
    inner = B(t, t, t, w - 2 * t, h - 2 * t, d) if not vertical else B(t, t, t, w - 2 * t, h - 2 * t, d)
    body = body.cut(inner)
    n = int((w if not vertical else h) // 8)
    for i in range(n):
        if not vertical:
            body = body.cut(B(4 + i * 8, -1, 8, 4, 3, d - 8)).cut(B(4 + i * 8, h - 2, 8, 4, 3, d - 8))
        else:
            body = body.cut(B(-1, 4 + i * 8, 8, 3, 4, d - 8)).cut(B(w - 2, 4 + i * 8, 8, 3, 4, d - 8))
    cover = B(-0.5, -0.5, d, w + 1, h + 1, 2)
    return [("wiring duct", body, (0.62, 0.63, 0.64)), ("duct cover", cover, (0.66, 0.67, 0.68))]


# ------------------------------------------------------------ door devices
def estop(head=40):
    """Red mushroom on a yellow ring, 22.5 mm cutout. Local: door outer face z = 0, out +z."""
    ring = cq.Workplane("XY").circle(30).circle(11.5).extrude(1)
    collar = cq.Workplane("XY").circle(15).extrude(10)
    mush = cq.Workplane("XY").workplane(offset=10).circle(head / 2).extrude(12).faces(">Z").fillet(6)
    block = B(-15, -15, -62, 30, 30, 60)
    return [("E-stop label ring", ring, YELLOW), ("E-stop collar", collar, BLACK),
            ("E-stop mushroom", mush, RED), ("E-stop contact block 2NC", block, DARK)]


def pushbutton(colour, d=30, lamp=False):
    bez = cq.Workplane("XY").circle(d / 2).extrude(5)
    btn = cq.Workplane("XY").workplane(offset=5).circle(d / 2 - 4).extrude(2 if not lamp else 4)
    return [("bezel", bez, (0.80, 0.80, 0.82)), ("button" if not lamp else "lamp lens", btn, colour),
            ("contact block", B(-15, -15, -50, 30, 30, 48), DARK)]


def cable_gland(size):
    """Nylon gland: lock nut inside, hex body and dome cap outside (+z)."""
    r = size / 2
    af = {16: 19, 20: 24, 25: 30}[size]
    hexb = cq.Workplane("XY").polygon(6, af / math.cos(math.pi / 6)).extrude(6)
    dome = cq.Workplane("XY").workplane(offset=6).polygon(6, (af - 2) / math.cos(math.pi / 6)).extrude(10) \
        .edges(">Z").chamfer(2)
    nut = cq.Workplane("XY").workplane(offset=-7).polygon(6, af / math.cos(math.pi / 6)).extrude(5)
    seal = cq.Workplane("XY").workplane(offset=16).circle(r * 0.55).extrude(0.5)
    return [("gland", hexb.union(dome), (0.20, 0.20, 0.22)), ("gland nut", nut, (0.20, 0.20, 0.22)),
            ("gland seal", seal, BLACK)]


def filter_fan(size=125):
    frame = B(0, 0, 0, size, size, 12)
    for i in range(12):
        frame = frame.cut(B(10, 10 + i * 9, 6, size - 20, 4.5, 6))
    return [("filter fan grille", frame, (0.55, 0.57, 0.60)),
            ("fan", cq.Workplane("XY").circle(55).extrude(14).translate((size / 2, size / 2, -14)), BLACK)]


def wire(points, d=2.0):
    """A wire bundle through points (box frame), round corners."""
    path = cq.Workplane("XY").polyline(points)
    try:
        prof = cq.Workplane(cq.Plane(origin=points[0], normal=tuple(b - a for a, b in zip(points[0], points[1]))))
        return prof.circle(d / 2).sweep(path, transition="round")
    except Exception:
        return None


def sct013():
    """SCT-013-005 split-core current transformer (13 mm aperture), clipped round one
    conductor. Local frame: aperture axis along Y, centred on the origin; the body
    runs forward along +Z (hinge end at -Z), 13 mm thick in Y, 30 mm wide in X."""
    t, w = 13.0, 30.0
    body = (cq.Workplane("XZ").center(0, 11.0).rect(w, 46.0).extrude(-t / 2, both=True)
            .edges("|Y").fillet(6.0))
    body = body.cut(cq.Workplane("XZ").circle(6.5).extrude(-t, both=True))
    split = cq.Workplane("XY").box(w + 2, t + 2, 0.6).translate((0, 0, 9.5))         # the split line
    body = body.cut(split)
    label = cq.Workplane("XY").box(20.0, 0.3, 14.0).translate((0, t / 2 + 0.15, 22.0))
    lead = cq.Workplane("XY").circle(1.6).extrude(12.0).translate((0, 0, 34.0))
    return [("current sensor SCT-013-005", body, (0.10, 0.10, 0.11)),
            ("SCT-013 label", label, (0.92, 0.92, 0.90)),
            ("SCT-013 lead", lead, (0.15, 0.15, 0.16))]
