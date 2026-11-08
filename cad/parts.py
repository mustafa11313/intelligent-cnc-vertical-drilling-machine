"""Parametric replacement/add-on parts for the drilling machine (CadQuery).

    pip install cadquery
    python3 parts.py            # writes step/*.step and step/*.svg previews

Dimensions come from the real assembly (Parasolid/Ana_Montaj_1_6_25.x_t,
read with xt/), not from the report drawings. Values that are bought-part
data (bearing, anti-backlash nut) are marked VENDOR: check them against
the part you actually buy.
Import the STEP files into SolidWorks (File > Open > STEP) and mate them
into Ana_Montaj.
"""
import os

import cadquery as cq

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "step")


def export(shape, name):
    cq.exporters.export(shape, os.path.join(OUT, name + ".step"))
    cq.exporters.export(shape, os.path.join(OUT, name + ".svg"),
                        opt={"projectionDir": (1, -1.4, 1.1), "showHidden": False,
                             "width": 500, "height": 380, "marginLeft": 30, "marginTop": 30})
    bb = shape.val().BoundingBox()
    print(f"{name}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")


def spoilboard_insert(pocket_x=150.0, pocket_y=200.0, pocket_r=5.0, depth=4.0,
                      clearance=0.2, pin_d=3.0, pin_offset=90.0):
    """Sacrificial backer for the pocket in "300x250 Is Tablasi".
    Measured in the CAD: 150 mm along machine X x 200 mm along machine Y,
    4 mm deep, R5 corners, centred on the table (only 6 mm of aluminium
    is left under it). Without a backer the PCB spans the pocket and flexes
    as the bit enters. Make it from 4 mm MDF/FR4 (or 3 mm + shim) and
    replace it when worn. Two Ø3 pin holes on the Y centre line, 180 mm
    apart, let you flip a double-sided board about the same axis (drill
    them with the machine itself so they sit exactly on its axes)."""
    w, h = pocket_x - 2 * clearance, pocket_y - 2 * clearance
    plate = (cq.Workplane("XY").rect(w, h).extrude(depth)
             .edges("|Z").fillet(pocket_r - clearance))
    plate = (plate.faces(">Z").workplane()
             .pushPoints([(0, -pin_offset), (0, pin_offset)]).hole(pin_d))
    return plate


def pcb_riser(size_x=200.0, size_y=200.0, thick=45.0, screw_xy=90.0,
              screw_d=5.5, cbore_d=10.0, cbore_depth=6.0, pin_d=3.0, pin_offset=90.0):
    """Work riser that lifts the PCB 45 mm, for standard PCB bits.
    In the CAD the lowest the collet face can reach is ~57 mm above the
    table top (Z blocks are 9 mm from the ends of the Z rails at the
    bottom). The model was set up with a 127 mm long Ø10 jobber drill,
    which reaches. A standard 38 mm PCB bit with ~20 mm out of the
    collet stops ~37 mm above the table, so it can never reach the board.
    With 45 mm and 20 mm of bit out of the collet, the tip reaches 9 mm
    below the top of a 1.6 mm board at the bottom of Z, and clears it by
    ~58 mm at the top. Bolt this to the table with 4x M5x55 into holes tapped in the table at
    (±90, ±90) mm from its centre (outside the pocket, clear of the
    carriage screws). MDF or aluminium; skim the top flat with the machine
    once fitted. Pin holes as on the spoilboard insert."""
    r = (cq.Workplane("XY").rect(size_x, size_y).extrude(thick)
         .edges("|Z").fillet(3))
    pts = [(sx * screw_xy, sy * screw_xy) for sx in (-1, 1) for sy in (-1, 1)]
    r = r.faces(">Z").workplane().pushPoints(pts).cboreHole(screw_d, cbore_d, cbore_depth)
    r = r.faces(">Z").workplane().pushPoints([(0, -pin_offset), (0, pin_offset)]).hole(pin_d)
    return r


