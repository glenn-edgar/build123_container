# continue.md — `<project>`: build123d + ltree CAD prototype (rev 3)

This is **revision 3** of the handoff spec. It supersedes rev 2 only for
**status, definition of done, and next steps**. The architectural decisions in
rev 2 §2 are *locked* and remain authoritative — they're carried forward
verbatim in §2 below. Working history (what landed when) lives in
`HISTORY.md`. v2 design sketches accumulate under `docs/`.

## 0. Where we are

**v1 baselined** as of 2026-05-09. All six rev-2 phases verified end-to-end.
Container builds clean as `mk-cad:local`; `mk init`, `mk apply`, `mk build`,
`mk mass`, `mk bom`, `mk export <step|stl|brep>`, `mk show`, `mk measure`,
`mk part new` all green.

**Real-world evaluation #1 active**: `project/manifests/window_test.py`
(`asm_window_test`) is an N20 worm-motor + lever + L-bracket digital twin
for window-controller software-in-the-loop testing. Renders end-to-end
with per-part colors. Surfaced and fixed five bugs during construction —
see `HISTORY.md` 2026-05-09 entry. Documentation site config in
`mkdocs.yml`; rendered docs under `docs/`.

The next iteration on the evaluation drives v1.x and v2 priorities (§4).

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

Things found during mop-up + the §4 evaluation that should be addressed
before they bite the next evaluator:

- **SUB-nested mate paths don't parse.** `src/mk/mate.py`'s `JOINT_PATH_RE`
  matches only the flat form `<asm>.INST.<inst>.JOINT.<joint>`. Paths like
  `asm_nested.SUB.group_a.INST.inner_a1.JOINT.face` (which the
  `kb_asm.sub()` context manager generates) don't parse, so any nested
  assembly with mates breaks at `mk build` time. Fix is a small regex +
  INST-lookup-by-path change in `mate.py` and `measure.py`. <100 lines.
- **No pytest harness.** The repo has no `tests/test_*.py`. Coverage is the
  manual §1 verifier sequence. Wiring pytest needs `pip install -e .`
  packaging config so tests can `import mk.*` cleanly.
- **STEP geom_hash not deterministic.** `sha256(STEP-bytes)` picks up
  timestamps in OpenCascade's STEP serializer, so even identical builds
  produce different hashes. Cosmetic for prototype (cache still works);
  blocks v2 hash-cascade caching plans.
- **Mass override missing.** `META.density × volume` over-counts hollow
  assemblies — the N20 motor renders as 43 g where real is ~10 g. Add
  `META.mass_g_override` that supersedes the volume×density calc. ~15
  lines in `mass.py`.
- **Single index.html per outputs/.** `mk show <asm>` overwrites whatever
  the previous `mk show` wrote. Multi-asm projects need separate URLs.
  Could partition by subdirectory (`/asm_window_test/`,
  `/asm_unit_box/`...) and have viewer serve each.
- **No `mk part rm`.** Stale KBs from prior fixtures persist forever.
  Need a delete command (or a `--force` re-apply mode that clears the
  KB before rewrite).
- **Mate solver assumes joint-b is the fixed end.** No detection of cycles,
  no over-constraint handling, no bidirectional propagation. Works for
  trees of mates processed in dependency order; falls over on closed
  loops (which would be needed for kinematic chains in v2).
- **Color rendering subtleties** (resolved during evaluation but worth
  noting): `Compound([list])` doesn't propagate child colors — must use
  `Compound(children=[...])` keyword form. `Color()` rejects hex strings;
  needs the parser added in `show.py`. `Location * Shape` strips the
  `.color` attribute; assign color *after* applying location.
