# SPDX-License-Identifier: MPL-2.0
"""asm_coupler_demo — coupler hanging off the lever tip of asm_window_test.

§4-round-2 exercise: builds on the existing window-test rig by mating
the new part_coupler (drag-link bar) onto the lever's tip joint.

Layer-tagging exercise:
- lever, coupler tagged 'mechanism' (the moving sub-assembly)
- sheet, brackets, motor tagged 'fixed_structure'

The two layers can be toggled independently via `mk layer set ... on|off`.
"""
from mk.kb import connect, kb_asm


with connect():
    with kb_asm("asm_coupler_demo", description="window rig + drag-link coupler") as a:
        a.inst("sheet", ref_kb="part_hdpe_sheet", layer="fixed_structure")
        a.inst("bracket", ref_kb="part_meccanixity_bracket", layer="fixed_structure")
        a.inst("motor", ref_kb="part_n20_worm_motor_16rpm", layer="fixed_structure")
        a.inst("lever", ref_kb="part_lever_arm", layer="mechanism")
        a.inst("coupler", ref_kb="part_coupler", layer="mechanism")

        # Same mate chain as asm_window_test for the motor / bracket / sheet /
        # lever, then the coupler hangs on the lever tip.
        a.mate(
            "a_bracket_to_sheet",
            joint_a="asm_coupler_demo.INST.bracket.JOINT.foot_bottom",
            joint_b="asm_coupler_demo.INST.sheet.JOINT.bracket_anchor",
            mate_type="rigid",
        )
        a.mate(
            "b_motor_to_bracket",
            joint_a="asm_coupler_demo.INST.motor.JOINT.body_center",
            joint_b="asm_coupler_demo.INST.bracket.JOINT.bore_center",
            mate_type="rigid",
        )
        a.mate(
            "c_lever_to_shaft",
            joint_a="asm_coupler_demo.INST.lever.JOINT.shaft_socket",
            joint_b="asm_coupler_demo.INST.motor.JOINT.shaft_a_tip",
            mate_type="rigid",
        )
        # New mate: coupler.motor_end on lever.tip. Rigid for now;
        # a revolute mate would be more physically faithful (the
        # coupler can rotate around the lever tip pin) but rigid
        # makes the static-pose render obvious.
        a.mate(
            "d_coupler_to_lever",
            joint_a="asm_coupler_demo.INST.coupler.JOINT.motor_end",
            joint_b="asm_coupler_demo.INST.lever.JOINT.tip",
            mate_type="rigid",
        )
