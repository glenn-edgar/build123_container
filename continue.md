# continue.md — `<project>`: build123d + ltree CAD prototype (rev 3)

This is **revision 3** of the handoff spec. It supersedes rev 2 only for
**status, definition of done, and next steps**. The architectural decisions in
rev 2 §2 are *locked* and remain authoritative — they're carried forward
verbatim in §2 below. Working history (what landed when) lives in
`HISTORY.md`. v2 design sketches accumulate under `docs/`.

## 0. Where we are

**v1 baselined** 2026-05-09. **Phase A complete; Phase B essentially done
(3 of 4 sub-phases shipped)** as of 2026-05-10.

| Phase | Status | What landed |
|---|---|---|
| v1 | ✅ | All six rev-2 phases. `asm_window_test` is the working evaluation rig. |
| Phase A — v1.x gaps | ✅ (6/6) | SUB-mate paths; topo-sort solver; `META.mass_g_override`; multi-asm viewer (`outputs/<asm>/`); `mk part rm`; pytest harness. |
| Phase B.1 — revolute/prismatic mates | ✅ | `mate(... mate_type="revolute", axis=, limits=, default=)`. Pure-Python Rodrigues math, host-tested. `tests/fixtures/hinge_demo.py` exercises it. |
| Phase B.2.a — state-injection at build time | ✅ | `mk build` reads `outputs/<asm>/state.json` (or `--state <path>`). Override + clamping working. |
| Phase B.2.b — live animation in viewer | ⏳ deferred | needs `<model-viewer>` → three.js swap; ~2–3 days. |
| Phase B.3 — typed META schema | ✅ | Dotted META keys (`electrical.voltage_nominal_v`, `mech.gear_ratio`, …) group into namespaces under `meta` in the new `mk part export <kb>` JSON output. Flat keys (density, color, mass_g_override, _TODO_*) stay top-level. Backward-compatible — manifest API unchanged, `mk part show` keeps its row view. window_test motor migrated to the typed schema as a worked example. |
| Phase B.4 — URDF export | ✅ | `mk export <asm> urdf` writes URDF + per-link STL in `outputs/<asm>/`. Per-link mass/CoM/inertia tensor (kg·m² at CoM) via OCP GProps. Revolute / prismatic / rigid mates → URDF `revolute` / `continuous` / `prismatic` / `fixed` joints. Multi-root → synthesized `world` link. Smoke-tested on `asm_hinge` (revolute) and `asm_window_test` (4 fixed joints). |
| Phase C.1+C.2 — layer data model + CLI | ✅ | `LAYER.<name>` sentinel + `properties.layer` tags on INST/SUB. SUB inheritance with multi-tag union (`leaf_set ∪ ancestor_set`). Auto-create on first reference; state preserved across `mk apply` re-runs. `mk layer ls/set/all/color` CLI. Bool visibility (tri-state deferred to v3 per design doc). |
| Phase C.3 — per-command visibility filter | ✅ | `mk show` and `mk export stl` filter out hidden insts; `mk export step/brep/urdf` and `mk build` always include all; `mk mass`/`mk bom` default-include with `--respect-layers` flag for opt-in filtering. Filtered commands log the skip count. |
| Phase C.4 — STEP XCAF roundtrip | ⚠️ partial | `mk export step` now uses STEPCAFControl_Writer + XCAF doc model. **Colors round-trip cleanly** (META.color → STEP COLOUR_RGB → FreeCAD/etc.). **Layers are best-effort**: OCC 7.8.1.1's writer emits at most one shape per `PRESENTATION_LAYER_ASSIGNMENT` and drops multi-tag shapes entirely. Documented in `src/mk/step_xcaf.py`. |
| Phase D.1+D.2 — engineering drawings → DXF | ✅ | `mk export <asm> dxf` writes a 4-view (top/front/right/iso) third-angle drawing via HLR projection. Visible edges on `MK_VISIBLE`, hidden on `MK_HIDDEN` (DASHED). Title block from META.part_number/vendor + assembly description. Edges discretized as LWPOLYLINEs (~24 segs/edge); exact-line/arc preservation is a polish step. |
| Phase D.3+D.4 — PDF wrap | ⏳ optional | `ezdxf.addons.drawing` → PDF (D.3) or direct SVG-based PDF (D.4). The v2_plan calls these optional; `dxf2pdf` externally or FreeCAD TechDraw fills the gap until needed. |

