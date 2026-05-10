# SPDX-License-Identifier: MPL-2.0
"""DB connection, ltree extension loading, and idempotent schema setup.

Why we don't use the vendored ``_create_tables``: it drops the KB tables before
re-creating them. ``mk init`` must preserve data on re-run, so we run our own
``CREATE TABLE IF NOT EXISTS`` DDL here. Later commands open the manager with
``upload_flag=True`` to skip the destructive path.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = "/project/db/project.db"
DEFAULT_LTREE_PATH = "/usr/local/lib/ltree.so"

# Schema mirrors vendor/kb_python/knowledge_base_manager.py::_create_tables
# but uses CREATE TABLE IF NOT EXISTS without the leading DROP.
KB_TABLE_NAME = "knowledge_base"

_KB_DDL = [
    f"""
    CREATE TABLE IF NOT EXISTS {KB_TABLE_NAME} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        knowledge_base TEXT NOT NULL,
        label TEXT NOT NULL,
        name TEXT NOT NULL,
        properties TEXT,
        data TEXT,
        has_link INTEGER DEFAULT 0,
        has_link_mount INTEGER DEFAULT 0,
        path TEXT UNIQUE
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {KB_TABLE_NAME}_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        knowledge_base TEXT NOT NULL UNIQUE,
        description TEXT
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {KB_TABLE_NAME}_link (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_name TEXT NOT NULL,
        parent_node_kb TEXT NOT NULL,
        parent_path TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(link_name, parent_node_kb, parent_path)
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {KB_TABLE_NAME}_link_mount (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_name TEXT NOT NULL UNIQUE,
        knowledge_base TEXT NOT NULL,
        mount_path TEXT NOT NULL,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(knowledge_base, mount_path)
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS geometry (
        hash TEXT PRIMARY KEY,
        brep_blob BLOB NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

_KB_INDEXES = [
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_kb ON {KB_TABLE_NAME} (knowledge_base)",
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_path ON {KB_TABLE_NAME} (path)",
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_label ON {KB_TABLE_NAME} (label)",
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_name ON {KB_TABLE_NAME} (name)",
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_kb_path ON {KB_TABLE_NAME} (knowledge_base, path)",
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_info_kb ON {KB_TABLE_NAME}_info (knowledge_base)",
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_link_name ON {KB_TABLE_NAME}_link (link_name)",
    f"CREATE INDEX IF NOT EXISTS idx_{KB_TABLE_NAME}_link_mount_kb ON {KB_TABLE_NAME}_link_mount (knowledge_base)",
]


def _resolve_ltree_path() -> str:
    """Find the ltree extension. Container path wins; dev path fallback."""
    env_path = os.environ.get("MK_LTREE_PATH")
    if env_path:
        return env_path
    if os.path.exists(DEFAULT_LTREE_PATH):
        return DEFAULT_LTREE_PATH
    # Dev fallback: vendored location relative to the package.
    here = Path(__file__).resolve().parent.parent.parent
    candidate = here / "vendor" / "ltree.so"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        f"ltree.so not found at {DEFAULT_LTREE_PATH} or {candidate}; "
        "set MK_LTREE_PATH to override."
    )


def open_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open SQLite, load ltree extension, return connection."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    ltree_path = _resolve_ltree_path()
    conn.enable_load_extension(True)
    try:
        # SQLite's load_extension auto-appends the platform suffix when the
        # path has no extension, but if the path already ends in .so it will
        # also accept it on Linux.
        conn.load_extension(ltree_path, entrypoint="sqlite3_ltree_init")
    finally:
        conn.enable_load_extension(False)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create KB tables and geometry table if missing. Idempotent."""
    cur = conn.cursor()
    for stmt in _KB_DDL:
        cur.execute(stmt)
    for stmt in _KB_INDEXES:
        cur.execute(stmt)
    conn.commit()


def verify_ltree(conn: sqlite3.Connection) -> bool:
    """Sanity check: call ltree_descendant. Returns True on success."""
    row = conn.execute(
        "SELECT ltree_descendant(?, ?)", ("parts", "parts.foo")
    ).fetchone()
    return bool(row[0])


def kb_exists(conn: sqlite3.Connection, kb_name: str) -> bool:
    """True iff ``kb_name`` has an entry in ``knowledge_base_info``.

    Used by user-facing commands to distinguish "no such assembly" from
    "assembly exists but has no INST rows yet" — different fixes, so
    different error messages.
    """
    return conn.execute(
        "SELECT 1 FROM knowledge_base_info WHERE knowledge_base = ?",
        (kb_name,),
    ).fetchone() is not None
