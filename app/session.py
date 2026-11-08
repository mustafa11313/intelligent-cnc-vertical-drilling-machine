"""Running a drilling session on the machine.

Replaces the old Processing.SSNManagerFunction loop, which emitted one
target at a time and spun in a while-loop with processEvents(). Here the
whole program is generated up front and streamed to GRBL; progress comes
back through the acknowledgements of the 'G4' sync lines after each hole.

No Qt in this module so it can be tested headless against the simulator.
"""

import threading
import time

from .jobs import generate_program


class SessionRunner:
    IDLE, RUNNING, PAUSED, STOPPING, FINISHED = "idle", "running", "paused", "stopping", "finished"

    def __init__(self, grbl, holes, params, on_hole=None, on_finished=None, on_log=None,
                 require_homed=False):
        """on_hole(index, status) with status 'Drilling' or 'Done'.
        on_finished(result, message) with result 'completed', 'cancelled',
        'aborted' or 'failed'."""
        self.grbl = grbl
        self.holes = holes
        self.params = params
        self.on_hole = on_hole
        self.on_finished = on_finished
        self.on_log = on_log
        self.require_homed = require_homed
        self.state = self.IDLE
        self.done_count = 0
        self.started_at = None
        self.finished_at = None
        self.result = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- control
    def start(self):
        g = self.grbl
        if not g.connected:
            raise RuntimeError("Motion controller not connected")
        if g.state.state == "Alarm":
            raise RuntimeError("Machine is in ALARM. Unlock it and check the work zero first")
        if g.state.state == "Door":
            raise RuntimeError("The cover door is open. Close it, press Start on the electrical box, "
                               "then 'Unlock alarm' on the System tab")
        if self.require_homed and not g.homed:
            raise RuntimeError("Home the machine first (System tab, 'Home machine')")
        if g.state.state not in ("Idle",):
            raise RuntimeError(f"Machine must be Idle to start (now {g.state.state})")
        if not self.holes:
            raise RuntimeError("No holes to drill")
        program = generate_program(self.holes, self.params)
        self.state = self.RUNNING
        self.started_at = time.time()
        self._log(f"Session started: {len(self.holes)} holes, {len(program)} lines")
        self._hole_status(0, "Drilling")
        g.send_many(program)

    def pause(self):
        if self.state == self.RUNNING:
            self.grbl.feed_hold()
            self.state = self.PAUSED
            self._log("Paused (feed hold). Spindle keeps running")

    def resume(self):
        if self.state == self.PAUSED:
            self.grbl.cycle_start()
            self.state = self.RUNNING
            self._log("Resumed")

    def cancel(self):
        """Controlled stop: hold, wait for the axes to stop, reset (keeps
        position because nothing is moving), spindle off, raise Z."""
        if self.state not in (self.RUNNING, self.PAUSED):
            return
        self.state = self.STOPPING
        self._log("Cancelling: stopping motion")
        threading.Thread(target=self._cancel_worker, daemon=True).start()

    def _cancel_worker(self):
        g = self.grbl
        g.clear_queue()
        g.feed_hold()
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if g.state.substate in ("Hold:0", "Idle"):
                break
            time.sleep(0.05)
        self._expect_reset = True
        g.soft_reset()                  # flushes GRBL's buffers, spindle off
        time.sleep(0.5)
        if g.state.state == "Alarm":
            g.unlock()
        g.send("M5")
        g.send(f"G90 G0 Z{self.params.safe_z:.3f}")
        self._finish("cancelled", f"Cancelled after {self.done_count} of {len(self.holes)} holes")

    def emergency_stop(self):
        """Immediate soft reset. Motion stops without deceleration, so GRBL
        will flag ALARM 3 and the work zero must be checked before continuing.
        This does not replace a hardware E-stop that cuts motor and spindle power."""
        self._expect_reset = True
        self.grbl.soft_reset()
        if self.state in (self.RUNNING, self.PAUSED, self.STOPPING):
            self._finish("aborted", "EMERGENCY STOP. Check the tool, then unlock and re-zero")

    # ------------------------------------------------------ events from GRBL
    _expect_reset = False

    def handle_ack(self, tag, ok, code):
        if self.state not in (self.RUNNING, self.PAUSED):
            return
        if not ok:
            self.grbl.soft_reset()
            self._finish("failed", f"GRBL rejected a line (error {code}). Session stopped")
            return
        if not tag:
            return
        if tag[0] == "hole_done":
            i = tag[1]
            self.done_count = i + 1
            self._hole_status(i, "Done")
            if i + 1 < len(self.holes):
                self._hole_status(i + 1, "Drilling")
        elif tag[0] == "program_done":
            self._finish("completed", f"All {len(self.holes)} holes drilled")

    def handle_reset(self):
        if self._expect_reset:
            self._expect_reset = False
            return
        if self.state in (self.RUNNING, self.PAUSED, self.STOPPING):
            self._finish("aborted", "Motion controller reset unexpectedly (power or USB?)")

    def handle_alarm(self, text):
        if self.state in (self.RUNNING, self.PAUSED):
            self._finish("aborted", text)

    def handle_door(self, text):
        """Cover door opened: K1 has already cut spindle and motor power in hardware.
        The job cannot carry on, so flush what GRBL still holds (otherwise a cycle
        start after closing the door would run the rest of the program)."""
        if self.state not in (self.RUNNING, self.PAUSED, self.STOPPING):
            return
        self._expect_reset = True
        self.grbl.soft_reset()
        self._finish("aborted", f"Cover door opened: job stopped after {self.done_count} of "
                                f"{len(self.holes)} holes. Close the door, press Start, home the machine, "
                                "then check the work zero")

    def handle_disconnect(self, reason):
        if self.state in (self.RUNNING, self.PAUSED, self.STOPPING):
            self._finish("aborted", f"Lost connection to the motion controller: {reason}")

    # --------------------------------------------------------------- helpers
    @property
    def active(self):
        return self.state in (self.RUNNING, self.PAUSED, self.STOPPING)

    @property
    def progress(self):
        return 100.0 * self.done_count / len(self.holes) if self.holes else 0.0

    def _finish(self, result, message):
        with self._lock:
            if self.state == self.FINISHED:
                return
            self.state = self.FINISHED
        self.result = result
        self.finished_at = time.time()
        self._log(message)
        if self.on_finished:
            self.on_finished(result, message)

    def _hole_status(self, i, status):
        self.holes[i].status = status
        if self.on_hole:
            self.on_hole(i, status)

    def _log(self, msg):
        if self.on_log:
            self.on_log(msg)
