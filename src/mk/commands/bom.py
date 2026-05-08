# SPDX-License-Identifier: LGPL-2.1-or-later
"""mk bom <asm-kb>: flat BOM by counting INST rows grouped by ref_kb."""
from __future__ import annotations

import argparse

from mk.db import DEFAULT_DB_PATH, open_db


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("bom", help="Flat BOM for an assembly KB.")
    p.add_argument("asm_kb", help="assembly KB name, e.g. asm_demo")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    rows = conn.execute(
        """
        SELECT json_extract(properties, '$.ref_kb') AS part, COUNT(*) AS qty
        FROM knowledge_base
        WHERE knowledge_base = ? AND label = 'INST'
        GROUP BY part
        ORDER BY qty DESC, part
        """,
        (args.asm_kb,),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"no INST rows in {args.asm_kb}")
        return 0

    width = max(len(r["part"]) for r in rows)
    print(f"{'part'.ljust(width)}  qty")
    print(f"{'-' * width}  ---")
    for r in rows:
        print(f"{r['part'].ljust(width)}  {r['qty']:>3}")
    return 0