`docs/v2_plan.md` is the long-form v2 commitment. `HISTORY.md` is the
phase-by-phase log.

## 0a. Pick-up point for next session

**Read this first.** v2 plan is effectively complete. All four phases
(A, B, C, D) have shipped their must-haves; the remaining items are
optional or low-priority. Three candidates if you want to keep
extending the prototype:

1. **Phase B.2.b — live JS animation** (~2–3 days) **[my pick if any]**.
   Last unbuilt B sub-phase. Replaces `<model-viewer>` with direct
   three.js so the scene updates from `state.json` polling without
   rebuilding. B.2.a's format and override logic are already in
   place — pure viewer rewrite. Most concrete leverage of any open
   item: makes the controller-in-the-loop story feel alive.

2. **Phase D.3+D.4 — PDF wrap** (~3 days, optional in v2 plan).
   `ezdxf.addons.drawing` renders DXF to matplotlib → PDF. Drop-in
   if it works cleanly; the DXF is the real engineering artifact
   anyway and FreeCAD TechDraw / external `dxf2pdf` already fill the
   gap.

3. **DXF polish** — preserve exact lines + arcs instead of polyline
   discretization. Current emitter writes every edge as a 24-segment
   LWPOLYLINE; downstream tools handle that fine but a true LINE
   entity for straight edges and ARC entity for circles would
   produce cleaner geometry. ~1 day.

4. **Evaluation phase** (per `continue.md` §4). Build a small library
   of real parts, exercise the API, and write down friction. v3
   priorities come from this list. The §4 list above hasn't been
   exercised since v1 baseline — the cycle since has been pure
   feature work.

My pick: **#4 (evaluation) or #1 (B.2.b)**. v2's scope is done; the
honest next move is to use what's built and let real-use friction
drive v3 priorities. If you want one more polish phase first, B.2.b
is the highest-leverage of the open items.

**Evaluation completed in this session** — see `docs/v2_evaluation.md`
for the prioritized friction log (23 items + 3 surprises). The doc's
"v3 status" section tracks which items landed.

**v3 polish complete** (same session): 16 of 23 friction items
closed across 4 commits — quick wins, output-layout + `mk state` CLI,
mass/show summary cleanup, and a second round covering URDF
short-names + float-noise threshold + mate-coincidence sanity + `mk
asm list` + `mk part show --json` + README refresh. The eval doc's
v3-status table tracks the per-commit mapping.

**Still open**: BOM rewrite (deferred per direction), diff apply
(~1wk, deferred per v2 plan), STEP geom_hash determinism (v3-
deferred), three documented surprises (OCC writer bug, container
rebuild time, model-viewer CDN). Nothing blocking.

Next session: either run the §4 evaluation loop again on actual
new work (find what hurts in *real* use of the polished tool), or
pick one of the three deferred-by-decision items if the timing's
right. The prototype is in a clean state to support either.

**State of the repo**: clean working tree (assuming this session's
D.1+D.2 commit lands), `main` at the most recent commit. Docs at
https://glenn-edgar.github.io/build123_container/.

**Quick verification commands**:
```bash
.venv/bin/pytest tests/                                        # 150 host tests, ~120 ms
docker compose run --rm cad layer ls asm_nested                # 5 layers + counts
docker compose run --rm cad mass asm_nested                    # default: include all
docker compose run --rm cad mass asm_nested --respect-layers   # filter
docker compose run --rm cad export asm_nested step             # color preserved
docker compose run --rm cad export asm_nested dxf              # 4-view drawing
docker compose run --rm cad show asm_nested                    # viewer filters hidden
docker compose run --rm cad export asm_window_test urdf        # B.4 still works
docker compose run --rm cad part export part_n20_worm_motor_16rpm  # B.3 still works
```

See §10 URDF, §11 typed META, §12 layers, §13 STEP+XCAF caveat,
§14 DXF drawings.

## 1. Definition of done — v1 ✅

The spec §14 sequence runs end-to-end on a fresh laptop with only Docker
installed:

