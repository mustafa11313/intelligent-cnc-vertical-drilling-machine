"""Render step/*.step into parts_preview.png (matplotlib, no GUI needed)."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = [("spoilboard_insert_150x200", "Spoilboard insert 150×200×4"),
         ("pcb_riser_200x200x45", "PCB riser 200×200×45"),
         ("nut_block_antibacklash_Tr8", "Anti-backlash Y/Z nut block"),
         ("x_front_plate_KFL08", "X front plate for KFL08"),
         ("limit_sensor_bracket_M12", "Limit sensor bracket M12")]

UPGRADE = [("upgrade/y_carriage_plate", "Y carriage plate (2 rails, Z lowered)"),
           ("upgrade/z_top_plate_608x2", "Z top plate, 2× 608 thrust"),
           ("upgrade/x_table_4block", "X table, 4 blocks"),
           ("upgrade/vacuum_plate_200x200", "Vacuum plate 200×200"),
           ("upgrade/head_yoke_camera", "Head yoke + camera holder"),
           ("upgrade/pressure_foot_dustshoe", "Pressure foot / dust shoe")]


def sheet(parts, out, y_up=False):
    fig = plt.figure(figsize=(15, 8.5))
    for k, (f, title) in enumerate(parts):
        _draw(fig, k, f, title, y_up)
    plt.tight_layout()
    plt.savefig(os.path.join(HERE, out), dpi=100)
    plt.close(fig)


def _draw(fig, k, f, title, y_up=False):
    shape = cq.importers.importStep(os.path.join(HERE, "step", f + ".step")).val()
    verts, tris = shape.tessellate(0.1)
    v = [(p.x, p.z, p.y) if y_up else (p.x, p.y, p.z) for p in verts]   # assembly parts: Y is up
    ax = fig.add_subplot(2, 3, k + 1, projection="3d")
    ax.add_collection3d(Poly3DCollection([[v[i] for i in t] for t in tris],
                                         facecolors="#8fa3c4", edgecolors="#8fa3c4", linewidth=0, shade=True))
    bb = shape.BoundingBox()
    c = ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)
    if y_up:
        c = (c[0], c[2], c[1])
    r = max(bb.xlen, bb.ylen, bb.zlen) / 2
    ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r); ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1)); ax.set_title(title)
    if y_up:
        ax.set_xlabel("X"); ax.set_ylabel("Z"); ax.set_zlabel("Y (up)")
    else:
        ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")


if __name__ == "__main__":
    sheet(PARTS, "parts_preview.png")
    if os.path.isdir(os.path.join(HERE, "step", "upgrade")):
        sheet(UPGRADE, "upgrade_parts_preview.png", y_up=True)
