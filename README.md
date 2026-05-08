# mk-cad

build123d + ltree CAD prototype. See `continue.md` for the spec.

Licensed under the [Mozilla Public License 2.0](LICENSE).

## Status

Phases 1–4, 6 done: container + DB, manifest apply, builder + STEP export, mass
properties + BOM, rigid mate solver. Verified end-to-end against the fixtures in
`tests/fixtures/`. Phase 5 (yacv viewer) is the only spec phase remaining.

## Units

- **Lengths**: millimetres (build123d / OCC default).
- **Volumes**: mm³.
- **Densities** (`META.density.value`): grams per cm³ (g/cm³). Steel ≈ 7.85.
- **Masses**: grams. `mass(g) = volume(mm³) × density(g/cm³) ÷ 1000`.
- **Inertia tensor**: g·mm² (mass-weighted).

A `Box(10, 10, 10)` with density 1 g/cm³ has mass `1000 × 1 / 1000 = 1.000 g` and
diagonal inertia `m·a² / 6 = 16.667 g·mm²` — used as the Phase 4 sanity test
(`project/manifests/box_unit.py`).

## Local development (no Docker)

```bash
pip install -e .
mk init --db /tmp/test.db
```

Expected output:
```
DB ready at /tmp/test.db
  tables: geometry, knowledge_base, knowledge_base_info, knowledge_base_link, knowledge_base_link_mount, sqlite_sequence
  ltree: ok
```

## Container

```bash
docker compose build cad
docker compose run --rm cad init

# Use a different host directory (e.g., a project elsewhere on disk):
PROJECT_DIR=/home/me/cad/robot1 docker compose run --rm cad init
```

`PROJECT_DIR` is the host path that gets bind-mounted to `/project` inside
both services. Defaults to `./project` next to this repo.
