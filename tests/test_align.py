"""Head-camera calibration and fiducial alignment against a simulated camera."""
import math

import numpy as np

from app import align
from app.vision import Calibration
from sim.camera_sim import render

MMPX = 0.02
CAM_OFFSET = np.array([55.0, 3.0])          # true camera offset from the spindle
CAM_ROT = 3.0                               # camera mounted 3° rotated


class FakeGrbl:
    def __init__(self):
        self.pos = np.zeros(2)

    def jog_to(self, x=None, y=None, z=None, feed=0):
        if x is not None:
            self.pos = np.array([x, self.pos[1]])
        if y is not None:
            self.pos = np.array([self.pos[0], y])

    def wait_idle(self, timeout=0):
        return True


def camera(grbl, board_holes):
    """Image the head camera takes with the spindle at grbl.pos."""
    def frame():
        q = grbl.pos + CAM_OFFSET
        a = math.radians(CAM_ROT)
        rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        rel = [rot @ (np.array([h["x"], h["y"]]) - q) for h in board_holes]
        holes = [{"x": r[0], "y": r[1], "d": h["d"]} for r, h in zip(rel, board_holes)
                 if abs(r[0]) < 10 and abs(r[1]) < 8]
        img, _ = render(holes, mm_per_px=MMPX, size=(1280, 960), origin_px=(640, 480), seed=len(holes))
        return img
    return frame


def board(design, rot_deg, shift):
    a = math.radians(rot_deg)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return [{"x": p[0], "y": p[1], "d": 1.0} for p in (np.asarray(design) @ R.T + shift)]


def test_fit_rigid_recovers_rotation_and_shift():
    d = np.array([[0, 0], [50, 0], [50, 30], [0, 30]], float)
    a = math.radians(1.2)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    m = d @ R.T + [3.0, -2.0]
    R2, t2, res = align.fit_rigid(d, m)
    assert abs(align.rotation_deg(R2) - 1.2) < 1e-9
    assert np.allclose(t2, [3.0, -2.0]) and res.max() < 1e-9


def test_head_camera_calibration_and_alignment():
    g = FakeGrbl()
    cal = Calibration.from_scale(MMPX, (1280, 960))
    # 1) calibration: one hole drilled at (10, 10) on a scrap board
    scrap = [{"x": 10.0, "y": 10.0, "d": 1.0}]
    M, c = align.calibrate_head_camera(g, camera(g, scrap), cal, (10.0, 10.0), (58.0, 0.0), z=10,
                                       log=lambda s: None)
    assert np.allclose(c, CAM_OFFSET, atol=0.02)
    # 2) a board placed 1.5° rotated and shifted; fiducials at two corners
    design = [(0, 0), (60, 0), (60, 40), (0, 40), (30, 20)]
    true_board = board(design, 1.5, np.array([2.0, -1.3]))
    R, t, res, _ = align.align_board(g, camera(g, true_board), cal, [(0, 0), (60, 40)], M, c, z=10,
                                     log=lambda s: None)
    assert abs(align.rotation_deg(R) - 1.5) < 0.03
    pred = align.apply(R, t, design)
    truth = np.array([[h["x"], h["y"]] for h in true_board])
    assert np.abs(pred - truth).max() < 0.03
