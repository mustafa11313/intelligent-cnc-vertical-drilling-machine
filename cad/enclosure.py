"""Safety and dust cover for the drilling machine.

    python3 enclosure.py <Ana_Montaj.x_t>

Writes step/enclosure.step (the cover alone), step/full_machine_enclosed.step
(upgraded machine + cover) and prints the cut list. Coordinates are built in
Ana_Montaj's frame (Y up, mm) like everything else here and written Z up.

What it is
  * 20x20 B-type aluminium profile frame (slot 6), standing on the bench on
    four M8 levelling feet, around the machine, not on it, so vibration and
    knocks on the cover don't reach the machine.
  * 4 mm clear polycarbonate panels held in the profile slots.
  * Front door (the side the operator stands at, +X, where the spindle
    faces) on two hinges, with a handle, magnetic catch and a safety
    interlock switch (tongue type, 2 NC) wired in series with the E-stop:
    opening the door drops K1, so the spindle and motors stop.
  * Removable lid for changing bits and reaching the Z motor.
  * Ø50 extraction port high on the back panel (the shop vac keeps a slight
    vacuum inside, so dust that escapes the dust shoe stays in), and a
    brush-strip cable entry low on the back.
"""
import os
import sys

import cadquery as cq
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

P = 20.0                                    # profile size
SLOT = 6.2
FEET = 20.0                                 # bench to the underside of the bottom frame
# profile centre lines (Ana_Montaj frame: x along the table travel, y up, z across)
X0, X1 = -290.0, 260.0                      # back (X motor end), front (door side)
Z0, Z1 = -380.0, 170.0
Y0, Y1 = FEET + P / 2, 700.0
PANEL_T = 4.0
PANEL_IN_SLOT = 5.0                         # panel edge depth in the slot
DOOR_ANGLE = 100.0                          # drawn open
PC = (0.80, 0.88, 0.95, 0.28)               # polycarbonate, see-through
ALU = (0.80, 0.82, 0.85)
BLACK = (0.10, 0.10, 0.11)
STEEL = (0.70, 0.72, 0.74)
YELLOW = (0.95, 0.80, 0.10)


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def profile(p0, p1):
    """20x20 slot-6 profile between two points on an axis-parallel line."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    axis = int(np.argmax(np.abs(p1 - p0)))
    L = abs(p1[axis] - p0[axis])
    sec = cq.Workplane("XY").rect(P, P).extrude(L)
    for ang in (0, 90, 180, 270):                              # slot + undercut on each face
        s = box(-SLOT / 2, SLOT / 2, P / 2 - 1.8, P / 2 + 1, 0, L).union(box(-5.5, 5.5, P / 2 - 6, P / 2 - 1.8, 0, L))
        sec = sec.cut(s.rotate((0, 0, 0), (0, 0, 1), ang))
    sec = sec.cut(cq.Workplane("XY").circle(2.1).extrude(L))
    sec = sec.edges("|Z").fillet(0.5) if False else sec
    start = np.minimum(p0, p1)
    if axis == 0:
        sec = sec.rotate((0, 0, 0), (0, 1, 0), 90)
    elif axis == 1:
        sec = sec.rotate((0, 0, 0), (1, 0, 0), -90)
    c = start.copy()
    return sec.translate(tuple(c))


def panel(axis_n, at, a0, a1, b0, b1):
    """Polycarbonate sheet normal to axis_n at coordinate `at`, spanning [a0,a1]x[b0,b1]
    on the other two axes (in x, y, z order), thickness PANEL_T."""
    lo = [0, 0, 0]
    hi = [0, 0, 0]
    others = [i for i in range(3) if i != axis_n]
    lo[axis_n], hi[axis_n] = at - PANEL_T / 2, at + PANEL_T / 2
    lo[others[0]], hi[others[0]] = a0, a1
    lo[others[1]], hi[others[1]] = b0, b1
    return box(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])


def span(c0, c1):
    """Panel extent between two profile centre lines: into each slot by PANEL_IN_SLOT."""
    return c0 + P / 2 - PANEL_IN_SLOT, c1 - P / 2 + PANEL_IN_SLOT


def corner_bracket(p, sx, sy, sz):
    """Small cast corner bracket at a frame corner (visual + bolts)."""
    b = box(0, 20, 0, 20, 0, 3).union(box(0, 3, 0, 20, 0, 20)).union(box(0, 20, 0, 3, 0, 20))
    m = np.diag([sx, sy, sz]).astype(float)
    v = b.val()
    from OCP.gp import gp_GTrsf, gp_Mat, gp_XYZ
    from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform
    g = gp_GTrsf()
    g.SetVectorialPart(gp_Mat(*m.flatten()))
    g.SetTranslationPart(gp_XYZ(*p))
    return cq.Workplane().add(cq.Shape.cast(BRepBuilderAPI_GTransform(v.wrapped, g, True).Shape()))


def handle(length=120.0):
    """U handle, legs along +x from the mounting face, grip along y."""
    leg = cq.Workplane("YZ").circle(4).extrude(30)
    grip = cq.Workplane("XZ").circle(4).extrude(-length).translate((30, 0, 0))
    return leg.union(leg.translate((0, length, 0))).union(grip)


def parts():
    """[(name, Workplane, rgba)] in the Ana_Montaj frame, door open."""
    out = []
    xs, ys, zs = (X0, X1), (Y0, Y1), (Z0, Z1)
    # frame: 4 verticals, 4 + 4 horizontals, a middle rail on the back for the cable entry
    for x in xs:
        for z in zs:
            out.append(("profile 20x20 vertical", profile((x, Y0 - P / 2, z), (x, Y1 + P / 2, z)), ALU))
    for y in ys:
        for z in zs:
            out.append(("profile 20x20 X", profile((X0 + P / 2, y, z), (X1 - P / 2, y, z)), ALU))
        for x in xs:
            out.append(("profile 20x20 Z", profile((x, y, Z0 + P / 2), (x, y, Z1 - P / 2)), ALU))
    YM = 140.0
    out.append(("profile 20x20 Z", profile((X0, YM, Z0 + P / 2), (X0, YM, Z1 - P / 2)), ALU))
    # corner brackets inside the bottom and top corners
    for x, sx in ((X0 + P / 2, 1), (X1 - P / 2, -1)):
        for z, sz in ((Z0 + P / 2, 1), (Z1 - P / 2, -1)):
            for y, sy in ((Y0 + P / 2, 1), (Y1 - P / 2, -1)):
                out.append(("corner bracket 20", corner_bracket((x, y, z), sx, sy, sz), (0.55, 0.57, 0.60)))
    # panels: two sides, back (two parts, around the middle rail), lid
    for z in zs:
        a0, a1 = span(X0, X1)
        b0, b1 = span(Y0, Y1)
        out.append(("polycarbonate side panel", panel(2, z, a0, a1, b0, b1), PC))
    a0, a1 = span(Y0, YM)
    b0, b1 = span(Z0, Z1)
    low = panel(0, X0, a0, a1, b0, b1).cut(box(X0 - 5, X0 + 5, YM - P / 2 - 45, YM - P / 2 - 5, -300, 90))
    out.append(("polycarbonate back panel, low (cable entry)", low, PC))
    out.append(("brush strip cable entry", box(X0 - 8, X0 + 2, YM - P / 2 - 45, YM - P / 2 - 5, -300, 90)
                .cut(box(X0 - 9, X0 + 3, YM - P / 2 - 26, YM - P / 2 - 24, -299, 89)), BLACK))
    a0, a1 = span(YM, Y1)
    port_y, port_z = 600.0, (Z0 + Z1) / 2
    high = panel(0, X0, a0, a1, b0, b1).cut(cq.Workplane("YZ").center(port_y, port_z).circle(25.5)
                                           .extrude(20).translate((X0 - 10, 0, 0)))
    out.append(("polycarbonate back panel, high", high, PC))
    flange = cq.Workplane("YZ").center(port_y, port_z).circle(40).circle(25).extrude(4).translate((X0 - PANEL_T / 2 - 4, 0, 0))
    tube = cq.Workplane("YZ").center(port_y, port_z).circle(25).circle(23).extrude(-45).translate((X0 - 6, 0, 0))
    out.append(("extraction port 50 mm", flange.union(tube), BLACK))
    a0, a1 = span(X0, X1)
    b0, b1 = span(Z0, Z1)
    lid = panel(1, Y1 + P / 2 + PANEL_T / 2, X0 - P / 2, X1 + P / 2, Z0 - P / 2, Z1 + P / 2)  # lies on top, removable
    out.append(("polycarbonate lid 6 mm (removable)", lid, PC))
    for x in (X0 + 120, X1 - 120):
        h = handle(100).rotate((0, 0, 0), (0, 0, 1), 90).translate((x, Y1 + P / 2 + PANEL_T, (Z0 + Z1) / 2 - 50))
        out.append(("lid handle", h, BLACK))
    # door: own profile frame in front of the front face, hinged on the Z0 edge
    dx0 = X1 + P / 2                                          # back face of the door frame
    door = []
    dz0, dz1 = Z0 - P / 2, Z1 + P / 2
    dy0, dy1 = Y0 - P / 2, Y1 + P / 2
    for z in (dz0 + P / 2, dz1 - P / 2):
        door.append(("door profile vertical", profile((dx0 + P / 2, dy0, z), (dx0 + P / 2, dy1, z)), ALU))
    for y in (dy0 + P / 2, dy1 - P / 2):
        door.append(("door profile horizontal", profile((dx0 + P / 2, y, dz0 + P), (dx0 + P / 2, y, dz1 - P)), ALU))
    a0, a1 = span(dy0 + P / 2, dy1 - P / 2)
    b0, b1 = span(dz0 + P / 2, dz1 - P / 2)
    door.append(("polycarbonate door panel", panel(0, dx0 + P / 2, a0, a1, b0, b1), PC))
    h = handle(120).translate((dx0 + P, (dy0 + dy1) / 2 - 60, dz1 - P / 2))
    door.append(("door handle", h, BLACK))
    door.append(("interlock actuator key", box(dx0 - 2, dx0, dy1 - 140, dy1 - 110, dz1 - 15, dz1 - 5), STEEL))
    hinge_axis = ((dx0 + P, 0, dz0), (dx0 + P, 1, dz0))
    for n, w, c in door:
        out.append((n, w.rotate(hinge_axis[0], hinge_axis[1], -DOOR_ANGLE), c))
    for y in (Y0 + 80, Y1 - 80):                               # hinges stay on the frame line
        out.append(("door hinge", box(dx0, dx0 + P + 2, y - 20, y + 20, dz0 - 4, dz0 + 4)
                    .union(cq.Workplane("XZ").center(dx0 + P, dz0).circle(4).extrude(-40).translate((0, y - 20, 0))),
                    BLACK))
    # interlock switch on the front frame (fixed), magnetic catch
    out.append(("door interlock switch 2NC (e.g. Omron D4NS)", box(X1 - P / 2 - 32, X1 - P / 2, Y1 - 150, Y1 - 60,
                                                                   Z1 - P / 2 - 28, Z1 - P / 2), YELLOW))
    out.append(("magnetic catch", box(X1 - P / 2 - 15, X1 + P / 2, (Y0 + Y1) / 2 - 15, (Y0 + Y1) / 2 + 15,
                                      Z1 - P / 2 - 16, Z1 - P / 2), BLACK))
    # levelling feet
    for x in xs:
        for z in zs:
            foot = cq.Workplane("XZ").center(x, z).circle(15).extrude(-4).union(
                cq.Workplane("XZ").center(x, z).circle(4).extrude(-(FEET - 4)).translate((0, 4, 0)))
            out.append(("levelling foot M8", foot, BLACK))
    return out


def cut_list():
    h = (Y1 - Y0) + P
    lx = (X1 - X0) - P
    lz = (Z1 - Z0) - P
    dy, dz = h, (Z1 - Z0) + P
    rows = [
        ("20x20 profile, frame verticals", 4, h),
        ("20x20 profile, frame along X (front-back)", 4, lx),
        ("20x20 profile, frame along Z (left-right) incl. back middle rail", 5, lz),
        ("20x20 profile, door verticals", 2, dy),
        ("20x20 profile, door horizontals", 2, dz - 2 * P),
    ]
    a = span(X0, X1)
    b = span(Y0, Y1)
    c = span(Z0, Z1)
    panels = [
        ("polycarbonate 4 mm, sides", 2, a[1] - a[0], b[1] - b[0]),
        ("polycarbonate 4 mm, back low", 1, span(Y0, 140)[1] - span(Y0, 140)[0], c[1] - c[0]),
        ("polycarbonate 4 mm, back high", 1, span(140, Y1)[1] - span(140, Y1)[0], c[1] - c[0]),
        ("polycarbonate 4 mm, door", 1, b[1] - b[0], c[1] - c[0]),
        ("polycarbonate 6 mm, lid", 1, (X1 - X0) + P, (Z1 - Z0) + P),
    ]
    lines = ["Cut list (mm)"]
    total = 0.0
    for n, q, L in rows:
        lines.append(f"  {q} x {L:6.1f}  {n}")
        total += q * L
    lines.append(f"  total profile {total / 1000:.2f} m: buy 6 x 2 m bars, cut each into 690 + 530 + 530 (one 530 spare)")
    for n, q, w, h_ in panels:
        lines.append(f"  {q} x {w:6.1f} x {h_:6.1f}  {n}")
    lines.append(f"Outside size: {X1 - X0 + P + P:.0f} (X, with door) x {Z1 - Z0 + P:.0f} (Z) x {Y1 + P / 2 + 6:.0f} high")
    return "\n".join(lines)


def check_clearance(machine_parts):
    """Swept envelope of the machine against the inside of the cover."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    lo, hi = np.full(3, 1e9), np.full(3, -1e9)
    for name, shape, _ in machine_parts:
        bb = Bnd_Box()
        BRepBndLib.Add_s(shape, bb)
        b = np.array(bb.Get())
        lo, hi = np.minimum(lo, b[:3]), np.maximum(hi, b[3:])
    # table travel (cad/README.md): table x from -206 to +226 at the ends
    lo[0], hi[0] = min(lo[0], -206.0), max(hi[0], 226.0)
    inner_lo = np.array([X0 + P / 2, 0.0, Z0 + P / 2])
    inner_hi = np.array([X1 - P / 2, Y1 - P / 2, Z1 - P / 2])
    gaps = {"back (X-)": lo[0] - inner_lo[0], "front (X+)": inner_hi[0] - hi[0],
            "side Z-": lo[2] - inner_lo[2], "side Z+": inner_hi[2] - hi[2], "top": inner_hi[1] - hi[1]}
    return gaps


