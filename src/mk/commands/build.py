# SPDX-License-Identifier: MPL-2.0
"""mk build <asm-kb>: walk INST rows, exec builders, cache BREP, set geom_hash."""
from __future__ import annotations

import argparse
import json
import sys

from mk.builder import get_part_defaults, run_builder
from mk.db import DEFAULT_DB_PATH, open_db
from mk.geometry import geometry_hash, shape_to_brep_bytes, shape_to_step_bytes
from mk.mate import solve_assembly


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("build", help="Build geometry for an assembly KB.")
    p.add_argument("asm_kb", help="assembly KB name, e.g. asm_demo")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    conn = open_db(args.db)

    n_mates = solve_assembly(conn, args.asm_kb, verbose=True)
    if n_mates:
        print(f"resolved {n_mates} rigid mate(s)")

    rows = conn.execute(
        "SELECT path, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (args.asm_kb,),
    ).fetchall()

    if not rows:
        print(f"no INST rows in {args.asm_kb}", file=sys.stderr)
        return 1

    n_built = 0
    n_cached = 0
    for r in rows:
        props = json.loads(r["properties"])
        ref_kb = props.get("ref_kb")
        if not ref_kb:
            print(f"  WARN: {r['path']} has no ref_kb; skipping", file=sys.stderr)
            continue
        params_override = props.get("params_override", {})

        defaults = get_part_defaults(conn, ref_kb)
        params = {**defaults, **params_override}

        shape = run_builder(conn, ref_kb, params)
        step_bytes = shape_to_step_bytes(shape)
        gh = geometry_hash(step_bytes)

        existing = conn.execute(
            "SELECT 1 FROM geometry WHERE hash = ?", (gh,)
        ).fetchone()
        if existing is None:
            brep = shape_to_brep_bytes(shape)
            conn.execute(
                "INSERT INTO geometry (hash, brep_blob) VALUES (?, ?)",
                (gh, brep),
            )
            n_cached += 1

        props["geom_hash"] = gh
        conn.execute(
            "UPDATE knowledge_base SET properties = ? WHERE path = ?",
            (json.dumps(props), r["path"]),
        )
        print(f"  {r['path']}  ←  {ref_kb}  →  {gh[:12]}")
        n_built += 1

    conn.commit()
    conn.close()
    print(f"built {n_built} instance(s); {n_cached} new BREP blob(s) cached")
    return 0
