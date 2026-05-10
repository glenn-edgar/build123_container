"""Tests for `mk part export` document assembly (no OCP needed)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from mk.commands.part import build_part_document


@pytest.fixture
def conn():
    """In-memory SQLite with the columns mk.commands.part queries."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # Subset of the real schema — only what build_part_document touches.
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
            properties TEXT
        )
    """)
    return c


def _insert(conn, kb, label, name, props):
    conn.execute(
        "INSERT INTO knowledge_base (knowledge_base, label, name, properties) "
        "VALUES (?, ?, ?, ?)",
        (kb, label, name, json.dumps(props)),
    )


# ── basic shape ──────────────────────────────────────────────────────────────

class TestPartDocument:
    def test_missing_kb_returns_none(self, conn):
        assert build_part_document(conn, "no_such_part") is None

    def test_minimal_kb(self, conn):
        conn.execute(
            "INSERT INTO knowledge_base_info VALUES (?, ?)",
            ("part_x", "test part"),
        )
        doc = build_part_document(conn, "part_x")
        assert doc == {
            "kb": "part_x",
            "description": "test part",
            "params": {},
            "joints": {},
            "meta": {},
        }

    def test_params_collected_as_flat_dict(self, conn):
        conn.execute("INSERT INTO knowledge_base_info VALUES (?, ?)", ("part_x", ""))
        _insert(conn, "part_x", "PARAM", "w", {"value": 30, "type": "float"})
        _insert(conn, "part_x", "PARAM", "h", {"value": 50, "type": "float"})
        doc = build_part_document(conn, "part_x")
        assert doc["params"] == {"w": 30, "h": 50}

    def test_joints_include_dirs_when_present(self, conn):
        conn.execute("INSERT INTO knowledge_base_info VALUES (?, ?)", ("part_x", ""))
        _insert(conn, "part_x", "JOINT", "top", {
            "origin": [0, 0, 10], "z_dir": [0, 0, 1],
        })
        _insert(conn, "part_x", "JOINT", "side", {
            "origin": [5, 0, 0], "z_dir": [1, 0, 0], "x_dir": [0, 1, 0],
        })
        doc = build_part_document(conn, "part_x")
        assert doc["joints"]["top"] == {"origin": [0, 0, 10], "z_dir": [0, 0, 1]}
        assert doc["joints"]["side"] == {
            "origin": [5, 0, 0], "z_dir": [1, 0, 0], "x_dir": [0, 1, 0],
        }

    def test_meta_flat_only(self, conn):
        conn.execute("INSERT INTO knowledge_base_info VALUES (?, ?)", ("part_x", ""))
        _insert(conn, "part_x", "META", "density", {"value": 7.85})
        _insert(conn, "part_x", "META", "color", {"value": "#5a6573"})
        doc = build_part_document(conn, "part_x")
        assert doc["meta"] == {"density": 7.85, "color": "#5a6573"}

    def test_meta_with_dotted_namespaces(self, conn):
        conn.execute("INSERT INTO knowledge_base_info VALUES (?, ?)", ("part_x", ""))
        _insert(conn, "part_x", "META", "density", {"value": 7.0})
        _insert(conn, "part_x", "META", "electrical.voltage_nominal_v", {"value": 12.0})
        _insert(conn, "part_x", "META", "electrical.voltage_max_v", {"value": 14.0})
        _insert(conn, "part_x", "META", "mech.gear_ratio", {"value": 100})
        doc = build_part_document(conn, "part_x")
        assert doc["meta"]["density"] == 7.0
        assert doc["meta"]["electrical"]["voltage_nominal_v"] == 12.0
        assert doc["meta"]["electrical"]["voltage_max_v"] == 14.0
        assert doc["meta"]["mech"]["gear_ratio"] == 100

    def test_full_n20_motor_like(self, conn):
        """The shape `mk part export part_n20_worm_motor_16rpm` would produce."""
        conn.execute(
            "INSERT INTO knowledge_base_info VALUES (?, ?)",
            ("part_motor", "N20 worm motor"),
        )
        _insert(conn, "part_motor", "PARAM", "body_d", {"value": 12, "type": "float"})
        _insert(conn, "part_motor", "JOINT", "body_center", {
            "origin": [0, 0, 0], "z_dir": [-1, 0, 0],
        })
        _insert(conn, "part_motor", "META", "density", {"value": 7.0})
        _insert(conn, "part_motor", "META", "mass_g_override", {"value": 10.0})
        _insert(conn, "part_motor", "META", "electrical.voltage_nominal_v", {"value": 12.0})
        _insert(conn, "part_motor", "META", "mech.no_load_rpm_at_12v", {"value": 16})
        _insert(conn, "part_motor", "META", "encoder.present", {"value": True})
        _insert(conn, "part_motor", "META", "_TODO_electrical_resistance_ohm", {"value": None})

        doc = build_part_document(conn, "part_motor")
        # Top-level fields.
        assert doc["kb"] == "part_motor"
        assert doc["description"] == "N20 worm motor"
        # Params.
        assert doc["params"]["body_d"] == 12
        # Joints.
        assert doc["joints"]["body_center"]["z_dir"] == [-1, 0, 0]
        # Meta: flat keys at top.
        assert doc["meta"]["density"] == 7.0
        assert doc["meta"]["mass_g_override"] == 10.0
        # Meta: namespaces.
        assert doc["meta"]["electrical"] == {"voltage_nominal_v": 12.0}
        assert doc["meta"]["mech"]["no_load_rpm_at_12v"] == 16
        assert doc["meta"]["encoder"]["present"] is True
        # _TODO_ keys stay flat (no dot).
        assert doc["meta"]["_TODO_electrical_resistance_ohm"] is None

    def test_serializes_to_valid_json(self, conn):
        conn.execute("INSERT INTO knowledge_base_info VALUES (?, ?)", ("part_x", ""))
        _insert(conn, "part_x", "META", "electrical.voltage_nominal_v", {"value": 12.0})
        _insert(conn, "part_x", "META", "encoder.present", {"value": True})
        doc = build_part_document(conn, "part_x")
        # Must round-trip via json.dumps / json.loads.
        text = json.dumps(doc, indent=2)
        round_trip = json.loads(text)
        assert round_trip == doc