```
docker compose up -d viewer
docker compose run --rm cad init
docker compose run --rm cad apply /project/manifests/two_part_asm.py
docker compose run --rm cad build asm_demo
docker compose run --rm cad mass asm_demo
docker compose run --rm cad bom asm_demo
docker compose run --rm cad export asm_demo step
docker compose run --rm cad show asm_demo
```

…and the model renders at `localhost:32323`. Verified 2026-05-09.

## 2. Architectural decisions (locked — carried forward from rev 2)

These are unchanged. Re-stated for self-containment:

- **Source of truth**: Python manifests, IaC model. DB is derived. `mk apply`
  is `terraform apply`.
- **DSL**: a Python builder API on top of `KnowledgeBaseManager`. *Not* an
  S-expression language. Builders are normal Python functions; their source
  is captured at apply time via `inspect.getsource`.
- **Storage**: SQLite at `/project/db/project.db`, reusing the existing
  `knowledge_base` schema unmodified. One `geometry(hash, brep_blob)` table
  added. No DDL changes to the KB tables.
- **One KB per part, one KB per assembly.** Sentinel labels `PART`, `JOINT`,
  `PARAM`, `META`, `SUB`, `INST`, `MATE`.
- **Joints as KB rows, never inline JSON.** Mate edges reference joints as
  real ltree paths.
- **Apply semantics**: naive truncate-and-rewrite per KB; diff-based apply is
  v2.
- **Engine**: build123d only.
- **Geometry hash**: `sha256(STEP-bytes)`. Param-aware hashing is v2.
- **Caching**: prototype rebuilds on every `mk build`; cascade caching is v2.
- **License**: Mozilla Public License 2.0 (MPL-2.0). File-level copyleft —
  modifications to mk-cad files stay MPL; embedding in proprietary work is
  fine. Supersedes the rev-2 spec's LGPL+exception decision (custom exception
  text was the risk; MPL achieves the same intent with battle-tested terms).
  build123d is depended on via the container, *not* vendored as source.

For the long-form rationale behind each, see the rev-2 archive — captured in
this file's history (`HISTORY.md`) and reproduced in `docs/spec_r2.md` if you
want the full text.

## 3. Phase 5 implementation — what actually shipped

The rev-2 spec assumed `yacv-server --watch /project/outputs/` would render
glTF the moment we wrote it. Discovery during Phase 5 implementation
(2026-05-09): **yacv 0.9.4 — the version in `:with_yacv` — has no CLI**. No
`yacv-server` binary, no `__main__.py`, no console-scripts entry point. The
package is a Python *library* meant to be embedded in a script that creates
shapes and pushes them through `yacv.show_*`.

Resolution: dropped yacv entirely from the viewer path. The `viewer` service
now runs `python -m http.server 32323 --directory /project/outputs`, and
`mk show` emits a tiny `index.html` next to the glTF that loads it via
Google's `<model-viewer>` web component (CDN-loaded; needs internet on first
visit). User refreshes the browser after each `mk show` rerun — there's no
auto-reload in this prototype.

What `mk show <asm>` actually does:

- Reads INST rows for the assembly, loads each BREP from the `geometry`
  cache, applies the solved `location` (translation + rotation) via
  `mk.transform.build123d_location`, builds a `Compound`, calls
  `build123d.export_gltf(compound, path)`. Defaults to text glTF (`.gltf` +
  separate `.bin` buffer); `--binary` writes a single `.glb`.
- Also writes `index.html` referencing the glTF. The viewer service serves
  both files at `:32323`.

Trade-offs accepted for v1:
- No camera-controls richness beyond what `<model-viewer>` provides
  (orbit/zoom/auto-rotate). Section views, exploded views, hierarchy panel,
  bookmark cameras: not supported.
- No live reload. Manual refresh after each rerun.
- glTF library loaded from a CDN. Air-gapped deployments would need to
  vendor `model-viewer.min.js` locally.

If any of these become friction during the §4 evaluation, revisit. The
embedded-yacv path is still available (option 2 from the original Phase-5
discussion) — it's just more code to write than was budgeted for v1.

## 4. After v1 — evaluation phase

