# CLI reference

Every `mk` subcommand, in the order you'll typically use them.

All commands run inside the `cad` Compose service:

```bash
docker compose run --rm cad <subcommand> [args]
```

Most commands accept `--db <path>` (defaulting to `/project/db/project.db`).
Commands that write artefacts also accept `--outdir <path>` (defaulting to
`/project/outputs/`). These defaults match the volume-mounted host paths.

## Setup

### `mk init`

Open the DB, load the ltree extension, ensure the schema (KB tables +
`geometry` table), exit. Idempotent — safe to re-run.

```bash
mk init
mk init --db /project/db/other.db
```

Output:
```
DB ready at /project/db/project.db
  tables: geometry, knowledge_base, knowledge_base_info, ...
  ltree: ok
```

If `ltree: ok` is missing, the extension didn't load — see
[Troubleshooting](troubleshooting.md).

## Authoring

### `mk part new <name> [--template <kind>]`

Scaffold a starter manifest into `/project/manifests/<name>.py`.

Templates:

| Template | Geometry |
|---|---|
| `block` (default) | `Box(w, d, h)` with three params |
| `cylinder` | `Cylinder(d/2, h)` with two params |
| `plate_with_hole` | `Box(w, d, t) - Cylinder(hole_d/2, t*4)` |
| `blank` | A 10 mm box; replace the body |

```bash
mk part new my_widget --template plate_with_hole
mk part new fasteners/m3_socket --template cylinder      # subdirs OK
```

The generated file applies cleanly out-of-the-box; edit params, joints,
meta, and the builder body to suit.

### `mk apply <file>`

Import the manifest module. Every `kb_part` and `kb_asm` block truncates
the named KB and writes fresh rows. Idempotent — rerunning `mk apply` on
the same manifest leaves the same end state.

```bash
mk apply /project/manifests/window_test.py
```

Manifests may declare multiple parts and assemblies. They're processed in
the order they appear.

### `mk build <asm_kb>`

Resolve mates in dependency order, run each INST's referenced builder,
serialize to STEP+BREP, hash, dedupe against the geometry cache, write
`geom_hash` back to each INST row. Always rebuilds in v1 (no
hash-cascade caching yet).

```bash
mk build asm_window_test
```

You'll see one line per resolved mate (with the inst's world-frame
location), then one line per INST naming its `geom_hash` prefix.

## Inspection

### `mk part list [--prefix <p>]`

List part KBs. Default prefix is `part_`.

```bash
mk part list
mk part list --prefix part_n20
mk part list --prefix asm_         # also works for assemblies
```

### `mk part show <kb_name>`

Print a part KB's contents — params, joints, meta, builder source line
count.

```bash
mk part show part_lever_arm
```

### `mk asm tree <asm_kb>`

Render the assembly hierarchy as ASCII, showing INSTs (with `ref_kb` and
any `params_override`) and MATEs (with both joint paths).

```bash
mk asm tree asm_window_test
```

## Output

### `mk show <asm_kb> [--binary]`

Write `<asm>.gltf` (or `<asm>.glb` with `--binary`) and an `index.html`
into `/project/outputs/`. The viewer service serves them at
`http://localhost:32323`. Refresh the browser after each rerun (no
auto-reload in v1).

The emitted page bakes in:

- A *Stats* panel: bbox extents, mass, CoM
- An *Instances* panel: per-INST bbox in world coords
- A *Joints* panel: world-frame coords for every joint, with 3D hotspots
  pinned at each joint origin on the model

Panels are draggable, collapsible, and position-persisted in localStorage.
Double-click empty viewport to reset positions.

```bash
mk show asm_window_test
mk show asm_window_test --binary       # glb instead of gltf
```

### `mk export <asm_kb> <fmt>`

Write a single artefact:

| Format | Output |
|---|---|
| `step` | ISO-10303-21, with XCAF colors and labels |
| `stl` | binary STL |
| `brep` | OpenCascade BREP |

```bash
mk export asm_window_test step
mk export asm_window_test stl
mk export asm_window_test brep
```

#### Interop with CadQuery / FreeCAD / SolidWorks / Fusion 360

The STEP file preserves per-part colors and labels via XCAF. Any tool that
reads STEP can consume mk-cad output:

```python
# CadQuery
import cadquery as cq
result = cq.importers.importStep("project/outputs/asm_window_test.step")
```

```
# FreeCAD: File → Import → asm_window_test.step
# SolidWorks / Fusion 360: File → Open → STEP file
```

build123d and CadQuery both wrap the same `OCP` Python bindings, so you
can also hand a `TopoDS_Shape` directly between them without going
through a file:

```python
from build123d import import_step
b = import_step("asm_window_test.step")

import cadquery as cq
result = cq.Workplane(obj=b.wrapped)
```

Use the file path for cross-tool / cross-machine interop; use the
in-process path when you want to continue parametric work in CadQuery
after generating geometry in mk-cad.

## Engineering

### `mk mass <asm_kb>`

Total mass, centre of mass (mm), inertia tensor (g·mm²), principal moments
and axes. Iterates INST rows, loads BREP from cache, applies location,
weights by `META.density` from the part KB (default 1.0 g/cm³ if absent).

```bash
mk mass asm_window_test
```

Per-instance breakdown printed first, then the assembly totals.

Units convention: mm, mm³, g/cm³, g, g·mm². See README.

### `mk bom <asm_kb>`

Flat parts list grouped by `ref_kb`, sorted by quantity. The "killer
query" — one `GROUP BY json_extract(properties, '$.ref_kb')`.

```bash
mk bom asm_window_test
```

### `mk measure <asm_kb> [--no-joints] [--distance JOINT_A JOINT_B]`

Bounding boxes (overall + per-instance, world coords), joint frames in
world coordinates, optional Euclidean distance between two joint paths.

```bash
mk measure asm_window_test
mk measure asm_window_test --distance \
    asm_window_test.INST.lever.JOINT.tip \
    asm_window_test.INST.bracket.JOINT.foot_bottom
```

The `--distance` flag also doubles as a mate-solver sanity check: any rigid
mate's two joints should be 0.0000 mm apart in world coordinates.

## Verbosity

All commands accept `-v` / `--verbose` for `DEBUG`-level Python logging.
By default mk prints `INFO` level.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | command-specific failure (missing manifest, missing geom_hash, etc.) |

Tracebacks bubble up from builder execution and DB errors — no silent
failures.
