"""Pure-Python tests for mk state file helpers (no OCP needed)."""
from __future__ import annotations

import json

import pytest

from mk.commands.state import _fmt_limits, _load_state, _save_state, _state_path


class TestStatePath:
    def test_default_outdir(self):
        p = _state_path("/project/outputs", "asm_demo")
        assert str(p) == "/project/outputs/asm_demo/state.json"

    def test_custom_outdir(self, tmp_path):
        p = _state_path(str(tmp_path), "asm_x")
        assert p == tmp_path / "asm_x" / "state.json"


class TestLoadState:
    def test_missing_file_empty(self, tmp_path):
        assert _load_state(tmp_path / "no_such.json") == {}

    def test_empty_file_empty(self, tmp_path):
        f = tmp_path / "state.json"
        f.write_text("")
        assert _load_state(f) == {}

    def test_whitespace_only_empty(self, tmp_path):
        f = tmp_path / "state.json"
        f.write_text("   \n\n")
        assert _load_state(f) == {}

    def test_normal(self, tmp_path):
        f = tmp_path / "state.json"
        f.write_text('{"hinge": 45.0, "slider": 5}')
        assert _load_state(f) == {"hinge": 45.0, "slider": 5.0}


class TestSaveState:
    def test_creates_parent_dir(self, tmp_path):
        f = tmp_path / "subdir" / "state.json"
        _save_state(f, {"hinge": 45.0})
        assert f.exists()
        data = json.loads(f.read_text())
        assert data == {"hinge": 45.0}

    def test_overwrites(self, tmp_path):
        f = tmp_path / "state.json"
        _save_state(f, {"hinge": 45.0})
        _save_state(f, {"hinge": 90.0, "slider": 5.0})
        data = json.loads(f.read_text())
        assert data == {"hinge": 90.0, "slider": 5.0}

    def test_trailing_newline(self, tmp_path):
        # Pretty-printed JSON with a trailing newline — POSIX-friendly.
        f = tmp_path / "state.json"
        _save_state(f, {"hinge": 45.0})
        assert f.read_text().endswith("\n")


class TestFmtLimits:
    def test_none(self):
        assert _fmt_limits(None) == "—"

    def test_empty(self):
        assert _fmt_limits([]) == "—"

    def test_both(self):
        assert _fmt_limits([0.0, 180.0]) == "[0.0, 180.0]"

    def test_lower_only(self):
        assert _fmt_limits([0.0, None]) == "[0.0, —]"

    def test_upper_only(self):
        assert _fmt_limits([None, 100.0]) == "[—, 100.0]"
