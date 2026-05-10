# SPDX-License-Identifier: MPL-2.0
"""Rigid mate solver (Phase 6, with chain composition + topo-sort).

For each MATE row in an assembly KB:
- joint_a and joint_b are full ltree paths of the form
  ``<asm>[.SUB.<sub>...].INST.<inst>.JOINT.<joint>`` (any number of nested
  SUB segments allowed; flat case has zero).
- The joint frames are looked up in the inst's referenced part KB.
- The "rigid" mate aligns frame A so that:
    A_world.origin == B_world.origin
    A_world.z_dir  == -B_world.z_dir   (opposing surfaces touch)
- The result is composed with joint_b's INST's already-resolved world
  transform, so chains of mates produce correct world coords. Inst A's
  ``location`` is written back as ``{"loc": [...], "rot": [[...]]}``.

Mates are processed in **topological order** of their inst-dependency
graph (mate M depends on mate M' if M's joint_b inst is M'.s joint_a inst).
Naming discipline isn't required. Cycles and over-constraints raise
ValueError before any DB write.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

# Match ``<asm>[.SUB.<sub>]*.INST.<inst>.JOINT.<joint>``. The full inst path
# (everything up to ``.JOINT.<joint>``) is captured so we can look up the
# INST row by path and disambiguate same-named insts in different SUB scopes.
JOINT_PATH_RE = re.compile(
    r"^(?P<inst_path>"
    r"(?P<asm>[^.]+)"
    r"(?:\.SUB\.[^.]+)*"
    r"\.INST\.(?P<inst>[^.]+)"
    r")"
    r"\.JOINT\.(?P<joint>[^.]+)$"
)


def _parse_joint_path(path: str) -> tuple[str, str, str, str]:
    """Return ``(asm, inst_path, inst_name, joint_name)``.

    - ``asm`` — the assembly KB name (root segment).
    - ``inst_path`` — the full ltree path of the INST row (lookup key).
    - ``inst_name`` — the leaf INST name (last segment after ``INST.``);
      used for human-readable verbose logging only.
    - ``joint_name`` — the joint's ``name`` field in the part KB.
    """
    m = JOINT_PATH_RE.match(path)
    if not m:
        raise ValueError(
            f"joint path not in "
            f"'<asm>[.SUB.<s>]*.INST.<inst>.JOINT.<joint>' form: {path!r}"
        )
    return m["asm"], m["inst_path"], m["inst"], m["joint"]


def _read_inst_ref_kb(conn: sqlite3.Connection, asm_kb: str, inst_path: str) -> str:
    """Look up an INST row by full ltree path. Path is the disambiguating
    key — leaf names alone collide across SUB scopes.
    """
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' AND path = ?",
        (asm_kb, inst_path),
    ).fetchone()
    if row is None:
        raise ValueError(f"INST at path {inst_path!r} not found in {asm_kb!r}")
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




def _topo_sort_mates(parsed: list[dict]) -> list[dict]:
    """Sort mate dicts in dependency order.

    A mate M depends on M' iff M's joint_b inst path equals M'.s joint_a inst
    path (M needs M''s INST already positioned). Each inst can be joint_a in
    at most one mate (over-constraint detection). Cycles raise ValueError.

    Returns parsed in topo order. Insts not appearing as joint_a anywhere
    are at world identity; mates whose joint_b inst is one of those have
    no incoming edges and start the queue.
    """
    from collections import deque

    # inst_path → index of the mate that resolves it (where it's joint_a).
    resolves: dict[str, int] = {}
    for i, m in enumerate(parsed):
        a_path = m["a_path"]
        if a_path in resolves:
            other = parsed[resolves[a_path]]["name"]
            raise ValueError(
                f"mate over-constraint: inst {a_path!r} is joint_a in both "
                f"mates {other!r} and {m['name']!r}"
            )
        resolves[a_path] = i

    # Edges: for each mate, the mate that resolves its joint_b inst (if any)
    # must come before it.
    in_degree = [0] * len(parsed)
    children: list[list[int]] = [[] for _ in parsed]
    for i, m in enumerate(parsed):
        b_resolver = resolves.get(m["b_path"])
        if b_resolver is not None:
            children[b_resolver].append(i)
            in_degree[i] += 1

    queue = deque(i for i, d in enumerate(in_degree) if d == 0)
    order: list[int] = []
    while queue:
        i = queue.popleft()
        order.append(i)
        for j in children[i]:
            in_degree[j] -= 1
            if in_degree[j] == 0:
                queue.append(j)

    if len(order) < len(parsed):
        cyclic = sorted(
            parsed[i]["name"] for i, d in enumerate(in_degree) if d > 0
        )
        raise ValueError(
            f"mate cycle detected — these mates form a circular dependency: "
            f"{cyclic}. Each inst can have at most one parent in the mate tree."
        )
    return [parsed[i] for i in order]


def solve_assembly(conn: sqlite3.Connection, asm_kb: str, *, verbose: bool = False) -> int:
    """Resolve all rigid mates in the assembly. Returns count processed.

    Each mate produces inst_a's transform relative to inst_b's local frame.
    The result is composed with inst_b's already-resolved world transform
    so chains land in correct world coords. Mates fire in topological
    order of the inst-dependency graph; cycles raise ValueError.
    """
    mate_rows = conn.execute(
        "SELECT name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'MATE'",
        (asm_kb,),
    ).fetchall()

    # Parse all mates upfront so the topo sort can see the dependency graph.
    parsed: list[dict] = []
    for r in mate_rows:
        p = json.loads(r["properties"])
        if p.get("mate_type", "rigid") != "rigid":
            print(
                f"  skip mate {r['name']!r}: "
                f"type {p.get('mate_type')!r} (Phase 6 = rigid only)"
            )
            continue
        _, a_path, a_name, joint_a_name = _parse_joint_path(p["joint_a"])
        _, b_path, b_name, joint_b_name = _parse_joint_path(p["joint_b"])
        parsed.append({
            "name": r["name"],
            "a_path": a_path, "a_name": a_name, "joint_a_name": joint_a_name,
            "b_path": b_path, "b_name": b_name, "joint_b_name": joint_b_name,
        })

    if not parsed:
        return 0

    parsed = _topo_sort_mates(parsed)

    # Track world transforms resolved in this pass so chain composition is
    # idempotent across repeated `mk build` calls (we never read stale
    # locations back from the DB).
    resolved: dict[str, tuple[list[list[float]], list[float]]] = {}

    n_solved = 0
    for m in parsed:
        a_path = m["a_path"]
        b_path = m["b_path"]
        a_name = m["a_name"]
        b_name = m["b_name"]
        joint_a_name = m["joint_a_name"]
        joint_b_name = m["joint_b_name"]

        ref_a = _read_inst_ref_kb(conn, asm_kb, a_path)
        ref_b = _read_inst_ref_kb(conn, asm_kb, b_path)

        ja_origin, ja_zdir = _read_joint_frame(conn, ref_a, joint_a_name)
        jb_origin, jb_zdir = _read_joint_frame(conn, ref_b, joint_b_name)

        # Rotation/translation of inst_a relative to inst_b's local frame.
        rel_rot, rel_trans = _solve_rigid(ja_origin, ja_zdir, jb_origin, jb_zdir)

        # Compose with inst_b's already-resolved world transform:
        #   T_a_world = T_b_world ∘ T_a_rel_to_b
        # As (R, t):  (R_b R_rel,  R_b @ t_rel + t_b)
        # Insts not yet resolved (e.g., the chain root) are at identity.
        # Keyed by inst PATH so SUB-nested chains compose correctly.
        b_rot, b_trans = resolved.get(b_path, (_identity_rot(), [0.0, 0.0, 0.0]))
        composed_rot = _matmul3(b_rot, rel_rot)
        composed_trans = [
            x + y for x, y in zip(_matvec3(b_rot, rel_trans), b_trans, strict=True)
        ]
        resolved[a_path] = (composed_rot, composed_trans)

        a_props = json.loads(
            conn.execute(
                "SELECT properties FROM knowledge_base "
                "WHERE knowledge_base = ? AND label = 'INST' AND path = ?",
                (asm_kb, a_path),
            ).fetchone()["properties"]
        )
        a_props["location"] = {"loc": composed_trans, "rot": composed_rot}
        conn.execute(
            "UPDATE knowledge_base SET properties = ? "
            "WHERE knowledge_base = ? AND label = 'INST' AND path = ?",
            (json.dumps(a_props), asm_kb, a_path),
        )
        if verbose:
            print(
                f"  mate {m['name']}: {a_name}.{joint_a_name} ↔ "
                f"{b_name}.{joint_b_name}"
            )
            print(
                f"    world loc=({composed_trans[0]:.3f}, "
                f"{composed_trans[1]:.3f}, {composed_trans[2]:.3f})"
            )
        n_solved += 1

    conn.commit()
    return n_solved
