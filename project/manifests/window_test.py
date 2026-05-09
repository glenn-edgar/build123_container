# SPDX-License-Identifier: MPL-2.0
"""Window-controller test rig.

Simulates a car window subsystem for software-in-the-loop testing of a
controller. The N20 worm gearmotor (16 RPM at 12 V) drives a lever arm
through ±30° of travel. Soft foam-faced stops at each angular limit emulate
the upper and lower window seals; the controller detects end-of-travel
via stall-current spike. Worm gear is self-locking — motor holds position
when unpowered.

Layout (world coords):
- HDPE sheet flat in the XZ plane, top face at y=12.7 mm. X = 6" (152.4 mm),
  Z = 12" (304.8 mm). Centered at origin.
- MECCANIXITY L-bracket sits on top of the sheet near the +X long edge
  (z=0). Wall at +X edge of foot, motor mounts on wall's -X face.
- Motor body horizontal along world X. Body extends in -X (toward sheet
  center) from the bracket. Output shafts along world Y (vertical).
- Lever arm on the motor's upper shaft (+Y), rotating in the **horizontal**
  XZ plane like a record-player tonearm. At neutral, lever points in +X —
  tip extends past the sheet edge so the wheel hangs in clear air.
- Two foam-faced stop strips on the sheet top, in the lever's swing path.
  User unbolts both for motor calibration; reinstalls once the controller
  knows no-load characteristics.

Mate names start with letters that sort in dependency order (a_*, b_*, ...)
so the path-ordered solver processes them correctly.

META rows starting with `_TODO_` are placeholders the listing didn't
specify — fill from the datasheet before trusting controller simulations.
"""
from mk.kb import connect, kb_asm, kb_part


# ── Builders ───────────────────────────────────────────────────────────────

def build_hdpe_sheet(p):
    from build123d import Box  # noqa: F401
    return Box(p["w"], p["t"], p["d"])  # X × Y × Z


def build_meccanixity_bracket(p):
    """L-bracket. Foot in XZ plane at +Y up. Wall at the +X edge of the foot,
    extending up. mount_face is on the wall's -X face (back, away from foot).
    Motor mounts there and extends in -X direction.
    """
    from build123d import Box, Cylinder, Pos, Rotation  # noqa: F401
    foot = Pos(0, p["foot_t"] / 2, p["foot_d"] / 2) * Box(
        p["foot_w"], p["foot_t"], p["foot_d"]
    )
    wall_x = p["foot_w"] / 2 - p["wall_thickness"] / 2
    wall = Pos(wall_x, p["foot_t"] + p["wall_h"] / 2, p["foot_d"] / 2) * Box(
        p["wall_thickness"], p["wall_h"], p["foot_d"]
    )
    body = foot + wall

    # Bores through the wall along X (Cylinder default is Z; rotate to X).
    bore_y = p["foot_t"] + p["wall_h"] / 2
    bore_z = p["foot_d"] / 2
    central_bore = Pos(wall_x, bore_y, bore_z) * Rotation(0, 90, 0) * Cylinder(
        p["central_bore_d"] / 2, p["wall_thickness"] * 4
    )
    screw_l = Pos(
        wall_x, bore_y, bore_z - p["screw_spacing"] / 2
    ) * Rotation(0, 90, 0) * Cylinder(
        p["screw_clearance_d"] / 2, p["wall_thickness"] * 4
    )
    screw_r = Pos(
        wall_x, bore_y, bore_z + p["screw_spacing"] / 2
    ) * Rotation(0, 90, 0) * Cylinder(
        p["screw_clearance_d"] / 2, p["wall_thickness"] * 4
    )
    return body - central_bore - screw_l - screw_r


