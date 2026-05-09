# Getting started

Five minutes to a rendering 3D model in your browser, end-to-end.

## Prerequisites

- **Docker** (Desktop on Windows/Mac, or `docker` + `docker compose` on Linux).
- **Internet access on first run** — the upstream `ghcr.io/derhuerst/build123d`
  image is ~2.6 GB and the viewer's `<model-viewer>` JS loads from a CDN.
- **An aarch64 host?** The upstream image is amd64-only; it'll run via qemu
  emulation. First build takes ~2 min for the apt-get layer; subsequent
  rebuilds with cached layers are seconds.

That's it. mk-cad runs entirely inside containers — nothing is installed on
your host except Docker.

## Bring it up

```bash
git clone https://github.com/glenn-edgar/build123_container.git
cd build123_container
docker compose build cad
docker compose up -d viewer
```

The `viewer` service is a tiny `python -m http.server` exposing
`/project/outputs/` on `localhost:32323`. Leave it running.

## Initialize the project DB

```bash
docker compose run --rm cad init
```

You'll see:

```
DB ready at /project/db/project.db
  tables: geometry, knowledge_base, knowledge_base_info, knowledge_base_link, knowledge_base_link_mount, sqlite_sequence
  ltree: ok
```

If `ltree: ok` is missing, the SQLite ltree extension didn't load — see
[Troubleshooting](troubleshooting.md).

## Apply a manifest, build, view

```bash
docker compose run --rm cad apply /project/manifests/window_test.py
docker compose run --rm cad build asm_window_test
docker compose run --rm cad show asm_window_test
```

Then open `http://localhost:32323`. You should see a coloured assembly:
green sheet, white motor mount, gunmetal motor, orange lever, red L-bracket.
Drag the panels to rearrange; hover the orange dots to see joint labels.

## Your first part

Scaffold a starter manifest:

```bash
docker compose run --rm cad part new my_first_part --template plate_with_hole
```

That writes `/project/manifests/my_first_part.py` (which you can find at
`./project/manifests/` on your host, since the directory is bind-mounted).
Edit the params, the `build_my_first_part` function, and any joints. Then:

```bash
docker compose run --rm cad apply /project/manifests/my_first_part.py
docker compose run --rm cad part show part_my_first_part
```

`mk part show` prints the captured params, joints, meta, and a line count
for the builder source.

## Useful commands

| Command | What it does |
|---|---|
| `mk apply <file>` | Import a manifest; persist parts/assemblies into the DB. Idempotent. |
| `mk build <asm>` | Resolve mates, run builders, cache BREP, write `geom_hash`. |
| `mk show <asm>` | Write glTF + index.html into outputs/ for the viewer. |
| `mk export <asm> <fmt>` | `step`, `stl`, or `brep` to outputs/. |
| `mk mass <asm>` | Total mass, CoM, inertia tensor. |
| `mk bom <asm>` | Flat parts list grouped by `ref_kb`. |
| `mk measure <asm>` | Bounding boxes, joint world-coords, optional `--distance` between two joints. |
| `mk part list` | All part KBs in the DB. |
| `mk part new <name>` | Scaffold a manifest from a template. |
| `mk asm tree <asm>` | Render the assembly hierarchy. |

See [CLI reference](cli.md) for full details.

## Project layout (host side)

```
project/
├── manifests/      ← your .py manifests (git-tracked)
├── db/             ← project.db (git-ignored; created by `mk init`)
├── inputs/         ← imported STEP/STL files
└── outputs/        ← exports + viewer index.html (git-ignored)
```

The whole `project/` directory is bind-mounted into the container at
`/project`. Edit on host, see changes inside the container.

## What next

You've got the loop. Read [Writing parts](writing-parts.md) to learn the
manifest API in detail, [Architecture](architecture.md) for what's
happening underneath, or [Troubleshooting](troubleshooting.md) when
something doesn't render the way you expected.
