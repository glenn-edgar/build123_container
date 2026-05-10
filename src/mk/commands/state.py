# SPDX-License-Identifier: MPL-2.0
"""mk state ls / set / reset — manage the per-assembly joint-state file.

Phase B.2.a introduced ``outputs/<asm>/state.json`` as the way to override
revolute / prismatic mate DOF values at build time. Pre-v3 the only way
to edit it was to hand-write JSON; this command surface makes the
common operations one-liners.

State-file shape (unchanged from B.2.a):

    {"<mate_name>": <value>, ...}

Values are degrees for revolute mates, mm for prismatic. The file lives
under the same per-asm output subdir that exports and viewer assets use.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mk.db import DEFAULT_DB_PATH, kb_exists, open_db
from mk.mate import _parse_mate_rows

DEFAULT_OUTDIR = "/project/outputs"


def add_parser(subparsers) -> None:
    state = subparsers.add_parser("state", help="Manage per-assembly mate-state overrides.")
    sub = state.add_subparsers(dest="state_cmd", required=True)

    ls = sub.add_parser("ls", help="List mates with current state vs default + limits.")
    ls.add_argument("asm_kb")
    ls.add_argument("--db", default=DEFAULT_DB_PATH)
    ls.add_argument("--outdir", default=DEFAULT_OUTDIR)
    ls.set_defaults(func=run_ls)

    setp = sub.add_parser("set", help="Write a state override for one mate.")
    setp.add_argument("asm_kb")
    setp.add_argument("mate")
    setp.add_argument("value", type=float)
    setp.add_argument("--db", default=DEFAULT_DB_PATH)
    setp.add_argument("--outdir", default=DEFAULT_OUTDIR)
    setp.set_defaults(func=run_set)

    reset = sub.add_parser("reset", help="Delete the state file (revert to manifest defaults).")
    reset.add_argument("asm_kb")
    reset.add_argument("--outdir", default=DEFAULT_OUTDIR)
    reset.set_defaults(func=run_reset)


def _state_path(outdir: str, asm_kb: str) -> Path:
    return Path(outdir) / asm_kb / "state.json"


def _load_state(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    text = path.read_text()
    if not text.strip():
        return {}
    data = json.loads(text)
    return {k: float(v) for k, v in data.items()}


def _save_state(path: Path, state: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _dof_mates(conn, asm_kb: str) -> list[dict]:
    """Return the revolute + prismatic mates only (rigid mates have no DOF)."""
    return [m for m in _parse_mate_rows(conn, asm_kb)
            if m["mate_type"] in ("revolute", "prismatic")]


def _fmt_limits(limits) -> str:
    if not limits:
        return "—"
    lo, hi = limits
    lo_s = f"{lo}" if lo is not None else "—"
    hi_s = f"{hi}" if hi is not None else "—"
    return f"[{lo_s}, {hi_s}]"


# ── commands ────────────────────────────────────────────────────────────────

def run_ls(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if not kb_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    mates = _dof_mates(conn, args.asm_kb)
    conn.close()

    state_file = _state_path(args.outdir, args.asm_kb)
    state = _load_state(state_file)

    if not mates:
        print(f"{args.asm_kb}: no revolute or prismatic mates (rigid-only assembly)")
        if state:
            print(f"  WARN: state.json has {len(state)} key(s) but no DOF mates to apply to: "
                  f"{sorted(state)}", file=sys.stderr)
        return 0

    print(f"{args.asm_kb} — {len(mates)} DOF mate(s); state file: {state_file}"
          + ("  (missing)" if not state_file.exists() else ""))
    name_w = max(len(m["name"]) for m in mates)
    print(f"  {'NAME':<{name_w}}  TYPE       UNIT  DEFAULT   LIMITS              CURRENT  SOURCE")
    for m in mates:
        unit = "deg" if m["mate_type"] == "revolute" else "mm"
        default = m.get("default")
        default_s = f"{default}" if default is not None else "0"
        limits = _fmt_limits(m.get("limits"))
        if m["name"] in state:
            current = state[m["name"]]
            source = "state.json"
        else:
            current = float(default) if default is not None else 0.0
            source = "default"
        print(
            f"  {m['name']:<{name_w}}  "
            f"{m['mate_type']:<9}  {unit:<4}  "
            f"{default_s:<8}  {limits:<18}  "
            f"{current:>7}  {source}"
        )
    return 0


def run_set(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if not kb_exists(conn, args.asm_kb):
        print(f"no such assembly: {args.asm_kb}", file=sys.stderr)
        conn.close()
        return 1

    mates = _dof_mates(conn, args.asm_kb)
    target = next((m for m in mates if m["name"] == args.mate), None)
    conn.close()

    if target is None:
        # Distinguish "no such mate" from "mate is rigid".
        # Re-check with all mates to give the right hint.
        conn = open_db(args.db)
        all_mates = _parse_mate_rows(conn, args.asm_kb)
        conn.close()
        any_match = next((m for m in all_mates if m["name"] == args.mate), None)
        if any_match is not None:
            print(
                f"mate {args.mate!r} is type {any_match['mate_type']!r}; "
                f"only revolute and prismatic mates accept state overrides.",
                file=sys.stderr,
            )
        else:
            dof_names = [m["name"] for m in mates]
            print(
                f"no DOF mate named {args.mate!r} in {args.asm_kb}. "
                f"Available: {dof_names}",
                file=sys.stderr,
            )
        return 1

    # Warn if out-of-limits — mk build will clamp anyway but the user
    # should see this at set-time.
    limits = target.get("limits")
    if limits:
        lo, hi = limits
        if lo is not None and args.value < lo:
            print(
                f"  WARN: value {args.value} below lower limit {lo}; "
                "mk build will clamp.", file=sys.stderr,
            )
        if hi is not None and args.value > hi:
            print(
                f"  WARN: value {args.value} above upper limit {hi}; "
                "mk build will clamp.", file=sys.stderr,
            )

    state_file = _state_path(args.outdir, args.asm_kb)
    state = _load_state(state_file)
    state[args.mate] = args.value
    _save_state(state_file, state)

    unit = "deg" if target["mate_type"] == "revolute" else "mm"
    print(f"{args.asm_kb}: state[{args.mate}] = {args.value} {unit}  → {state_file}")
    print(f"  next: mk build {args.asm_kb}  &&  mk show {args.asm_kb}")
    return 0


def run_reset(args: argparse.Namespace) -> int:
    state_file = _state_path(args.outdir, args.asm_kb)
    if not state_file.exists():
        print(f"{args.asm_kb}: no state file at {state_file} (nothing to reset)")
        return 0
    state_file.unlink()
    print(f"{args.asm_kb}: deleted {state_file} — mates will use manifest defaults")
    return 0
