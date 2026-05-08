# SPDX-License-Identifier: MPL-2.0
"""mk CLI entry point."""
from __future__ import annotations

import argparse
import logging
import sys

from mk import __version__
from mk.commands import apply as cmd_apply
from mk.commands import asm as cmd_asm
from mk.commands import bom as cmd_bom
from mk.commands import build as cmd_build
from mk.commands import export as cmd_export
from mk.commands import init as cmd_init
from mk.commands import mass as cmd_mass
from mk.commands import part as cmd_part


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mk", description="build123d + ltree CAD prototype")
    parser.add_argument("--version", action="version", version=f"mk {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG-level logging")

    subparsers = parser.add_subparsers(dest="command", required=True)
    cmd_init.add_parser(subparsers)
    cmd_apply.add_parser(subparsers)
    cmd_part.add_parser(subparsers)
    cmd_asm.add_parser(subparsers)
    cmd_build.add_parser(subparsers)
    cmd_export.add_parser(subparsers)
    cmd_mass.add_parser(subparsers)
    cmd_bom.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
