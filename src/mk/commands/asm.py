# SPDX-License-Identifier: MPL-2.0
"""mk asm tree: render an assembly subtree as ASCII."""
from __future__ import annotations

import argparse
import json
import sys

from mk.db import DEFAULT_DB_PATH, open_db


def add_parser(subparsers) -> None:
    asm = subparsers.add_parser("asm", help="Assembly inspection.")
    asm_sub = asm.add_subparsers(dest="asm_cmd", required=True)

    lst = asm_sub.add_parser("list", help="List assembly KBs.")
    lst.add_argument("--prefix", default="asm_", help="kb_name prefix filter")
    lst.add_argument("--db", default=DEFAULT_DB_PATH)
    lst.set_defaults(func=run_list)

    tree = asm_sub.add_parser("tree", help="ASCII tree of an assembly KB.")
    tree.add_argument("kb_name", help="assembly KB name, e.g. asm_demo")
    tree.add_argument("--db", default=DEFAULT_DB_PATH)
    tree.set_defaults(func=run_tree)


def run_list(args: argparse.Namespace) -> int:
    """Mirror of mk part list: enumerate kb_name + description for every
    KB whose name starts with ``--prefix`` (default ``asm_``).
    """
    conn = open_db(args.db)
    rows = conn.execute(
        "SELECT knowledge_base, description FROM knowledge_base_info "
        "WHERE knowledge_base LIKE ? ORDER BY knowledge_base",
        (args.prefix + "%",),
    ).fetchall()
    if not rows:
        print(f"no assemblies matching prefix '{args.prefix}'")
        return 0
    for r in rows:
        desc = r["description"] or ""
        print(f"{r['knowledge_base']}\t{desc}")
    conn.close()
    return 0


def run_tree(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    rows = conn.execute(
        "SELECT path, label, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? ORDER BY path",
        (args.kb_name,),
    ).fetchall()

    info = conn.execute(
        "SELECT description FROM knowledge_base_info WHERE knowledge_base = ?",
        (args.kb_name,),
    ).fetchone()

    if info is None and not rows:
        print(f"no such assembly: {args.kb_name}", file=sys.stderr)
        return 1

    desc = (info["description"] if info else "") or ""
    header = f"{args.kb_name}" + (f"  — {desc}" if desc else "")
    print(header)

    for row in rows:
        path = row["path"]
        # depth = segments minus the kb_name root
        depth = path.count(".")
        indent = "  " * (depth - 1) if depth > 0 else ""
        props = json.loads(row["properties"]) if row["properties"] else {}
        suffix = _format_suffix(row["label"], row["name"], props)
        print(f"{indent}{row['label']}.{row['name']}{suffix}")

    conn.close()
    return 0


def _format_suffix(label: str, name: str, props: dict) -> str:
    if label == "INST":
        ref = props.get("ref_kb", "?")
        extra = ""
        if "params_override" in props:
            extra += f" overrides={props['params_override']}"
        return f"  ← {ref}{extra}"
    if label == "MATE":
        return f"  {props.get('joint_a', '?')} ↔ {props.get('joint_b', '?')}"
    return ""
