# SPDX-License-Identifier: MPL-2.0
"""DXF engineering-drawing emitter — Phase D.2.

Builds a 2D engineering drawing from an assembly's geometry:

  - 4 views: top, front, right, iso
  - HLR (hidden-line removal) on each → visible + hidden edge sets
  - Edges discretized to polylines (sufficient fidelity for most
    downstream tools; preserves-exact-arcs/lines is a polish step)
  - Visible edges on ``MK_VISIBLE`` (continuous, default color)
  - Hidden edges on ``MK_HIDDEN`` (DASHED, grey)
  - Standard third-angle layout:
        +-----+   +-----+
        | top |   | iso |
        +-----+   +-----+
        +-----+   +-----+
        |front|   |right|
        +-----+   +-----+
  - Optional title block in the lower-right with part name, vendor,
    and project description from META rows.

The DXF is emitted in mm units. Most CAD tools (FreeCAD TechDraw,
AutoCAD, LibreCAD) honor the ``$INSUNITS = 4`` (millimeters) header
that ezdxf sets when units are configured.

Per Phase C.3 policy: this command includes all parts (engineering
data shouldn't shift with viewer state). Layer-respecting filtering
would be a `--respect-layers` flag, but the design doc doesn't list
it for export commands, so we hold off until someone asks.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from mk.geometry import brep_bytes_to_shape
from mk.hlr import HLRResult, discretize_edge, iter_edges, project_to_2d, project_view
from mk.transform import apply_location_to_topods


# ── Layer / styling constants ────────────────────────────────────────────────

LAYER_VISIBLE = "MK_VISIBLE"
LAYER_HIDDEN = "MK_HIDDEN"
LAYER_TITLE = "MK_TITLE"
LAYER_BORDER = "MK_BORDER"

DISCRETIZE_SEGMENTS = 24
VIEW_GAP_MM = 30.0  # space between adjacent views


# ── Bounding-box helper ──────────────────────────────────────────────────────

@dataclass
class _ViewBBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin


def _bbox_of_view(result: HLRResult) -> _ViewBBox | None:
    """Return the 2D bbox of all projected edges in the visible+hidden
    compounds. None if no edges (empty view)."""
    xmin = float("inf")
    ymin = float("inf")
    xmax = float("-inf")
    ymax = float("-inf")
    found = False
    for compound in (result.visible, result.hidden):
        for edge in iter_edges(compound):
            for pt in discretize_edge(edge, n_segments=DISCRETIZE_SEGMENTS):
                x, y = project_to_2d(pt, result.look, result.up)
                xmin = min(xmin, x)
                ymin = min(ymin, y)
                xmax = max(xmax, x)
                ymax = max(ymax, y)
                found = True
    if not found:
        return None
    return _ViewBBox(xmin, ymin, xmax, ymax)


# ── ezdxf helpers ────────────────────────────────────────────────────────────

def _ensure_layers(doc) -> None:
    """Create the mk-cad layers in a fresh DXF document.

    ezdxf raises if you re-declare a layer, so we no-op for layers
    that already exist (handy if export_dxf is called twice into the
    same doc, though we don't do that yet).
    """
    layers = doc.layers
    if LAYER_VISIBLE not in layers:
        layers.new(LAYER_VISIBLE, dxfattribs={"color": 7})  # white/black
    if LAYER_HIDDEN not in layers:
        layers.new(LAYER_HIDDEN, dxfattribs={"color": 8, "linetype": "DASHED"})
    if LAYER_TITLE not in layers:
        layers.new(LAYER_TITLE, dxfattribs={"color": 7})
    if LAYER_BORDER not in layers:
        layers.new(LAYER_BORDER, dxfattribs={"color": 7})


def _emit_view(
    msp, result: HLRResult,
    offset: tuple[float, float],
    label: str,
) -> tuple[float, float]:
    """Emit one view's edges into the modelspace at the given offset.

    Each visible/hidden edge becomes a LWPOLYLINE on the appropriate
    layer. Returns the (width, height) of the emitted view (the
    caller uses this for the third-angle layout).
    """
    dx, dy = offset
    bbox = _bbox_of_view(result)
    if bbox is None:
        # Empty view (entire shape projected to a single point or fully
        # culled). Still emit the label so the layout shows the slot.
        msp.add_text(
            f"{label} (empty)",
            dxfattribs={"layer": LAYER_TITLE, "height": 4.0,
                        "insert": (dx, dy)},
        )
        return (0.0, 0.0)

    # Shift the view so its (xmin, ymin) lands at the offset.
    shift_x = dx - bbox.xmin
    shift_y = dy - bbox.ymin

    def _add_compound(compound, layer):
        for edge in iter_edges(compound):
            pts = discretize_edge(edge, n_segments=DISCRETIZE_SEGMENTS)
            if len(pts) < 2:
                continue
            xy = [
                (
                    project_to_2d(p, result.look, result.up)[0] + shift_x,
                    project_to_2d(p, result.look, result.up)[1] + shift_y,
                )
                for p in pts
            ]
            msp.add_lwpolyline(xy, dxfattribs={"layer": layer})

    _add_compound(result.visible, LAYER_VISIBLE)
    _add_compound(result.hidden, LAYER_HIDDEN)

    # View label below the bbox.
    msp.add_text(
        label.upper(),
        dxfattribs={
            "layer": LAYER_TITLE,
            "height": 4.0,
            "insert": (dx, dy - 8.0),
        },
    )

    return (bbox.width, bbox.height)


# ── Title block ─────────────────────────────────────────────────────────────

def _title_block_meta(conn: sqlite3.Connection, asm_kb: str) -> dict[str, str]:
    """Pick up META fields useful for a title block from any one of the
    assembly's referenced parts (commonly the main / largest part)
    plus the assembly KB's own description. Best-effort.
    """
    info = conn.execute(
        "SELECT description FROM knowledge_base_info WHERE knowledge_base = ?",
        (asm_kb,),
    ).fetchone()
    description = (info["description"] if info else "") or ""

    # Pick part_number / vendor from the first INST's referenced part.
    inst = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path LIMIT 1",
        (asm_kb,),
    ).fetchone()
    part_number = vendor = ""
    if inst:
        ref_kb = json.loads(inst["properties"]).get("ref_kb")
        if ref_kb:
            for key in ("part_number", "vendor"):
                row = conn.execute(
                    "SELECT properties FROM knowledge_base "
                    "WHERE knowledge_base = ? AND label = 'META' AND name = ?",
                    (ref_kb, key),
                ).fetchone()
                if row:
                    val = json.loads(row["properties"]).get("value", "")
                    if key == "part_number":
                        part_number = str(val)
                    else:
                        vendor = str(val)
    return {
        "assembly": asm_kb,
        "description": description,
        "part_number": part_number,
        "vendor": vendor,
    }


def _emit_title_block(msp, origin: tuple[float, float], info: dict[str, str]) -> None:
    """Simple title block: a 100×40 mm rectangle with 4 text rows."""
    ox, oy = origin
    w, h = 100.0, 40.0

    rect = [(ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h), (ox, oy)]
    msp.add_lwpolyline(rect, dxfattribs={"layer": LAYER_BORDER})

    rows = [
        ("ASSEMBLY", info["assembly"]),
        ("DESCRIPTION", info["description"][:80]),
        ("PART NO.", info["part_number"]),
        ("VENDOR", info["vendor"]),
    ]
    for i, (label, value) in enumerate(rows):
        y = oy + h - 8.0 * (i + 1)
        msp.add_text(
            label,
            dxfattribs={"layer": LAYER_TITLE, "height": 2.5, "insert": (ox + 2.0, y)},
        )
        msp.add_text(
            value,
            dxfattribs={"layer": LAYER_TITLE, "height": 3.0,
                        "insert": (ox + 32.0, y)},
        )


# ── Top-level builder ───────────────────────────────────────────────────────

def export_dxf(
    conn: sqlite3.Connection,
    asm_kb: str,
    inst_rows: list,
    out_path: Path,
) -> Path:
    """Write a DXF engineering drawing with 4 views + title block.

    inst_rows is already-filtered by the caller. Per Phase C.3 policy
    `mk export dxf` defaults to include-all; the caller may pass a
    visibility-filtered list if a `--respect-layers` flag is added.
    """
    import ezdxf
    from build123d import Compound

    # ── Build the combined TopoDS_Shape (transforms baked in) ──────────────
    shapes = []
    for r in inst_rows:
        props = json.loads(r["properties"])
        gh = props.get("geom_hash")
        if not gh:
            raise RuntimeError(
                f"{r['path']}: missing geom_hash (run `mk build {asm_kb}` first)"
            )
        blob = conn.execute(
            "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
        ).fetchone()
        if blob is None:
            raise RuntimeError(f"{r['path']}: BREP {gh[:12]} missing from cache")
        shape = brep_bytes_to_shape(blob["brep_blob"])
        topods = apply_location_to_topods(shape.wrapped, props.get("location"))
        shapes.append(topods)

    if not shapes:
        raise RuntimeError(f"no buildable INST rows in {asm_kb}")

    # Combine into one compound for the HLR pass.
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    combined = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(combined)
    for s in shapes:
        builder.Add(combined, s)

    # ── Run HLR for each view ──────────────────────────────────────────────
    views = {name: project_view(combined, name) for name in ("top", "front", "right", "iso")}

    # ── Lay out the views (third-angle) ────────────────────────────────────
    bboxes = {name: _bbox_of_view(v) for name, v in views.items()}
    # Use the front view's size to drive layout columns; top sits above it.
    front_bbox = bboxes.get("front") or _ViewBBox(0, 0, 100, 50)
    top_bbox = bboxes.get("top") or _ViewBBox(0, 0, 100, 50)
    right_bbox = bboxes.get("right") or _ViewBBox(0, 0, 50, 50)

    front_offset = (0.0, 0.0)
    top_offset = (0.0, front_bbox.height + VIEW_GAP_MM)
    right_offset = (front_bbox.width + VIEW_GAP_MM, 0.0)
    iso_offset = (front_bbox.width + VIEW_GAP_MM, top_offset[1])

    # ── Build the DXF document ─────────────────────────────────────────────
    doc = ezdxf.new(dxfversion="R2010", setup=True)  # setup=True adds DASHED linetype
    doc.units = 4  # millimeters
    _ensure_layers(doc)
    msp = doc.modelspace()

    _emit_view(msp, views["front"], front_offset, "front")
    _emit_view(msp, views["top"],   top_offset,   "top")
    _emit_view(msp, views["right"], right_offset, "right")
    _emit_view(msp, views["iso"],   iso_offset,   "iso")

    # Title block in the lower-right, below the iso view.
    title_origin = (
        front_bbox.width + VIEW_GAP_MM,
        -50.0,
    )
    _emit_title_block(msp, title_origin, _title_block_meta(conn, asm_kb))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out_path))
    return out_path