def main(xt):
    import full_assembly as FA
    mc = FA.Machine(xt)
    mc.build_upgraded()
    gaps = check_clearance(mc.parts)
    print("Clearance from the machine's swept envelope to the inside of the cover (mm):")
    for k, v in gaps.items():
        print(f"  {k:12s} {v:6.1f}")
    print(cut_list())
    z_up = cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 90)
    cov = parts()
    for path, with_machine in (("enclosure.step", False), ("full_machine_enclosed.step", True)):
        asm = cq.Assembly(name="drilling_machine_cover" if not with_machine else "drilling_machine_enclosed", loc=z_up)
        counts = {}
        items = [(n, w.val().wrapped, c) for n, w, c in cov]
        if with_machine:
            items = mc.parts + items
        for n, s, c in items:
            k = counts[n] = counts.get(n, 0) + 1
            asm.add(cq.Shape.cast(s), name=f"{n}_{k}" if k > 1 else n, color=cq.Color(*c))
        asm.save(os.path.join(HERE, "step", path))
        print("wrote step/" + path)
    with open(os.path.join(HERE, "enclosure_cut_list.txt"), "w") as f:
        f.write(cut_list() + "\n")
    return min(gaps.values()) > 10


if __name__ == "__main__":
    raise SystemExit(0 if main(sys.argv[1]) else 1)