Once v1 closes, the next step is **building real test parts** to find out
what's painful and what's missing in the API. Concretely:

- Pick 5–10 representative parts (a bracket, a fastener, a bearing, a frame
  segment, an enclosure, etc.) and write manifests for them.
- Build a small assembly that exercises `SUB` scopes (currently exercised only
  by `tests/fixtures/nested_asm.py`, never run end-to-end).
- Try mating them. Watch where the rigid-only mate solver feels limiting.
- Try the BOM and mass-props on the resulting assembly and see whether the
  output is usable for engineering review.

Track friction. Don't fix as you go — write it down. The result of this phase
should be a prioritized list that drives v2 design choices.

## 5. v2 plan

**The v2 commitment lives in `docs/v2_plan.md`.** Four phases, ~5–6 weeks
total:

- **Phase A** — close v1.x gaps (SUB mates, topo-sort, mass override,
  multi-asm viewer, mk part rm, pytest)
- **Phase B** — simulation + actuation (revolute/prismatic mates, browser
  animation, typed META schema, URDF export)
- **Phase C** — layers (LAYER sentinel + visibility filter; per-command
  policy; STEP roundtrip via XCAF)
- **Phase D** — engineering drawings (HLR ortho-view → DXF; optional PDF)

What's *out* of v2.0: FEA, Postgres, sandboxing, codegen, hash cascade,
diff apply, portable surface syntax, view pipeline beyond drawings. See
`docs/v2_plan.md` "Out of scope" section.

**CadQuery interop** (decided 2026-05-09): covered today via STEP/BREP
file exchange. STEP carries XCAF colors and labels which CadQuery's
`importers.importStep()` reads; in-process TopoDS_Shape handoff works
because both libraries wrap the same OCP bindings. Engine-pluggability
(CadQuery as an alternative builder engine inside mk-cad) remains
deferred to v3 — STEP-based interop is sufficient. See
`docs/cli.md` → "Interop with CadQuery / FreeCAD / ..." for the recipe.

## 5b. v2 sketch material (older notes)

The rev-2 §11 v2-deferral list is the long form. Specific design notes
accumulating under `docs/`:

- **`docs/v2_layers.md`** — layer tagging on INST/SUB, `LAYER` sentinel rows
  for visibility state, per-command policy on whether engineering vs viewer
  commands respect layer visibility. Not implemented.

Other v2 candidates from rev-2 §11, status unchanged:

- Hash-cascade caching (`inst_hash` over source + params + child hashes).
- Diff-based apply preserving unchanged-row `geom_hash`.
- DB → manifest round-trip codegen (the existing YAML exporter handles rows;
  the Python-manifest emitter is the new piece).
- Postgres adapter behind a backend interface (Postgres has native ltree).
- Builder sandboxing (subprocess + import allowlist + signed manifests for
  multi-user trunk).
- Engine pluggability (`payload.engine` field reserved but unused).
- View pipeline (ortho/section/exploded/sheet) — the spec deferral that is
  most likely to push the schema; layers (above) is its precondition.
- Multibody export (URDF) — needs a more capable mate solver first.

Prioritization waits on the §4 evaluation.

## 6. Repository layout

Current structure:

```
build123_container/
├── continue.md                 (this file — rev 3 handoff)
├── HISTORY.md                  what landed when, with verifications
├── README.md                   user-facing usage and units
├── NOTICE                      attribution (build123d, OCCT, yacv, KB infra)
├── Dockerfile                  thin layer on the build123d :with_yacv image
├── compose.yaml                cad + viewer services
├── pyproject.toml
├── docs/
│   └── v2_layers.md            v2 design sketch
├── vendor/
│   ├── ltree_sqlite.c          source — compiled in-container
│   ├── ltree.so                aarch64 host build (dev fallback only)
│   └── kb_python/              KnowledgeBaseManager + Construct_KB subset
├── src/mk/
│   ├── __main__.py             CLI: argparse + dispatch
│   ├── kb.py                   PartBuilder/AsmBuilder context managers
│   ├── builder.py              source capture + compile/exec runner
│   ├── geometry.py             shape ↔ STEP/BREP bytes, geometry hashing
│   ├── transform.py            location dict ↔ gp_Trsf (Phase 6)
│   ├── mate.py                 rigid mate solver (Phase 6)
│   ├── db.py                   open_db + ensure_schema + ltree loader
│   └── commands/               one module per `mk` subcommand
│       ├── init.py             ✅
│       ├── apply.py            ✅
│       ├── part.py             ✅
│       ├── asm.py              ✅
│       ├── build.py            ✅ (Phase 6: now calls solve_assembly)
│       ├── export.py           ✅ (step verified; stl/brep code paths exist)
│       ├── mass.py             ✅
│       ├── bom.py              ✅
│       └── show.py             ✅
├── tests/fixtures/
│   ├── single_part.py          Phase 2 verify
│   ├── two_part_asm.py         Phase 2/6 verify
│   └── nested_asm.py           SUB-scope fixture; never exercised
└── project/                    bind-mounted to /project in container
    ├── db/                     project.db
    ├── manifests/              copies of fixtures + box_unit.py (Phase 4)
    ├── inputs/
    └── outputs/                STEP / glTF outputs land here
```

