"""CNC router: full assembly, placed by machine position.

World frame: Z up, X left-right, Y front(-) to back(+), origin on the floor
under the centre of the base. The spindle axis is at X = machine X, Y = 0.

Kinematics: fixed gantry, moving table.
  X  carriage moves left-right on the gantry beam    tx = x
  Y  table moves front-back under the gantry         ty = -y  (table moves
     forward when the tool goes +Y relative to the work)
  Z  plate moves up-down on the carriage             p0 = Z_TOP + z

Travel: X ±150, Y ±125, Z -100..0 (work area 300 x 250 x 100 mm).

python3 assembly.py            -> step/router_assembly.step (home pose),
                                  step/parts/*.step (one file per part)
python3 assembly.py x y z      -> the assembly at that machine position
"""
import os
import sys

import cadquery as cq
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parts as P  # noqa: E402
from parts import box, cyl  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TRAVEL = {"x": (-150.0, 150.0), "y": (-125.0, 125.0), "z": (-100.0, 0.0)}
Z_TOP = 303.0                     # Z plate bottom (p0) at z = 0

# ------------------------------------------------------------- key planes
BF = 193.5                        # gantry beam front face (Y)
RISER_Y = 163.5                   # front face of the X rail risers (rail base)
X_BK_X, X_BF_X = 267.5, -270.0
X_RAIL_Z = (320.0, 440.0)         # X rail centres (= beam slots)
X_SCREW = (158.5, 380.0)          # X screw axis (Y, Z)
X_SUPPORT_Y = 183.5               # X BK/BF base face (on the beam's 10 mm front plate)
X_CAR_Y = (120.5, 135.5)          # X carriage plate (front, back)
Z_SCREW_Y = 95.5                  # Z screw axis Y
Z_RAIL_BASE = 96.5                # Z rails: base face (Y), rails at X ±50
Z_PLATE_Y = (47.5, 62.5)          # Z plate (front, back)
Z_BLOCK_Z = (340.0, 425.0)        # Z blocks (fixed on the carriage)
Y_SCREW_Z = 65.0
Y_SUPPORT = (300.0, -300.0)       # BK12 / BF12 centres on the cross member slots
TABLE_Z = (108.0, 123.0)
SPINDLE_DROP = -3.5               # spindle body bottom below the Z plate bottom (negative: above)
MOTOR_HP = 47.14 / 2              # NEMA23 hole half-pitch
NUT_PCD_ANGLES = np.radians(np.arange(0, 360, 60))


# ------------------------------------------------------------- placement
def place(wp, ex=(1, 0, 0), ez=(0, 0, 1), t=(0, 0, 0)):
    """Map a part's canonical X axis to ex and Z axis to ez, then move its
    origin to t."""
    shape = wp.val() if isinstance(wp, cq.Workplane) else wp
    ex, ez = np.array(ex, float), np.array(ez, float)
    if abs(np.dot(ex, ez)) > 0.9:                       # only the axis matters (round parts)
        ex = np.array(any_perp(ez))
    ey = np.cross(ez, ex)
    tr = gp_Trsf()
    tr.SetValues(ex[0], ey[0], ez[0], t[0], ex[1], ey[1], ez[1], t[1], ex[2], ey[2], ez[2], t[2])
    return cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, tr, True).Shape())


def move(shape, t):
    return place(shape, t=t)


def holes(wp, d, pts, axis, length):
    """Cut several equal holes in one boolean."""
    return P.cut_holes(wp, d, pts, axis, length)


def cbore(wp, d, dc, depth_c, pts, axis, length):
    """Through holes d with counterbores dc x depth_c, starting at pts going along axis."""
    return holes(holes(wp, d, pts, axis, length), dc, pts, axis, depth_c)


def any_perp(v):
    v = np.array(v, float)
    a = np.array((1, 0, 0)) if abs(v[0]) < 0.9 else np.array((0, 1, 0))
    return tuple(np.cross(v, a) / np.linalg.norm(np.cross(v, a)))


# ============================================================ made parts
# Built in world coordinates at the home pose of their group (tx = ty = 0,
# Z group at p0 = 0). Aluminium 6061/6082 unless noted.

def table():
    """Worktable 554 x 330 x 15: M6 grid at 50 mm, blocks and nut housing
    bolted from the top through counterbores."""
    t = box(-277, 277, -165, 165, *TABLE_Z)
    grid = [(x, y, TABLE_Z[0]) for x in range(-200, 201, 50) for y in range(-150, 151, 50)
            if not (abs(x) <= 50 and abs(y) <= 50)]
    t = holes(t, 5.0, grid, (0, 0, 1), 15)                                    # M6 tapped
    t = cbore(t, 4.5, 8.0, 7.0, TABLE_BLOCK_BOLTS, (0, 0, -1), 15)            # M4x12 to HGH15CA
    t = cbore(t, 4.5, 8.0, 7.0, TABLE_ACC_BOLTS, (0, 0, -1), 15)              # M4: chain mount, home flag
    return cbore(t, 5.5, 10.0, 7.0, TABLE_NUT_BOLTS, (0, 0, -1), 15)          # M5x16 to the nut housing


TABLE_BLOCK_BOLTS = [(sx * 260 + dx, sy * 100 + dy, TABLE_Z[1]) for sx in (-1, 1) for sy in (-1, 1)
                     for dx in (-13, 13) for dy in (-13, 13)]
TABLE_NUT_BOLTS = [(sx * 30, sy * 15, TABLE_Z[1]) for sx in (-1, 1) for sy in (-1, 1)]
Y_CHAIN_X = 125.0                                                         # Y drag chain centre line
Y_FLAG = dict(x=(222.0, 242.0), y=(99.0, 102.0))                          # Y home flag (table coordinates)
TABLE_ACC_BOLTS = [(Y_CHAIN_X - 5, 0, TABLE_Z[1]), (Y_CHAIN_X + 5, 0, TABLE_Z[1]),
                   (227.0, 112.0, TABLE_Z[1]), (237.0, 112.0, TABLE_Z[1])]


def spoilboard():
    """12 mm MDF on the table (sacrificial)."""
    return box(-277, 277, -165, 165, TABLE_Z[1], TABLE_Z[1] + 12)


def y_nut_housing():
    h = box(-40, 40, -25, 25, 42, TABLE_Z[0])
    h = h.cut(cyl(28.5, (0, -25, Y_SCREW_Z), (0, 1, 0), 50))
    h = holes(h, 4.2, [(19 * np.cos(q), -25, Y_SCREW_Z + 19 * np.sin(q)) for q in NUT_PCD_ANGLES], (0, 1, 0), 12)
    return holes(h, 4.2, [(x, y, TABLE_Z[0]) for x, y, _ in TABLE_NUT_BOLTS], (0, 0, -1), 12)


Y_STANDOFF_Y = (330.0, 358.0)


