# SPDX-License-Identifier: MPL-2.0
"""part_button — round-3 evaluation fixture.

Two-diameter cylindrical pushbutton: a small ``shaft`` that pokes
through the panel hole, capped with a wider ``cap`` flange that
seats on the panel's top face.
"""
from mk.kb import connect, kb_part


def build_button(p):
    from build123d import Cylinder, Pos  # noqa: F401
    shaft = Cylinder(p["shaft_d"] / 2, p["shaft_l"])
    cap = Pos(0, 0, p["shaft_l"] / 2 + p["cap_t"] / 2) * Cylinder(
        p["cap_d"] / 2, p["cap_t"],
    )
    return shaft + cap


with connect():
    with kb_part(
        "part_button",
        description="Two-diameter pushbutton — Φ12 shaft, Φ18 cap, 8 mm protrusion",
    ) as p:
        p.param("shaft_d", 12, type="float")
        p.param("shaft_l", 8, type="float")
        p.param("cap_d", 18, type="float")
        p.param("cap_t", 3, type="float")

        # Bottom of the cap — seats on the panel's hole_top joint.
        # Cap bottom is at z = shaft_l/2 (with shaft_l=8 → z=4).
        p.joint("seat", origin=[0, 0, 4], z_dir=[0, 0, -1])

        p.meta("density", 1.20)
        p.meta("material", "ABS")
        p.meta("color", "#dc1c20")  # red
        p.meta("electrical.voltage_max_v", 24.0)
        p.meta("electrical.contact_rating_a", 0.5)
        p.meta("mech.actuation_force_n", 1.2)

        p.builder(build_button)
