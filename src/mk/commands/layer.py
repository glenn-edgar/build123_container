# SPDX-License-Identifier: MPL-2.0
"""mk layer ls / set / all / color — manage LAYER.<name> rows in an assembly.

Layers are visibility tags on INST and SUB rows. The state itself lives in
``LAYER.<name>`` rows in the assembly KB. These commands mutate those rows
directly via SQL UPDATE — no `mk apply` round-trip needed, and the toggle
state survives subsequent re-applies (the kb_asm context manager
snapshots/restores LAYER state across truncate).

Phase C.1+C.2 ships the data model and CLI. Phase C.3 (per-command
visibility filtering on mk show / mk export / mk mass etc.) is the
follow-up that makes the toggle visible to other commands.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from mk.db import DEFAULT_DB_PATH, open_db
from mk.layers import count_insts_per_layer, list_layer_rows

# Same pattern as in mk.kb: identifier-style names, no dots, no commas.
_LAYER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# RGB hex like "#aabbcc" — six hex digits. Alpha is decided per-render.
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def add_parser(subparsers) -> None:
    layer = subparsers.add_parser("layer", help="Manage assembly layers (visibility tags).")
    sub = layer.add_subparsers(dest="layer_cmd", required=True)

    ls = sub.add_parser("ls", help="List layers and their state.")
    ls.add_argument("asm_kb")
    ls.add_argument("--db", default=DEFAULT_DB_PATH)
    ls.set_defaults(func=run_ls)

    setp = sub.add_parser("set", help="Toggle one layer's visibility.")
    setp.add_argument("asm_kb")
    setp.add_argument("name")
    setp.add_argument("state", choices=["on", "off"])
    setp.add_argument("--db", default=DEFAULT_DB_PATH)
    setp.set_defaults(func=run_set)

    allp = sub.add_parser("all", help="Bulk-toggle every layer on or off.")
    allp.add_argument("asm_kb")
    allp.add_argument("state", choices=["on", "off"])
    allp.add_argument("--db", default=DEFAULT_DB_PATH)
    allp.set_defaults(func=run_all)

    colorp = sub.add_parser("color", help="Set a layer's display color (hex).")
    colorp.add_argument("asm_kb")
    colorp.add_argument("name")
    colorp.add_argument("hex", help="six-digit hex like #aabbcc")
    colorp.add_argument("--db", default=DEFAULT_DB_PATH)
    colorp.set_defaults(func=run_color)


def _asm_exists(conn, asm_kb: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM knowledge_base_info WHERE knowledge_base = ?", (asm_kb,),
    ).fetchone() is not None


def _layer_exists(conn, asm_kb: str, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'LAYER' AND name = ?",
        (asm_kb, name),
    ).fetchone() is not None


def _update_layer_props(conn, asm_kb: str, name: str, mutate) -> None:
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'LAYER' AND name = ?",
        (asm_kb, name),
    ).fetchone()
    props = json.loads(row["properties"]) if row and row["properties"] else {}
    mutate(props)
    conn.execute(
        "UPDATE knowledge_base SET properties = ? "
        "WHERE knowledge_base = ? AND label = 'LAYER' AND name = ?",
        (json.dumps(props), asm_kb, name),
    )
    conn.commit()


# ── commands ────────────────────────────────────────────────────────────────

def run_ls(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if not _asm_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    layers = list_layer_rows(conn, args.asm_kb)
    if not layers:
        print(f"{args.asm_kb}: no LAYER rows (run `mk apply` to auto-create them)")
        conn.close()
        return 0

    counts = count_insts_per_layer(conn, args.asm_kb)
    name_w = max(len(n) for n, _ in layers)

    print(f"{args.asm_kb} — {len(layers)} layer(s)")
    print(f"  {'NAME':<{name_w}}  STATE   COUNT  COLOR    DESCRIPTION")
    for name, props in layers:
        state = "visible" if props.get("visible", True) else "hidden "
        count = counts.get(name, 0)
        color = props.get("color") or "-"
        desc = props.get("description") or ""
        # rstrip drops the trailing whitespace when description is empty
        # (the f-string padding leaves the description column with a
        # space-padded "" otherwise).
        row = f"  {name:<{name_w}}  {state}  {count:>5}  {color:<7}  {desc}"
        print(row.rstrip())
    conn.close()
    return 0


def run_set(args: argparse.Namespace) -> int:
    if not _LAYER_NAME_RE.match(args.name):
        print(f"invalid layer name: {args.name!r}", file=sys.stderr)
        return 1
    conn = open_db(args.db)
    if not _asm_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1
    if not _layer_exists(conn, args.asm_kb, args.name):
        print(
            f"no such layer {args.name!r} in {args.asm_kb}. "
            f"Run `mk layer ls {args.asm_kb}` to see what exists.",
            file=sys.stderr,
        )
        conn.close()
        return 1

    want_visible = args.state == "on"
    _update_layer_props(
        conn, args.asm_kb, args.name,
        lambda props: props.update(visible=want_visible),
    )
    print(f"{args.asm_kb}: layer {args.name} → {'visible' if want_visible else 'hidden'}")
    conn.close()
    return 0


def run_all(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if not _asm_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    want_visible = args.state == "on"
    layers = list_layer_rows(conn, args.asm_kb)
    for name, _ in layers:
        _update_layer_props(
            conn, args.asm_kb, name,
            lambda props: props.update(visible=want_visible),
        )
    print(
        f"{args.asm_kb}: {len(layers)} layer(s) → "
        f"{'visible' if want_visible else 'hidden'}"
    )
    conn.close()
    return 0


def run_color(args: argparse.Namespace) -> int:
    if not _HEX_RE.match(args.hex):
        print(f"invalid hex color: {args.hex!r} (want #aabbcc)", file=sys.stderr)
        return 1
    conn = open_db(args.db)
    if not _asm_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1
    if not _layer_exists(conn, args.asm_kb, args.name):
        print(f"no such layer {args.name!r} in {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    _update_layer_props(
        conn, args.asm_kb, args.name,
        lambda props: props.update(color=args.hex),
    )
    print(f"{args.asm_kb}: layer {args.name} color → {args.hex}")
    conn.close()
    return 0