## 7. Operational notes

- **No git repository** has been initialized in this directory. Everything
  has been on the working filesystem only. If you want history-tracked
  development, run `git init && git add . && git commit -m "v1 prototype
  through Phase 6"` from the project root. Doing this is the user's call —
  not initialized automatically.
- **Container arch**: image is amd64 only (upstream is amd64-only) and runs
  under qemu emulation on aarch64 hosts. `apt-get` and `pip install` layers
  during build take ~25–60 s each; subsequent rebuilds with cached layers are
  fast.
- **Never run `multiarch/qemu-user-static --reset -p yes`** on an aarch64
  host. It registers a `qemu-aarch64` binfmt handler that traps the host's
  own bash and crashes WSL. Docker Desktop's pre-existing handlers are
  sufficient.

## 8. Tests / verification status

| Spec verification                                               | Status |
| --------------------------------------------------------------- | ------ |
| Phase 1: `sqlite3 .tables` shows expected tables                | ✅     |
| Phase 1: `SELECT ltree_descendant('parts', 'parts.foo')` → 1    | ✅     |
| Phase 2: PARAM rows after applying `single_part.py`             | ✅     |
| Phase 2: `mk asm tree asm_demo` after applying `two_part_asm.py`| ✅     |
| Phase 3: `mk build` + `mk export step`                          | ✅     |
| Phase 4: `Box(10,10,10)` density 1 → mass 1.000 g exact         | ✅     |
| Phase 4: `mk bom asm_demo` returns expected counts              | ✅     |
| Phase 5: `mk show asm_demo` model in browser                    | ✅ via static-server + model-viewer (yacv CLI doesn't exist upstream) |
| Phase 6: bolt sits in bracket hole after `mk build`             | ✅     |
| `mk export <asm> stl` end-to-end                                | ✅     |
| `mk export <asm> brep` end-to-end                               | ✅     |
| `tests/fixtures/nested_asm.py` apply                            | ✅ — SUB rows generate correct ltree paths |
| `pytest` test suite                                             | ⚠️ none written; needs packaging-config setup |
| `mk measure` (CLI bbox/joints/distance)                         | ✅     |
| Viewer overlay (sidebar + 3D hotspots)                          | ✅     |
| build123d CSG support (booleans, holes)                         | ✅ — bracket fixture demonstrates `body - hole` |

## 9. Known limitations / v1.x backlog

Phase A of v2 (closed 2026-05-10) resolved most of these. Remaining open:

- **STEP geom_hash not deterministic.** `sha256(STEP-bytes)` picks up
  timestamps in OpenCascade's STEP serializer, so even identical builds
  produce different hashes. Cosmetic for prototype (cache still works);
  blocks v2 hash-cascade caching plans. Fix punted to v3.
- **Color rendering subtleties** (resolved in code, captured for memory):
  `Compound([list])` doesn't propagate child colors — must use
  `Compound(children=[...])` keyword form. `Color()` rejects hex strings;
  the parser in `show.py` handles it. `Location * Shape` strips the
  `.color` attribute; assign color *after* applying location. See
  `docs/troubleshooting.md` and the build123d-gotchas memory note.

Closed during Phase A:

- ✅ SUB-nested mate paths parse (regex + path-lookup fix).
- ✅ Topo-sort mates with cycle/over-constraint detection (no more
  `a_/b_/c_` naming discipline required).
- ✅ `META.mass_g_override` (virtual-density factor preserves inertia
  consistency).
- ✅ Multi-assembly viewer (`outputs/<asm>/` subdirs + top-level listing).
- ✅ `mk part rm <kb>` (dry-run by default; `--force` to delete; warns on
  dangling INST refs).
- ✅ pytest harness (26 tests on host via `.venv/bin/pytest`; OCP-needing
  tests gated behind a marker for in-container runs).

## 10. URDF export (Phase B.4) — conventions

`mk export <asm> urdf` writes to `outputs/<asm>/<asm>.urdf` with
`outputs/<asm>/meshes/<link>.stl` alongside. Units are SI (kg, m, kg·m²)
per URDF convention; STLs are mm-native with `scale="0.001 0.001 0.001"`
on each `<mesh>` element.

**Link frame** = the part's own build123d-local frame. Visual /
collision / inertial origins are zero except for `<inertial>`, which
places the CoM in link frame.

**Joint frame** = child link frame at DOF=0. Joint origin is
`inverse(T_parent) @ T_child` evaluated with all DOFs at zero. The
axis vector from the manifest (`mate(... axis=[...])`) is emitted as-is
because it's already in the joint frame under this convention.

**Mate → URDF joint type**:
- `rigid` → `fixed`
- `revolute` with limits → `revolute` (degrees converted to radians)
- `revolute` without limits → `continuous`
- `prismatic` → `prismatic` (mm → m on the limit)

**Tree topology**. Each INST is the child of at most one mate
(enforced by the existing topo-sort solver). Single-root assemblies
emit naturally. If multiple roots exist (disconnected parts), the
exporter synthesizes a `<link name="world"/>` and fixes each free
root to it.

**Inertia**. Computed via two GProp_GProps passes per part: first at
the origin (gives volume + CoM in part-local mm), second with the
reference point at the CoM (gives the inertia tensor at the CoM in
link frame). Density rules match `mk mass`: `META.density.value`
(g/cm³, default 1.0) or `META.mass_g_override.value` (g) when present.

**Color**. `META.color` hex string is parsed and emitted as a
URDF `<material><color rgba="r g b 1"/></material>` block inside
`<visual>`. Most ROS tools render this.

**Effort / velocity limits**. URDF's `<limit>` element requires
`effort` (N or N·m) and `velocity` (m/s or rad/s). We don't yet model
these — placeholder `effort="100" velocity="1"` is emitted. Phase B.3
typed META is where these properly live; until then the user can edit
the URDF or override per-tool.

**Smoke verifications**:
- `asm_hinge` → 2 links, 1 revolute joint @ 0–π rad, mass 23.55 g per
  leaf (matches `mk mass`).
- `asm_window_test` → 5 links, 4 fixed joints, single root (`sheet`),
  motor 10 g (mass_g_override), bracket 1.40 g (volume × ρ).

**Not yet covered** (potential follow-ups):
- Real ROS tool verification (urdf_viz, RViz, Gazebo). The XML
  parses cleanly and the tree is well-formed; downstream importability
  not exercised this session.
- Effort/velocity limits from typed META — could read these from
  Phase B.3's `mech.*` namespace (e.g. `mech.stall_torque_kg_cm`,
  `mech.no_load_rpm_at_12v`) but URDF still emits placeholders today.
