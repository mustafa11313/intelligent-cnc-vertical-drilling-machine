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
def feature_near_centre(image, calib, polarity="auto", min_d_mm=0.3, max_d_mm=8.0):
    """(vector, feature): vector (mm, image frame) from the image centre to the
    round feature nearest to it, and that feature as vision.find_holes gives it."""
    found = vision.find_holes(image, calib, min_d_mm=min_d_mm, max_d_mm=max_d_mm, polarity=polarity)
    if not found:
        raise AlignError("no round feature found in the camera image")
    h, w = image.shape[:2]
    centre = calib.px_to_mm([[w / 2.0, h / 2.0]])[0]
    best = min(found, key=lambda f: (f["x_mm"] - centre[0]) ** 2 + (f["y_mm"] - centre[1]) ** 2)
    return np.array([best["x_mm"] - centre[0], best["y_mm"] - centre[1]]), best


def circle_near_centre(image, calib, polarity="auto", min_d_mm=0.3, max_d_mm=8.0):
    """Vector (mm, image frame) from the image centre to the round feature
    nearest to it, plus that feature's diameter."""
    v, f = feature_near_centre(image, calib, polarity, min_d_mm, max_d_mm)
    return v, f["d_mm"]


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


def _feature_near(image, calib, target, polarity, max_jump):
    """Image vector to the round feature nearest to `target` (image mm from the centre)."""
    found = vision.find_holes(image, calib, polarity=polarity)
    h, w = image.shape[:2]
    centre = calib.px_to_mm([[w / 2.0, h / 2.0]])[0]
    vs = [np.array([f["x_mm"] - centre[0], f["y_mm"] - centre[1]]) for f in found]
    if not vs:
        raise AlignError("no round feature found in the camera image")
    v = min(vs, key=lambda q: np.linalg.norm(q - target))
    if np.linalg.norm(v - target) > max_jump:
        raise AlignError("lost the test hole while moving the camera; is the image in focus?")
    return v


def calibrate_head_camera(grbl, frame_fn, calib, hole_xy, nominal_offset, z, step=1.0,
                          feed=600.0, z_feed=300.0, polarity="auto", log=print):
    """hole_xy: where a hole was just drilled (spindle position, work coords).
    nominal_offset: rough camera offset (dx, dy) from the CAD, to find it.
    The camera is moved only `step` mm between pictures, so the same hole is
    followed even when other holes of a dense pattern are in view.
    Returns (M, c) for config camera.head_matrix / camera.head_offset_mm."""
    p0 = np.asarray(hole_xy, float) - np.asarray(nominal_offset, float)
    v0, _ = circle_near_centre(_move_and_grab(grbl, p0, z, frame_fn, feed, z_feed), calib, polarity)
    jump = 1.6 * step
    vx = _feature_near(_move_and_grab(grbl, p0 + [step, 0], z, frame_fn, feed, z_feed), calib, v0, polarity, jump)
    vy = _feature_near(_move_and_grab(grbl, p0 + [0, step], z, frame_fn, feed, z_feed), calib, v0, polarity, jump)
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


