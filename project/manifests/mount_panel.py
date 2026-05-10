# SPDX-License-Identifier: MPL-2.0
"""part_mount_panel — round-3 evaluation fixture.

Square panel with a centered hole for a flush-mount button. Joint
``hole_face_top`` is the top face of the hole; ``base_back`` is the
bottom face of the panel (mounting surface).
"""
from mk.kb import connect, kb_part


def build_mount_panel(p):
    from build123d import Box, Cylinder, Pos  # noqa: F401
    plate = Box(p["w"], p["d"], p["t"])
    hole = Cylinder(p["hole_d"] / 2, p["t"] * 4)
    return plate - hole


with connect():
    with kb_part(
        "part_mount_panel",
        description="50×50×5 mm ABS panel with centered Φ12 mm button hole",
    ) as p:
        p.param("w", 50, type="float")
        p.param("d", 50, type="float")
        p.param("t", 5, type="float")
        p.param("hole_d", 12, type="float")  # matches button shaft

        # Top of the hole — where the button's flange seats. +Z normal
        # points up (out of the panel).
        p.joint("hole_top", origin=[0, 0, 2.5], z_dir=[0, 0, 1])
        # Bottom face for mounting to something.
        p.joint("base_back", origin=[0, 0, -2.5], z_dir=[0, 0, -1])

        p.meta("density", 1.05)
        p.meta("material", "ABS")
        p.meta("color", "#2c3540")  # charcoal
        p.meta("vendor", "(machined)")
        p.meta("mech.max_clamp_torque_nm", 0.4)

        p.builder(build_mount_panel)
