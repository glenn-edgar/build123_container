# SPDX-License-Identifier: MPL-2.0
"""N20 worm-motor test rig — digital twin for window-controller software.

Models an Anreak DC 12V 381 RPM Φ3×10mm double-shaft N20 worm motor with
encoder, mounted in a tabletop saddle bracket. No cable, no load — the
controller-under-test consumes the META rows for its simulation contract.

Coordinate convention: motor body cylinder axis is +X. Encoder block is at
−X end, worm gearbox is at +X end. Output shafts protrude perpendicular to
the body (along ±Z) from the gearbox sides — characteristic of a worm
drive. +Y is up; the motor sits on the bracket with its bottom touching
the saddle.

META rows starting with `_TODO` are placeholders the listing didn't
specify; fill from the datasheet before trusting controller simulations.
"""
from mk.kb import connect, kb_asm, kb_part


def build_n20_motor(p):
    from build123d import Box, Cylinder, Pos, Rotation
    # Body cylinder along X (default Cylinder is along Z — rotate 90° about Y).
    body = Rotation(0, 90, 0) * Cylinder(p["body_d"] / 2, p["body_l"])
    # Encoder block at the −X end of the body.
    enc_x = -(p["body_l"] / 2 + p["enc_l"] / 2)
    encoder = Pos(enc_x, 0, 0) * Box(p["enc_l"], p["enc_w"], p["enc_h"])
    # Worm gearbox block at the +X end of the body.
    gb_x = p["body_l"] / 2 + p["gb_l"] / 2
    gearbox = Pos(gb_x, 0, 0) * Box(p["gb_l"], p["gb_w"], p["gb_h"])
    # Two output shafts in ±Z, sticking out of the gearbox sides.
    shaft_top_z = p["gb_h"] / 2 + p["shaft_l"] / 2
    shaft_top = Pos(gb_x, 0, shaft_top_z) * Cylinder(p["shaft_d"] / 2, p["shaft_l"])
    shaft_bot_z = -(p["gb_h"] / 2 + p["shaft_l"] / 2)
    shaft_bot = Pos(gb_x, 0, shaft_bot_z) * Cylinder(p["shaft_d"] / 2, p["shaft_l"])
    return body + encoder + gearbox + shaft_top + shaft_bot


def build_motor_bracket(p):
    from build123d import Box, Cylinder, Pos, Rotation
    # Flat base plate centred on origin, sitting at y∈[-base_t/2, +base_t/2].
    base = Box(p["base_w"], p["base_t"], p["base_d"])
    # Saddle wall rises from the top of the base.
    wall_y = p["base_t"] / 2 + p["wall_h"] / 2
    wall = Pos(0, wall_y, 0) * Box(p["wall_w"], p["wall_h"], p["wall_d"])
    # Bore: horizontal cylinder along X through the saddle wall, sized to
    # cradle the motor body. Bore center sits high in the wall so motor
    # rests on top of the bracket.
    bore_y = p["base_t"] / 2 + p["wall_h"] - p["bore_r"]
    bore = (
        Pos(0, bore_y, 0)
        * Rotation(0, 90, 0)
        * Cylinder(p["bore_r"], p["wall_w"] * 2)
    )
    return (base + wall) - bore


