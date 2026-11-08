import time

import pytest

from app.grbl import GrblError, parse_status
from sim.loopback import connect_client


def test_parse_status():
    st = parse_status("<Run|MPos:1.000,-2.500,0.000|FS:500,12000|WCO:1.0,1.0,0.0|A:SF>")
    assert st["state"] == "Run" and st["MPos"] == (1.0, -2.5, 0.0)
    assert st["feed"] == 500 and st["spindle_speed"] == 12000
    assert st["accessories"] == "SF"
    assert parse_status("<Hold:0|MPos:0,0,0|FS:0,0>")["substate"] == "Hold:0"
    assert parse_status("ok") is None


@pytest.fixture
def grbl():
    g, ser = connect_client()
    yield g, ser
    g.close()


def test_banner_and_settings(grbl):
    g, _ = grbl
    assert g.version.startswith("Grbl 1.1")
    s = g.read_settings()
    assert s[100] == 800 and s[110] == 1000


def test_write_settings_only_changes(grbl):
    g, ser = grbl
    changed = g.write_settings({100: 800, 101: 1600})
    assert changed == [101]
    assert ser.sim.settings[101] == 1600


def test_streaming_long_program_never_overflows(grbl):
    g, ser = grbl
    acks = []
    g.on_ack = lambda tag, ok, code: acks.append((tag, ok))
    lines = [(f"G1 X{i % 7 * 0.5:.1f} Y{i % 5 * 0.5:.1f} F3000", i) for i in range(200)]
    g.send("G21 G90")
    g.send_many(lines)
    assert g.wait_idle(timeout=30)
    assert ser.sim.overflows == 0
    assert [t for t, ok in acks if t is not None] == list(range(200))
    assert all(ok for _, ok in acks)


def test_work_zero_and_wpos(grbl):
    g, ser = grbl
    g.send("G0 X12 Y7")
    g.wait_idle(10)
    g.set_work_zero()
    g.send("G0 X1 Y1")
    assert g.wait_idle(10)
    time.sleep(0.4)
    assert g.state.mpos == pytest.approx((13, 8, 0), abs=1e-3)
    assert g.state.wpos == pytest.approx((1, 1, 0), abs=1e-3)


def test_error_reported(grbl):
    g, _ = grbl
    acks = []
    g.on_ack = lambda tag, ok, code: acks.append((tag, ok, code))
    g.send("G1 X5", tag="nofeed")          # no feed rate set yet
    g.send("G99", tag="bad")
    time.sleep(0.3)
    assert ("nofeed", False, 22) in acks
    assert ("bad", False, 20) in acks


def test_jog_and_cancel(grbl):
    g, ser = grbl
    g.jog(dx=50, feed=200)
    time.sleep(0.3)
    assert g.state.state == "Jog"
    g.jog_cancel()
    time.sleep(0.3)
    assert g.state.state == "Idle"
    assert 0 < g.state.mpos[0] < 50


def test_soft_reset_while_moving_alarms(grbl):
    g, _ = grbl
    resets = []
    g.on_reset = lambda: resets.append(1)
    g.send("G1 X100 F500")
    time.sleep(0.3)
    g.soft_reset()
    time.sleep(0.3)
    assert resets and g.state.state == "Alarm"
    with pytest.raises(GrblError):
        g.query("G0 X1")          # locked out
    g.unlock()
    time.sleep(0.4)
    assert g.state.state == "Idle"


def test_query(grbl):
    g, _ = grbl
    lines = g.query("$#")
    assert lines[0].startswith("[G54:")
