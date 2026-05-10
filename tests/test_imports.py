"""Smoke: every mk module imports without errors.

Catches syntax errors, circular imports, and broken vendor links. Doesn't
exercise any function — just imports. Lazy OCP/build123d imports inside
function bodies stay lazy, so this passes on host.
"""
from __future__ import annotations


def test_mk_top_level():
    import mk
    assert mk.__version__


def test_mk_pure_modules():
    """Modules whose top-level imports are stdlib + vendor only."""
    import mk.db
    import mk.transform
    import mk.mate
    import mk.geometry
    import mk.builder
    import mk.kb
    assert all(m for m in (mk.db, mk.transform, mk.mate, mk.geometry, mk.builder, mk.kb))


def test_mk_commands():
    """Command modules. Their build123d imports are lazy."""
    from mk.commands import (
        apply, asm, bom, build, export, init, mass, measure, part, show,
    )
    assert all(m for m in (apply, asm, bom, build, export, init, mass, measure, part, show))


def test_main_dispatch_table():
    """Every command registered in __main__.py builds its parser cleanly."""
    from mk.__main__ import build_parser
    parser = build_parser()
    # Each subcommand should be registered.
    subcommands = parser._subparsers._actions[-1].choices  # noqa: SLF001
    expected = {"init", "apply", "part", "asm", "build", "export", "mass", "bom", "show", "measure"}
    assert expected.issubset(set(subcommands)), \
        f"missing subcommands: {expected - set(subcommands)}"
