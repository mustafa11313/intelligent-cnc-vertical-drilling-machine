"""Put the upgrade parts into the real assembly and check them.

    python3 upgrade_check.py <Ana_Montaj.x_t>

Loads the original assembly with xt/, removes the parts the upgrade
replaces, moves the Z unit by upgrade.ZSHIFT, adds the new parts and
stand-ins for the bought parts (rails, blocks, screws), then:
  * reports any original edge that ends up inside a new solid (a clash),
  * reports the new travel of each axis,
  * draws upgrade_views.png (front, top, side, 3D) in the same style as
    assembly_views.png, new parts in orange.
"""
import os
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from OCP.BRepClass3d import BRepClass3d_SolidClassifier  # noqa: E402
from OCP.gp import gp_Pnt  # noqa: E402
from OCP.TopAbs import TopAbs_IN  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "xt"))
import upgrade as U  # noqa: E402
from model import Model  # noqa: E402

REPLACED = ("Tabla2", "Arka Kapak", "300x250", "Y eksen Ray", "hgh15ca", "HGR 15H RAY-1-Z", "Z_Trapez", "X_Trapez")
FASTENER = ("ISO 4762", "M3 x", "M4x", "M5x", "nut_din", "DIN125")
Z_UNIT = ("Spindle_Tutucu", "HMA85", "ER 16", "ER 161", "drill_bit", "Z Eksen Somunu", "Z_Trapez")


def is_replaced(path):
    leaf = path.split("/")[-1]
    if leaf.startswith(REPLACED):
        return True
    if "Spindle_Yarı" in path and leaf.startswith(("nut_din", "M6_DIN125")):    # stop nut on the old Z screw end
        return True
    # the single Y block (HGW15CC behind the carriage plate) is replaced by 2 x HGH15CA
    return False


Z_HOVER = 25.0      # draw the Z unit 25 mm above its CAD pose: a 1 mm PCB bit hovering ~10 mm over the board
Z_MOVING = ("Spindle_Tutucu", "HMA85", "ER 16", "ER 161", "Z Eksen Somunu")


def placement(inst):
    """Offset of an original part in the upgraded machine."""
    leaf = inst.path.split("/")[-1]
    lo, hi = inst.bbox()
    if "Spindle_Yarı" not in inst.path:
        return np.zeros(3)
    if "Step_Motor" in inst.path:
        return np.array([U.ZSHIFT[0], 60.0, 0.0])          # motor on 50 mm standoffs above the new top plate
    if leaf.startswith("NEMA17_Coupler"):
        return np.array([U.ZSHIFT[0], 60.0, 0.0])
    if leaf.startswith("HGW") and lo[0] < -95:              # the Y block: replaced
        return None
    if leaf.startswith("M3 x12") and lo[1] > 450:           # motor screws go with the motor
        return np.array([U.ZSHIFT[0], 60.0, 0.0])
    if leaf.startswith(Z_MOVING) or (leaf.startswith("HGW") and lo[0] > -95) or \
            (leaf.startswith(("M5x12", "M3 x12")) and lo[0] > -82 and lo[1] < 400):
        return np.array(U.ZSHIFT) + [0, Z_HOVER, 0]         # moves with Z
    if lo[0] > -95 or leaf.startswith(Z_UNIT):              # everything in front of the carriage plate
        return np.array(U.ZSHIFT)
    return np.zeros(3)                                      # top link, Y nut parts: unchanged


def bought_parts():
    """Simple stand-ins (bounding solids) for rails, blocks and screws."""
    b = U.box
    yc = U.YC
    parts = []
    for yr in (347.5, 392.5):                                # 2 Y rails + HGH15CA
        parts.append(("HGR15 Y rail", b(-125, -110, yr - 7.5, yr + 7.5, -286.5, 20.0)))
        parts.append(("HGH15CA Y block", b(-120.7, -97, yr - 17, yr + 17, yc - 30.7, yc + 30.7)))
    for zr in (yc - 50, yc + 50):                            # Z rails 195 mm
        parts.append(("HGR15 Z rail", b(-88, -73, 245, 440, zr - 7.5, zr + 7.5)))
    for bx in (U.TABLE_C[0] - 49, U.TABLE_C[0] + 49):        # 4 table blocks
        for rz in (0.0, -266.5):
            parts.append(("HGH15CA X block", b(bx - 30.7, bx + 30.7, 94.3, 118.0, rz - 17, rz + 17)))
    parts.append(("Tr8x2 X screw 395", U.cyl(8, (-177, 67.5, -131.5), (1, 0, 0), 395)))
    parts.append(("KFL08", b(205, 216, 54, 81, -131.5 - 24, -131.5 + 24)))
    parts.append(("Tr8x2 Z screw 230", U.cyl(8, (-75, 265, yc), (0, 1, 0), 230)))
    h = Z_HOVER
    for zr in (yc - U.ROD_DZ, yc + U.ROD_DZ):
        parts.append(("guide rod 6x110", U.cyl(6, (-21, 135 + h, zr), (0, 1, 0), 110)))
    parts.append(("endoscope camera", U.cyl(8, (37, 190 + h, yc + 25), (0, 1, 0), 50)))
    parts.append(("PCB bit 1.0 mm", U.cyl(1.0, (-21, 126.3 + h, yc), (0, 1, 0), 8)))
    parts.append(("PCB bit shank", U.cyl(3.175, (-21, 134.3 + h, yc), (0, 1, 0), 30)))
    return parts