def nut_block_antibacklash(width=40.0, height=25.0, length=30.0,        # Y/Z nut block, measured
                           bore=12.0,                                   # Ø11 -> Ø12 for the spring nut body (VENDOR)
                           flange_d=23.0, flange_depth=5.0,             # measured
                           flange_pcd=16.0, flange_tap=2.5,             # M3 tapping on Ø16, measured
                           mount_dx=30.0, mount_dy=15.0, mount_d=3.3):  # 4x M4 on 30 x 15, measured
    """Y/Z nut block ("Y Eksen Somunu_son" / "Z Eksen Somunu") with the
    same outside, flange recess and M4 mounting pattern as the original,
    but bored through Ø12 for a spring-loaded anti-backlash Tr8x2 nut
    (POM, flange Ø22 with 4 holes on Ø16, like your brass nut). Axis along Y."""
    blk = cq.Workplane("XZ").rect(width, height).extrude(-length)      # along +Y
    blk = (blk.faces("<Y").workplane(centerOption="CenterOfBoundBox")
           .cboreHole(bore, flange_d, flange_depth)
           .faces("<Y").workplane(centerOption="CenterOfBoundBox")
           .polarArray(flange_pcd / 2, 0, 360, 4).hole(flange_tap, 12))
    blk = (blk.faces(">Z").workplane(centerOption="CenterOfBoundBox")
           .rect(mount_dx, mount_dy, forConstruction=True).vertices().hole(mount_d, 10))
    return blk


def x_front_plate_kfl08(length=311.5, height=45.0, thick=5.0,
                        axis_from_bottom=15.0,          # X screw axis is 15 mm above the plate's lower edge
                        axis_offset=1.75,               # ...and 1.75 mm off centre, toward the profile at world Z=0 (+ side here)
                        profile_bolt_d=10.2, profile_pitch=266.5,
                        kfl_pitch=37.0, kfl_bolt_d=5.5, screw_hole_d=16.0):  # KFL08 (VENDOR)
    """Replacement for "On_Kapak-Son" (front end plate of the X axis).
    In the CAD the X lead screw is 255 mm long and ends in free air at
    X=+78 mm, 122 mm short of this plate. With a 395 mm screw passing
    through this plate into a KFL08 flange bearing on its outer face, the
    screw is held at both ends, the bearing takes the drilling thrust instead
    of the motor, and X travel grows from ~230 to ~320 mm.
    Same outline and M10 profile holes as the original, plus the KFL08
    holes, long axis horizontal so its 27 mm width fits the 45 mm plate."""
    plate = cq.Workplane("YZ").rect(length, height).extrude(thick)
    zc = -height / 2 + axis_from_bottom
    plate = (plate.faces(">X").workplane(centerOption="CenterOfBoundBox")
             .pushPoints([(-profile_pitch / 2, zc), (profile_pitch / 2, zc)]).hole(profile_bolt_d))
    plate = (plate.faces(">X").workplane(centerOption="CenterOfBoundBox")
             .pushPoints([(axis_offset, zc)]).hole(screw_hole_d)
             .faces(">X").workplane(centerOption="CenterOfBoundBox")
             .pushPoints([(axis_offset - kfl_pitch / 2, zc), (axis_offset + kfl_pitch / 2, zc)]).hole(kfl_bolt_d))
    return plate


def sensor_bracket_m12(slot_bolt=8.5, sensor_d=12.3, thick=4.0, width=25.0,
                       base_len=30.0, up_len=32.0):
    """L-bracket for an M12 inductive limit/home sensor (LJ12A3-4-Z/BX)
    on the sigma profile (M8 T-slot bolt, ASSUMED 10 mm slot). The slot
    gives ±5 mm adjustment of the trigger point. Print in PETG (100 %
    infill near the bend) or cut from 4 mm aluminium angle."""
    base = cq.Workplane("XY").box(base_len, width, thick, centered=(False, True, False))
    up = cq.Workplane("XY").box(thick, width, up_len, centered=(False, True, False))
    br = base.union(up).edges("|Y and (not <X) and (not >X)").fillet(1.0)
    br = br.cut(cq.Workplane("XY").center(base_len / 2 + thick / 2, 0)
                .slot2D(12, slot_bolt, 0).extrude(thick))
    br = br.cut(cq.Workplane("YZ").center(0, up_len / 2 + thick / 2)
                .circle(sensor_d / 2).extrude(thick))
    return br


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    export(spoilboard_insert(), "spoilboard_insert_150x200")
    export(pcb_riser(), "pcb_riser_200x200x45")
    export(nut_block_antibacklash(), "nut_block_antibacklash_Tr8")
    export(x_front_plate_kfl08(), "x_front_plate_KFL08")
    export(sensor_bracket_m12(), "limit_sensor_bracket_M12")
