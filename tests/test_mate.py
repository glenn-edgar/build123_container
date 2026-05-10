"""Pure-Python tests for mk.mate (no OCP needed)."""
from __future__ import annotations

import math

import pytest

from mk.mate import (
    JOINT_PATH_RE,
    _axis_angle_to_rot,
    _clamp_dof,
    _identity_rot,
    _matmul3,
    _matvec3,
    _parse_joint_path,
    _topo_sort_mates,
)


# ── _parse_joint_path / JOINT_PATH_RE ────────────────────────────────────────

class TestParseJointPath:
    def test_flat(self):
        asm, inst_path, inst, joint = _parse_joint_path(
            "asm_demo.INST.bolt.JOINT.thread_tip"
        )
        assert asm == "asm_demo"
        assert inst_path == "asm_demo.INST.bolt"
        assert inst == "bolt"
        assert joint == "thread_tip"

    def test_one_sub(self):
        asm, inst_path, inst, joint = _parse_joint_path(
            "asm_nested.SUB.group_a.INST.inner_a1.JOINT.face_pos"
        )
        assert asm == "asm_nested"
        assert inst_path == "asm_nested.SUB.group_a.INST.inner_a1"
        assert inst == "inner_a1"
        assert joint == "face_pos"

    def test_deep_nesting(self):
        asm, inst_path, inst, joint = _parse_joint_path(
            "asm_x.SUB.s1.SUB.s2.SUB.s3.INST.deep.JOINT.j"
        )
        assert asm == "asm_x"
        assert inst_path == "asm_x.SUB.s1.SUB.s2.SUB.s3.INST.deep"
        assert inst == "deep"
        assert joint == "j"

    @pytest.mark.parametrize("bad_path", [
        "no_dots",
        "asm.INST.x",                              # missing .JOINT.j
        "asm.WRONG.x.JOINT.j",                     # not INST
        "asm.SUB.s.WRONG.x.JOINT.j",               # broken middle
        "asm.JOINT.j",                             # no INST
        "",
    ])
    def test_rejects_malformed(self, bad_path):
        with pytest.raises(ValueError, match="joint path"):
            _parse_joint_path(bad_path)


# ── matrix helpers ───────────────────────────────────────────────────────────

