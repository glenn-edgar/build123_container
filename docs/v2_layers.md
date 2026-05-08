# v2 design note — Layers

**Status:** v2 design sketch. Not implemented in the prototype. Captured here so
the eventual v2 work has a starting point and so prototype decisions don't paint
us into a corner.

## Goal

Allow tagging instances or subassemblies with one or more named **layers**, and
let users toggle each layer's visibility on/off. Visible-layer instances render
in the viewer and (optionally) in exports; hidden ones don't. Layer state is
persisted in the assembly KB so it round-trips through `mk apply` / `mk build`.

This is the AutoCAD / Onshape / Fusion model: layers are a display concern
attached to nodes, with global on/off state plus optional color/style metadata.

## Why this is feasible without a schema rewrite

The existing `knowledge_base` schema already has the two pieces we need:

- A `properties` JSON blob on every row → layer tag goes in there as a free
  field, no DDL change.
- A `label` column with sentinel discipline → a new `LAYER` sentinel for layer
  state rows fits naturally next to `PART`, `INST`, etc.

The whole feature is additive.

## Data model

### 1. Tag at any node in the assembly tree

A `properties.layer` field on `INST` or `SUB` rows. Single string for the
common case, or comma-separated for multi-layer membership.

```
asm_robot.SUB.electronics                  properties.layer="electronics"
asm_robot.SUB.electronics.INST.pcb_main    (inherits "electronics" from parent SUB)
asm_robot.SUB.electronics.INST.shield      properties.layer="electronics,emi"
asm_robot.INST.frame_bolt_1                properties.layer="fasteners"
asm_robot.INST.frame_main                  (no tag → DEFAULT)
```

**Inheritance:** a SUB's layer tag flows down to all descendants unless a
descendant overrides. An untagged node falls back to the literal name `DEFAULT`.
Multi-tag at the leaf adds layers to whatever was inherited rather than
replacing — the leaf's effective layer set is `parent_set ∪ leaf_set`.

### 2. Layer state in `LAYER` sentinel rows

New sentinel label `LAYER`. One row per named layer in the assembly KB.

```
asm_robot.LAYER.electronics   {"visible": true,  "color": "#00aaff", "description": "PCBs and harnesses"}
asm_robot.LAYER.fasteners     {"visible": false}
asm_robot.LAYER.emi            {"visible": true}
asm_robot.LAYER.DEFAULT       {"visible": true}
```

Auto-create on first reference: applying a manifest that tags an INST with a
previously-unknown layer name should also write a `LAYER.<name>` row with
`{"visible": true}`. Removing the last reference is *not* a trigger to delete
the LAYER row — visibility state should persist across re-applies even if the
tag temporarily disappears.

### 3. CLI surface

```
mk layer ls <asm_kb>                 # show layers and current state
mk layer set <asm_kb> <name> on|off  # mutate one layer's visibility
mk layer all <asm_kb> on|off         # bulk
mk layer color <asm_kb> <name> <hex>
```

Layer state is part of the assembly's persistent state; toggling does not
require `mk apply`.

## Where the filter applies — per-command policy

Different commands have different correct behavior:

| Command           | Default behavior                                                      |
| ----------------- | --------------------------------------------------------------------- |
| `mk show`         | Visualization-only filter: hidden parts not in the glTF               |
| `mk export gltf`  | Same as `show` — viewer-bound                                         |
| `mk export stl`   | Same — STL has no layer metadata to preserve                          |
| `mk export step`  | Include all parts; emit XCAF layer metadata so it round-trips         |
| `mk export dxf`   | Include all parts; map layers → DXF layers (ezdxf is layer-native)    |
| `mk mass`         | **Include all parts.** Engineering data shouldn't lie about mass.     |
| `mk bom`          | Include all parts; optionally `--group-by layer`                      |
| `mk build`        | Always all parts. Hidden ≠ unbuilt. Cache is layer-agnostic.          |

A `--respect-layers` flag on `mk mass` and `mk bom` answers the
"what does the user *see* weigh" question for the rare case it's wanted.

## SQL: the visibility filter

For commands that *do* respect layer state, this is the core query (single-tag
case, no SUB inheritance):

```sql
WITH visible AS (
  SELECT name FROM knowledge_base
   WHERE knowledge_base = :asm AND label = 'LAYER'
     AND json_extract(properties, '$.visible') = 1
)
SELECT i.*
  FROM knowledge_base i
 WHERE i.knowledge_base = :asm
   AND i.label = 'INST'
   AND COALESCE(json_extract(i.properties, '$.layer'), 'DEFAULT')
       IN (SELECT name FROM visible);
```

Multi-tag (comma-separated) and SUB inheritance need a recursive CTE that walks
up `path` to find the nearest tagged ancestor and unions the leaf's own tags.
Doable in pure SQLite; ~15 lines.

## Gotchas / decisions to nail down before coding

1. **Bool isn't enough long-term.** "Hidden" vs "ghosted/translucent" vs
   "wireframe-only" are different display states. The `visible` bool should
   become a `state: "show" | "ghost" | "hide"` string when v2 lands. The data
   shape is forwards-compatible — readers that only understand bool should
   treat any non-`"hide"` state as visible.

2. **Layers vs views.** Layer visibility is currently a *global* property of
   the assembly KB. The eventual view system (also a v2 deferral) wants its
   own per-view layer overrides — so the ultimate model is: assembly has
   default state, views carry diffs that override during their export. Don't
   bake "layers are global" into hot paths.

3. **The mate solver does not care about layers.** Hidden parts still mate
   normally; toggling a layer must not silently break solved positions.

4. **STEP roundtrip via XCAF.** OCC's `XCAFDoc_LayerTool` is the right
   integration point — `SetLayer(label, layerName)` per shape during STEP
   export. STL and glTF have no layer concept and will lose the metadata; only
   geometric inclusion/exclusion survives.

5. **DEFAULT is a layer name, not a magic value.** Untagged nodes resolve to
   the layer named `DEFAULT`, which is itself a `LAYER` row that can be
   toggled off (which would hide every untagged node — useful for "show me
   only what I've explicitly tagged").

6. **Auto-create vs explicit declaration.** Auto-creating LAYER rows on first
   tag use is convenient for prototyping but lets typos silently create
   "fasteenrs". A `mk layer declare` step or a strict mode is worth
   considering once the API stabilizes.

7. **Mass and BOM honesty.** Hiding is a display concern. The default for
   engineering commands must be to include all parts. This is the inverse of
   what AutoCAD does for plot scope, and the right default for a CAD database
   that's ground-truth for downstream analysis.

## What this means for the prototype

Nothing changes. The prototype's `INST` rows have `properties` already; adding
a `layer` key in v2 is a no-op for code that doesn't look for it. No prototype
schema or sentinel needs to anticipate this — `LAYER` slots in next to the
existing seven sentinels without colliding.