- `<gazebo>` extension blocks for friction / contact tuning.

## 11. Typed META schema (Phase B.3) — conventions

Manifests can now use dotted META keys like
`electrical.voltage_nominal_v` or `mech.gear_ratio`. The dot splits
the name into hierarchical segments:

```python
p.meta("electrical.voltage_nominal_v", 12.0)
p.meta("electrical.voltage_min_v", 3.0)
p.meta("mech.gear_ratio", 100.0)
p.meta("density", 7.85)        # flat — stays top-level
```

Backward-compatible: the manifest API didn't change, `mk part show`
keeps its row-oriented display, and existing flat-name parts work
unchanged. Only the new `mk part export <kb>` consumer relies on
the tree shape.

**`mk part export <kb>`** emits a structured JSON document for
consumption by controller code (sim contract). Output shape:

```json
{
  "kb": "part_n20_worm_motor_16rpm",
  "description": "...",
  "params": { "body_d": 12, ... },
  "joints": {
    "body_center": {"origin": [0,0,0], "z_dir": [-1,0,0]},
    ...
  },
  "meta": {
    "density": 7.0,            // flat keys stay at top
    "color": "#5a6573",
    "electrical": {            // dotted keys nest
      "voltage_nominal_v": 12.0,
      "voltage_min_v": 3.0,
      "voltage_max_v": 12.0
    },
    "mech": { "gear_type": "worm", ... },
    "encoder": { "present": true },
    "_TODO_electrical_resistance_ohm": null,
    ...
  }
}
```

