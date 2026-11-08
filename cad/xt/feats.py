"""List holes/shafts (cylinders) and horizontal faces of named parts, in world mm.

    python3 feats.py <file.x_t> "X Eksen Somunu" "300x250" ...
"""
import os
import sys

import numpy as np

from model import Model

m = Model.load(sys.argv[1], cache=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".xt_cache.pkl"))
L = m.leaves()
want = sys.argv[2:]
seen = set()
for inst in L:
    n = inst.path.split('/')[-1]
    if not any(w in n for w in want) or n in seen: continue
    seen.add(n)
    b = inst.body
    print(f"== {inst.path}  world box {np.round(inst.bbox()[0],1)} {np.round(inst.bbox()[1],1)}")
    cyl = {}
    for p, a, r in b.cylinders:
        P = inst.world([p])[0]; A = inst.T[:3,:3] @ a
        A = A / np.linalg.norm(A); A = A * np.sign(A[np.argmax(abs(A))])
        # project point onto plane perpendicular to axis to dedupe
        Pp = P - (P @ A) * A
        k = (round(2*r,2), tuple(np.round(A,2)), tuple(np.round(Pp,1)))
        cyl[k] = cyl.get(k, 0) + 1
    for (d, A, Pp), c in sorted(cyl.items()):
        print(f"   Ø{d:6.2f} axis {tuple(float(a) for a in A)} through {tuple(float(p) for p in Pp)}")
    hs = sorted({round(float(inst.world([p])[0] @ (inst.T[:3,:3]@nn)),1) for p, nn in b.planes if abs((inst.T[:3,:3]@nn)[1])>0.99})
    print("   horizontal planes at y:", [round(abs(h),1) for h in hs][:20])
