import os
import time

import numpy as np

from app import analysis, jobs
from app.daq import DaqSample
from app.database import Database, SampleLogger

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_session_roundtrip(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    holes = [jobs.Hole(1.5, 2.25), jobs.Hole(3, 4)]
    sid = db.create_session("s", "FR4", 1.6, 1.0, holes, "test")
    log = SampleLogger(db, sid, flush_every_s=0)
    m = {"state": "Run", "wpos": (1.5, 2.25, -1.0), "spindle_on": True}
    log.add(m, DaqSample(0, 10, 1.2, 30.0, None, 0, 0, 1, 0.05))
    log.add(m, None)
    log.flush()
    db.update_hole(sid, 1, status="Done", measured_d=1.02)
    db.finish_session(sid, "completed")
    s = db.get_samples(sid)
    assert s["current_a"] == [1.2, None] and s["temp2_c"] == [None, None]
    assert s["x"] == [1.5, 1.5]
    assert db.get_holes(sid)[0]["measured_d"] == 1.02
    assert db.get_session(sid)["status"] == "completed"
    db.delete_session(sid)
    assert db.get_samples(sid)["t"] == []


def test_legacy_migration(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    n = db.migrate_legacy(os.path.join(DATA, "legacy_my_db.db"))
    assert n >= 10
    sessions = db.list_sessions()
    assert all(r[3] == "legacy" for r in sessions)
    sid = sessions[-1][0]
    assert len(db.get_samples(sid)["t"]) > 0


def test_fit_prefers_simple_model():
    t = np.linspace(0, 100, 200)
    rng = np.random.default_rng(0)
    y = 0.05 * t + 20 + rng.normal(0, 0.2, t.size)
    fit = analysis.fit_trend(list(t), list(y))
    assert fit["degree"] == 1
    assert abs(fit["coeffs"][0] - 0.05) < 0.005


def test_fit_handles_missing_values():
    t = [0, 1, 2, 3, 4, 5]
    y = [1.0, None, 3.0, float("nan"), 5.0, 6.0]
    fit = analysis.fit_trend(t, y)
    assert fit is not None
    assert analysis.stats(y)["n"] == 4
