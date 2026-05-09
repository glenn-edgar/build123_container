# mk-cad

A database-backed CAD prototype layered on
[build123d](https://github.com/gumyr/build123d). Python manifests as the
source of truth; SQLite + ltree as the derived state; build123d as the
geometry engine; `<model-viewer>` for the browser.

Licensed under the [Mozilla Public License 2.0](LICENSE).

## Status

**v1 baselined** as of 2026-05-09. All six rev-2 phases verified end-to-end.
First real-world evaluation scenario — an N20 worm-motor window-controller
test rig — lives at `project/manifests/window_test.py`. Container,
viewer, mate-chain composition, per-part colors, `mk part new` scaffold,
and `mk measure` all green.

The active backlog is in `continue.md` §9. Phase-by-phase change log is in
`HISTORY.md`.

## Documentation

Docs are written under `docs/` and serve as a [mkdocs](https://www.mkdocs.org/)
site:

```bash
pip install mkdocs mkdocs-material pymdown-extensions
mkdocs serve     # local preview at http://127.0.0.1:8000
mkdocs build     # static site under ./site/
```

If you'd rather just read the markdown:

- [docs/index.md](docs/index.md) — landing
- [docs/getting-started.md](docs/getting-started.md) — five minutes to a model
- [docs/architecture.md](docs/architecture.md) — KB schema, namespace, mate solving
- [docs/writing-parts.md](docs/writing-parts.md) — manifest API + build123d recipes
- [docs/cli.md](docs/cli.md) — every `mk` subcommand
- [docs/troubleshooting.md](docs/troubleshooting.md) — known gotchas
- [docs/v2_layers.md](docs/v2_layers.md) — design sketch for v2 layer support

## Quick start

```bash
git clone https://github.com/glenn-edgar/build123_container.git
cd build123_container
docker compose build cad
docker compose up -d viewer
docker compose run --rm cad init
docker compose run --rm cad apply /project/manifests/window_test.py
docker compose run --rm cad build asm_window_test
docker compose run --rm cad show asm_window_test
# open http://localhost:32323
```

Then explore:

```bash
docker compose run --rm cad mass asm_window_test
docker compose run --rm cad bom asm_window_test
docker compose run --rm cad measure asm_window_test
docker compose run --rm cad export asm_window_test step
```

## Units

- **Lengths**: millimetres (build123d / OCC default)
- **Volumes**: mm³
- **Densities** (`META.density.value`): g/cm³. Steel ≈ 7.85.
- **Masses**: grams. `mass(g) = volume(mm³) × density(g/cm³) ÷ 1000`.
- **Inertia tensor**: g·mm² (mass-weighted)

A `Box(10, 10, 10)` with density 1 g/cm³ has mass `1.000 g` and diagonal
inertia `m·a² / 6 = 16.667 g·mm²`. That's the Phase 4 sanity test
(`project/manifests/box_unit.py`).

## Repository layout

```
build123_container/
├── continue.md              spec / handoff (rev 3)
├── HISTORY.md               phase-by-phase change log
├── README.md                this file
├── LICENSE                  MPL 2.0
├── NOTICE                   third-party attribution
├── mkdocs.yml               docs site config
├── Dockerfile               thin layer over upstream build123d image
├── compose.yaml             cad + viewer services
├── pyproject.toml
├── docs/                    documentation site source
├── vendor/                  ltree.so source + KB infrastructure subset
├── src/mk/                  the mk-cad CLI
├── tests/fixtures/          example manifests
└── project/                 bind-mounted to /project in container
    ├── manifests/           your .py manifests
    ├── db/                  project.db (git-ignored)
    ├── inputs/              imported STEP/STL
    └── outputs/             exports + viewer index.html (git-ignored)
```

## Developing without Docker

mk-cad's CLI is pure Python and importable on the host *if* your host has
build123d, OCP, and the SQLite ltree extension available — but those are
why we use Docker in the first place. For docs editing, no container
needed; just `mkdocs serve`.

## Contributing

Manifests live under `project/manifests/`. Add a new part with:

```bash
docker compose run --rm cad part new my_widget --template plate_with_hole
```

Edit, `mk apply`, `mk part show`, `mk build`, `mk show`. See
[docs/writing-parts.md](docs/writing-parts.md) for the API.

## Container topology

`compose.yaml` defines two services using the same locally-built image:

- `cad` — entrypoint is `mk`. Runs the CLI commands.
- `viewer` — entrypoint is `python -m http.server 32323 --directory
  /project/outputs`. Serves the glTF + index.html that `mk show` writes.

Bring up the viewer once with `docker compose up -d viewer`; run `cad`
commands ad-hoc with `docker compose run --rm cad <cmd>`. The host
directory bind-mounted to `/project` is configurable via `PROJECT_DIR`:

```bash
PROJECT_DIR=/home/me/cad/robot1 docker compose run --rm cad init
```
