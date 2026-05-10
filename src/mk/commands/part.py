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

    print(f"{args.kb_name}" + (f"  — {info['description']}" if info["description"] else ""))
    for r in rows:
        props = json.loads(r["properties"]) if r["properties"] else {}
        if r["label"] == "PART":
            entry = props.get("entry", "?")
            n_lines = len(props.get("source", "").splitlines())
            print(f"  PART.{r['name']}: entry={entry}, source={n_lines} lines")
        elif r["label"] == "PARAM":
            print(f"  PARAM.{r['name']} = {props.get('value')!r} ({props.get('type','?')})")
        elif r["label"] == "JOINT":
            origin = props.get("origin")
            print(f"  JOINT.{r['name']}: origin={origin}")
        elif r["label"] == "META":
            print(f"  META.{r['name']} = {props.get('value')!r}")
        else:
            print(f"  {r['label']}.{r['name']}: {props}")
    conn.close()
    return 0


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
