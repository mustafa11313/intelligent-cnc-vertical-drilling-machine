"""The whole machine as real solids, in one STEP file, Z up.

    python3 full_assembly.py <Ana_Montaj_1_6_25.x_t>

Writes
    step/full_machine_original.step   the machine as built (graduation project)
    step/full_machine_upgraded.step   with every upgrade from UPGRADE.md fitted
Both open in FreeCAD, SolidWorks, Fusion etc. with part names and colours.

The original parts are rebuilt from the Parasolid file (xt/brep.py): each
face on its exact surface, sewn into solids. The upgrade parts come from
upgrade.py, the bought parts from bought.py; rails and blocks are copies of
the HIWIN models in your own assembly, cut to the new lengths.

The SolidWorks frame is Y up; the files here are turned so that Z is up
(SolidWorks Y -> Z, Z -> -Y), which is what FreeCAD and most CAM expect.
"""
import os
import sys

import cadquery as cq
import numpy as np
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Trsf
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS_Shape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "xt"))
import bought as B  # noqa: E402
import brep  # noqa: E402
import upgrade as U  # noqa: E402
import upgrade_check as UC  # noqa: E402
from model import Model  # noqa: E402

CACHE = os.path.join(HERE, ".brep_cache")

# ------------------------------------------------------------------ colours
STEEL = (0.62, 0.64, 0.67)
ALU = (0.80, 0.82, 0.85)
ALU_DARK = (0.55, 0.58, 0.62)
BLACK = (0.12, 0.12, 0.13)
BLACK_OX = (0.20, 0.20, 0.22)
BRASS = (0.78, 0.62, 0.30)
BRONZE = (0.70, 0.50, 0.28)
PAINT = (0.25, 0.30, 0.36)
BLUE = (0.15, 0.35, 0.75)
POM = (0.95, 0.95, 0.92)
ORANGE = (0.95, 0.55, 0.10)
NEW_ALU = (0.78, 0.80, 0.86)


def colour_of(name):
    n = name.lower()
    if n.startswith(("iso 4762", "m3 x", "m4x", "m5x")):
        return BLACK_OX
    if n.startswith(("nut_din", "m6_din")) or "626" in n:
        return STEEL
    if "stepper" in n:
        return BLACK if n.endswith("_01") else STEEL
    if "coupler" in n:
        return ALU_DARK
    if "somunu" in n and "vidal" in n:
        return BRASS
    if "trapez" in n:
        return STEEL
    if "ray" in n or "hgr" in n or "hgh" in n or "hgw" in n:
        return STEEL
    if "yan_plaka" in n or "kapak-son" in n:
        return PAINT
    if "hma85" in n:
        return (0.85, 0.86, 0.88)
    if "er 16" in n or "drill" in n:
        return STEEL
    if "2.1.001" in n:
        return BLACK
    return ALU


# --------------------------------------------------------------- helpers
def trsf_from(T):
    t = gp_Trsf()
    R = T[:3, :3]
    p = T[:3, 3]
    t.SetValues(*map(float, (R[0, 0], R[0, 1], R[0, 2], p[0],
                             R[1, 0], R[1, 1], R[1, 2], p[1],
                             R[2, 0], R[2, 1], R[2, 2], p[2])))
    return t


def moved(shape, T):
    return BRepBuilderAPI_Transform(shape, trsf_from(T), True).Shape()


def mat(R=np.eye(3), p=(0, 0, 0)):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def volume(shape):
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


def body_cached(m, idx):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{idx}.brep")
    if os.path.exists(path):
        s = TopoDS_Shape()
        BRepTools.Read_s(s, path, BRep_Builder())
        return s
    s, _ = brep.body_shape(m, idx)
    if volume(s) < 0:
        s = s.Reversed()
    BRepTools.Write_s(s, path)
    return s


def wp(shape):
    return cq.Workplane().add(cq.Shape.cast(shape))


# rotations taking a part's local frame (rail along +x, top along +y,
# as the X rails are modelled) to the other axes
R_Y = np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float)    # rail along +z, top facing +x
R_Z = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]], float)   # rail along +y, top facing +x
LOCAL_Z_TO = {                                              # bought.py parts are built along +z
    "+x": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float),
    "+y": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float),
    "-y": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float),
    "+z": np.eye(3),
}


def place_local(w, axis, p):
    """A bought.py Workplane, built along +z from the origin, to point p, along axis."""
    return moved(w.val().wrapped, mat(LOCAL_Z_TO[axis], p))


