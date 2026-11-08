import numpy as np
import pytest

from app.vision import Calibration, compare_to_expected, find_holes
from sim.camera_sim import checkerboard, render


@pytest.mark.parametrize("d", [0.6, 0.8, 1.0, 2.0])
def test_diameter_accuracy(d):
    holes = [{"x": x * 4.0, "y": y * 4.0, "d": d} for x in range(3) for y in range(3)]
    img, _ = render(holes, mm_per_px=0.025, rotation_deg=2.0, seed=1)
    cal = Calibration.from_scale(0.025, (img.shape[1], img.shape[0]))
    found = find_holes(img, cal)
    assert len(found) == 9
    res, summary = compare_to_expected(found, [(h["x"], h["y"]) for h in holes], nominal_d=d)
    assert summary["passed"] == 9
    assert summary["max_pos_err"] < 0.02
    assert max(abs(r["d_err"]) for r in res) < 0.03


def test_detects_misplaced_hole():
    holes = [{"x": x * 5.0, "y": y * 5.0, "d": 1.0} for x in range(3) for y in range(3)]
    expected = [(h["x"], h["y"]) for h in holes]
    holes[4] = {"x": 5.25, "y": 5.0, "d": 1.0}       # drilled 0.25 mm off
    img, _ = render(holes, mm_per_px=0.025, seed=2)
    cal = Calibration.from_scale(0.025)
    res, summary = compare_to_expected(find_holes(img, cal), expected, 1.0, pos_tol=0.1)
    bad = [r["index"] for r in res if not r["ok"]]
    assert bad == [4]


def test_detects_missing_hole():
    holes = [{"x": x * 5.0, "y": 0.0, "d": 1.0} for x in range(5)]
    expected = [(h["x"], h["y"]) for h in holes]
    img, _ = render(holes[:2] + holes[3:], mm_per_px=0.025, seed=3)
    res, summary = compare_to_expected(find_holes(img, Calibration.from_scale(0.025)), expected, 1.0)
    assert summary["found"] == 4
    assert [r["index"] for r in res if not r["found"]] == [2]


def test_checkerboard_calibration(tmp_path):
    img = checkerboard(9, 6, 5.0, mm_per_px=0.05)
    cal = Calibration.from_checkerboard([img], (9, 6), 5.0)
    assert cal.mm_per_px == pytest.approx(0.05, rel=0.01)
    p = tmp_path / "cal.json"
    cal.save(p)
    cal2 = Calibration.load(p)
    pts = np.array([[100.0, 200.0], [640.0, 480.0]])
    assert np.allclose(cal.px_to_mm(pts), cal2.px_to_mm(pts))


def test_reference_circle_calibration():
    img, _ = render([{"x": 0, "y": 0, "d": 6.0}], mm_per_px=0.04, seed=4)
    cal = Calibration.from_reference_circle(img, 6.0)
    assert cal.mm_per_px == pytest.approx(0.04, rel=0.01)