def y_motor_plate():
    """10 mm plate on the back cross member (2 x M6 + T-nuts); motor on 28 mm standoffs."""
    p = box(-45, 45, 320, 330, 0, 110)
    p = p.cut(cyl(42, (0, 320, Y_SCREW_Z), (0, 1, 0), 10))
    p = cbore(p, 5.5, 10.0, 5.0, [(sx * MOTOR_HP, 320, Y_SCREW_Z + sz * MOTOR_HP) for sx in (-1, 1)
                                  for sz in (-1, 1)], (0, 1, 0), 10)
    return holes(p, 6.6, [(sx * 30, 320, 20) for sx in (-1, 1)], (0, 1, 0), 10)


UPRIGHT_T = 30.0                  # side plate thickness
X_SENSOR_YZ = (128.0, 285.0)      # X home sensor axis on the right side plate
X_SENSOR_BLOCK_BOLTS = [(118.0, 275.0), (138.0, 295.0)]
UPRIGHT_BASE_BOLTS = [(y, z) for y in (140, 200, 260, 300) for z in (20, 60)]
UPRIGHT_BEAM_BOLTS = [(y, z) for y in (BF + 20, BF + 60) for z in (320, 360, 400, 440)]
X_STANDOFF_X = (280.0 + UPRIGHT_T, 325.0)


def upright(right):
    """30 mm gantry side plate, bolted to the side profile (8 x M6 + T-nuts)
    and to the beam ends (8 x M12 into the tapped profile cores)."""
    t = UPRIGHT_T
    x0 = 280.0 if right else -280.0 - t
    xo, xi, out = (x0 + t, x0, 1) if right else (x0, x0 + t, -1)
    u = box(x0, x0 + t, 110, 320, 0, 460)
    u = holes(u, 6.6, [(x0, y, z) for y, z in UPRIGHT_BASE_BOLTS], (1, 0, 0), t)
    u = cbore(u, 13.0, 20.0, 13.0, [(xo, y, z) for y, z in UPRIGHT_BEAM_BOLTS], (-out, 0, 0), t)
    if right:
        u = u.cut(cyl(13, (x0, *X_SENSOR_YZ), (1, 0, 0), t))                                 # X home sensor
        u = holes(u, 5.5, [(x0, y, z) for y, z in X_SENSOR_BLOCK_BOLTS], (1, 0, 0), t)
        u = u.cut(cyl(42, (x0, *X_SCREW), (1, 0, 0), t))
        u = cbore(u, 5.5, 10.0, 5.0, [(xi, X_SCREW[0] + sy * MOTOR_HP, X_SCREW[1] + sz * MOTOR_HP)
                                      for sy in (-1, 1) for sz in (-1, 1)], (1, 0, 0), t)
    return u


# ---- torsion box around the 80x160 beam: 10 mm plates on all four faces,
# each bolted into the beam slots (M6 + T-nuts), top and bottom plates also
# screwed into the edges of the front and back plates so the four plates
# close into a box.
BOX_T = 10.0
BEAM_BACK = BF + 80
BOX_X = [-240, -160, -80, 0, 80, 160, 240]
BOX_EDGE_X = [-200, -120, -40, 40, 120, 200]
BOX_ROWS_Z = (320, 360, 400, 440)
BOX_ROWS_Y = (BF + 20, BF + 60)


def beam_front_plate():
    p = box(-280, 280, BF - BOX_T, BF, 300, 460)
    p = cbore(p, 6.6, 11.0, 6.5, [(x, BF - BOX_T, z) for x in BOX_X for z in BOX_ROWS_Z], (0, 1, 0), BOX_T)
    p = holes(p, 5.0, [(x, BF - BOX_T, zr) for zr in X_RAIL_Z for x in RISER_BOLTS_X], (0, 1, 0), BOX_T)  # M6 risers
    p = holes(p, 4.2, [(xc, BF - BOX_T, X_SCREW[1] + sz * 23) for xc in (X_BK_X, X_BF_X) for sz in (-1, 1)],
              (0, 1, 0), BOX_T)                                                              # M5 BK12/BF12
    p = holes(p, 4.2, [(x, BF - BOX_T / 2, 460) for x in BOX_EDGE_X], (0, 0, -1), 12)        # M5 edge, top
    return holes(p, 4.2, [(x, BF - BOX_T / 2, 300) for x in BOX_EDGE_X], (0, 0, 1), 12)      # M5 edge, bottom


def beam_back_plate():
    p = box(-280, 280, BEAM_BACK, BEAM_BACK + BOX_T, 300, 460)
    p = cbore(p, 6.6, 11.0, 6.5, [(x, BEAM_BACK + BOX_T, z) for x in BOX_X for z in BOX_ROWS_Z], (0, -1, 0), BOX_T)
    p = holes(p, 4.2, [(x, BEAM_BACK + BOX_T / 2, 460) for x in BOX_EDGE_X], (0, 0, -1), 12)
    return holes(p, 4.2, [(x, BEAM_BACK + BOX_T / 2, 300) for x in BOX_EDGE_X], (0, 0, 1), 12)


def beam_cap_plate(top):
    z0 = 460.0 if top else 300.0 - BOX_T
    face, d = (z0 + BOX_T, (0, 0, -1)) if top else (z0, (0, 0, 1))
    p = box(-280, 280, BF - BOX_T, BEAM_BACK + BOX_T, z0, z0 + BOX_T)
    p = cbore(p, 6.6, 11.0, 6.5, [(x, y, face) for x in BOX_X for y in BOX_ROWS_Y], d, BOX_T)
    edges = [(x, y, face) for x in BOX_EDGE_X for y in (BF - BOX_T / 2, BEAM_BACK + BOX_T / 2)]
    return cbore(p, 5.5, 10.0, 5.5, edges, d, BOX_T)


RISER_BOLTS_X = list(range(-210, 211, 60))


def x_riser(zc):
    """20 x 30 bar under each X rail, bolted to the beam front plate (M6)."""
    r = box(-280, 280, RISER_Y, BF - BOX_T, zc - 15, zc + 15)
    r = holes(r, 3.3, [(x, RISER_Y, zc) for x in P.rail_holes(560)], (0, 1, 0), 12)              # M4 rail
    return cbore(r, 6.6, 11.0, 6.5, [(x, RISER_Y, zc) for x in RISER_BOLTS_X], (0, 1, 0), 20)



def x_carriage():
    """15 mm X carriage plate, 180 x 260. HGH15CA blocks on the back,
    HGW15CC Z blocks, Z screw supports and Z motor bracket on the front."""
    yf, yb = X_CAR_Y
    c = box(-90, 90, yf, yb, 270, 530)
    c = cbore(c, 4.5, 8.0, 7.0, CAR_XBLOCK_BOLTS, (0, 1, 0), 15)               # M4x12 to X blocks
    c = holes(c, 3.3, CAR_ZBLOCK_BOLTS, (0, 1, 0), 15)                          # M4 from the HGW15CC side
    c = cbore(c, 5.5, 10.0, 7.0, CAR_NUT_BOLTS, (0, 1, 0), 15)
    c = holes(c, 4.2, [(sx * 23, yf, z) for sx in (-1, 1) for z in (472.5, 282.0)], (0, 1, 0), 15)  # BK/BF
    c = holes(c, 4.2, [(sx * 20, yf, 505) for sx in (-1, 1)], (0, 1, 0), 12)            # motor bracket
    c = holes(c, 5.5, [(50, yf, z) for z in (505, 520)], (0, 1, 0), 15)                 # Z home sensor bracket
    return holes(c, 4.2, [(x, 128.0, 530) for x in (-55, -45)], (0, 0, -1), 12)        # X chain arm