def inside(shape, pts):
    solid = shape.val().wrapped
    clf = BRepClass3d_SolidClassifier(solid)
    hits = []
    for p in pts:
        clf.Perform(gp_Pnt(*map(float, p)), 1e-3)
        if clf.State() == TopAbs_IN:
            hits.append(p)
    return hits


def main(xt_path):
    m = Model.load(xt_path, cache=os.path.join(HERE, ".xt_cache.pkl"))
    old = []
    for inst in m.leaves():
        if not inst.body.polylines or is_replaced(inst.path) or "drill_bit" in inst.path:
            continue
        off = placement(inst)
        if off is None:
            continue
        old.append((inst.path, [p + off for p in inst.polylines()]))

    new = {n: fn() for n, fn in U.PARTS.items()}
    for n in ("head_yoke_camera", "pressure_foot_dustshoe"):          # these move with Z
        new[n] = new[n].translate((0, Z_HOVER, 0))
    bought = bought_parts()

    print("Clash check (original edges inside new solids, 0.2 mm tolerance):")
    clean = True
    for name, shape in list(new.items()) + bought:
        bb = shape.val().BoundingBox()
        lo = np.array([bb.xmin, bb.ymin, bb.zmin]) + 0.2
        hi = np.array([bb.xmax, bb.ymax, bb.zmax]) - 0.2
        for path, polys in old:
            leaf = path.split("/")[-1]
            if leaf.startswith(FASTENER) or "drill_bit" in leaf:      # screws get new lengths; see README
                continue
            if name.startswith(("HGR15", "HGH15CA", "Tr8x2")) and leaf.startswith(("HGW", "HGR", "Vidal")):
                continue                                              # stand-in boxes wrap their rail/nut
            pts = np.vstack(polys)
            pts = pts[np.all((pts > lo) & (pts < hi), axis=1)]
            if not len(pts):
                continue
            hits = inside(shape, pts[:: max(1, len(pts) // 400)])
            if hits:
                clean = False
                print(f"  {name} <-> {path}: {len(hits)} points, e.g. {np.round(hits[0], 1)}")
    if clean:
        print("  none")

    # ---------------------------------------------------------------- draw
    fig = plt.figure(figsize=(20, 15))
    views = [(0, 1, "Front: X right, Y up"), (0, 2, "Top: X right, Z"), (2, 1, "Side: Z right, Y up")]

    def edges(shape):
        out = []
        for e in shape.val().Edges():
            ts = np.linspace(0, 1, 16 if e.geomType() != "LINE" else 2)
            out.append(np.array([e.positionAt(t).toTuple() for t in ts]))
        return out

    new_edges = [edges(s) for s in new.values()]
    bought_edges = [edges(s) for _, s in bought]
    for k, (a, b, title) in enumerate(views):
        ax = fig.add_subplot(2, 2, k + 1)
        for _, polys in old:
            for p in polys:
                ax.plot(p[:, a], p[:, b], lw=0.3, color="#888888")
        for group in bought_edges:
            for p in group:
                ax.plot(p[:, a], p[:, b], lw=0.6, color="#1f77b4")
        for group in new_edges:
            for p in group:
                ax.plot(p[:, a], p[:, b], lw=0.8, color="#e8590c")
        ax.set_aspect("equal"); ax.set_title(title); ax.grid(alpha=0.3)
    ax = fig.add_subplot(2, 2, 4, projection="3d")
    for _, polys in old:
        for p in polys:
            ax.plot(p[:, 0], p[:, 2], p[:, 1], lw=0.25, color="#888888")
    for group in bought_edges:
        for p in group:
            ax.plot(p[:, 0], p[:, 2], p[:, 1], lw=0.5, color="#1f77b4")
    for group in new_edges:
        for p in group:
            ax.plot(p[:, 0], p[:, 2], p[:, 1], lw=0.7, color="#e8590c")
    ax.set_box_aspect((480, 380, 560)); ax.view_init(elev=22, azim=-58)
    ax.set_xlabel("X"); ax.set_ylabel("Z"); ax.set_zlabel("Y (up)"); ax.set_title("3D")
    fig.legend(handles=[plt.Line2D([], [], color="#888888", label="your parts (Z unit moved down 45 mm)"),
                        plt.Line2D([], [], color="#e8590c", label="new parts (upgrade.py)"),
                        plt.Line2D([], [], color="#1f77b4", label="bought parts (rails, blocks, screws, rods)")],
               loc="upper center", ncol=3, fontsize=12)
    plt.tight_layout(rect=(0, 0, 1, 0.97))
    plt.savefig(os.path.join(HERE, "upgrade_views.png"), dpi=90)
    print("wrote upgrade_views.png")


if __name__ == "__main__":
    main(sys.argv[1])
