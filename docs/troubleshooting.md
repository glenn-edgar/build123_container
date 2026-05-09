# Troubleshooting

Real failures we've hit in this project, in rough order of how often they
come up.

## Container builds fail or run extremely slowly

The upstream `ghcr.io/derhuerst/build123d` image is **amd64-only**.
On aarch64 hosts (Apple Silicon, Snapdragon WSL, Raspberry Pi), the image
runs under qemu user-mode emulation. The first build's `apt-get` and
`pip install` layers each take 30–60 s under qemu; subsequent layer-cached
rebuilds are seconds.

If the build hangs or takes minutes:

- Is your host aarch64? `uname -m` on the host. If yes, qemu emulation is
  expected.
- Is qemu binfmt registered? `ls /proc/sys/fs/binfmt_misc/` should show
  `x86_64` if Docker Desktop's binfmt is set up. Without it, amd64 binaries
  can't run.

**Don't try to fix this with `docker run --privileged
multiarch/qemu-user-static --reset -p yes`** on aarch64 — that registers a
`qemu-aarch64` handler that traps the host's own `/bin/bash` and crashes
WSL. Docker Desktop's pre-existing handlers are sufficient.

## `mk init` says `ltree: failed`

Means the SQLite ltree extension didn't load. Two common causes:

- **Wrong arch**. `vendor/ltree.so` in this repo is the host-side
  (aarch64) build. The container compiles its own amd64 copy at build
  time via `vendor/ltree_sqlite.c` (see Dockerfile). If you've modified
  the build, check the Dockerfile's `gcc` step.
- **Path mismatch**. The default container path is
  `/usr/local/lib/ltree.so`. Override with `MK_LTREE_PATH=...` if needed
  (see `src/mk/db.py::_resolve_ltree_path`).

When debugging dlopen errors, note that SQLite's "no such file or
directory" message is misleading — Linux `dlopen` returns this when the
file *exists but is the wrong arch*, not just when it's missing.

## `mk show` produces a glTF with `"materials": []`

You set `META.color` but the viewer renders the model in default beige.
Three independent things need to be right (we hit all three during the N20
evaluation):

1. **Use `Compound(children=[...])`, not `Compound([...])`.** The
   positional list form leaves `compound.children` empty, so build123d's
   `export_gltf` walks zero children and emits no materials.
2. **Set `.color` *after* `loc * shape`, not before.** Location-multiplied
   shapes don't inherit the `.color` attribute.
3. **`Color()` rejects hex strings.** It accepts named colors and RGB
   floats; hex like `"#ff9028"` raises `ValueError: Unknown color name`.
   `mk show`'s `_parse_color` helper handles all three input forms.

If you write your own export path, replicate the order: load BREP →
apply location → set color → append to `Compound(children=...)` list.

## `'ShapeList' object has no attribute 'wrapped'`

Raised from `export_step` or `export_stl`, but the actual cause is in your
builder. build123d's `+` (boolean union) returns a `ShapeList` of disjoint
solids when the constituents don't overlap or touch. The exporters expect a
`Compound`/`Solid` and crash on the wrapper.

Check whether your builder positions every part of the geometry to *touch
or overlap*. The classic case: a `Cylinder(...)` with default `+Z` axis,
positioned at `Pos(x, y, 0)`, when you actually meant the cylinder to
extend along Y or X. Because the cylinder's own axis didn't get rotated,
it floats in space along Z instead of connecting to the gearbox/block you
expected. Add `Rotation(...)` before `Cylinder` to fix the axis.

## Mate chain produces wrong positions

Was a real bug in early v1. If the symptom is that *everything except the
first inst* is at strange world coordinates (looks like its absolute
position equals its joint-b-relative offset), you're running an older
version of `mate.py` that didn't compose chains.

Fix is committed: `mate.solve_assembly` tracks resolved transforms in a
per-call dict and composes `T_a_world = T_b_world ∘ T_a_rel_to_b`.
Process mates in path order; name them `a_/b_/c_/...` so dependency order
holds.

If chains are still wrong: check that the joint_b inst is named such that
its mate sorts *before* the mate that has it as joint_b.

## Lever rotates into something it shouldn't

The mate solver doesn't model collisions — it just places joints
coincident. If your assembly has a part in the lever's rotational path
(like the L-bracket too close to the swing), the rendered scene looks
fine but the real device wouldn't actually rotate.

For visual sanity-checking, run `mk measure <asm>` and look at the joint
world coords vs the swept arc radius. The lever's tip sweeps a circle of
its `outer_r` around the shaft joint; anything inside that radius is in
the path.

## Mass numbers are way off

`mk mass` computes `volume × density / 1000`. For hollow assemblies (a
real motor is mostly air around windings and magnets), this over-counts
by a factor of 4–5×. The N20 motor in `asm_window_test` measures 43 g via
this calc, where the actual datasheet value is ~10 g.

For now this is a documented limitation. v1.x backlog has
`META.mass_g_override` planned — when present it'll supersede the
volume×density calc for that part.

## `mk build` fails with `Unknown Compound type, color not set`

A warning from build123d's `_create_xde` when a Compound contains
unrecognized children. Usually harmless. If the export still produces a
valid file, ignore. If it's blocking, simplify the builder — return a
single `Solid` or `Part` instead of a multi-Compound structure.

## I get a different `geom_hash` on each rebuild even though nothing changed

Known v1.x issue: `sha256(STEP-bytes)` picks up timestamps in
OpenCascade's STEP serializer. Cosmetic for prototype use (the cache still
matches when you actually build the same shape twice in one process). It
blocks the v2 hash-cascade caching plan; on the backlog.

## SUB-nested assemblies break at `mk build`

The mate solver's joint-path regex matches only the flat form
`<asm>.INST.<inst>.JOINT.<joint>`. Nested forms like
`<asm>.SUB.<sub>.INST.<inst>.JOINT.<joint>` (which the `kb_asm.sub()`
context manager generates) don't parse, raising `ValueError`.

`mk apply` and `mk asm tree` work correctly for SUB scopes; only
mate-solving breaks. `tests/fixtures/nested_asm.py` is the
not-actually-buildable-yet fixture that demonstrates the limit.

Fix is in v1.x backlog — small regex update plus inst-lookup-by-path.

## I can't see multiple assemblies at once in the viewer

Each `mk show <asm>` overwrites `outputs/<asm>.gltf` AND the single
`outputs/index.html`. The viewer only renders whichever assembly was
shown most recently. v1.x backlog: partition by subdirectory so each
assembly gets its own URL.

Workaround: copy the index.html under a different name after each
`mk show`.

## Where to ask for more help

The repo's `HISTORY.md` records every bug fixed and why. `continue.md`
§9 lists the open backlog. Memory under
`~/.claude/projects/-home-gedgar-build123-container/memory/` includes a
`feedback_build123d_gotchas.md` with the build123d-specific pitfalls
written up in detail.