with connect():
    # ── Motor ─────────────────────────────────────────────────────────────
    with kb_part(
        "part_n20_motor",
        description="Anreak N20 worm motor 12V 381RPM Φ3x10 double-shaft, with encoder",
    ) as p:
        # Geometry (mm)
        p.param("body_d", 12, type="float")     # N20 standard body diameter
        p.param("body_l", 25, type="float")     # body length (without enc/gb)
        p.param("enc_l", 7, type="float")       # encoder block depth (along X)
        p.param("enc_w", 12, type="float")
        p.param("enc_h", 12, type="float")
        p.param("gb_l", 15, type="float")       # gearbox length
        p.param("gb_w", 12, type="float")
        p.param("gb_h", 12, type="float")
        p.param("shaft_d", 3, type="float")     # output shaft diameter
        p.param("shaft_l", 10, type="float")    # output shaft protruding length

        # Joints — all in motor-local coords.
        # body_clamp: bottom of the body cylinder, points downward. Mates
        # to the bracket's saddle (which points up). After rigid mate the
        # motor sits in the cradle with body axis along world X.
        p.joint("body_clamp", origin=[0, -6, 0], z_dir=[0, -1, 0])
        # The two output shaft tips. Either is a candidate for an optional
        # load attachment in a later version of this rig.
        p.joint("shaft_a_tip",
                origin=[20, 0, 16], z_dir=[0, 0, 1])     # gb_x=20, gb_h/2 + shaft_l = 6+10 = 16
        p.joint("shaft_b_tip",
                origin=[20, 0, -16], z_dir=[0, 0, -1])

        # Identity / sourcing
        p.meta("part_number", "Anreak N20-381 worm w/ encoder")
        p.meta("vendor", "Anreak")

        # Electrical (controller simulation contract)
        p.meta("electrical_voltage_nominal_v", 12.0)
        p.meta("electrical_voltage_min_v", 3.0)
        p.meta("electrical_voltage_max_v", 12.0)
        p.meta("_TODO_electrical_resistance_ohm", None)
        p.meta("_TODO_electrical_back_emf_v_per_krpm", None)
        p.meta("_TODO_electrical_stall_current_a", None)

        # Mechanical
        p.meta("mech_no_load_rpm_at_12v", 381)
        p.meta("mech_no_load_rpm_at_3v", 4)
        p.meta("mech_gear_type", "worm")
        p.meta("mech_double_shaft", True)
        p.meta("shaft_diameter_mm", 3)
        p.meta("shaft_length_mm", 10)
        p.meta("_TODO_mech_gear_ratio", None)         # derivable once base motor RPM known
        p.meta("_TODO_mech_stall_torque_kg_cm", None)

        # Encoder
        p.meta("encoder_present", True)
        p.meta("_TODO_encoder_type", "magnetic_quadrature")  # typical N20 encoder
        p.meta("_TODO_encoder_cpr_pre_gear", 7)              # typical; verify
        # Post-gear CPR = pre_gear * gear_ratio; computed at controller side.

        # Material / density. N20-with-encoder is mostly steel body + small
        # plastic + small PCB. Single average density; fine for first-cut
        # mass estimates. Replace with measured weight if you have a scale.
        p.meta("density", 7.0)  # g/cm^3, rough average

        p.builder(build_n20_motor)

    # ── Bracket ───────────────────────────────────────────────────────────
    with kb_part(
        "part_motor_bracket",
        description="Saddle bracket for N20 motor, tabletop test rig",
    ) as p:
        p.param("base_w", 30, type="float")    # along X
        p.param("base_d", 50, type="float")    # along Z (long enough to clear gearbox)
        p.param("base_t", 4, type="float")     # thickness Y
        p.param("wall_w", 30, type="float")    # saddle wall — same width as base
        p.param("wall_h", 12, type="float")    # wall height above base top
        p.param("wall_d", 30, type="float")    # wall depth (Z) — narrower than base
        p.param("bore_r", 6, type="float")     # matches motor body radius

        # Saddle top: where the motor's body_clamp lands. The saddle's
        # cradling surface faces +Y (up). bore_y was: base_t/2 + wall_h - bore_r
        # = 2 + 12 - 6 = 8. The motor's bottom-of-body sits here.
        p.joint("saddle_top", origin=[0, 8, 0], z_dir=[0, 1, 0])

        # Bracket base flat for tabletop mounting.
        p.joint("base_bottom", origin=[0, -2, 0], z_dir=[0, -1, 0])

        p.meta("density", 1.05)  # ABS plastic — fine for prototype rig
        p.meta("material", "ABS")

        p.builder(build_motor_bracket)

    # ── Assembly ──────────────────────────────────────────────────────────
    with kb_asm(
        "asm_n20_test",
        description="N20 motor mounted in saddle bracket, tabletop test fixture",
    ) as a:
        a.inst("bracket", ref_kb="part_motor_bracket")
        a.inst("motor", ref_kb="part_n20_motor")
        a.mate(
            "motor_to_bracket",
            joint_a="asm_n20_test.INST.motor.JOINT.body_clamp",
            joint_b="asm_n20_test.INST.bracket.JOINT.saddle_top",
            mate_type="rigid",
        )
