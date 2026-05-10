# v2 evaluation — friction log

**Date**: 2026-05-10. **Model exercised**: `asm_window_test` (the N20
worm-motor window-controller rig — 5 parts, 4 rigid mates, typed META
on the motor) plus `asm_nested` (SUB-scope multi-layer test).

## v3 status (updated 2026-05-10)

Four v3 commits landed in the same session as the evaluation:

| Commit | Items addressed |
|---|---|
| `42c880c` v3 quick wins | #2 typed-META in show, #3 joint dirs in show, #11 measure column alignment, #15 ensure_ascii, #18 no-such-asm vs empty, #21 ezdxf log noise, #23 layer ls trailing whitespace |
| `264b2b2` layout + state CLI | #8 unified output layout, #16 `mk state ls/set/reset` |
| `1cd93bf` mass + show cleanup | #10 mass summary-first, #13 show always announces layer state |
| `e947293` round 2 | #4 URDF short link names, #5 URDF float-noise threshold, #6 `mk asm list`, #12 measure mate-coincidence, #14 `mk part show --json`, #17 (verified clean — no leak), #20 README refresh, plus stale-mesh cleanup on URDF re-export and writing-parts.md API table refresh (covers #22) |

**Closed since the snapshot**: 16 of 23 items.

**Still open** after this v3 pass:
- **#1 BOM rewrite** — explicitly deferred at user direction.
- **#7 Diff apply** — explicitly deferred (~1wk, invasive).
- **#19 STEP geom_hash non-determinism** — v3-deferred per continue.md §9.
- **Surprises A, B, C** — OCC STEP XCAF multi-layer bug (documented in
  step_xcaf.py); container build time (would benefit from a
  compose.dev.yaml with bind-mounted src); `<model-viewer>` CDN
  dependency. None are blocking; all are documented.

That's the whole list. The prototype is in a clean state for the
"build real parts, drive v3+" cycle — pause the polish loop, exercise
the tool on actual work, and let the next round of friction surface.

---

## Round-2 evaluation — author's-path exercise (2026-05-10)

The round-1 evaluation exercised the reader's path: every read-side
command on existing models. Round 2 exercises the **writer's path**:
`mk part new`, edit the manifest, apply, mate into an assembly.

Worked example: scaffolded a new `part_coupler` (drag-link bar with
two pivot holes), edited the manifest with typed META, then wrote a
new `asm_coupler_demo` that mates it onto the lever tip of the
window-test rig. Five-inst assembly with two layer groups
(`fixed_structure`, `mechanism`). Full author's loop took ~5 minutes.

### New friction items

#### R2.1 `mk part new` scaffold predates the typed META schema (~30min)

The generated manifest uses flat `p.meta("density", 7.85)` /
`p.meta("material", "steel")`. A user following the template won't
discover the dotted-namespace pattern (`electrical.voltage_nominal_v`,
`mech.max_load_n`, ...) unless they read `window_test.py`. The
scaffold should include a commented-out example:

```python
# Typed sim-contract fields (optional; namespaced with dots):
# p.meta("electrical.voltage_nominal_v", 12.0)
# p.meta("mech.max_load_n", 25.0)
```

Also worth surfacing: `mass_g_override` for hollow / composite parts
where volume × density over-counts.

#### R2.2 No `mk asm new` (~1h)

Mirrors the v2-evaluation #6 finding (`mk asm list`) but for the
creator-side. To write `asm_coupler_demo.py` I had to copy from
existing fixtures. A scaffold:

```bash
mk asm new coupler_demo --template flat
# writes a starter manifest with:
#   one inst, no mates, comments showing inst()/sub()/mate() syntax
```

Round 1 closed #6 (list) but missed the symmetric `new` gap.

#### R2.3 Rigid mate always rotates child to align z-dirs (~1d? design call)

