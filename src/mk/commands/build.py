# SPDX-License-Identifier: MPL-2.0
"""mk build <asm-kb>: walk INST rows, exec builders, cache BREP, set geom_hash."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mk.builder import get_part_defaults, run_builder
from mk.db import DEFAULT_DB_PATH, open_db
from mk.geometry import geometry_hash, shape_to_brep_bytes, shape_to_step_bytes
from mk.mate import solve_assembly

DEFAULT_OUTDIR = "/project/outputs"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("build", help="Build geometry for an assembly KB.")
    p.add_argument("asm_kb", help="assembly KB name, e.g. asm_demo")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument(
        "--state",
        default=None,
        help=(
            "path to a JSON file with revolute/prismatic DOF overrides "
            "({\"<mate_name>\": value, ...}). Defaults to "
            "<outdir>/<asm_kb>/state.json if it exists."
        ),
    )
    p.add_argument("--outdir", default=DEFAULT_OUTDIR,
                   help="used to find the default state.json")
    p.set_defaults(func=run)


def _load_state(args: argparse.Namespace) -> dict[str, float]:
    """Load DOF state overrides from a JSON file. Format: ``{mate_name: val}``.

    Explicit ``--state <path>`` takes precedence; otherwise looks for
    ``<outdir>/<asm_kb>/state.json``. Missing files = empty dict (no
    overrides). Malformed files raise.
    """
    if args.state:
        path = Path(args.state)
    else:
        path = Path(args.outdir) / args.asm_kb / "state.json"
    if not path.exists():
        return {}
    text = path.read_text()
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"state file {path} must be a JSON object, got {type(data).__name__}")
    # Coerce to floats; reject malformed entries.
    out: dict[str, float] = {}
    for k, v in data.items():
        if not isinstance(v, (int, float)):
            raise ValueError(
                f"state file {path}: mate {k!r} value must be a number, got {type(v).__name__}"
            )
        out[k] = float(v)
    return out


def run(args: argparse.Namespace) -> int:
    conn = open_db(args.db)

    state = _load_state(args)
    if state:
        print(f"loaded state.json: {len(state)} mate override(s)")

    n_mates = solve_assembly(conn, args.asm_kb, verbose=True, state_overrides=state)
    if n_mates:
        print(f"resolved {n_mates} mate(s)")

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
