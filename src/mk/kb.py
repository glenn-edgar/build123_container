# SPDX-License-Identifier: MPL-2.0
"""Manifest API: ``connect``, ``kb_part``, ``kb_asm``.

Wraps the vendored ``Construct_KB`` with CAD-specific sentinel labels (PART,
JOINT, PARAM, META, SUB, INST, MATE) and ``with``-block scoping.

Apply semantics: each ``kb_part``/``kb_asm`` block truncates that KB's rows
before rewriting (naive idempotency — see continue.md §2 "Apply semantics").
"""
from __future__ import annotations

import inspect
import io
import json
import os
import re
import textwrap
from contextlib import contextmanager, redirect_stdout
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional, Sequence

from mk.db import _resolve_ltree_path
from vendor.kb_python.construct_kb import Construct_KB

# A single layer name: identifier-ish. Multi-tag splits on comma; the same
# pattern applies to each piece. Liberal enough for ``fasteners``,
# ``emi_shield``, ``layer1`` but rejects ``oh no`` or ``a.b``.
_LAYER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_layer_tag(tag: str, *, where: str = "") -> str:
    """Validate a layer-tag string (single name or comma-separated list).

    Returns the canonical form: whitespace stripped around commas, but
    insertion order preserved. Raises ValueError on invalid names.
    """
    if not isinstance(tag, str):
        raise ValueError(f"{where}: layer= must be a string, got {type(tag).__name__}")
    parts = [p.strip() for p in tag.split(",")]
    if any(not p for p in parts):
        raise ValueError(
            f"{where}: empty layer name in {tag!r} (leading/trailing/double comma?)"
        )
    for p in parts:
        if not _LAYER_NAME_RE.match(p):
            raise ValueError(
                f"{where}: invalid layer name {p!r} — must match "
                f"[A-Za-z_][A-Za-z0-9_]* (got {tag!r})"
            )
    return ",".join(parts)


def _split_layer_tag(tag: Optional[str]) -> list[str]:
    """Parse a stored ``properties.layer`` string into a list of names.

    Whitespace tolerated. Empty / None returns ``[]``.
    """
    if not tag:
        return []
    return [p.strip() for p in tag.split(",") if p.strip()]

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


def _snapshot_layer_state(mgr: "Construct_KB", kb_name: str) -> dict[str, dict]:
    """Read existing LAYER.<name> rows before truncate so re-apply preserves
    user-toggled visibility / color / description state.

    Returns ``{layer_name: properties_dict}``. Empty dict if the KB has no
    LAYER rows yet (first apply).
    """
    rows = mgr.conn.execute(
        "SELECT name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'LAYER'",
        (kb_name,),
    ).fetchall()
    return {
        r["name"]: (json.loads(r["properties"]) if r["properties"] else {})
        for r in rows
    }


def _emit_layer_rows(
    mgr: "Construct_KB", kb_name: str, preserved: dict[str, dict],
) -> None:
    """After a kb_asm() block finishes, scan its INST and SUB rows for
    layer tags and write the corresponding LAYER.<name> rows.

    Always emits ``LAYER.DEFAULT`` (the implicit layer for untagged
    nodes). For names that existed before the truncate, preserves their
    visibility / color / description; new names default to
    ``{"visible": true}``. Preserved layers stick around even if the
    current apply doesn't reference them — so toggle state survives a
    transient manifest change.
    """
    rows = mgr.conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label IN ('INST', 'SUB') "
        "  AND properties IS NOT NULL",
        (kb_name,),
    ).fetchall()

    referenced: set[str] = {"DEFAULT"}
    for r in rows:
        props = json.loads(r["properties"])
        for name in _split_layer_tag(props.get("layer")):
            referenced.add(name)

    # Preserved-but-currently-unreferenced layers keep their row so toggle
    # state isn't lost if the manifest temporarily drops a tag.
    referenced.update(preserved.keys())

    for name in sorted(referenced):
        state = dict(preserved.get(name, {}))
        state.setdefault("visible", True)
        with redirect_stdout(io.StringIO()):
            mgr.add_info_node("LAYER", name, state, None)


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
        layer: Optional[str] = None,
    ) -> None:
        props: dict[str, Any] = {"ref_kb": ref_kb}
        if params_override:
            props["params_override"] = params_override
        if location:
            props["location"] = location
        if layer is not None:
            props["layer"] = _validate_layer_tag(layer, where=f"inst {name!r}")
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node("INST", name, props, None)

    def mate(
        self,
        name: str,
        *,
        joint_a: str,
        joint_b: str,
        mate_type: str = "rigid",
        axis: Optional[list] = None,
        limits: Optional[list] = None,
        default: Optional[float] = None,
        params: Optional[dict] = None,
    ) -> None:
        """Declare a mate between two joint paths.

        For ``mate_type="rigid"``: aligns joint_a coincident with joint_b,
        z-axes opposing. No kinematic DOF.

        For ``mate_type="revolute"`` or ``"prismatic"``: rigid alignment plus
        one DOF along ``axis`` (a 3-vector in joint_a's local frame; defaults
        to ``[0, 0, 1]`` = the joint's z direction = a hinge pin / slide
        along the joint normal). ``limits=[lo, hi]`` constrains the DOF
        range (degrees for revolute, mm for prismatic; ``None`` = unbounded).
        ``default`` is the initial pose value (degrees / mm) used at build
        time. Phase B.2 adds animation overrides via outputs/<asm>.state.json.
        """
        props: dict[str, Any] = {
            "joint_a": joint_a,
            "joint_b": joint_b,
            "mate_type": mate_type,
        }
        if axis is not None:
            props["axis"] = list(axis)
        if limits is not None:
            props["limits"] = list(limits)
        if default is not None:
            props["default"] = float(default)
        if params:
            props["params"] = params
        with redirect_stdout(io.StringIO()):
            self._mgr.add_info_node("MATE", name, props, None)

    @contextmanager
    def sub(
        self,
        name: str,
        description: str = "",
        *,
        layer: Optional[str] = None,
    ) -> Iterator["_AsmBuilder"]:
        props: dict[str, Any] = {}
        if layer is not None:
            props["layer"] = _validate_layer_tag(layer, where=f"sub {name!r}")
        with redirect_stdout(io.StringIO()):
            self._mgr.add_header_node("SUB", name, props, None, description)
        try:
            # Same builder instance — manager carries the path stack.
            yield self
        finally:
            with redirect_stdout(io.StringIO()):
                self._mgr.leave_header_node("SUB", name)


@contextmanager
def kb_asm(kb_name: str, description: str = "") -> Iterator[_AsmBuilder]:
    """Declare an assembly. Truncates and rewrites kb_name's rows.

    LAYER state from a previous apply is snapshotted before truncate and
    restored after the user's inst/sub/mate calls land; new layer names
    referenced by INST/SUB tags auto-create with ``{"visible": true}``.
    """
    mgr = _get_mgr()
    preserved_layers = _snapshot_layer_state(mgr, kb_name)
    _truncate_kb(mgr, kb_name)
    with redirect_stdout(io.StringIO()):
        mgr.add_kb(kb_name, description)
        mgr.select_kb(kb_name)
    builder = _AsmBuilder(mgr, kb_name)
    try:
        yield builder
    finally:
        _emit_layer_rows(mgr, kb_name, preserved_layers)
