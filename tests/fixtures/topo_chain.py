# SPDX-License-Identifier: MPL-2.0
"""Topo-sort mate solver smoke fixture.

Three blocks chained left-to-right via face mates, but with mates declared
and named in REVERSE dependency order. Proves the solver topologically
sorts before processing — old path-order processing would have failed
because zzz_a_to_b would fire before the chain root was resolved.

Expected after build:
    block_a  at world (-5, -5, -5) → ( 5,  5,  5)   identity
    block_b  at world ( 5, -5, -5) → (15,  5,  5)   shifted +10X (mated to a)
    block_c  at world (15, -5, -5) → (25,  5,  5)   shifted +10X (mated to b)
"""
from mk.kb import connect, kb_asm, kb_part


def build_block(p):
    from build123d import Box  # noqa: F401
    return Box(p["w"], p["w"], p["w"])


with connect():
    with kb_part("part_chain_block") as p:
        p.param("w", 10, type="float")
        p.joint("face_pos", origin=[5, 0, 0], z_dir=[1, 0, 0])
        p.joint("face_neg", origin=[-5, 0, 0], z_dir=[-1, 0, 0])
        p.meta("density", 1.0)
        p.meta("color", "#aaccaa")
        p.builder(build_block)

    with kb_asm("asm_topo_chain", description="3-block chain with mates declared in reverse dependency order") as a:
        a.inst("block_a", ref_kb="part_chain_block")
        a.inst("block_b", ref_kb="part_chain_block")
        a.inst("block_c", ref_kb="part_chain_block")

        # Declared/named in reverse: zzz mate (c→b) is declared FIRST and
        # sorts FIRST alphabetically, but it depends on block_b's transform
        # which is set by aaa_b_to_a. Old path-order processing would
        # produce wrong world coords for block_c. Topo-sort handles it.
        a.mate(
            "zzz_c_to_b",
            joint_a="asm_topo_chain.INST.block_c.JOINT.face_neg",
            joint_b="asm_topo_chain.INST.block_b.JOINT.face_pos",
            mate_type="rigid",
        )
        a.mate(
            "aaa_b_to_a",
            joint_a="asm_topo_chain.INST.block_b.JOINT.face_neg",
            joint_b="asm_topo_chain.INST.block_a.JOINT.face_pos",
            mate_type="rigid",
        )
