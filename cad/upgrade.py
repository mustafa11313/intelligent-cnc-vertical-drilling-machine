"""Upgrade parts for the drilling machine, placed in Ana_Montaj's own coordinates.

    python3 upgrade.py          # step/upgrade/*.step + step/upgrade_assembly.step

Every part is built at its final position in the SolidWorks assembly's
world frame (mm, Y up), measured from Ana_Montaj_1_6_25.x_t with xt/.
Insert upgrade_assembly.step (or a single part) into Ana_Montaj and mate
its origin to the assembly origin: everything lands where it belongs.

What moves in the upgraded machine:
  * The whole Z unit (holder, spindle, Z rails, nut, screw, motor) moves
    by ZSHIFT = (+6, -45, 0): -45 so a standard 38 mm PCB bit reaches the
    board, +6 because the new Y carriage plate is 6 mm thicker.
  * The single Y rail becomes two rails in the cross profile's slots.
Parts that keep their place in the frame (table, plates) need no shift.
Bought parts (rails, blocks, bearings) are not modelled here; the
buy list in README.md names them.
"""
import os

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "step", "upgrade")

ZSHIFT = (6.0, -45.0, 0.0)          # Z unit: new position = old + ZSHIFT
YC = -125.3                         # carriage / spindle centre line (world Z)
SPINDLE = (-27.0, YC)               # spindle axis (world X, Z), before ZSHIFT


# ------------------------------------------------------------------ helpers
def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl(d, p, axis, length):
    """Cylinder of diameter d starting at point p, running `length` along axis (unit vector)."""
    return cq.Workplane("XY").add(cq.Solid.makeCylinder(d / 2, length, cq.Vector(*p), cq.Vector(*axis)))


def hole(part, d, p, axis, length):
    return part.cut(cyl(d, p, axis, length))


def cbore(part, d, cd, depth, p, axis, length):
    """Through hole d with counterbore cd x depth at the entry point p."""
    part = hole(part, d, p, axis, length)
    return hole(part, cd, p, axis, depth)


def shifted(wp, v=ZSHIFT):
    return wp.translate(v)


# ------------------------------------------------- Y carriage (replaces Tabla2)
def y_carriage_plate():
    """Carries the Z unit. Replaces Tabla2 (10 mm, one HGW15CC).

    Back face (x=-104) rides on TWO HGH15CA blocks, one on each of two
    HGR15 rails fitted in the cross profile's slots (rail centres at
    y 347.5 and 392.5, 45 mm apart): the spindle no longer hangs from a
    single block. The blocks sit in 7 mm pockets so the back face stays at
    x=-104 and the existing top link (Y eksen takozu) still bolts on.
    Front face (x=-88) carries the Z rails, now 195 mm long and 45 mm lower.
    """
    x0, x1, y0, y1, z0, z1 = -104.0, -88.0, 240.0, 455.0, YC - 60, YC + 60
    p = box(x0, x1, y0, y1, z0, z1)
    for yr in (347.5, 392.5):
        p = p.cut(box(x0, x0 + 7, yr - 18, yr + 18, YC - 32, YC + 32))          # block pocket
        for dy in (-13, 13):
            for dz in (-13, 13):                                                   # HGH15CA: M4 on 26 x 26
                p = cbore(p, 4.5, 8.0, 4.5, (x1, yr + dy, YC + dz), (-1, 0, 0), 16)
    for zr in (YC - 50, YC + 50):                                                  # Z rails, M4 at 60 pitch
        for y in (282.5, 342.5, 402.5):
            p = hole(p, 3.3, (x1, y, zr), (-1, 0, 0), 10)
    for z in (-167.8, -152.8, -97.8, -82.8):                                       # top plate, M5 tapped
        p = hole(p, 4.2, (-98.0, y1, z), (0, -1, 0), 15)
    for z in (-178.3, -142.8, -127.8, -112.8, -72.3):                             # link to Y eksen takozu
        p = cbore(p, 5.5, 10.0, 5.5, (x1, 449.0, z), (-1, 0, 0), 16)
    return p


