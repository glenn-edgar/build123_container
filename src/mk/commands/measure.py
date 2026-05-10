# SPDX-License-Identifier: MPL-2.0
"""mk measure <asm-kb>: bounding boxes, joint frames in world coords, distances.

Reports:
- Overall assembly bounding box (X/Y/Z extents in mm).
- Per-instance bounding box in world coords (after mate-solved transforms).
- Joint frames in world coords for every INST.
- Optional --distance <joint_path> <joint_path> for a specific measurement.

Joint paths use the same shape as MATE rows:
``<asm>[.SUB.<sub>...].INST.<inst>.JOINT.<joint>``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any

from mk.db import DEFAULT_DB_PATH, kb_exists, open_db
from mk.geometry import brep_bytes_to_shape
from mk.mate import _parse_joint_path, _read_inst_ref_kb, _read_joint_frame
from mk.transform import apply_location_to_topods, trsf_from_location


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("measure", help="Bounding boxes, joints, distances.")
    p.add_argument("asm_kb", help="assembly KB name, e.g. asm_demo")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument(
        "--distance",
        nargs=2,
        metavar=("JOINT_A", "JOINT_B"),
        help="print Euclidean distance between two joint frames in world coords",
    )
    p.add_argument(
        "--no-joints", action="store_true",
        help="suppress per-joint world-coord listing",
    )
    p.set_defaults(func=run)


def _bbox(topods) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(topods, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return (xmin, ymin, zmin), (xmax, ymax, zmax)


def _fmt_xyz(v) -> str:
    return f"({v[0]:>9.3f}, {v[1]:>9.3f}, {v[2]:>9.3f})"


def _apply_trsf_to_point(trsf, pt: list[float]) -> list[float]:
    """Apply a gp_Trsf to a 3-point. trsf=None → identity."""
    if trsf is None:
        return list(pt)
    from OCP.gp import gp_Pnt

    p = gp_Pnt(float(pt[0]), float(pt[1]), float(pt[2]))
    p.Transform(trsf)
    return [p.X(), p.Y(), p.Z()]


def _apply_trsf_to_vec(trsf, vec: list[float]) -> list[float]:
    """Apply a gp_Trsf's rotation part to a direction vector."""
    if trsf is None:
        return list(vec)
    from OCP.gp import gp_Vec

    v = gp_Vec(float(vec[0]), float(vec[1]), float(vec[2]))
    v.Transform(trsf)
    return [v.X(), v.Y(), v.Z()]


def _world_joint_frame(conn, asm_kb: str, joint_path: str) -> tuple[list[float], list[float]]:
    """Resolve a joint path to (origin_world, zdir_world)."""
    _, inst_path, _inst_name, joint_name = _parse_joint_path(joint_path)
    ref_kb = _read_inst_ref_kb(conn, asm_kb, inst_path)
    origin_local, zdir_local = _read_joint_frame(conn, ref_kb, joint_name)

    inst_row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' AND path = ?",
        (asm_kb, inst_path),
    ).fetchone()
    location = json.loads(inst_row["properties"]).get("location") if inst_row else None
    trsf = trsf_from_location(location)

    return _apply_trsf_to_point(trsf, origin_local), _apply_trsf_to_vec(trsf, zdir_local)


