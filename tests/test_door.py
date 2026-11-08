"""Cover door interlock (safety door on GRBL A1), against the simulator.

Opening the door drops K1 in hardware and puts GRBL in its Door state. The app
must stop the job, flush what GRBL still holds, refuse to start with the door
open, and forget the homed state if an axis was moving when power was cut.
"""
import time

import pytest

from app import jobs
from app.grbl import GrblError
from app.session import SessionRunner
from sim.loopback import connect_client

HOMING = {20: 1, 21: 1, 22: 1, 23: 0, 24: 25, 25: 500, 26: 250, 27: 1.0}


def wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def homed():
    g, ser = connect_client(settings=HOMING, time_scale=20.0)
    msgs = []
    g.on_message = msgs.append
    g.home()
    g.send("G90 G0 X-120 Y-80 Z-20")
    assert g.wait_idle(timeout=20)
    g.set_work_zero()
    assert g.wait_idle()
    yield g, ser, msgs
    g.close()


def test_door_open_while_idle_keeps_position(homed):
    g, ser, msgs = homed
    ser.sim.set_door(True)
    assert wait(lambda: g.state.substate == "Door:1")
    assert g.door_open and g.homed                     # nothing was moving
    assert any(m.startswith("DOOR") for m in msgs)
    assert "D" in g.state.pins or wait(lambda: "D" in g.state.pins)
    with pytest.raises(GrblError):
        g.door_resume()                                 # still open
    ser.sim.set_door(False)
    assert wait(lambda: g.state.substate == "Door:0")
    g.door_resume()
    assert wait(lambda: g.state.state == "Idle")
    assert g.homed


def test_door_open_during_job_stops_it_and_needs_homing(homed):
    g, ser, msgs = homed
    holes = [jobs.Hole(x * 8.0, 0.0) for x in range(6)]
    p = jobs.DrillParams(board_thickness=1.6, breakthrough=0.4, spinup_s=0.5, plunge_feed=300)
    result = {}
    r = SessionRunner(g, holes, p, on_finished=lambda res, msg: result.update(res=res, msg=msg),
                      require_homed=True)
    g.on_ack = r.handle_ack
    g.on_reset = r.handle_reset

    def on_msg(m):
        msgs.append(m)
        if m.startswith("DOOR"):
            r.handle_door(m)
    g.on_message = on_msg
    r.start()
    assert wait(lambda: r.done_count >= 1, timeout=30)
    assert wait(lambda: ser.sim.snapshot()["moving"], timeout=10)
    ser.sim.set_door(True)
    assert wait(lambda: not r.active, timeout=10)
    assert result["res"] == "aborted" and "door" in result["msg"].lower()
    assert not g.homed                                   # motors lost power while moving
    drilled = len(ser.sim.drilled)
    assert drilled < len(holes)
    assert not ser.sim.spindle
    # Closing the door must not restart the rest of the program
    ser.sim.set_door(False)
    time.sleep(0.5)
    assert not ser.sim.planner and ser.sim.current is None
    assert len(ser.sim.drilled) == drilled
    # A new job is refused until the machine is cleared and homed again
    r2 = SessionRunner(g, [jobs.Hole(0, 0)], p, require_homed=True)
    with pytest.raises(RuntimeError):
        r2.start()
    g.soft_reset()
    time.sleep(0.3)
    g.home()
    assert g.homed and g.state.state == "Idle"


def test_door_opened_during_homing_fails_homing():
    g, ser = connect_client(settings=HOMING, time_scale=2.0)
    try:
        assert wait(lambda: g.state.state == "Alarm")
        g.send("$H")
        assert wait(lambda: g.state.state == "Home")
        ser.sim.set_door(True)
        assert wait(lambda: g.state.state == "Alarm")
        assert "ALARM 7" in (g._last_alarm or "")
        assert not g.homed
    finally:
        g.close()


def test_start_refused_with_door_open(homed):
    g, ser, _ = homed
    ser.sim.set_door(True)
    assert wait(lambda: g.state.state == "Door")
    r = SessionRunner(g, [jobs.Hole(0, 0)], jobs.DrillParams(board_thickness=1.6))
    with pytest.raises(RuntimeError, match="door"):
        r.start()
    with pytest.raises(GrblError):
        g.send("G0 X1")
        g.wait_idle(timeout=2)
