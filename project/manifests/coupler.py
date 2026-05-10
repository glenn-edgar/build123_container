# SPDX-License-Identifier: MPL-2.0
"""part_coupler — drag-link coupler between the lever tip and a load.

Thin rectangular bar with a through-hole at each end. The motor-side
hole hangs on the lever tip; the load-side hole connects to a target
that the window-controller test rig drives.

§4-round-2 exercise: scaffolded via `mk part new --template plate_with_hole`,
then edited to add real joints + typed META.
"""
from mk.kb import connect, kb_part


def build_coupler(p):
    from build123d import Box, Cylinder, Pos  # noqa: F401
    bar = Box(p["length"], p["width"], p["thickness"])
    hole_left = Pos(-p["length"] / 2 + p["hole_offset"], 0, 0) * Cylinder(
        p["hole_d"] / 2, p["thickness"] * 4,
    )
    hole_right = Pos(p["length"] / 2 - p["hole_offset"], 0, 0) * Cylinder(
        p["hole_d"] / 2, p["thickness"] * 4,
    )
    return bar - hole_left - hole_right


with connect():
    with kb_part(
        "part_coupler",
        description="Drag-link coupler bar — 40 mm aluminium, 3 mm holes both ends",
    ) as p:
        p.param("length", 40, type="float")
        p.param("width", 8, type="float")
        p.param("thickness", 2, type="float")
        p.param("hole_d", 3, type="float")
        p.param("hole_offset", 4, type="float")  # hole center inset from end

        # Two pivot joints, one at each end. z_dir along +Z so they
        # mate to vertical shafts (matches the motor's shaft_a_tip).
        # motor_end is at -X end (closer to motor); load_end at +X.
        p.joint(
            "motor_end",
            origin=[-20 + 4, 0, 0],
            z_dir=[0, 1, 0],
        )
        p.joint(
            "load_end",
            origin=[20 - 4, 0, 0],
            z_dir=[0, 1, 0],
        )

        # Typed META — exercises the Phase B.3 namespace schema.
        p.meta("density", 2.70)             # aluminium, g/cm^3
        p.meta("material", "aluminium_6061")
        p.meta("color", "#c0c0c8")          # brushed-aluminium grey
        p.meta("vendor", "(self-machined)")
        p.meta("part_number", "MK-COUPLER-40")
        p.meta("mech.max_load_n", 25.0)     # design limit
        p.meta("mech.material_yield_mpa", 276)  # 6061-T6
        p.meta("mech.fatigue_cycles", 1_000_000)

        p.builder(build_coupler)
