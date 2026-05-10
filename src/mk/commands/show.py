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

    # Phase C.3: viewer respects layer visibility — hidden parts vanish
    # entirely from the glTF, sidebar, joint hotspots, and mass tally.
    from mk.layers import partition_by_visibility
    inst_rows, hidden_count = partition_by_visibility(conn, args.asm_kb, inst_rows)
    if hidden_count > 0:
        print(f"  layer filter: {hidden_count} hidden inst(s) excluded from view")
    if not inst_rows:
        print(
            f"no visible INST rows in {args.asm_kb} — every part is on a hidden layer",
            file=sys.stderr,
        )
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

        # Per-part color via META.color (hex string or build123d-named color).
        # build123d's export_gltf preserves shape colors via XCAF. Apply after
        # location since `loc * shape` returns a new shape that doesn't inherit
        # the color attribute.
        color_value = _read_part_meta(conn, ref_kb, "color") if ref_kb else None
        if color_value:
            color = _parse_color(color_value)
            if color is not None:
                shape_for_export.color = color
            else:
                print(
                    f"  WARN: {r['path']} META.color={color_value!r} not understood; skipping",
                    file=sys.stderr,
                )

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

    # Use children= keyword (not positional) so the tree-iteration in
    # export_gltf sees per-child colors. Compound(positional_list) builds
    # a TopoDS_Compound but leaves the NodeMixin children empty, so colors
    # never reach the XCAF document.
    compound = Compound(children=shapes)

    # Per-assembly subdirectory so multiple assemblies can coexist in the
    # viewer. Browser URL becomes /<asm_kb>/ instead of /.
    out_root = Path(args.outdir)
    out_dir = out_root / args.asm_kb
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

    # Top-level listing of all assemblies that have an index.html. Refreshed
    # on every mk show so a recently-built assembly always appears.
    listing_path = out_root / "index.html"
    listing_path.write_text(_listing_html(out_root))

    print(f"wrote {out_path}  ({out_path.stat().st_size} bytes)")
    print(f"wrote {index_path} with {len(joints_for_hotspots)} joint hotspot(s)")
    print(f"viewer: {VIEWER_URL}/{args.asm_kb}/  (or {VIEWER_URL}/ for index)")
    print(f"  (run `docker compose up -d viewer` if not already up)")
    return 0


def _listing_html(out_root: Path) -> str:
    """Top-level outputs/index.html — links to every per-assembly viewer page.

    Scans out_root for subdirectories that contain an index.html, lists them
    with a small 'opened-in-this-session' indicator (most recently modified
    first).
    """
    entries = []
    for child in sorted(out_root.iterdir()):
        if not child.is_dir():
            continue
        idx = child / "index.html"
        if not idx.exists():
            continue
        entries.append({
            "name": child.name,
            "mtime": idx.stat().st_mtime,
        })
    entries.sort(key=lambda e: -e["mtime"])

    rows_html = "".join(
        f'<li><a href="{e["name"]}/">{e["name"]}</a></li>'
        for e in entries
    ) or "<li><em>No assemblies yet. Run <code>mk show &lt;asm&gt;</code>.</em></li>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>mk-cad — assemblies</title>
