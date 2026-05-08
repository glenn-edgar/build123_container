# SPDX-License-Identifier: MPL-2.0
"""Shared geometry transform helpers.

`location` JSON shape on INST rows:
    {"loc": [x, y, z],            # translation (mm); optional, default zero
     "rot": [[r11,r12,r13],       # 3x3 rotation; optional, default identity
             [r21,r22,r23],
             [r31,r32,r33]]}

Pre-Phase-6 manifests only set `loc`. The rigid mate solver writes both keys.
"""
from __future__ import annotations

from typing import Any


def trsf_from_location(location: dict[str, Any] | None):
    """Build an OCC gp_Trsf. Returns None when location yields the identity."""
    if not location:
        return None
    loc = location.get("loc") or [0.0, 0.0, 0.0]
    rot = location.get("rot")
    if rot is None and not any(loc):
        return None

    from OCP.gp import gp_Trsf, gp_Vec

    trsf = gp_Trsf()
    if rot is not None:
        trsf.SetValues(
            rot[0][0], rot[0][1], rot[0][2], float(loc[0]),
            rot[1][0], rot[1][1], rot[1][2], float(loc[1]),
            rot[2][0], rot[2][1], rot[2][2], float(loc[2]),
        )
    else:
        trsf.SetTranslation(gp_Vec(float(loc[0]), float(loc[1]), float(loc[2])))
    return trsf


def apply_location_to_topods(topods, location: dict[str, Any] | None):
    """Return a new TopoDS_Shape with the location applied (or original if identity)."""
    trsf = trsf_from_location(location)
    if trsf is None:
        return topods
    from OCP.TopLoc import TopLoc_Location

    return topods.Moved(TopLoc_Location(trsf))


def build123d_location(location: dict[str, Any] | None):
    """Return a build123d Location, or None if identity."""
    trsf = trsf_from_location(location)
    if trsf is None:
        return None
    from build123d import Location

    return Location(trsf)