CAR_XBLOCK_BOLTS = [(sx * 59.3 + dx, X_CAR_Y[0], z + dz) for sx in (-1, 1) for z in X_RAIL_Z
                    for dx in (-13, 13) for dz in (-13, 13)]
CAR_ZBLOCK_BOLTS = [(sx * 50 + dx, X_CAR_Y[0], z + dz) for sx in (-1, 1) for z in Z_BLOCK_Z
                    for dx in (-19, 19) for dz in (-15, 15)]
CAR_NUT_BOLTS = [(sx * 15, X_CAR_Y[0], z) for sx in (-1, 1) for z in (360, 400)]


def x_nut_housing():
    h = box(-25, 25, X_CAR_Y[1], 175, 345, 415)
    h = h.cut(cyl(28.5, (-25, *X_SCREW), (1, 0, 0), 50))
    h = holes(h, 4.2, [(25, X_SCREW[0] + 19 * np.sin(q), X_SCREW[1] - 19 * np.cos(q)) for q in NUT_PCD_ANGLES],
              (-1, 0, 0), 12)
    return holes(h, 4.2, [(x, X_CAR_Y[1], z) for x, _, z in CAR_NUT_BOLTS], (0, 1, 0), 12)


def z_motor_bracket():
    """10 mm L bracket on top of the carriage front; motor sits on it."""
    b = box(-32, 32, 110.5, X_CAR_Y[0], 495, 530).union(box(-32, 32, 65.5, X_CAR_Y[0], 520, 530))
    b = b.cut(cyl(40, (0, Z_SCREW_Y, 520), (0, 0, 1), 10))
    b = holes(b, 4.2, [(sx * MOTOR_HP, Z_SCREW_Y + sy * MOTOR_HP, 530) for sx in (-1, 1) for sy in (-1, 1)],
              (0, 0, -1), 15)
    return cbore(b, 5.5, 10.0, 5.0, [(sx * 20, 110.5, 505) for sx in (-1, 1)], (0, 1, 0), 10)


# ---- Z group (p0 = 0 at the bottom of the Z plate)
ZP_RISER_BOLTS = [(sx * 50, Z_PLATE_Y[0], z) for sx in (-1, 1) for z in (60, 120, 180, 240)]
ZP_CLAMP_BOLTS = [(sx * 30, Z_PLATE_Y[1], z) for sx in (-1, 1) for z in (15, 55)]
ZP_NUT_BOLTS = [(sx * 15, Z_PLATE_Y[0], z) for sx in (-1, 1) for z in (110, 130)]


def z_plate():
    yf, yb = Z_PLATE_Y
    p = box(-70, 70, yf, yb, 0, 300)
    p = cbore(p, 5.5, 10.0, 7.0, ZP_RISER_BOLTS, (0, 1, 0), 15)
    p = cbore(p, 6.6, 11.0, 6.5, ZP_CLAMP_BOLTS, (0, -1, 0), 15)
    return cbore(p, 5.5, 10.0, 7.0, ZP_NUT_BOLTS, (0, 1, 0), 15)


def z_riser(xc):
    r = box(xc - 10, xc + 10, Z_PLATE_Y[1], Z_RAIL_BASE, 0, 300)
    r = holes(r, 3.3, [(xc, Z_RAIL_BASE, 5 + z) for z in P.rail_holes(290)], (0, -1, 0), 12)   # M4 rail
    return holes(r, 4.2, [(xc, Z_PLATE_Y[1], z) for _, _, z in ZP_RISER_BOLTS[:4]], (0, 1, 0), 12)  # M5 plate


def z_nut_housing():
    h = box(-24, 24, Z_PLATE_Y[1], 115, 100, 140)
    h = h.cut(cyl(28.5, (0, Z_SCREW_Y, 100), (0, 0, 1), 40))
    h = holes(h, 4.2, [(19 * np.cos(q), Z_SCREW_Y + 19 * np.sin(q), 140) for q in NUT_PCD_ANGLES], (0, 0, -1), 12)
    return holes(h, 4.2, [(x, Z_PLATE_Y[1], z) for x, _, z in ZP_NUT_BOLTS], (0, 1, 0), 12)


def spindle_clamp():
    """Ø65 split clamp, 100 x 95 x 70, two M6 pinch bolts."""
    c = box(-50, 50, -47.5, Z_PLATE_Y[0], 0, 70)
    c = c.cut(cyl(65.1, (0, 0, 0), (0, 0, 1), 70))
    c = c.cut(box(-1.5, 1.5, -47.5, -30, 0, 70))
    c = holes(c, 6.6, [(-50, -40, z) for z in (20, 50)], (1, 0, 0), 50)
    c = holes(c, 5.0, [(0, -40, z) for z in (20, 50)], (1, 0, 0), 50)
    c = holes(c, 4.2, [(sx * 40, 0, 0) for sx in (-1, 1)], (0, 0, 1), 12)              # M5 dust shoe
    return holes(c, 5.0, [(x, Z_PLATE_Y[0], z) for x, _, z in ZP_CLAMP_BOLTS], (0, -1, 0), 15)



# ---- accessories: home switches, chip covers, drag chains, dust shoe, feet
def x_sensor_block():
    """Holds the X home sensor on the inside of the right side plate."""
    b = box(255, 280, 113, 143, 270, 300)
    b = b.cut(cyl(12.2, (255, *X_SENSOR_YZ), (1, 0, 0), 25))
    return holes(b, 4.2, [(280, y, z) for y, z in X_SENSOR_BLOCK_BOLTS], (-1, 0, 0), 12)


Y_SENSOR = dict(x=233.0, z=92.0, face_y=230.0)


def y_sensor_block():
    """Holds the Y home sensor on the inner face of the right base profile."""
    b = box(226, 240, 255, 275, 50, 100)
    b = b.cut(cyl(12.2, (Y_SENSOR["x"], 255, Y_SENSOR["z"]), (0, 1, 0), 20))
    return holes(b, 6.6, [(226, 265, 60)], (1, 0, 0), 14)


def y_home_flag():
    """Steel flag under the table that the Y sensor sees (table coordinates)."""
    x0, x1 = Y_FLAG["x"]
    y0, y1 = Y_FLAG["y"]
    f = box(x0, x1, y0, y1, 82, TABLE_Z[0]).union(box(x0, x1, y0, 119, TABLE_Z[0] - 3, TABLE_Z[0]))
    return holes(f, 3.3, [(x, y, TABLE_Z[0]) for x, y, _ in TABLE_ACC_BOLTS[2:]], (0, 0, -1), 3)


Z_SENSOR = dict(x=50.0, y=80.0, face_z=606.5)


def z_sensor_bracket():
    """L bracket on the carriage front top; the Z sensor looks down at the
    top of the right Z riser."""
    b = box(40, 60, 114.5, X_CAR_Y[0], 495, 620).union(box(40, 60, 70, X_CAR_Y[0], 614, 620))
    b = b.cut(cyl(12.2, (Z_SENSOR["x"], Z_SENSOR["y"], 614), (0, 0, 1), 6))
    return holes(b, 4.2, [(50, 114.5, z) for z in (505, 520)], (0, 1, 0), 6)            # M5 from the carriage back


