"""Pure-Python tests for HLR view definitions and 2D projection math.

The actual HLR run + DXF write happen in-container (OCP-bound); host
tests cover the view-direction table, the 3D→2D projection used
during DXF emission, and ezdxf is exercised via a smoke test that
emits an empty drawing.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from mk.hlr import VIEW_DIRECTIONS, project_to_2d


def _almost(a, b, tol=1e-9):
    return abs(a - b) < tol


# ── View direction table ────────────────────────────────────────────────────

class TestViewDirections:
    def test_all_four_views_defined(self):
        assert set(VIEW_DIRECTIONS) == {"top", "front", "right", "iso"}

    def test_each_view_has_unit_vectors(self):
        # iso isn't unit-length intentionally (it's the corner-of-cube),
        # so check top/front/right only.
        for name in ("top", "front", "right"):
            look, up = VIEW_DIRECTIONS[name]
            assert _almost(sum(c * c for c in look), 1.0)
            assert _almost(sum(c * c for c in up), 1.0)

    def test_top_looks_down(self):
        look, up = VIEW_DIRECTIONS["top"]
        assert look == (0.0, 0.0, -1.0)
        assert up == (0.0, 1.0, 0.0)

    def test_front_looks_at_y(self):
        look, up = VIEW_DIRECTIONS["front"]
        assert look == (0.0, -1.0, 0.0)
        assert up == (0.0, 0.0, 1.0)


# ── 3D → 2D projection ──────────────────────────────────────────────────────

class TestProjectTo2D:
    def test_top_view_projects_xy_plane(self):
        # top view: look=(0,0,-1), up=(0,1,0), so right=(1,0,0)
        # → 2D (x, y) = (3D x, 3D y) modulo sign.
        look, up = VIEW_DIRECTIONS["top"]
        x, y = project_to_2d((5.0, 7.0, 99.0), look, up)
        assert _almost(x, 5.0)
        assert _almost(y, 7.0)

    def test_front_view_projects_xz_plane(self):
        # Front view: camera at +Y looking toward -Y, screen up = +Z.
        # Third-angle convention: scene +X appears on the viewer's LEFT
        # (the way you see a part standing in front of it), so a +X point
        # projects to negative screen-x.
        look, up = VIEW_DIRECTIONS["front"]
        x, y = project_to_2d((5.0, 99.0, 3.0), look, up)
        assert _almost(x, -5.0)
        assert _almost(y, 3.0)

    def test_right_view_projects_yz_plane(self):
        # right view: look=(-1,0,0), up=(0,0,1), right=up×look=(0,1,0).
        look, up = VIEW_DIRECTIONS["right"]
        x, y = project_to_2d((99.0, 5.0, 3.0), look, up)
        assert _almost(x, 5.0)
        assert _almost(y, 3.0)

    def test_origin_stays_at_origin(self):
        for name in ("top", "front", "right", "iso"):
            look, up = VIEW_DIRECTIONS[name]
            x, y = project_to_2d((0.0, 0.0, 0.0), look, up)
            assert _almost(x, 0.0)
            assert _almost(y, 0.0)


# ── ezdxf smoke ──────────────────────────────────────────────────────────────

class TestEzdxfSmoke:
    def test_can_build_doc_with_mk_layers(self, tmp_path):
        ezdxf = pytest.importorskip("ezdxf")
        from mk.dxf import LAYER_HIDDEN, LAYER_TITLE, LAYER_VISIBLE, _ensure_layers

        doc = ezdxf.new(dxfversion="R2010", setup=True)
        _ensure_layers(doc)
        assert LAYER_VISIBLE in doc.layers
        assert LAYER_HIDDEN in doc.layers
        assert LAYER_TITLE in doc.layers

        # Roundtrip through the filesystem.
        out = tmp_path / "smoke.dxf"
        doc.saveas(str(out))
        doc2 = ezdxf.readfile(str(out))
        assert LAYER_VISIBLE in doc2.layers
        # Hidden layer should be DASHED.
        assert doc2.layers.get(LAYER_HIDDEN).dxf.linetype == "DASHED"


# ── Bbox-of-view math ───────────────────────────────────────────────────────

class TestViewBBox:
    def test_bbox_width_height(self):
        from mk.dxf import _ViewBBox
        b = _ViewBBox(-10, -5, 20, 25)
        assert b.width == 30
        assert b.height == 30
