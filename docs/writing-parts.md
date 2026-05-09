# Writing parts — cheat sheet

How to write a manifest that mk-cad understands. Pairs with the working
fixtures under `tests/fixtures/` — copy from those liberally.

## The shape of a manifest

Every manifest is a regular Python `.py` file. Run it with `mk apply <file>`.
Inside, you open a connection, declare one or more parts and assemblies via
context managers, and the underlying `KnowledgeBaseManager` upserts rows for
you.

```python
from mk.kb import connect, kb_part, kb_asm

with connect():
    with kb_part("part_my_widget", description="a widget") as p:
        p.param("d", 6, type="float")
        p.builder(build_widget)
```

Each `kb_part(name)` block **truncates and rewrites** the part's KB rows. Apply
is idempotent — rerunning it leaves the same end state.

## PartBuilder methods

| Method | Stores into | Notes |
|---|---|---|
| `p.param(name, value, type="float")` | `PARAM` row | default value used when no INST override is set |
| `p.joint(name, *, origin, z_dir=[0,0,1], x_dir=None)` | `JOINT` row | named coordinate frame; mate edges reference these |
| `p.meta(key, value)` | `META` row | `density` (g/cm³), `material`, `color`, etc. |
| `p.builder(fn)` | `PART.body` row | the function gets serialized via `inspect.getsource` |

The builder function takes a single `dict` of resolved params and returns a
build123d shape:

```python
def build_widget(p):
    from build123d import Box  # imports go inside; the function is captured as text
    return Box(p["d"], p["d"], p["d"])
```

**Always import build123d inside the function**, not at module top. The
function body is captured by `inspect.getsource` and re-executed in a clean
namespace at build time — outer imports won't follow it.

## AssemblyBuilder methods

| Method | Stores into | Notes |
|---|---|---|
| `a.inst(name, *, ref_kb, params_override=None, location=None)` | `INST` row | place a part instance |
| `a.sub(name, description="")` | `SUB` row, returns nested AsmBuilder | use as `with a.sub("frame") as s:` |
| `a.mate(name, *, joint_a, joint_b, mate_type="rigid", params=None)` | `MATE` row | rigid mate solver runs at `mk build` time |

Joint paths in `mate(...)` use the form
`<asm>.INST.<inst_name>.JOINT.<joint_name>` (or with `.SUB.<sub>` segments
for nested instances — but **note**: as of v1, the rigid mate solver only
parses the flat form; SUB-nested mate paths are a v1.x backlog item per
`continue.md` §9).

## build123d primitives that map to common features

The builder gets a full `build123d` namespace; here are the patterns you'll
reach for most. See https://build123d.readthedocs.io for the complete API.

### Solids

```python
Box(width, depth, height)           # centered at origin by default
Cylinder(radius, height)            # axis along Z by default, centered
Sphere(radius)
Cone(bottom_radius, top_radius, height)
Torus(major_radius, minor_radius)
```

### Positioning / rotation

```python
Pos(x, y, z) * shape                # translate
Rotation(rx, ry, rz) * shape        # Euler angles in degrees
Plane.XY.location * shape           # named planes: XY, XZ, YZ, top, bottom, etc.
```

### CSG (boolean ops)

```python
body - tool          # subtract (drill a hole)
body + tool          # union
body & tool          # intersection
body.cut(tool)       # explicit method form of subtract
```

### Common composite recipes

**Block with a hole**
```python
def build_plate(p):
    from build123d import Box, Cylinder
    plate = Box(p["w"], p["d"], p["t"])
    hole = Cylinder(p["hole_d"]/2, p["t"] * 4)   # tall enough to clear
    return plate - hole
```

**Cylinder oriented along Y instead of Z** (default axis is Z)
```python
def build_pin(p):
    from build123d import Cylinder, Rotation
    return Rotation(-90, 0, 0) * Cylinder(p["d"]/2, p["len"])
```

**Filleted edges**
```python
def build_filleted_block(p):
    from build123d import Box, fillet
    body = Box(p["w"], p["d"], p["h"])
    return fillet(body.edges(), radius=p["fillet_r"])
```

**Chamfered edges**
```python
def build_chamfered_block(p):
    from build123d import Box, chamfer
    body = Box(p["w"], p["d"], p["h"])
    return chamfer(body.edges().filter_by(Axis.Z), length=p["c"])
```

**Revolved profile**
```python
def build_pulley(p):
    from build123d import BuildSketch, BuildPart, Revolve, make_face, Polyline
    with BuildPart() as part:
        with BuildSketch() as profile:
            # ... draw 2D profile ...
            pass
        Revolve(axis=Axis.Z)
    return part.part
```

**Multiple holes via `Locations`**
```python
def build_pcb(p):
    from build123d import BuildPart, Box, Locations, Hole
    with BuildPart() as part:
        Box(p["w"], p["d"], p["t"])
        with Locations((p["w"]/2 - 5, p["d"]/2 - 5, 0),
                       (-p["w"]/2 + 5, -p["d"]/2 + 5, 0)):
            Hole(radius=p["hole_d"]/2)
    return part.part
```

## Joints — the mating contract

Joints are coordinate frames you attach to a part to define how it can mate
with others. The rigid mate solver puts joint A's origin coincident with
joint B's origin, with z-axes opposing (so surfaces touch, not overlap).

```python
p.joint("hole_top",   origin=[0, -15, 0], z_dir=[0,  1, 0])  # +z points OUT of the hole
p.joint("thread_tip", origin=[0,   0, 0], z_dir=[0,  0, -1]) # +z points OUT of the bolt's tip
```

When mated rigid, this puts the bolt's `thread_tip` at world coords
`(0, -15, 0)` (the bracket's `hole_top`) with the bolt extending outward
along the bracket's `+y` direction.

Convention: **make every joint's `z_dir` point OUT of the surface it
represents** (out of the hole opening, out of the threaded end). The mate
solver flips one to align with the other's negative direction so that
surfaces meet.

## Quick start

```bash
mk part new my_bracket --template plate_with_hole
mk apply /project/manifests/my_bracket.py
mk part show part_my_bracket

# in an assembly:
mk build asm_thing
mk mass asm_thing
mk measure asm_thing
mk show asm_thing                    # browser at :32323
```

## Patterns to copy

- `tests/fixtures/single_part.py` — minimal part with all label kinds
- `tests/fixtures/two_part_asm.py` — bolt + bracket-with-hole, one mate; demonstrates CSG
- `tests/fixtures/nested_asm.py` — SUB-scoped assembly (apply works; mating SUB-nested is a v1.x backlog item)
- `project/manifests/box_unit.py` — Phase 4 sanity fixture (Box(10,10,10) ρ=1 → 1.0 g)