Default output is stdout, pretty-printed (2-space indent). Flags:
- `--out <path>` writes to file
- `--compact` single-line JSON

**Worked example**: `part_n20_worm_motor_16rpm` in `window_test.py`
demonstrates the convention. Its `electrical.*`, `mech.*`, and
`encoder.*` namespaces group together; placeholders kept under
`_TODO_*` top-level so reviewers can find them at a glance.

**Conflict detection**: A flat key and a namespace cannot share a
path. `meta("electrical", 12.0)` and `meta("electrical.voltage", 5.0)`
raise `MetaTreeConflictError` at export time. Duplicate keys raise
the same error.

## 12. Layers (Phase C.1+C.2) — conventions

Manifests can tag INST and SUB rows with one or more layer names via
the `layer=` kwarg. Single names or comma-separated multi-tag both
work; names must match `[A-Za-z_][A-Za-z0-9_]*`.

```python
a.inst("top_block", ref_kb="part_block", layer="frame")
with a.sub("group_a", layer="electronics") as s:
    s.inst("inner_a1", ref_kb="part_block")           # inherits "electronics"
    s.inst("inner_a2", ref_kb="part_block", layer="emi")
    # effective set: {"electronics", "emi"}
```

**Inheritance is additive.** An INST's effective layer set is the
union of its own tags with every ancestor SUB's tags. Untagged
anywhere falls back to the literal name `DEFAULT`, which is itself a
`LAYER` row that can be toggled.

**State storage.** Each named layer gets a `LAYER.<name>` row in the
assembly KB. Properties: `visible` (bool, default true), optional
`color` (hex string), optional `description`.

**Auto-create + state preservation.** First reference to a new layer
name in a manifest creates a `LAYER.<name>` row with
`{"visible": true}`. On re-apply (`mk apply`), the layer state is
snapshotted before truncate and restored after — so user-toggled
visibility / color survive subsequent applies even if the manifest
temporarily drops a tag.

**CLI**:
- `mk layer ls <asm>` — list with per-layer inst counts
- `mk layer set <asm> <name> on|off` — toggle one
- `mk layer all <asm> on|off` — bulk toggle
- `mk layer color <asm> <name> <#hex>` — set color

**What's not yet wired (Phase C.3, next session)**: visibility is
recorded but no command consumes it yet. `mk show`, `mk export gltf`,
etc. all still include every INST. C.3 threads the filter through.

**Tri-state visibility** (show / ghost / hide) was deferred per
`docs/v2_layers.md` §"Gotchas" #1 — bool is forward-compatible (readers
that only understand bool treat any non-`"hide"` state as visible),
and tri-state ghosting needs viewer infrastructure that lives in
Phase B.2.b territory.

## 13. Phase C.3 + C.4 — what threads layers through, what doesn't

**C.3 (per-command visibility filter)** — the policy is encoded in
each command:

| Command | Default | Notes |
|---|---|---|
| `mk show` | filter hidden | sidebar / glTF / joint hotspots all skip hidden insts |
| `mk export gltf` | (same as show, see show.py) | |
| `mk export stl` | filter hidden | visualization-bound |
| `mk export step` | include all | XCAF emits layer metadata via C.4 |
| `mk export brep` | include all | engineering-bound; no layer concept in BREP |
| `mk export urdf` | include all | sim needs full kinematic tree |
| `mk mass` | include all | `--respect-layers` opt-in for filtering |
| `mk bom` | include all | `--respect-layers` opt-in |
| `mk build` | always all | hidden ≠ unbuilt; cache is layer-agnostic |

