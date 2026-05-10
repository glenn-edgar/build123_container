# SPDX-License-Identifier: MPL-2.0
"""mk asm tree: render an assembly subtree as ASCII."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mk.db import DEFAULT_DB_PATH, open_db


DEFAULT_MANIFESTS_DIR = "/project/manifests"


def add_parser(subparsers) -> None:
    asm = subparsers.add_parser("asm", help="Assembly inspection.")
    asm_sub = asm.add_subparsers(dest="asm_cmd", required=True)

    lst = asm_sub.add_parser("list", help="List assembly KBs.")
    lst.add_argument("--prefix", default="asm_", help="kb_name prefix filter")
    lst.add_argument("--db", default=DEFAULT_DB_PATH)
    lst.set_defaults(func=run_list)

    tree = asm_sub.add_parser("tree", help="ASCII tree of an assembly KB.")
    tree.add_argument("kb_name", help="assembly KB name, e.g. asm_demo")
    tree.add_argument("--db", default=DEFAULT_DB_PATH)
    tree.set_defaults(func=run_tree)

    new = asm_sub.add_parser(
        "new", help="Scaffold a starter manifest .py for a new assembly.",
    )
    new.add_argument("name", help="asm kb_name (will be prefixed with 'asm_' if missing)")
    new.add_argument(
        "--outdir", default=DEFAULT_MANIFESTS_DIR,
        help="directory to write the manifest into",
    )
    new.add_argument(
        "--template", default="flat",
        choices=["flat", "with_sub"],
        help="'flat' = single inst, no mates; 'with_sub' = one SUB, two "
             "insts, one mate (shows the SUB-scope mate-path form)",
    )
    new.add_argument(
        "--force", action="store_true",
        help="overwrite an existing manifest file",
    )
    new.set_defaults(func=run_new)


def run_list(args: argparse.Namespace) -> int:
    """Mirror of mk part list: enumerate kb_name + description for every
    KB whose name starts with ``--prefix`` (default ``asm_``).
    """
    conn = open_db(args.db)
    rows = conn.execute(
        "SELECT knowledge_base, description FROM knowledge_base_info "
        "WHERE knowledge_base LIKE ? ORDER BY knowledge_base",
        (args.prefix + "%",),
    ).fetchall()
    if not rows:
        print(f"no assemblies matching prefix '{args.prefix}'")
        return 0
    for r in rows:
        desc = r["description"] or ""
        print(f"{r['knowledge_base']}\t{desc}")
    conn.close()
    return 0


_ASM_TEMPLATE_FLAT = '''# SPDX-License-Identifier: MPL-2.0
"""{kb_name} — scaffolded by `mk asm new` (template: flat).

Single inst, no mates. Edit to add more insts + `a.mate(...)` calls.
Apply / build / show:

    mk apply /project/manifests/{stem}.py
    mk build {kb_name}
    mk show {kb_name}
"""
from mk.kb import connect, kb_asm


with connect():
    with kb_asm({kb_name!r}, description="TODO: describe {stem}") as a:
        # Replace `part_unit_box` with one of your applied parts
        # (run `mk part list` to see what's available).
        a.inst("main", ref_kb="part_unit_box")

        # Layer tags are optional. Single name or comma-separated list:
        # a.inst("bolt1", ref_kb="part_m6_cap_20mm", layer="fasteners")

        # Add mates here. Joint paths use the form
        # `{kb_name}.INST.<inst>.JOINT.<joint>`. Example:
        # a.mate(
        #     "main_to_floor",
        #     joint_a="{kb_name}.INST.main.JOINT.bottom",
        #     joint_b="{kb_name}.INST.floor.JOINT.top",
        #     mate_type="rigid",
        #     # align="z",          # default — z-axes oppose
        #     # align="position",   # translate only; preserve part orientation
        # )
'''

_ASM_TEMPLATE_WITH_SUB = '''# SPDX-License-Identifier: MPL-2.0
"""{kb_name} — scaffolded by `mk asm new` (template: with_sub).

Two-level assembly. Demonstrates SUB-scope mate path form
(`{kb_name}.SUB.<sub>.INST.<inst>.JOINT.<joint>`).

    mk apply /project/manifests/{stem}.py
    mk build {kb_name}
    mk show {kb_name}
"""
from mk.kb import connect, kb_asm


with connect():
    with kb_asm({kb_name!r}, description="TODO: describe {stem}") as a:
        a.inst("root", ref_kb="part_unit_box")

        # Subassembly scope. Layer cascades to descendants.
        with a.sub("group", description="lower-level group", layer="mechanism") as s:
            s.inst("piece_a", ref_kb="part_unit_box")
            s.inst("piece_b", ref_kb="part_unit_box")
            # Mate inside the SUB. joint_a / joint_b use full ltree paths
            # including the SUB segment.
            s.mate(
                "b_to_a",
                joint_a="{kb_name}.SUB.group.INST.piece_b.JOINT.face_neg",
                joint_b="{kb_name}.SUB.group.INST.piece_a.JOINT.face_pos",
                mate_type="rigid",
            )
'''

_ASM_TEMPLATES = {
    "flat": _ASM_TEMPLATE_FLAT,
    "with_sub": _ASM_TEMPLATE_WITH_SUB,
}


def run_new(args: argparse.Namespace) -> int:
    raw = args.name
    kb_name = raw if raw.startswith("asm_") else f"asm_{raw}"
    stem = kb_name.removeprefix("asm_")
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.py"
    if out_path.exists() and not args.force:
        print(f"refusing to overwrite {out_path} (use --force)", file=sys.stderr)
        return 1

    content = _ASM_TEMPLATES[args.template].format(kb_name=kb_name, stem=stem)
    out_path.write_text(content)
    print(f"wrote {out_path}")
    print(f"next: mk apply {out_path}  &&  mk build {kb_name}")
    return 0


def run_tree(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    rows = conn.execute(
        "SELECT path, label, name, properties FROM knowledge_base "
        "WHERE knowledge_base = ? ORDER BY path",
        (args.kb_name,),
    ).fetchall()

    info = conn.execute(
        "SELECT description FROM knowledge_base_info WHERE knowledge_base = ?",
        (args.kb_name,),
    ).fetchone()

    if info is None and not rows:
        print(f"no such assembly: {args.kb_name}", file=sys.stderr)
        return 1

    desc = (info["description"] if info else "") or ""
    header = f"{args.kb_name}" + (f"  — {desc}" if desc else "")
    print(header)

    for row in rows:
        path = row["path"]
        # depth = segments minus the kb_name root
        depth = path.count(".")
        indent = "  " * (depth - 1) if depth > 0 else ""
        props = json.loads(row["properties"]) if row["properties"] else {}
        suffix = _format_suffix(row["label"], row["name"], props)
        print(f"{indent}{row['label']}.{row['name']}{suffix}")

    conn.close()
    return 0


def _format_suffix(label: str, name: str, props: dict) -> str:
    if label == "INST":
        ref = props.get("ref_kb", "?")
        extra = ""
        if "params_override" in props:
            extra += f" overrides={props['params_override']}"
        return f"  ← {ref}{extra}"
    if label == "MATE":
        return f"  {props.get('joint_a', '?')} ↔ {props.get('joint_b', '?')}"
    return ""