def run(args: argparse.Namespace) -> int:
    conn = open_db(args.db)

    if not kb_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    rows = conn.execute(
        "SELECT path, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (args.asm_kb,),
    ).fetchall()
    if not rows:
        print(f"{args.asm_kb} has no INST rows", file=sys.stderr)
        conn.close()
        return 1

    inst_data: list[dict[str, Any]] = []
    overall_min = [math.inf, math.inf, math.inf]
    overall_max = [-math.inf, -math.inf, -math.inf]

    for r in rows:
        props = json.loads(r["properties"])
        gh = props.get("geom_hash")
        ref_kb = props.get("ref_kb")
        if gh is None or ref_kb is None:
            print(f"  skip {r['path']}: missing geom_hash or ref_kb (run `mk build` first)",
                  file=sys.stderr)
            continue
        blob = conn.execute(
            "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
        ).fetchone()
        if blob is None:
            print(f"  skip {r['path']}: BREP {gh[:12]} not in cache", file=sys.stderr)
            continue

        shape = brep_bytes_to_shape(blob["brep_blob"])
        topods = apply_location_to_topods(shape.wrapped, props.get("location"))
        bmin, bmax = _bbox(topods)

        for i in (0, 1, 2):
            overall_min[i] = min(overall_min[i], bmin[i])
            overall_max[i] = max(overall_max[i], bmax[i])

        inst_data.append({
            "name": r["name"], "ref_kb": ref_kb, "bmin": bmin, "bmax": bmax,
        })

    if not inst_data:
        conn.close()
        print("no buildable instances", file=sys.stderr)
        return 1

    overall_extent = [overall_max[i] - overall_min[i] for i in (0, 1, 2)]

    print(f"== {args.asm_kb} ==")
    print(f"overall bounding box (mm)")
    print(f"  min:    {_fmt_xyz(overall_min)}")
    print(f"  max:    {_fmt_xyz(overall_max)}")
    print(f"  extent: {_fmt_xyz(overall_extent)}  "
          f"=  {overall_extent[0]:.3f} × {overall_extent[1]:.3f} × {overall_extent[2]:.3f} mm")
    print()

    print("per-instance bounding box (world coords, mm)")
    name_w = max(len(d["name"]) for d in inst_data)
    for d in inst_data:
        ext = [d["bmax"][i] - d["bmin"][i] for i in (0, 1, 2)]
        print(f"  {d['name'].ljust(name_w)}  "
              f"min={_fmt_xyz(d['bmin'])}  max={_fmt_xyz(d['bmax'])}  "
              f"extent={ext[0]:.2f}×{ext[1]:.2f}×{ext[2]:.2f}")
    print()

    # Mate-coincidence sanity check. For any well-built assembly every
    # mate's joint_a and joint_b should be at the same world point
    # (rigid: by definition; revolute/prismatic: the pivot is shared
    # with joint_b's origin at DOF=0). Non-zero drift = stale build
    # or override mismatch.
    mate_rows = conn.execute(
        "SELECT name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'MATE' ORDER BY name",
        (args.asm_kb,),
    ).fetchall()
    if mate_rows:
        print("mate coincidence (joint_a vs joint_b world distance)")
        any_warn = False
        name_w = max(len(mr["name"]) for mr in mate_rows)
        for mr in mate_rows:
            mp = json.loads(mr["properties"])
            try:
                oa, _ = _world_joint_frame(conn, args.asm_kb, mp["joint_a"])
                ob, _ = _world_joint_frame(conn, args.asm_kb, mp["joint_b"])
            except (ValueError, KeyError, TypeError) as e:
                print(f"  {mr['name'].ljust(name_w)}  ERR  {e}")
                continue
            d = math.sqrt(sum((oa[i] - ob[i]) ** 2 for i in (0, 1, 2)))
            mate_type = mp.get("mate_type", "rigid")
            status = "OK" if d < 1e-6 else f"WARN distance={d:.4g} mm"
            print(f"  {mr['name'].ljust(name_w)}  ({mate_type:<9})  {status}")
            if d >= 1e-6:
                any_warn = True
        if any_warn:
            print("  ↑ non-zero distance suggests stale build or override mismatch")
        print()

    if not args.no_joints:
        joint_rows = conn.execute(
            """
            SELECT i.name AS inst_name,
                   i.path AS inst_path,
                   json_extract(i.properties, '$.ref_kb') AS ref_kb
            FROM knowledge_base i
            WHERE i.knowledge_base = ? AND i.label = 'INST'
            ORDER BY i.path
            """,
            (args.asm_kb,),
        ).fetchall()

        # First pass: collect every (inst, joint) pair so we can size the
        # label column from the longest "inst.joint" combined string.
        joint_entries: list[tuple[str, str, str]] = []  # (inst_name, joint_name, joint_path)
        for ir in joint_rows:
            j_rows = conn.execute(
                "SELECT name FROM knowledge_base "
                "WHERE knowledge_base = ? AND label = 'JOINT' ORDER BY name",
                (ir["ref_kb"],),
            ).fetchall()
            for jr in j_rows:
                joint_entries.append((
                    ir["inst_name"], jr["name"],
                    f"{ir['inst_path']}.JOINT.{jr['name']}",
                ))

        if joint_entries:
            print("joint frames in world coords")
            label_w = max(len(f"{i}.{j}") for i, j, _ in joint_entries)
            for inst_name, joint_name, joint_path in joint_entries:
                origin_w, zdir_w = _world_joint_frame(conn, args.asm_kb, joint_path)
                label = f"{inst_name}.{joint_name}"
                print(f"  {label.ljust(label_w)}  "
                      f"origin={_fmt_xyz(origin_w)}  z_dir={_fmt_xyz(zdir_w)}")
            print()

    if args.distance:
        a_path, b_path = args.distance
        oa, _ = _world_joint_frame(conn, args.asm_kb, a_path)
        ob, _ = _world_joint_frame(conn, args.asm_kb, b_path)
        d = math.sqrt(sum((oa[i] - ob[i]) ** 2 for i in (0, 1, 2)))
        print(f"distance({a_path}, {b_path}) = {d:.4f} mm")

    conn.close()
    return 0
