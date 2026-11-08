"""Hole inspection with a calibrated camera.

The old code ran HoughCircles and converted pixels to mm assuming 96 DPI,
which is a screen convention and has nothing to do with the camera, so the
diameters it printed were not real millimetres.

Here:
  * Calibration maps image pixels to millimetres on the board plane.
    Best: a printed checkerboard (fixes lens distortion and perspective).
    Quick: a scale factor from a reference of known size.
  * Holes are found as contours (not Hough), and diameter comes from the
    contour area mapped into mm, which is sub-pixel accurate and does not
    depend on Hough's radius quantisation.
  * Positions are compared to the drilled pattern after a best-fit
    alignment, so the result does not depend on where the board sits
    under the camera.
"""

import json
import math

import cv2
import numpy as np


class Calibration:
    def __init__(self, camera_matrix=None, dist_coeffs=None, homography=None,
                 image_size=None, method="none", rms_px=None):
        self.camera_matrix = camera_matrix
        self.dist_coeffs = dist_coeffs
        self.homography = homography if homography is not None else np.eye(3)
        self.image_size = image_size
        self.method = method
        self.rms_px = rms_px

    @property
    def valid(self):
        return self.method != "none"

    @property
    def mm_per_px(self):
        """Average scale at the image centre (for display only)."""
        if self.image_size:
            cx, cy = self.image_size[0] / 2, self.image_size[1] / 2
        else:
            cx, cy = 0.0, 0.0
        p = self.px_to_mm(np.array([[cx, cy], [cx + 1, cy], [cx, cy + 1]], dtype=np.float64))
        return float((np.linalg.norm(p[1] - p[0]) + np.linalg.norm(p[2] - p[0])) / 2)

    # ---------------------------------------------------------------- build
    @classmethod
    def from_scale(cls, mm_per_px, image_size=None):
        H = np.diag([mm_per_px, mm_per_px, 1.0])
        return cls(homography=H, image_size=image_size, method="scale")

    @classmethod
    def from_reference_circle(cls, image, known_diameter_mm, polarity="auto"):
        """Scale-only calibration from one circular feature of known size
        (for example a gauge pin or a hole measured with calipers)."""
        tmp = cls.from_scale(1.0, image_size=(image.shape[1], image.shape[0]))
        found = find_holes(image, tmp, min_d_mm=5, max_d_mm=max(image.shape) / 2, polarity=polarity)
        if not found:
            raise ValueError("No circular feature found in the reference image")
        best = max(found, key=lambda h: h["circularity"])
        return cls.from_scale(known_diameter_mm / best["d_mm"],
                              image_size=(image.shape[1], image.shape[0]))

    @classmethod
    def from_checkerboard(cls, images, pattern=(9, 6), square_mm=5.0):
        """images: list of BGR/gray images of a checkerboard. The LAST one
        must show the board lying flat on the work plane where the PCB goes;
        it defines the pixel->mm mapping. pattern = inner corners (cols, rows)."""
        objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square_mm
        obj_pts, img_pts = [], []
        size = None
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
        last_corners = None
        for img in images:
            gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            size = (gray.shape[1], gray.shape[0])
            ok, corners = cv2.findChessboardCorners(gray, pattern)
            if not ok:
                continue
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), crit)
            obj_pts.append(objp)
            img_pts.append(corners)
            last_corners = corners
        if not img_pts:
            raise ValueError("Checkerboard not found in any image")
        if len(img_pts) >= 3:
            rms, K, dist, _, _ = cv2.calibrateCamera(obj_pts, img_pts, size, None, None)
        else:
            K, dist, rms = None, None, None    # too few views for lens model
        # Plane mapping from the last view, in undistorted pixel coordinates
        pts = last_corners.reshape(-1, 2).astype(np.float64)
        if K is not None:
            pts = cv2.undistortPoints(pts.reshape(-1, 1, 2), K, dist, P=K).reshape(-1, 2)
        H, _ = cv2.findHomography(pts, objp[:, :2].astype(np.float64))
        return cls(K, dist, H, size, "checkerboard", rms)

    # ---------------------------------------------------------------- use
    def undistort_points(self, pts):
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        if self.camera_matrix is None:
            return pts
        return cv2.undistortPoints(pts.reshape(-1, 1, 2), self.camera_matrix,
                                   self.dist_coeffs, P=self.camera_matrix).reshape(-1, 2)

    def px_to_mm(self, pts):
        pts = self.undistort_points(pts)
        return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), self.homography).reshape(-1, 2)

    # ---------------------------------------------------------------- io
    def save(self, path):
        d = {
            "method": self.method,
            "image_size": self.image_size,
            "rms_px": self.rms_px,
            "homography": np.asarray(self.homography).tolist(),
            "camera_matrix": None if self.camera_matrix is None else np.asarray(self.camera_matrix).tolist(),
            "dist_coeffs": None if self.dist_coeffs is None else np.asarray(self.dist_coeffs).tolist(),
        }
        with open(path, "w") as f:
            json.dump(d, f, indent=2)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            d = json.load(f)
        arr = lambda v: None if v is None else np.array(v, dtype=np.float64)
        return cls(arr(d.get("camera_matrix")), arr(d.get("dist_coeffs")),
                   arr(d["homography"]), tuple(d["image_size"]) if d.get("image_size") else None,
                   d.get("method", "scale"), d.get("rms_px"))