def x_chain_arm():
    """Carries the moving end of the X drag chain from the carriage top back
    over the beam."""
    a = box(-60, -40, 125, 135, 530, 546).union(box(-60, -40, 125, 245, 541, 546))
    return holes(a, 5.5, [(x, 128.0, 546) for x in (-55, -45)], (0, 0, -1), 16)


def y_chain_mount():
    m = box(Y_CHAIN_X - 10, Y_CHAIN_X + 10, -10, 10, 93, TABLE_Z[0])
    return holes(m, 3.3, [(x, y, TABLE_Z[0]) for x, y, _ in TABLE_ACC_BOLTS[:2]], (0, 0, -1), 12)


def y_chain_tray():
    """2 mm aluminium tray the Y chain's lower run lies on, across the cross members."""
    t = box(Y_CHAIN_X - 15, Y_CHAIN_X + 15, -305, 305, 40, 42)
    return holes(t, 5.5, [(Y_CHAIN_X, sy * 300, 40) for sy in (-1, 1)], (0, 0, 1), 2)


def dust_shoe():
    """Ring under the spindle clamp with a Ø40 hose port to the front; the
    brush skirt is a separate part (Z group, p0 = 0)."""
    r = cyl(100, (0, 0, -20), (0, 0, 1), 20).cut(cyl(60, (0, 0, -20), (0, 0, 1), 20))
    r = r.cut(cyl(92, (0, 0, -20), (0, 0, 1), 14).cut(cyl(66, (0, 0, -20), (0, 0, 1), 14)))     # plenum
    port = cyl(40, (0, -48, 0), (0, -1, 0), 42).union(cyl(40, (0, -44, -10), (0, -1, 0), 4).intersect(
        box(-20, 20, -48, -44, -20, 0)))
    r = r.union(port).cut(cyl(34, (0, -30, 0), (0, -1, 0), 61))
    return cbore(r, 5.5, 10, 6, [(sx * 40, 0, -20) for sx in (-1, 1)], (0, 0, 1), 20)


def dust_brush():
    return cyl(100, (0, 0, -48), (0, 0, 1), 28).cut(cyl(92, (0, 0, -48), (0, 0, 1), 28))


FOOT_XY = [(sx * 260, sy * 317) for sx in (-1, 1) for sy in (-1, 1)]


def foot_plate(sx, sy):
    """10 mm plate under each base-profile end: M8 into the bottom slot,
    M12 thread for the levelling foot."""
    y0, y1 = (280.0, 330.0) if sy > 0 else (-330.0, -280.0)
    p = box(sx * 260 - 20, sx * 260 + 20, y0, y1, -10, 0)
    p = cbore(p, 8.5, 14, 8, [(sx * 260, sy * 295, -10)], (0, 0, 1), 10)
    return holes(p, 10.2, [(sx * 260, sy * 317, -10)], (0, 0, 1), 10)


# ---- enclosure: Bosch 40x40L frame, 6 mm polycarbonate, hinged door, safety switch
ENC = dict(x=(-400.0, 480.0), y=(-420.0, 500.0), z=(-40.0, 720.0))


def enclosure_parts():
    """(name, shape, colour, kind) for the enclosure, all fixed."""
    (x0, x1), (y0, y1), (z0, z1) = ENC["x"], ENC["y"], ENC["z"]
    out = []
    prof = lambda L: P.profile(40, 40, L)                                         # noqa: E731
    pc = (0.75, 0.85, 0.95)
    # bottom and top rings
    for zc, nm in ((z0 + 20, "bottom"), (z1 - 20, "top")):
        out.append((f"enc_{nm}_front", place(prof(x1 - x0), t=(x0, y0 + 20, zc)), ALU, "bought"))
        out.append((f"enc_{nm}_back", place(prof(x1 - x0), t=(x0, y1 - 20, zc)), ALU, "bought"))
        out.append((f"enc_{nm}_left", place(prof(y1 - y0 - 80), ex=(0, 1, 0), t=(x0 + 20, y0 + 40, zc)), ALU, "bought"))
        out.append((f"enc_{nm}_right", place(prof(y1 - y0 - 80), ex=(0, 1, 0), t=(x1 - 20, y0 + 40, zc)), ALU, "bought"))
    for xc in (x0 + 20, x1 - 20):                                                  # corner posts
        for yc in (y0 + 20, y1 - 20):
            out.append((f"enc_post_{'L' if xc < 0 else 'R'}{'F' if yc < 0 else 'B'}",
                        place(prof(z1 - z0 - 80), ex=(0, 0, 1), ez=(1, 0, 0), t=(xc, yc, z0 + 40)), ALU, "bought"))
    # polycarbonate panels, edges 8 mm deep in the slots
    e = 8.0
    for nm, xa in (("left", x0 + 17), ("right", x1 - 23)):            # edges in the post and ring slots
        side = box(xa, xa + 6, y0 + 40 - e, y1 - 40 + e, z0 + 40, z1 - 40).union(
            box(xa, xa + 6, y0 + 40, y1 - 40, z0 + 40 - e, z1 - 40 + e))
        out.append((f"enc_panel_{nm}", side, pc, "made"))
    back = box(x0 + 40 - e, x1 - 40 + e, y1 - 23, y1 - 17, z0 + 40 - e, z1 - 40 + e)
    back = back.cut(cyl(100, (0, y1 - 23, 300), (0, 1, 0), 6)).cut(cyl(50, (300, y1 - 23, 150), (0, 1, 0), 6))
    out.append(("enc_panel_back", back, pc, "made"))
    out.append(("enc_panel_top", box(x0 + 40 - e, x1 - 40 + e, y0 + 40 - e, y1 - 40 + e, z1 - 23, z1 - 17), pc, "made"))
    out.append(("enc_dust_port_flange", cyl(130, (0, y1, 300), (0, 1, 0), 4).union(cyl(100, (0, y1 + 4, 300), (0, 1, 0), 40))
                .cut(cyl(94, (0, y1 - 1, 300), (0, 1, 0), 50)), BLACK, "bought"))
    out.append(("enc_base_board", box(x0, x1, y0, y1, z0 - 18, z0), MDF, "made"))
    # door: own 40x40 frame in the front opening, 2 mm gap all round
    gx0, gx1, gz0, gz1 = x0 + 42, x1 - 42, z0 + 42, z1 - 42
    yc = y0 + 20
    out.append(("door_left", place(prof(gz1 - gz0), ex=(0, 0, 1), ez=(1, 0, 0), t=(gx0 + 20, yc, gz0)), ALU, "bought"))
    out.append(("door_right", place(prof(gz1 - gz0), ex=(0, 0, 1), ez=(1, 0, 0), t=(gx1 - 20, yc, gz0)), ALU, "bought"))
    out.append(("door_bottom", place(prof(gx1 - gx0 - 80), t=(gx0 + 40, yc, gz0 + 20)), ALU, "bought"))
    out.append(("door_top", place(prof(gx1 - gx0 - 80), t=(gx0 + 40, yc, gz1 - 20)), ALU, "bought"))
    out.append(("door_panel", box(gx0 + 40 - e, gx1 - 40 + e, yc - 3, yc + 3, gz0 + 40 - e, gz1 - 40 + e), pc, "made"))
    for zh in (gz0 + 80, gz1 - 80):                                               # hinges on the left
        hinge = box(gx0 - 14, gx0 + 14, y0 - 3, y0, zh - 30, zh + 30).union(cyl(10, (gx0 - 1, y0 - 5, zh - 30), (0, 0, 1), 60))
        out.append((f"door_hinge_{int(zh)}", hinge, BLACK, "bought"))
    zm = (gz0 + gz1) / 2
    handle = (cyl(10, (gx1 - 20, y0, zm - 50), (0, -1, 0), 30).union(cyl(10, (gx1 - 20, y0, zm + 50), (0, -1, 0), 30))
              .union(cyl(14, (gx1 - 20, y0 - 30, zm - 60), (0, 0, 1), 120)))
    out.append(("door_handle", handle, BLACK, "bought"))
    body, act = P.safety_switch()
    out.append(("door_safety_switch", place(body, ez=(0, -1, 0), t=(x1 - 20, y0, zm + 150)), (0.9, 0.8, 0.1), "bought"))
    out.append(("door_safety_actuator", place(act, ez=(0, -1, 0), t=(x1 - 20, y0, zm + 150)), BLACK, "bought"))
    return out

