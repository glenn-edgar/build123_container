# SPDX-License-Identifier: LGPL-2.1-or-later
"""build123d shape ↔ STEP/BREP bytes, plus geometry hashing.

We use tempfile+disk for serialization rather than ``Standard_OStream`` plumbing
because the file API is stable across OCP versions and the cost is negligible.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any


def shape_to_step_bytes(shape: Any) -> bytes:
    """Export a build123d shape to STEP file format, return bytes."""
    from build123d import export_step

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
        path = f.name
    try:
        export_step(shape, path)
        return Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)


def shape_to_stl_bytes(shape: Any) -> bytes:
    from build123d import export_stl

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        path = f.name
    try:
        export_stl(shape, path)
        return Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)


def shape_to_brep_bytes(shape: Any) -> bytes:
    """Export a shape's underlying TopoDS_Shape to BREP, return bytes."""
    from OCP.BRepTools import BRepTools

    inner = shape.wrapped if hasattr(shape, "wrapped") else shape
    with tempfile.NamedTemporaryFile(suffix=".brep", delete=False) as f:
        path = f.name
    try:
        BRepTools.Write_s(inner, path)
        return Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)


def brep_bytes_to_shape(blob: bytes) -> Any:
    """Reverse of shape_to_brep_bytes. Returns a build123d Shape."""
    from build123d import Shape
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    with tempfile.NamedTemporaryFile(suffix=".brep", delete=False) as f:
        f.write(blob)
        path = f.name
    try:
        topods_shape = TopoDS_Shape()
        builder = BRep_Builder()
        BRepTools.Read_s(topods_shape, path, builder)
        return Shape(topods_shape)
    finally:
        Path(path).unlink(missing_ok=True)


def geometry_hash(step_bytes: bytes) -> str:
    """Content hash for the geometry table key. Prototype: sha256 of STEP bytes."""
    return hashlib.sha256(step_bytes).hexdigest()
