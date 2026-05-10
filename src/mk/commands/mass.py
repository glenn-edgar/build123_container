# SPDX-License-Identifier: MPL-2.0
"""mk mass <asm-kb>: total mass, CoM, inertia tensor, principal moments+axes.

Conventions (mm/g, per spec §10 Phase 4):
- build123d/OCC operates in millimetres; volume is mm^3.
- Density rows store g/cm^3 in part KB's META.density.value.
- mass(g) = volume(mm^3) * density(g/cm^3) / 1000.

INST.location.loc is honoured (translation only). Mate-resolved positions
(rotation, joint coincidence) are a Phase 6 concern; if absent we use
each part's local origin.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from mk.db import DEFAULT_DB_PATH, kb_exists, open_db
from mk.geometry import brep_bytes_to_shape
from mk.transform import apply_location_to_topods

DEFAULT_DENSITY = 1.0  # g/cm^3 if META.density absent


def _part_density(conn, part_kb: str) -> float:
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'META' AND name = 'density'",
        (part_kb,),
    ).fetchone()
    if row is None:
        return DEFAULT_DENSITY
    val = json.loads(row["properties"]).get("value")
    return float(val) if val is not None else DEFAULT_DENSITY


def _part_mass_override(conn, part_kb: str) -> float | None:
    """Return META.mass_g_override.value if present (grams), else None.

    When present, supersedes the volume × density calc so hollow assemblies
    (motors, enclosures) report their datasheet mass instead of the
    over-counted geometric estimate.
    """
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'META' AND name = 'mass_g_override'",
        (part_kb,),
    ).fetchone()
    if row is None:
        return None
    val = json.loads(row["properties"]).get("value")
    return float(val) if val is not None else None


def _located_topods(blob: bytes, location: dict[str, Any] | None):
    """Return a TopoDS_Shape with the INST's location (translation+rotation) applied."""
    shape = brep_bytes_to_shape(blob)
    return apply_location_to_topods(shape.wrapped, location)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("mass", help="Mass / CoM / inertia for an assembly KB.")
    p.add_argument("asm_kb", help="assembly KB name, e.g. asm_demo")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument(
        "--respect-layers", action="store_true",
        help="exclude insts on hidden layers (default: include all — "
             "engineering data shouldn't change with viewer state)",
    )
    # `mk -v mass <asm>` (the global verbose flag) also enables per-inst lines.
    # A subcommand --per-inst exists so `mk mass <asm> --per-inst` works
    # without having to put the flag before the subcommand name.
    p.add_argument(
        "--per-inst", action="store_true",
        help="also print per-inst volume / mass / CoM (default: summary only)",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    conn = open_db(args.db)

    if not kb_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    rows = conn.execute(
        "SELECT path, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (args.asm_kb,),
    ).fetchall()
    if not rows:
        print(f"{args.asm_kb} has no INST rows", file=sys.stderr)
        conn.close()
        return 1

    if getattr(args, "respect_layers", False):
        from mk.layers import partition_by_visibility
        rows, hidden_count = partition_by_visibility(conn, args.asm_kb, rows)
        if hidden_count > 0:
            print(f"  layer filter: {hidden_count} hidden inst(s) excluded from mass tally")

    total = GProp_GProps()
    n_inst = 0
    per_inst_lines: list[str] = []

    for r in rows:
        props = json.loads(r["properties"])
        gh = props.get("geom_hash")
        ref_kb = props.get("ref_kb")
        if not gh or not ref_kb:
            print(f"  skip {r['path']}: missing geom_hash or ref_kb (run mk build first?)",
                  file=sys.stderr)
            continue

        blob_row = conn.execute(
            "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
        ).fetchone()
        if blob_row is None:
            print(f"  skip {r['path']}: BREP {gh[:12]} missing from cache", file=sys.stderr)
            continue

        topods = _located_topods(blob_row["brep_blob"], props.get("location"))
        density = _part_density(conn, ref_kb)
        mass_override = _part_mass_override(conn, ref_kb)

        item = GProp_GProps()
        BRepGProp.VolumeProperties_s(topods, item)
        vol_mm3 = item.Mass()  # GProp_GProps.Mass() of VolumeProperties = volume

        # If META.mass_g_override is present, use a virtual density that makes
        # GProp_GProps.Add produce exactly that mass. The same factor scales
        # inertia proportionally — correct under the uniform-density
        # approximation we use throughout.
        if mass_override is not None and vol_mm3 > 0:
            effective_factor = mass_override * 1000.0 / vol_mm3
            mass_g = mass_override
            tag = f"override {mass_override:.4f} g"
        else:
            effective_factor = density
            mass_g = vol_mm3 * density / 1000.0
            tag = f"ρ={density:g}"

        total.Add(item, effective_factor)
        n_inst += 1

        # Capture per-inst details but defer printing until after the
        # summary unless -v is set. Keeps the "how heavy is this?"
        # common case to four lines of output.
        com = item.CentreOfMass()
        per_inst_lines.append(
            f"  {r['path']}  {tag}  V={vol_mm3:.3f} mm^3  "
            f"m={mass_g:.4f} g  com=({com.X():.3f},{com.Y():.3f},{com.Z():.3f})"
        )

    conn.close()

    if n_inst == 0:
        print("no buildable instances", file=sys.stderr)
        return 1

    # `total.Mass()` here is sum(volume_i * density_i) in mm^3·(g/cm^3) = mg·1000 → grams ÷1000.
    # Equivalently sum_i(vol_i_mm3 * density_g_per_cm3) / 1000 == grams.
    total_grams = total.Mass() / 1000.0
    com = total.CentreOfMass()
    inertia = total.MatrixOfInertia()  # gp_Mat
    pp = total.PrincipalProperties()
    p1, p2, p3 = pp.Moments()
    a1 = pp.FirstAxisOfInertia()
    a2 = pp.SecondAxisOfInertia()
    a3 = pp.ThirdAxisOfInertia()

    # Summary first (the common-case "how heavy is this?" answer).
    print(f"{args.asm_kb}: {n_inst} inst(s)")
    print(f"total mass:    {total_grams:.4f} g")
    print(f"centre of mass:  ({com.X():.4f}, {com.Y():.4f}, {com.Z():.4f}) mm")
    print(f"inertia tensor (g·mm^2, weighted):")
    for i in (1, 2, 3):
        row = "  " + "  ".join(f"{inertia.Value(i, j) / 1000.0:>14.4f}" for j in (1, 2, 3))
        print(row)
    print(f"principal moments (g·mm^2):  {p1 / 1000.0:.4f}  {p2 / 1000.0:.4f}  {p3 / 1000.0:.4f}")
    print(f"principal axes:")
    for label, ax in (("e1", a1), ("e2", a2), ("e3", a3)):
        print(f"  {label} = ({ax.X():.4f}, {ax.Y():.4f}, {ax.Z():.4f})")

    # Per-inst details after the summary, only on --per-inst (or the
    # top-level -v). Saves the common reader from scrolling past 5+
    # lines of intermediates.
    show_per_inst = getattr(args, "per_inst", False) or getattr(args, "verbose", False)
    if show_per_inst and per_inst_lines:
        print()
        print("per-instance breakdown:")
        for line in per_inst_lines:
            print(line)
    return 0
