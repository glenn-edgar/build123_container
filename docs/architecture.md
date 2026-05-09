# Architecture

mk-cad is a thin layer over three pre-existing pieces:

- **build123d** — Python parametric CAD, on top of OpenCascade.
- **A SQLite ltree-aware knowledge_base** — the user's pre-existing
  `KnowledgeBaseManager` infrastructure, vendored under `vendor/kb_python/`.
  Gives us namespaced KBs, ltree paths, scalar `ltree_*` UDFs.
- **`<model-viewer>`** — Google's web component, loaded from a CDN.

Everything specific to mk-cad lives under `src/mk/` and totals ~1500 lines.

## Two-level namespace

Every part and every assembly gets its own KB (a row in
`knowledge_base_info`). This is the *outer* namespace — `kb_name` discriminates
between parts and assemblies and individual designs.

By convention:

- Parts use `part_*` prefix
- Assemblies use `asm_*` prefix

The convention isn't schema-enforced (yet); see
`continue.md` §11 for the v2 plan to add a CHECK constraint.

Inside each KB, rows are addressed by **ltree paths** built from sentinel
labels:

```
<kb_name>.<LABEL>.<name>
```

For nested assemblies, the path can include `SUB.<sub_name>` segments:

```
<asm>.SUB.<group>.INST.<inst_name>.JOINT.<joint_name>
```

## The seven sentinel labels

Every row in `knowledge_base` carries one of these values in its `label`
column. The label encodes what kind of thing the row represents.

| Label | Used in | Meaning |
|---|---|---|
| `PART` | parts | The build target. Carries the builder source code in `properties.source`. |
| `PARAM` | parts | A default parameter value the builder consumes. |
| `JOINT` | parts | A named coordinate frame attached to the part. Mate edges reference these. |
| `META` | parts | Material/density/color/electrical specs/anything not geometry. |
| `SUB` | assemblies | A subassembly node (creates a `SUB.<name>` segment in child paths). |
| `INST` | assemblies | A leaf instance. `properties.ref_kb` points to the part KB. |
| `MATE` | assemblies | An edge linking two joint paths into a constraint (rigid for v1). |

A query like

```sql
SELECT * FROM knowledge_base
WHERE knowledge_base = ? AND label = ?
```