def build_n20_worm_motor_y_shaft(p):
    """N20 worm motor; body along motor-local X, shafts along motor-local Y,
    gearbox at +X end with mount face on its +X face. After mating to a
    bracket whose mount_face faces world -X, the motor sits unrotated:
    body along world X, shafts along world Y.
    """
    from build123d import Box, Cylinder, Pos, Rotation  # noqa: F401
    body = Rotation(0, 90, 0) * Cylinder(p["body_d"] / 2, p["body_l"])
    enc_x = -(p["body_l"] / 2 + p["enc_l"] / 2)
    encoder = Pos(enc_x, 0, 0) * Box(p["enc_l"], p["enc_w"], p["enc_h"])
    gb_x = p["body_l"] / 2 + p["gb_l"] / 2
    gearbox = Pos(gb_x, 0, 0) * Box(p["gb_l"], p["gb_w"], p["gb_h"])
    shaft_top_y = p["gb_h"] / 2 + p["shaft_l"] / 2
    # Cylinder default axis = Z; rotate +90° about X so shafts extend along Y.
    shaft_top = Pos(gb_x, shaft_top_y, 0) * Rotation(90, 0, 0) * Cylinder(
        p["shaft_d"] / 2, p["shaft_l"]
    )
    shaft_bot_y = -(p["gb_h"] / 2 + p["shaft_l"] / 2)
    shaft_bot = Pos(gb_x, shaft_bot_y, 0) * Rotation(90, 0, 0) * Cylinder(
        p["shaft_d"] / 2, p["shaft_l"]
    )
    return body + encoder + gearbox + shaft_top + shaft_bot


def build_lever_arm(p):
    """Triangular lever (approximating a 30° pie-slice). Wedge sits in the
    XZ plane (axis = Y) pointing in lever-local +X. shaft_socket faces -Y.
    Outer edge is a chord rather than a true arc — visually indistinguishable
    at 30° sweep; ~4% less area than a true sector.
    """
    from build123d import (  # noqa: F401
        BuildLine, BuildSketch, Cylinder, Polyline, Pos, Rotation, extrude, make_face,
    )
    import math

    half = math.radians(p["sweep_deg"] / 2)
    r = p["outer_r"]
    th = p["thickness"]

    p0 = (0.0, 0.0)
    p1 = (r * math.cos(half), r * math.sin(half))
    p2 = (r * math.cos(-half), r * math.sin(-half))

    with BuildSketch() as sk:
        with BuildLine():
            Polyline(p0, p1, p2, p0)
        make_face()

    # Sketch sits in XY by default. Extrude in +Z, recenter on Z=0, then
    # rotate so wedge thickness is along Y (lever rotation axis).
    wedge = extrude(sk.sketch, amount=th)
    wedge = Pos(0, 0, -th / 2) * wedge
    wedge = Rotation(-90, 0, 0) * wedge

    hub_outer = Rotation(-90, 0, 0) * Cylinder(p["hub_d"] / 2, th)
    hub_bore = Rotation(-90, 0, 0) * Cylinder(p["shaft_d"] / 2, th * 4)
    return (wedge + hub_outer) - hub_bore


def build_stop_strip(p):
    """Vertical stop strip on the sheet. Substrate is a tall thin block;
    foam pad is on the -Z face so the lever (sweeping in +Z direction)
    contacts it. Mounting hole through the substrate to the sheet.
    """
    from build123d import Box, Cylinder, Pos  # noqa: F401
    sub = Pos(0, p["height"] / 2, 0) * Box(p["thickness"], p["height"], p["length"])
    foam = Pos(0, p["height"] / 2, -p["length"] / 2 - p["foam_t"] / 2) * Box(
        p["thickness"], p["height"], p["foam_t"]
    )
    return sub + foam


# ── Apply ──────────────────────────────────────────────────────────────────

