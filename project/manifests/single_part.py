# SPDX-License-Identifier: MPL-2.0
"""Phase-2 verify fixture: a single part with all label kinds populated."""
from mk.kb import connect, kb_part


def build_m6_cap(p):
    from build123d import Cylinder, Pos, Compound  # noqa: F401  (resolved at exec time)
    head = Pos(0, 0, p["l"]) * Cylinder(p["d"], 4)
    shaft = Cylinder(p["d"] / 2, p["l"])
    return Compound([shaft, head])


with connect():
    with kb_part("part_m6_cap_20mm", description="ISO 4762 M6 cap screw, 20mm") as p:
        p.param("d", 6, type="float")
        p.param("l", 20, type="float")
        p.joint("head", origin=[0, 0, 20], z_dir=[0, 0, 1])
        p.joint("thread_tip", origin=[0, 0, 0], z_dir=[0, 0, -1])
        p.meta("density", 7.85)
        p.meta("material", "steel")
        p.builder(build_m6_cap)
