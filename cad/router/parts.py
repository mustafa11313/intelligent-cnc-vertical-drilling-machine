"""Bought parts for the CNC router (CadQuery), modelled from catalogue
drawings. All dimensions in mm.

Each part is built in its own canonical frame (documented per function) and
placed by assembly.py. Every catalogue value is in VENDOR, with its source.
Values that differ between sellers are marked "check" and must be confirmed
against the listing actually bought. Any manufacturer STEP that becomes
available can replace a function here in the same canonical frame.
"""
import math

import cadquery as cq

THREADS = True        # real helical ball screw thread (slow); False -> plain Ø15.8 envelope

# --------------------------------------------------------------- catalogue
VENDOR = {
    # Bosch Rexroth strut profiles, slot 10, R40 grid: 40x40L 3842993120 (A 5.6 cm², I 9.1/9.1 cm⁴),
    # 40x80L 3842993130 (A 9.9, Ix 63.4, Iy 17.3), 80x160L 3842993673 (A 32.9, Ix 850.7, Iy 253.4).
    # Slot 10 opening and core M12 from the datasheets; lip, wall and web thickness fitted so the
    # modelled section matches Bosch's published area and Ix within 5 %.
    "sl_open": 10.2, "sl_lip": 3.2, "sl_groove_w": 20.6, "sl_groove_d1": 6.5, "sl_depth": 12.2,
    "sl_bottom_w": 9.2, "core_d": 10.2, "pr_wall": 1.3, "pr_core_od": 14.0, "pr_web": 1.5, "pr_iweb": 2.0,
    # HIWIN HGR15R rail (HIWIN linear guideway catalogue, HG series)
    "rail_w": 15.0, "rail_h": 15.0, "rail_pitch": 60.0, "rail_e": 20.0, "rail_cb_d": 7.5, "rail_cb_h": 5.3,
    "rail_hole": 4.5,
    # HIWIN HGH15CA: H 28, H1 4.3, W 34, B 26, C 26, L1 39.4, L 61.4, M4x5, G (nipple) 5.3
    "hgh_h": 28.0, "hgh_w": 34.0, "hgh_b": 26.0, "hgh_c": 26.0,
    "blk_h1": 4.3, "blk_l1": 39.4, "blk_l": 61.4, "nipple": 5.3,
    # HIWIN HGW15CC: H 24, W 47, B 38, C 30, L1 39.4, L 61.4, M5 through, T1 8.9
    "hgw_h": 24.0, "hgw_w": 47.0, "hgw_b": 38.0, "hgw_c": 30.0, "hgw_t1": 8.9,
    # SFU1605 (rolled C7, internal recirculation): d 16, lead 5, ball 3.175. Nut D 28, L 42,
    # flange 48 x 10 with flats 40, 6 x Ø5.5 on PCD 38.  check: seller drawing
    "screw_d": 16.0, "lead": 5.0, "ball": 3.175,
    "nut_d": 28.0, "nut_l": 42.0, "nut_fl_d": 48.0, "nut_fl_t": 10.0, "nut_flat": 40.0,
    "nut_pcd": 38.0, "nut_hole": 5.5,
    # BK12 / BF12 supports: B 60, H 43, h 25, L 25 / 20, P 46, X Ø5.5.  check: seller drawing
    "bk_w": 60.0, "bk_h": 43.0, "bk_axis_h": 25.0, "bk_l": 25.0, "bf_l": 20.0,
    "bk_bolt_b": 46.0, "bk_bolt": 5.5, "bk_bore": 12.0, "locknut_d": 22.0, "locknut_l": 8.0,
    # NEMA23, 76 mm body (e.g. StepperOnline 23HS30-3004S class): 56.4 square, holes 47.14,
    # boss 38.1 x 1.6, shaft Ø8 x 21 with D flat
    "m23_sq": 56.4, "m23_len": 76.0, "m23_holes": 47.14, "m23_boss": 38.1, "m23_shaft": 8.0,
    "m23_shaft_l": 21.0, "m23_flange_t": 5.0,
    # Spindle: Zhong Hua Jiang "65 1.5KW ER11 water cooled" (catalogue 2025 p.17): body Ø65 x 200
    # (9 + 171 + 20), front Ø51.2 x 19.5, nose Ø33.5, Ø17.8, ER11 nut Ø19 x 13, 54 in front of
    # the body, 13 behind it, 267 overall, 3 kg
    "sp_d": 65.0, "sp_body_l": 200.0, "sp_front": 54.0, "sp_rear": 13.0, "sp_nut_d": 19.0, "sp_nut_l": 13.0,
}
V = VENDOR


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl(d, p, axis, length):
    return cq.Workplane("XY").add(cq.Solid.makeCylinder(d / 2, length, cq.Vector(*p), cq.Vector(*axis)))


