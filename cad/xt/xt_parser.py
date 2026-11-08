"""Reader for Parasolid transmit files in text format (.x_t).

SolidWorks, NX, Solid Edge and Onshape all export this format, but no open
source tool reads it, so this module decodes it directly. It covers the parts of the format
an assembly of prismatic parts uses: assembly/instance/transform
structure, topology (body, shell, face, loop, fin, edge, vertex), the
analytic surfaces and curves (plane, cylinder, cone, sphere, torus, line,
circle, ellipse), B-spline curves and surfaces, attributes (names,
colours), and the embedded-schema mechanism that newer Parasolid versions
use to describe changed node layouts.

Field layouts were reverse-engineered from the file itself plus the
public XT format notes, and the parse is self-checking: every node must
end exactly where the next node's type code starts, otherwise it stops
with the position and context.
"""

import re

# ---------------------------------------------------------------- field kinds
#   n  number or pointer (followed by a space), or '?' for null
#   c  single character (sense '+'/'-', logical 'T'/'F'), no space after
#   v  vector: '?' or 3 numbers
#   m  3x3 matrix: '?' or 9 numbers
#   i  interval: '?' or 2 numbers
#   b  box: '?' or 6 numbers

CURVE = "nnnnnnc"            # node_id attribs owner next prev geometric_owner sense
SURF = "nnnnnnc"

BASE = {
    10: "n" * 17,                     # ASSEMBLY (replaced by embedded schema in practice)
    11: "n" * 10,                     # INSTANCE
    13: "n" * 9,                      # SHELL
    14: "n" * 8 + "c" + "n" * 5,      # FACE: id attr tol next prev loop shell surf sense ...
    15: "n" * 5,                      # LOOP: id attr fin face next
    16: "n" * 10,                     # EDGE
    17: "n" * 9 + "c",                # FIN: ... sense
    18: "n" * 8,                      # VERTEX
    19: "nnnnnnc",                    # REGION: ... type (S solid / V void)
    80: ["n", "n", "n", "n" * 8, "n", "c" * 14, ""],  # ATTRIB_DEF: next ident type actions[8] ? legal_owners[14] fields[]
    74: ["n", "n", ""],
    38: ["n"] * 6 + ["c", "nn", "n", "n", "n"],  # INTERSECTION: CURVE surface[2] chart start end
    41: ["c", ""],                    # LIMIT: type, hvec[]
    40: ["n"] * 5 + ["nn", ""],       # CHART: base_param base_scale count chordal angular param_err[2], hvec[]
    124: CURVE + "nn",                # B_CURVE-like: nurbs, data
    134: CURVE + "nn",                # B_CURVE: nurbs, data
    137: CURVE + "nnnn",              # SP_CURVE: surface b_curve original tolerance
    136: "nnnnnccc" + "nnnn",         # NURBS_CURVE: degree n_vert dim n_knots knot_type periodic closed rational form vertices mult knots
    135: "nn",                        # CURVE_DATA
    126: "cc" + "n" * 8 + "ccc" + "nn" + "nnnnn",  # NURBS_SURF
    125: "iiii" + "n" + "c" * 9 + "n" * 7,          # SURFACE_DATA
    133: CURVE + "nvvnn",             # TRIMMED_CURVE: basis point1 point2 parm1 parm2
    67: SURF + "nvn",                 # SWEPT_SURF: section sweep scale
    141: "nnnn",
    163: "vvcnnnnn",                  # HELIX surface data
    184: "vvvcnnnn",                  # HELIX curve data: axis point, axis dir, start, hand, turns, pitch, tol
    100: "nnnnmvnnv",                 # TRANSFORM: id owner next prev R t scale flag persp
    29: "nnnnnv",                     # POINT
    30: CURVE + "vv",                 # LINE: pvec direction
    31: CURVE + "vvvn",               # CIRCLE: centre normal x_axis radius
    32: CURVE + "vvvnn",              # ELLIPSE
    50: SURF + "vvv",                 # PLANE: pvec normal x_axis
    51: SURF + "vvnv",                # CYLINDER: pvec axis radius x_axis
    52: SURF + "vvnnnv",              # CONE
    53: SURF + "vnvv",                # SPHERE
    54: SURF + "vvnnv",               # TORUS
}