# -------------------------------------------- Z top plate (replaces Arka Kapak)
def z_top_plate():
    """Takes the Z screw's thrust in two 608ZZ bearings instead of the
    stepper's own bearing. The motor stands on 4 M3x50 standoffs above it,
    with the coupler in between. Clamp the screw journal with an 8 mm lock
    collar above and below the bearing pair. Same 4 screws into the
    carriage plate as the original Arka Kapak; 6 mm longer at the front
    because the Z unit moved forward."""
    ax, az = -81.0 + ZSHIFT[0], YC                                                 # Z screw axis, moved with the Z unit
    p = box(-104.0, -53.0, 455.0, 475.0, YC - 50, YC + 50)
    for z in (-167.8, -152.8, -97.8, -82.8):
        p = cbore(p, 5.5, 10.0, 5.5, (-98.0, 475.0, z), (0, -1, 0), 20)
    p = hole(p, 12.0, (ax, 475.0, az), (0, -1, 0), 20)                             # journal clearance
    p = hole(p, 22.0, (ax, 475.0, az), (0, -1, 0), 7.5)                            # 608 from the top
    p = hole(p, 22.0, (ax, 455.0, az), (0, 1, 0), 7.5)                             # 608 from below
    for dx in (-15.5, 15.5):
        for dz in (-15.5, 15.5):                                                   # M3 standoffs, NEMA17 square
            p = hole(p, 2.5, (ax + dx, 475.0, az + dz), (0, -1, 0), 8)
    p = hole(p, 11.0, (Z_SENSOR[0], 475.0, Z_SENSOR[1]), (0, -1, 0), 20)          # Z home sensor, tap M12x1
    return p


# ------------------------------------------------------------ home switches
# Three LJ12A3-4-Z/BX inductive sensors (M12, 4 mm nominal range on steel).
# Each sees a steel target and triggers about 3 mm from it, a few mm before
# the axis reaches a hard end. The ends were measured on Ana_Montaj with xt/:
#   X: the table's blocks reach the ends of the 400 mm rails (x = 200)
#   Y: the spindle holder Spindle_Tutucu (152 mm wide, wider than the
#      120 mm carriage plate) reaches the side plate Yan_Plaka_2 (z = 22.5)
#      after 71.8 mm. Side plate inner faces are 311.5 mm apart, so Y has
#      159.5 mm of travel, not the 191 mm of the carriage plate alone
#   Z: the spindle holder's top face reaches the Z top plate (102.8 mm up)
SENSOR_RANGE = 3.0                  # trigger gap used for placement (assured range of a 4 mm sensor ~3.2)
X_SENSOR = (192.0, 106.0)           # (x, y): on the front base profile, looks along -z at the front blocks
Y_SENSOR = (-59.5, 340.0)           # (x, y): through Yan_Plaka_2, looks along -z at the holder end (Z homed)
Z_SENSOR = (-64.0, -165.0)          # (x, z): through the Z top plate, looks down at the holder top
HOLDER_TOP = 352.2                  # Spindle_Tutucu top face after ZSHIFT (y), Z at its CAD pose
Z_HOME_DZ = 455.0 - SENSOR_RANGE - (HOLDER_TOP + 2.0)    # Z rise at which the switch triggers
PULL_OFF = 1.0                      # GRBL $27
HOLDER_END = -49.3                  # Spindle_Tutucu end face towards Yan_Plaka_2 (z)
Y_TRAVEL_PLUS = 22.5 - HOLDER_END                       # 71.8: from the CAD pose to the hard stop
Y_HOME_DY = 22.5 - SENSOR_RANGE - (HOLDER_END + 2.0)    # 66.8: Y move at which the switch triggers


def x_limit_bracket():
    """5 mm aluminium plate on the outside face of the front base profile
    (z = 22.5), beyond the side plate. One M8 T-slot bolt in the profile's
    upper slot (y 67.5), slotted ±5 mm in X to set the trigger point. The
    sensor screws into the M12x1 thread above the profile top (no room for
    a nut on the inside), locked with its nut outside, and looks at the
    side of the front rail's leading HGH15CA block (steel) 3 mm away."""
    x, y = X_SENSOR
    p = box(x - 10, x + 10, 55.0, 118.0, 22.5, 27.5)
    p = p.cut(box(x - 5, x + 5, 67.5 - 4.25, 67.5 + 4.25, 22.5, 27.5))           # M8 slot, ±5 mm
    for dx in (-5, 5):
        p = hole(p, 8.5, (x + dx, 67.5, 22.5), (0, 0, 1), 5)
    return hole(p, 11.0, (x, y, 22.5), (0, 0, 1), 5)                              # tap M12x1


def y_home_flag():
    """2 mm steel target on the spindle holder's end face (towards
    Yan_Plaka_2), two M3 screws into new tapped holes. The holder, not the
    carriage plate, is what reaches the side plate first, so the target
    goes on it. It moves with Z: GRBL homes Z first, so during the Y
    homing move the holder is Z_HOME_DZ - PULL_OFF higher than in the CAD
    pose and the target sits in front of the sensor. The sensor screws
    into a new M12x1 thread in Yan_Plaka_2, face flush with its inside,
    locked with its nut outside. Shown at the CAD pose (Z not homed)."""
    x, y = Y_SENSOR
    y -= Z_HOME_DZ - PULL_OFF
    p = box(-66.0, -53.0, y - 8, y + 8, HOLDER_END, HOLDER_END + 2)
    for dy in (-4, 4):
        p = hole(p, 3.4, (x, y + dy, HOLDER_END), (0, 0, 1), 2)
    return p


