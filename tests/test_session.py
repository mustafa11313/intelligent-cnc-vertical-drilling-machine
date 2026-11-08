"""End-to-end drilling against the simulated machine, including backlash."""

import math
import time

import pytest

from app import jobs
from app.session import SessionRunner
from sim.loopback import connect_client

GRID = [(x * 7.5, y * 6.0) for x in range(4) for y in range(3)]


def run_job(holes_xy, backlash=0.0, approach=0.5, scale=40.0, before_start=None, during=None):
    g, ser = connect_client(time_scale=scale, backlash=(backlash, backlash, 0.0))
    try:
        g.set_work_zero()
        g.wait_idle(5)
        holes = [jobs.Hole(x, y) for x, y in holes_xy]
        p = jobs.DrillParams(board_thickness=1.6, breakthrough=0.4, spinup_s=0.5,
                             approach_offset=approach, plunge_feed=300)
        events, result = [], {}
        r = SessionRunner(g, holes, p, on_hole=lambda i, s: events.append((i, s)),
                          on_finished=lambda res, msg: result.update(res=res, msg=msg))
        g.on_ack = r.handle_ack
        g.on_reset = r.handle_reset
        if before_start:
            before_start(g)
        r.start()
        t0 = time.time()
        while r.active and time.time() - t0 < 60:
            if during:
                during(r, g, events)
            time.sleep(0.02)
        return r, events, result, ser.sim
    finally:
        time.sleep(0.2)
        g.close()


def test_complete_job():
    r, events, result, sim = run_job(GRID)
    assert result["res"] == "completed"
    assert [i for i, s in events if s == "Done"] == list(range(len(GRID)))
    assert len(sim.drilled) == len(GRID)
    for (x, y), d in zip(GRID, sim.drilled):
        assert d["x"] == pytest.approx(x, abs=1e-3) and d["y"] == pytest.approx(y, abs=1e-3)
        assert d["depth"] == pytest.approx(2.0, abs=1e-3)
    assert not sim.spindle                 # spindle off at the end
    assert sim.overflows == 0


def spread(sim, expected):
    """Hole-to-hole position error after removing the common offset."""
    dx = [d["x"] - x for d, (x, y) in zip(sim.drilled, expected)]
    dy = [d["y"] - y for d, (x, y) in zip(sim.drilled, expected)]
    mx, my = sum(dx) / len(dx), sum(dy) / len(dy)
    return max(math.hypot(a - mx, b - my) for a, b in zip(dx, dy))


def test_backlash_without_unidirectional_approach_scatters_holes():
    order = jobs.order_holes([jobs.Hole(x, y) for x, y in GRID])
    xy = [(h.x, h.y) for h in order]
    _, _, result, sim = run_job(xy, backlash=0.2, approach=0.0)
    assert result["res"] == "completed"
    assert spread(sim, xy) > 0.1           # holes land on both sides of the play


def test_unidirectional_approach_cancels_backlash():
    order = jobs.order_holes([jobs.Hole(x, y) for x, y in GRID])
    xy = [(h.x, h.y) for h in order]
    _, _, result, sim = run_job(xy, backlash=0.2, approach=0.5)
    assert result["res"] == "completed"
    assert spread(sim, xy) < 0.005         # same error on every hole: pattern is exact


def test_pause_and_resume():
    state = {"paused": False, "resumed": False}

    def during(r, g, events):
        if not state["paused"] and any(s == "Done" for _, s in events):
            r.pause()
            state["paused"] = True
            state["t"] = time.time()
            state["pos"] = g.state.mpos
        elif state["paused"] and not state["resumed"] and time.time() - state["t"] > 0.5:
            state["held_still"] = g.state.mpos == state["pos"] or g.state.substate.startswith("Hold")
            r.resume()
            state["resumed"] = True

    r, events, result, sim = run_job(GRID[:4], during=during)
    assert state["resumed"] and state["held_still"]
    assert result["res"] == "completed" and len(sim.drilled) == 4


def test_cancel_stops_and_lifts():
    def during(r, g, events):
        if r.state == r.RUNNING and any(s == "Done" for _, s in events):
            r.cancel()

    r, events, result, sim = run_job(GRID, during=during)
    time.sleep(0.1)
    assert result["res"] == "cancelled"
    assert 1 <= len(sim.drilled) < len(GRID)
    assert not sim.spindle


def test_emergency_stop():
    def during(r, g, events):
        if r.state == r.RUNNING and g.state.state == "Run" and any(s == "Done" for _, s in events):
            r.emergency_stop()

    r, events, result, sim = run_job(GRID, during=during)
    assert result["res"] == "aborted"
    assert not sim.spindle


def test_refuses_to_start_in_alarm():
    g, ser = connect_client()
    try:
        g.send("G1 X50 F300")
        time.sleep(0.2)
        g.soft_reset()
        time.sleep(0.3)
        r = SessionRunner(g, [jobs.Hole(0, 0)], jobs.DrillParams())
        with pytest.raises(RuntimeError, match="ALARM"):
            r.start()
    finally:
        g.close()