# ============================================================ assembly
ALU, STEEL, BLACK, MDF = (0.75, 0.77, 0.8), (0.55, 0.57, 0.6), (0.15, 0.15, 0.17), (0.72, 0.6, 0.42)
BLUE, RAIL, BOLT, RED = (0.25, 0.42, 0.75), (0.4, 0.42, 0.45), (0.2, 0.2, 0.22), (0.7, 0.15, 0.12)


class Groups:
    """Parts by moving group: base (fixed), y (table), x (carriage), z (spindle plate).
    Each entry is (name, shape, colour, kind); kind is 'made', 'bought',
    'bolt' or 'tnut'. Bolts also keep their head alone for the clash check."""

    def __init__(self):
        self.g = {"base": [], "y": [], "x": [], "z": []}
        self.heads = {}
        self.count = {}
        self.dyn = []                       # (name, fn(x, y, z) -> world shape, colour, kind)

    def add(self, group, name, shape, colour, kind="bought"):
        self.g[group].append((name, shape, colour, kind))

    def bolt(self, group, d, length, p, direction, tag):
        """ISO 4762 M<d> x length: head underside at p, shank along direction."""
        k = self.count[tag] = self.count.get(tag, 0) + 1
        name = f"bolt_M{d}x{length}_{tag}_{k}"
        ez = tuple(direction)
        self.add(group, name, place(P.shcs(d, length), ex=any_perp(ez), ez=ez, t=p), BOLT, "bolt")
        self.heads[name] = place(P.shcs_head(d), ex=any_perp(ez), ez=ez, t=p)

    def tnut(self, group, d, p, slot_dir, normal, tag):
        k = self.count["tn" + tag] = self.count.get("tn" + tag, 0) + 1
        self.add(group, f"tnut_M{d}_{tag}_{k}", place(P.tnut(d), ex=slot_dir, ez=normal, t=p), STEEL, "tnut")