class TestMatrixMath:
    def test_identity_rot(self):
        I = _identity_rot()
        assert I == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    def test_matmul_identity(self):
        I = _identity_rot()
        M = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        assert _matmul3(I, M) == [
            [1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0],
        ]
        assert _matmul3(M, I) == [
            [1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0],
        ]

    def test_matmul_known(self):
        # 90° rotation about Z
        Rz = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        # Rz @ Rz = 180° about Z
        result = _matmul3(Rz, Rz)
        assert result == [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]]

    def test_matvec_identity(self):
        I = _identity_rot()
        assert _matvec3(I, [1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]

    def test_matvec_rotation(self):
        # 90° about Z takes +X to +Y
        Rz = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        assert _matvec3(Rz, [1.0, 0.0, 0.0]) == [0.0, 1.0, 0.0]


# ── topo sort ────────────────────────────────────────────────────────────────

def _mate(name: str, a_path: str, b_path: str) -> dict:
    """Build a minimal parsed-mate dict for topo-sort testing."""
    return {
        "name": name,
        "a_path": a_path, "a_name": a_path.split(".")[-1], "joint_a_name": "j",
        "b_path": b_path, "b_name": b_path.split(".")[-1], "joint_b_name": "j",
    }


class TestTopoSort:
    def test_empty(self):
        assert _topo_sort_mates([]) == []

    def test_single(self):
        m = _mate("only", "asm.INST.a", "asm.INST.b")
        assert _topo_sort_mates([m]) == [m]

    def test_independent_mates_preserve_input_order(self):
        # Two roots — neither depends on the other.
        m1 = _mate("m1", "asm.INST.a", "asm.INST.root1")
        m2 = _mate("m2", "asm.INST.b", "asm.INST.root2")
        result = _topo_sort_mates([m1, m2])
        # Input order is fine since neither has a dependency.
        assert {r["name"] for r in result} == {"m1", "m2"}
        assert len(result) == 2

    def test_chain_in_dependency_order(self):
        # c→b, b→a: must process b first then c, regardless of input order.
        c_to_b = _mate("zzz_c", "asm.INST.c", "asm.INST.b")
        b_to_a = _mate("aaa_b", "asm.INST.b", "asm.INST.a")
        # Input in REVERSE dep order:
        result = _topo_sort_mates([c_to_b, b_to_a])
        assert [r["name"] for r in result] == ["aaa_b", "zzz_c"]

    def test_branching(self):
        # tree: b→a, c→a (b and c both depend on a being root).
        # a is unmated, both b and c can run after a — but a doesn't appear as joint_a anywhere.
        b = _mate("b", "asm.INST.b", "asm.INST.a")
        c = _mate("c", "asm.INST.c", "asm.INST.a")
        result = _topo_sort_mates([b, c])
        assert {r["name"] for r in result} == {"b", "c"}

    def test_overconstraint_same_inst_as_a_in_two_mates(self):
        m1 = _mate("m1", "asm.INST.a", "asm.INST.x")
        m2 = _mate("m2", "asm.INST.a", "asm.INST.y")
        with pytest.raises(ValueError, match="over-constraint"):
            _topo_sort_mates([m1, m2])

    def test_cycle_detection(self):
        # a→b, b→a forms a 2-cycle.
        m1 = _mate("a_to_b", "asm.INST.a", "asm.INST.b")
        m2 = _mate("b_to_a", "asm.INST.b", "asm.INST.a")
        with pytest.raises(ValueError, match="cycle"):
            _topo_sort_mates([m1, m2])

    def test_sub_paths_distinct_keys(self):
        # Two insts with same leaf name but different SUB scopes —
        # must be treated as distinct keys.
        m1 = _mate(
            "m1",
            "asm.SUB.x.INST.foo",
            "asm.SUB.x.INST.bar",
        )
        m2 = _mate(
            "m2",
            "asm.SUB.y.INST.foo",        # same leaf 'foo' but different SUB
            "asm.SUB.y.INST.baz",
        )
        # No over-constraint despite both having joint_a leaf == "foo".
        result = _topo_sort_mates([m1, m2])
        assert len(result) == 2


# ── axis-angle rotation (Rodrigues) ──────────────────────────────────────────

def _almost_equal(a, b, tol=1e-9):
    return abs(a - b) < tol


def _mat_almost_equal(A, B, tol=1e-9):
    return all(_almost_equal(A[i][j], B[i][j], tol) for i in range(3) for j in range(3))


class TestAxisAngleRot:
    def test_zero_angle_is_identity(self):
        R = _axis_angle_to_rot([1, 0, 0], 0.0)
        assert _mat_almost_equal(R, _identity_rot())

    def test_zero_axis_returns_identity(self):
        R = _axis_angle_to_rot([0, 0, 0], math.pi)
        assert R == _identity_rot()

    def test_180_about_z(self):
        # Rotation by 180° about +Z: takes +X to -X, +Y to -Y, +Z stays.
        R = _axis_angle_to_rot([0, 0, 1], math.pi)
        v = _matvec3(R, [1.0, 0.0, 0.0])
        assert _almost_equal(v[0], -1.0)
        assert _almost_equal(v[1], 0.0, tol=1e-12)
        assert _almost_equal(v[2], 0.0, tol=1e-12)
        v = _matvec3(R, [0.0, 1.0, 0.0])
        assert _almost_equal(v[1], -1.0)

    def test_90_about_y_takes_x_to_minus_z(self):
        # Right-hand rule: +90° about +Y takes +X to -Z.
        R = _axis_angle_to_rot([0, 1, 0], math.pi / 2)
        v = _matvec3(R, [1.0, 0.0, 0.0])
        assert _almost_equal(v[0], 0.0, tol=1e-12)
        assert _almost_equal(v[1], 0.0, tol=1e-12)
        assert _almost_equal(v[2], -1.0)

    def test_axis_normalized(self):
        # Non-unit axis should give same result as unit axis.
        R1 = _axis_angle_to_rot([0, 0, 1], math.pi / 4)
        R2 = _axis_angle_to_rot([0, 0, 5], math.pi / 4)  # axis * 5
        assert _mat_almost_equal(R1, R2, tol=1e-12)

    def test_full_rotation_returns_identity(self):
        R = _axis_angle_to_rot([1, 1, 1], 2 * math.pi)
        assert _mat_almost_equal(R, _identity_rot(), tol=1e-9)


# ── DOF clamping ─────────────────────────────────────────────────────────────

class TestClampDof:
    def test_no_limits_passes_through(self, capsys):
        assert _clamp_dof(42.0, None, "m", "deg") == 42.0
        assert capsys.readouterr().out == ""

    def test_within_range(self, capsys):
        assert _clamp_dof(45.0, [0.0, 90.0], "m", "deg") == 45.0
        assert capsys.readouterr().out == ""

    def test_below_lower_clamps(self, capsys):
        assert _clamp_dof(-10.0, [0.0, 90.0], "hinge", "deg") == 0.0
        assert "WARN" in capsys.readouterr().out

    def test_above_upper_clamps(self, capsys):
        assert _clamp_dof(120.0, [0.0, 90.0], "hinge", "deg") == 90.0
        assert "WARN" in capsys.readouterr().out

    def test_one_sided_lower_only(self):
        assert _clamp_dof(50.0, [0.0, None], "m", "mm") == 50.0
        assert _clamp_dof(-5.0, [0.0, None], "m", "mm") == 0.0

    def test_one_sided_upper_only(self):
        assert _clamp_dof(50.0, [None, 100.0], "m", "mm") == 50.0
        assert _clamp_dof(150.0, [None, 100.0], "m", "mm") == 100.0


# ── state-loading helper ─────────────────────────────────────────────────────

class TestLoadState:
    """mk.commands.build._load_state — JSON file → dict[mate_name, value]."""

    def _args(self, tmp_path, **overrides):
        import argparse
        ns = argparse.Namespace(asm_kb="asm_x", state=None, outdir=str(tmp_path))
        for k, v in overrides.items():
            setattr(ns, k, v)
        return ns

    def test_missing_default_path(self, tmp_path):
        from mk.commands.build import _load_state
        # Default outdir/<asm>/state.json doesn't exist.
        assert _load_state(self._args(tmp_path)) == {}

    def test_explicit_path_missing(self, tmp_path):
        from mk.commands.build import _load_state
        ns = self._args(tmp_path, state=str(tmp_path / "no_such.json"))
        assert _load_state(ns) == {}

    def test_default_path(self, tmp_path):
        from mk.commands.build import _load_state
        sub = tmp_path / "asm_x"
        sub.mkdir()
        (sub / "state.json").write_text('{"hinge": 30.0, "slide": 5}')
        result = _load_state(self._args(tmp_path))
        assert result == {"hinge": 30.0, "slide": 5.0}

    def test_explicit_path_wins(self, tmp_path):
        from mk.commands.build import _load_state
        # Default would find this:
        sub = tmp_path / "asm_x"
        sub.mkdir()
        (sub / "state.json").write_text('{"a": 1}')
        # But explicit overrides:
        explicit = tmp_path / "elsewhere.json"
        explicit.write_text('{"b": 2}')
        ns = self._args(tmp_path, state=str(explicit))
        assert _load_state(ns) == {"b": 2.0}

    def test_empty_file_is_empty_dict(self, tmp_path):
        from mk.commands.build import _load_state
        sub = tmp_path / "asm_x"
        sub.mkdir()
        (sub / "state.json").write_text("")
        assert _load_state(self._args(tmp_path)) == {}

    def test_non_object_rejected(self, tmp_path):
        from mk.commands.build import _load_state
        sub = tmp_path / "asm_x"
        sub.mkdir()
        (sub / "state.json").write_text('[1, 2, 3]')
        with pytest.raises(ValueError, match="JSON object"):
            _load_state(self._args(tmp_path))

    def test_non_numeric_value_rejected(self, tmp_path):
        from mk.commands.build import _load_state
        sub = tmp_path / "asm_x"
        sub.mkdir()
        (sub / "state.json").write_text('{"hinge": "forty"}')
        with pytest.raises(ValueError, match="must be a number"):
            _load_state(self._args(tmp_path))
