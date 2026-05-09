# mk-cad

A database-backed CAD prototype layered on [build123d](https://github.com/gumyr/build123d).

mk-cad treats Python files as the manifest (Infrastructure-as-Code), persists
parts and assemblies as rows in a SQLite knowledge-base, runs build123d
builders to produce geometry, caches BREP, exports STEP/STL/glTF, and serves
the result through a `<model-viewer>`-based browser viewer.

## What it's good at

- **Parametric parts as code.** A part is a builder function plus
  `param`/`joint`/`meta` metadata, all in one Python file. Edit, `mk apply`,
  `mk build`, see the result.
- **Mating via named coordinate frames.** Each part declares joints; the
  assembly references joints across instances. The rigid mate solver
  composes transforms through chains.
- **Co-located simulation contracts.** Electrical specs, gear ratios,
  encoder CPRs, etc. live in `META` rows alongside geometry. Software
  consuming the database gets one source of truth.
- **Self-documenting viewer.** `mk show` emits glTF + a viewer page with
  per-part colors, draggable measurement panels, and 3D joint hotspots.
- **Mixed-format export.** STEP for round-tripping (with XCAF colors and
  layers), glTF for the browser, BREP for the cache, STL for slicing.

## Quick start

```bash
git clone https://github.com/glenn-edgar/build123_container.git
cd build123_container
docker compose build cad             # ~2-3 min on first build
docker compose up -d viewer
docker compose run --rm cad init
docker compose run --rm cad apply /project/manifests/window_test.py
docker compose run --rm cad build asm_window_test
docker compose run --rm cad show asm_window_test
# open http://localhost:32323
```

`docker compose run --rm cad mass asm_window_test` and
`docker compose run --rm cad measure asm_window_test` add engineering data.

## Where to go from here

- [Getting started](getting-started.md) — prerequisites, setup, the first
  manifest you'll write.
- [Architecture](architecture.md) — the KB schema, ltree paths, sentinel
  labels, and how INST + MATE rows resolve at build time.
- [Writing parts](writing-parts.md) — manifest API reference and build123d
  recipe collection.
- [CLI reference](cli.md) — every `mk` subcommand, in detail.
- [Troubleshooting](troubleshooting.md) — known gotchas and what to try
  when things look wrong.
- [v2 layers design](v2_layers.md) — the future layer-tag system, sketched
  but not implemented.

## Status

v1 prototype baselined 2026-05-09. The N20 worm-motor window-controller
test rig (`asm_window_test`) is the first real-world evaluation. See
`HISTORY.md` for the change log and `continue.md` for the active backlog.
