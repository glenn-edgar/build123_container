# SPDX-License-Identifier: MPL-2.0
"""Phase B.1 fixture: revolute mate demo (a hinge).

Two thin "leaves" joined by a revolute mate — like a door hinge.
The leaf_b rotates around the hinge axis (joint_a's z-direction at the
mate point) by `default` degrees.

To see it at different angles, edit the `default` value and re-apply +
re-build. Phase B.2 will add live animation via outputs/<asm>.state.json.
"""
from mk.kb import connect, kb_asm, kb_part


def build_hinge_leaf(p):
    from build123d import Box  # noqa: F401
    return Box(p["w"], p["t"], p["h"])


with connect():
    with kb_part("part_hinge_leaf", description="Thin rectangular leaf for the hinge demo") as p:
        p.param("w", 30, type="float")     # X extent
        p.param("t", 2, type="float")      # Y extent (thickness)
        p.param("h", 50, type="float")     # Z extent (height — matches hinge axis)
        # Hinge edge runs along the leaf's +Z axis. Joint at the +X edge,
        # at the bottom of the leaf, with z_dir pointing OUT in +Y (the
        # leaf's broad face).
        p.joint("hinge_edge", origin=[15, 0, 0], z_dir=[0, 1, 0])
        p.meta("density", 7.85)
        p.meta("color", "#7799cc")
        p.builder(build_hinge_leaf)

    with kb_asm("asm_hinge", description="Revolute mate demo: two leaves joined by a hinge") as a:
        a.inst("leaf_a", ref_kb="part_hinge_leaf")
        a.inst("leaf_b", ref_kb="part_hinge_leaf")
        # Revolute mate: leaf_b's hinge_edge mates to leaf_a's hinge_edge.
        # Axis = [0, 0, 1] in joint_a's local frame = the hinge pin
        # direction (along the joint's local Z, after the rigid alignment
        # this is the world axis around which leaf_b swings).
        a.mate(
            "hinge",
            joint_a="asm_hinge.INST.leaf_b.JOINT.hinge_edge",
            joint_b="asm_hinge.INST.leaf_a.JOINT.hinge_edge",
            mate_type="revolute",
            axis=[0, 0, 1],
            limits=[0.0, 180.0],
            default=45.0,             # 45° open
        )
