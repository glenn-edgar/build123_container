# SPDX-License-Identifier: MPL-2.0
"""mk show <asm-kb>: glTF + measurement-augmented index.html for the viewer.

The viewer service (Compose) runs `python -m http.server` over /project/outputs
and serves at http://localhost:32323. Browser refresh required after each
`mk show` rerun — there's no auto-reload in this prototype.

The emitted index.html embeds a sidebar panel with overall bbox, mass, and
joint world-coords, plus 3D hotspots pinned at every joint origin. Static —
frozen at `mk show` time. The browser loads the glTF via Google's
<model-viewer> web component (CDN, needs internet on first visit).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from mk.db import DEFAULT_DB_PATH, open_db
from mk.geometry import brep_bytes_to_shape
from mk.transform import apply_location_to_topods, build123d_location, trsf_from_location

DEFAULT_OUTDIR = "/project/outputs"
VIEWER_URL = "http://localhost:32323"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("show", help="Write glTF + index.html for the viewer.")
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

    inst_rows = conn.execute(
        "SELECT path, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (args.asm_kb,),
    ).fetchall()
    if not inst_rows:
        print(f"no INST rows in {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    shapes = []
    inst_summaries: list[dict[str, Any]] = []
    overall_min = [math.inf] * 3
    overall_max = [-math.inf] * 3

    for r in inst_rows:
        props = json.loads(r["properties"])
        gh = props.get("geom_hash")
        ref_kb = props.get("ref_kb")
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
        shape_for_export = loc * shape if loc is not None else shape
        shapes.append(shape_for_export)

        # Per-instance world-frame bbox for the sidebar.
        topods_world = apply_location_to_topods(shape.wrapped, props.get("location"))
        bmin, bmax = _bbox(topods_world)
        for i in (0, 1, 2):
            overall_min[i] = min(overall_min[i], bmin[i])
            overall_max[i] = max(overall_max[i], bmax[i])
        inst_summaries.append(
            {"name": r["name"], "ref_kb": ref_kb, "bmin": bmin, "bmax": bmax}
        )

    # Joint world frames (one per part-joint per inst).
    joints_for_hotspots: list[dict[str, Any]] = []
    for r in inst_rows:
        props = json.loads(r["properties"])
        ref_kb = props.get("ref_kb")
        if ref_kb is None:
            continue
        trsf = trsf_from_location(props.get("location"))
        joint_rows = conn.execute(
            "SELECT name, properties FROM knowledge_base "
            "WHERE knowledge_base = ? AND label = 'JOINT' ORDER BY name",
            (ref_kb,),
        ).fetchall()
        for jr in joint_rows:
            jp = json.loads(jr["properties"])
            origin_local = [float(x) for x in jp["origin"]]
            world = _apply_trsf_to_point(trsf, origin_local)
            joints_for_hotspots.append(
                {"label": f"{r['name']}.{jr['name']}", "world_mm": world}
            )

    # Mass (best-effort — skip if any inst missing meta).
    mass_g, com_world = _mass_and_com(conn, args.asm_kb, inst_rows)

    conn.close()

    from build123d import Compound, export_gltf

    compound = Compound(shapes)

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".glb" if args.binary else ".gltf"
    out_path = out_dir / f"{args.asm_kb}{suffix}"
    export_gltf(compound, str(out_path), binary=args.binary)

    overall_extent = [overall_max[i] - overall_min[i] for i in (0, 1, 2)]
    index_path = out_dir / "index.html"
    index_path.write_text(
        _index_html(
            asm_kb=args.asm_kb,
            gltf_filename=out_path.name,
            overall_min=overall_min,
            overall_max=overall_max,
            overall_extent=overall_extent,
            instances=inst_summaries,
            joints=joints_for_hotspots,
            mass_g=mass_g,
            com_world=com_world,
        )
    )

    print(f"wrote {out_path}  ({out_path.stat().st_size} bytes)")
    print(f"wrote {index_path} with {len(joints_for_hotspots)} joint hotspot(s)")
    print(f"viewer: {VIEWER_URL}  (run `docker compose up -d viewer` if not already up)")
    return 0


def _bbox(topods) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(topods, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return (xmin, ymin, zmin), (xmax, ymax, zmax)


def _apply_trsf_to_point(trsf, pt: list[float]) -> list[float]:
    if trsf is None:
        return list(pt)
    from OCP.gp import gp_Pnt

    p = gp_Pnt(float(pt[0]), float(pt[1]), float(pt[2]))
    p.Transform(trsf)
    return [p.X(), p.Y(), p.Z()]


def _mass_and_com(conn, asm_kb: str, inst_rows) -> tuple[float | None, list[float] | None]:
    """Best-effort mass + CoM. Returns (None, None) if anything's missing."""
    try:
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        total = GProp_GProps()
        for r in inst_rows:
            props = json.loads(r["properties"])
            gh = props.get("geom_hash")
            ref_kb = props.get("ref_kb")
            if not gh or not ref_kb:
                return None, None
            blob = conn.execute(
                "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
            ).fetchone()
            if blob is None:
                return None, None
            shape = brep_bytes_to_shape(blob["brep_blob"])
            topods = apply_location_to_topods(shape.wrapped, props.get("location"))
            density_row = conn.execute(
                "SELECT properties FROM knowledge_base "
                "WHERE knowledge_base = ? AND label = 'META' AND name = 'density'",
                (ref_kb,),
            ).fetchone()
            density = (
                float(json.loads(density_row["properties"]).get("value", 1.0))
                if density_row else 1.0
            )
            item = GProp_GProps()
            BRepGProp.VolumeProperties_s(topods, item)
            total.Add(item, density)
        com = total.CentreOfMass()
        return total.Mass() / 1000.0, [com.X(), com.Y(), com.Z()]
    except Exception:
        return None, None