The visibility helper `mk.layers.build_visibility_index(conn, asm_kb)`
is the single source of truth. Each command reads it once at the top
and skips hidden insts when emitting output. Union semantics: an inst
is visible if *any* of its effective layers is visible.

**C.4 (STEP XCAF roundtrip)** — see also `src/mk/step_xcaf.py` docstring:

- **Color works**: `META.color` hex → `Quantity_Color` →
  `COLOUR_RGB` in STEP. FreeCAD picks it up.
- **Layers are best-effort**: OCC 7.8.1.1's `STEPCAFControl_Writer`
  emits at most one shape per `PRESENTATION_LAYER_ASSIGNMENT`
  *and* drops multi-tag shapes. Workaround: write the
  alphabetically-first layer per inst, warn on stderr when multi-
  tag info is lost.
- Multi-shape-per-layer (e.g., all DEFAULT) gets only the last
  shape's assignment in the STEP file — known OCC issue.
- Phase D's DXF export sidesteps this entirely by attaching layers
  directly via ezdxf, which we control end-to-end (see §14).

## 14. Phase D.1+D.2 — engineering drawings (DXF)

`mk export <asm> dxf` writes `outputs/<asm>.dxf` containing four
views of the assembly in standard third-angle layout:

```
+-----+   +-----+
| TOP |   | ISO |
+-----+   +-----+
+-----+   +-----+
|FRONT|   |RIGHT|
+-----+   +-----+
              +------------------+
              | TITLE BLOCK      |
              | assembly | desc  |
              | part_no  | vendor|
              +------------------+
```

**HLR pipeline** (src/mk/hlr.py):
- Each inst's BREP at its mate-resolved location → combined
  `TopoDS_Compound`.
- `HLRBRep_Algo.Update()` + `.Hide()` per view direction →
  `HLRBRep_HLRToShape` extractor splits edges into visible / hidden
  (sharp + tangent + silhouette buckets unioned).
- Edges in OCC's 3D output are projected to 2D via
  `project_to_2d()`: `right = look × up` (third-angle convention,
  scene +X appears on viewer's left in front view), screen-y = up.

**DXF emission** (src/mk/dxf.py):
- 4 layers: `MK_VISIBLE` (continuous, default color), `MK_HIDDEN`
  (DASHED, color 8), `MK_TITLE`, `MK_BORDER`.
- Each edge discretized to a 24-segment LWPOLYLINE. Sufficient for
  most CAD viewers; exact line/arc preservation is a follow-up
  polish item (~1 day).
- Title block reads `META.part_number` and `META.vendor` from the
  first INST's referenced part; assembly description from KB info.
- ezdxf header `$INSUNITS = 4` → millimetres.

**Per-command layer policy**: include-all (engineering-bound per
Phase C.3). The mk-cad LAYER state from Phase C doesn't currently
map to DXF layers; if downstream toolchains want per-mk-cad-layer
edge segregation in the DXF, the emitter would route edges through
`partition_by_visibility` and emit per-layer DXF layers. Hasn't
been requested yet.

**Smoke verifications**:
- `asm_nested` (4 cubes): 78 MK_VISIBLE polylines + 66 MK_HIDDEN
  + title block, 143 KB.
- `asm_window_test` (5 parts, includes curved motor body): 94 +
  348 + title block, 370 KB. Hidden line count dominated by
  cylinder/encoder facet edges.
- Roundtrip via `ezdxf.readfile` confirms layer assignments and
  `$INSUNITS = 4` (mm) preserved.

**Not yet covered**:
- D.3 (`ezdxf.addons.drawing` → PDF). Optional per v2_plan. A
  `dxf2pdf` external pass or FreeCAD TechDraw fills the gap.
- Exact line / circle / arc entity preservation. The discretizer
  treats every curve uniformly. Real LINE / ARC entities would
  cut file size and improve fidelity.
- Per-mk-cad-layer DXF layer mapping (currently flat MK_VISIBLE
  / MK_HIDDEN regardless of which mk-cad layer each part is on).
