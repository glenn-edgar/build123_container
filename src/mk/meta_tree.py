# SPDX-License-Identifier: MPL-2.0
"""Group flat META rows into a structured namespace tree.

Phase B.3 introduces a typed convention: META keys may use dotted names like
``electrical.voltage_nominal_v`` or ``mech.gear_ratio``. Each dot splits the
name into a hierarchy segment. Flat names (no dot) stay at the top level.

Backward-compatible: the manifest API is unchanged — ``meta(key, value)``
still accepts any string — and ``mk part show`` keeps its row-oriented
display. Only the new ``mk part export`` consumer relies on the tree shape,
so old parts coexist with new ones in the same DB.

Example:

    rows = [
        ("electrical.voltage_nominal_v", 12.0),
        ("electrical.resistance_ohm", 5.0),
        ("mech.gear_ratio", 100.0),
        ("density", 7.85),
    ]
    build_meta_tree(rows) == {
        "electrical": {"voltage_nominal_v": 12.0, "resistance_ohm": 5.0},
        "mech": {"gear_ratio": 100.0},
        "density": 7.85,
    }
"""
from __future__ import annotations

from typing import Any


class MetaTreeConflictError(ValueError):
    """A META key collides with an existing namespace (or vice versa)."""


def build_meta_tree(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    """Group ``(name, value)`` pairs into a nested namespace dict.

    Splits each name on ``.``: intermediate segments become nested dicts,
    the final segment is assigned the value. Names without ``.`` are flat
    keys at the top level. Order of insertion is preserved for human
    readability.

    Raises ``MetaTreeConflictError`` if a name and namespace share a path:
    - Same name twice (the DB shouldn't allow this, but we guard).
    - ``"electrical" = 12`` then ``"electrical.voltage" = 13`` (flat
      shadows / blocks namespace).
    - The reverse: ``"electrical.voltage" = 12`` then ``"electrical" = 7``.
    """
    tree: dict[str, Any] = {}
    for name, value in rows:
        if "." not in name:
            if name in tree and isinstance(tree[name], dict):
                raise MetaTreeConflictError(
                    f"META key {name!r} (flat) collides with existing namespace "
                    f"{name!r}.* — cannot be both a value and a namespace."
                )
            if name in tree:
                raise MetaTreeConflictError(
                    f"META key {name!r} appears more than once."
                )
            tree[name] = value
            continue

        segments = name.split(".")
        if any(not s for s in segments):
            raise MetaTreeConflictError(
                f"META key {name!r} has an empty segment "
                f"(leading/trailing/double dot)."
            )

        # Walk down, creating intermediate dicts. Detect collision with
        # a flat value at any intermediate segment.
        cursor: dict[str, Any] = tree
        for i, seg in enumerate(segments[:-1]):
            if seg in cursor:
                if not isinstance(cursor[seg], dict):
                    raise MetaTreeConflictError(
                        f"META key {name!r}: segment {'.'.join(segments[:i+1])!r} "
                        f"is already a flat value, cannot nest under it."
                    )
            else:
                cursor[seg] = {}
            cursor = cursor[seg]

        leaf = segments[-1]
        if leaf in cursor:
            if isinstance(cursor[leaf], dict):
                raise MetaTreeConflictError(
                    f"META key {name!r} collides with existing namespace "
                    f"{name!r}.* — cannot be both a value and a namespace."
                )
            raise MetaTreeConflictError(
                f"META key {name!r} appears more than once."
            )
        cursor[leaf] = value

    return tree
