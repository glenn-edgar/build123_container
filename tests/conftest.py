"""Shared pytest setup.

Marks tests that need OCP / build123d so they can be selectively skipped
when running on the host (where those C++ deps usually aren't installed).
The container has them, so `docker compose run --rm cad pytest` runs
everything; on host, `pytest -m "not needs_ocp"` runs only the pure-Python
subset.
"""
from __future__ import annotations

import pytest


def _has_ocp() -> bool:
    try:
        import OCP  # noqa: F401
        return True
    except ImportError:
        return False


HAS_OCP = _has_ocp()


def pytest_collection_modifyitems(config, items):
    if HAS_OCP:
        return
    skip_marker = pytest.mark.skip(reason="requires OCP / build123d (run in container)")
    for item in items:
        if "needs_ocp" in item.keywords:
            item.add_marker(skip_marker)