def cut_holes(wp, d, pts, axis, length):
    if not pts:
        return wp
    cs = [cq.Solid.makeCylinder(d / 2, length, cq.Vector(*p), cq.Vector(*axis)) for p in pts]
    return wp.cut(cq.Workplane().add(cq.Compound.makeCompound(cs)))


def prism_x(pts, length, x0=0.0):
    """Extrude a closed polygon given in (y, z) along +X from x0."""
    return cq.Workplane("YZ", origin=(x0, 0, 0)).polyline(pts).close().extrude(length)


def hexagon(af, length, p=(0, 0, 0), axis="Z"):
    """Hexagonal prism, across-flats af, along +axis from p."""
    wp = {"X": cq.Workplane("YZ"), "Y": cq.Workplane("XZ"), "Z": cq.Workplane("XY")}[axis]
    s = wp.polygon(6, af / math.cos(math.pi / 6)).extrude(length if axis != "Y" else -length)
    return s.translate(p)


# ============================================================ profiles
def _slot_polygon():
    """Slot-10 groove polygon in (u, v): u across the slot, v depth into the
    profile from the face (v = 0 at the face)."""
    o, lip, gw, d1, d, bw = (V["sl_open"] / 2, V["sl_lip"], V["sl_groove_w"] / 2, V["sl_groove_d1"],
                             V["sl_depth"], V["sl_bottom_w"] / 2)
    return [(-o, -0.1), (-o, lip), (-gw, lip), (-gw, d1), (-bw, d), (bw, d), (gw, d1), (gw, lip), (o, lip), (o, -0.1)]


def profile_section(w, h):
    """Bosch-style hollow section (shapely polygon in (y, z)): outer skin and
    slot walls of thickness pr_wall, a core tube (M12 tap, Ø10.2) in every
    40 mm cell, diagonal webs from each core to its cell corners, and webs
    on the inner cell boundaries."""
    import itertools
    from shapely.geometry import LineString, Point, Polygon, box as sbox
    from shapely.ops import unary_union
    t = V["pr_wall"]
    outer = sbox(-w / 2, -h / 2, w / 2, h / 2)
    ny, nz = int(round(w / 40)), int(round(h / 40))
    grooves = []
    for k in range(ny):
        yc = -w / 2 + 20 + 40 * k
        grooves.append(Polygon([(yc + u, h / 2 - v) for u, v in _slot_polygon()]))
        grooves.append(Polygon([(yc + u, -h / 2 + v) for u, v in _slot_polygon()]))
    for k in range(nz):
        zc = -h / 2 + 20 + 40 * k
        grooves.append(Polygon([(w / 2 - v, zc + u) for u, v in _slot_polygon()]))
        grooves.append(Polygon([(-w / 2 + v, zc + u) for u, v in _slot_polygon()]))
    G = unary_union(grooves)
    centres = [(-w / 2 + 20 + 40 * i, -h / 2 + 20 + 40 * j) for i in range(ny) for j in range(nz)]
    keep = []
    for c in centres:
        keep.append(Point(c).buffer(V["pr_core_od"] / 2))
        for sx, sy in itertools.product((-1, 1), (-1, 1)):
            keep.append(LineString([c, (c[0] + sx * 20, c[1] + sy * 20)]).buffer(V["pr_web"] / 2))
    for i in range(1, ny):
        keep.append(LineString([(-w / 2 + 40 * i, -h / 2), (-w / 2 + 40 * i, h / 2)]).buffer(V["pr_iweb"] / 2))
    for j in range(1, nz):
        keep.append(LineString([(-w / 2, -h / 2 + 40 * j), (w / 2, -h / 2 + 40 * j)]).buffer(V["pr_iweb"] / 2))
    interior = outer.buffer(-t, join_style=2).difference(G.buffer(t, join_style=2)).difference(unary_union(keep))
    sec = outer.difference(G).difference(interior)
    for c in centres:
        sec = sec.difference(Point(c).buffer(V["core_d"] / 2, quad_segs=12))
    return sec.simplify(0.02)


