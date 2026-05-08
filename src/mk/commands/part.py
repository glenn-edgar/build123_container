# SPDX-License-Identifier: LGPL-2.1-or-later
"""mk part list / mk part show."""
from __future__ import annotations

import argparse
import json
import sys

from mk.db import DEFAULT_DB_PATH, open_db


def add_parser(subparsers) -> None:
    part = subparsers.add_parser("part", help="Part inspection.")
    part_sub = part.add_subparsers(dest="part_cmd", required=True)

    lst = part_sub.add_parser("list", help="List part KBs.")
    lst.add_argument("--prefix", default="part_", help="kb_name prefix filter")
    lst.add_argument("--db", default=DEFAULT_DB_PATH)
    lst.set_defaults(func=run_list)

    show = part_sub.add_parser("show", help="Show a part KB's contents.")
    show.add_argument("kb_name")
    show.add_argument("--db", default=DEFAULT_DB_PATH)
    show.set_defaults(func=run_show)


def run_list(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    rows = conn.execute(
        "SELECT knowledge_base, description FROM knowledge_base_info "
        "WHERE knowledge_base LIKE ? ORDER BY knowledge_base",
        (args.prefix + "%",),
    ).fetchall()
    if not rows:
        print(f"no parts matching prefix '{args.prefix}'")
        return 0
    for r in rows:
        desc = r["description"] or ""
        print(f"{r['knowledge_base']}\t{desc}")
    conn.close()
    return 0


def run_show(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    info = conn.execute(
        "SELECT description FROM knowledge_base_info WHERE knowledge_base = ?",
        (args.kb_name,),
    ).fetchone()
    if info is None:
        print(f"no such part: {args.kb_name}", file=sys.stderr)
        return 1

    rows = conn.execute(
        "SELECT label, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? ORDER BY label, name",
        (args.kb_name,),
    ).fetchall()

    print(f"{args.kb_name}" + (f"  — {info['description']}" if info["description"] else ""))
    for r in rows:
        props = json.loads(r["properties"]) if r["properties"] else {}
        if r["label"] == "PART":
            entry = props.get("entry", "?")
            n_lines = len(props.get("source", "").splitlines())
            print(f"  PART.{r['name']}: entry={entry}, source={n_lines} lines")
        elif r["label"] == "PARAM":
            print(f"  PARAM.{r['name']} = {props.get('value')!r} ({props.get('type','?')})")
        elif r["label"] == "JOINT":
            origin = props.get("origin")
            print(f"  JOINT.{r['name']}: origin={origin}")
        elif r["label"] == "META":
            print(f"  META.{r['name']} = {props.get('value')!r}")
        else:
            print(f"  {r['label']}.{r['name']}: {props}")
    conn.close()
    return 0