def build_groups():
    G = Groups()
    add = G.add

    # ---------------- base frame
    for s in (-1, 1):
        side = "L" if s < 0 else "R"
        add("base", f"base_profile_40x80_{side}", place(P.profile(40, 80, 640), ex=(0, 1, 0), t=(s * 260, -320, 40)),
            ALU)
        add("base", f"cross_profile_40x40_{'front' if s < 0 else 'back'}",
            place(P.profile(40, 40, 480), t=(-240, s * 300, 20)), ALU)
        add("base", f"y_rail_HGR15_{side}", place(P.rail(600), ex=(0, 1, 0), t=(s * 260, -300, 80)), RAIL)
        for y in P.rail_holes(600):                       # rail bolts into T-nuts in the profile top slot
            G.bolt("base", 4, 16, (s * 260, y - 300, 80 + 15 - 5.3), (0, 0, -1), "yrail")
            G.tnut("base", 4, (s * 260, y - 300, 80), (0, 1, 0), (0, 0, 1), "yrail")
        for sy in (-1, 1):                                # corner brackets
            ex = (0, -1, 0) if s < 0 else (0, 1, 0)
            add("base", f"corner_bracket_{side}{'F' if sy < 0 else 'B'}",
                place(P.corner_bracket(), ex=ex, ez=(0, 0, 1), t=(s * 240, sy * 300, 40)), ALU)
            G.bolt("base", 8, 16, (s * 220, sy * 300, 45), (0, 0, -1), "bracket")
            G.tnut("base", 8, (s * 220, sy * 300, 40), (1, 0, 0), (0, 0, 1), "bracket")
            G.bolt("base", 8, 16, (s * 235, sy * 300, 60), (s, 0, 0), "bracket")
            G.tnut("base", 8, (s * 240, sy * 300, 60), (0, 1, 0), (-s, 0, 0), "bracket")

    # ---------------- gantry
    t = UPRIGHT_T
    for s in (-1, 1):
        side = "L" if s < 0 else "R"
        add("base", f"upright_{side}", upright(s > 0), BLUE, "made")
        xo = (280 + t) * s
        for y, z in UPRIGHT_BASE_BOLTS:
            G.bolt("base", 6, 40, (xo, y, z), (-s, 0, 0), "upright")
            G.tnut("base", 6, (280 * s, y, z), (0, 1, 0), (s, 0, 0), "upright")
        for y, z in UPRIGHT_BEAM_BOLTS:
            G.bolt("base", 12, 45, (s * (280 + t - 13), y, z), (-s, 0, 0), "beam")
    add("base", "beam_profile_80x160", place(P.profile(80, 160, 560), t=(-280, BF + 40, 380)), ALU)
    add("base", "beam_box_front", beam_front_plate(), BLUE, "made")
    add("base", "beam_box_back", beam_back_plate(), BLUE, "made")
    add("base", "beam_box_top", beam_cap_plate(True), BLUE, "made")
    add("base", "beam_box_bottom", beam_cap_plate(False), BLUE, "made")
    for x in BOX_X:
        for z in BOX_ROWS_Z:
            G.bolt("base", 6, 12, (x, BF - BOX_T + 6.5, z), (0, 1, 0), "boxfront")
            G.tnut("base", 6, (x, BF, z), (1, 0, 0), (0, -1, 0), "boxfront")
            G.bolt("base", 6, 12, (x, BEAM_BACK + BOX_T - 6.5, z), (0, -1, 0), "boxback")
            G.tnut("base", 6, (x, BEAM_BACK, z), (1, 0, 0), (0, 1, 0), "boxback")
        for y in BOX_ROWS_Y:
            G.bolt("base", 6, 12, (x, y, 460 + BOX_T - 6.5), (0, 0, -1), "boxtop")
            G.tnut("base", 6, (x, y, 460), (1, 0, 0), (0, 0, 1), "boxtop")
            G.bolt("base", 6, 12, (x, y, 300 - BOX_T + 6.5), (0, 0, 1), "boxbottom")
            G.tnut("base", 6, (x, y, 300), (1, 0, 0), (0, 0, -1), "boxbottom")
    for x in BOX_EDGE_X:
        for y in (BF - BOX_T / 2, BEAM_BACK + BOX_T / 2):
            G.bolt("base", 5, 16, (x, y, 460 + BOX_T - 5.5), (0, 0, -1), "boxedge")
            G.bolt("base", 5, 16, (x, y, 300 - BOX_T + 5.5), (0, 0, 1), "boxedge")
    for zr in X_RAIL_Z:
        add("base", f"x_riser_{int(zr)}", x_riser(zr), ALU, "made")
        add("base", f"x_rail_HGR15_{int(zr)}", place(P.rail(560), ez=(0, -1, 0), t=(-280, RISER_Y, zr)), RAIL)
        for x in P.rail_holes(560):
            G.bolt("base", 4, 20, (x - 280, RISER_Y - 15 + 5.3, zr), (0, 1, 0), "xrail")
        for x in RISER_BOLTS_X:
            G.bolt("base", 6, 20, (x, RISER_Y + 6.5, zr), (0, 1, 0), "riser")

    # ---------------- Y drive
    yb, yf = Y_SUPPORT
    add("base", "y_screw_SFU1605", place(P.ball_screw((yf + 10, yb - 12.5), 25, 33, end_len=15.5), ex=(0, 1, 0),
                                         t=(0, 0, Y_SCREW_Z)), STEEL)
    add("base", "y_BK12", place(P.screw_support(True), ex=(0, 1, 0), t=(0, yb, 40)), BLACK)
    add("base", "y_BF12", place(P.screw_support(False), ex=(0, 1, 0), t=(0, yf, 40)), BLACK)
    for y in (yb, yf):
        for sx in (-1, 1):
            G.bolt("base", 5, 25, (sx * 23, y, 40 + 14.5), (0, 0, -1), "ysupport")
            G.tnut("base", 5, (sx * 23, y, 40), (1, 0, 0), (0, 0, 1), "ysupport")
    add("base", "y_locknut", place(P.locknut(), ex=(0, 1, 0), t=(0, yb + 12.5, Y_SCREW_Z)), STEEL)
    add("base", "y_coupler", place(P.coupler(), ex=(0, 1, 0), t=(0, 321, Y_SCREW_Z)), RED)
    add("base", "y_motor_plate", y_motor_plate(), BLUE, "made")
    for sx in (-1, 1):
        G.bolt("base", 6, 20, (sx * 30, 330, 20), (0, -1, 0), "ymotorplate")
        G.tnut("base", 6, (sx * 30, 320, 20), (1, 0, 0), (0, 1, 0), "ymotorplate")
        for sz in (-1, 1):
            p = (sx * MOTOR_HP, Y_STANDOFF_Y[0], Y_SCREW_Z + sz * MOTOR_HP)
            add("base", f"y_standoff_{sx:+d}{sz:+d}", place(P.standoff(Y_STANDOFF_Y[1] - Y_STANDOFF_Y[0]),
                ex=(0, 1, 0), t=p), STEEL)
            G.bolt("base", 5, 12, (p[0], 325, p[2]), (0, 1, 0), "ystandoff")
            G.bolt("base", 5, 12, (p[0], Y_STANDOFF_Y[1] + 5, p[2]), (0, -1, 0), "ymotor")
    add("base", "y_motor_NEMA23", place(P.nema23(), ez=(0, -1, 0), t=(0, Y_STANDOFF_Y[1], Y_SCREW_Z)), BLACK)

    # ---------------- X drive
    add("base", "x_screw_SFU1605", place(P.ball_screw((-260, 255), 19, 29, end_len=20), t=(0, *X_SCREW)), STEEL)
    for xc, kind in ((X_BK_X, True), (X_BF_X, False)):
        nm = "x_BK12" if kind else "x_BF12"
        add("base", nm, place(P.screw_support(kind), ez=(0, -1, 0), t=(xc, X_SUPPORT_Y, X_SCREW[1])), BLACK)
        for sz in (-1, 1):
            G.bolt("base", 5, 20, (xc, X_SUPPORT_Y - 14.5, X_SCREW[1] + sz * 23), (0, 1, 0), "xsupport")
    add("base", "x_locknut", place(P.locknut(), t=(X_BK_X + 12.5, *X_SCREW)), STEEL)
    add("base", "x_coupler", place(P.coupler(), t=(289, *X_SCREW)), RED)
    for sy in (-1, 1):
        for sz in (-1, 1):
            p = (X_STANDOFF_X[0], X_SCREW[0] + sy * MOTOR_HP, X_SCREW[1] + sz * MOTOR_HP)
            add("base", f"x_standoff_{sy:+d}{sz:+d}", place(P.standoff(X_STANDOFF_X[1] - X_STANDOFF_X[0]), t=p), STEEL)
            G.bolt("base", 5, 30, (285, p[1], p[2]), (1, 0, 0), "xstandoff")
            G.bolt("base", 5, 12, (330, p[1], p[2]), (-1, 0, 0), "xmotor")
    add("base", "x_motor_NEMA23", place(P.nema23(), ex=(0, 1, 0), ez=(-1, 0, 0), t=(325, *X_SCREW)), BLACK)

    # ---------------- Y group: table
    add("y", "table", table(), ALU, "made")
    add("y", "spoilboard_MDF", spoilboard(), MDF, "made")
    add("y", "y_nut_housing", y_nut_housing(), BLUE, "made")
    add("y", "y_nut_SFU1605", place(P.ball_nut(), ex=(0, -1, 0), t=(0, -25, Y_SCREW_Z)), STEEL)
    for q in NUT_PCD_ANGLES:
        G.bolt("y", 5, 16, (19 * np.cos(q), -35, Y_SCREW_Z + 19 * np.sin(q)), (0, 1, 0), "ynut")
    for sx in (-1, 1):
        for sy in (-1, 1):
            add("y", f"y_block_HGH15CA_{sx:+d}{sy:+d}", place(P.block(), ex=(0, 1, 0), t=(sx * 260, sy * 100, 80)),
                STEEL)
    for x, y, z in TABLE_BLOCK_BOLTS:
        G.bolt("y", 4, 12, (x, y, z - 7), (0, 0, -1), "yblock")
    for x, y, z in TABLE_NUT_BOLTS:
        G.bolt("y", 5, 16, (x, y, z - 7), (0, 0, -1), "ytable")

    # ---------------- X group: carriage
    add("x", "x_carriage", x_carriage(), BLUE, "made")
    add("x", "x_nut_housing", x_nut_housing(), BLUE, "made")
    add("x", "x_nut_SFU1605", place(P.ball_nut(), ez=(0, 1, 0), t=(25, *X_SCREW)), STEEL)
    for q in NUT_PCD_ANGLES:
        G.bolt("x", 5, 16, (35, X_SCREW[0] + 19 * np.sin(q), X_SCREW[1] - 19 * np.cos(q)), (-1, 0, 0), "xnut")
    for x, y, z in CAR_NUT_BOLTS:
        G.bolt("x", 5, 16, (x, y + 7, z), (0, 1, 0), "xcarnut")
    for sx in (-1, 1):
        for zr in X_RAIL_Z:
            add("x", f"x_block_HGH15CA_{sx:+d}_{int(zr)}", place(P.block(), ez=(0, -1, 0),
                t=(sx * 59.3, RISER_Y, zr)), STEEL)
        for zb in Z_BLOCK_Z:
            add("x", f"z_block_HGW15CC_{sx:+d}_{int(zb)}", place(P.block_flange(), ex=(0, 0, 1), ez=(0, 1, 0),
                t=(sx * 50, Z_RAIL_BASE, zb)), STEEL)
    for x, y, z in CAR_XBLOCK_BOLTS:
        G.bolt("x", 4, 12, (x, y + 7, z), (0, 1, 0), "xblock")
    for x, y, z in CAR_ZBLOCK_BOLTS:
        G.bolt("x", 4, 20, (x, y - P.V["hgw_t1"], z), (0, 1, 0), "zblock")
    add("x", "z_screw_SFU1605", place(P.ball_screw((292, 460), 20, 33, end_len=16), ex=(0, 0, 1), ez=(1, 0, 0),
                                      t=(0, Z_SCREW_Y, 0)), STEEL)
    add("x", "z_BK12", place(P.screw_support(True), ex=(0, 0, 1), ez=(0, -1, 0), t=(0, X_CAR_Y[0], 472.5)), BLACK)
    add("x", "z_BF12", place(P.screw_support(False), ex=(0, 0, 1), ez=(0, -1, 0), t=(0, X_CAR_Y[0], 282)), BLACK)
    for zc in (472.5, 282.0):
        for sx in (-1, 1):
            G.bolt("x", 5, 25, (sx * 23, X_CAR_Y[0] - 14.5, zc), (0, 1, 0), "zsupport")
    add("x", "z_locknut", place(P.locknut(), ex=(0, 0, 1), ez=(1, 0, 0), t=(0, Z_SCREW_Y, 485)), STEEL)
    add("x", "z_coupler", place(P.coupler(), ex=(0, 0, 1), ez=(1, 0, 0), t=(0, Z_SCREW_Y, 494)), RED)
    add("x", "z_motor_bracket", z_motor_bracket(), BLUE, "made")
    for sx in (-1, 1):
        G.bolt("x", 5, 16, (sx * 20, 115.5, 505), (0, 1, 0), "zbracket")
        for sy in (-1, 1):
            G.bolt("x", 5, 12, (sx * MOTOR_HP, Z_SCREW_Y + sy * MOTOR_HP, 535), (0, 0, -1), "zmotor")
    add("x", "z_motor_NEMA23", place(P.nema23(), ex=(-1, 0, 0), ez=(0, 0, -1), t=(0, Z_SCREW_Y, 530)), BLACK)

    # ---------------- Z group: spindle plate (p0 = 0)
    add("z", "z_plate", z_plate(), BLUE, "made")
    for sx in (-1, 1):
        add("z", f"z_riser_{sx:+d}", z_riser(sx * 50), ALU, "made")
        add("z", f"z_rail_HGR15_{sx:+d}", place(P.rail(290), ex=(0, 0, 1), ez=(0, 1, 0),
            t=(sx * 50, Z_RAIL_BASE, 5)), RAIL)
        for z in P.rail_holes(290):
            G.bolt("z", 4, 20, (sx * 50, Z_RAIL_BASE + 15 - 5.3, 5 + z), (0, -1, 0), "zrail")
    for x, y, z in ZP_RISER_BOLTS:
        G.bolt("z", 5, 16, (x, y + 7, z), (0, 1, 0), "zriser")
    for x, y, z in ZP_NUT_BOLTS:
        G.bolt("z", 5, 16, (x, y + 7, z), (0, 1, 0), "zplatenut")
    for x, y, z in ZP_CLAMP_BOLTS:
        G.bolt("z", 6, 20, (x, y - 6.5, z), (0, -1, 0), "clamp")
    add("z", "z_nut_housing", z_nut_housing(), BLUE, "made")
    add("z", "z_nut_SFU1605", place(P.ball_nut(), ex=(0, 0, 1), ez=(0, 1, 0), t=(0, Z_SCREW_Y, 140)), STEEL)
    for q in NUT_PCD_ANGLES:
        G.bolt("z", 5, 16, (19 * np.cos(q), Z_SCREW_Y + 19 * np.sin(q), 150), (0, 0, -1), "znut")
    add("z", "spindle_clamp", spindle_clamp(), BLUE, "made")
    for z in (20, 50):
        G.bolt("z", 6, 60, (-50, -40, z), (1, 0, 0), "pinch")
    sp, tool = P.spindle(tool_out=25)
    add("z", "spindle_65mm_1.5kW", move(sp, (0, 0, -SPINDLE_DROP)), (0.9, 0.9, 0.92))
    add("z", "tool_3.175", move(tool, (0, 0, -SPINDLE_DROP)), (0.85, 0.7, 0.2))

    # ---------------- chip covers: bellows on the Y and X ball screws (length follows the axis)
    bf_y, bk_y = Y_SUPPORT[1] + 10, Y_SUPPORT[0] - 12.5
    G.dyn.append(("y_bellows_front", lambda x, y, z: place(P.bellows(-y - 40 - bf_y), ex=(0, 1, 0),
                                                           t=(0, bf_y, Y_SCREW_Z)), BLACK, "bought"))
    G.dyn.append(("y_bellows_back", lambda x, y, z: place(P.bellows(bk_y - (-y + 25)), ex=(0, 1, 0),
                                                          t=(0, -y + 25, Y_SCREW_Z)), BLACK, "bought"))
    G.dyn.append(("x_bellows_left", lambda x, y, z: place(P.bellows(x - 25 - (X_BF_X + 10)),
                                                          t=(X_BF_X + 10, *X_SCREW)), BLACK, "bought"))
    G.dyn.append(("x_bellows_right", lambda x, y, z: place(P.bellows(X_BK_X - 12.5 - (x + 40)),
                                                           t=(x + 40, *X_SCREW)), BLACK, "bought"))

    # ---------------- home switches (M12 inductive, PNP NO)
    add("base", "x_sensor_block", x_sensor_block(), BLUE, "made")
    add("base", "x_home_sensor", place(P.inductive_sensor(), ez=(1, 0, 0), t=(243, *X_SENSOR_YZ)), (0.85, 0.6, 0.1))
    add("base", "x_sensor_nut", place(P.hex_nut(17, 4, 12), ez=(1, 0, 0), t=(251, *X_SENSOR_YZ)), STEEL)
    for y, zb in X_SENSOR_BLOCK_BOLTS:
        G.bolt("base", 5, 40, (280 + UPRIGHT_T, y, zb), (-1, 0, 0), "xsensor")
    add("base", "y_sensor_block", y_sensor_block(), BLUE, "made")
    add("base", "y_home_sensor", place(P.inductive_sensor(), ez=(0, 1, 0), t=(Y_SENSOR["x"], Y_SENSOR["face_y"],
                                                                              Y_SENSOR["z"])), (0.85, 0.6, 0.1))
    for yn in (251.0, 275.0):
        add("base", f"y_sensor_nut_{int(yn)}", place(P.hex_nut(17, 4, 12), ez=(0, 1, 0),
                                                     t=(Y_SENSOR["x"], yn, Y_SENSOR["z"])), STEEL)
    G.bolt("base", 6, 25, (226, 265, 60), (1, 0, 0), "ysensor")
    G.tnut("base", 6, (240, 265, 60), (0, 1, 0), (-1, 0, 0), "ysensor")
    add("y", "y_home_flag", y_home_flag(), STEEL, "made")
    for bx, by, bz in TABLE_ACC_BOLTS[2:]:
        G.bolt("y", 4, 12, (bx, by, bz - 7), (0, 0, -1), "yflag")
    add("x", "z_sensor_bracket", z_sensor_bracket(), BLUE, "made")
    add("x", "z_home_sensor", place(P.inductive_sensor(), t=(Z_SENSOR["x"], Z_SENSOR["y"], Z_SENSOR["face_z"])),
        (0.85, 0.6, 0.1))
    for zn in (610.0, 620.0):
        add("x", f"z_sensor_nut_{int(zn)}", place(P.hex_nut(17, 4, 12), t=(Z_SENSOR["x"], Z_SENSOR["y"], zn)), STEEL)
    for zb in (505, 520):
        G.bolt("x", 5, 20, (50, X_CAR_Y[1], zb), (0, -1, 0), "zsensor")

    # ---------------- drag chains
    add("x", "x_chain_arm", x_chain_arm(), BLUE, "made")
    for xb in (-55, -45):
        G.bolt("x", 5, 20, (xb, 128.0, 546), (0, 0, -1), "xchain")
    XF, XK, XR, XH, XW, XY = -200.0, 320.0, 38.0, 20.0, 25.0, 232.5

    def x_chain(x, y, z):
        xm = x - 50
        xl = (XF + xm + XK) / 2
        return place(P.drag_chain(XF, xm, xl, XR, XH, XW), t=(0, XY, 470 + BOX_T * 0))
    G.dyn.append(("x_drag_chain", x_chain, BLACK, "bought"))
    add("base", "y_chain_tray", y_chain_tray(), ALU, "made")
    for sy in (-1, 1):
        G.bolt("base", 5, 12, (Y_CHAIN_X, sy * 300, 42), (0, 0, -1), "ytray")
        G.tnut("base", 5, (Y_CHAIN_X, sy * 300, 40), (1, 0, 0), (0, 0, 1), "ytray")
    add("y", "y_chain_mount", y_chain_mount(), BLUE, "made")
    for bx, by, bz in TABLE_ACC_BOLTS[:2]:
        G.bolt("y", 4, 12, (bx, by, bz - 7), (0, 0, -1), "ychain")
    YF, YK, YR, YH, YW = -125.0, 270.0, 18.0, 15.0, 15.0

    def y_chain(x, y, z):
        ym = -y
        yl = (YF + ym + YK) / 2
        return place(P.drag_chain(YF, ym, yl, YR, YH, YW), ex=(0, 1, 0), t=(Y_CHAIN_X, 0, 42))
    G.dyn.append(("y_drag_chain", y_chain, BLACK, "bought"))

    # ---------------- dust shoe, tool setter, feet
    add("z", "dust_shoe", dust_shoe(), (0.2, 0.25, 0.3), "made")
    add("z", "dust_brush", dust_brush(), (0.3, 0.3, 0.3), "bought")
    for sx in (-1, 1):
        G.bolt("z", 5, 16, (sx * 40, 0, -14), (0, 0, 1), "dustshoe")
    add("y", "tool_setter", move(P.tool_setter(), (-170, 0, TABLE_Z[1] + 12)), (0.8, 0.1, 0.1))
    for sx in (-1, 1):
        for sy in (-1, 1):
            add("base", f"foot_plate_{'L' if sx < 0 else 'R'}{'F' if sy < 0 else 'B'}", foot_plate(sx, sy), BLUE, "made")
            add("base", f"levelling_foot_{'L' if sx < 0 else 'R'}{'F' if sy < 0 else 'B'}",
                move(P.levelling_foot(), (sx * 260, sy * 317, -40)), BLACK)
            G.bolt("base", 8, 16, (sx * 260, sy * 295, -2), (0, 0, 1), "foot")
            G.tnut("base", 8, (sx * 260, sy * 295, 0), (0, 1, 0), (0, 0, -1), "foot")

    # ---------------- enclosure
    for n, shp, c, kind in enclosure_parts():
        add("base", n, shp, c, kind)
    return G