<style>
  html, body {{ margin: 0; padding: 24px; background: #1e1e1e; color: #ddd;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 13px; }}
  h1 {{ font-size: 16px; color: #fff; margin: 0 0 16px 0; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ padding: 6px 0; border-bottom: 1px solid #333; }}
  li:last-child {{ border-bottom: none; }}
  a {{ color: #6cf; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ margin-top: 24px; opacity: 0.5; font-size: 11px; }}
</style>
</head>
<body>
<h1>mk-cad — assemblies in /project/outputs/</h1>
<ul>
{rows_html}
</ul>
<div class="footer">
  Sorted by most-recently-shown. Each link opens that assembly's viewer
  page (sidebar panels, joint hotspots, draggable). Refresh this index
  after running another <code>mk show &lt;asm&gt;</code>.
</div>
</body>
</html>
"""


def _parse_color(value):
    """Convert a META.color value to a build123d Color, or None on failure.
    Accepts: hex strings ('#rgb', '#rrggbb'), RGB tuples/lists, or
    build123d-recognized color names ('red', 'orange', etc.).
    """
    from build123d import Color

    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        return Color(*value)
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("#"):
            h = s.lstrip("#")
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            if len(h) != 6:
                return None
            try:
                r = int(h[0:2], 16) / 255.0
                g = int(h[2:4], 16) / 255.0
                b = int(h[4:6], 16) / 255.0
                return Color(r, g, b)
            except ValueError:
                return None
        try:
            return Color(s)
        except Exception:
            return None
    return None


def _read_part_meta(conn, part_kb: str, name: str):
    """Return the `value` field of a single META row, or None if absent."""
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'META' AND name = ?",
        (part_kb, name),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["properties"]).get("value")


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
    """Best-effort mass + CoM. Returns (None, None) if anything's missing.

    Honors META.mass_g_override on a part (falls back to volume × density).
    """
    try:
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        def _meta_value(part_kb: str, meta_name: str):
            row = conn.execute(
                "SELECT properties FROM knowledge_base "
                "WHERE knowledge_base = ? AND label = 'META' AND name = ?",
                (part_kb, meta_name),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["properties"]).get("value")

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

            mass_override = _meta_value(ref_kb, "mass_g_override")
            density_v = _meta_value(ref_kb, "density")
            density = float(density_v) if density_v is not None else 1.0

            item = GProp_GProps()
            BRepGProp.VolumeProperties_s(topods, item)
            vol_mm3 = item.Mass()
            if mass_override is not None and vol_mm3 > 0:
                # Virtual density: makes total.Add produce exactly the override.
                effective = float(mass_override) * 1000.0 / vol_mm3
            else:
                effective = density
            total.Add(item, effective)
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

    stats_table = (
        f"<tr><th>bbox extent (mm)</th>"
        f"<td>{overall_extent[0]:.2f} × {overall_extent[1]:.2f} × {overall_extent[2]:.2f}</td></tr>"
        f"<tr><th>bbox min</th><td>{fmt3(overall_min)}</td></tr>"
        f"<tr><th>bbox max</th><td>{fmt3(overall_max)}</td></tr>"
        f"{mass_line}"
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

  .panel {{ position: fixed; min-width: 200px; max-width: 520px;
            background: rgba(30,30,30,0.92); border: 1px solid #444;
            border-radius: 4px; max-height: calc(100vh - 24px);
            display: flex; flex-direction: column;
            box-shadow: 0 2px 6px rgba(0,0,0,0.4); }}
  .panel.dragging {{ opacity: 0.85; box-shadow: 0 4px 16px rgba(0,0,0,0.6); }}
  .panel-header {{ display: flex; align-items: center; padding: 4px 8px;
                   background: rgba(255,255,255,0.05);
                   border-bottom: 1px solid #444;
                   border-radius: 4px 4px 0 0;
                   cursor: grab; user-select: none; }}
  .panel.dragging .panel-header {{ cursor: grabbing; }}
  .panel-title {{ flex: 1; font-size: 12px; color: #fff; font-weight: 600; }}
  .panel-collapse {{ background: transparent; border: 1px solid #555;
                     color: #ddd; cursor: pointer; padding: 0 6px;
                     font-size: 12px; font-family: inherit; border-radius: 2px;
                     line-height: 1.2; }}
  .panel-collapse:hover {{ background: rgba(255,255,255,0.1); }}
  .panel-body {{ overflow-y: auto; padding: 6px 10px 10px; }}
  .panel.collapsed .panel-body {{ display: none; }}

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

<div class="panel" data-panel-id="stats" style="top: 12px; right: 12px;">
  <div class="panel-header">
    <span class="panel-title">{asm_kb} — stats</span>
    <button class="panel-collapse" title="collapse">−</button>
  </div>
  <div class="panel-body"><table>{stats_table}</table></div>
</div>

<div class="panel" data-panel-id="instances" style="top: 200px; right: 12px;">
  <div class="panel-header">
    <span class="panel-title">instances ({len(instances)})</span>
    <button class="panel-collapse" title="collapse">−</button>
  </div>
  <div class="panel-body">
    <table>
      <tr><th>name</th><th>ref_kb</th><th>min</th><th>max</th></tr>
      {inst_rows_html}
    </table>
  </div>
</div>

<div class="panel" data-panel-id="joints" style="top: 380px; right: 12px;">
  <div class="panel-header">
    <span class="panel-title">joints ({len(joints)}) — hover dots on model</span>
    <button class="panel-collapse" title="collapse">−</button>
  </div>
  <div class="panel-body">
    <table>
      <tr><th>label</th><th>world (mm)</th></tr>
      {joint_rows_html}
    </table>
  </div>
</div>

<div class="footer">refresh after `mk show` to reload — drag panel headers, click − to collapse</div>

<script>
(function() {{
  // Per-panel position + collapsed state, persisted in localStorage so the
  // user's layout survives `mk show` reruns. Keyed by assembly so different
  // assemblies remember independently.
  const KEY = (id) => `mkcad:{asm_kb}:panel:` + id;

  document.querySelectorAll('.panel').forEach(panel => {{
    const id = panel.dataset.panelId;
    const collapseBtn = panel.querySelector('.panel-collapse');
    const header = panel.querySelector('.panel-header');

    const restore = () => {{
      try {{
        const saved = JSON.parse(localStorage.getItem(KEY(id)) || 'null');
        if (!saved) return;
        if (typeof saved.x === 'number' && typeof saved.y === 'number') {{
          panel.style.left = saved.x + 'px';
          panel.style.top = saved.y + 'px';
          panel.style.right = 'auto';
        }}
        if (saved.collapsed) {{
          panel.classList.add('collapsed');
          collapseBtn.textContent = '+';
        }}
      }} catch (e) {{}}
    }};

    const save = () => {{
      const r = panel.getBoundingClientRect();
      localStorage.setItem(KEY(id), JSON.stringify({{
        x: Math.max(0, r.left), y: Math.max(0, r.top),
        collapsed: panel.classList.contains('collapsed'),
      }}));
    }};

    restore();

    header.addEventListener('pointerdown', e => {{
      if (e.target === collapseBtn) return;
      e.preventDefault();
      header.setPointerCapture(e.pointerId);
      const rect = panel.getBoundingClientRect();
      const dx = e.clientX - rect.left;
      const dy = e.clientY - rect.top;
      panel.classList.add('dragging');
      panel.style.right = 'auto';

      const onMove = ev => {{
        const x = Math.max(0, Math.min(window.innerWidth - 40, ev.clientX - dx));
        const y = Math.max(0, Math.min(window.innerHeight - 30, ev.clientY - dy));
        panel.style.left = x + 'px';
        panel.style.top = y + 'px';
      }};
      const onUp = () => {{
        panel.classList.remove('dragging');
        header.removeEventListener('pointermove', onMove);
        header.removeEventListener('pointerup', onUp);
        save();
      }};
      header.addEventListener('pointermove', onMove);
      header.addEventListener('pointerup', onUp);
    }});

    collapseBtn.addEventListener('click', () => {{
      panel.classList.toggle('collapsed');
      collapseBtn.textContent = panel.classList.contains('collapsed') ? '+' : '−';
      save();
    }});
  }});

  // Convenience: double-click an empty area of the page to reset all panel
  // positions for this assembly.
  document.body.addEventListener('dblclick', e => {{
    if (e.target !== document.body) return;
    document.querySelectorAll('.panel').forEach(panel => {{
      localStorage.removeItem(KEY(panel.dataset.panelId));
    }});
    location.reload();
  }});
}})();
</script>
</body>
</html>
"""
