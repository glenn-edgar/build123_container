# SPDX-License-Identifier: MPL-2.0
"""Rigid mate solver (Phase 6).

For each MATE row in an assembly KB:
- joint_a and joint_b are full ltree paths of the form
  ``<asm>.INST.<inst>.JOINT.<joint>``.
- The joint frames are looked up in the inst's referenced part KB.
- The "rigid" mate aligns frame A so that:
    A_world.origin == B_world.origin
    A_world.z_dir  == -B_world.z_dir   (opposing surfaces touch)
- B is treated as the fixed reference (identity placement). Inst A's
  ``location`` is written back as ``{"loc": [...], "rot": [[...]]}``.

Multi-mate chains are processed in path order. This is a prototype that does
**not** detect cycles or solve coupled constraint systems.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

JOINT_PATH_RE = re.compile(
    r"^(?P<asm>[^.]+)\.INST\.(?P<inst>[^.]+)\.JOINT\.(?P<joint>[^.]+)$"
)


def _parse_joint_path(path: str) -> tuple[str, str, str]:
    m = JOINT_PATH_RE.match(path)
    if not m:
        raise ValueError(
            f"joint path not in '<asm>.INST.<inst>.JOINT.<joint>' form: {path!r}"
        )
    return m["asm"], m["inst"], m["joint"]


def _read_inst_ref_kb(conn: sqlite3.Connection, asm_kb: str, inst_name: str) -> str:
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' AND name = ?",
        (asm_kb, inst_name),
    ).fetchone()
    if row is None:
        raise ValueError(f"INST {inst_name!r} not found in {asm_kb!r}")
    return json.loads(row["properties"])["ref_kb"]


def _read_joint_frame(
    conn: sqlite3.Connection, part_kb: str, joint_name: str
) -> tuple[list[float], list[float]]:
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'JOINT' AND name = ?",
        (part_kb, joint_name),
    ).fetchone()
    if row is None:
        raise ValueError(f"JOINT {joint_name!r} not found in part {part_kb!r}")
    p = json.loads(row["properties"])
    origin = [float(x) for x in p["origin"]]
    z_dir = [float(x) for x in p.get("z_dir", [0.0, 0.0, 1.0])]
    return origin, z_dir


def _solve_rigid(
    ja_origin: list[float],
    ja_zdir: list[float],
    jb_origin: list[float],
    jb_zdir: list[float],
) -> tuple[list[list[float]], list[float]]:
    """Compute (rotation, translation) that places A's joint coincident with B's,
    with z axes opposing. B is fixed at identity."""
    from OCP.gp import gp_Quaternion, gp_Trsf, gp_Vec

    a_z = gp_Vec(*ja_zdir)
    b_z_neg = gp_Vec(*jb_zdir).Reversed()

    q = gp_Quaternion()
    q.SetRotation(a_z, b_z_neg)
    rot_trsf = gp_Trsf()
    rot_trsf.SetRotation(q)

    rot = [[rot_trsf.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)]
    rotated_a = [
        rot[0][0] * ja_origin[0] + rot[0][1] * ja_origin[1] + rot[0][2] * ja_origin[2],
        rot[1][0] * ja_origin[0] + rot[1][1] * ja_origin[1] + rot[1][2] * ja_origin[2],
        rot[2][0] * ja_origin[0] + rot[2][1] * ja_origin[1] + rot[2][2] * ja_origin[2],
    ]
    translation = [
        jb_origin[0] - rotated_a[0],
        jb_origin[1] - rotated_a[1],
        jb_origin[2] - rotated_a[2],
    ]
    return rot, translation


def _matmul3(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """3x3 matrix multiply: a @ b."""
    return [
        [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
        for i in range(3)
    ]


def _matvec3(a: list[list[float]], v: list[float]) -> list[float]:
    """3x3 × 3-vector."""
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def _identity_rot() -> list[list[float]]:
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]




def solve_assembly(conn: sqlite3.Connection, asm_kb: str, *, verbose: bool = False) -> int:
    """Resolve all rigid mates in the assembly. Returns count processed.

    Each mate produces inst_a's transform *relative to inst_b's local frame*.
    To get absolute world transforms, we compose with inst_b's already-resolved
    location (which reflects any prior mates in the chain). Mates are processed
    in path order — name them with a leading dependency-prefix so joint_b's
    inst is always positioned before joint_a's needs to be.
    """
    mates = conn.execute(
        "SELECT name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'MATE' ORDER BY path",
        (asm_kb,),
    ).fetchall()

    # Track world transforms resolved in this pass so chain composition is
    # idempotent across repeated `mk build` calls (we never read stale
    # locations back from the DB).
    resolved: dict[str, tuple[list[list[float]], list[float]]] = {}

    n_solved = 0
    for m in mates:
        p = json.loads(m["properties"])
        mate_type = p.get("mate_type", "rigid")
        if mate_type != "rigid":
            print(f"  skip mate {m['name']!r}: type {mate_type!r} (Phase 6 = rigid only)")
            continue

        _, inst_a_name, joint_a_name = _parse_joint_path(p["joint_a"])
        _, inst_b_name, joint_b_name = _parse_joint_path(p["joint_b"])

        ref_a = _read_inst_ref_kb(conn, asm_kb, inst_a_name)
        ref_b = _read_inst_ref_kb(conn, asm_kb, inst_b_name)

        ja_origin, ja_zdir = _read_joint_frame(conn, ref_a, joint_a_name)
        jb_origin, jb_zdir = _read_joint_frame(conn, ref_b, joint_b_name)

        # Rotation/translation of inst_a relative to inst_b's local frame.
        rel_rot, rel_trans = _solve_rigid(ja_origin, ja_zdir, jb_origin, jb_zdir)

        # Compose with inst_b's already-resolved world transform:
        #   T_a_world = T_b_world ∘ T_a_rel_to_b
        # As (R, t):  (R_b R_rel,  R_b @ t_rel + t_b)
        # Insts not yet resolved (e.g., the chain root mated to "the sheet")
        # are treated as identity.
        b_rot, b_trans = resolved.get(inst_b_name, (_identity_rot(), [0.0, 0.0, 0.0]))
        composed_rot = _matmul3(b_rot, rel_rot)
        composed_trans = [
            x + y for x, y in zip(_matvec3(b_rot, rel_trans), b_trans, strict=True)
        ]
        resolved[inst_a_name] = (composed_rot, composed_trans)

        a_row = conn.execute(
            "SELECT properties FROM knowledge_base "
            "WHERE knowledge_base = ? AND label = 'INST' AND name = ?",
            (asm_kb, inst_a_name),
        ).fetchone()
        a_props = json.loads(a_row["properties"])
        a_props["location"] = {"loc": composed_trans, "rot": composed_rot}
        conn.execute(
            "UPDATE knowledge_base SET properties = ? "
            "WHERE knowledge_base = ? AND label = 'INST' AND name = ?",
            (json.dumps(a_props), asm_kb, inst_a_name),
        )
        if verbose:
            print(
                f"  mate {m['name']}: {inst_a_name}.{joint_a_name} ↔ {inst_b_name}.{joint_b_name}"
            )
            print(
                f"    world loc=({composed_trans[0]:.3f}, "
                f"{composed_trans[1]:.3f}, {composed_trans[2]:.3f})"
            )
        n_solved += 1

    conn.commit()
    return n_solved
