"""Pure-Python tests for mk.urdf (no OCP needed)."""
from __future__ import annotations

import math
from xml.etree import ElementTree as ET

import pytest

from mk.urdf import (
    _compose_inv_a_times_b,
    _has_limits,
    _joint_element,
    _sanitize,
    determine_roots,
    rot_to_rpy,
)


# ── name sanitizer ───────────────────────────────────────────────────────────

class TestSanitize:
    def test_flat_inst(self):
        assert _sanitize("asm_demo.INST.bolt") == "asm_demo__INST__bolt"

    def test_sub_path(self):
        assert _sanitize("asm.SUB.group.INST.foo") == "asm__SUB__group__INST__foo"

    def test_no_dots_passthrough(self):
        assert _sanitize("link1") == "link1"


# ── rot → rpy ────────────────────────────────────────────────────────────────

def _almost(a, b, tol=1e-9):
    return abs(a - b) < tol


def _rpy_to_rot(roll, pitch, yaw):
    """Inverse: build a rotation from RPY for verification."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    Rx = [[1, 0, 0], [0, cr, -sr], [0, sr, cr]]
    Ry = [[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]]
    Rz = [[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]

    def mm(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return mm(mm(Rz, Ry), Rx)


def _mat_almost(A, B, tol=1e-9):
    return all(_almost(A[i][j], B[i][j], tol) for i in range(3) for j in range(3))


class TestRotToRpy:
    def test_identity_is_zero(self):
        r, p, y = rot_to_rpy([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        assert _almost(r, 0.0)
        assert _almost(p, 0.0)
        assert _almost(y, 0.0)

    @pytest.mark.parametrize("roll,pitch,yaw", [
        (0.3, 0.5, 0.7),
        (-0.4, 0.2, 1.0),
        (1.0, -0.3, -0.8),
        (math.pi / 3, 0.0, 0.0),
        (0.0, math.pi / 4, 0.0),
        (0.0, 0.0, math.pi / 2),
    ])
    def test_roundtrip_non_singular(self, roll, pitch, yaw):
        R = _rpy_to_rot(roll, pitch, yaw)
        r2, p2, y2 = rot_to_rpy(R)
        R_back = _rpy_to_rot(r2, p2, y2)
        # Rotations should round-trip even if angles drift modulo 2π.
        assert _mat_almost(R, R_back, tol=1e-9)

    def test_gimbal_lock_positive_pitch(self):
        # pitch = +π/2: yaw set to 0 by convention; remaining angle goes to roll.
        R = _rpy_to_rot(0.5, math.pi / 2, 0.3)  # roll - yaw = 0.2
        r, p, y = rot_to_rpy(R)
        assert _almost(p, math.pi / 2, tol=1e-9)
        assert _almost(y, 0.0, tol=1e-9)
        # Round-trip the matrix should still match.
        R_back = _rpy_to_rot(r, p, y)
        assert _mat_almost(R, R_back, tol=1e-9)

    def test_clamps_drift_outside_unit(self):
        # Tiny FP drift past 1.0 must not raise from asin's domain check.
        # R[2][0] = -1.0000001 (FP drift past −1) → pitch = asin(1.0000001).
        # Without clamping this raises ValueError; with clamping pitch saturates at +π/2.
        R = [[0, 0, 1], [0, 1, 0], [-1.0000001, 0, 0]]
        r, p, y = rot_to_rpy(R)
        assert _almost(p, math.pi / 2, tol=1e-6)


# ── inverse-compose ──────────────────────────────────────────────────────────

class TestComposeInv:
    def test_inv_identity_times_other(self):
        I = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        R = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        rot, trans = _compose_inv_a_times_b(I, [0, 0, 0], R, [1, 2, 3])
        assert rot == R
        assert trans == [1, 2, 3]

    def test_inv_same_is_identity(self):
        # inverse(A) @ A = I
        R = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        rot, trans = _compose_inv_a_times_b(R, [1, 2, 3], R, [1, 2, 3])
        I = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        assert _mat_almost(rot, I)
        assert all(_almost(t, 0.0) for t in trans)

    def test_translation_subtraction(self):
        I = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        rot, trans = _compose_inv_a_times_b(I, [10, 0, 0], I, [13, 0, 0])
        assert trans == [3, 0, 0]


# ── topology ─────────────────────────────────────────────────────────────────

def _mate(name, a, b, mt="rigid", **kw):
    d = {
        "name": name,
        "mate_type": mt,
        "a_path": a, "a_name": a.split(".")[-1], "joint_a_name": "j",
        "b_path": b, "b_name": b.split(".")[-1], "joint_b_name": "j",
        "axis": [0, 0, 1],
        "limits": None,
        "default": None,
    }
    d.update(kw)
    return d


class TestDetermineRoots:
    def test_single_inst_zero_mates(self):
        assert determine_roots(["asm.INST.lone"], []) == ["asm.INST.lone"]

    def test_simple_chain(self):
        # bracket child of sheet, motor child of bracket.
        # Roots = [sheet].
        mates = [
            _mate("m1", "asm.INST.bracket", "asm.INST.sheet"),
            _mate("m2", "asm.INST.motor", "asm.INST.bracket"),
        ]
        assert determine_roots(
            ["asm.INST.sheet", "asm.INST.bracket", "asm.INST.motor"], mates,
        ) == ["asm.INST.sheet"]

    def test_two_disconnected_roots(self):
        # foo unmated, bar unmated → both roots.
        roots = determine_roots(
            ["asm.INST.foo", "asm.INST.bar"], []
        )
        assert set(roots) == {"asm.INST.foo", "asm.INST.bar"}


# ── joint element XML ────────────────────────────────────────────────────────

class TestJointElement:
    def test_rigid_emits_fixed(self):
        m = _mate("a_to_b", "asm.INST.a", "asm.INST.b", mt="rigid")
        elem = _joint_element(m, [0.1, 0.2, 0.3], (0.0, 0.0, 0.0))
        assert elem.tag == "joint"
        assert elem.get("type") == "fixed"
        assert elem.get("name") == "a_to_b"
        # No <axis> or <limit> for fixed.
        assert elem.find("axis") is None
        assert elem.find("limit") is None
        # parent/child links sanitized.
        assert elem.find("parent").get("link") == "asm__INST__b"
        assert elem.find("child").get("link") == "asm__INST__a"

    def test_revolute_with_limits(self):
        m = _mate(
            "hinge", "asm.INST.leaf_b", "asm.INST.leaf_a",
            mt="revolute", axis=[0, 0, 1], limits=[0.0, 180.0],
        )
        elem = _joint_element(m, [0, 0, 0], (0, 0, 0))
        assert elem.get("type") == "revolute"
        assert elem.find("axis").get("xyz") == "0 0 1"
        lim = elem.find("limit")
        assert lim is not None
        # Degrees → radians.
        assert _almost(float(lim.get("lower")), 0.0)
        assert _almost(float(lim.get("upper")), math.pi, tol=1e-7)
        assert lim.get("effort") == "100"
        assert lim.get("velocity") == "1"

    def test_revolute_without_limits_becomes_continuous(self):
        m = _mate("spinner", "asm.INST.a", "asm.INST.b", mt="revolute", limits=None)
        elem = _joint_element(m, [0, 0, 0], (0, 0, 0))
        assert elem.get("type") == "continuous"
        assert elem.find("limit") is None
        assert elem.find("axis") is not None

    def test_revolute_with_only_one_limit(self):
        m = _mate(
            "half_bound", "asm.INST.a", "asm.INST.b",
            mt="revolute", limits=[0.0, None],
        )
        elem = _joint_element(m, [0, 0, 0], (0, 0, 0))
        # [0, None] is "bounded" — still revolute (not continuous).
        assert elem.get("type") == "revolute"
        lim = elem.find("limit")
        assert lim.get("lower") == "0"
        assert "upper" not in lim.attrib

    def test_prismatic_mm_to_metres(self):
        m = _mate(
            "slider", "asm.INST.a", "asm.INST.b",
            mt="prismatic", axis=[1, 0, 0], limits=[0.0, 50.0],
        )
        elem = _joint_element(m, [0, 0, 0], (0, 0, 0))
        assert elem.get("type") == "prismatic"
        lim = elem.find("limit")
        # 50 mm → 0.05 m.
        assert _almost(float(lim.get("upper")), 0.05)

    def test_axis_normalized(self):
        m = _mate(
            "hinge", "asm.INST.a", "asm.INST.b",
            mt="revolute", axis=[0, 0, 5], limits=[0, 90],
        )
        elem = _joint_element(m, [0, 0, 0], (0, 0, 0))
        # Axis should be normalized to unit length.
        xyz = [float(x) for x in elem.find("axis").get("xyz").split()]
        assert _almost(math.sqrt(sum(c * c for c in xyz)), 1.0)

    def test_origin_xyz_rpy_written(self):
        m = _mate("m", "asm.INST.a", "asm.INST.b")
        elem = _joint_element(m, [1.5, 2.5, 3.5], (0.1, 0.2, 0.3))
        origin = elem.find("origin")
        xyz = [float(x) for x in origin.get("xyz").split()]
        rpy = [float(x) for x in origin.get("rpy").split()]
        assert xyz == [1.5, 2.5, 3.5]
        assert all(_almost(a, b) for a, b in zip(rpy, [0.1, 0.2, 0.3]))


class TestHasLimits:
    def test_none(self):
        assert not _has_limits({"limits": None})

    def test_empty(self):
        assert not _has_limits({"limits": []})

    def test_both_none(self):
        assert not _has_limits({"limits": [None, None]})

    def test_one_side(self):
        assert _has_limits({"limits": [0, None]})
        assert _has_limits({"limits": [None, 10]})

    def test_both(self):
        assert _has_limits({"limits": [0, 10]})


# ── XML parses cleanly ───────────────────────────────────────────────────────

class TestXmlValid:
    def test_joint_element_serializes(self):
        m = _mate("m", "asm.INST.a", "asm.INST.b", mt="revolute", limits=[0, 90])
        elem = _joint_element(m, [0, 0, 0], (0, 0, 0))
        xml = ET.tostring(elem)
        # Must round-trip via parse without error.
        parsed = ET.fromstring(xml)
        assert parsed.tag == "joint"
