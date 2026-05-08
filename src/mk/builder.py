# SPDX-License-Identifier: MPL-2.0
"""Builder execution: read PART.body source, exec, return a build123d shape."""
from __future__ import annotations

import json
import sqlite3
from typing import Any


def get_part_defaults(conn: sqlite3.Connection, part_kb: str) -> dict[str, Any]:
    """Return {param_name: value} from the part's PARAM rows."""
    rows = conn.execute(
        "SELECT name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'PARAM'",
        (part_kb,),
    ).fetchall()
    out: dict[str, Any] = {}
    for r in rows:
        props = json.loads(r["properties"]) if r["properties"] else {}
        out[r["name"]] = props.get("value")
    return out


def run_builder(conn: sqlite3.Connection, part_kb: str, params: dict[str, Any]):
    """Read PART.body, compile + exec into a fresh namespace, call entry(params).

    Returns whatever the builder returns — typically a build123d Shape, Part,
    Solid, or Compound.
    """
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'PART' AND name = 'body'",
        (part_kb,),
    ).fetchone()
    if row is None:
        raise ValueError(f"part {part_kb!r}: no PART.body row (not built/applied?)")

    payload = json.loads(row["properties"])
    source = payload["source"]
    entry = payload.get("entry", "build")

    code = compile(source, f"<builder:{part_kb}>", "exec")
    ns: dict[str, Any] = {}
    exec("from build123d import *", ns)
    exec(code, ns)
    fn = ns.get(entry)
    if fn is None:
        raise ValueError(
            f"part {part_kb!r}: entry function {entry!r} not found in builder source"
        )
    return fn(params)
