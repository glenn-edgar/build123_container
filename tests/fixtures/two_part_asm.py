# SPDX-License-Identifier: MPL-2.0
"""Phase-2 verify fixture: two parts + a flat assembly with one mate."""
from mk.kb import connect, kb_asm, kb_part


def build_m6_cap(p):
    from build123d import Cylinder, Pos, Compound  # noqa: F401
    head = Pos(0, 0, p["l"]) * Cylinder(p["d"], 4)
    shaft = Cylinder(p["d"] / 2, p["l"])
    return Compound([shaft, head])


def build_simple_l(p):
    from build123d import Box, Pos, Cylinder, Rotation  # noqa: F401
    base = Box(p["w"], p["t"], p["h"])
    flange = Pos(0, p["w"] / 2, -p["h"] / 2 + p["t"] / 2) * Box(p["w"], p["w"], p["t"])
    body = base + flange
    # Mounting hole through the base in the Y-axis direction at (x=0, z=0).
    # Cylinder default axis is Z; rotate -90 around X so it lies along Y.
    hole = Rotation(-90, 0, 0) * Cylinder(p["hole_d"] / 2, p["t"] * 4)
    return body - hole


with connect():
    with kb_part("part_m6_cap_20mm", description="M6 cap screw, 20mm") as p:
        p.param("d", 6, type="float")
        p.param("l", 20, type="float")
        p.joint("head", origin=[0, 0, 20], z_dir=[0, 0, 1])
        p.joint("thread_tip", origin=[0, 0, 0], z_dir=[0, 0, -1])
        p.meta("density", 7.85)
        p.builder(build_m6_cap)

    with kb_part("part_simple_l", description="Simple L-bracket with mount hole") as p:
        p.param("w", 30, type="float")
        p.param("h", 30, type="float")
        p.param("t", 3, type="float")
        p.param("hole_d", 7, type="float")
        p.joint("mount_face", origin=[0, 15, 0], z_dir=[0, 1, 0])
        p.joint("hole_top", origin=[0, -15, 0], z_dir=[0, 1, 0])
        p.meta("density", 7.85)
        p.builder(build_simple_l)

    with kb_asm("asm_demo", description="Demo: bracket + bolt") as a:
        a.inst("bracket", ref_kb="part_simple_l")
        a.inst(
            "bolt",
            ref_kb="part_m6_cap_20mm",
            params_override={"l": 25},
            location={"loc": [0, 0, 30]},
        )
        a.mate(
            "bolt_to_bracket",
            joint_a="asm_demo.INST.bolt.JOINT.thread_tip",
            joint_b="asm_demo.INST.bracket.JOINT.hole_top",
            mate_type="rigid",
        )