def z_home_flag():
    """2 mm steel target on the spindle holder's top face, two M3 screws
    into new tapped holes. The holder top is only 10 mm wide, so the flag
    overhangs it to give the sensor a full 16 mm target. Moves with Z."""
    x, z = Z_SENSOR
    p = box(-70.0, -54.0, HOLDER_TOP, HOLDER_TOP + 2, z - 8, z + 8)
    for dz in (-4, 4):
        p = hole(p, 3.4, (-62.0, HOLDER_TOP, z + dz), (0, 1, 0), 2)
    return p


# ----------------------------------------------------------- X table
TABLE_C = (48.0, -133.2)            # table centre (world X, Z)


def x_table():
    """Replaces "300x250 Is Tablasi": same outline, pocket, underside lanes
    and nut-block recess, but TWO HGH15CA blocks per rail (stops the table
    rocking on one block) with M4 screws (the original used M5 into M4
    threads). Four M5 tapped holes at (±90, ±90) take the vacuum plate."""
    cx, cz = TABLE_C
    p = box(-52.0, 148.0, 115.0, 125.0, -283.2, 16.8)
    p = p.cut(box(-52.0, 148.0, 115.0, 118.0, -283.2, -249.5))                     # rail lanes, 3 mm
    p = p.cut(box(-52.0, 148.0, 115.0, 118.0, -17.0, 16.8))
    p = p.cut(box(33.0, 63.0, 115.0, 117.0, -151.5, -111.5))                       # nut block recess
    p = p.cut(box(-27.0, 123.0, 121.0, 125.0, -233.2, -33.2).edges("|Y").fillet(5))  # 150 x 200 x 4 pocket
    for bx in (cx - 49, cx + 49):                                                  # 4 blocks
        for rz in (0.0, -266.5):
            for dx in (-13, 13):
                for dz in (-13, 13):
                    p = cbore(p, 4.5, 8.0, 4.5, (bx + dx, 125.0, rz + dz), (0, -1, 0), 10)
    for x in (40.5, 55.5):                                                         # X nut block, M4
        for z in (-146.5, -116.5):
            p = cbore(p, 4.5, 8.0, 2.0, (x, 121.0, z), (0, -1, 0), 6)
    for sx in (-90, 90):
        for sz in (-90, 90):
            p = hole(p, 4.2, (cx + sx, 125.0, cz + sz), (0, -1, 0), 10)            # M5 for vacuum plate
    return p