Most user-visible surprise of round 2. Writing the coupler-to-lever
mate, the lever.tip joint has `z_dir=[1,0,0]` (out in +X); the
coupler.motor_end has `z_dir=[0,1,0]` (up). Rigid mate aligns
joint_a's z to -joint_b's z, so the coupler rotates 90° about Z
relative to its part-local frame.

The mate solver does what the spec says. But users writing a
fastener-into-hole or pin-into-bushing mate often **just want
translation** — keep the part's existing orientation, just put
joint A at joint B. Today's API doesn't express that.

Suggested fix: an optional flag on `mate()`:

```python
a.mate("c", joint_a=..., joint_b=..., mate_type="rigid",
       align="z"            # default — align z-dirs as today
       # align="position"   # only translate joint_a to joint_b origin
       )
```

Real engineering use cases want both. Worth designing properly
rather than tacking a flag on.

#### R2.4 Bbox extents show world-frame, not part-frame (~1h)

`mk measure` reports `coupler extent=8.00×40.00×2.00` after the
coupler is rotated 90° about Z. The author declared `length=40`
along X in part-local — but world-frame Y is now 40. Both numbers
are legitimate but the world-frame extent is what `measure` shows
without labeling. Adding a per-inst `extent (part-local)` line, or
labeling the existing one as "world-frame", would clarify.

#### R2.5 Joint `z_dir` semantics not documented in `mk part show` output (~15min)