# ---------------------------------------------------------------- builder
class Machine:
    def __init__(self, xt_path):
        self.m = Model.load(xt_path, cache=os.path.join(HERE, ".xt_cache.pkl"))
        self.leaves = self.m.leaves()
        self.parts = []                 # (name, shape, colour)

    def add(self, name, shape, colour):
        self.parts.append((name, shape, colour))

    def original_shape(self, inst):
        return moved(body_cached(self.m, inst.body.idx), inst.T)

    def find(self, leaf_start, pred=None):
        for inst in self.leaves:
            if inst.path.split("/")[-1].startswith(leaf_start) and (pred is None or pred(inst)):
                return inst
        raise KeyError(leaf_start)

    # ------------------------------------------------------------ original
    def build_original(self):
        for inst in self.leaves:
            leaf = inst.path.split("/")[-1]
            self.add(leaf, self.original_shape(inst), colour_of(leaf))

    # ------------------------------------------------------------- upgrade
    def build_upgraded(self):
        h = UC.Z_HOVER
        for inst in self.leaves:
            leaf = inst.path.split("/")[-1]
            if UC.is_replaced(inst.path) or "drill_bit" in leaf or leaf.startswith("On_Kapak-Son"):
                continue
            off = UC.placement(inst)
            if off is None:
                continue
            self.add(leaf, moved(self.original_shape(inst), mat(p=off)), colour_of(leaf))

        for name, fn in U.PARTS.items():
            s = fn()
            if name in ("head_yoke_camera", "pressure_foot_dustshoe", "z_home_flag", "y_home_flag"):
                s = s.translate((0, h, 0))
            col = STEEL if name.endswith("flag") else NEW_ALU
            if name == "pressure_foot_dustshoe":
                col = (0.85, 0.85, 0.80)                               # PETG / POM
            self.add(name, s.val().wrapped, col)

        # X front plate with the KFL08 seat (replaces On_Kapak-Son), its local frame -> world
        fp = cq.importers.importStep(os.path.join(HERE, "step", "x_front_plate_KFL08.step")).val().wrapped
        Rfp = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
        self.add("x_front_plate_KFL08", moved(fp, mat(Rfp, (200.0, 75.0, -133.25))), PAINT)
        self.add("KFL08 X screw bearing", place_local(B.kfl08(), "+x", (205.0, 67.5, -131.5)), (0.3, 0.3, 0.32))

        self.rails_and_blocks()
        self.screws_and_bearings()
        self.head_parts(h)
        self.sensors()
        self.add("G1/8 vacuum fitting", place_local(B.hose_fitting(), "+x", (148.0, 131.0, U.TABLE_C[1])), BRASS)

    def rails_and_blocks(self):
        rail = self.find("HGR 15H RAY-1(L=400)", lambda i: i.bbox()[1][2] > 0)     # front X rail, z -7.5..7.5
        block = self.find("hgh15ca", lambda i: i.bbox()[1][2] > 0)                 # front X block, centre x 48
        rail_s = self.original_shape(rail)
        block_s = self.original_shape(block)
        rail_ref = np.array([-200.0, 90.0, 0.0])                                   # rail start, base, centre line
        block_ref = np.array([48.0, 90.0, 0.0])

        def rail_piece(length):
            cut = cq.Workplane().box(length, 40, 40, centered=(False, True, True)).translate((-200, 97.5, 0))
            return BRepAlgoAPI_Common(rail_s, cut.val().wrapped).Shape()

        def put(shape, ref, R, to):
            return moved(moved(shape, mat(p=-ref)), mat(R, to))

        yc = U.YC
        for yr in (347.5, 392.5):                                                  # 2 Y rails + blocks
            self.add("HGR15 Y rail 306", put(rail_piece(306.5), rail_ref, R_Y, (-125.0, yr, -286.5)), STEEL)
            self.add("HGH15CA Y block", put(block_s, block_ref, R_Y, (-125.0, yr, yc)), STEEL)
        for zr in (yc - 50, yc + 50):                                              # Z rails 195
            self.add("HGR15 Z rail 195", put(rail_piece(195.0), rail_ref, R_Z, (-88.0, 245.0, zr)), STEEL)
        for bx in (U.TABLE_C[0] - 49, U.TABLE_C[0] + 49):                          # 4 X blocks
            for rz in (0.0, -266.5):
                self.add("HGH15CA X block", put(block_s, block_ref, np.eye(3), (bx, 90.0, rz)), STEEL)

    def screws_and_bearings(self):
        yc = U.YC
        self.add("Tr8x2 X screw 395", place_local(B.tr8_screw(395), "+x", (-177.0, 67.5, -131.5)), STEEL)
        ax, az = -81.0 + U.ZSHIFT[0], yc                                           # Z screw axis
        self.add("Tr8x2 Z screw 230", place_local(B.tr8_screw(230), "+y", (ax + 6.0 - 6.0, 265.0, az)), STEEL)
        for y0 in (455.0, 468.0):
            self.add("608ZZ", place_local(B.bearing(22, 8, 7), "+y", (ax, y0, az)), STEEL)
        for y0 in (446.0, 475.0):
            self.add("lock collar 8", place_local(B.lock_collar(), "+y", (ax, y0, az)), BLACK_OX)
        for x in (-96.5 + 6.0, -65.5 + 6.0):
            for z in (-109.75, -140.75):
                self.add("M3x50 standoff", place_local(B.standoff(48.0), "+y", (x, 475.0, z)), BRASS)

    def head_parts(self, h):
        yc = U.YC
        for zr in (yc - U.ROD_DZ, yc + U.ROD_DZ):
            self.add("guide rod 6x110", place_local(cq.Workplane().circle(3).extrude(110), "+y",
                                                    (-21.0, 135.0 + h, zr)), STEEL)
            self.add("spring 6.5x70", place_local(B.spring(length=66.0), "+y", (-21.0, 143.5 + h, zr)), STEEL)
            self.add("bronze bushing 6x10x10", place_local(B.bushing(), "+y", (-21.0, 211.2 + h, zr)), BRONZE)
        for nm, w, col in B.endoscope():
            self.add(f"head camera (USB endoscope 8 mm) {nm}", place_local(w, "+y", (37.0, 190.0 + h, yc + 25)), col)   # clamped on the steel tip
        self.add("PCB drill 1.0 mm", place_local(B.pcb_bit(), "+y", (-21.0, 126.3 + h, yc)), (0.75, 0.75, 0.78))
        # Spindle sensors for the DAQ board (electronics/README.md §3.6). They are bonded to flat
        # faces of the spindle body (+Z side face at z -89.3, -Z side face at z -161.2).
        flip = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], float)            # local +Z -> world -Z
        for label, R, p in (("temperature probe 1 (DS18B20, lower bearing)", np.eye(3), (-25.0, 269.0 + h, -89.3)),
                            ("temperature probe 2 (DS18B20, upper bearing)", flip, (-25.0, 347.0 + h, -161.2))):
            for nm, w, col in B.ds18b20_clamp():
                self.add(f"{label} {nm}", moved(w.val().wrapped, mat(R, p)), col)
        # ADXL345: the app reads tilt from the board's Z axis, so the board must lie flat. A 3 mm aluminium
        # angle is bonded to the front face; the box sits on its shelf with the board horizontal.
        face, top = -89.2, 355.0 + h                                           # front face, shelf top
        angle = (cq.Workplane("XY").box(32.0, 26.0, 3.0, centered=(True, False, False)).translate((-28.0, top - 26.0, face))
                 .union(cq.Workplane("XY").box(32.0, 3.0, 30.0, centered=(True, False, False))
                        .translate((-28.0, top - 3.0, face))))
        self.add("vibration sensor (ADXL345) mounting angle", angle.val().wrapped, ALU)
        for nm, w, col in B.adxl345_box():
            self.add(f"vibration sensor (ADXL345) {nm}",
                     place_local(w, "+y", (-28.0, top, face + 3.0 + 13.5)), col)

    def sensors(self):
        (xx, xy), (yx, yy), (zx, zz) = U.X_SENSOR, U.Y_SENSOR, U.Z_SENSOR
        for name, p, axis, nut_at in (("X home sensor", (xx, xy, 20.0), "+z", 7.5),
                                      ("Y home sensor", (yx, yy, 22.5), "+z", 10.0),
                                      ("Z home sensor", (zx, 455.0, zz), "+y", 20.0)):
            body, led, cable, face = B.m12_sensor()
            self.add(name, place_local(body, axis, p), (0.70, 0.70, 0.72))
            self.add(name + " LED", place_local(led.translate((0, 0, 49)), axis, p), ORANGE)
            self.add(name + " cable", place_local(cable, axis, p), BLACK)
            self.add(name + " nut", place_local(B.m12_nut().translate((0, 0, nut_at)), axis, p), STEEL)

    # ---------------------------------------------------------------- write
    def write(self, path, title):
        z_up = cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 90)            # SolidWorks Y up -> Z up
        asm = cq.Assembly(name=title, loc=z_up)
        counts = {}
        for name, shape, col in self.parts:
            k = counts[name] = counts.get(name, 0) + 1
            asm.add(cq.Shape.cast(shape), name=f"{name}_{k}" if k > 1 else name, color=cq.Color(*col))
        asm.save(path, "STEP")
        return len(self.parts)


def main(xt_path):
    out = os.path.join(HERE, "step")
    for kind in ("original", "upgraded"):
        mc = Machine(xt_path)
        getattr(mc, f"build_{kind}")()
        n = mc.write(os.path.join(out, f"full_machine_{kind}.step"), f"drilling_machine_{kind}")
        print(f"full_machine_{kind}.step: {n} parts")


if __name__ == "__main__":
    main(sys.argv[1])
