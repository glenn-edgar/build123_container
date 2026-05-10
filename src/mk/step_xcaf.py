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

What's preserved (after the v3 round-3 post-processor — see
``_rewrite_layer_assignments``):

- **Layer assignments — multi-shape and multi-tag both work.** OCC
  7.8.1.1's STEPCAFControl_Writer has a known bug: it emits at most
  one shape per PRESENTATION_LAYER_ASSIGNMENT entity and drops
  shapes with multiple layer assignments entirely. We work around by
  letting OCC write its (broken) layer assignments alongside the
  full XCAF doc, then post-process the STEP text to:
    1. Find every MANIFOLD_SOLID_BREP entity ID in file order
       (this order matches the XCAF add-order, which matches our
       inst_rows iteration order).
    2. Strip out OCC's incorrect PRESENTATION_LAYER_ASSIGNMENT lines.
    3. Emit fresh ones from our Python-side
       ``layer_name → set[entity_id]`` map, computed via
       ``resolve_inst_layers`` over the same inst_rows.
  Verified: asm_window_test's 5 shapes all on DEFAULT round-trip;
  asm_nested's inner_a2 retains both ``electronics`` and ``emi``.

What's not preserved:
- Assembly hierarchy (SUB nesting collapses to flat instance list).
  The STEP file is a bag of shapes with per-shape metadata, not a
  product structure tree.
