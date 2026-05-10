# v2 plan

Four phases. Sequenced so each phase unblocks the next without leaving
half-built dependencies behind. Total estimate ~5–6 weeks of focused work.

This document is the v2 commitment; updates land here, not in `continue.md`
§11 (which records the original rev-2 deferrals).

## Phase A — close v1.x gaps ✅ (done 2026-05-10)

Small fixes that finished the v1 prototype's rough edges. Each unblocks more
ambitious work later.

| Item | Status | Notes |
|---|---|---|
| SUB-nested mate paths parse correctly | ✅ | `JOINT_PATH_RE` now matches `<asm>[.SUB.<s>]*.INST.<i>.JOINT.<j>`. INST lookups use full path (leaf names collide across SUB scopes). `nested_asm.py` fixture builds end-to-end. |
| Topo-sort mates instead of name-prefix discipline | ✅ | Kahn's algorithm over inst-dependency DAG. Cycles + over-constraints raise ValueError before any DB write. Naming discipline no longer required; verified via `topo_chain.py` fixture with scrambled names. |
| `META.mass_g_override` | ✅ | When present, supersedes volume×density. Inertia stays consistent via virtual-density factor. N20 motor in `asm_window_test` now reports 10 g (was 43 g). |
| Multi-assembly viewer | ✅ | `mk show <asm>` writes to `outputs/<asm>/`. Top-level `outputs/index.html` lists all assemblies. Browser URL: `/<asm>/`. |
| `mk part rm <kb>` | ✅ | Default = dry-run with row count + warning if any other assembly's INST still references the part. `--force` actually deletes. |
| pytest harness | ✅ | `pyproject.toml` has `[project.optional-dependencies] dev = ["pytest>=7"]` + `[tool.pytest.ini_options]`. `tests/conftest.py` skips OCP-needing tests on host. 26 tests in `test_imports.py` + `test_mate.py` (parse, matrix math, topo sort) — all passing on host via `.venv/bin/pytest`. |

**Phase A definition of done met.** Remaining v1.x items in `continue.md`
§9 (STEP geom_hash determinism, color-rendering subtleties documented but
acted-on, mate cycle detection) are either resolved or out-of-scope for v2.

## Phase B — simulation + actuation (~2 weeks)

The differentiator. mk-cad's database-backed approach starts paying off when
the same KB rows that produce geometry also drive software simulation.

### B.1 — Revolute and prismatic mate types (~3 days)

Spec the constraint in `MATE.properties`:

```python
{
  "mate_type": "revolute",
  "joint_a": "asm.INST.bolt.JOINT.head",
  "joint_b": "asm.INST.bracket.JOINT.hole",
  "axis": [0, 1, 0],            # rotation axis in joint_a's local frame
  "limits": [-180.0, 180.0],    # degrees; null = unlimited
  "default": 0.0                # current angle for static render
}
```

Same shape for `prismatic`, with `axis` interpreted as translation direction
and `limits` in mm.

Mate solver pre-applies `default` (or `current` from a state file) to compute
the world transform. `mk build` and `mk show` render the assembly at that
state. Animation (B.2) sweeps the value over time.

### B.2 — Live animation in viewer (~3 days)

Two pieces:

1. **Joint state injection.** A small file `outputs/<asm>.state.json` carries
   `{"joint_<n>": angle_deg}`. `mk show` reads it; mate solver applies these
   as overrides; emitted glTF reflects the state.
2. **Browser-side animation.** `mk show --animate` emits a glTF with
   per-revolute-joint nodes, plus a JS shim that polls
   `<asm>.state.json` (or a WebSocket) and updates node transforms in the
   `<model-viewer>` scene without a page reload.

Controller-under-test writes a state file or pushes to a small relay; the
viewer shows the controller-driven motion live.

### B.3 — Typed META schema (~2 days)

Replace free-form `META.<key>` rows with a typed schema. Group keys by
namespace prefix:

```
META.electrical.voltage_nominal_v = 12.0
META.electrical.resistance_ohm   = 5.0
META.mech.gear_ratio             = 100.0
META.mech.no_load_rpm            = 16
META.encoder.cpr_pre_gear        = 7
META.encoder.type                = "magnetic_quadrature"
```

`mk part show` renders these as a structured tree. A new `mk part export
<kb> --json` emits the part's sim contract for consumption by controller
code.

Backward-compatible: existing flat META rows continue to work; the schema
is opt-in via dotted-key naming.

### B.4 — URDF export (~3 days)

`mk export <asm> urdf` produces a URDF file consumable by ROS Gazebo /
MoveIt / MuJoCo / drake. Requires:

- Each `INST` becomes a `<link>` with mass + inertia from `mk mass`
- Each `MATE` of type revolute/prismatic becomes a `<joint>` with axis and
  limits
- Rigid mates collapse into static link-to-link transforms
- Mesh exports per link (STL or glTF) referenced from the URDF

