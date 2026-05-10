# SPDX-License-Identifier: MPL-2.0
"""asm_button_panel_test — round-3 evaluation fixture.

A button seated on a panel. Single mate at the hole_top ↔ seat
joint pair. Tries both align="z" (the default) and align="position"
via separate insts to show the difference.
"""
from mk.kb import connect, kb_asm


with connect():
    with kb_asm(
        "asm_button_panel_test",
        description="Pushbutton seated on mount panel — round-3 eval",
    ) as a:
        a.inst("panel", ref_kb="part_mount_panel", layer="frame")
        a.inst("button", ref_kb="part_button", layer="electrical")

        # Default align="z": rigid solver opposes z-dirs. With panel.hole_top
        # z_dir=[0,0,1] and button.seat z_dir=[0,0,-1], the alignment math
        # finds them already opposing — no rotation needed.
        a.mate(
            "button_to_panel",
            joint_a="asm_button_panel_test.INST.button.JOINT.seat",
            joint_b="asm_button_panel_test.INST.panel.JOINT.hole_top",
            mate_type="rigid",
        )
