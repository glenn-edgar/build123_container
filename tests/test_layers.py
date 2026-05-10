"""Tests for layer name parsing, resolution, and auto-create state.

Doesn't need OCP — uses a seeded in-memory SQLite.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from mk.kb import _split_layer_tag, _validate_layer_tag
from mk.layers import (
    DEFAULT_LAYER,
    count_insts_per_layer,
    list_layer_rows,
    resolve_inst_layers,
)


# ── tag validation / parsing ─────────────────────────────────────────────────

class TestValidateLayerTag:
    @pytest.mark.parametrize("tag", [
        "fasteners",
        "emi_shield",
        "_internal",
        "layer1",
        "electronics,emi",
        "a, b, c",
    ])
    def test_valid(self, tag):
        _validate_layer_tag(tag)

    @pytest.mark.parametrize("tag", [
        "1starts_with_digit",
        "has space",
        "has.dot",
        "",
        ",leading_comma",
        "trailing_comma,",
        "double,,comma",
    ])
    def test_invalid(self, tag):
        with pytest.raises(ValueError):
            _validate_layer_tag(tag, where="test")

    def test_strips_whitespace(self):
        assert _validate_layer_tag("a, b, c") == "a,b,c"

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            _validate_layer_tag(42, where="test")  # type: ignore


class TestSplitLayerTag:
    def test_none(self):
        assert _split_layer_tag(None) == []

    def test_empty(self):
        assert _split_layer_tag("") == []

    def test_single(self):
        assert _split_layer_tag("fasteners") == ["fasteners"]

    def test_multi(self):
        assert _split_layer_tag("electronics,emi") == ["electronics", "emi"]

    def test_whitespace_tolerant(self):
        assert _split_layer_tag("a , b ,c") == ["a", "b", "c"]


# ── DB fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE knowledge_base_info (
            knowledge_base TEXT PRIMARY KEY,
            description TEXT
        )
    """)
    c.execute("""
        CREATE TABLE knowledge_base (
            knowledge_base TEXT,
            label TEXT,
            name TEXT,
            properties TEXT,
            path TEXT
        )
    """)
    c.execute("INSERT INTO knowledge_base_info VALUES (?, ?)", ("asm_t", ""))
    return c


def _add_inst(conn, name, *, layer=None, path=None):
    props = {}
    if layer is not None:
        props["layer"] = layer
    full_path = path or f"asm_t.INST.{name}"
    conn.execute(
        "INSERT INTO knowledge_base (knowledge_base, label, name, properties, path) "
        "VALUES (?, ?, ?, ?, ?)",
        ("asm_t", "INST", name, json.dumps(props), full_path),
    )


def _add_sub(conn, name, *, layer=None, path=None):
    props = {}
    if layer is not None:
        props["layer"] = layer
    full_path = path or f"asm_t.SUB.{name}"
    conn.execute(
        "INSERT INTO knowledge_base (knowledge_base, label, name, properties, path) "
        "VALUES (?, ?, ?, ?, ?)",
        ("asm_t", "SUB", name, json.dumps(props), full_path),
    )


def _add_layer(conn, name, props):
    conn.execute(
        "INSERT INTO knowledge_base (knowledge_base, label, name, properties, path) "
        "VALUES (?, ?, ?, ?, ?)",
        ("asm_t", "LAYER", name, json.dumps(props), f"asm_t.LAYER.{name}"),
    )


# ── resolve_inst_layers ──────────────────────────────────────────────────────