OFFSETS = {"base": lambda x, y, z: (0, 0, 0), "y": lambda x, y, z: (0, -y, 0),
           "x": lambda x, y, z: (x, 0, 0), "z": lambda x, y, z: (x, 0, Z_TOP + z)}


def pose(G, x=0.0, y=0.0, z=0.0, heads=False):
    """List of (name, shape, colour, kind) at machine position x, y, z.
    heads=True swaps each bolt for its head alone (for clash checking)."""
    out = []
    for k, items in G.g.items():
        off = OFFSETS[k](x, y, z)
        for n, s, c, kind in items:
            s = G.heads[n] if heads and kind == "bolt" else s
            out.append((n, move(s, off), c, kind))
    for n, fn, c, kind in G.dyn:
        out.append((n, fn(x, y, z), c, kind))
    return out


def to_assembly(items, name="cnc_router"):
    a = cq.Assembly(name=name)
    for n, s, c, _ in items:
        a.add(s, name=n, color=cq.Color(*c))
    return a


def tool_tip_z(z):
    return Z_TOP + z - SPINDLE_DROP - P.spindle_tip_below_body(25)


if __name__ == "__main__":
    x, y, z = (float(v) for v in sys.argv[1:4]) if len(sys.argv) >= 4 else (0.0, 0.0, 0.0)
    G = build_groups()
    items = pose(G, x, y, z)
    os.makedirs(os.path.join(HERE, "step", "parts"), exist_ok=True)
    out = os.path.join(HERE, "step", "router_assembly.step" if (x, y, z) == (0, 0, 0)
                       else f"router_x{x:g}_y{y:g}_z{z:g}.step")
    to_assembly(items).export(out)
    print("wrote", out, len(items), "parts")
    if (x, y, z) == (0, 0, 0):
        seen = set()
        for n, s, _, kind in items:
            key = n.split("_")[0] + n.split("_")[1] if kind in ("bolt", "tnut") else n
            if kind == "bought":
                key = n.rstrip("+-0123456789_LRFB")
            if key in seen:
                continue
            seen.add(key)
            bb = s.BoundingBox()
            fn = (key if kind in ("bolt", "tnut") else n).replace("+", "p").replace("-", "m")
            cq.exporters.export(cq.Workplane().add(move(s, (-bb.xmin, -bb.ymin, -bb.zmin))),
                                os.path.join(HERE, "step", "parts", fn + ".step"))
        print("per-part STEP in step/parts/")