with connect():
    # ── HDPE sheet ────────────────────────────────────────────────────────
    with kb_part("part_hdpe_sheet", description="6\"×12\"×1/2\" HDPE base plate") as p:
        p.param("w", 152.4, type="float")
        p.param("t", 12.7, type="float")
        p.param("d", 304.8, type="float")

        # Bracket anchor: top-of-sheet, near +X long edge, at z=0.
        # X chosen so the bracket foot's +X edge lands at the sheet edge (76.2).
        p.joint("bracket_anchor", origin=[67.2, 6.35, 0], z_dir=[0, 1, 0])
        # Stop strips on the sheet top, on either side of z=0 (lever swing).
        p.joint("stop_pos_anchor", origin=[60, 6.35, 18], z_dir=[0, 1, 0])
        p.joint("stop_neg_anchor", origin=[60, 6.35, -18], z_dir=[0, 1, 0])

        p.meta("density", 0.95)
        p.meta("material", "HDPE")
        p.builder(build_hdpe_sheet)

    # ── MECCANIXITY bracket ──────────────────────────────────────────────
    with kb_part(
        "part_meccanixity_bracket",
        description="MECCANIXITY 18×15 mm L-bracket for N20, 11.5 mm hole spacing",
    ) as p:
        p.param("foot_w", 18, type="float")
        p.param("foot_d", 10, type="float")
        p.param("foot_t", 3.5, type="float")
        p.param("wall_h", 11.5, type="float")
        p.param("wall_thickness", 3, type="float")
        p.param("central_bore_d", 5.8, type="float")
        p.param("screw_spacing", 11.5, type="float")
        p.param("screw_clearance_d", 2.4, type="float")  # 2-56 clearance

        # foot_bottom: bottom of the foot, faces -Y. Mates to sheet top.
        p.joint("foot_bottom", origin=[0, 0, 5], z_dir=[0, -1, 0])
        # mount_face: -X face of the wall (back, where motor attaches).
        # wall_x = foot_w/2 - wall_thickness/2 = 9 - 1.5 = 7.5
        # wall back face at x = 7.5 - 1.5 = 6
        p.joint("mount_face", origin=[6, 9.25, 5], z_dir=[-1, 0, 0])

        p.meta("density", 1.05)
        p.meta("material", "ABS")
        p.builder(build_meccanixity_bracket)

    # ── N20 worm motor (16 RPM variant, vertical-shaft layout) ────────────
    with kb_part(
        "part_n20_worm_motor_16rpm",
        description="N20 worm motor 12V 16RPM Φ3x10 double-shaft, encoder",
    ) as p:
        p.param("body_d", 12, type="float")
        p.param("body_l", 25, type="float")
        p.param("enc_l", 7, type="float")
        p.param("enc_w", 12, type="float")
        p.param("enc_h", 12, type="float")
        p.param("gb_l", 15, type="float")
        p.param("gb_w", 12, type="float")
        p.param("gb_h", 12, type="float")
        p.param("shaft_d", 3, type="float")
        p.param("shaft_l", 10, type="float")

        # gearbox_front: +X face of gearbox.
        # x = body_l/2 + gb_l = 12.5 + 15 = 27.5
        p.joint("gearbox_front", origin=[27.5, 0, 0], z_dir=[1, 0, 0])
        # shaft_a_tip: top of upper shaft.
        # x = body_l/2 + gb_l/2 = 12.5 + 7.5 = 20
        # y = gb_h/2 + shaft_l = 6 + 10 = 16
        p.joint("shaft_a_tip", origin=[20, 16, 0], z_dir=[0, 1, 0])
        p.joint("shaft_b_tip", origin=[20, -16, 0], z_dir=[0, -1, 0])

        p.meta("part_number", "Anreak N20-16RPM worm w/ encoder")
        p.meta("vendor", "Anreak")
        p.meta("electrical_voltage_nominal_v", 12.0)
        p.meta("electrical_voltage_min_v", 3.0)
        p.meta("electrical_voltage_max_v", 12.0)
        p.meta("_TODO_electrical_resistance_ohm", None)
        p.meta("_TODO_electrical_back_emf_v_per_krpm", None)
        p.meta("_TODO_electrical_stall_current_a", None)
        p.meta("mech_no_load_rpm_at_12v", 16)
        p.meta("mech_no_load_rpm_at_3v", 4)
        p.meta("mech_gear_type", "worm")
        p.meta("mech_self_locking", True)
        p.meta("mech_double_shaft", True)
        p.meta("shaft_diameter_mm", 3)
        p.meta("shaft_length_mm", 10)
        p.meta("_TODO_mech_gear_ratio", None)
        p.meta("_TODO_mech_stall_torque_kg_cm", None)
        p.meta("encoder_present", True)
        p.meta("_TODO_encoder_type", "magnetic_quadrature")
        p.meta("_TODO_encoder_cpr_pre_gear", 7)
        p.meta("density", 7.0)
        p.builder(build_n20_worm_motor_y_shaft)

    # ── Lever arm (30° pie slice from a 40 mm wheel) ─────────────────────
    with kb_part(
        "part_lever_arm",
        description="30° pie-slice wedge cut from a 40×7 mm wheel",
    ) as p:
        p.param("hub_d", 10, type="float")
        p.param("outer_r", 20, type="float")
        p.param("thickness", 7, type="float")
        p.param("shaft_d", 3, type="float")
        p.param("sweep_deg", 30, type="float")

        # shaft_socket: bottom face of the lever (where shaft enters), faces -Y.
        p.joint("shaft_socket", origin=[0, -3.5, 0], z_dir=[0, -1, 0])
        # tip: outermost point at angular zero.
        p.joint("tip", origin=[20, 0, 0], z_dir=[1, 0, 0])

        p.meta("density", 1.25)
        p.meta("material", "PLA")
        p.builder(build_lever_arm)

    # ── Stop strip (foam-faced, removable) ───────────────────────────────
    with kb_part(
        "part_stop_strip",
        description="1/2\" plastic strip + 8 mm foam, vertical mount on sheet. Removable.",
    ) as p:
        p.param("length", 30, type="float")
        p.param("thickness", 12.7, type="float")
        p.param("height", 25, type="float")
        p.param("foam_t", 8, type="float")

        # base_bottom: bottom of substrate, faces -Y.
        p.joint("base_bottom", origin=[0, 0, 0], z_dir=[0, -1, 0])

        p.meta("density", 0.6)
        p.meta("material", "plastic+foam composite")
        p.meta("removable", True)
        p.meta("calibration_state", "remove for cal; reinstall after")
        p.builder(build_stop_strip)

    # ── Assembly ─────────────────────────────────────────────────────────
    with kb_asm(
        "asm_window_test",
        description="N20 worm + lever + foam stops on HDPE sheet — window-controller test rig",
    ) as a:
        a.inst("sheet", ref_kb="part_hdpe_sheet")
        a.inst("bracket", ref_kb="part_meccanixity_bracket")
        a.inst("motor", ref_kb="part_n20_worm_motor_16rpm")
        a.inst("lever", ref_kb="part_lever_arm")
        a.inst("stop_pos", ref_kb="part_stop_strip")
        a.inst("stop_neg", ref_kb="part_stop_strip")

        a.mate("a_bracket_to_sheet",
               joint_a="asm_window_test.INST.bracket.JOINT.foot_bottom",
               joint_b="asm_window_test.INST.sheet.JOINT.bracket_anchor",
               mate_type="rigid")
        a.mate("b_motor_to_bracket",
               joint_a="asm_window_test.INST.motor.JOINT.gearbox_front",
               joint_b="asm_window_test.INST.bracket.JOINT.mount_face",
               mate_type="rigid")
        a.mate("c_lever_to_shaft",
               joint_a="asm_window_test.INST.lever.JOINT.shaft_socket",
               joint_b="asm_window_test.INST.motor.JOINT.shaft_a_tip",
               mate_type="rigid")
        a.mate("d_stop_pos_to_sheet",
               joint_a="asm_window_test.INST.stop_pos.JOINT.base_bottom",
               joint_b="asm_window_test.INST.sheet.JOINT.stop_pos_anchor",
               mate_type="rigid")
        a.mate("e_stop_neg_to_sheet",
               joint_a="asm_window_test.INST.stop_neg.JOINT.base_bottom",
               joint_b="asm_window_test.INST.sheet.JOINT.stop_neg_anchor",
               mate_type="rigid")