def vacuum_plate(thick=12.0, grid=15.0, area=170.0):
    """Vacuum hold-down, 200 x 200 x 12, on top of the table. A 3 x 2 mm
    groove grid over 170 x 170 mm, fed from a G1/8 port in the front edge
    through a Ø6 channel. Put a 3 mm MDF bleeder sheet on the grid (MDF is
    porous) and the PCB on the MDF: the vacuum pulls the board flat
    through it, and the MDF is the sacrificial backer. Two Ø3 pin holes
    (outside the grid) register double-sided boards; tape over any grid
    area the board doesn't cover."""
    cx, cz = TABLE_C
    y0, y1 = 125.0, 125.0 + thick
    p = box(cx - 100, cx + 100, y0, y1, cz - 100, cz + 100)
    n = int(area // grid)
    off = -(n * grid) / 2
    for i in range(n + 1):                                                         # grooves along X and Z
        c = off + i * grid
        p = p.cut(box(cx - area / 2, cx + area / 2, y1 - 2, y1, cz + c - 1.5, cz + c + 1.5))
        p = p.cut(box(cx + c - 1.5, cx + c + 1.5, y1 - 2, y1, cz - area / 2, cz + area / 2))
    p = hole(p, 6.0, (cx, y1, cz), (0, -1, 0), thick / 2 + 3)                      # centre feed
    p = hole(p, 6.0, (cx + 100, y0 + thick / 2, cz), (-1, 0, 0), 100)              # channel from the edge
    p = hole(p, 8.8, (cx + 100, y0 + thick / 2, cz), (-1, 0, 0), 10)               # G1/8 tapping
    for sx in (-90, 90):
        for sz in (-90, 90):
            p = cbore(p, 5.5, 10.0, 5.5, (cx + sx, y1, cz + sz), (0, -1, 0), thick)
    for sz in (-95, 95):
        p = hole(p, 3.0, (cx, y1, cz + sz), (0, -1, 0), thick)
    return p


# ------------------------------------------------ head: yoke, foot, camera
# Designed against the Z unit as it is in Ana_Montaj, then moved by ZSHIFT.
ROD_DZ = 52.0                       # guide rods at spindle axis ± 52 mm in world Z
ARM_Y = (255.2, 267.2)              # arms hang under the spindle holder (bottom face y 267.2)


def head_yoke():
    """U-shaped yoke under the spindle holder (Spindle_Tutucu). Two arms
    pass either side of the spindle body (8 mm clear of it) and are joined
    by a crossbar in front. Each arm holds a 6x10x10 bronze bushing for a
    pressure-foot guide rod. The crossbar holds an Ø8 USB endoscope
    camera looking down, 58 mm in front of the spindle axis, locked with
    an M3 set screw. Two M5 screws into new tapped holes in the holder's
    bottom face."""
    sx, sz = SPINDLE
    y0, y1 = ARM_Y
    p = None
    for zr in (sz - ROD_DZ, sz + ROD_DZ):
        arm = box(-73.0, 37.0, y0, y1, zr - 6, zr + 6)
        p = arm if p is None else p.union(arm)
    p = p.union(box(25.0, 37.0, y0, y1, sz - ROD_DZ - 6, sz + ROD_DZ + 6))
    for zr in (sz - ROD_DZ, sz + ROD_DZ):
        p = cbore(p, 5.5, 10.0, 5.0, (-65.5, y0, zr), (0, 1, 0), 12)              # to the holder
        p = hole(p, 10.0, (sx, y0, zr), (0, 1, 0), 12)                             # bushing bore
    cam = (31.0, sz + 25.0)
    p = hole(p, 8.2, (cam[0], y0, cam[1]), (0, 1, 0), 12)                          # camera
    p = hole(p, 2.5, (37.0, (y0 + y1) / 2, cam[1]), (-1, 0, 0), 7)                 # M3 set screw
    return shifted(p)


def pressure_foot(rest_y=169.3):
    """Spring-loaded pressure foot and dust shoe in one part.
    At rest its face is 2 mm below the tip of a bit with 20 mm out of the
    collet. It meets the board first, two springs (on the guide rods
    between foot and yoke) press the board flat, the bit drills through
    the Ø6 hole, and the Ø16 side port takes a vacuum hose: chips leave
    through four radial grooves in the face. Stroke 12 mm (collar on the
    rods above the yoke)."""
    sx, sz = SPINDLE
    top = rest_y + 18.7
    p = cyl(44.0, (sx, rest_y, sz), (0, 1, 0), top - rest_y)
    p = p.union(box(sx - 6, sx + 6, top - 8, top, sz - ROD_DZ - 6, sz - 15))       # lugs out to the rods
    p = p.union(box(sx - 6, sx + 6, top - 8, top, sz + 15, sz + ROD_DZ + 6))
    d = (0.7071, 0.0, -0.7071)                                                     # port: front and to -Z
    port_c = (sx, rest_y + 10.0, sz)
    p = p.union(cyl(16.0, port_c, d, 55.0))
    p = p.cut(cyl(34.0, (sx, rest_y + 3, sz), (0, 1, 0), 30))                      # chamber
    p = p.cut(cyl(12.0, port_c, d, 60.0))                                          # port bore
    p = hole(p, 6.0, (sx, rest_y - 1, sz), (0, 1, 0), 5)                           # bit hole
    for a in (0, 90):                                                              # radial air grooves
        if a == 0:
            p = p.cut(box(sx - 23, sx + 23, rest_y, rest_y + 1.5, sz - 2, sz + 2))
        else:
            p = p.cut(box(sx - 2, sx + 2, rest_y, rest_y + 1.5, sz - 23, sz + 23))
    for zr in (sz - ROD_DZ, sz + ROD_DZ):
        p = hole(p, 6.0, (sx, top - 8, zr), (0, 1, 0), 8)                          # rod seats (press fit)
    return shifted(p)


PARTS = {
    "y_carriage_plate": y_carriage_plate,
    "z_top_plate_608x2": z_top_plate,
    "x_table_4block": x_table,
    "vacuum_plate_200x200": vacuum_plate,
    "head_yoke_camera": head_yoke,
    "pressure_foot_dustshoe": pressure_foot,
    "x_limit_bracket": x_limit_bracket,
    "y_home_flag": y_home_flag,
    "z_home_flag": z_home_flag,
}


def build():
    os.makedirs(OUT, exist_ok=True)
    asm = cq.Assembly(name="upgrade")
    shapes = {}
    for name, fn in PARTS.items():
        s = fn()
        shapes[name] = s
        cq.exporters.export(s, os.path.join(OUT, name + ".step"))
        bb = s.val().BoundingBox()
        print(f"{name:26s} {bb.xlen:6.1f} x {bb.ylen:6.1f} x {bb.zlen:6.1f} mm  "
              f"at x {bb.xmin:.1f}..{bb.xmax:.1f}  y {bb.ymin:.1f}..{bb.ymax:.1f}  z {bb.zmin:.1f}..{bb.zmax:.1f}")
        asm.add(s, name=name)
    asm.save(os.path.join(HERE, "step", "upgrade_assembly.step"))
    return shapes


if __name__ == "__main__":
    build()
