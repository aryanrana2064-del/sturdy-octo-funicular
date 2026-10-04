"""SQLite connection, schema and migrations.

* Foreign keys are always enforced.
* Schema changes are applied by numbered migrations, tracked in ``PRAGMA user_version``.
* Each migration runs in one transaction: it fully applies or not at all.
* The connection is in autocommit mode; writes use :func:`transaction`.
"""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3


class DatabaseError(Exception):
    """The database file cannot be used."""


MIGRATIONS: dict[int, list[str]] = {
    1: [
        """CREATE TABLE customers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            name_key   TEXT NOT NULL UNIQUE,
            mobile     TEXT NOT NULL DEFAULT '',
            address    TEXT NOT NULL DEFAULT '',
            notes      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE transactions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
            txn_date     TEXT NOT NULL
                         CHECK (txn_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
            item         TEXT NOT NULL,
            quantity     TEXT,
            rate_paise   INTEGER CHECK (rate_paise IS NULL OR rate_paise > 0),
            amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
            txn_type     TEXT NOT NULL CHECK (txn_type IN ('UDHAAR', 'JAMA')),
            notes        TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )""",
        "CREATE INDEX idx_txn_customer_date ON transactions(customer_id, txn_date, id)",
        "CREATE INDEX idx_txn_date ON transactions(txn_date)",
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ],
    2: [
        "CREATE INDEX idx_customers_mobile ON customers(mobile)",
        "CREATE INDEX idx_txn_item ON transactions(item COLLATE NOCASE)",
    ],
    # v3: dedicated Deposit Date for JAMA entries. txn_date (the entry date) and created_at
    # (the real entry time) are left exactly as they were. Existing deposits are back-filled
    # with their own entry date so no legacy row is ever left without one.
    3: [
        "ALTER TABLE transactions ADD COLUMN deposit_date TEXT "
        "CHECK (deposit_date IS NULL OR deposit_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')",
        "UPDATE transactions SET deposit_date = txn_date WHERE txn_type = 'JAMA' AND deposit_date IS NULL",
        "CREATE INDEX idx_txn_deposit_date ON transactions(deposit_date)",
        "CREATE INDEX idx_txn_customer_effective ON transactions(customer_id, "
        "(CASE WHEN txn_type = 'JAMA' THEN COALESCE(deposit_date, txn_date) ELSE txn_date END), id)",
    ],
}

# The date a row counts on in the ledger, filters and balances: a deposit counts on the day the
# money really arrived (deposit_date, falling back to its entry date for legacy rows); an udhaar
# counts on its transaction date. ``{p}`` is an optional table-alias prefix such as ``t.``.
EFFECTIVE_DATE_SQL = (
    "CASE WHEN {p}txn_type = 'JAMA' THEN COALESCE({p}deposit_date, {p}txn_date) ELSE {p}txn_date END"
)

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "customers": {"id", "name", "name_key", "mobile", "address", "notes", "created_at", "updated_at"},
    "transactions": {
        "id", "customer_id", "txn_date", "item", "quantity", "rate_paise",
        "amount_paise", "txn_type", "notes", "created_at", "updated_at",
    },
    "settings": {"key", "value"},
}


def required_columns(schema_version: int) -> dict[str, set[str]]:
    """Columns a database of the given schema version must have (older backups lack newer ones)."""
    needed = {table: set(cols) for table, cols in REQUIRED_COLUMNS.items()}
    if schema_version >= 3:
        needed["transactions"].add("deposit_date")
    return needed


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Run a block inside BEGIN IMMEDIATE ... COMMIT; roll back on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def get_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the schema up to SCHEMA_VERSION. Returns the final version."""
    current = get_user_version(conn)
    if current > SCHEMA_VERSION:
        raise DatabaseError(
            f"This data file was created by a newer version of VX7 KHATA PRO "
            f"(schema {current}, this version supports {SCHEMA_VERSION})."
        )
    for version in range(current + 1, SCHEMA_VERSION + 1):
        with transaction(conn):
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
    return SCHEMA_VERSION


def open_database(path, premigration_backup: bool = True) -> sqlite3.Connection:
    """Open (creating if needed) and migrate the database at ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists() and path.stat().st_size > 0

    conn = sqlite3.connect(str(path), isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise DatabaseError("SQLite foreign key enforcement is unavailable")
        try:
            current = get_user_version(conn)
            tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"'{path.name}' is not a valid database file: {exc}") from exc
        if current == 0 and tables > 0:
            raise DatabaseError(f"'{path.name}' is not a VX7 KHATA PRO database")
        if existed and 0 < current < SCHEMA_VERSION and premigration_backup:
            shutil.copyfile(path, path.with_name(f"{path.name}.pre-v{current}-migration.bak"))
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn
