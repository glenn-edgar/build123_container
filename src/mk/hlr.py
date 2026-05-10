# SPDX-License-Identifier: MPL-2.0
"""Hidden-line removal (HLR) ortho-view projection — Phase D.1.

Wraps OCC's `HLRBRep_Algo` / `HLRBRep_HLRToShape` to compute the
visible and hidden edge sets of a shape as seen from a given
direction. The output is two `TopoDS_Compound`s containing 3D edges
on the projection plane; the DXF emitter (Phase D.2) walks these and
discretizes each edge to polyline geometry.

Standard view directions (right-handed, mm units, build123d native):

  view   look-direction   up-direction
  ----   --------------   ------------
  top      (0, 0, -1)       (0, +1, 0)   — looking down at the XY plane
  front    (0, -1, 0)       (0, 0, +1)   — looking at the XZ plane from +Y
  right    (-1, 0, 0)       (0, 0, +1)   — looking at the YZ plane from +X
  iso      (-1, -1, -1)     (0, 0, +1)   — corner-of-cube view

Edge classification (HLRBRep_HLRToShape's standard buckets):
  - sharp visible / hidden: the most useful — sharp silhouette edges
  - smooth (Rg1) visible / hidden: tangent edges where surfaces meet
    smoothly. Conventional engineering drawings hide these or render
    thin; we keep them on the same layer as sharp visible for now.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Look-direction / up-direction pairs for each named view.
VIEW_DIRECTIONS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "top":   ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "iso":   ((-1.0, -1.0, -1.0), (0.0, 0.0, 1.0)),
}


@dataclass
class HLRResult:
    """Output of one view's HLR pass.

    ``visible`` and ``hidden`` are TopoDS_Compounds containing the
    projected edges (in 3D — the projection plane is determined by
    ``look_direction``, but OCC returns the result as 3D edges that
    happen to lie on that plane). The DXF emitter projects them to
    2D by dropping the look-axis coordinate.
    """
    visible: object
    hidden: object
    look: tuple[float, float, float]
    up: tuple[float, float, float]


def project_view(shape, view: str) -> HLRResult:
    """Run HLR on ``shape`` for the named view.

    Accepts either a build123d wrapper (uses ``.wrapped``) or a raw
    TopoDS_Shape. Returns visible and hidden edge compounds plus the
    direction vectors used (so the caller can project 3D → 2D).
    """
    if view not in VIEW_DIRECTIONS:
        raise ValueError(
            f"unknown view {view!r}; expected one of {sorted(VIEW_DIRECTIONS)}"
        )
    look, up = VIEW_DIRECTIONS[view]

    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.TopoDS import TopoDS_Shape

    topods = shape if isinstance(shape, TopoDS_Shape) else shape.wrapped

    # Ax2: a coordinate system with main direction = look, X direction
    # derived from `up`. OCC's projector projects onto the plane
    # perpendicular to the main direction.
    ax = gp_Ax2(
        gp_Pnt(0, 0, 0),
        gp_Dir(*look),
        gp_Dir(*up),
    )
    projector = HLRAlgo_Projector(ax)

    algo = HLRBRep_Algo()
    algo.Add(topods)
    algo.Projector(projector)
    algo.Update()
    algo.Hide()

    extract = HLRBRep_HLRToShape(algo)

    # Combine sharp + smooth into single visible/hidden compounds.
    # The two share a "this should be drawn" classification; their
    # OCC-level distinction (sharp = silhouette, smooth = tangent
    # surface meeting) gets folded together for the prototype.
    def _combine(*compounds):
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        result = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(result)
        for c in compounds:
            if c is None or c.IsNull():
                continue
            builder.Add(result, c)
        return result

    visible = _combine(
        _try(extract.VCompound),
        _try(extract.Rg1LineVCompound),
        _try(extract.OutLineVCompound),
    )
    hidden = _combine(
        _try(extract.HCompound),
        _try(extract.Rg1LineHCompound),
        _try(extract.OutLineHCompound),
    )

    return HLRResult(visible=visible, hidden=hidden, look=look, up=up)


def _try(getter):
    """Some HLRBRep_HLRToShape getters raise when the bucket is empty.
    Wrap them so callers can union compounds without try/except per call.
    """
    try:
        return getter()
    except Exception:
        return None


def iter_edges(compound):
    """Yield each TopoDS_Edge in a compound. Skips null edges and
    non-edge sub-shapes. Useful for the DXF emitter that walks the
    visible/hidden compound and emits one DXF entity per edge.
    """
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    explorer = TopExp_Explorer(compound, TopAbs_EDGE)
    while explorer.More():
        yield TopoDS.Edge_s(explorer.Current())
        explorer.Next()


def discretize_edge(edge, n_segments: int = 24) -> list[tuple[float, float, float]]:
    """Sample ``n_segments + 1`` points along an edge in world coords.

    Falls back to (start, end) for degenerate edges. The DXF emitter
    will project these 3D points to 2D by dropping the look-axis
    component.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    try:
        curve = BRepAdaptor_Curve(edge)
    except Exception:
        # Should never happen for well-formed HLR edges, but be defensive.
        return []

    u0 = curve.FirstParameter()
    u1 = curve.LastParameter()
    if not (u0 < u1):
        return []

    points: list[tuple[float, float, float]] = []
    n = max(1, int(n_segments))
    for i in range(n + 1):
        u = u0 + (u1 - u0) * i / n
        try:
            p = curve.Value(u)
            points.append((p.X(), p.Y(), p.Z()))
        except Exception:
            continue
    return points


def project_to_2d(
    point_3d: tuple[float, float, float],
    look: tuple[float, float, float],
    up: tuple[float, float, float],
) -> tuple[float, float]:
    """Project a 3D point to the view's 2D plane.

    Convention: ``look`` is camera-toward-scene (so for a top view,
    look=(0,0,-1)). With right-handed coordinates and screen up = +Y:
    ``right = look × up`` gives the viewer's-right direction. Returns
    ``(x_2d, y_2d)`` in the same units as the input.
    """
    # right = look × up
    right = (
        look[1] * up[2] - look[2] * up[1],
        look[2] * up[0] - look[0] * up[2],
        look[0] * up[1] - look[1] * up[0],
    )
    x = right[0] * point_3d[0] + right[1] * point_3d[1] + right[2] * point_3d[2]
    y = up[0] * point_3d[0] + up[1] * point_3d[1] + up[2] * point_3d[2]
    return x, y
