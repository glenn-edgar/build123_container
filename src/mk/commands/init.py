# SPDX-License-Identifier: LGPL-2.1-or-later
"""mk init: create or verify the project DB."""
from __future__ import annotations

import argparse
import sys

from mk.db import DEFAULT_DB_PATH, ensure_schema, open_db, verify_ltree


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("init", help="Create or verify the project DB.")
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to project.db")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    ensure_schema(conn)
    if not verify_ltree(conn):
        print("ltree extension loaded but verification call failed", file=sys.stderr)
        return 1
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    print(f"DB ready at {args.db}")
    print(f"  tables: {', '.join(tables)}")
    print("  ltree: ok")
    conn.close()
    return 0