This is what plugs the test rig into existing simulation ecosystems.

## Phase C — layers (~1 week)

Per the design sketch in [v2_layers.md](v2_layers.md) — implementation now
in scope.

### C.1 — LAYER sentinel + tagging (~2 days)

- New label `LAYER` in `knowledge_base`
- `properties.layer = "fasteners"` field on `INST` or `SUB` rows
- `LAYER.<name>` rows store `{visible: bool, color: "#hex", description: "..."}`
- Inheritance: SUB tags propagate to descendants unless overridden
- Auto-create `LAYER` row on first reference (with `visible: true` default)

### C.2 — CLI surface (~1 day)

```
mk layer ls <asm>
mk layer set <asm> <name> on|off
mk layer all <asm> on|off
mk layer color <asm> <name> #hex
```

### C.3 — Per-command policy (~2 days)

Implement the visibility-filter table from `docs/v2_layers.md`:

| Command | Hidden parts |
|---|---|
| `mk show`, `mk export gltf` | excluded |
| `mk export step` | included with XCAF layer metadata |
| `mk export dxf` (Phase D) | included; mapped to DXF layers |
| `mk mass`, `mk bom` | included by default; `--respect-layers` flag for "what user sees weighs" |
| `mk build` | always all parts |

### C.4 — STEP roundtrip (~1 day)

Use OCC's `XCAFDoc_LayerTool` to attach layer assignments during STEP
export. Verify import-side preservation via FreeCAD or similar.

## Phase D — engineering drawings export (~1.5 weeks)

`mk export <asm> dxf` produces orthographic engineering drawings as DXF.
Downstream CAD tools (FreeCAD TechDraw, AutoCAD, LibreCAD, etc.) consume
them; users can dimension/annotate there.

### D.1 — HLR projection pipeline (~3 days)

Use OpenCascade's `HLRBRep_Algo` (or the polygonal `HLRBRep_PolyAlgo`):

1. Place the assembly's compound at world origin
2. Define a viewing direction (top: +Y down, front: +Z back, right: +X
   left, iso: vector from corner)
3. Run HLR — produces visible and hidden edge sets
4. Convert to build123d edges
5. Project onto a 2D plane perpendicular to the view direction

Return a `Sketch` per view containing visible edges (thick lines) and
hidden edges (dashed).

### D.2 — DXF export with view layout (~3 days)

`mk export <asm> dxf` emits a single DXF with:

- Top, front, right, iso views in standard third-angle layout
- Visible edges on `MK_VISIBLE` DXF layer (continuous, thick)
- Hidden edges on `MK_HIDDEN` DXF layer (dashed, thin)
- Layer assignments from Phase C carried through (each mk-cad layer →
  matching DXF layer)
- A simple title block (templated; reads `META.part_number`,
  `META.vendor`, project description)

### D.3 — PDF wrap-up (~3 days, optional)

Use `ezdxf.addons.drawing` (renders DXF to matplotlib) to produce a PDF.
Convenient for review/sharing. Optional — drop if scope tightens.

### D.4 — `mk export <asm> pdf` (~2 days, optional)

Direct PDF export bypassing DXF. Uses build123d's `ExportSVG` plus
`reportlab` or `svglib` for assembly. Skip unless DXF→PDF (D.3) doesn't
work cleanly.

## Out of scope for v2

Carried forward to v3 (or never):

- FEA pipeline (gmsh + CalculiX)
- Postgres adapter (single-user prototype is fine)
- Builder sandbox (no multi-user yet)
- DB → manifest codegen (would help migrations; not blocking)
- Hash cascade caching (depends on STEP-determinism; v3)
- Diff-based apply (depends on hash cascade)
- Portable surface syntax (S-expression / YAML emitter)
- View pipeline beyond drawings (sectioning, exploded views, sheet
  composition) — Phase D delivers ortho drawings; richer view authoring is
  a v3 concern

## Sequencing note

Phases A → B → C → D depend in that order:

- Phase B's URDF export uses Phase A's mass override and mate-solver
  improvements
- Phase D's drawing export uses Phase C's layer system to drive DXF
  layers
- All phases use Phase A's pytest harness for regression coverage

Phase A could happen in parallel with starting Phase B (the gaps don't
block animation work directly), but the simpler plan is to finish A first.

## What would change v2's shape

If during Phase B we discover that controller-test consumers want more than
a state-file dump (e.g., real-time bidirectional MQTT, ROS topics), the
animation interface would expand. Park that conversation for after Phase
B's MVP lands.

If Phase D users want auto-dimensions, that's its own project — needs
constraint extraction from the geometry, sensible default placement, and
typically interactive editing. Not in v2.0.

If multi-user/multi-machine becomes a real ask mid-v2, Theme 3 (Postgres,
sandboxing) jumps the queue. Document the trigger; don't pre-build.
