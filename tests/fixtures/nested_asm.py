# SPDX-License-Identifier: LGPL-2.1-or-later
"""Phase-2 verify fixture: assembly with a SUB scope."""
from mk.kb import connect, kb_asm, kb_part


def build_block(p):
    from build123d import Box  # noqa: F401
    return Box(p["w"], p["w"], p["w"])


with connect():
    with kb_part("part_block", description="cube") as p:
        p.param("w", 10, type="float")
        p.builder(build_block)

    with kb_asm("asm_nested", description="two-level structure") as a:
        a.inst("top_block", ref_kb="part_block")
        with a.sub("group_a", description="lower-level group") as s:
            s.inst("inner_a1", ref_kb="part_block")
            s.inst("inner_a2", ref_kb="part_block")
            s.mate(
                "a1_to_a2",
                joint_a="asm_nested.SUB.group_a.INST.inner_a1.JOINT.face",
                joint_b="asm_nested.SUB.group_a.INST.inner_a2.JOINT.face",
            )
        with a.sub("group_b") as s:
            s.inst("inner_b1", ref_kb="part_block")
