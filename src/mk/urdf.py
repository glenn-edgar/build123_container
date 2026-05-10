# SPDX-License-Identifier: MPL-2.0
"""URDF (Unified Robot Description Format) exporter.

Produces ROS-compatible URDF for an assembly: each INST → ``<link>``, each
revolute / prismatic / rigid MATE → ``<joint>`` of type ``revolute`` /
``prismatic`` / ``fixed`` respectively. The output drops directly into
Gazebo, MuJoCo (via the URDF importer), Drake, and MoveIt.

Geometry handling
-----------------
URDF locates each link via joint origins, not baked-in transforms. So we
write one STL per link in part-local coordinates (no INST.location applied)
and reference it from ``<visual>`` and ``<collision>``. The mate-resolved
transforms live in each joint's ``<origin>``.

Inertia handling
----------------
`mk.inertia.link_mass_props_for_inst` computes mass, CoM, and inertia tensor
at the CoM in the link's frame. Density and ``META.mass_g_override`` rules
match ``mk mass``.

Units
-----
URDF is SI: kilograms, metres, kg·m². Meshes are in mm (build123d native),
so the ``<mesh>`` element carries ``scale="0.001 0.001 0.001"``.

Topology
--------
URDF requires a kinematic tree (single root). Each INST is the child of at
most one mate (already enforced by the mate solver's over-constraint check).
If exactly one INST has no parent mate, it's the URDF root. If multiple do,
we synthesize a ``world`` link and connect each free root to it with a
fixed joint.

Naming
------
ltree paths use ``.`` separators, which URDF disallows in link/joint names.
We map ``.`` → ``__`` for emission.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET

from mk.geometry import brep_bytes_to_shape
from mk.mate import _parse_mate_rows, compute_world_transforms


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize(path: str) -> str:
    """ltree path → URDF-safe identifier. URDF disallows '.', '/', etc.
    in link/joint names; '__' is the conventional escape for '.'.
    """
    return path.replace(".", "__")


def _short_link_name(inst_path: str) -> str:
    """Return just the leaf inst name from an ``<asm>.INST.<inst>`` path.

    Falls back to the sanitized full path if the path has SUB segments
    (where the leaf alone wouldn't disambiguate across SUBs).
    """
    if ".SUB." in inst_path:
        return _sanitize(inst_path)
    # Path shape is "<asm>.INST.<leaf>" — split on .INST. for the leaf.
    if ".INST." in inst_path:
        return inst_path.rsplit(".INST.", 1)[-1]
    return _sanitize(inst_path)


def _name_for(inst_path: str, can_shorten: bool) -> str:
    """Pick the link-name spelling based on whether the assembly has SUBs.

    When ``can_shorten`` is True (no SUBs anywhere), use the leaf inst
    name (``bracket``, ``motor``, ``lever``). Otherwise fall back to
    the sanitized full path (``asm__SUB__group__INST__pcb``) to
    preserve disambiguation across SUB scopes.
    """
    return _short_link_name(inst_path) if can_shorten else _sanitize(inst_path)


def rot_to_rpy(R: list[list[float]]) -> tuple[float, float, float]:
    """3x3 rotation → URDF roll-pitch-yaw (radians), fixed-axis XYZ.

    Convention: R = Rz(yaw) @ Ry(pitch) @ Rx(roll). Gimbal lock at
    pitch=±pi/2 yields yaw=0; the remaining angle goes into roll.
    """
    # Clamp to handle floating-point drift outside [-1, 1].
    sp = max(-1.0, min(1.0, -R[2][0]))
    pitch = math.asin(sp)
    cp = math.cos(pitch)
    if abs(cp) < 1e-9:
        # Gimbal lock: roll and yaw share a degree of freedom; pick yaw=0.
        roll = math.atan2(R[0][1], R[1][1])
        if sp < 0:
            roll = -roll
        yaw = 0.0
    else:
        roll = math.atan2(R[2][1], R[2][2])
        yaw = math.atan2(R[1][0], R[0][0])
    return roll, pitch, yaw


def _compose_inv_a_times_b(
    a_rot: list[list[float]], a_trans: list[float],
    b_rot: list[list[float]], b_trans: list[float],
) -> tuple[list[list[float]], list[float]]:
    """Return inverse(A) @ B for (rotation, translation) pairs.

    Inverse of (R, t) is (R^T, -R^T @ t). Then (R^T, -R^T t_a) @ (R_b, t_b)
    = (R^T R_b, R^T (t_b - t_a)).
    """
    rt = [[a_rot[j][i] for j in range(3)] for i in range(3)]  # transpose
    rot = [
        [sum(rt[i][k] * b_rot[k][j] for k in range(3)) for j in range(3)]
        for i in range(3)
    ]
    delta = [b_trans[k] - a_trans[k] for k in range(3)]
    trans = [sum(rt[i][k] * delta[k] for k in range(3)) for i in range(3)]
    return rot, trans


# Below this magnitude, treat a float as numerical-integration zero. Cleans
# up the 1e-19 / 1e-24 garbage that OCP's volume properties produce for
# off-diagonal inertia entries and CoM components of symmetric shapes.
_FLOAT_NOISE_THRESHOLD = 1e-12


def _clean(v: float) -> float:
    """Threshold float-math noise so URDF output reads cleanly."""
    return 0.0 if abs(v) < _FLOAT_NOISE_THRESHOLD else float(v)


def _f(v: float) -> str:
    """URDF numeric attribute formatter: threshold noise, then ``%.9g``."""
    return f"{_clean(v):.9g}"


def _xyz_str(xyz: list[float] | tuple[float, ...]) -> str:
    return f"{_f(xyz[0])} {_f(xyz[1])} {_f(xyz[2])}"


# ── Tree topology ────────────────────────────────────────────────────────────

def determine_roots(
    inst_paths: list[str], parsed_mates: list[dict],
) -> list[str]:
    """Insts that are never a child in any mate. URDF requires one root;
    multiple roots get joined to a synthetic `world` link.
    """
    child_paths = {m["a_path"] for m in parsed_mates}
    return [p for p in inst_paths if p not in child_paths]


# ── XML emission ─────────────────────────────────────────────────────────────

def _link_element(
    inst_path: str,
    mass_kg: float, com_m: tuple[float, float, float],
    inertia_kg_m2: list[list[float]],
    mesh_filename: str,
    rgba: tuple[float, float, float, float] | None,
    link_name: str | None = None,
) -> ET.Element:
    name = link_name if link_name is not None else _sanitize(inst_path)
    link = ET.Element("link", name=name)

    inertial = ET.SubElement(link, "inertial")
    ET.SubElement(inertial, "origin", xyz=_xyz_str(com_m), rpy="0 0 0")
    ET.SubElement(inertial, "mass", value=_f(mass_kg))
    ET.SubElement(
        inertial, "inertia",
        ixx=_f(inertia_kg_m2[0][0]),
        ixy=_f(inertia_kg_m2[0][1]),
        ixz=_f(inertia_kg_m2[0][2]),
        iyy=_f(inertia_kg_m2[1][1]),
        iyz=_f(inertia_kg_m2[1][2]),
        izz=_f(inertia_kg_m2[2][2]),
    )

    for tag in ("visual", "collision"):
        vis = ET.SubElement(link, tag)
        ET.SubElement(vis, "origin", xyz="0 0 0", rpy="0 0 0")
        geom = ET.SubElement(vis, "geometry")
        # STL exported in mm; URDF expects metres. scale converts.
        ET.SubElement(
            geom, "mesh",
            filename=mesh_filename,
            scale="0.001 0.001 0.001",
        )
        if tag == "visual" and rgba is not None:
            mat = ET.SubElement(vis, "material", name=f"{name}__mat")
            ET.SubElement(mat, "color", rgba=_xyz_str(rgba[:3]) + f" {rgba[3]:.3g}")
    return link


def _joint_element(
    mate: dict,
    origin_xyz_m: list[float], origin_rpy: tuple[float, float, float],
    *,
    parent_link: str | None = None,
    child_link: str | None = None,
) -> ET.Element:
    name = _sanitize(mate["name"])
    parent = parent_link if parent_link is not None else _sanitize(mate["b_path"])
    child = child_link if child_link is not None else _sanitize(mate["a_path"])

    mate_type = mate["mate_type"]
    if mate_type == "rigid":
        urdf_type = "fixed"
    elif mate_type == "revolute":
        # No limits → URDF "continuous". Bounded → URDF "revolute".
        urdf_type = "continuous" if not _has_limits(mate) else "revolute"
    elif mate_type == "prismatic":
        urdf_type = "prismatic"  # URDF requires bounded; we emit limit even if None
    else:
        raise ValueError(f"unsupported mate_type: {mate_type!r}")

    joint = ET.Element("joint", name=name, type=urdf_type)
    ET.SubElement(joint, "parent", link=parent)
    ET.SubElement(joint, "child", link=child)
    ET.SubElement(
        joint, "origin",
        xyz=_xyz_str(origin_xyz_m),
        rpy=_xyz_str(origin_rpy),
    )

    if mate_type in ("revolute", "prismatic"):
        axis = mate["axis"]
        n = math.sqrt(sum(c * c for c in axis))
        unit_axis = [c / n for c in axis] if n > 0 else [0.0, 0.0, 1.0]
        ET.SubElement(joint, "axis", xyz=_xyz_str(unit_axis))

        # URDF wants radians for revolute, metres for prismatic.
        limits = mate.get("limits") or [None, None]
        lo, hi = limits
        if mate_type == "revolute":
            lo = math.radians(lo) if lo is not None else None
            hi = math.radians(hi) if hi is not None else None
        else:
            lo = lo / 1000.0 if lo is not None else None
            hi = hi / 1000.0 if hi is not None else None

        # URDF's <limit> requires effort + velocity. We don't model these
        # yet (Phase B.3 typed META is where torque/speed limits land); use
        # generous placeholders that won't constrain typical sim runs.
        limit_attrs = {"effort": "100", "velocity": "1"}
        if lo is not None:
            limit_attrs["lower"] = _f(lo)
        if hi is not None:
            limit_attrs["upper"] = _f(hi)
        if urdf_type != "continuous":
            ET.SubElement(joint, "limit", **limit_attrs)

    return joint


def _has_limits(mate: dict) -> bool:
    lims = mate.get("limits")
    return bool(lims) and any(x is not None for x in lims)


# ── Material colour ──────────────────────────────────────────────────────────

def _read_color_rgba(conn: sqlite3.Connection, part_kb: str) -> tuple[float, float, float, float] | None:
    """Read META.color (hex string) and convert to RGBA floats. None if absent."""
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'META' AND name = 'color'",
        (part_kb,),
    ).fetchone()
    if row is None:
        return None
    raw = json.loads(row["properties"]).get("value")
    if not isinstance(raw, str) or not raw.startswith("#") or len(raw) != 7:
        return None
    try:
        r = int(raw[1:3], 16) / 255.0
        g = int(raw[3:5], 16) / 255.0
        b = int(raw[5:7], 16) / 255.0
    except ValueError:
        return None
    return r, g, b, 1.0


# ── Mesh export ──────────────────────────────────────────────────────────────

def export_link_mesh(conn: sqlite3.Connection, geom_hash: str, out_path: Path) -> None:
    """Write the part's part-local geometry to STL at `out_path`."""
    blob_row = conn.execute(
        "SELECT brep_blob FROM geometry WHERE hash = ?", (geom_hash,)
    ).fetchone()
    if blob_row is None:
        raise RuntimeError(f"geometry hash {geom_hash[:12]} missing from cache")

    from build123d import export_stl
    shape = brep_bytes_to_shape(blob_row["brep_blob"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    export_stl(shape, str(out_path))


# ── Builder ──────────────────────────────────────────────────────────────────

def build_urdf(
    conn: sqlite3.Connection,
    asm_kb: str,
    outdir: Path,
    *,
    package_name: str | None = None,
) -> Path:
    """Emit URDF + per-link STL meshes under ``outdir``. Returns URDF path.

    File layout:
        outdir/
            <asm_kb>.urdf
            meshes/
                <link_name>.stl   (one per INST, part-local coordinates)

    Mesh references use ``package://<package_name>/meshes/<name>.stl``
    (defaults to ``package_name=asm_kb``). Most ROS-aware tools resolve
    these from the URDF's directory.
    """
    from mk.inertia import link_mass_props_for_inst

    package_name = package_name or asm_kb

    inst_rows = conn.execute(
        "SELECT path, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'INST' ORDER BY path",
        (asm_kb,),
    ).fetchall()
    if not inst_rows:
        raise RuntimeError(f"no INST rows in {asm_kb!r}")

    inst_by_path = {r["path"]: r for r in inst_rows}
    inst_paths = list(inst_by_path)

    # Flat assemblies get short leaf names (`bracket`, `motor`, `lever`);
    # SUB-nested ones keep the disambiguating full sanitized path.
    can_shorten = not any(".SUB." in p for p in inst_paths)
    name_for = lambda p: _name_for(p, can_shorten)

    parsed_mates = _parse_mate_rows(conn, asm_kb)
    # Baseline at DOF=0 — URDF joints define the home pose.
    world_T = compute_world_transforms(
        conn, asm_kb,
        state_overrides={m["name"]: 0.0 for m in parsed_mates},
        parsed=parsed_mates,
    )

    roots = determine_roots(inst_paths, parsed_mates)
    if not roots:
        # All insts are children of some mate — would mean a cycle, but
        # _topo_sort_mates already errors on cycles. Defensive guard.
        raise RuntimeError(
            f"{asm_kb}: no root link found (every INST is a mate child). "
            "Check for circular mates."
        )

    robot = ET.Element("robot", name=asm_kb)

    # If multiple roots: synthesize a `world` link and fixed-joint each root to it.
    multi_root = len(roots) > 1
    if multi_root:
        ET.SubElement(robot, "link", name="world")

    # Emit links.
    outdir = Path(outdir)
    mesh_dir = outdir / "meshes"
    # Clear stale STLs from prior runs so name-shortening or removed
    # parts don't leave orphan files. Cheap (handful of files).
    if mesh_dir.exists():
        for old in mesh_dir.glob("*.stl"):
            old.unlink()
    for row in inst_rows:
        props = json.loads(row["properties"])
        gh = props.get("geom_hash")
        ref_kb = props.get("ref_kb")
        if not gh or not ref_kb:
            raise RuntimeError(
                f"{row['path']}: missing geom_hash or ref_kb "
                f"(run `mk build {asm_kb}` first)"
            )

        link_name = name_for(row["path"])
        stl_path = mesh_dir / f"{link_name}.stl"
        export_link_mesh(conn, gh, stl_path)

        shape = brep_bytes_to_shape(
            conn.execute(
                "SELECT brep_blob FROM geometry WHERE hash = ?", (gh,)
            ).fetchone()["brep_blob"]
        )
        props_mass = link_mass_props_for_inst(conn, shape.wrapped, ref_kb)
        rgba = _read_color_rgba(conn, ref_kb)
        mesh_ref = f"package://{package_name}/meshes/{link_name}.stl"
        robot.append(_link_element(
            row["path"],
            props_mass.mass_kg, props_mass.com_m, props_mass.inertia_kg_m2,
            mesh_ref, rgba,
            link_name=link_name,
        ))

    # Fixed joints from `world` to each free root, if synthesized.
    if multi_root:
        for root_path in roots:
            root_rot, root_trans = world_T[root_path]
            origin_xyz_m = [c / 1000.0 for c in root_trans]
            origin_rpy = rot_to_rpy(root_rot)
            root_name = name_for(root_path)
            j = ET.Element(
                "joint",
                name=f"world__to__{root_name}",
                type="fixed",
            )
            ET.SubElement(j, "parent", link="world")
            ET.SubElement(j, "child", link=root_name)
            ET.SubElement(
                j, "origin",
                xyz=_xyz_str(origin_xyz_m), rpy=_xyz_str(origin_rpy),
            )
            robot.append(j)

    # Emit one URDF joint per MATE.
    for m in parsed_mates:
        parent_rot, parent_trans = world_T[m["b_path"]]
        child_rot, child_trans = world_T[m["a_path"]]
        rel_rot, rel_trans = _compose_inv_a_times_b(
            parent_rot, parent_trans, child_rot, child_trans,
        )
        origin_xyz_m = [c / 1000.0 for c in rel_trans]
        origin_rpy = rot_to_rpy(rel_rot)
        robot.append(_joint_element(
            m, origin_xyz_m, origin_rpy,
            parent_link=name_for(m["b_path"]),
            child_link=name_for(m["a_path"]),
        ))

    ET.indent(robot, space="  ")
    urdf_path = outdir / f"{asm_kb}.urdf"
    urdf_path.parent.mkdir(parents=True, exist_ok=True)
    urdf_path.write_bytes(
        b'<?xml version="1.0" ?>\n' + ET.tostring(robot, encoding="utf-8")
    )
    return urdf_path
