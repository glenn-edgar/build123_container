# SPDX-License-Identifier: LGPL-2.1-or-later
"""mk export <asm-kb> <fmt>: write STEP / STL / BREP for the assembly."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mk.db import DEFAULT_DB_PATH, open_db
from mk.geometry import brep_bytes_to_shape, shape_to_brep_bytes
from mk.transform import build123d_location


DEFAULT_OUTDIR = "/project/outputs"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("export", help="Export assembly geometry.")
    p.add_argument("asm_kb")
    p.add_argument("format", choices=["step", "stl", "brep"])
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--outdir", default=DEFAULT_OUTDIR)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    conn = open_db(args.db)

    rows = conn.execute(
        "SELECT path, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (args.asm_kb,),
    ).fetchall()
    if not rows:
        print(f"no INST rows in {args.asm_kb}", file=sys.stderr)
        return 1

    shapes = []
    for r in rows:
        props = json.loads(r["properties"])
        gh = props.get("geom_hash")
        if gh is None:
            print(
                f"  ERR: {r['path']} has no geom_hash. run `mk build {args.asm_kb}` first.",
                file=sys.stderr,
            )
            return 1
        blob_row = conn.execute(
            "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
        ).fetchone()
        if blob_row is None:
            print(
                f"  ERR: geometry hash {gh[:12]} not in cache for {r['path']}",
                file=sys.stderr,
            )
            return 1

        shape = brep_bytes_to_shape(blob_row["brep_blob"])

        b123d_loc = build123d_location(props.get("location"))
        if b123d_loc is not None:
            shape = b123d_loc * shape

        shapes.append(shape)

    from build123d import Compound, export_step, export_stl

    compound = Compound(shapes)

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.asm_kb}.{args.format}"

    if args.format == "step":
        export_step(compound, str(out_path))
    elif args.format == "stl":
        export_stl(compound, str(out_path))
    elif args.format == "brep":
        out_path.write_bytes(shape_to_brep_bytes(compound))

    conn.close()
    print(f"wrote {out_path}  ({out_path.stat().st_size} bytes)")
    return 0