`mk part show` lists `z_dir=[0, 1, 0]` per joint after this round's
fix. But what does z_dir *mean*? It's the joint frame's z-axis (the
direction the rigid mate flips against). New users won't know that
from looking at the output. A one-line legend at the top of the
JOINT section ("`z_dir` = joint normal; rigid mates align A's z to
−B's z") would explain it.

### Validated round-1 fixes (positive findings)

- `mk part show` grouped sections + nested META look great on the
  new part. `mech.*` namespace shows cleanly indented.
- `mk part new` → edit → apply → build → export sequence is fast
  (~5 min for a non-trivial part) thanks to the polished error
  messages.
- `mk measure` mate-coincidence sanity caught 4/4 mates as OK on
  the new assembly — good baseline for spotting future regressions.
- URDF short link names land for the new flat assembly:
  `bracket`/`coupler`/`lever`/`motor`/`sheet` instead of the v2-era
  `asm_coupler_demo__INST__bracket` form.
- Layer toggle workflow on the new assembly (3 layers, with
  per-mate visibility) is intuitive. State preservation
  across re-apply works invisibly.
- `mk part export` JSON correctly nests the new `mech.*` keys
  under a `mech` namespace.
- `mk state ls` on a rigid-only assembly correctly identifies
  it as "no revolute or prismatic mates" — no spurious warnings.

### What still hurts but is out-of-scope

- DXF still emits LWPOLYLINEs for every edge (the 396 KB asm_coupler
  _demo.dxf bears this out — most of it is hidden-edge facet
  geometry from the motor body). Real LINE/ARC entities would
  shrink this significantly. Carried forward from the v3 round-1
  open list (DXF polish, ~1d).
- The OCC STEP XCAF multi-shape-layer bug still drops layer info
  during STEP export. Same documented limitation.

### Round-2 priorities

If a v3 round 3 cycle starts:
1. **R2.3 align option on rigid mates** — biggest user-visible gap;
   needs design discussion before coding.
2. **R2.1 + R2.2 scaffold updates** — quick (~1h combined). Adds
   `mk asm new` and updates `mk part new` template to mention
   typed META.
3. **R2.4 part-frame bbox in measure** — minor; can wait.
4. **R2.5 z_dir legend** — trivial doc tweak.

The original entries below are preserved verbatim as a snapshot of what
was found at evaluation time.

---


Every `mk` command was run end-to-end against these two assemblies on
a freshly-rebuilt container. The list below is what hurt, ranked by
impact. Each entry has a rough fix-size estimate; **none of these
were fixed during evaluation** per the §4 protocol (write it down,
don't patch as you go).

The goal of this list is to feed v3 prioritization. Some entries are
real bugs, some are ergonomics, some are missing capabilities.

---

## High impact

### 1. `mk bom` output is too thin to be a real BOM (~1d)

Current output is just `part_kb` + `qty`. Engineering review needs
at minimum: `part_number`, `vendor`, `description`, per-line mass,
total mass. The data already lives in META rows — the BOM command
just doesn't join against it. Spec-compliant BOMs typically also
have column headers in the right order for an MRP / ERP import.

**Repro**: `mk bom asm_window_test` — 5 lines, no useful identifiers
beyond `part_n20_worm_motor_16rpm` (the kb_name, not the vendor's
part number).

### 2. `mk part show` doesn't honor the typed META namespaces (~2h)

After Phase B.3 introduced dotted META keys, `mk part show` still
displays them flat:

```
META.electrical.voltage_max_v = 12.0
META.electrical.voltage_min_v = 3.0
META.electrical.voltage_nominal_v = 12.0
META.encoder.present = True
...
META._TODO_electrical_back_emf_v_per_krpm = None
META._TODO_electrical_resistance_ohm = None
...
```

Real values and `_TODO_` placeholders interleave alphabetically;
namespaces don't group visually. The new `mk part export <kb>`
groups them correctly via `meta_tree.py`; `show` should reuse the
same builder for a tree-formatted display, and visually segregate
`_TODO_*` placeholders below the real schema.

### 3. `mk part show` omits joint directions (~30min)

Each JOINT row stores `origin`, optionally `z_dir`, optionally
`x_dir`. `mk part show` prints only `origin`. For a motor with
shafts on +Y and -Y, knowing the direction is essential context;
otherwise the joint name has to encode it (`shaft_a_tip` vs
`shaft_b_tip` — which is +Y?).

### 4. URDF link names are unnecessarily verbose (~2h)

`asm_window_test__INST__bracket` for every link. The full
ltree-path sanitization disambiguates across SUBs, but flat
assemblies don't need it. Add `--short-names` (or default short
when no SUBs exist) to emit just `bracket` / `motor` / `lever`.
Currently the names make hand-editing URDF and reading sim logs
unpleasant.

### 5. URDF inertia tensors have numerical-noise off-diagonals (~1h)

```
<inertia ixx="9.20769755e-08" ixy="1.79056769e-24" ixz="1.10418341e-24"
         iyy="6.44100183e-08" iyz="5.48361356e-24" izz="4.45295808e-08"/>
```

`ixy` etc. are float-math zero from the OCP integration. URDF
consumers ignore them, but the file is noisy. Threshold values
< `1e-15` to literal `0` before emission. Same for CoM xyz
components.

### 6. No `mk asm list` (~30min)

`mk part list` enumerates parts. `mk asm` only has `tree`. A user
discovering the project has no way to ask "what assemblies are in
this DB?" without poking SQL. Add `mk asm list` (mirror of part
list).

### 7. Apply-truncates-everything invalidates downstream artifacts (~1wk if pursued)

Every `mk apply` truncates the affected KB and rewrites — which
also nukes `geom_hash` on INST rows. The user-visible effect:

```
$ mk apply window_test.py    # tweak a param
$ mk export asm_window_test step
  ERR: asm_window_test.INST.bracket: missing geom_hash or ref_kb
       (run `mk build asm_window_test` first)
```

For prototyping this is fine. For an iterative "tweak a param,
re-render" loop it's friction. v2-deferred diff-based apply
(`continue.md` §5b) would address this; cost is non-trivial
because the hash-cascade is downstream.

### 8. STEP/STL/BREP output goes flat, URDF/show go in a subdir (~1h)

```
outputs/asm_window_test.step
outputs/asm_window_test.stl
outputs/asm_window_test.brep
outputs/asm_window_test.dxf
outputs/asm_window_test/         ← URDF + meshes/, show's gltf + index.html
```