class TestResolveInstLayers:
    def test_untagged_inst_returns_default(self, conn):
        _add_inst(conn, "foo")
        assert resolve_inst_layers(conn, "asm_t", "asm_t.INST.foo") == {DEFAULT_LAYER}

    def test_single_tag(self, conn):
        _add_inst(conn, "bolt", layer="fasteners")
        assert resolve_inst_layers(conn, "asm_t", "asm_t.INST.bolt") == {"fasteners"}

    def test_multi_tag(self, conn):
        _add_inst(conn, "shield", layer="electronics,emi")
        assert resolve_inst_layers(conn, "asm_t", "asm_t.INST.shield") == {
            "electronics", "emi",
        }

    def test_inherits_from_one_sub(self, conn):
        _add_sub(conn, "electronics", layer="electronics")
        _add_inst(
            conn, "pcb",
            path="asm_t.SUB.electronics.INST.pcb",
        )
        assert resolve_inst_layers(
            conn, "asm_t", "asm_t.SUB.electronics.INST.pcb",
        ) == {"electronics"}

    def test_inst_adds_to_inherited(self, conn):
        _add_sub(conn, "electronics", layer="electronics")
        _add_inst(
            conn, "shield",
            layer="emi",
            path="asm_t.SUB.electronics.INST.shield",
        )
        assert resolve_inst_layers(
            conn, "asm_t", "asm_t.SUB.electronics.INST.shield",
        ) == {"electronics", "emi"}

    def test_deep_sub_chain(self, conn):
        _add_sub(conn, "outer", layer="outer_tag", path="asm_t.SUB.outer")
        _add_sub(conn, "inner", layer="inner_tag", path="asm_t.SUB.outer.SUB.inner")
        _add_inst(
            conn, "deep",
            layer="leaf_tag",
            path="asm_t.SUB.outer.SUB.inner.INST.deep",
        )
        assert resolve_inst_layers(
            conn, "asm_t", "asm_t.SUB.outer.SUB.inner.INST.deep",
        ) == {"outer_tag", "inner_tag", "leaf_tag"}

    def test_sibling_sub_does_not_leak(self, conn):
        # Two SUBs at the same depth with different tags; an INST in one
        # must not pick up the other's tag.
        _add_sub(conn, "elec", layer="electronics", path="asm_t.SUB.elec")
        _add_sub(conn, "mech", layer="mechanical", path="asm_t.SUB.mech")
        _add_inst(conn, "pcb", path="asm_t.SUB.elec.INST.pcb")
        assert resolve_inst_layers(conn, "asm_t", "asm_t.SUB.elec.INST.pcb") == {
            "electronics",
        }

    def test_path_prefix_boundary(self, conn):
        # 'asm_t.SUB.x' must NOT match 'asm_t.SUB.xy.INST.foo' — the '.'
        # boundary check guards against this.
        _add_sub(conn, "x", layer="wrong", path="asm_t.SUB.x")
        _add_inst(conn, "foo", path="asm_t.SUB.xy.INST.foo")
        # foo is under SUB.xy, not SUB.x — should not inherit 'wrong'.
        assert resolve_inst_layers(conn, "asm_t", "asm_t.SUB.xy.INST.foo") == {
            DEFAULT_LAYER,
        }


# ── count_insts_per_layer ────────────────────────────────────────────────────

class TestCountInstsPerLayer:
    def test_only_default(self, conn):
        _add_inst(conn, "a")
        _add_inst(conn, "b")
        _add_inst(conn, "c")
        assert count_insts_per_layer(conn, "asm_t") == {DEFAULT_LAYER: 3}

    def test_per_layer_count(self, conn):
        _add_inst(conn, "bolt1", layer="fasteners")
        _add_inst(conn, "bolt2", layer="fasteners")
        _add_inst(conn, "frame")
        assert count_insts_per_layer(conn, "asm_t") == {
            "fasteners": 2,
            DEFAULT_LAYER: 1,
        }

    def test_multi_tag_counts_once_per_layer(self, conn):
        _add_inst(conn, "shield", layer="electronics,emi")
        # Shows up in both layers.
        assert count_insts_per_layer(conn, "asm_t") == {
            "electronics": 1, "emi": 1,
        }


# ── list_layer_rows ──────────────────────────────────────────────────────────

class TestListLayerRows:
    def test_returns_sorted_with_props(self, conn):
        _add_layer(conn, "zebra", {"visible": True})
        _add_layer(conn, "alpha", {"visible": False, "color": "#aabbcc"})
        rows = list_layer_rows(conn, "asm_t")
        assert [n for n, _ in rows] == ["alpha", "zebra"]
        assert rows[0][1] == {"visible": False, "color": "#aabbcc"}
