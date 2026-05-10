# SPDX-License-Identifier: MPL-2.0
"""SUB-scope smoke fixture. Two-level assembly that mates across a SUB
scope — exercises the SUB-aware mate solver introduced in Phase A.

Layout (after build):
    asm_nested
    ├── top_block       (no mate — at world identity)
    └── SUB.group_a
        ├── inner_a1    (chain root for the SUB; at world identity within asm)
        └── inner_a2    (mated to inner_a1 via face_pos ↔ face_neg)
"""
from mk.kb import connect, kb_asm, kb_part


def build_block(p):
    from build123d import Box  # noqa: F401
    return Box(p["w"], p["w"], p["w"])


with connect():
    with kb_part("part_block", description="10 mm cube with two opposing face joints") as p:
        p.param("w", 10, type="float")
        # Faces of the centered cube. +X face and -X face. Used for the
        # SUB-scope mate test.
        p.joint("face_pos", origin=[5, 0, 0], z_dir=[1, 0, 0])
        p.joint("face_neg", origin=[-5, 0, 0], z_dir=[-1, 0, 0])
        p.meta("density", 1.0)
        p.meta("color", "#88aacc")
        p.builder(build_block)

    with kb_asm("asm_nested", description="two-level SUB-scope mate test") as a:
        a.inst("top_block", ref_kb="part_block")
        with a.sub("group_a", description="lower-level group") as s:
            s.inst("inner_a1", ref_kb="part_block")
            s.inst("inner_a2", ref_kb="part_block")
            # Mate inner_a2's -X face onto inner_a1's +X face. Tests that
            # the SUB-nested joint paths parse and the chain composes.
            s.mate(
                "a_a2_to_a1",
                joint_a="asm_nested.SUB.group_a.INST.inner_a2.JOINT.face_neg",
                joint_b="asm_nested.SUB.group_a.INST.inner_a1.JOINT.face_pos",
                mate_type="rigid",
            )
        with a.sub("group_b") as s:
            s.inst("inner_b1", ref_kb="part_block")
