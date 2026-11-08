"""Realistic models of the bought parts the upgrade adds.

Shapes follow the catalogue outlines (HIWIN, generic KFL08, LJ12A3 sensors,
608ZZ, Tr8x2), with threads drawn as a revolved tooth profile so they look
like threads without a slow helical sweep. Each function returns a
cq.Workplane in a local frame (described in its docstring); full_assembly.py
places them.
"""
import math

import cadquery as cq


def revolved(profile, axis_len_dir="Z"):
    """Revolve a closed (r, z) profile about the Z axis."""
    return cq.Workplane("XZ").polyline(profile).close().revolve(360, (0, 0, 0), (0, 1, 0))


def threaded_rod(d, length, pitch, depth=None):
    """Rod along +Z from z = 0, with a trapezoid tooth profile."""
    depth = depth or pitch * 0.5
    r0, r1 = d / 2 - depth, d / 2
    n = int(length / pitch)
    pts = [(0, 0), (r0, 0)]
    for i in range(n):
        z = i * pitch
        pts += [(r0, z + pitch * 0.15), (r1, z + pitch * 0.35), (r1, z + pitch * 0.65), (r0, z + pitch * 0.85)]
    pts += [(r0, length), (0, length)]
    return revolved(pts)


def tr8_screw(length):
    return threaded_rod(8.0, length, 2.0, 1.0)


def hex_prism(af, h):
    """Hex nut blank along +Z from z = 0, af = across flats."""
    return cq.Workplane("XY").polygon(6, af / math.cos(math.pi / 6)).extrude(h)


def m12_sensor(length=55.0):
    """LJ12A3-4-Z/BX: sensing face at z = 0, body along +Z, cable out the back.
    Two M12 nuts are not included (see m12_nut)."""
    body = threaded_rod(12.0, length - 6, 1.0, 0.55)
    face = cq.Workplane("XY").circle(5.6).extrude(-0.01)                   # blue sensing cap
    tail = cq.Workplane("XY").workplane(offset=length - 6).circle(5.4).extrude(6)
    cable = cq.Workplane("XY").workplane(offset=length).circle(2.2).extrude(60)
    return body.union(tail), cq.Workplane("XY").circle(5.9).extrude(1.5), cable, face


def m12_nut():
    n = hex_prism(17.0, 5.0)
    return n.cut(cq.Workplane("XY").circle(5.5).extrude(5)).edges("not |Z").chamfer(0.6)


def bearing(od, id_, w):
    """Deep groove ball bearing with shields, axis Z, from z = 0."""
    outer = cq.Workplane("XY").circle(od / 2).circle(od / 2 - (od - id_) * 0.18).extrude(w)
    inner = cq.Workplane("XY").circle(id_ / 2 + (od - id_) * 0.16).circle(id_ / 2).extrude(w)
    shield = cq.Workplane("XY").workplane(offset=0.4).circle(od / 2 - (od - id_) * 0.18) \
        .circle(id_ / 2 + (od - id_) * 0.16).extrude(w - 0.8)
    return outer.union(inner).union(shield)


def lock_collar(id_=8.0, od=16.0, w=9.0):
    c = cq.Workplane("XY").circle(od / 2).circle(id_ / 2).extrude(w).edges().chamfer(0.4)
    return c.cut(cq.Workplane("YZ").center(0, w / 2).circle(1.5).extrude(od))   # M3 set screw hole


def standoff(length, af=5.5):
    s = hex_prism(af, length).edges("not |Z").chamfer(0.3)
    return s.cut(cq.Workplane("XY").circle(1.25).extrude(length))


def kfl08():
    """2-bolt rhombic flange bearing, KFL08: bolt spacing 37, flange 48 x 27,
    axis Z, mounting face at z = 0, housing towards +Z."""
    R, r, d = 13.5, 6.0, 18.5
    phi = math.asin((R - r) / d)
    nx, ny = math.sin(phi), math.cos(phi)
    poly = [(R * nx, R * ny), (d + r * nx, r * ny), (d + r * nx, -r * ny), (R * nx, -R * ny),
            (-R * nx, -R * ny), (-d - r * nx, -r * ny), (-d - r * nx, r * ny), (-R * nx, R * ny)]
    fl = cq.Workplane("XY").polyline(poly).close().extrude(4.0)
    fl = fl.union(cq.Workplane("XY").circle(R).extrude(4.0))
    fl = fl.union(cq.Workplane("XY").pushPoints([(-d, 0), (d, 0)]).circle(r).extrude(4.0))
    boss = cq.Workplane("XY").circle(11.0).extrude(9.0)
    insert = cq.Workplane("XY").workplane(offset=1).circle(8.5).circle(4.0).extrude(9.0)
    p = fl.union(boss).union(insert)
    p = p.cut(cq.Workplane("XY").pushPoints([(-18.5, 0), (18.5, 0)]).circle(2.4).extrude(4))
    return p.cut(cq.Workplane("XY").circle(4.0).extrude(20)).edges(">Z").fillet(0.5)


