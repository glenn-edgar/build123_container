# SPDX-License-Identifier: LGPL-2.1-or-later
"""mk apply: import a Python manifest and let it write to the DB."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from mk.db import DEFAULT_DB_PATH


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("apply", help="Apply a Python manifest to the DB.")
    p.add_argument("file", help="path to manifest .py file")
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="path to project.db")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    manifest = Path(args.file).resolve()
    if not manifest.exists():
        print(f"manifest not found: {manifest}", file=sys.stderr)
        return 1

    # Manifests call `connect()` with no arg and pick up MK_DB.
    os.environ["MK_DB"] = args.db

    spec = importlib.util.spec_from_file_location(f"manifest_{manifest.stem}", manifest)
    if spec is None or spec.loader is None:
        print(f"could not load manifest: {manifest}", file=sys.stderr)
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    print(f"applied {manifest}")
    return 0
