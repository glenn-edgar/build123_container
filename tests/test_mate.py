"""Pure-Python tests for mk.mate (no OCP needed)."""
from __future__ import annotations

import pytest

from mk.mate import (
    JOINT_PATH_RE,
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
