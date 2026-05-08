# SPDX-License-Identifier: LGPL-2.1-or-later
"""Manifest API: ``connect``, ``kb_part``, ``kb_asm``.

Wraps the vendored ``Construct_KB`` with CAD-specific sentinel labels (PART,
JOINT, PARAM, META, SUB, INST, MATE) and ``with``-block scoping.

Apply semantics: each ``kb_part``/``kb_asm`` block truncates that KB's rows
before rewriting (naive idempotency — see continue.md §2 "Apply semantics").
"""
from __future__ import annotations

import inspect
import io
import os
import textwrap
from contextlib import contextmanager, redirect_stdout
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional, Sequence

from mk.db import _resolve_ltree_path
from vendor.kb_python.construct_kb import Construct_KB

_current_kb: ContextVar[Optional["Construct_KB"]] = ContextVar(
    "_current_kb", default=None
)


def _get_mgr() -> "Construct_KB":
    mgr = _current_kb.get()
    if mgr is None:
        raise RuntimeError(
            "no active connection. wrap manifest body in `with connect(): ...`"
        )
    return mgr


def _truncate_kb(mgr: "Construct_KB", kb_name: str) -> None:
    """Delete all rows for kb_name so the block can re-write from scratch."""
    cur = mgr.cursor
    cur.execute("DELETE FROM knowledge_base WHERE knowledge_base = ?", (kb_name,))
    cur.execute("DELETE FROM knowledge_base_info WHERE knowledge_base = ?", (kb_name,))
    cur.execute(
        "DELETE FROM knowledge_base_link WHERE parent_node_kb = ?", (kb_name,)
    )
    cur.execute(
        "DELETE FROM knowledge_base_link_mount WHERE knowledge_base = ?", (kb_name,)
    )
    mgr.conn.commit()
    # vendored code has in-memory state per-kb; reset so add_kb doesn't refuse
    mgr.path.pop(kb_name, None)
    mgr.path_values.pop(kb_name, None)


@contextmanager
def connect(db_path: Optional[str] = None) -> Iterator["Construct_KB"]:
    """Open the project DB. Picks up MK_DB env var when called without args."""
    if db_path is None:
        db_path = os.environ.get("MK_DB")
        if db_path is None:
            raise RuntimeError(
                "connect() requires db_path or MK_DB env var (set by `mk apply`)"
            )

    ltree_path = _resolve_ltree_path()
    mgr = Construct_KB(
        db_path,
        table_name="knowledge_base",
        ltree_extension_path=ltree_path,
        upload_flag=True,  # tables already exist (created by `mk init`)
    )
    token = _current_kb.set(mgr)
    try:
        yield mgr
    finally:
        _current_kb.reset(token)
        mgr.disconnect()


# ---------- part API ----------------------------------------------------------


class _PartBuilder:
    """Yielded inside ``with kb_part(...) as p:``."""

    def __init__(self, mgr: "Construct_KB", kb_name: str) -> None:
        self._mgr = mgr
        self._kb_name = kb_name
        self._builder_fn: Optional[Callable] = None

    def param(self, name: str, value: Any, type: str = "float") -> None:
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node(
                "PARAM", name, {"value": value, "type": type}, None
            )

    def joint(
        self,
        name: str,
        *,
        origin: Sequence[float],
        x_dir: Optional[Sequence[float]] = None,
        z_dir: Optional[Sequence[float]] = None,
    ) -> None:
        props: dict[str, Any] = {"origin": list(origin)}
        if x_dir is not None:
            props["x_dir"] = list(x_dir)
        if z_dir is not None:
            props["z_dir"] = list(z_dir)
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node("JOINT", name, props, None)

    def meta(self, key: str, value: Any) -> None:
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node("META", key, {"value": value}, None)

    def builder(self, fn: Callable) -> None:
        """Register the build function. Source is captured on block exit."""
        self._builder_fn = fn

    def _finalize(self) -> None:
        if self._builder_fn is None:
            raise ValueError(
                f"part {self._kb_name!r}: no builder registered "
                "(call .builder(fn) inside the `with` block)"
            )
        source = textwrap.dedent(inspect.getsource(self._builder_fn))
        props = {"source": source, "entry": self._builder_fn.__name__}
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node("PART", "body", props, None)


@contextmanager
def kb_part(kb_name: str, description: str = "") -> Iterator[_PartBuilder]:
    """Declare a part. Truncates and rewrites kb_name's rows."""
    mgr = _get_mgr()
    _truncate_kb(mgr, kb_name)
    with redirect_stdout(io.StringIO()):
        mgr.add_kb(kb_name, description)
        mgr.select_kb(kb_name)
    builder = _PartBuilder(mgr, kb_name)
    try:
        yield builder
    finally:
        builder._finalize()


# ---------- asm API -----------------------------------------------------------


class _AsmBuilder:
    """Yielded inside ``with kb_asm(...) as a:`` and from ``a.sub(...)``."""

    def __init__(self, mgr: "Construct_KB", kb_name: str) -> None:
        self._mgr = mgr
        self._kb_name = kb_name

    def inst(
        self,
        name: str,
        *,
        ref_kb: str,
        params_override: Optional[dict] = None,
        location: Optional[dict] = None,
    ) -> None:
        props: dict[str, Any] = {"ref_kb": ref_kb}
        if params_override:
            props["params_override"] = params_override
        if location:
            props["location"] = location
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node("INST", name, props, None)

    def mate(
        self,
        name: str,
        *,
        joint_a: str,
        joint_b: str,
        mate_type: str = "rigid",
        params: Optional[dict] = None,
    ) -> None:
        props: dict[str, Any] = {
            "joint_a": joint_a,
            "joint_b": joint_b,
            "mate_type": mate_type,
        }
        if params:
            props["params"] = params
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node("MATE", name, props, None)

    @contextmanager
    def sub(self, name: str, description: str = "") -> Iterator["_AsmBuilder"]:
        with redirect_stdout(io.StringIO()):
            self._mgr.add_header_node("SUB", name, {}, None, description)
        try:
            # Same builder instance — manager carries the path stack.
            yield self
        finally:
            with redirect_stdout(io.StringIO()):
                self._mgr.leave_header_node("SUB", name)


@contextmanager
def kb_asm(kb_name: str, description: str = "") -> Iterator[_AsmBuilder]:
    """Declare an assembly. Truncates and rewrites kb_name's rows."""
    mgr = _get_mgr()
    _truncate_kb(mgr, kb_name)
    with redirect_stdout(io.StringIO()):
        mgr.add_kb(kb_name, description)
        mgr.select_kb(kb_name)
    yield _AsmBuilder(mgr, kb_name)
