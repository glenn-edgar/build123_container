# Project history

Phase-by-phase record of what was built, when, and what was verified. Pairs
with `continue.md` (forward-looking handoff) and `docs/v2_layers.md` (v2
sketches).

## 2026-05-08 — v1 prototype: Phases 1–4 + 6

Worked through the spec in `continue.md` (revision 2). Phase 5 (yacv viewer)
deferred; everything else complete.

### Phase 1 — Container + DB scaffold ✅

- `Dockerfile` `FROM ghcr.io/derhuerst/build123d` (digest-pinned, `:with_yacv`
  variant, `--platform=linux/amd64`).
- `compose.yaml` defines `cad` and `viewer` services sharing the same
  locally-built image.
- Vendored `ltree_sqlite.c` and compiled to `/usr/local/lib/ltree.so` *inside*
  the container during build. **Reason**: the host-vendored `ltree.so` is
  aarch64 and won't dlopen under qemu-amd64; SQLite's "no such file" error in
  that case is misleading.
- `src/mk/db.py` opens SQLite, loads ltree, runs `CREATE TABLE IF NOT EXISTS`
  for the existing KB tables plus a new `geometry(hash, brep_blob)` table.
- `mk init` verified end-to-end against the container.

### Phase 2 — Manifest API + apply ✅

- `src/mk/kb.py` provides `connect()`, `kb_part`, `kb_asm` context managers
  built on top of `KnowledgeBaseManager` from
  `vendor/kb_python/knowledge_base_manager.py`.
- `mk apply <manifest.py>` dynamically imports the manifest; the `connect()`
  context picks up `MK_DB` and threads the connection via `contextvars`.
- Sentinel labels (`PART`, `JOINT`, `PARAM`, `META`, `SUB`, `INST`, `MATE`)
  populated correctly. Path layout matches spec §5.1.
- Verified against `tests/fixtures/single_part.py` and
  `tests/fixtures/two_part_asm.py`.

### Phase 3 — Builder runner + STEP export ✅

- `src/mk/builder.py` reads `PART.body.properties.source`, compiles + execs
  into a fresh namespace with `from build123d import *` already applied,
  calls the entry function with the merged param dict.
- `src/mk/geometry.py` has `shape_to_step_bytes`, `shape_to_brep_bytes`,
  `brep_bytes_to_shape`, `geometry_hash`. Uses tempfile + disk for OCC
  serialization (stable across OCP versions; cost negligible).
- `mk build <asm>` walks INST rows, runs builders, caches BREP keyed by
  sha256 of STEP bytes, writes `geom_hash` back to INST `properties`.
- `mk export <asm> step` produces a valid ISO-10303-21 STEP file.

### Phase 4 — Mass properties + BOM ✅

- `src/mk/commands/mass.py` uses `OCP.BRepGProp.VolumeProperties_s` and
  `GProp_GProps.Add(item, density)` to combine instances with parallel-axis
  weighting. Honors `INST.location` (translation) per the existing schema.
- Units convention documented in `README.md`: mm / mm³ / g/cm³ / g / g·mm².
- Sanity test: `Box(10,10,10)` with density 1 → mass `1.0000 g` exact;
  diagonal inertia `m·a²/6 = 16.667 g·mm²` exact.
- `src/mk/commands/bom.py` is the spec §9 "killer query" — one
  `GROUP BY json_extract(properties, '$.ref_kb')`.

### Phase 6 — Rigid mate solver ✅

- `src/mk/mate.py` parses joint paths of the form
  `<asm>.INST.<inst>.JOINT.<joint>`, looks up frames in the inst's referenced
  part KB, computes a rotation (via `gp_Quaternion.SetRotation(vec1, vec2)`)
  and translation that places joint A coincident with joint B with
  z-axes opposing.
- Schema extension: `INST.properties.location` now optionally carries a
  `rot` 3×3 rotation matrix alongside `loc`. Pre-Phase-6 manifests still work.
- `src/mk/transform.py` is the shared helper that turns the location dict
  into a `gp_Trsf` (or build123d `Location`); `mass.py` and `export.py` both
  consume it.
- `mk build` runs `mate.solve_assembly` before iterating INSTs, so a single
  `mk build asm_demo` covers `apply → mate → build → export`.
- Verified: bolt's `thread_tip` lands at the bracket's `hole_top.origin`
  with z-axes opposing. Total mass unchanged (rigid transforms preserve it);
  bolt CoM transforms by exactly the math the rotation predicts.

### Operational notes from this session

- A previous session crashed WSL by running `multiarch/qemu-user-static
  --reset -p yes`, which registered a `qemu-aarch64` binfmt handler on an
  aarch64 host — every `bash` invocation got intercepted and re-run through
  `qemu-aarch64-static`, an aarch64 binary, recursively. Outcome: ENOEXEC
  cascade, WSL killed by Hyper-V, lost work. Recovery: WSL rebooted on its
  own, binfmt state cleared. Saved as a feedback memory so this doesn't
  recur. Docker Desktop's pre-existing `x86_64`-only binfmt handler is
  sufficient for our amd64 builds — no `multiarch/qemu-user-static` needed.

## 2026-05-08 — Licensing decision

Relicensed from rev-2's planned LGPL-2.1 + Python-aware exception to **Mozilla
Public License 2.0**. Reason: the custom exception text (necessary because
LGPL was written for the C/C++ linking model) is the kind of artisanal
license-authoring that creates ambiguity. MPL 2.0 achieves the same intent —
file-level copyleft on mk-cad source, with no friction when embedded in
proprietary work — using battle-tested terms.

Mechanical changes: `LICENSE` file added (canonical Mozilla text), SPDX
headers on all 24 source files updated `LGPL-2.1-or-later` → `MPL-2.0`,
`pyproject.toml` `license` field updated, `continue.md` §2 and `NOTICE`
amended.

## What's next

See `continue.md` (revision 3) for the forward plan: finish Phase 5, build a
small library of real test parts to exercise the API, then prioritize v2 work
based on what hurts in real use.
