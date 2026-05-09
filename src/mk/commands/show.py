# SPDX-License-Identifier: MPL-2.0
"""mk show <asm-kb>: write glTF to /project/outputs/<asm>.gltf for the viewer.

The viewer service (Compose) runs `yacv-server --watch /project/outputs` and
serves at http://localhost:32323. Hot-reloads when this command rewrites the
glTF. Bring it up once with `docker compose up -d viewer`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mk.db import DEFAULT_DB_PATH, open_db
from mk.geometry import brep_bytes_to_shape
from mk.transform import build123d_location

DEFAULT_OUTDIR = "/project/outputs"
VIEWER_URL = "http://localhost:32323"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("show", help="Write glTF for the yacv viewer to load.")
    p.add_argument("asm_kb")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--outdir", default=DEFAULT_OUTDIR)
    p.add_argument(
        "--binary", action="store_true",
        help="emit .glb (binary glTF) instead of .gltf",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    conn = open_db(args.db)

    rows = conn.execute(
        "SELECT path, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (args.asm_kb,),
    ).fetchall()
    if not rows:
        print(f"no INST rows in {args.asm_kb}", file=sys.stderr)
        conn.close()
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
            conn.close()
            return 1
        blob_row = conn.execute(
            "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
        ).fetchone()
        if blob_row is None:
            print(
                f"  ERR: geometry hash {gh[:12]} not in cache for {r['path']}",
                file=sys.stderr,
            )
            conn.close()
            return 1

        shape = brep_bytes_to_shape(blob_row["brep_blob"])
        loc = build123d_location(props.get("location"))
        if loc is not None:
            shape = loc * shape
        shapes.append(shape)

    conn.close()

    from build123d import Compound, export_gltf

    compound = Compound(shapes)

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".glb" if args.binary else ".gltf"
    out_path = out_dir / f"{args.asm_kb}{suffix}"

    export_gltf(compound, str(out_path), binary=args.binary)

    # Emit a tiny index.html alongside the glTF so the viewer service
    # (a plain http.server) has something to render at /. <model-viewer> is
    # Google's web component; loaded from CDN so this needs internet on the
    # first visit. Browser refresh required after each `mk show` rerun —
    # there's no auto-reload in this prototype.
    index_path = out_dir / "index.html"
    index_path.write_text(_index_html(out_path.name))

    print(f"wrote {out_path}  ({out_path.stat().st_size} bytes)")
    print(f"viewer: {VIEWER_URL}  (run `docker compose up -d viewer` if not already up)")
    return 0


def _index_html(gltf_filename: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>mk-cad viewer — {gltf_filename}</title>
<script type="module"
  src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js">
</script>
<style>
  html, body {{ margin: 0; height: 100%; background: #1e1e1e; color: #ddd;
                font-family: ui-monospace, monospace; }}
  model-viewer {{ width: 100%; height: 100%; --poster-color: #1e1e1e; }}
  .label {{ position: fixed; top: 8px; left: 12px; font-size: 12px;
            opacity: 0.65; pointer-events: none; }}
</style>
</head>
<body>
<div class="label">{gltf_filename} — refresh after `mk show` to reload</div>
<model-viewer src="{gltf_filename}" alt="mk-cad assembly"
              camera-controls touch-action="pan-y"
              shadow-intensity="1" exposure="1.1"
              auto-rotate auto-rotate-delay="3000">
</model-viewer>
</body>
</html>
"""