Inconsistent. URDF needs a subdir because it has a `meshes/`
sidecar; show needs one for the multi-file viewer assets; STL+STEP
are single files. Unify: put everything under `outputs/<asm>/`
with predictable filenames. One-time output-path migration.

---

## Medium impact

### 9. OCC + ezdxf log noise pollutes every command (~1h)

Every `mk` command (even `mk mass`) prints:

```
WARNING ezdxf: Cannot create cache home directory: '/.cache/ezdxf', cache files will not be saved.
```

Because build123d imports ezdxf eagerly, this fires on import-time
regardless of whether the user touches DXF. Also OCC's STEP writer
prints multi-line ANSI-colored "Statistics on Transfer" blocks. All
of this noise is fixable with stderr suppression around the noisy
imports/calls.

### 10. `mk mass` mixes per-inst details with the summary (~30min)

Five per-inst lines (V, ρ, mass, CoM) followed by the assembly
total + inertia tensor + principal axes. The user asking "how
heavy is this?" has to scroll past the per-inst lines to find
`total mass:`. Move per-inst behind `--verbose` and lead with the
summary; or `-q` for summary-only. Per-inst is useful when
debugging a mass-override mismatch but not the common case.

### 11. `mk measure` joint-name column alignment is off (~15min)

```
  lbracket.foot_bottom     origin=...    ← double-space
  lever.shaft_socket    origin=...        ← single-space
```

Compute column widths from the longest joint name, not the inst
name. Cosmetic but jarring.

### 12. `mk measure` doesn't sanity-check mates (~1h)

For every rigid MATE, the two joint origins should be coincident
in world (distance 0). For revolute/prismatic, they should
coincide at DOF=0. Surface this as a default check —
"all mates closed within 1e-6 mm" — and warn if any mate has
non-zero gap. Catches "I changed a param and the mate doesn't
quite close" silently-broken builds.

### 13. `mk show` doesn't volunteer layer state in stdout (~15min)

If 3 of 5 insts are on a hidden layer, the user opening the
viewer sees a sparse scene and might think the build broke. `mk
show` currently logs only the filter count when something is
filtered; should always log the per-layer breakdown so the user
knows what's in the scene.

### 14. `mk part show` lacks `--json` (~15min)

`mk part export <kb>` exists (Phase B.3) and emits the structured
JSON. But `mk part show` is the discoverable "tell me about this
part" command. Add `--json` to `mk part show` as an alias to
`mk part export <kb>` so users don't need to know two commands
mean similar things.

### 15. `mk part export` JSON emits `Φ` instead of literal Φ (~5min)

`ensure_ascii=False` on the `json.dumps` call. Trivial; tested
in the controller-under-test path where they'd see this when
loading the sim contract.

### 16. No `mk state` CLI for joint pose-setting (~2h)

State injection (B.2.a) reads `outputs/<asm>/state.json` — but
users have to hand-edit JSON to set a mate's DOF. Add:
- `mk state ls <asm>` — show current state.json contents + each
  mate's default and limits
- `mk state set <asm> <mate> <value>` — write into state.json
- `mk state reset <asm>` — remove state.json so defaults apply

Then `mk build && mk show` cycles for pose-setting feel natural.

---

## Low impact

### 17. `mk apply` is verbose with `print()` from vendored KB infra

The vendored `Construct_KB.add_header_node` does
`print("path", path)`; our `kb.py` redirects stdout but only for
some calls. On a fresh apply, hundreds of "path ..." lines
should go away — we already suppress them via `redirect_stdout`.
Worth verifying nothing leaks.

### 18. "no INST rows in <kb>" conflates "no such assembly" with "applied but empty"

`mk mass typo_asm` says "no INST rows" — but `typo_asm` doesn't
exist as a KB at all. Should distinguish:
- "no such assembly: typo_asm" (no info row)
- "asm_x has no INST rows" (info row exists, body is empty)
Same fix in `mk build`, `mk bom`, `mk export`.

