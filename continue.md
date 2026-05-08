# continue.md — `<project>`: build123d + ltree CAD prototype (rev 3)

This is **revision 3** of the handoff spec. It supersedes rev 2 only for
**status, definition of done, and next steps**. The architectural decisions in
rev 2 §2 are *locked* and remain authoritative — they're carried forward
verbatim in §2 below. Working history (what landed when) lives in
`HISTORY.md`. v2 design sketches accumulate under `docs/`.

## 0. Where we are

Phases 1–4 and 6 of the rev-2 phase plan are complete and verified end-to-end
against `tests/fixtures/single_part.py`, `tests/fixtures/two_part_asm.py`, and
the Phase-4 sanity fixture `project/manifests/box_unit.py`. Container builds
clean as `mk-cad:local`; `mk init`, `mk apply`, `mk build`, `mk mass`,
`mk bom`, `mk export step` all green.

**The single remaining piece for v1** is Phase 5 — `mk show` + the yacv
viewer service smoke test.

## 1. Definition of done — v1

The spec §14 sequence must run end-to-end on a fresh laptop with only Docker
installed:

```
docker compose up -d viewer
docker compose run --rm cad init
docker compose run --rm cad apply /project/manifests/two_part_asm.py
docker compose run --rm cad build asm_demo
docker compose run --rm cad mass asm_demo
docker compose run --rm cad bom asm_demo
docker compose run --rm cad export asm_demo step
docker compose run --rm cad show asm_demo            # ← only this is unimplemented
```

Every command except `mk show` is currently green. Closing v1 means:

1. **Implement `src/mk/commands/show.py`**. Walk INST rows, load BREP from the
   `geometry` table, apply `INST.location` via `mk.transform`, build a
   `Compound`, and write glTF to `/project/outputs/<asm>.gltf`. Use whatever
   build123d exposes (`export_gltf` or equivalent — verify the actual API at
   implementation time; the rev-2 spec note about an HTTP push is wrong, the
   viewer is volume-mount-driven, see §3 below).
2. **Bring up the viewer service** (`docker compose up -d viewer`) and confirm
   it serves at `localhost:32323` and hot-reloads when `mk show` rewrites the
   glTF.
3. **README touch-up** documenting the show workflow.

The viewer service is already wired in `compose.yaml` (no Compose changes
needed). Estimated work: ~30 lines + a smoke test.

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

## 3. Phase 5 implementation notes

The rev-2 spec §8 mentioned HTTP push to yacv — that was wrong and was
corrected in rev 2 §2 ("Viewer" decision, verified Nov 2026). Current truth:

- yacv has **no standalone Docker image** and **no HTTP push API**. It ships
  bundled into `ghcr.io/derhuerst/build123d:with_yacv`.
- Both `cad` and `viewer` services use the *same* locally-built `mk-cad:local`
  image; they differ only in entrypoint. The `viewer` service runs
  `yacv-server --watch /project/outputs`.
- `mk show <asm>` writes glTF to `/project/outputs/<asm>.gltf`. yacv-server
  hot-reloads it. Browser at `localhost:32323`.

Implementation skeleton (~30 lines):

```python
# src/mk/commands/show.py
def run(args):
    conn = open_db(args.db)
    rows = ... # SELECT INST rows like in mk build / mk export
    shapes = []
    for r in rows:
        # load BREP from geometry by geom_hash; apply build123d_location.
        ...
    compound = Compound(shapes)
    out = Path(args.outdir) / f"{args.asm_kb}.gltf"
    # build123d API: verify whether it's `export_gltf` or `compound.export_gltf(...)`
    # at implementation time. Same pattern as src/mk/commands/export.py.
    print(f"wrote {out}; viewer at http://localhost:32323")
```

No new schema. No new vendored dependency. Just a new command file plus
registration in `__main__.py`.

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

## 5. v2 directions (sketches, not commitments)

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
│       └── show.py             ❌ Phase 5
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
| Phase 5: `mk show asm_demo` model in browser                    | ❌     |
| Phase 6: bolt sits in bracket hole after `mk build`             | ✅     |
| `mk export <asm> stl` end-to-end                                | ⚠️ untested |
| `mk export <asm> brep` end-to-end                               | ⚠️ untested |
| `tests/fixtures/nested_asm.py` apply                            | ⚠️ untested |
| `pytest` test suite                                             | ⚠️ none written |

The ⚠️ items are inside completed phases and don't block v1 done. Worth
mopping up before declaring v1 complete; could also wait for the §4
evaluation phase to drive what tests actually matter.
