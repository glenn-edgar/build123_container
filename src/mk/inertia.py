# SPDX-License-Identifier: MPL-2.0
"""Per-link mass properties: mass, CoM (link-local), inertia tensor at CoM.

Used by `mk export <asm> urdf` to populate each URDF `<inertial>` block.
The tensor is expressed in the link's own frame, with the reference point
translated to the centre of mass — that's the convention URDF expects.

Density rules mirror `mk mass`:
- `META.density.value` (g/cm^3) on the part KB, default 1.0
- `META.mass_g_override.value` (grams) overrides the volume*density product
  and scales the inertia tensor proportionally (uniform-density approximation).

The shape passed in must be in **link-local coordinates** (no `INST.location`
applied) — URDF places links via joint origins, not baked-in transforms.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass
class LinkMassProps:
    mass_kg: float
    com_m: tuple[float, float, float]
    # 3x3 inertia tensor at CoM in link frame, units kg*m^2.
    inertia_kg_m2: list[list[float]]


def _read_density(conn: sqlite3.Connection, part_kb: str) -> float:
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'META' AND name = 'density'",
        (part_kb,),
    ).fetchone()
    if row is None:
        return 1.0
    val = json.loads(row["properties"]).get("value")
    return float(val) if val is not None else 1.0


def _read_mass_override(conn: sqlite3.Connection, part_kb: str) -> float | None:
    row = conn.execute(
        "SELECT properties FROM knowledge_base "
        "WHERE knowledge_base = ? AND label = 'META' AND name = 'mass_g_override'",
        (part_kb,),
    ).fetchone()
    if row is None:
        return None
    val = json.loads(row["properties"]).get("value")
    return float(val) if val is not None else None


def compute_link_mass_props(topods_shape, density_g_cm3: float,
                            mass_g_override: float | None) -> LinkMassProps:
    """Compute mass, CoM, and inertia tensor at CoM for a part-local shape.

    Two-pass GProps:
    1. First pass at the global origin → volume + CoM in part-local mm.
    2. Second pass with reference point at the CoM → inertia at CoM
       (mm^5; we scale by density to get g*mm^2, then to kg*m^2).

    URDF wants SI (kg, m, kg*m^2), so all outputs are converted.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.gp import gp_Pnt

    g1 = GProp_GProps()
    BRepGProp.VolumeProperties_s(topods_shape, g1)
    volume_mm3 = g1.Mass()  # `Mass()` of VolumeProperties returns volume
    com = g1.CentreOfMass()
    cx, cy, cz = com.X(), com.Y(), com.Z()

    if mass_g_override is not None and volume_mm3 > 0:
        # Same virtual-density factor that mk mass uses, so inertia scales
        # consistently. Factor units: (g/cm^3) chosen so that
        # volume_mm3 * factor / 1000 == mass_g_override.
        density_g_cm3 = mass_g_override * 1000.0 / volume_mm3
        mass_g = mass_g_override
    else:
        mass_g = volume_mm3 * density_g_cm3 / 1000.0

    g2 = GProp_GProps(gp_Pnt(cx, cy, cz))
    BRepGProp.VolumeProperties_s(topods_shape, g2)
    I_mm5 = g2.MatrixOfInertia()  # gp_Mat; volume-weighted inertia at CoM

    # I[g*mm^2] = I[mm^5] * density[g/cm^3] / 1000 (cm^3 = 1000 mm^3)
    # I[kg*m^2] = I[g*mm^2] * 1e-9
    # combined factor: density / 1000 * 1e-9 = density * 1e-12
    factor = density_g_cm3 * 1e-12
    inertia = [
        [I_mm5.Value(i, j) * factor for j in (1, 2, 3)]
        for i in (1, 2, 3)
    ]

    return LinkMassProps(
        mass_kg=mass_g / 1000.0,
        com_m=(cx / 1000.0, cy / 1000.0, cz / 1000.0),
        inertia_kg_m2=inertia,
    )


def link_mass_props_for_inst(conn: sqlite3.Connection, topods_shape, ref_kb: str) -> LinkMassProps:
    """Convenience wrapper: pull density / override from the part's META rows."""
    density = _read_density(conn, ref_kb)
    override = _read_mass_override(conn, ref_kb)
    return compute_link_mass_props(topods_shape, density, override)
