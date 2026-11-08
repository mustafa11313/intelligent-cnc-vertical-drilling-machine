"""Board alignment with a camera on the drilling head (fiducials).

The camera sits on the head yoke (cad/upgrade.py), ~58 mm in front of the
spindle, so it moves with the machine. Two calibrations tie it to the
spindle, then any job can be aligned to the real board:

1. calibrate_head_camera(): drill one hole, look at it from three camera
   positions. That gives
     M  2x2 map from image millimetres (vision.Calibration) to machine
        X/Y (handles camera rotation, mirrored image axes, small scale error)
     c  camera offset: the machine X/Y the image centre sees, minus the
        spindle X/Y at that moment.
2. align_board(): for each fiducial (a hole or pad whose design X/Y you
   know), move the camera over where it should be, measure where it is,
   then fit rotation + translation design -> machine and apply it to the
   job's holes. One fiducial gives translation only; two or more give
   rotation as well, and the residuals show how well they agree.

All coordinates are work coordinates (what jog_to() and the job use).
"""

import math

import numpy as np

from . import vision


class AlignError(Exception):
    pass


# ------------------------------------------------------------- image side
def circle_near_centre(image, calib, polarity="auto", min_d_mm=0.3, max_d_mm=8.0):
    """Vector (mm, image frame) from the image centre to the round feature
    nearest to it, plus that feature's diameter."""
    found = vision.find_holes(image, calib, min_d_mm=min_d_mm, max_d_mm=max_d_mm, polarity=polarity)
    if not found:
        raise AlignError("no round feature found in the camera image")
    h, w = image.shape[:2]
    centre = calib.px_to_mm([[w / 2.0, h / 2.0]])[0]
    best = min(found, key=lambda f: (f["x_mm"] - centre[0]) ** 2 + (f["y_mm"] - centre[1]) ** 2)
    return np.array([best["x_mm"] - centre[0], best["y_mm"] - centre[1]]), best["d_mm"]


# ------------------------------------------------------------- geometry
def solve_image_map(d_img_x, d_img_y, step):
    """M such that M @ image_vector = machine_vector, from the image shift of
    a fixed feature when the machine moved +step in X and then +step in Y
    (the feature moves the opposite way in the image)."""
    A = np.column_stack([d_img_x, d_img_y])               # image shifts
    B = -step * np.eye(2)                                  # machine moves they correspond to
    if abs(np.linalg.det(A)) < 1e-6 * step * step:
        raise AlignError("camera calibration moves gave parallel image shifts; check the camera")
    return B @ np.linalg.inv(A)


def fit_rigid(design, measured):
    """Rotation R (2x2) and translation t with measured ≈ R @ design + t.
    One point: translation only."""
    d = np.asarray(design, float).reshape(-1, 2)
    m = np.asarray(measured, float).reshape(-1, 2)
    if len(d) == 1:
        return np.eye(2), m[0] - d[0], np.zeros(1)
    cd, cm = d.mean(0), m.mean(0)
    U, _, Vt = np.linalg.svd((d - cd).T @ (m - cm))
    D = np.diag([1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
    R = Vt.T @ D @ U.T
    t = cm - R @ cd
    res = np.linalg.norm(d @ R.T + t - m, axis=1)
    return R, t, res


def apply(R, t, xy):
    return np.asarray(xy, float).reshape(-1, 2) @ np.asarray(R).T + np.asarray(t)


def rotation_deg(R):
    return math.degrees(math.atan2(R[1, 0], R[0, 0]))


# ------------------------------------------------------------- procedures
def _move_and_grab(grbl, xy, z, frame_fn, feed, z_feed, settle_s=0.3):
    import time
    grbl.jog_to(z=z, feed=z_feed)
    grbl.jog_to(x=float(xy[0]), y=float(xy[1]), feed=feed)
    if not grbl.wait_idle(timeout=60):
        raise AlignError("machine did not reach the camera position")
    time.sleep(settle_s)
    return frame_fn()


def calibrate_head_camera(grbl, frame_fn, calib, hole_xy, nominal_offset, z, step=3.0,
                          feed=600.0, z_feed=300.0, polarity="auto", log=print):
    """hole_xy: where a hole was just drilled (spindle position, work coords).
    nominal_offset: rough camera offset (dx, dy) from the CAD, to find it.
    Returns (M, c) for config camera.head_matrix / camera.head_offset_mm."""
    p0 = np.asarray(hole_xy, float) - np.asarray(nominal_offset, float)
    v0, _ = circle_near_centre(_move_and_grab(grbl, p0, z, frame_fn, feed, z_feed), calib, polarity)
    vx, _ = circle_near_centre(_move_and_grab(grbl, p0 + [step, 0], z, frame_fn, feed, z_feed), calib, polarity)
    vy, _ = circle_near_centre(_move_and_grab(grbl, p0 + [0, step], z, frame_fn, feed, z_feed), calib, polarity)
    M = solve_image_map(vx - v0, vy - v0, step)
    c = np.asarray(hole_xy, float) - p0 - M @ v0
    sx, sy = np.linalg.norm(M[:, 0]), np.linalg.norm(M[:, 1])
    log(f"Head camera: offset X{c[0]:+.3f} Y{c[1]:+.3f} mm, image axes rotated "
        f"{math.degrees(math.atan2(M[1, 0], M[0, 0])):.1f}°, scale {sx:.3f}/{sy:.3f}"
        f"{', mirrored' if np.linalg.det(M) < 0 else ''}")
    if not (0.8 < sx < 1.25 and 0.8 < sy < 1.25):
        log("Warning: scale far from 1. Recalibrate the camera at the head's focus height.")
    return M, c


def align_board(grbl, frame_fn, calib, fiducials, M, c, z, feed=600.0, z_feed=300.0,
                polarity="auto", log=print):
    """Measure each fiducial (design X/Y) and return (R, t, residuals, measured)."""
    M, c = np.asarray(M, float), np.asarray(c, float)
    R, t = np.eye(2), np.zeros(2)
    measured = []
    for i, d in enumerate(np.asarray(fiducials, float).reshape(-1, 2)):
        guess = apply(R, t, d)[0]
        cam_at = guess - c
        img = _move_and_grab(grbl, cam_at, z, frame_fn, feed, z_feed)
        v, dia = circle_near_centre(img, calib, polarity)
        m = cam_at + c + M @ v
        measured.append(m)
        log(f"Fiducial {i + 1} ({d[0]:.3f}, {d[1]:.3f}): found at ({m[0]:.3f}, {m[1]:.3f}), Ø{dia:.2f} mm")
        if len(measured) >= 1:                       # refine the guess for the next fiducial
            R, t, _ = fit_rigid(np.asarray(fiducials, float).reshape(-1, 2)[:len(measured)], measured)
    R, t, res = fit_rigid(fiducials, measured)
    return R, t, res, np.array(measured)
