# SPDX-License-Identifier: MPL-2.0
"""Phase-4 verify fixture: Box(10,10,10) density=1.0 → expected mass = 1.0 g.
Volume = 1000 mm^3; density = 1 g/cm^3 = 1e-3 g/mm^3; mass = 1.000 g.
"""
from mk.kb import connect, kb_asm, kb_part


def build_unit_box(p):
    from build123d import Box
    return Box(p["s"], p["s"], p["s"])


with connect():
    with kb_part("part_unit_box", description="10mm cube, density 1") as bp:
        bp.param("s", 10, type="float")
        bp.meta("density", 1.0)
        bp.builder(build_unit_box)

    with kb_asm("asm_unit_box", description="single unit-box instance") as a:
        a.inst("box1", ref_kb="part_unit_box")
