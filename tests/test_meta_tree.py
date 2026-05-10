"""Pure-Python tests for mk.meta_tree."""
from __future__ import annotations

import pytest

from mk.meta_tree import MetaTreeConflictError, build_meta_tree


class TestBuildMetaTree:
    def test_empty(self):
        assert build_meta_tree([]) == {}

    def test_flat_only(self):
        rows = [("density", 7.85), ("color", "#5a6573"), ("vendor", "Anreak")]
        assert build_meta_tree(rows) == {
            "density": 7.85,
            "color": "#5a6573",
            "vendor": "Anreak",
        }

    def test_one_namespace(self):
        rows = [
            ("electrical.voltage_nominal_v", 12.0),
            ("electrical.voltage_min_v", 3.0),
            ("electrical.voltage_max_v", 12.0),
        ]
        assert build_meta_tree(rows) == {
            "electrical": {
                "voltage_nominal_v": 12.0,
                "voltage_min_v": 3.0,
                "voltage_max_v": 12.0,
            },
        }

    def test_two_namespaces(self):
        rows = [
            ("electrical.voltage_nominal_v", 12.0),
            ("mech.gear_ratio", 100.0),
            ("mech.no_load_rpm", 16),
        ]
        tree = build_meta_tree(rows)
        assert tree == {
            "electrical": {"voltage_nominal_v": 12.0},
            "mech": {"gear_ratio": 100.0, "no_load_rpm": 16},
        }

    def test_mixed_flat_and_namespaced(self):
        rows = [
            ("density", 7.85),
            ("electrical.voltage_nominal_v", 12.0),
            ("vendor", "Anreak"),
            ("mech.gear_ratio", 100.0),
            ("color", "#5a6573"),
        ]
        tree = build_meta_tree(rows)
        # Top-level: density, vendor, color (flat) + electrical, mech (namespaces).
        assert set(tree.keys()) == {"density", "vendor", "color", "electrical", "mech"}
        assert tree["density"] == 7.85
        assert tree["electrical"]["voltage_nominal_v"] == 12.0
        assert tree["mech"]["gear_ratio"] == 100.0

    def test_deep_nesting(self):
        # Two-level: encoder.quadrature.cpr — supported, just nests further.
        rows = [
            ("encoder.quadrature.cpr", 7),
            ("encoder.quadrature.gear_ratio", 100),
            ("encoder.absolute.bits", 12),
        ]
        tree = build_meta_tree(rows)
        assert tree == {
            "encoder": {
                "quadrature": {"cpr": 7, "gear_ratio": 100},
                "absolute": {"bits": 12},
            },
        }

    def test_none_value_preserved(self):
        rows = [("_TODO_resistance_ohm", None), ("electrical.voltage", 12)]
        tree = build_meta_tree(rows)
        assert tree["_TODO_resistance_ohm"] is None
        assert tree["electrical"]["voltage"] == 12

    def test_underscore_prefix_treated_as_flat(self):
        # _TODO_ keys (no dot) stay at the top level as a flat marker.
        rows = [("_TODO_electrical_resistance_ohm", None)]
        tree = build_meta_tree(rows)
        assert "_TODO_electrical_resistance_ohm" in tree
        assert "electrical" not in tree

    def test_insertion_order_preserved(self):
        rows = [
            ("zebra", 1),
            ("alpha.x", 2),
            ("alpha.y", 3),
            ("beta", 4),
        ]
        tree = build_meta_tree(rows)
        assert list(tree.keys()) == ["zebra", "alpha", "beta"]
        assert list(tree["alpha"].keys()) == ["x", "y"]

    # ── Conflict detection ─────────────────────────────────────────────────

    def test_duplicate_flat_key(self):
        rows = [("density", 7.85), ("density", 8.0)]
        with pytest.raises(MetaTreeConflictError, match="appears more than once"):
            build_meta_tree(rows)

    def test_flat_then_namespace_conflict(self):
        rows = [("electrical", 12.0), ("electrical.voltage", 5.0)]
        with pytest.raises(MetaTreeConflictError, match="already a flat value"):
            build_meta_tree(rows)

    def test_namespace_then_flat_conflict(self):
        rows = [("electrical.voltage", 5.0), ("electrical", 12.0)]
        with pytest.raises(MetaTreeConflictError, match="collides with existing namespace"):
            build_meta_tree(rows)

    def test_duplicate_nested_key(self):
        rows = [("electrical.voltage", 12.0), ("electrical.voltage", 5.0)]
        with pytest.raises(MetaTreeConflictError, match="appears more than once"):
            build_meta_tree(rows)

    @pytest.mark.parametrize("bad_name", [
        ".foo",       # leading dot
        "foo.",       # trailing dot
        "foo..bar",   # double dot
    ])
    def test_rejects_malformed_names(self, bad_name):
        with pytest.raises(MetaTreeConflictError, match="empty segment"):
            build_meta_tree([(bad_name, 1)])