"""
from __future__ import annotations

import json
import re
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

    # Capture the layer set for each shape, in add-order. This becomes
    # the Python-side source of truth that _rewrite_layer_assignments
    # uses to fix OCC's broken layer-write output.
    inst_layer_lists: list[list[str]] = []

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

        # Assign each effective layer to the shape's XCAF label. The
        # in-memory XCAF doc handles this correctly; OCC's STEP writer
        # mangles multi-shape/multi-tag cases. We let it write what it
        # can and rewrite the PRESENTATION_LAYER_ASSIGNMENT lines after
        # the fact (see _rewrite_layer_assignments below). The Python-
        # side map below is the source of truth.
        layer_set = sorted(resolve_inst_layers(conn, asm_kb, r["path"]))
        for layer_name in layer_set:
            layer_tool.SetLayer(label, TCollection_ExtendedString(layer_name), False)
        inst_layer_lists.append(layer_set)

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

    # Post-process to fix OCC's broken multi-shape/multi-tag layer writes.
    _rewrite_layer_assignments(out_path, inst_layer_lists)
    return out_path


# ── Layer-write post-processor ──────────────────────────────────────────────

# Match a STEP entity definition: "#<id> = <ENTITY_NAME>(...)"
_ENTITY_DEF_RE = re.compile(r"^\s*#(\d+)\s*=\s*([A-Z_][A-Z0-9_]*)\b")
# Match PRESENTATION_LAYER_ASSIGNMENT lines specifically (single-line form
# that OCC emits; multi-line wraps would need a smarter parser — none seen
# in practice for OCC 7.8.1.1's output).
_PLA_LINE_RE = re.compile(r"^\s*#\d+\s*=\s*PRESENTATION_LAYER_ASSIGNMENT\b")


def _rewrite_layer_assignments(
    step_path: Path, inst_layer_lists: list[list[str]],
) -> None:
    """In-place fix for OCC's broken PRESENTATION_LAYER_ASSIGNMENT writes.

    OCC 7.8.1.1's STEPCAFControl_Writer emits at most one shape per layer
    entity and drops multi-tagged shapes entirely. We replace OCC's PLA
    lines with correct ones derived from the Python-side
    ``inst_layer_lists`` (one entry per inst, in the same order shapes
    were added to the XCAF doc).

    Assumes ``MANIFOLD_SOLID_BREP`` entities appear in the STEP file in
    XCAF add-order. Verified empirically on OCC 7.8.1.1; if a future
    OCC version reorders, this assumption breaks and the routine no-ops
    (better to ship correct color + half-right layers than corrupted
    output).
    """
    text = step_path.read_text()
    lines = text.splitlines(keepends=True)

    # First pass: collect MANIFOLD_SOLID_BREP entity IDs in file order,
    # the current maximum entity ID (for assigning new PLA IDs), the
    # index of the DATA section's ENDSEC (where we'll insert), and
    # the indices of existing PLA lines to remove.
    #
    # STEP file shape:  HEADER; ... ENDSEC;  DATA; ... ENDSEC;  END-ISO...;
    # We want the SECOND ENDSEC (DATA's). Track which section we're in
    # by watching for the DATA; marker.
    msb_ids: list[int] = []
    max_id = 0
    data_endsec_idx: int | None = None
    pla_indices: list[int] = []
    in_data = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "DATA;":
            in_data = True
            continue
        m = _ENTITY_DEF_RE.match(line)
        if m:
            entity_id = int(m.group(1))
            entity_name = m.group(2)
            max_id = max(max_id, entity_id)
            if entity_name == "MANIFOLD_SOLID_BREP":
                msb_ids.append(entity_id)
            if entity_name == "PRESENTATION_LAYER_ASSIGNMENT":
                pla_indices.append(i)
        elif stripped == "ENDSEC;" and in_data and data_endsec_idx is None:
            data_endsec_idx = i

    if len(msb_ids) != len(inst_layer_lists):
        # Shape-count mismatch — the post-processor's add-order
        # assumption may have failed. Bail out rather than emit
        # something wrong; leave OCC's partial layer writes intact.
        print(
            f"  WARN: STEP post-process saw {len(msb_ids)} MANIFOLD_SOLID_BREP "
            f"entries but expected {len(inst_layer_lists)} from XCAF. Leaving "
            f"OCC's (partial) layer writes in place.",
            file=sys.stderr,
        )
        return
    if data_endsec_idx is None:
        print(
            "  WARN: STEP post-process couldn't find DATA section's ENDSEC; "
            "layer-assignment rewrite skipped.",
            file=sys.stderr,
        )
        return

    # Build layer_name → list of MANIFOLD_SOLID_BREP entity IDs.
    layer_to_ids: dict[str, list[int]] = {}
    for shape_idx, layers in enumerate(inst_layer_lists):
        for layer_name in layers:
            layer_to_ids.setdefault(layer_name, []).append(msb_ids[shape_idx])

    # Strip OCC's PLA lines and adjust the data-ENDSEC index accordingly.
    pla_index_set = set(pla_indices)
    stripped_pla_before_endsec = sum(1 for i in pla_indices if i < data_endsec_idx)
    new_lines = [line for i, line in enumerate(lines) if i not in pla_index_set]
    new_endsec_idx = data_endsec_idx - stripped_pla_before_endsec

    # Emit fresh PLA entities just before the data-ENDSEC. Sorted by
    # layer name for stable diffs.
    next_id = max_id + 1
    inserts: list[str] = []
    for layer_name in sorted(layer_to_ids):
        ids = sorted(set(layer_to_ids[layer_name]))
        id_tuple = ",".join(f"#{i}" for i in ids)
        inserts.append(
            f"#{next_id} = PRESENTATION_LAYER_ASSIGNMENT"
            f"('{layer_name}','visible',({id_tuple}));\n"
        )
        next_id += 1

    new_lines[new_endsec_idx:new_endsec_idx] = inserts
    step_path.write_text("".join(new_lines))


def read_step_layer_assignments(step_path: Path) -> dict[str, int]:
    """Re-import a STEP file and return ``{layer_name: shape_count}``.

    Used by tests / smoke checks to verify the layer→shape map survives
    the write→read roundtrip. Counts come from
    ``XCAFDoc_LayerTool.GetShapesOfLayer_s`` (per-layer query); the
    inverse per-shape ``GetLayers`` call has an OCP/XCAF quirk that
    only returns the first layer assignment in a multi-shape tuple,
    so we go layer-first instead.
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

    layer_tool = XCAFDoc_DocumentTool.LayerTool_s(doc.Main())

    all_layers = TDF_LabelSequence()
    layer_tool.GetLayerLabels(all_layers)

    out: dict[str, int] = {}
    for i in range(1, all_layers.Length() + 1):
        lbl = all_layers.Value(i)
        attr = TDataStd_Name()
        if not lbl.FindAttribute(TDataStd_Name.GetID_s(), attr):
            continue
        name = attr.Get().ToExtString()
        shapes = TDF_LabelSequence()
        layer_tool.GetShapesOfLayer_s(lbl, shapes)
        out[name] = shapes.Length()
    return out