def spring(d=6.5, wire=0.8, length=70.0, pitch=4.0):
    helix = cq.Wire.makeHelix(pitch, length, d / 2)
    prof = cq.Workplane("XZ").center(d / 2, 0).circle(wire / 2)
    return prof.sweep(cq.Workplane().add(helix), isFrenet=True)


def pcb_bit():
    """Carbide PCB drill, 1.0 mm, 3.175 shank, 38 mm long; tip at z = 0."""
    flute = cq.Workplane("XY").circle(0.5).extrude(8.0)
    cone = cq.Solid.makeCone(0.5, 1.5875, 2.0, cq.Vector(0, 0, 8), cq.Vector(0, 0, 1))
    shank = cq.Workplane("XY").workplane(offset=10).circle(1.5875).extrude(28)
    ring = cq.Workplane("XY").workplane(offset=20).circle(2.0).extrude(3)              # depth ring
    tip = cq.Solid.makeCone(0.0, 0.5, 0.3, cq.Vector(0, 0, -0.3), cq.Vector(0, 0, 1))
    return flute.union(cq.Workplane().add(cone)).union(shank).union(ring).union(cq.Workplane().add(tip))


def endoscope():
    """8 mm USB endoscope camera, lens face at z = 0, looking along -Z, cable along +Z.
    Returns [(part name, Workplane, colour)]: stainless tip with a glass lens and a ring
    of 6 white LEDs, black grip, rubber strain relief and the cable."""
    steel, glass, led = (0.78, 0.79, 0.81), (0.05, 0.08, 0.16), (1.0, 0.97, 0.80)
    black, rubber = (0.10, 0.10, 0.11), (0.16, 0.16, 0.17)
    tip = revolved([(0, 0.0), (3.6, 0.0), (4.0, 0.4), (4.0, 30.0), (0, 30.0)])
    tip = tip.cut(cq.Workplane("XY").circle(1.6).extrude(1.0))               # lens recess
    leds = None
    for i in range(6):
        a = math.radians(30 + 60 * i)
        c = cq.Workplane("XY").center(2.75 * math.cos(a), 2.75 * math.sin(a)).circle(0.55).extrude(0.4)
        tip = tip.cut(cq.Workplane("XY").center(2.75 * math.cos(a), 2.75 * math.sin(a)).circle(0.55).extrude(0.6))
        leds = c.translate((0, 0, 0.2)) if leds is None else leds.union(c.translate((0, 0, 0.2)))
    lens = cq.Workplane("XY").circle(1.55).extrude(0.4).translate((0, 0, 0.6))
    grip = revolved([(0, 30.0), (4.0, 30.0), (4.0, 48.0), (3.6, 50.0), (0, 50.0)])
    for z in (34.0, 37.0, 40.0, 43.0):                                       # grip rings
        grip = grip.cut(cq.Workplane("XY").workplane(offset=z).circle(5).circle(3.7).extrude(0.8))
    relief = revolved([(0, 50.0), (3.2, 50.0), (2.0, 64.0), (0, 64.0)])
    cable = cq.Workplane("XY").workplane(offset=64.0).circle(1.75).extrude(30)
    return [("tip", tip, steel), ("lens", lens, glass), ("LEDs", leds, led),
            ("grip", grip, black), ("strain relief", relief, rubber), ("cable", cable, black)]


def bushing(d=6.0, od=10.0, l=10.0):
    return cq.Workplane("XY").circle(od / 2).circle(d / 2).extrude(l).edges().chamfer(0.3)


def hose_fitting():
    """G1/8 straight barb fitting: thread into the part along -Z from z = 0."""
    thread = threaded_rod(9.7, 6.0, 0.9, 0.5).translate((0, 0, -6))
    hexb = hex_prism(14.0, 5.0)
    barb = revolved([(0, 5), (3.2, 5), (3.2, 8), (4.2, 9), (3.2, 13), (4.2, 14), (3.2, 18), (0, 18)])
    return thread.union(hexb).union(barb).cut(cq.Workplane("XY").workplane(offset=-6).circle(1.5).extrude(24))