is the workhorse — every interesting thing the system needs to find boils
down to one of these. See [the BOM query](#bom-the-killer-query) for the
canonical example.

## How rows resolve at build time

Rough flow when you run `mk build asm_foo`:

1. **Mate solve**. Walk all `MATE` rows in `asm_foo`. For each, parse the
   joint paths to identify the inst pair, look up each part's joint frame,
   and compute the rigid transform that places joint A coincident with
   joint B (z-axes opposing). Compose with joint B's already-resolved
   transform from earlier mates in the chain. Write the result to inst A's
   `INST.properties.location`.

2. **Walk INST rows**. For each, read `ref_kb`, look up the part KB's
   `PART.body` row, get `properties.source` (the captured Python text),
   `compile + exec` it in a fresh namespace with `from build123d import *`,
   call the entry function with merged params (defaults + INST overrides).

3. **Cache BREP**. Serialize the build123d shape to STEP bytes, hash with
   `sha256`, look up `geometry.hash` — if absent, also serialize to BREP and
   insert the row. Write the hash back to the INST as `properties.geom_hash`.

4. **Output**. `mk show`, `mk export`, `mk mass`, `mk measure` all read
   the BREP from `geometry`, apply the `INST.location` transform, optionally
   set per-part color from `META.color`, build a `Compound`, and run the
   appropriate exporter.

## The path layout for a real assembly

Take the window-test rig (`asm_window_test`):

```
asm_window_test
├── INST.sheet        →  ref_kb=part_hdpe_sheet
├── INST.bracket      →  ref_kb=part_meccanixity_bracket
├── INST.motor        →  ref_kb=part_n20_worm_motor_16rpm
├── INST.lever        →  ref_kb=part_lever_arm
├── INST.lbracket     →  ref_kb=part_paoleju_lbracket
├── MATE.a_bracket_to_sheet
├── MATE.b_motor_to_bracket
├── MATE.c_lever_to_shaft
└── MATE.d_lbracket_to_sheet
```

And inside, say, `part_n20_worm_motor_16rpm`:

```
part_n20_worm_motor_16rpm
├── PART.body                ←  the geometry builder
├── PARAM.body_d=12          ←  motor body diameter (mm)
├── PARAM.body_l=25
├── PARAM.shaft_d=3
├── ... (more PARAM rows)
├── JOINT.gearbox_front      ←  +X face of gearbox (legacy mount)
├── JOINT.body_center        ←  middle of body cylinder (used in window-test)
├── JOINT.shaft_a_tip        ←  top output shaft tip
├── JOINT.shaft_b_tip        ←  bottom output shaft tip
├── META.density=7.0
├── META.color="#5a6573"
├── META.electrical_voltage_nominal_v=12.0
├── META.mech_no_load_rpm_at_12v=16
├── META.mech_gear_type="worm"
├── META.encoder_present=True
└── ... (more META rows for the simulation contract)
```

## Mate names sort in dependency order

The mate solver processes `MATE` rows in **path order** (alphabetical
by `name`). Chain mates require the joint-b inst to be resolved before the
joint-a inst is computed, so naming follows a `a_, b_, c_, ...` discipline:

```
asm_window_test.MATE.a_bracket_to_sheet     ← bracket positioned on sheet (sheet at identity)
asm_window_test.MATE.b_motor_to_bracket     ← motor positioned via bracket's resolved transform
asm_window_test.MATE.c_lever_to_shaft       ← lever positioned via motor's resolved transform
asm_window_test.MATE.d_lbracket_to_sheet    ← independent; sheet at identity
```

Topological sorting is a v1.x backlog item; for now naming discipline keeps
chains correct.

## INST.location format

After mate solve, `INST.properties.location` looks like:

```json
{
  "loc": [50.0, 10.675, 0.0],
  "rot": [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0]
  ]
}
```

The `rot` field is a 3×3 rotation matrix; `loc` is the translation in mm.
Both interpreted as world-frame transforms (composed through any prior
mates in the chain). When `rot` is absent, identity is implied. Pre-Phase-6
manifests that only set `loc` still work.

## BOM, the killer query

Because INSTs carry `ref_kb` in `properties` and live under one
`label = 'INST'` bucket, the bill-of-materials is one SQL statement:

```sql
SELECT
  json_extract(properties, '$.ref_kb') AS part,
  COUNT(*) AS qty
FROM knowledge_base
WHERE knowledge_base = ?            -- the assembly KB
  AND label = 'INST'
GROUP BY part
ORDER BY qty DESC, part;
```

This is `mk bom` (`src/mk/commands/bom.py`). The row layout is what makes
it possible.

## ltree extension

The vendored ltree extension is *not* the Postgres ltree operator set
(`<@`, `@>`, `~`). It's a SQLite extension that exposes scalar functions:

| Function | Equivalent | Notes |
|---|---|---|
| `ltree_match(path, pattern)` | Postgres `~` | Supports `*`, `COL*`, `*{n,m}` |
| `ltree_ancestor(child, parent)` | Postgres `<@` | parent is an ancestor of child |
| `ltree_descendant(parent, child)` | Postgres `@>` | child is a descendant of parent |
| `ltree_depth(path)` | path length | for filtering by depth |

For hot prefix queries, pair the function with a `LIKE` clause so SQLite
uses the path index:

```sql
WHERE path LIKE 'asm_window_test.%' AND ltree_descendant('asm_window_test', path)
```

UDFs alone trigger full scans.

## What lives where in the codebase

```
src/mk/
├── __main__.py              CLI: argparse + dispatch
├── kb.py                    PartBuilder/AsmBuilder context managers
├── builder.py               source capture + compile/exec runner
├── geometry.py              shape ↔ STEP/BREP bytes; geometry hashing
├── transform.py             location dict ↔ gp_Trsf (Phase 6)
├── mate.py                  rigid mate solver with chain composition
├── db.py                    open_db + schema + ltree loader
└── commands/
    ├── init.py              create DB, ensure schema
    ├── apply.py             import a manifest .py
    ├── part.py              list / show / new
    ├── asm.py               tree
    ├── build.py             solve mates → run builders → cache BREP
    ├── export.py            STEP / STL / BREP
    ├── show.py              glTF + viewer index.html
    ├── mass.py              mass / CoM / inertia
    ├── bom.py               grouped INST.ref_kb count
    └── measure.py           bboxes / joint world coords / distances
```

`vendor/kb_python/` and `vendor/ltree_sqlite.c` are the user's KB
infrastructure subset, vendored verbatim. `vendor/__init__.py` is a
namespace marker.

## Locked architectural decisions

These are unchanged since rev-2 of the spec:

- **Source of truth: Python manifests** (IaC model). DB is derived state.
  `mk apply` is `terraform apply`.
- **DSL: Python builder API**, not S-expressions. Builders are normal
  functions; `inspect.getsource` captures their text into the `PART.body` row.
- **Storage: SQLite + the existing KB schema**, unmodified. One
  `geometry(hash, brep_blob)` table added for BREP cache.
- **One KB per part, one KB per assembly.** Cheap; eliminates path
  collisions; makes BOM trivial.
- **Joints as KB rows, never inline JSON.** Mate edges reference joints
  as real ltree paths.
- **Apply: naive truncate-and-rewrite per KB.** Diff-based apply is v2.
- **Engine: build123d only.** Engine pluggability is a v2 concern.
- **Geometry hash: `sha256(STEP-bytes)`.** Param-aware hashing is v2.
- **Caching: rebuild every `mk build`.** Cascade caching is v2.
- **License: MPL 2.0**, supersedes the rev-2 plan to use LGPL with a
  Python-aware exception.