### 19. STEP geometry hash is non-deterministic

Mentioned in continue.md §9. `sha256(STEP-bytes)` picks up OCC's
timestamp. Cosmetic for the prototype but blocks v2 hash-cascade
caching plans.

### 20. README status is stale

Says "v1 baselined". Reality is closer to "v2 effectively
complete, B.2.b deferred, evaluation in flight". One-paragraph
update. Pointers to continue.md §10-14 for the new features
(URDF, typed META, layers, STEP+XCAF, DXF).

### 21. ezdxf "INFO ezdxf: did not write header var $INTERFEREOBJVS" on DXF write

Harmless library logging that escaped to stderr. Filter or
suppress.

### 22. `mate` names still start with `a_/b_/c_/d_`

Vestige of pre-Phase-A naming discipline (alphabetical order to
satisfy the old solver). Topo-sort (Phase A) removed the need but
the names persist in fixtures. Renaming is cosmetic; users
writing new manifests don't need the prefix. Worth a one-line
note in `writing-parts.md`.

### 23. `mk layer ls` has trailing whitespace on every row

f-string padding bug — empty DESCRIPTION column ends with a
trailing space. Cosmetic.

---

## Surprises (worth recording, no fix yet)

### A. OCC's STEP XCAF writer drops multi-shape-per-layer info

Discovered during C.4 (Phase C.3+C.4 commit). Single-tag distinct-
layer shapes survive write/read; multi-shape-same-layer collapses
to one shape in the STEP file. Documented in `src/mk/step_xcaf.py`.
Upstream OCCT issue; can be worked around by post-processing the
STEP text or via newer OCC. Not blocking for v2 since Phase D's DXF
output goes through ezdxf directly, but a real user wanting layer-
preserving STEP roundtrip will hit this.

### B. Container build is ~1 minute per code change

`docker compose build cad` rebuilds the `pip install` layer every
time `src/` changes. Bind-mounting `src/` would skip the rebuild
for interactive iteration. Worth a `compose.dev.yaml` for the
prototyping mode (and the current image for "ship" mode).

### C. The viewer's `<model-viewer>` CDN dependency

`mk show` emits an `index.html` that pulls
`model-viewer.min.js` from `ajax.googleapis.com`. First load
needs internet. Air-gapped deployments would need to vendor the
JS locally. Documented in continue.md §3.

---

## What was NOT painful

For balance — things that worked smoothly:

- `mk apply` → `mk build` → `mk export <fmt>` end-to-end on a real 5-part
  assembly with mated parts. The mate solver placed everything correctly;
  STEP, STL, URDF, and DXF all produced sensible output.
- The typed META schema (Phase B.3) genuinely makes the motor's data
  feel like a real datasheet record. `mk part export` JSON is exactly
  what a controller-under-test wants.
- Phase C's layer toggle workflow (`mk layer set foo off` → `mk show`
  → toggle back on) is fast and intuitive. The state-preservation
  across re-apply is invisible but correct, which is the right
  invisible-correctness behaviour.
- URDF mass + inertia values match hand-calculation for known
  geometries (the hinge leaf box matched analytically).
- 150 host tests run in 110 ms. Test feedback is immediate.

---

## Priorities for v3

If a v3 cycle starts from this list, the natural order is:

1. **Quick wins** (#15, #11, #21, #23, #18) — ~4 hours total. CLI polish.
2. **BOM rewrite** (#1) — 1 day. Most-asked-for feature gap.
3. **Output-layout unification** (#8) + **state-CLI** (#16) — 1 day combined.
4. **Mass / show summary cleanup** (#10, #13) — 2 hours.
5. **Diff apply** (#7) — ~1 week. Biggest impact for iterative workflow but most invasive.

Items #19, #20, #22, A, B, C are documentation / cleanup that
shouldn't block v3 feature work but should ride along.