def profile(w, h, length):
    """Aluminium strut profile (Bosch Rexroth slot 10, R40), canonical: along
    +X from 0, section w (Y) x h (Z) centred on the axis."""
    sec = profile_section(w, h)
    polys = getattr(sec, "geoms", [sec])
    solids = []
    for poly in polys:
        def wire(ring):
            pts = list(ring.coords)[:-1]
            return cq.Wire.makePolygon([cq.Vector(0, y, z) for y, z in pts], close=True)
        face = cq.Face.makeFromWires(wire(poly.exterior), [wire(r) for r in poly.interiors])
        solids.append(cq.Solid.extrudeLinear(face, cq.Vector(length, 0, 0)))
    return cq.Workplane().add(solids[0] if len(solids) == 1 else cq.Compound.makeCompound(solids))


def tnut(thread, length=16.0):
    """Slot-10 T-nut (drop-in type) for the groove, canonical: slot axis
    along X, centred at x=0; v = depth from the profile face is -z (face at
    z=0, nut below it, top of the nut against the lips at z=-4.3)."""
    gw, d1, d, bw, lip = (V["sl_groove_w"] / 2 - 0.4, V["sl_groove_d1"], V["sl_depth"] - 0.4,
                          V["sl_bottom_w"] / 2 - 0.3, V["sl_lip"])
    poly = [(-gw, -lip), (gw, -lip), (gw, -d1), (bw, -d), (-bw, -d), (-gw, -d1)]
    n = cq.Workplane("YZ", origin=(-length / 2, 0, 0)).polyline(poly).close().extrude(length)
    tap = {4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8}[thread]
    return n.cut(cyl(tap, (0, 0, -d - 1), (0, 0, 1), d + 1))


def corner_bracket():
    """40 x 40 x 35 cast angle bracket with rib, slot 10. Canonical: inside
    corner on the X axis line, legs on z=0 (along +Y) and y=0 (along +Z),
    width along X centred at 0. One Ø8.5 hole per leg, 20 from the corner (slot centre)."""
    t, a, w = 5.0, 40.0, 35.0
    b = box(-w / 2, w / 2, 0, a, 0, t).union(box(-w / 2, w / 2, 0, t, 0, a))
    for xr in (-w / 2, w / 2 - 3):                                   # two side ribs
        rib = cq.Workplane("YZ").polyline([(t, t), (a - 3, t), (t, a - 3)]).close().extrude(3).translate((xr, 0, 0))
        b = b.union(rib)
    b = cut_holes(b, 8.5, [(0, 20, 0)], (0, 0, 1), t)
    return cut_holes(b, 8.5, [(0, 0, 20)], (0, 1, 0), t)


# ============================================================ linear guides
def _rail_section():
    """HGR15 cross-section (y, z) with the four ball grooves (gothic arch,
    simplified to arcs)."""
    return [(-7.5, 0), (7.5, 0), (7.5, 5.6), (6.6, 6.8), (6.6, 8.2), (7.5, 9.4), (7.5, 12.6),
            (6.0, 13.4), (5.2, 15.0), (-5.2, 15.0), (-6.0, 13.4), (-7.5, 12.6), (-7.5, 9.4),
            (-6.6, 8.2), (-6.6, 6.8), (-7.5, 5.6)]