# Variable-length nodes: (fixed field kinds, kind of each repeated element)
VARIABLE = {
    82: ("", "n"),                    # INT_VALUES
    83: ("", "n"),                    # REAL_VALUES
    84: ("", "s"),                    # CHAR_VALUES (raw characters)
    79: ("", "s"),                    # ATTRIB_DEF identifier string
    98: ("", "n"),
    85: ("", "n"),                    # POINTER_VALUES
    86: ("", "v"),                    # VECTOR_VALUES
    87: ("", "vv"),                   # AXIS_VALUES
    88: ("", "v"),                    # DIRECTION_VALUES
    40: ("nnnnnnn", "v"),             # CHART
    41: ("c", "v"),                   # LIMIT                    # unicode string as char codes
    45: ("", "n"),                    # BSPLINE_VERTICES
    127: ("", "n"),                   # KNOT_MULT
    128: ("", "n"),                   # KNOT_SET
    74: ("nn", "n"),                  # POINTER_LIS_BLOCK: n_entries next_block, entries[]
    81: ("nnnnnnn", "n"),             # ATTRIBUTE
    80: ("", "n"),                    # ATTRIB_DEF (fixed part from BASE / schema)
}


class XTError(Exception):
    pass


class Reader:
    def __init__(self, text, base=None, variable=None):
        self.s = text
        self.p = 0
        self.base = dict(BASE)
        if base:
            self.base.update(base)
        self.variable = dict(VARIABLE)
        if variable:
            self.variable.update(variable)
        self.schema = {}              # type -> field kinds (after embedded edits)
        self.names = {}               # type -> field names from embedded edits
        self.nodes = {}               # index -> (type, fields)
        self.order = []

    # ---------------------------------------------------------- primitives
    def ctx(self, back=120, fwd=200):
        return self.s[max(0, self.p - back):self.p] + " <<HERE>> " + self.s[self.p:self.p + fwd]

    def num(self):
        s = self.s
        if s[self.p] == "?":
            self.p += 1
            return None
        j = s.index(" ", self.p)
        tok = s[self.p:j]
        self.p = j + 1
        try:
            if re.fullmatch(r"[-+]?\d+", tok):
                return int(tok)
            return float(tok)
        except ValueError:
            raise XTError(f"bad number {tok!r}: {self.ctx()}")

    def char(self):
        c = self.s[self.p]
        self.p += 1
        return c

    def vec(self, n):
        if self.s[self.p] == "?":
            self.p += 1
            return None
        return tuple(self.num() for _ in range(n))

    def field(self, kind):
        if kind == "n":
            return self.num()
        if kind == "c":
            return self.char()
        if kind == "v":
            return self.vec(3)
        if kind == "m":
            return self.vec(9)
        if kind == "i":
            return self.vec(2)
        if kind == "b":
            return self.vec(6)
        raise XTError("unknown kind " + kind)

    # ------------------------------------------------------ embedded schema
    def read_schema_edits(self, t, nfields):
        base = self.base.get(t) or "n" * 80     # unknown base: assume numeric fields
        base = list(base)                        # one entry per field (arrays are multi-kind)
        kinds, names = [], []
        bi = 0
        while True:
            op = self.char()
            if op == "Z":
                break
            if op == "C":
                if base is None:
                    raise XTError(f"type {t}: copy from unknown base field {bi}: {self.ctx()}")
                kinds.append(base[bi])
                names.append(f"base{bi}")
                bi += 1
            elif op == "D":
                bi += 1
            elif op in "IA":
                ln = self.num()
                name = self.s[self.p:self.p + ln]
                self.p += ln
                pc = self.num()
                x = self.num()
                if pc == 0:
                    self.num()               # element size / flag
                    tchar = self.char()
                    kind = {"l": "c", "c": "c", "v": "v", "i": "i", "b": "b"}.get(tchar, "n")
                    kind = kind * max(x or 1, 1)
                else:
                    kind = "n"
                kinds.append(kind)
                names.append(name)
            else:
                raise XTError(f"bad schema op {op!r}: {self.ctx()}")
        if len(kinds) != nfields:
            raise XTError(f"type {t}: schema gives {len(kinds)} fields, header says {nfields}")
        self.schema[t] = "".join(kinds)
        self.names[t] = names

    def read_new_type(self, t, nfields):
        """A node type the base schema does not have: name, description, then
        each field as <len><name><ptr_class> <n_elts> <?> <type char>, then a
        logical saying whether the last field is variable-length."""
        def string():
            ln = self.num()
            v = self.s[self.p:self.p + ln]
            self.p += ln
            return v
        tname, _desc = string(), string()
        kinds, names = [], []
        for _ in range(nfields):
            name = string()
            pc = self.num()
            x = self.num()
            if pc == 0:
                self.num()
                tchar = self.char()
                kind = {"l": "c", "c": "c", "v": "v", "i": "i", "b": "b"}.get(tchar, "n")
            else:
                kind = "n"
            kinds.append(kind * (x if x and x > 1 else 1))
            names.append(name)
        variable = self.char() == "T"
        if variable:
            self.variable[t] = ("".join(kinds[:-1]), kinds[-1])
        self.schema[t] = "".join(kinds[:-1] if variable else kinds)
        self.names[t] = [tname] + names

    # --------------------------------------------------------------- nodes
    def node(self):
        t = self.num()
        if t == 1:                         # terminator
            return False
        if t not in self.schema:
            # first occurrence: field count, or 255 = same as base schema
            nf = self.num()
            if nf == 255:
                if t in self.variable:
                    self.schema[t] = self.variable[t][0]
                elif t in self.base:
                    self.schema[t] = "".join(self.base[t])
                else:
                    self.schema[t] = self.learn(t)
            elif self.s[self.p].isdigit():
                self.read_new_type(t, nf)
            else:
                self.read_schema_edits(t, nf)
        if t in self.variable:
            n = self.num()
            idx = self.num()
            fixed = [self.field(k) for k in self.schema[t]]
            elem = self.variable[t][1]
            if elem == "s":
                data = self.s[self.p:self.p + n]
                self.p += n
            else:
                data = [self.field(elem) if len(elem) == 1 else [self.field(k) for k in elem]
                        for _ in range(n)]
            self.nodes[idx] = (t, fixed, data)
        else:
            idx = self.num()
            fields = [self.field(k) for k in self.schema[t]]
            self.nodes[idx] = (t, fields, None)
        self.order.append(idx)
        return True

    def learn(self, t):
        """Unknown layout: find the number of numeric fields that makes this
        node and the following ones parse cleanly."""
        here = self.p
        cands = [("n" * k) + tail for k in range(0, 60) for tail in ("", "c")]
        for lay in cands:
            self.p = here
            saved = (dict(self.schema), dict(self.nodes), list(self.order))
            self.schema[t] = lay
            ok = True
            try:
                idx = self.num()
                for k in lay:
                    if k == "c" and self.s[self.p] in "0123456789 .":
                        raise XTError("x")
                    self.field(k)
                if not self.s[self.p].isdigit():
                    raise XTError("x")
                for _ in range(6):
                    if not self.node():
                        break
                    if not self.s[self.p].isdigit():
                        raise XTError("x")
            except Exception:
                ok = False
            self.schema, self.nodes, self.order = saved
            if ok:
                self.p = here
                self.learned[t] = lay
                return lay
        self.p = here
        raise XTError(f"could not learn layout of type {t}: {self.ctx()}")

    learned = {}

    def parse(self, start):
        self.p = start
        n = 0
        while self.p < len(self.s) - 1:
            q = self.p
            try:
                if not self.node():
                    break
            except (XTError, IndexError, ValueError, TypeError) as e:
                self.p = q
                raise XTError(f"after {n} nodes, at {q}: {e}\n{self.ctx()}")
            if self.p < len(self.s) and not self.s[self.p].isdigit():
                bad = self.p
                self.p = q
                raise XTError(f"node {n} (type {self.s[q:q+4]}) did not end on a node start "
                              f"(char {self.s[bad]!r}):\n{self.ctx(60, 400)}")
            n += 1
        return n


def load_text(path):
    raw = open(path, encoding="latin1", newline="").read()
    body = raw.split("**END_OF_HEADER", 1)[1]
    body = body.split("\n", 1)[1]
    return "".join(body.replace("\r", "").split("\n"))


def find_start(s):
    """Data starts after 'SCH_..._<base>' and two header numbers."""
    m = re.search(r"SCH_\d+_\d+_\d{5}", s)
    return m.end()
