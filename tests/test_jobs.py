import os

import pytest

from app import jobs

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_parse_keeps_decimals():
    holes = jobs.parse_points_text("(3.2,5.7);(4.1,1.1);(-9.95,0.5)")
    assert [(h.x, h.y) for h in holes] == [(3.2, 5.7), (4.1, 1.1), (-9.95, 0.5)]


def test_parse_forgiving_formats():
    holes = jobs.parse_points_text("1,2\n 3.5 , 4.25 ;(5 6)")
    assert [(h.x, h.y) for h in holes] == [(1, 2), (3.5, 4.25), (5, 6)]


def test_parse_reports_bad_chunk():
    with pytest.raises(ValueError, match="abc"):
        jobs.parse_points_text("(1,2);(abc)")


def test_dxf_points_not_truncated():
    holes = jobs.read_dxf(os.path.join(DATA, "test2.DXF"))
    xs = sorted({h.x for h in holes})
    assert 1.1 in xs and 2.1 in xs           # old code turned 1.1 into 1


def test_dxf_negative_coordinates():
    holes = jobs.read_dxf(os.path.join(DATA, "Spicemen.DXF"))
    assert len(holes) == 4
    assert min(h.y for h in holes) == -60.0


def test_dxf_circles(tmp_path):
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_circle((10, 20), 0.4)       # 0.8 mm hole
    msp.add_circle((30, 20), 0.5)
    msp.add_circle((50, 50), 40)        # board outline, ignored
    p = tmp_path / "c.dxf"
    doc.saveas(p)
    holes = jobs.read_dxf(str(p))
    assert [(h.x, h.y, h.diameter) for h in holes] == [(10, 20, 0.8), (30, 20, 1.0)]


def test_dxf_inches(tmp_path):
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 1
    doc.modelspace().add_point((1, 2))
    p = tmp_path / "in.dxf"
    doc.saveas(p)
    h = jobs.read_dxf(str(p))[0]
    assert (h.x, h.y) == (25.4, 50.8)


def test_merge_unique():
    a = [jobs.Hole(1, 1)]
    merged, skipped = jobs.merge_unique(a, [jobs.Hole(1.001, 1), jobs.Hole(2, 2)])
    assert len(merged) == 2 and skipped == 1


def test_order_shortens_route():
    import random
    rng = random.Random(4)
    holes = [jobs.Hole(rng.uniform(0, 100), rng.uniform(0, 80)) for _ in range(60)]
    before = jobs.route_length(holes)
    ordered = jobs.order_holes(holes)
    assert sorted(id(h) for h in ordered) == sorted(id(h) for h in holes)
    assert jobs.route_length(ordered) < 0.6 * before


def test_program_structure():
    holes = [jobs.Hole(10, 10), jobs.Hole(20.25, 5.5)]
    p = jobs.DrillParams(board_thickness=1.6, breakthrough=0.4, approach_offset=0.5)
    prog = jobs.generate_program(holes, p)
    lines = [l for l, _ in prog]
    assert lines[0].startswith("G21 G90")
    assert "M3 S12000" in lines
    assert "G0 X9.5 Y9.5" in lines and "G1 X10 Y10 F300" in lines
    assert "G1 Z-2 F60" in lines
    tags = [t for _, t in prog if t]
    assert tags == [("hole_done", 0), ("hole_done", 1), ("program_done",)]
    assert all(len(l) < 127 for l in lines)
    # spindle off before parking
    assert lines.index("M5", 2) < lines.index("G0 X0 Y0")


def test_peck_program():
    p = jobs.DrillParams(board_thickness=1.6, breakthrough=0.4, peck_depth=0.8, approach_offset=0)
    lines = [l for l, _ in jobs.generate_program([jobs.Hole(0, 0)], p)]
    assert [l for l in lines if l.startswith("G1 Z")] == ["G1 Z-0.8 F60", "G1 Z-1.6 F60", "G1 Z-2 F60"]


def test_check_job():
    p = jobs.DrillParams()
    assert jobs.check_job([], (200, 150, 60), p) == ["No holes in the job"]
    assert jobs.check_job([jobs.Hole(0, 0), jobs.Hole(100, 100)], (200, 150, 60), p) == []
    probs = jobs.check_job([jobs.Hole(0, 0), jobs.Hole(250, 0)], (200, 150, 60), p)
    assert any("X" in s for s in probs)
