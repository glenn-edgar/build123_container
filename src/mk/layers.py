# SPDX-License-Identifier: MPL-2.0
"""Layer resolution (Phase C.1).

A LAYER is a named visibility tag attached to an INST or SUB row. Layer
state (visible / color / description) lives in dedicated ``LAYER.<name>``
rows in the assembly KB.

Inheritance follows the SUB hierarchy: an INST's effective layer set is
the union of its own tags plus the tags on every ancestor SUB. An INST
with no tags anywhere in its chain resolves to ``{"DEFAULT"}``, which is
itself a LAYER row that can be toggled (handy for "show only what I've
explicitly tagged").

Multi-tag is supported by storing a comma-separated string in
``properties.layer``; consumers parse with ``_split_layer_tag`` in
``mk.kb``.
"""
from __future__ import annotations

import json
import sqlite3

from mk.kb import _split_layer_tag

DEFAULT_LAYER = "DEFAULT"


def resolve_inst_layers(
    conn: sqlite3.Connection, asm_kb: str, inst_path: str,
) -> set[str]:
    """Effective layer set for an INST: own tags ∪ inherited from SUBs.

    Walks every INST/SUB row in the assembly and accumulates the
    ``properties.layer`` tags from rows whose path is the INST's own
    path or an ancestor prefix.

    Untagged anywhere → ``{"DEFAULT"}``.
    """
    rows = conn.execute(
        "SELECT path, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label IN ('INST', 'SUB') "
        "  AND properties IS NOT NULL",
        (asm_kb,),
    ).fetchall()

    tags: set[str] = set()
    for r in rows:
        path = r["path"]
        # Ancestor match: prefix + '.' boundary (so 'asm.SUB.x' matches
        # 'asm.SUB.x.INST.foo' but not 'asm.SUB.xy.INST.foo'). Self-match
        # via equality.
        if path == inst_path or inst_path.startswith(path + "."):
            props = json.loads(r["properties"])
            for name in _split_layer_tag(props.get("layer")):
                tags.add(name)

    return tags if tags else {DEFAULT_LAYER}


def list_layer_rows(
    conn: sqlite3.Connection, asm_kb: str,
) -> list[tuple[str, dict]]:
    """Return ``(name, properties_dict)`` for every LAYER row in the assembly,
    ordered by name."""
    rows = conn.execute(
        "SELECT name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'LAYER' "
        "ORDER BY name",
        (asm_kb,),
    ).fetchall()
    return [
        (r["name"], json.loads(r["properties"]) if r["properties"] else {})
        for r in rows
    ]


def count_insts_per_layer(
    conn: sqlite3.Connection, asm_kb: str,
) -> dict[str, int]:
    """Count INST rows whose effective layer set includes each layer.

    Useful for ``mk layer ls`` to show "X instances on this layer".
    A multi-tag INST counts once per layer it belongs to.
    """
    inst_rows = conn.execute(
        "SELECT path FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' "
        "ORDER BY path",
        (asm_kb,),
    ).fetchall()

    counts: dict[str, int] = {}
    for r in inst_rows:
        for layer in resolve_inst_layers(conn, asm_kb, r["path"]):
            counts[layer] = counts.get(layer, 0) + 1
    return counts
