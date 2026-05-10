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


def _layer_visibility_map(conn: sqlite3.Connection, asm_kb: str) -> dict[str, bool]:
    """Map ``layer_name → visible_bool``. Unknown names default to True
    (forward-compat: a tag without a LAYER row is treated as visible).
    """
    rows = conn.execute(
        "SELECT name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'LAYER'",
        (asm_kb,),
    ).fetchall()
    out: dict[str, bool] = {}
    for r in rows:
        props = json.loads(r["properties"]) if r["properties"] else {}
        out[r["name"]] = bool(props.get("visible", True))
    return out


def build_visibility_index(
    conn: sqlite3.Connection, asm_kb: str,
) -> dict[str, bool]:
    """Map ``inst_path → is_visible`` for every INST in the assembly.

    Visibility is **union semantics**: an INST is visible if *any* of
    its effective layers (own ∪ inherited from SUB ancestors) has
    ``visible=true``. This matches how viewers handle overlapping
    layers — turning off ``electronics`` doesn't hide a part that's
    also on ``frame`` if ``frame`` is still on.

    Untagged insts resolve to ``{DEFAULT}``; their visibility tracks
    whatever state ``LAYER.DEFAULT`` is in.

    Forward-compat: a layer name with no corresponding LAYER row is
    treated as visible (true). Should only happen if a manifest is
    edited but not re-applied — the next ``mk apply`` creates the
    missing rows.
    """
    layer_vis = _layer_visibility_map(conn, asm_kb)
    inst_rows = conn.execute(
        "SELECT path FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' "
        "ORDER BY path",
        (asm_kb,),
    ).fetchall()
    out: dict[str, bool] = {}
    for r in inst_rows:
        effective = resolve_inst_layers(conn, asm_kb, r["path"])
        out[r["path"]] = any(layer_vis.get(name, True) for name in effective)
    return out


def partition_by_visibility(
    conn: sqlite3.Connection, asm_kb: str, inst_rows: list,
) -> tuple[list, int]:
    """Split a list of INST rows into (visible_only, hidden_count).

    Used by commands that filter their output by current layer state.
    The row objects are the result of a ``SELECT ... FROM knowledge_base``
    query; only the ``path`` column is consulted here, so any row mapping
    that supports ``r["path"]`` will work.
    """
    vis = build_visibility_index(conn, asm_kb)
    visible = [r for r in inst_rows if vis.get(r["path"], True)]
    hidden = len(inst_rows) - len(visible)
    return visible, hidden


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
