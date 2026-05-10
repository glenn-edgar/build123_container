# SPDX-License-Identifier: MPL-2.0
"""XCAF-aware STEP export — preserves colors, best-effort layers.

Phase C.4. Replaces build123d's plain `export_step` with a writer that
uses OCC's XCAF document model so each shape's color (and, where the
OCC writer cooperates, layer assignment) lands in the STEP file and
round-trips through other CAD tools (FreeCAD, CadQuery's STEP
importer, KiCAD's mechanical viewer, etc.).

What's preserved reliably:
- **Per-part color**: META.color hex string → Quantity_Color via
  XCAFDoc_ColorTool.SetColor (surface color). FreeCAD and CadQuery
  both pick this up correctly.
- **INST.location transforms**: baked into the TopoDS shape before
  AddShape; the STEP doc sees each inst at its world position.

What's preserved best-effort (OCC 7.8.1.1 writer quirks):
- **Layer assignments.** The XCAF in-memory layer table is built
  correctly (verified: each shape's GetLayers returns its effective
  set). But OCC's STEPCAFControl_Writer emits at most one shape per
  PRESENTATION_LAYER_ASSIGNMENT entity *and* drops shapes that have
  multiple layer assignments. Empirically:
    - asm_window_test (5 shapes all on "DEFAULT"): only the last
      shape's assignment survives the STEP write.
    - asm_nested (4 shapes, 4 distinct layers, 1 multi-tag): the 3
      single-tag shapes round-trip, the multi-tag one drops fully.
  Workaround: we write only the first layer name (sorted) per shape;
  multi-tag insts log a stderr warning. This is the best the writer
  will do without post-processing the STEP file. Phase D (DXF) doesn't
  go through this code path — it can attach layers directly via
  ezdxf, so the OCC issue won't affect engineering drawings.

What's not preserved:
- Assembly hierarchy (SUB nesting collapses to flat instance list).
  The STEP file is a bag of shapes with per-shape metadata, not a
  product structure tree.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from mk.geometry import brep_bytes_to_shape
from mk.layers import resolve_inst_layers
from mk.transform import apply_location_to_topods


def _read_color_hex(conn: sqlite3.Connection, part_kb: str) -> str | None:
    """Return META.color hex string or None."""
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'META' AND name = 'color'",
        (part_kb,),
    ).fetchone()
    if row is None:
        return None
    val = json.loads(row["properties"]).get("value")
    if isinstance(val, str) and val.startswith("#") and len(val) == 7:
        return val
    return None


def _hex_to_rgb(hex_str: str) -> tuple[float, float, float] | None:
    try:
        r = int(hex_str[1:3], 16) / 255.0
        g = int(hex_str[3:5], 16) / 255.0
        b = int(hex_str[5:7], 16) / 255.0
    except ValueError:
        return None
    return r, g, b


def export_step_xcaf(
    conn: sqlite3.Connection,
    asm_kb: str,
    inst_rows: list,
    out_path: Path,
) -> Path:
    """Write a STEP file containing every inst's geometry with layer + color
    metadata attached. Returns the output path.

    inst_rows is the result of querying INST rows from the assembly KB
    (after any visibility filtering — Phase C.3 keeps STEP at "include
    all" by default, but the caller decides the row list).
    """
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

    app = XCAFApp_Application.GetApplication_s()
    fmt = TCollection_ExtendedString("MDTV-XCAF")
    doc = TDocStd_Document(fmt)
    app.NewDocument(fmt, doc)

    main_label = doc.Main()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(main_label)
    layer_tool = XCAFDoc_DocumentTool.LayerTool_s(main_label)
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(main_label)

    for r in inst_rows:
        props = json.loads(r["properties"])
        gh = props.get("geom_hash")
        ref_kb = props.get("ref_kb")
        if not gh or not ref_kb:
            raise RuntimeError(
                f"{r['path']}: missing geom_hash or ref_kb "
                f"(run `mk build {asm_kb}` first)"
            )

        blob_row = conn.execute(
            "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
        ).fetchone()
        if blob_row is None:
            raise RuntimeError(
                f"{r['path']}: BREP {gh[:12]} missing from geometry cache"
            )

        shape = brep_bytes_to_shape(blob_row["brep_blob"])
        topods = apply_location_to_topods(shape.wrapped, props.get("location"))
        # makeAssembly=False — each shape lands as a free shape under the
        # main label rather than as a sub-assembly node.
        label = shape_tool.AddShape(topods, False)

        # OCC's STEP writer drops multi-layer shapes from PRESENTATION_LAYER_
        # ASSIGNMENT entirely (verified, OCCT 7.6). Assign only the first
        # layer alphabetically and warn so the user knows the file is lossy.
        layer_set = sorted(resolve_inst_layers(conn, asm_kb, r["path"]))
        if len(layer_set) > 1:
            chosen = layer_set[0]
            dropped = layer_set[1:]
            print(
                f"  WARN: {r['path']} on layers {layer_set}; STEP only "
                f"records {chosen!r} (dropped: {dropped}). See step_xcaf.py "
                f"docstring for the OCC quirk.",
                file=sys.stderr,
            )
            layer_tool.SetLayer(label, TCollection_ExtendedString(chosen), False)
        elif layer_set:
            layer_tool.SetLayer(label, TCollection_ExtendedString(layer_set[0]), False)

        color_hex = _read_color_hex(conn, ref_kb)
        if color_hex:
            rgb = _hex_to_rgb(color_hex)
            if rgb is not None:
                qc = Quantity_Color(rgb[0], rgb[1], rgb[2], Quantity_TOC_RGB)
                color_tool.SetColor(label, qc, XCAFDoc_ColorSurf)

    writer = STEPCAFControl_Writer()
    writer.SetLayerMode(True)
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    writer.Transfer(doc, STEPControl_AsIs)
    writer.Write(str(out_path))
    return out_path


def read_step_layer_assignments(step_path: Path) -> dict[str, set[str]]:
    """Re-import a STEP file and return ``{shape_repr: {layer_name, ...}}``.

    Used by tests / smoke checks to verify layer info survives the
    write→read roundtrip. ``shape_repr`` is a stable key (``shape_N``)
    ordered by the free-shape sequence; we don't try to match by inst
    name (STEP loses that).

    Layer names are read by walking each layer label's TDataStd_Name
    attribute — XCAFDoc_LayerTool's GetLayer overload that returns the
    name string takes an out-param that OCP doesn't expose nicely.
    """
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    app = XCAFApp_Application.GetApplication_s()
    fmt = TCollection_ExtendedString("MDTV-XCAF")
    doc = TDocStd_Document(fmt)
    app.NewDocument(fmt, doc)

    reader = STEPCAFControl_Reader()
    reader.SetLayerMode(True)
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    if not reader.ReadFile(str(step_path)):
        raise RuntimeError(f"failed to open {step_path}")
    if not reader.Transfer(doc):
        raise RuntimeError(f"failed to transfer {step_path}")

    main_label = doc.Main()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(main_label)
    layer_tool = XCAFDoc_DocumentTool.LayerTool_s(main_label)

    shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(shapes)

    out: dict[str, set[str]] = {}
    for i in range(1, shapes.Length() + 1):
        lbl = shapes.Value(i)
        layers = TDF_LabelSequence()
        layer_tool.GetLayers(lbl, layers)
        names: set[str] = set()
        for j in range(1, layers.Length() + 1):
            attr = TDataStd_Name()
            if layers.Value(j).FindAttribute(TDataStd_Name.GetID_s(), attr):
                names.add(attr.Get().ToExtString())
        out[f"shape_{i}"] = names
    return out
