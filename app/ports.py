"""Find which serial port is the GRBL board and which is the DAQ board.

The old SerialManagerFunction opened every port, waited forever for a byte,
and treated anything that was not 'A' or 'M' as the DAQ. Here each port is
opened once, we wait up to a few seconds for its banner ('Grbl ...' or
'#DAQ'), and unknown devices are left alone.

On Ubuntu, CH340-based Nanos show up as /dev/ttyUSB*. If they never appear,
remove brltty (sudo apt remove brltty): it grabs CH340 devices on 22.04.
Your user must be in the 'dialout' group: sudo usermod -aG dialout $USER
"""

import glob
import time

import serial
import serial.tools.list_ports


def candidate_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*"):
        for p in glob.glob(pattern):
            if p not in ports:
                ports.append(p)
    return sorted(ports)


def identify(port, baud=115200, timeout=3.5):
    """Return 'grbl', 'daq' or None."""
    try:
        s = serial.Serial(port, baud, timeout=0.1)
    except (serial.SerialException, OSError):
        return None
    try:
        end = time.monotonic() + timeout
        buf = b""
        poked = False
        while time.monotonic() < end:
            buf += s.read(256)
            text = buf.decode("ascii", errors="replace")
            if "Grbl" in text:
                return "grbl"
            if "#DAQ" in text or "\nD," in text or text.startswith("D,"):
                return "daq"
            if not poked and time.monotonic() > end - timeout / 2:
                # No banner yet (board did not reset on open): ask.
                s.write(b"\x18")          # GRBL soft reset -> banner
                s.write(b"I\n")           # DAQ identity request
                poked = True
        return None
    finally:
        s.close()


def discover(baud=115200, exclude=()):
    """Return {'grbl': port or None, 'daq': port or None}."""
    found = {"grbl": None, "daq": None}
    for p in candidate_ports():
        if p in exclude:
            continue
        kind = identify(p, baud)
        if kind and not found[kind]:
            found[kind] = p
        if all(found.values()):
            break
    return found