def ds18b20_clamp():
    """DS18B20 temperature probe (Ø6 x 30 stainless tube) in an aluminium clamp block that is
    bonded with thermal epoxy to a flat face of the spindle body (no holes in the spindle).
    Local frame: contact face on z = 0, block towards +Z; probe along X, cable out at +X."""
    block = cq.Workplane("XY").box(30.0, 12.0, 9.0, centered=(True, True, False)).edges("|Y").fillet(1.0)
    block = block.cut(cq.Workplane("YZ").center(0, 4.5).circle(3.1).extrude(32, both=True))
    block = block.cut(cq.Workplane("XY").workplane(offset=6).center(-6, 0).circle(1.25).extrude(4))  # M3 grub
    grub = cq.Workplane("XY").workplane(offset=7.5).center(-6, 0).circle(1.5).extrude(1.0)
    tube = cq.Workplane("YZ").center(0, 4.5).circle(3.0).extrude(31.0).translate((-14.0, 0, 0))
    boot = cq.Workplane("YZ").center(0, 4.5).circle(3.3).extrude(10.0).translate((17.0, 0, 0))
    cable = cq.Workplane("YZ").center(0, 4.5).circle(2.0).extrude(18.0).translate((27.0, 0, 0))
    return [("clamp block", block, (0.80, 0.82, 0.85)), ("M3 grub screw", grub, (0.15, 0.15, 0.16)),
            ("probe", tube, (0.78, 0.79, 0.81)), ("boot", boot, (0.10, 0.10, 0.11)),
            ("cable", cable, (0.10, 0.10, 0.11))]


def adxl345_box():
    """ADXL345 board (GY-291, 20.3 x 15.7 mm) in a small aluminium box with a clear lid,
    bonded to a flat face of the spindle near the upper bearing.
    Local frame: base on z = 0 (against the spindle), box towards +Z, cable out at +X."""
    L, W, H, t = 32.0, 26.0, 12.0, 1.5
    box = cq.Workplane("XY").box(L, W, H - 1.5, centered=(True, True, False)).edges("|Z").fillet(2.5)
    box = box.cut(cq.Workplane("XY").workplane(offset=t).rect(L - 2 * t, W - 2 * t).extrude(H))
    box = box.cut(cq.Workplane("YZ").center(0, 6.0).circle(2.6).extrude(4.0).translate((L / 2 - 3.0, 0, 0)))
    lid = (cq.Workplane("XY").workplane(offset=H - 1.5).rect(L, W).extrude(1.5).edges("|Z").fillet(2.5))
    pcb = cq.Workplane("XY").workplane(offset=t + 2.0).rect(20.3, 15.7).extrude(1.6).translate((-3.0, 0, 0))
    pcb = pcb.cut(cq.Workplane("XY").workplane(offset=t + 2.0).pushPoints([(-10.4, 5.9), (-10.4, -5.9)])
                  .circle(1.5).extrude(2))
    chip = cq.Workplane("XY").workplane(offset=t + 3.6).rect(5.0, 3.0).extrude(1.0).translate((-3.0, 0, 0))
    header = cq.Workplane("XY").workplane(offset=t + 3.6).rect(2.5, 15.2).extrude(2.5).translate((5.5, 0, 0))
    standoffs = cq.Workplane("XY").workplane(offset=t).pushPoints([(-13.4, 5.9), (-13.4, -5.9)]) \
        .circle(1.8).extrude(2.0)
    gland = cq.Workplane("YZ").center(0, 6.0).circle(4.0).extrude(5.0).translate((L / 2, 0, 0))
    cable = cq.Workplane("YZ").center(0, 6.0).circle(2.3).extrude(20.0).translate((L / 2 + 5, 0, 0))
    return [("box", box.union(standoffs), (0.70, 0.72, 0.75)), ("clear lid", lid, (0.75, 0.85, 0.95, 0.35)),
            ("GY-291 board", pcb, (0.10, 0.30, 0.65)), ("ADXL345 chip", chip, (0.08, 0.08, 0.08)),
            ("pin header", header, (0.05, 0.05, 0.05)), ("cable gland", gland, (0.10, 0.10, 0.11)),
            ("cable", cable, (0.10, 0.10, 0.11))]