def _index_html(
    *,
    asm_kb: str,
    gltf_filename: str,
    overall_min: list[float],
    overall_max: list[float],
    overall_extent: list[float],
    instances: list[dict[str, Any]],
    joints: list[dict[str, Any]],
    mass_g: float | None,
    com_world: list[float] | None,
) -> str:
    def fmt3(v):
        return f"({v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f})"

    inst_rows_html = "".join(
        f"<tr><td>{i['name']}</td><td>{i['ref_kb']}</td>"
        f"<td>{fmt3(i['bmin'])}</td><td>{fmt3(i['bmax'])}</td></tr>"
        for i in instances
    )
    joint_rows_html = "".join(
        f"<tr><td>{j['label']}</td><td>{fmt3(j['world_mm'])}</td></tr>"
        for j in joints
    )
    # Hotspots: model-viewer expects positions in METRES (glTF native).
    # Our world coords are mm; divide by 1000.
    hotspot_html = "".join(
        f'<button class="Hotspot" slot="hotspot-{i}" '
        f'data-position="{j["world_mm"][0] / 1000:.6f} '
        f'{j["world_mm"][1] / 1000:.6f} {j["world_mm"][2] / 1000:.6f}" '
        f'data-normal="0 1 0" data-visibility-attribute="visible">'
        f'<span class="HotspotLabel">{j["label"]}</span></button>'
        for i, j in enumerate(joints)
    )

    mass_line = (
        f"<tr><th>mass</th><td>{mass_g:.4f} g</td></tr>"
        f"<tr><th>CoM (mm)</th><td>{fmt3(com_world)}</td></tr>"
        if mass_g is not None and com_world is not None
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>mk-cad viewer — {asm_kb}</title>
<script type="module"
  src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js">
</script>
<style>
  html, body {{ margin: 0; height: 100%; background: #1e1e1e; color: #ddd;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 12px; }}
  model-viewer {{ width: 100%; height: 100%; --poster-color: #1e1e1e; }}
  .panel {{ position: fixed; top: 12px; right: 12px; max-width: 460px;
            background: rgba(30,30,30,0.92); border: 1px solid #444;
            padding: 10px 14px; border-radius: 4px;
            max-height: calc(100vh - 24px); overflow-y: auto; }}
  .panel h2 {{ margin: 0 0 4px 0; font-size: 13px; color: #fff;
               border-bottom: 1px solid #444; padding-bottom: 4px; }}
  .panel h3 {{ margin: 10px 0 4px 0; font-size: 11px; color: #aaa;
               text-transform: uppercase; letter-spacing: 0.05em; }}
  .panel table {{ border-collapse: collapse; width: 100%; }}
  .panel th, .panel td {{ padding: 2px 6px; text-align: left;
                          font-size: 11px; vertical-align: top; }}
  .panel th {{ color: #aaa; font-weight: normal; white-space: nowrap; }}
  .panel td {{ color: #ddd; }}
  .panel tr:nth-child(even) td {{ background: rgba(255,255,255,0.03); }}
  .footer {{ position: fixed; bottom: 8px; left: 12px;
             font-size: 10px; opacity: 0.5; pointer-events: none; }}
  .Hotspot {{ background: #ff9028; border: 1px solid #fff;
              border-radius: 50%; box-shadow: 0 0 4px rgba(0,0,0,0.6);
              cursor: pointer; height: 14px; width: 14px;
              padding: 0; pointer-events: auto; }}
  .Hotspot:hover .HotspotLabel,
  .Hotspot:focus .HotspotLabel {{ display: block; }}
  .HotspotLabel {{ display: none; position: absolute; top: 18px; left: 18px;
                   background: rgba(0,0,0,0.85); color: #fff;
                   padding: 2px 6px; border-radius: 3px; white-space: nowrap;
                   font-size: 11px; pointer-events: none; }}
</style>
</head>
<body>
<model-viewer src="{gltf_filename}" alt="{asm_kb}"
              camera-controls touch-action="pan-y"
              shadow-intensity="1" exposure="1.1"
              auto-rotate auto-rotate-delay="3000">
{hotspot_html}
</model-viewer>

<div class="panel">
  <h2>{asm_kb}</h2>
  <table>
    <tr><th>bbox extent (mm)</th>
        <td>{overall_extent[0]:.2f} × {overall_extent[1]:.2f} × {overall_extent[2]:.2f}</td></tr>
    <tr><th>bbox min</th><td>{fmt3(overall_min)}</td></tr>
    <tr><th>bbox max</th><td>{fmt3(overall_max)}</td></tr>
    {mass_line}
  </table>

  <h3>instances ({len(instances)})</h3>
  <table>
    <tr><th>name</th><th>ref_kb</th><th>min</th><th>max</th></tr>
    {inst_rows_html}
  </table>

  <h3>joints ({len(joints)}) — hover dots on model</h3>
  <table>
    <tr><th>label</th><th>world (mm)</th></tr>
    {joint_rows_html}
  </table>
</div>

<div class="footer">refresh after `mk show` to reload</div>
</body>
</html>
"""