# ------------------------------------------------------------- quality check
def inspect_holes(grbl, frame_fn, calib, expected_xy, M, c, z, nominal_d=None, pos_tol=0.1,
                  d_tol=0.1, feed=600.0, z_feed=300.0, polarity="auto", search_mm=None,
                  log=print, should_stop=None, tile_px=240):
    """Quality check after drilling: move the head camera over every hole of the
    job, measure where the hole really is and how big it is, and compare it with
    the drawing.

    expected_xy: the job's hole positions in work coordinates, i.e. the drawing
    as placed on this board (after fiducial alignment, if it was used).
    Returns (results, summary, mosaic) in the same form as
    vision.compare_to_expected, plus 'x', 'y' (measured) per hole, and a BGR
    picture with one annotated tile per hole (green ok, red out of tolerance).

    Unlike a single photo of the whole board, every hole is seen close up in the
    middle of the image, where the lens distorts least, and positions are
    measured in machine coordinates. So the result is the real error against the
    drawing, not only hole-to-hole error."""
    import cv2

    M, c = np.asarray(M, float), np.asarray(c, float)
    scale = math.sqrt(abs(np.linalg.det(M)))               # image mm -> machine mm
    search = search_mm if search_mm is not None else max(1.0, 5 * pos_tol)
    exp = np.asarray(expected_xy, float).reshape(-1, 2)
    results, tiles = [], []
    for i, xy in enumerate(exp):
        if should_stop and should_stop():
            log("Quality check stopped")
            break
        cam_at = xy - c
        img = _move_and_grab(grbl, cam_at, z, frame_fn, feed, z_feed)
        r = {"index": i, "found": False, "ok": False}
        feat = None
        try:
            v, feat = feature_near_centre(img, calib, polarity)
            m = cam_at + c + M @ v
            dx, dy = m - xy
            err = math.hypot(dx, dy)
            if err > search:
                feat = None                                  # nearest hole is a neighbour: this one is missing
            else:
                d = feat["d_mm"] * scale
                d_err = None if nominal_d is None else d - nominal_d
                ok = err <= pos_tol and (d_err is None or abs(d_err) <= d_tol)
                r = {"index": i, "found": True, "x": float(m[0]), "y": float(m[1]),
                     "dx": float(dx), "dy": float(dy), "err": float(err), "d_mm": float(d),
                     "d_err": d_err, "circularity": feat["circularity"], "ok": bool(ok)}
        except AlignError:
            pass
        if r["found"]:
            log(f"Hole {i + 1}: {'OK ' if r['ok'] else 'BAD'} error {r['err']:.3f} mm "
                f"(dX {r['dx']:+.3f}, dY {r['dy']:+.3f}), Ø{r['d_mm']:.3f}")
        else:
            log(f"Hole {i + 1}: NOT FOUND near ({xy[0]:.3f}, {xy[1]:.3f})")
        results.append(r)
        tiles.append(_tile(img, feat, r, tile_px))
    errs = [r["err"] for r in results if r["found"]]
    summary = {"found": sum(r["found"] for r in results), "expected": len(exp),
               "passed": sum(r["ok"] for r in results),
               "max_pos_err": max(errs) if errs else None,
               "mean_pos_err": float(np.mean(errs)) if errs else None,
               "method": "head camera, hole by hole"}
    # How much of the error is the board/drawing placement (one shift + rotation for all
    # holes), and how much is the machine (what is left hole to hole).
    got = [(r["x"], r["y"]) for r in results if r["found"]]
    want = [tuple(exp[r["index"]]) for r in results if r["found"]]
    if len(got) >= 3:
        R, t, res = fit_rigid(want, got)
        summary.update(pattern_shift=(float(t[0]), float(t[1])), pattern_rot_deg=rotation_deg(R),
                       max_hole_to_hole_err=float(res.max()))
    return results, summary, _mosaic(tiles, tile_px)


def _tile(img, feat, r, size):
    import cv2
    h, w = img.shape[:2]
    if feat is not None:
        cx, cy = feat["cx_px"], feat["cy_px"]
        span = max(size, int(6 * feat["r_px"]))
    else:
        cx, cy, span = w / 2.0, h / 2.0, max(size, min(w, h) // 3)
    x0 = int(min(max(cx - span / 2, 0), max(w - span, 0)))
    y0 = int(min(max(cy - span / 2, 0), max(h - span, 0)))
    crop = img[y0:y0 + span, x0:x0 + span].copy()
    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    colour = (0, 190, 0) if r["ok"] else (0, 0, 230)
    if feat is not None:
        cv2.circle(crop, (int(round(cx - x0)), int(round(cy - y0))), int(round(feat["r_px"])), colour, 2,
                   cv2.LINE_AA)
    tile = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    cv2.rectangle(tile, (0, 0), (size - 1, size - 1), colour, 3)
    cv2.line(tile, (size // 2 - 8, size // 2), (size // 2 + 8, size // 2), (255, 160, 0), 1)
    cv2.line(tile, (size // 2, size // 2 - 8), (size // 2, size // 2 + 8), (255, 160, 0), 1)
    label = f"#{r['index'] + 1} " + (f"{r['err']:.3f} mm  D{r['d_mm']:.2f}" if r["found"] else "missing")
    cv2.rectangle(tile, (3, 3), (size - 4, 24), (255, 255, 255), -1)
    cv2.putText(tile, label, (7, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
    return tile


def _mosaic(tiles, size):
    if not tiles:
        return None
    cols = min(len(tiles), max(1, int(math.ceil(math.sqrt(len(tiles) * 4 / 3)))))
    rows = int(math.ceil(len(tiles) / cols))
    out = np.full((rows * size, cols * size, 3), 235, np.uint8)
    for k, t in enumerate(tiles):
        r, q = divmod(k, cols)
        out[r * size:(r + 1) * size, q * size:(q + 1) * size] = t
    return out