def rail(length):
    """HGR15R rail, canonical: along +X from 0, base on z=0, centred on y=0.
    Counterbored Ø4.5 / Ø7.5 x 5.3 holes for M4 at 60 mm pitch, equal ends."""
    r = prism_x(_rail_section(), length)
    n = int((length - 2 * V["rail_e"]) // V["rail_pitch"]) + 1
    e = (length - (n - 1) * V["rail_pitch"]) / 2
    xs = [e + i * V["rail_pitch"] for i in range(n)]
    r = cut_holes(r, V["rail_hole"], [(x, 0, 0) for x in xs], (0, 0, 1), V["rail_h"])
    return cut_holes(r, V["rail_cb_d"], [(x, 0, V["rail_h"] - V["rail_cb_h"]) for x in xs], (0, 0, 1), 6)


def rail_holes(length):
    n = int((length - 2 * V["rail_e"]) // V["rail_pitch"]) + 1
    e = (length - (n - 1) * V["rail_pitch"]) / 2
    return [e + i * V["rail_pitch"] for i in range(n)]


def _block(h, w_top, flange_t, bolt_b, bolt_c, bolt_d, bolt_through, body_w=34.0):
    h1, l1, l = V["blk_h1"], V["blk_l1"], V["blk_l"]
    b = box(-l1 / 2, l1 / 2, -body_w / 2, body_w / 2, h1, h)
    if w_top > body_w:
        b = b.union(box(-l1 / 2, l1 / 2, -w_top / 2, w_top / 2, h - flange_t, h))
    # rail channel with running clearance, steel retainer strips
    b = b.cut(prism_x([(-8.6, h1 - 1), (8.6, h1 - 1), (8.6, 15.6), (-8.6, 15.6)], l1, -l1 / 2))
    cap_l, seal_l = (l - l1) / 2 - 2.0, 2.0
    for s in (-1, 1):                                  # recirculation end caps + double-lip end seals
        x0 = l1 / 2 if s > 0 else -l1 / 2 - cap_l
        cap = box(x0, x0 + cap_l, -body_w / 2 + 0.5, body_w / 2 - 0.5, h1 + 0.3, h - 0.8)
        xs = l1 / 2 + cap_l if s > 0 else -l / 2
        seal = box(xs, xs + seal_l, -body_w / 2 + 0.2, body_w / 2 - 0.2, h1, h - 0.5)
        part = cap.union(seal).cut(prism_x([(-7.8, 0), (7.8, 0), (7.8, 15.3), (-7.8, 15.3)], l, -l / 2))
        b = b.union(part)
    # grease nipple M4 on the +X end (G = 5.3)
    zc = max(h - 7.0, V["rail_h"] + 4.5)
    b = b.union(hexagon(7.0, 3.5, (l / 2, 0, zc), "X")).union(cyl(4.5, (l / 2 + 3.5, 0, zc), (1, 0, 0), 1.8))
    pts = [(sx * bolt_c / 2, sy * bolt_b / 2, h) for sx in (-1, 1) for sy in (-1, 1)]
    depth = h - h1 if bolt_through else 5.0
    return cut_holes(b, bolt_d, [(x, y, h - depth) for x, y, _ in pts], (0, 0, 1), depth)


def block():
    """HGH15CA carriage, canonical: rail along X, centred at x=0, rail base
    at z=0 (block z 4.3..28), centred on y=0. 4 x M4 x 5 on top (26 x 26),
    grease nipple on the +X end."""
    return _block(V["hgh_h"], V["hgh_w"], 0, V["hgh_b"], V["hgh_c"], 3.3, False)


def block_flange():
    """HGW15CC flange carriage, canonical as block(); top at z=24. 4 x M5
    through the flange (38 x 30), so it bolts from either side (M4 from below)."""
    return _block(V["hgw_h"], V["hgw_w"], V["hgw_t1"], V["hgw_b"], V["hgw_c"], 4.2, True, body_w=30.0)


# ============================================================ ball screw drive
def ball_screw(threaded, journal_a, journal_b, end_len=0.0, journal_d=12.0, end_d=10.0, threads=None):
    """SFU1605 screw with machined ends, canonical: along +X.
    threaded = (x0, x1); journal_a = Ø12 floating-end journal before x0
    (with circlip groove), journal_b = Ø12 fixed-end journal after x1 (BK12
    bearing seat and M12x1 lock nut thread), then end_len of Ø10 for the
    coupler, with a 0.5 mm D flat."""
    x0, x1 = threaded
    threads = THREADS if threads is None else threads
    s = cyl(V["screw_d"] - 0.2, (x0, 0, 0), (1, 0, 0), x1 - x0)
    if threads:
        r = (V["screw_d"] - 0.2) / 2 + 0.3
        helix = cq.Wire.makeHelix(pitch=V["lead"], height=x1 - x0 - 4, radius=r)
        groove = (cq.Workplane("XZ").center(r, 0).circle(V["ball"] / 2 + 0.05)
                  .sweep(cq.Workplane().add(helix), isFrenet=True))
        groove = groove.val().rotate(cq.Vector(), cq.Vector(0, 1, 0), 90).translate(cq.Vector(x0 + 2, 0, 0))
        s = s.cut(cq.Workplane().add(groove))
    s = s.union(cyl(journal_d - 0.1, (x0 - journal_a, 0, 0), (1, 0, 0), journal_a))
    s = s.cut(box(x0 - journal_a + 4, x0 - journal_a + 5.15, -7, 7, -7, 7)
              .cut(cyl(11.5, (x0 - journal_a + 4, 0, 0), (1, 0, 0), 1.15)))      # circlip groove
    s = s.union(cyl(journal_d - 0.1, (x1, 0, 0), (1, 0, 0), journal_b))
    if end_len:
        e = cyl(end_d - 0.1, (x1 + journal_b, 0, 0), (1, 0, 0), end_len)
        e = e.cut(box(x1 + journal_b + 2, x1 + journal_b + end_len, -6, 6, (end_d - 0.1) / 2 - 0.5, 6))
        s = s.union(e)
    return s


def ball_nut():
    """SFU1605 nut, canonical: axis +X, flange face (mounting face) at x=0,
    flange 0..10 toward +X, body from x=0 back to x=-32. Flats (40 mm)
    perpendicular to z. Wiper seals at both ends, M6 grease port on the flange."""
    body_l = V["nut_l"] - V["nut_fl_t"]
    n = cyl(V["nut_d"], (-body_l, 0, 0), (1, 0, 0), body_l)
    fl = cyl(V["nut_fl_d"], (0, 0, 0), (1, 0, 0), V["nut_fl_t"])
    fl = fl.intersect(box(0, V["nut_fl_t"], -30, 30, -V["nut_flat"] / 2, V["nut_flat"] / 2))
    n = n.union(fl)
    n = n.cut(cyl(V["nut_d"] + 1, (-body_l, 0, 0), (1, 0, 0), 2.5)).union(cyl(V["nut_d"] - 3, (-body_l, 0, 0),
                                                                              (1, 0, 0), 2.5))
    pts = [(0, V["nut_pcd"] / 2 * math.cos(math.radians(a)), V["nut_pcd"] / 2 * math.sin(math.radians(a)))
           for a in (0, 60, 120, 180, 240, 300)]
    n = cut_holes(n, V["nut_hole"], pts, (1, 0, 0), V["nut_fl_t"])
    n = n.cut(cyl(V["screw_d"] + 0.2, (-body_l - 1, 0, 0), (1, 0, 0), V["nut_l"] + 2))
    return n.cut(cyl(5.0, (5, 0, V["nut_flat"] / 2 - 6), (0, 0, 1), 6))           # grease port


def screw_support(fixed=True):
    """BK12 (fixed=True) or BF12, canonical: axis along +X at z=25, base on
    z=0, length along X centred at x=0, width along Y. Stepped body, two
    counterbored Ø5.5 holes at P 46, bearing cover with seal."""
    l = V["bk_l"] if fixed else V["bf_l"]
    w, h, a = V["bk_w"], V["bk_h"], V["bk_axis_h"]
    s = box(-l / 2, l / 2, -w / 2, w / 2, 0, h)
    s = s.cut(box(-l / 2, l / 2, -w / 2, -w / 2 + 12, 20, h))
    s = s.cut(box(-l / 2, l / 2, w / 2 - 12, w / 2, 20, h))
    s = s.edges("|X").fillet(1.0)
    s = s.cut(cyl(V["bk_bore"] + 0.2, (-l / 2, 0, a), (1, 0, 0), l))
    pts = [(0, sy * V["bk_bolt_b"] / 2, 0) for sy in (-1, 1)]
    s = cut_holes(s, V["bk_bolt"], pts, (0, 0, 1), 20)
    s = cut_holes(s, 9.5, [(x, y, 20 - 5.5) for x, y, _ in pts], (0, 0, 1), 5.5)
    if fixed:                                                       # bearing cover outline
        s = s.cut(cyl(30.0, (l / 2 - 0.5, 0, a), (1, 0, 0), 0.5).cut(cyl(29.0, (l / 2 - 0.5, 0, a), (1, 0, 0), 0.5)))
    return s


def locknut():
    """M12x1 BK12 lock nut with clamp screw, canonical: along +X from 0, Ø22 x 8."""
    n = cyl(V["locknut_d"], (0, 0, 0), (1, 0, 0), V["locknut_l"]).cut(cyl(12.0, (0, 0, 0), (1, 0, 0), 8))
    n = n.cut(box(0, 8, -1, 1, 6, 12))
    return cut_holes(n, 3.3, [(4, 3, 4), (4, -3, 4)], (0, 0, 1), 8)


def nema23():
    """NEMA23 stepper, 76 mm, canonical: flange face on z=0, body toward -z,
    shaft along +z. Cast flange with corner pockets for the bolt heads,
    laminated stack, rear cap and cable gland."""
    sq, ln, ft = V["m23_sq"], V["m23_len"], V["m23_flange_t"]
    hp = V["m23_holes"] / 2
    fl = box(-sq / 2, sq / 2, -sq / 2, sq / 2, -ft, 0).edges("|Z").chamfer(3)
    stack_l = ln - ft - 12
    stack = box(-sq / 2 + 0.6, sq / 2 - 0.6, -sq / 2 + 0.6, sq / 2 - 0.6, -ft - stack_l, -ft).edges("|Z").chamfer(7)
    rear = box(-sq / 2, sq / 2, -sq / 2, sq / 2, -ln, -ft - stack_l).edges("|Z").chamfer(7)
    m = fl.union(stack).union(rear)
    for k in range(1, 8):                                          # lamination grooves
        z = -ft - k * stack_l / 8
        m = m.cut(box(-sq / 2, sq / 2, -sq / 2, sq / 2, z - 0.3, z + 0.3)
                  .cut(box(-sq / 2 + 1.2, sq / 2 - 1.2, -sq / 2 + 1.2, sq / 2 - 1.2, z - 0.3, z + 0.3)))
    m = cut_holes(m, 5.2, [(sx * hp, sy * hp, -ft) for sx in (-1, 1) for sy in (-1, 1)], (0, 0, 1), ft)
    m = cut_holes(m, 10.5, [(sx * hp, sy * hp, -ln) for sx in (-1, 1) for sy in (-1, 1)], (0, 0, 1), ln - ft)
    m = m.union(cyl(V["m23_boss"], (0, 0, 0), (0, 0, 1), 1.6))
    sh = cyl(V["m23_shaft"] - 0.05, (0, 0, 1.6), (0, 0, 1), V["m23_shaft_l"] - 1.6)
    sh = sh.cut(box(-5, 5, (V["m23_shaft"] - 0.05) / 2 - 0.5, 5, 6, V["m23_shaft_l"]))
    m = m.union(sh)
    m = m.union(box(-7, 7, sq / 2, sq / 2 + 6, -ln + 2, -ln + 10))           # cable gland
    return m.union(cyl(5, (0, sq / 2 + 6, -ln + 6), (0, 1, 0), 15))


def coupler(length=30.0, d=25.0, bore_a=10.0, bore_b=8.0):
    """Jaw (spider) coupling D25 L30, canonical: along +X from 0. bore_a at
    the x=0 end, bore_b at the other; two hubs, polyurethane spider, M4 set
    screws."""
    hub = (length - 6) / 2
    a = cyl(d, (0, 0, 0), (1, 0, 0), hub)
    b = cyl(d, (length - hub, 0, 0), (1, 0, 0), hub)
    jaws = cyl(d, (hub, 0, 0), (1, 0, 0), 6)
    for k in range(6):                                           # spider gaps between the jaws
        jaws = jaws.cut(box(hub, hub + 6, -0.8, 0.8, 6, d / 2 + 1).rotate((0, 0, 0), (1, 0, 0), 60 * k + 30))
    c = a.union(b).union(jaws)
    c = c.cut(cyl(bore_a + 0.05, (0, 0, 0), (1, 0, 0), length / 2))
    c = c.cut(cyl(bore_b + 0.05, (length / 2, 0, 0), (1, 0, 0), length / 2))
    c = cut_holes(c, 3.3, [(hub / 2, 0, 5), (length - hub / 2, 0, 4)], (0, 0, 1), d / 2)
    return c


def standoff(length, af=10.0):
    """Hex standoff M5 female both ends, canonical: along +X from 0."""
    return hexagon(af, length, (0, 0, 0), "X").cut(cyl(4.2, (0, 0, 0), (1, 0, 0), length))


def spindle(tool_out=25.0):
    """Zhong Hua Jiang 65 mm 1.5 kW water-cooled ER11 spindle, canonical:
    axis +Z, bottom of the Ø65 body at z=0. Body Ø65 x 200 (front cap 9,
    housing 171, rear cap 20), front bearing cap Ø51.2 x 19.5, nose Ø33.5,
    shaft Ø17.8, ER11 nut Ø19 x 13; GX16 plug and two water fittings within
    13 mm behind the body. Plus a 1/8" tool. Returns (spindle, tool)."""
    L, d = V["sp_body_l"], V["sp_d"]
    s = cyl(d, (0, 0, 0), (0, 0, 1), L)
    for z in (9.0, L - 20.0):                                                      # cap joints
        s = s.cut(cyl(d + 1, (0, 0, z - 0.3), (0, 0, 1), 0.6).cut(cyl(d - 1.2, (0, 0, z - 0.3), (0, 0, 1), 0.6)))
    s = s.union(cyl(51.2, (0, 0, -19.5), (0, 0, 1), 19.5))
    nut_l = V["sp_nut_l"]
    z_nose = -(V["sp_front"] - nut_l - 4.3)                                         # bottom of the Ø33.5 nose
    s = s.union(cyl(33.5, (0, 0, z_nose), (0, 0, 1), -19.5 - z_nose))
    s = s.union(cyl(17.8, (0, 0, z_nose - 4.3), (0, 0, 1), 4.3))
    z_nut = -V["sp_front"]
    nut = cyl(V["sp_nut_d"], (0, 0, z_nut), (0, 0, 1), nut_l)
    nut = nut.cut(box(-12, 12, 8.0, 12, z_nut, z_nut + 6)).cut(box(-12, 12, -12, -8.0, z_nut, z_nut + 6))
    s = s.union(nut)
    r = V["sp_rear"]
    s = s.union(cyl(19, (0, 0, L), (0, 0, 1), 3)).union(cyl(16, (0, 0, L + 3), (0, 0, 1), r - 3))   # GX16 plug
    for x in (-20, 20):                                                              # water fittings
        s = s.union(hexagon(10, 4, (x, 0, L), "Z")).union(cyl(6, (x, 0, L + 4), (0, 0, 1), r - 4))
    tool = cyl(3.175, (0, 0, z_nut - tool_out), (0, 0, 1), tool_out)
    return s, tool


def spindle_tip_below_body(tool_out=25.0):
    return V["sp_front"] + tool_out


# ============================================================ fasteners
SHCS = {3: (5.5, 2.5), 4: (7.0, 3.0), 5: (8.5, 4.0), 6: (10.0, 5.0), 8: (13.0, 6.0), 12: (18.0, 10.0)}


def shcs(d, length):
    """ISO 4762 socket head cap screw, canonical: underside of the head at
    z=0, shank along +z (into the part), head toward -z. Thread not drawn."""
    dk, s = SHCS[d]
    head = cyl(dk, (0, 0, -d), (0, 0, 1), d).edges("<Z").fillet(d * 0.08)
    head = head.cut(hexagon(s, 0.6 * d, (0, 0, -d), "Z"))
    return head.union(cyl(d, (0, 0, 0), (0, 0, 1), length))


def shcs_head(d):
    dk, _ = SHCS[d]
    return cyl(dk, (0, 0, -d), (0, 0, 1), d)


# ============================================================ accessories
def bellows(length, od=29.0, id_=18.0, folds=24):
    """Round ball-screw bellows (PU/fabric, Ø29 / Ø18), canonical: along +X
    from 0. Fold count is fixed, so the pitch follows the length; it works
    down to about 18 % of full extension."""
    b = cyl(od, (0, 0, 0), (1, 0, 0), length).cut(cyl(id_, (0, 0, 0), (1, 0, 0), length))
    p = length / folds
    rings = [cq.Solid.makeCylinder(od / 2 + 1, p / 2, cq.Vector(i * p + p / 4, 0, 0), cq.Vector(1, 0, 0))
             .cut(cq.Solid.makeCylinder(od / 2 - 2.5, p / 2, cq.Vector(i * p + p / 4, 0, 0), cq.Vector(1, 0, 0)))
             for i in range(folds)]
    return b.cut(cq.Workplane().add(cq.Compound.makeCompound(rings)))


def inductive_sensor(length=55.0):
    """M12 inductive proximity sensor, 4 mm range, PNP NO (LJ12A3-4-Z/BY
    class), canonical: sensing face at z=0, body along +z, cable gland and
    10 mm of cable at the far end."""
    s = cyl(12, (0, 0, 0), (0, 0, 1), length)
    for k in range(int(length // 1.75)):                                        # thread look
        s = s.cut(cyl(13, (0, 0, 3 + k * 1.75), (0, 0, 1), 0.4).cut(cyl(11.2, (0, 0, 3 + k * 1.75), (0, 0, 1), 0.4))) \
            if 3 + k * 1.75 < length - 6 else s
    return s.union(cyl(8, (0, 0, length), (0, 0, 1), 6)).union(cyl(4.5, (0, 0, length + 6), (0, 0, 1), 10))


def hex_nut(af, thick, bore):
    """Hex nut, canonical: along +z from 0."""
    return hexagon(af, thick, (0, 0, 0), "Z").cut(cyl(bore, (0, 0, 0), (0, 0, 1), thick))


def drag_chain(x_fixed, x_moving, x_loop, r, h, w):
    """Cable drag chain lying in the XZ plane, canonical: lower (fixed) run on
    z=0..h from x_fixed to x_loop, loop of centreline radius r opening to +X,
    upper (moving) run from x_moving to x_loop; width w centred on y=0.
    Link joints drawn every 15 mm."""
    zc = h / 2 + r                                                            # loop centre height
    lower = box(x_fixed, x_loop, -w / 2, w / 2, 0, h)
    upper = box(x_moving, x_loop, -w / 2, w / 2, 2 * r, 2 * r + h)
    loop = (cq.Workplane("XZ", origin=(0, w / 2, 0)).center(x_loop, zc).circle(r + h / 2).circle(r - h / 2)
            .extrude(w).intersect(box(x_loop, x_loop + r + h, -w / 2, w / 2, 0, 2 * r + h)))
    c = lower.union(loop).union(upper)
    cuts = [cq.Solid.makeBox(0.8, w + 2, h + 2, cq.Vector(x, -w / 2 - 1, -1)) for x in
            [x_fixed + 15 * k for k in range(1, int((x_loop - x_fixed) // 15))]]
    cuts += [cq.Solid.makeBox(0.8, w + 2, h + 2, cq.Vector(x, -w / 2 - 1, 2 * r - 1)) for x in
             [x_moving + 15 * k for k in range(1, int((x_loop - x_moving) // 15))]]
    if cuts:
        c = c.cut(cq.Workplane().add(cq.Compound.makeCompound(cuts)))
    return c


def levelling_foot():
    """Levelling foot M12, Ø50 pad with swivel, canonical: pad on z=0, stud
    up to z=40 (the top 10 mm sit in the foot plate's thread), lock nut."""
    f = cyl(50, (0, 0, 0), (0, 0, 1), 8).union(cyl(30, (0, 0, 8), (0, 0, 1), 4))
    f = f.union(cq.Workplane().add(cq.Solid.makeSphere(9, cq.Vector(0, 0, 16))))
    f = f.union(cyl(12, (0, 0, 20), (0, 0, 1), 20))
    return f.union(hex_nut(19, 8, 12).translate((0, 0, 22)))


def tool_setter():
    """Tool-length touch probe, Ø40 x 25 with spring plunger and cable,
    canonical: base on z=0."""
    t = cyl(40, (0, 0, 0), (0, 0, 1), 20).union(cyl(16, (0, 0, 20), (0, 0, 1), 5))
    return t.union(cyl(5, (0, 20, 6), (0, 1, 0), 15))


def safety_switch():
    """Door safety switch with separate actuator (AZ 16 / PSEN class):
    body 31 x 31 x 100, canonical: mounting face on z=0, body toward +z,
    actuator entry facing -x. Returns (body, actuator)."""
    body = box(-15.5, 15.5, -50, 50, 0, 31).edges("|Z").fillet(2)
    body = body.union(cyl(10, (0, 50, 15.5), (0, 1, 0), 12))                 # cable gland
    act = box(-30, -17, -10, 10, 3, 28).union(box(-38, -30, -15, 15, 0, 31))
    return body, act