def _binarize(gray, polarity):
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    if polarity == "dark":
        _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(bw, cv2.MORPH_OPEN, k)


def _polygon_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def find_holes(image, calib, min_d_mm=0.3, max_d_mm=8.0, polarity="auto", min_circularity=0.6):
    """Return holes as dicts: x_mm, y_mm, d_mm, circularity, cx_px, cy_px, r_px.
    polarity: 'dark' (holes darker than board, front light), 'bright'
    (backlit), or 'auto' (tries both, keeps the set with more round blobs)."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if polarity == "auto":
        a = find_holes(gray, calib, min_d_mm, max_d_mm, "dark", min_circularity)
        b = find_holes(gray, calib, min_d_mm, max_d_mm, "bright", min_circularity)
        return a if len(a) >= len(b) else b
    bw = _binarize(gray, polarity)
    contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    h, w = gray.shape[:2]
    out = []
    for c in contours:
        if len(c) < 8:
            continue
        x, y, cw, ch = cv2.boundingRect(c)
        if x <= 1 or y <= 1 or x + cw >= w - 1 or y + ch >= h - 1:
            continue                       # cut by the image edge
        area_px = cv2.contourArea(c)
        perim_px = cv2.arcLength(c, True)
        if area_px < 12 or perim_px <= 0:
            continue
        circ = 4 * math.pi * area_px / perim_px ** 2
        if circ < min_circularity:
            continue
        pts_mm = calib.px_to_mm(c.reshape(-1, 2))
        area_mm = _polygon_area(pts_mm)
        # Pixel-edge contours sit half a pixel inside the true edge on average;
        # add that back (in mm) so small holes are not measured undersize.
        half_px_mm = 0.5 * calib.mm_per_px if calib.valid else 0.0
        d_mm = 2 * math.sqrt(area_mm / math.pi) + 2 * half_px_mm * 0.5
        if not (min_d_mm <= d_mm <= max_d_mm):
            continue
        m = cv2.moments(c)
        cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        cmm = calib.px_to_mm([[cx, cy]])[0]
        out.append({"x_mm": float(cmm[0]), "y_mm": float(cmm[1]), "d_mm": float(d_mm),
                    "circularity": float(min(circ, 1.0)), "cx_px": float(cx), "cy_px": float(cy),
                    "r_px": float(math.sqrt(area_px / math.pi))})
    return out


def _fit_rigid(src, dst, allow_mirror=True):
    """Least-squares rotation+translation mapping src->dst (Kabsch). If
    allow_mirror, also tries a Y flip (camera images have Y pointing down)."""
    best = None
    for flip in ((1.0,) if not allow_mirror else (1.0, -1.0)):
        s = src * np.array([1.0, flip])
        cs, cd = s.mean(0), dst.mean(0)
        U, _, Vt = np.linalg.svd((s - cs).T @ (dst - cd))
        R = (U @ Vt).T
        if np.linalg.det(R) < 0:
            Vt[-1] *= -1
            R = (U @ Vt).T
        t = cd - cs @ R.T
        res = np.linalg.norm(s @ R.T + t - dst, axis=1)
        if best is None or res.mean() < best[3].mean():
            best = (R, t, flip, res)
    return best


def compare_to_expected(found, expected_xy, nominal_d=None, pos_tol=0.1, d_tol=0.1):
    """Match found holes to the expected pattern and report errors.

    expected_xy: list of (x, y) in work mm. Returns (results, summary).
    Each result: index, found (bool), dx, dy, err, d_mm, d_err, circularity, ok.
    The pattern is aligned by best-fit rotation/translation first, so a board
    that sits shifted or slightly rotated under the camera does not count as error;
    what remains is the hole-to-hole position error the machine made."""
    exp = np.asarray(expected_xy, dtype=np.float64).reshape(-1, 2)
    results = []
    if len(found) == 0 or len(exp) == 0:
        for i in range(len(exp)):
            results.append({"index": i, "found": False, "ok": False})
        return results, {"found": 0, "expected": len(exp), "passed": 0}
    got = np.array([[h["x_mm"], h["y_mm"]] for h in found])
    # Initial alignment: centroids, then iterate nearest-neighbour + Kabsch
    pairs = None
    R, t, flip = np.eye(2), exp.mean(0) - got.mean(0), 1.0
    best = None
    for flip0 in (1.0, -1.0):
        g = got * np.array([1.0, flip0])
        R, t = np.eye(2), exp.mean(0) - g.mean(0)
        for _ in range(10):
            mapped = g @ R.T + t
            d = np.linalg.norm(exp[:, None, :] - mapped[None, :, :], axis=2)
            nn = d.argmin(1)
            ok = d[np.arange(len(exp)), nn] < max(2.0, 5 * pos_tol)
            if ok.sum() < 2:
                break
            Rn, tn, _, _ = _fit_rigid(g[nn[ok]], exp[ok], allow_mirror=False)
            R, t = Rn, tn
        mapped = g @ R.T + t
        d = np.linalg.norm(exp[:, None, :] - mapped[None, :, :], axis=2)
        nn = d.argmin(1)
        score = np.minimum(d[np.arange(len(exp)), nn], 5.0).sum()
        if best is None or score < best[0]:
            best = (score, mapped, nn, d)
    _, mapped, nn, d = best
    used = set()
    passed = 0
    for i, (ex, j) in enumerate(zip(exp, nn)):
        dist = d[i, j]
        if dist > max(2.0, 5 * pos_tol) or j in used:
            results.append({"index": i, "found": False, "ok": False})
            continue
        used.add(j)
        dx, dy = mapped[j] - ex
        h = found[j]
        d_err = None if nominal_d is None else h["d_mm"] - nominal_d
        ok_ = dist <= pos_tol and (d_err is None or abs(d_err) <= d_tol)
        passed += ok_
        results.append({"index": i, "found": True, "dx": float(dx), "dy": float(dy),
                        "err": float(dist), "d_mm": h["d_mm"], "d_err": d_err,
                        "circularity": h["circularity"], "ok": bool(ok_), "found_index": int(j)})
    errs = [r["err"] for r in results if r["found"]]
    summary = {"found": sum(r["found"] for r in results), "expected": len(exp), "passed": passed,
               "max_pos_err": max(errs) if errs else None,
               "mean_pos_err": float(np.mean(errs)) if errs else None}
    return results, summary


def annotate(image, found, results=None):
    out = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    status = {}
    if results:
        for r in results:
            if r.get("found"):
                status[r["found_index"]] = (r["ok"], r["index"])
    for j, h in enumerate(found):
        ok, idx = status.get(j, (None, None))
        color = (0, 200, 0) if ok else ((0, 0, 255) if ok is False else (255, 160, 0))
        c = (int(round(h["cx_px"])), int(round(h["cy_px"])))
        cv2.circle(out, c, int(round(h["r_px"])), color, 2)
        cv2.drawMarker(out, c, color, cv2.MARKER_CROSS, 8, 1)
        label = f"#{idx + 1} " if idx is not None else ""
        cv2.putText(out, f"{label}{h['d_mm']:.2f}", (c[0] + int(h["r_px"]) + 3, c[1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return out


def open_camera(device):
    """device: int index or '/dev/videoN'. Uses V4L2 on Linux (the old code
    used CAP_DSHOW, which only exists on Windows)."""
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap = cv2.VideoCapture(device)
    return cap


def grab_frame(device, warmup=5, width=None, height=None):
    cap = open_camera(device)
    try:
        if not cap.isOpened():
            raise IOError(f"Cannot open camera {device}")
        if width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        frame = None
        for _ in range(max(1, warmup)):       # auto-exposure settles over a few frames
            ok, frame = cap.read()
        if frame is None:
            raise IOError("Camera returned no frame")
        return frame
    finally:
        cap.release()
