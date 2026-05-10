# SPDX-License-Identifier: MPL-2.0
"""mk part list / mk part show / mk part new."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mk.db import DEFAULT_DB_PATH, open_db

DEFAULT_MANIFESTS_DIR = "/project/manifests"


def add_parser(subparsers) -> None:
    part = subparsers.add_parser("part", help="Part inspection / scaffolding.")
    part_sub = part.add_subparsers(dest="part_cmd", required=True)

    lst = part_sub.add_parser("list", help="List part KBs.")
    lst.add_argument("--prefix", default="part_", help="kb_name prefix filter")
    lst.add_argument("--db", default=DEFAULT_DB_PATH)
    lst.set_defaults(func=run_list)

    show = part_sub.add_parser("show", help="Show a part KB's contents.")
    show.add_argument("kb_name")
    show.add_argument("--db", default=DEFAULT_DB_PATH)
    show.set_defaults(func=run_show)

    new = part_sub.add_parser(
        "new", help="Scaffold a starter manifest .py for a new part.",
    )
    new.add_argument("name", help="part kb_name (will be prefixed with 'part_' if missing)")
    new.add_argument(
        "--outdir", default=DEFAULT_MANIFESTS_DIR,
        help="directory to write the manifest into",
    )
    new.add_argument(
        "--template", default="block",
        choices=["block", "cylinder", "plate_with_hole", "blank"],
        help="starter template",
    )
    new.add_argument(
        "--force", action="store_true",
        help="overwrite an existing manifest file",
    )
    new.set_defaults(func=run_new)

    rm = part_sub.add_parser(
        "rm", help="Delete a part or assembly KB (and its rows) from the DB.",
    )
    rm.add_argument("kb_name", help="kb_name to delete")
    rm.add_argument(
        "--force", action="store_true",
        help="actually do the delete (required; safety check)",
    )
    rm.add_argument("--db", default=DEFAULT_DB_PATH)
    rm.set_defaults(func=run_rm)

    export = part_sub.add_parser(
        "export",
        help="Emit a structured JSON sim-contract document for a part KB.",
    )
    export.add_argument("kb_name")
    export.add_argument(
        "--out",
        help="write JSON to this path (default: stdout)",
    )
    export.add_argument(
        "--compact", action="store_true",
        help="single-line JSON (default: 2-space indent for human readers)",
    )
    export.add_argument("--db", default=DEFAULT_DB_PATH)
    export.set_defaults(func=run_export)


def run_list(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    rows = conn.execute(
        "SELECT knowledge_base, description FROM knowledge_base_info "
        "WHERE knowledge_base LIKE ? ORDER BY knowledge_base",
        (args.prefix + "%",),
    ).fetchall()
    if not rows:
        print(f"no parts matching prefix '{args.prefix}'")
        return 0
    for r in rows:
        desc = r["description"] or ""
        print(f"{r['knowledge_base']}\t{desc}")
    conn.close()
    return 0


def run_show(args: argparse.Namespace) -> int:
    """Grouped, tree-structured part-KB display.

    Layout: header (kb + description), then PARAM, JOINT, META, PART
    sections in that order. META renders dotted keys as a nested tree
    via mk.meta_tree (matching `mk part export`), with ``_TODO_*``
    placeholders kept in a separate sub-block so they don't interleave
    with real schema values.
    """
    from mk.meta_tree import build_meta_tree

    conn = open_db(args.db)
    info = conn.execute(
        "SELECT description FROM knowledge_base_info WHERE knowledge_base = ?",
        (args.kb_name,),
    ).fetchone()
    if info is None:
        print(f"no such part: {args.kb_name}", file=sys.stderr)
        return 1

    rows = conn.execute(
        "SELECT label, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? ORDER BY label, name",
        (args.kb_name,),
    ).fetchall()
    by_label: dict[str, list] = {"PARAM": [], "JOINT": [], "META": [], "PART": []}
    other: list = []
    for r in rows:
        if r["label"] in by_label:
            by_label[r["label"]].append(r)
        else:
            other.append(r)

    desc = info["description"] or ""
    print(f"{args.kb_name}" + (f"  — {desc}" if desc else ""))

    # PARAM block.
    if by_label["PARAM"]:
        print()
        print("PARAM:")
        for r in by_label["PARAM"]:
            p = json.loads(r["properties"]) if r["properties"] else {}
            print(f"  {r['name']} = {p.get('value')!r} ({p.get('type', '?')})")

    # JOINT block — show origin + optional z_dir + optional x_dir.
    if by_label["JOINT"]:
        print()
        print("JOINT:")
        name_w = max(len(r["name"]) for r in by_label["JOINT"])
        for r in by_label["JOINT"]:
            p = json.loads(r["properties"]) if r["properties"] else {}
            parts = [f"origin={p.get('origin')}"]
            if "z_dir" in p:
                parts.append(f"z_dir={p['z_dir']}")
            if "x_dir" in p:
                parts.append(f"x_dir={p['x_dir']}")
            print(f"  {r['name'].ljust(name_w)}  {'  '.join(parts)}")

    # META block — nested by namespace; _TODO_* split into a trailer.
    if by_label["META"]:
        meta_pairs: list[tuple[str, object]] = []
        todo_pairs: list[tuple[str, object]] = []
        for r in by_label["META"]:
            v = json.loads(r["properties"]).get("value") if r["properties"] else None
            if r["name"].startswith("_TODO_"):
                todo_pairs.append((r["name"], v))
            else:
                meta_pairs.append((r["name"], v))

        print()
        print("META:")
        _print_meta_tree(build_meta_tree(meta_pairs), indent=1)

        if todo_pairs:
            print()
            print("  _TODO_ (placeholders — fill from datasheet):")
            for name, v in todo_pairs:
                print(f"    {name} = {v!r}")

    # PART block — body source summary.
    if by_label["PART"]:
        print()
        print("PART:")
        for r in by_label["PART"]:
            p = json.loads(r["properties"]) if r["properties"] else {}
            entry = p.get("entry", "?")
            n_lines = len(p.get("source", "").splitlines())
            print(f"  {r['name']}: entry={entry}, source={n_lines} lines")

    # Any sentinel we didn't anticipate (SUB/INST/MATE/LAYER on a part —
    # shouldn't happen but handle gracefully).
    for r in other:
        p = json.loads(r["properties"]) if r["properties"] else {}
        print(f"  {r['label']}.{r['name']}: {p}")

    conn.close()
    return 0


def _print_meta_tree(tree: dict, *, indent: int = 0) -> None:
    """Pretty-print a nested META dict. Leaves render as ``key = value``;
    sub-dicts render as ``namespace:`` headers with recursive content
    indented two spaces deeper.
    """
    pad = "  " * indent
    # Render leaves before namespaces so flat keys appear together at
    # the top of each scope (visually cleaner — easier to spot the
    # primitive fields without scanning past namespace blocks).
    leaves = [(k, v) for k, v in tree.items() if not isinstance(v, dict)]
    namespaces = [(k, v) for k, v in tree.items() if isinstance(v, dict)]
    for k, v in leaves:
        print(f"{pad}{k} = {v!r}")
    for k, sub in namespaces:
        print(f"{pad}{k}:")
        _print_meta_tree(sub, indent=indent + 1)


def run_rm(args: argparse.Namespace) -> int:
    """Delete a KB and all its rows from the DB.

    Doesn't touch geometry rows (those are content-addressed and may be
    referenced by INSTs in other assemblies — orphan-cleanup is v3 GC).
    Doesn't touch any manifest .py file.

    If the deleted KB is a part referenced by INSTs in some assembly, those
    INSTs become dangling and `mk build <that_asm>` will fail when looking
    up the part KB. Re-apply the source manifest to recreate.
    """
    conn = open_db(args.db)
    info = conn.execute(
        "SELECT description FROM knowledge_base_info WHERE knowledge_base = ?",
        (args.kb_name,),
    ).fetchone()
    if info is None:
        print(f"no such kb: {args.kb_name!r}", file=sys.stderr)
        conn.close()
        return 1

    n_rows = conn.execute(
        "SELECT COUNT(*) FROM knowledge_base WHERE knowledge_base = ?",
        (args.kb_name,),
    ).fetchone()[0]

    desc = info["description"] or "(no description)"
    if not args.force:
        print(f"would delete {args.kb_name!r}")
        print(f"  description: {desc}")
        print(f"  knowledge_base rows: {n_rows}")
        print(f"  knowledge_base_info rows: 1")
        # Warn if referenced by INSTs in other assemblies (orphan risk).
        ref_rows = conn.execute(
            """
            SELECT DISTINCT knowledge_base
            FROM knowledge_base
            WHERE label = 'INST'
              AND json_extract(properties, '$.ref_kb') = ?
              AND knowledge_base != ?
            """,
            (args.kb_name, args.kb_name),
        ).fetchall()
        if ref_rows:
            kbs = ", ".join(r["knowledge_base"] for r in ref_rows)
            print(f"  WARN: still referenced as ref_kb by INSTs in: {kbs}")
            print(f"  (those assemblies will fail to build until the part is re-applied)")
        print(f"add --force to actually delete", file=sys.stderr)
        conn.close()
        return 1

    conn.execute("DELETE FROM knowledge_base WHERE knowledge_base = ?", (args.kb_name,))
    conn.execute("DELETE FROM knowledge_base_info WHERE knowledge_base = ?", (args.kb_name,))
    conn.commit()
    conn.close()
    print(f"deleted {args.kb_name!r} ({n_rows} kb rows + 1 info row)")
    return 0


def build_part_document(conn, kb_name: str) -> dict | None:
    """Assemble the part's sim-contract: params, joints, meta.

    Returns ``None`` if the kb doesn't exist. The ``meta`` field uses
    ``build_meta_tree`` so dotted META keys nest into namespaces while
    flat keys stay at the top level.
    """
    from mk.meta_tree import build_meta_tree

    info = conn.execute(
        "SELECT description FROM knowledge_base_info WHERE knowledge_base = ?",
        (kb_name,),
    ).fetchone()
    if info is None:
        return None

    rows = conn.execute(
        "SELECT label, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? ORDER BY label, name",
        (kb_name,),
    ).fetchall()

    params: dict = {}
    joints: dict = {}
    meta_rows: list[tuple[str, object]] = []

    for r in rows:
        props = json.loads(r["properties"]) if r["properties"] else {}
        if r["label"] == "PARAM":
            params[r["name"]] = props.get("value")
        elif r["label"] == "JOINT":
            j = {"origin": props.get("origin")}
            if "z_dir" in props:
                j["z_dir"] = props["z_dir"]
            if "x_dir" in props:
                j["x_dir"] = props["x_dir"]
            joints[r["name"]] = j
        elif r["label"] == "META":
            meta_rows.append((r["name"], props.get("value")))

    return {
        "kb": kb_name,
        "description": info["description"] or "",
        "params": params,
        "joints": joints,
        "meta": build_meta_tree(meta_rows),
    }


def run_export(args: argparse.Namespace) -> int:
    """``mk part export <kb>`` — JSON sim contract for controller code."""
    conn = open_db(args.db)
    doc = build_part_document(conn, args.kb_name)
    conn.close()

    if doc is None:
        print(f"no such part: {args.kb_name}", file=sys.stderr)
        return 1

    # ensure_ascii=False keeps Unicode literal (Φ stays Φ, not Φ) —
    # matters for descriptions and vendor strings that controllers may
    # render verbatim in logs / UIs.
    if args.compact:
        text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    else:
        text = json.dumps(doc, indent=2, ensure_ascii=False)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n")
        print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    else:
        print(text)
    return 0


_TEMPLATES = {
    "block": '''def build_{stem}(p):
    from build123d import Box  # noqa: F401
    return Box(p["w"], p["d"], p["h"])
''',
    "cylinder": '''def build_{stem}(p):
    from build123d import Cylinder  # noqa: F401
    return Cylinder(p["d"] / 2, p["h"])
''',
    "plate_with_hole": '''def build_{stem}(p):
    from build123d import Box, Cylinder  # noqa: F401
    plate = Box(p["w"], p["d"], p["t"])
    hole = Cylinder(p["hole_d"] / 2, p["t"] * 4)
    return plate - hole
''',
    "blank": '''def build_{stem}(p):
    from build123d import Box  # noqa: F401
    # Replace this with the actual geometry.
    return Box(10, 10, 10)
''',
}

_PARAMS = {
    "block":            [("w", 30, "float"), ("d", 30, "float"), ("h", 10, "float")],
    "cylinder":         [("d", 20, "float"), ("h", 30, "float")],
    "plate_with_hole":  [("w", 50, "float"), ("d", 50, "float"),
                         ("t", 5, "float"), ("hole_d", 6, "float")],
    "blank":            [],
}


def run_new(args: argparse.Namespace) -> int:
    raw = args.name
    kb_name = raw if raw.startswith("part_") else f"part_{raw}"
    stem = kb_name.removeprefix("part_")
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.py"
    if out_path.exists() and not args.force:
        print(f"refusing to overwrite {out_path} (use --force)", file=sys.stderr)
        return 1

    builder_src = _TEMPLATES[args.template].format(stem=stem)
    param_lines = "\n".join(
        f'        p.param({n!r}, {v}, type={t!r})' for n, v, t in _PARAMS[args.template]
    ) or "        # p.param('w', 30, type='float')"

    content = f'''# SPDX-License-Identifier: MPL-2.0
"""{kb_name} — scaffolded by `mk part new` (template: {args.template}).

Edit `build_{stem}` to define the geometry, adjust params/joints/meta,
then run:

    mk apply /project/manifests/{stem}.py
    mk part show {kb_name}
"""
from mk.kb import connect, kb_part


{builder_src}

with connect():
    with kb_part({kb_name!r}, description="TODO: describe {stem}") as p:
{param_lines}
        # Joints define named coordinate frames for mating. Optional.
        # p.joint("top",    origin=[0, 0, 0], z_dir=[0, 0,  1])
        # p.joint("bottom", origin=[0, 0, 0], z_dir=[0, 0, -1])

        # Material / density. density is g/cm^3; mk mass uses it directly.
        p.meta("density", 7.85)
        p.meta("material", "steel")

        p.builder(build_{stem})
'''
    out_path.write_text(content)
    print(f"wrote {out_path}")
    print(f"next: mk apply {out_path}  &&  mk part show {kb_name}")
    return 0
