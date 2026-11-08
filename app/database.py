"""SQLite storage for sessions, holes and sensor samples.

Old layout: one table per session named "<id>SessionParamtersList", filled
only when the session ended by zipping the DAQ list and the motor list
together after trimming them to equal length (so rows did not line up in
time, and a crash lost the whole session).

New layout: three tables. Samples are written while the session runs
(committed once a second) and every row carries its own timestamp plus the
machine position at that moment. migrate_legacy() imports the old tables.
"""

import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    ended_at        TEXT,
    status          TEXT NOT NULL DEFAULT 'created',
    board_type      TEXT,
    board_thickness REAL,
    bit_diameter    REAL,
    hole_count      INTEGER,
    holes_text      TEXT,
    source          TEXT,
    notes           TEXT,
    params_json     TEXT
);
CREATE TABLE IF NOT EXISTS holes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    x           REAL NOT NULL,
    y           REAL NOT NULL,
    diameter    REAL,
    status      TEXT,
    done_at     REAL,
    measured_d  REAL,
    measured_dx REAL,
    measured_dy REAL,
    circularity REAL
);
CREATE TABLE IF NOT EXISTS samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t           REAL NOT NULL,          -- seconds since session start
    current_a   REAL,
    temp1_c     REAL,
    temp2_c     REAL,
    ax_g        REAL,
    ay_g        REAL,
    az_g        REAL,
    vib_g       REAL,
    load_pct    REAL,
    x           REAL,
    y           REAL,
    z           REAL,
    spindle     INTEGER,
    state       TEXT
);
CREATE INDEX IF NOT EXISTS samples_session ON samples(session_id, t);
CREATE INDEX IF NOT EXISTS holes_session ON holes(session_id, seq);
"""

SAMPLE_COLUMNS = ("t", "current_a", "temp1_c", "temp2_c", "ax_g", "ay_g", "az_g",
                  "vib_g", "load_pct", "x", "y", "z", "spindle", "state")


class Database:
    def __init__(self, path):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(samples)")}
            if "load_pct" not in cols:          # databases from before firmware 2.1
                self.conn.execute("ALTER TABLE samples ADD COLUMN load_pct REAL")
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.commit()
            self.conn.close()

    # ---------------------------------------------------------- sessions
    def create_session(self, name, board_type, board_thickness, bit_diameter,
                       holes, source, notes="", params_json=None):
        from .jobs import format_points_text
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO sessions (name, created_at, status, board_type, board_thickness,"
                " bit_diameter, hole_count, holes_text, source, notes, params_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (name, now, "running", board_type, board_thickness, bit_diameter,
                 len(holes), format_points_text(holes), source, notes, params_json))
            sid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO holes (session_id, seq, x, y, diameter, status) VALUES (?,?,?,?,?,?)",
                [(sid, i + 1, h.x, h.y, h.diameter, h.status) for i, h in enumerate(holes)])
            self.conn.commit()
        return sid

    def finish_session(self, sid, status):
        with self.lock:
            self.conn.execute("UPDATE sessions SET status=?, ended_at=? WHERE id=?",
                              (status, time.strftime("%Y-%m-%d %H:%M:%S"), sid))
            self.conn.commit()

    def update_hole(self, sid, seq, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE holes SET {cols} WHERE session_id=? AND seq=?",
                              (*fields.values(), sid, seq))
            self.conn.commit()

    def list_sessions(self):
        with self.lock:
            return self.conn.execute(
                "SELECT id, name, created_at, status, hole_count FROM sessions ORDER BY id"
            ).fetchall()

    def get_session(self, sid):
        with self.lock:
            cur = self.conn.execute("SELECT * FROM sessions WHERE id=?", (sid,))
            row = cur.fetchone()
            if row is None:
                return None
            return dict(zip([c[0] for c in cur.description], row))

    def get_holes(self, sid):
        with self.lock:
            cur = self.conn.execute("SELECT * FROM holes WHERE session_id=? ORDER BY seq", (sid,))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def get_samples(self, sid):
        with self.lock:
            rows = self.conn.execute(
                f"SELECT {', '.join(SAMPLE_COLUMNS)} FROM samples WHERE session_id=? ORDER BY t",
                (sid,)).fetchall()
        return {c: [r[i] for r in rows] for i, c in enumerate(SAMPLE_COLUMNS)}

    def delete_session(self, sid):
        with self.lock:
            self.conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.conn.commit()

    def add_samples(self, sid, rows):
        with self.lock:
            self.conn.executemany(
                f"INSERT INTO samples (session_id, {', '.join(SAMPLE_COLUMNS)})"
                f" VALUES (?{', ?' * len(SAMPLE_COLUMNS)})",
                [(sid, *r) for r in rows])
            self.conn.commit()

    # ---------------------------------------------------------- migration
    def migrate_legacy(self, legacy_path):
        """Import sessions from the old my_db.db layout. Returns count.
        The old readings had random noise added by the DAQ code, so imported
        sessions get status 'legacy' and a note saying so."""
        src = sqlite3.connect(legacy_path)
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "SessionsData" not in tables:
            src.close()
            return 0
        count = 0
        for row in src.execute(
                "SELECT SessionID, SessionName, DateAndTime, BoardType, BoardThickness,"
                " DrillBitDiameter, Tasksqty, TasksCmndLine, Source FROM SessionsData"):
            old_id, name, dt, btype, thick, dia, qty, cmd, source = row
            note = ("Imported from the old database. Current and temperature in these "
                    "sessions include random values the old DAQ code added; do not use "
                    "them for analysis.")
            with self.lock:
                cur = self.conn.execute(
                    "INSERT INTO sessions (name, created_at, status, board_type, board_thickness,"
                    " bit_diameter, hole_count, holes_text, source, notes)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (name, (dt or "").replace(";", " "), "legacy", btype, thick, dia, qty, cmd,
                     source, note))
                sid = cur.lastrowid
                table = f"{old_id}SessionParamtersList"
                if table in tables:
                    rows = src.execute(
                        f'SELECT timeList, insAMP, insTEMP, insTiltX, insTiltY, insTiltZ,'
                        f' Xpos, Ypos, Zpos, SPMstat FROM "{table}"').fetchall()
                    self.conn.executemany(
                        "INSERT INTO samples (session_id, t, current_a, temp1_c, ax_g, ay_g, az_g,"
                        " x, y, z, spindle, state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(sid, (r[0] or 0) / 1000.0, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8],
                          1 if r[9] else 0, "legacy") for r in rows])
                self.conn.commit()
            count += 1
        src.close()
        return count


class SampleLogger:
    """Collects one row per DAQ sample (or per status report if the DAQ is
    absent) during a session and writes them in batches."""

    def __init__(self, db, session_id, flush_every_s=1.0):
        self.db = db
        self.sid = session_id
        self.t0 = time.monotonic()
        self.flush_every = flush_every_s
        self._rows = []
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()
        self.count = 0

    def add(self, machine, daq_sample=None):
        """machine: grbl.MachineState (or dict from as_dict()); daq_sample: DaqSample or None."""
        m = machine.as_dict() if hasattr(machine, "as_dict") else machine
        x, y, z = m["wpos"]
        s = daq_sample
        row = (round(time.monotonic() - self.t0, 3),
               s.current if s else None, s.temp1 if s else None, s.temp2 if s else None,
               s.ax if s else None, s.ay if s else None, s.az if s else None,
               s.vib if s else None, s.load if s else None,
               round(x, 3), round(y, 3), round(z, 3), 1 if m["spindle_on"] else 0, m["state"])
        with self._lock:
            self._rows.append(row)
            self.count += 1
            due = time.monotonic() - self._last_flush >= self.flush_every
        if due:
            self.flush()

    def flush(self):
        with self._lock:
            rows, self._rows = self._rows, []
            self._last_flush = time.monotonic()
        if rows:
            self.db.add_samples(self.sid, rows)
