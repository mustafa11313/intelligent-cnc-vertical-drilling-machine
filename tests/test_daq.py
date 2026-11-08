import math

from app.daq import format_line, parse_line


def test_roundtrip():
    line = format_line(1234, 1.25, 31.5, None, 0.01, -0.02, 0.998, 0.05)
    s = parse_line(line, now=0)
    assert s.ms == 1234 and s.current == 1.25 and s.temp1 == 31.5
    assert s.temp2 is None                     # missing sensor stays missing
    assert abs(s.tilt_deg - math.degrees(math.acos(0.998 / math.sqrt(0.01**2 + 0.02**2 + 0.998**2)))) < 1e-6


def test_bad_checksum_rejected():
    line = format_line(1, 1.0, 20.0, 20.0, 0, 0, 1, 0)
    corrupted = line.replace("1.000", "7.000", 1)
    assert parse_line(corrupted) is None


def test_garbage_rejected():
    for junk in ("", "hello", "D,1,2,3*00", "#DAQ,CNC-DAQ,1.0", "D,1,a,b,c,d,e,f,g*00"):
        assert parse_line(junk) is None


def test_no_random_in_app():
    """The app must never invent sensor data."""
    import pathlib
    app = pathlib.Path(__file__).resolve().parents[1] / "app"
    import re
    for f in app.glob("*.py"):
        code = re.sub(r'"""[\s\S]*?"""', "", f.read_text())      # ignore docstrings
        assert not re.search(r"^\s*(import random|from random)", code, re.M), f.name
        assert "np.random" not in code and "numpy.random" not in code, f.name


def test_load_field_and_old_firmware_lines():
    s = parse_line(format_line(10, 3.0, 30.0, None, 0, 0, 1, 0.02, 50.0), now=0)
    assert s.load == 50.0 and s.current == 3.0
    # Firmware 2.0 had no load field: still accepted, load unknown
    body = "D,10,3.000,30.00,nan,0.0000,0.0000,1.0000,0.0200"
    from app.daq import checksum
    old = parse_line(f"{body}*{checksum(body)}", now=0)
    assert old is not None and old.load is None and old.vib == 0.02


def test_old_database_gets_load_column(tmp_path):
    import sqlite3

    from app.database import SAMPLE_COLUMNS, Database
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY, session_id INTEGER, t REAL, current_a REAL,"
              " temp1_c REAL, temp2_c REAL, ax_g REAL, ay_g REAL, az_g REAL, vib_g REAL, x REAL, y REAL,"
              " z REAL, spindle INTEGER, state TEXT)")
    c.commit()
    c.close()
    db = Database(str(path))
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(samples)")}
    assert set(SAMPLE_COLUMNS) <= cols
    db.close()
