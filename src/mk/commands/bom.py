# SPDX-License-Identifier: MPL-2.0
"""mk bom <asm-kb>: flat BOM by counting INST rows grouped by ref_kb."""
from __future__ import annotations

import argparse

from mk.db import DEFAULT_DB_PATH, kb_exists, open_db


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("bom", help="Flat BOM for an assembly KB.")
    p.add_argument("asm_kb", help="assembly KB name, e.g. asm_demo")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument(
        "--respect-layers", action="store_true",
        help="exclude insts on hidden layers (default: include all — "
             "BOMs shouldn't change with viewer state)",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    import json
    import sys
    conn = open_db(args.db)

    if not kb_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    inst_rows = conn.execute(
        "SELECT path, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (args.asm_kb,),
    ).fetchall()

    if args.respect_layers and inst_rows:
        from mk.layers import partition_by_visibility
        inst_rows, hidden_count = partition_by_visibility(conn, args.asm_kb, inst_rows)
        if hidden_count > 0:
            print(f"  layer filter: {hidden_count} hidden inst(s) excluded from BOM")

    conn.close()

    if not inst_rows:
        print(f"{args.asm_kb} has no INST rows")
        return 0

    counts: dict[str, int] = {}
    for r in inst_rows:
        part = json.loads(r["properties"]).get("ref_kb")
        counts[part] = counts.get(part, 0) + 1

    sorted_rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    width = max(len(p) for p, _ in sorted_rows)
    print(f"{'part'.ljust(width)}  qty")
    print(f"{'-' * width}  ---")
    for part, qty in sorted_rows:
        print(f"{part.ljust(width)}  {qty:>3}")
    return 0
