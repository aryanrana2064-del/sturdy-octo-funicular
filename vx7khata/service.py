"""Ledger logic: customers, item-wise entries, balances, summaries.

Every total and every running balance is computed from the saved rows on
demand, so adding, editing or deleting a back-dated entry can never leave a
stale balance behind.

Dates: an UDHAAR counts on its transaction date; a JAMA (deposit) counts on its
**deposit date** - the day the money really arrived - which may be years before
the day it was entered. Ledger order, date-range filters, opening balances and
the dashboard all use that one "effective date". ``created_at`` is the real entry
time and is never touched.
"""
from __future__ import annotations

import itertools
import re
import shutil
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import backup as backup_mod
from . import db as dbmod
from . import dates, money

UDHAAR = "UDHAAR"
JAMA = "JAMA"
TXN_TYPES = (UDHAAR, JAMA)

DUPLICATE_WINDOW_SECONDS = 10
MAX_NAME = 120
MAX_ITEM = 200
MAX_TEXT = 2000
# A deposit (JAMA) needs no item: when none is typed this label is stored so the ledger row still reads well.
DEFAULT_DEPOSIT_ITEM = "Deposit received (Jama)"


class KhataError(Exception):
    """Base class for errors that are safe to show to the user."""


class ValidationError(KhataError):
    pass


class NotFoundError(KhataError):
    pass


class DuplicateEntryError(KhataError):
    """An identical entry was saved a few seconds ago (likely a double click)."""


# --------------------------------------------------------------------------- models
@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    mobile: str
    address: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CustomerSummary:
    customer: Customer
    total_udhaar: int
    total_jama: int
    txn_count: int
    last_txn_date: Optional[str]

    @property
    def total_deposit(self) -> int:
        return self.total_jama

    @property
    def balance(self) -> int:
        return self.total_udhaar - self.total_jama


@dataclass(frozen=True)
class Transaction:
    id: int
    customer_id: int
    txn_date: str  # ISO YYYY-MM-DD: the date the transaction happened
    item: str
    quantity: Optional[str]
    rate_paise: Optional[int]
    amount_paise: int
    txn_type: str
    notes: str
    created_at: str  # when the row was really entered (audit; never the txn date)
    updated_at: str
    deposit_date: Optional[str] = None  # ISO date the money really arrived (JAMA only)


def effective_date(txn: Transaction) -> str:
    """The date a row counts on: deposit date for a JAMA (legacy rows fall back to txn_date), else txn_date."""
    if txn.txn_type == JAMA:
        return txn.deposit_date or txn.txn_date
    return txn.txn_date


@dataclass(frozen=True)
class LedgerRow:
    txn: Transaction
    udhaar: int
    jama: int
    balance: int  # true running balance after this entry

    @property
    def deposit(self) -> int:
        """The deposited amount of this row only (never a balance)."""
        return self.jama

    @property
    def deposit_date(self) -> Optional[str]:
        return effective_date(self.txn) if self.txn.txn_type == JAMA else None


@dataclass
class Ledger:
    customer: Customer
    date_from: Optional[str]
    date_to: Optional[str]
    search: str
    opening_balance: int
    rows: list[LedgerRow]
    total_udhaar: int  # of the rows shown
    total_jama: int  # of the rows shown
    closing_balance: int  # true balance at the end of the selected period
    entries_in_period: int  # all entries in the date range, before item search

    @property
    def total_deposit(self) -> int:
        return self.total_jama

    @property
    def deposit_balance(self) -> int:
        """Outstanding balance at the end of the period: opening + udhaar - deposits (true account balance)."""
        return self.closing_balance


@dataclass(frozen=True)
class RegisterRow:
    txn: Transaction
    customer_name: str


@dataclass
class Register:
    date_from: Optional[str]
    date_to: Optional[str]
    search: str
    customer_ids: Optional[list[int]]
    rows: list[RegisterRow]
    total_udhaar: int
    total_jama: int

    @property
    def total_deposit(self) -> int:
        return self.total_jama

    @property
    def net(self) -> int:
        return self.total_udhaar - self.total_jama


@dataclass(frozen=True)
class DashboardSummary:
    total_customers: int
    total_udhaar: int
    total_jama: int
    todays_transactions: int  # entries dated today
    historical_transactions: int  # entries dated before today
    total_transactions: int

    @property
    def total_deposit(self) -> int:
        return self.total_jama

    @property
    def net_outstanding(self) -> int:
        return self.total_udhaar - self.total_jama


# --------------------------------------------------------------------------- helpers
@dataclass(frozen=True)
class PendingRow:
    """A customer who still owes money, with how long the oldest unpaid udhaar has been waiting."""
    customer: Customer
    balance: int  # outstanding paise (> 0)
    total_udhaar: int
    total_deposit: int
    oldest_unpaid_date: str  # ISO date of the oldest udhaar not yet covered by deposits
    days_pending: int
    last_deposit_date: Optional[str]
    last_deposit_paise: int


@dataclass(frozen=True)
class ImportReport:
    """Result (or dry-run preview) of importing rows from a spreadsheet."""
    total_rows: int
    errors: list  # [(line number, message)]
    new_customers: list  # names that will be created
    existing_customers: int
    total_udhaar: int
    total_jama: int
    likely_duplicates: int  # rows that look identical to an entry already saved
    imported: int  # entries actually saved (0 for a dry run or when there are errors)


def _clean_single_line(value, label: str, max_len: int, required: bool = True) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise ValidationError(f"{label} is required")
    if len(text) > max_len:
        raise ValidationError(f"{label} is too long (maximum {max_len} characters)")
    return text


def _clean_multiline(value, label: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_TEXT:
        raise ValidationError(f"{label} is too long (maximum {MAX_TEXT} characters)")
    return text


def _clean_mobile(value) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if not re.fullmatch(r"[0-9+\-() ]+", text):
        raise ValidationError("Mobile number can only contain digits, spaces, + - ( )")
    digit_count = len(re.sub(r"\D", "", text))
    if not 7 <= digit_count <= 15:
        raise ValidationError("Mobile number must have 7 to 15 digits")
    return text


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


_TXN_COLUMNS = (
    "id, customer_id, txn_date, item, quantity, rate_paise, amount_paise, "
    "txn_type, notes, created_at, updated_at, deposit_date"
)
_EFF = dbmod.EFFECTIVE_DATE_SQL.format(p="")
_EFF_T = dbmod.EFFECTIVE_DATE_SQL.format(p="t.")


def _row_to_customer(r: sqlite3.Row) -> Customer:
    return Customer(r["id"], r["name"], r["mobile"], r["address"], r["notes"], r["created_at"], r["updated_at"])


def _row_to_txn(r: sqlite3.Row) -> Transaction:
    return Transaction(
        r["id"], r["customer_id"], r["txn_date"], r["item"], r["quantity"], r["rate_paise"],
        r["amount_paise"], r["txn_type"], r["notes"], r["created_at"], r["updated_at"], r["deposit_date"],
    )


_SIGNED_AMOUNT = "CASE txn_type WHEN 'UDHAAR' THEN amount_paise ELSE -amount_paise END"


# --------------------------------------------------------------------------- service
class KhataService:
    def __init__(self, db_path, clock: Optional[Callable[[], datetime]] = None):
        self.db_path = Path(db_path)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self.conn = dbmod.open_database(self.db_path)

    def close(self) -> None:
        self.conn.close()

    # ---- time -------------------------------------------------------------
    def now(self) -> datetime:
        return self._clock()

    def today(self) -> date:
        return self._clock().date()

    def _now_iso(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    # ---- settings ---------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with dbmod.transaction(self.conn):
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ---- customers --------------------------------------------------------
    def add_customer(self, name, mobile="", address="", notes="") -> Customer:
        name = _clean_single_line(name, "Customer name", MAX_NAME)
        mobile = _clean_mobile(mobile)
        address = _clean_multiline(address, "Address")
        notes = _clean_multiline(notes, "Notes")
        now = self._now_iso()
        try:
            with dbmod.transaction(self.conn):
                cur = self.conn.execute(
                    "INSERT INTO customers(name, name_key, mobile, address, notes, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (name, name.casefold(), mobile, address, notes, now, now),
                )
        except sqlite3.IntegrityError:
            raise ValidationError(f"A customer named '{name}' already exists") from None
        return self.get_customer(cur.lastrowid)

    def update_customer(self, customer_id: int, name, mobile="", address="", notes="") -> Customer:
        self.get_customer(customer_id)
        name = _clean_single_line(name, "Customer name", MAX_NAME)
        mobile = _clean_mobile(mobile)
        address = _clean_multiline(address, "Address")
        notes = _clean_multiline(notes, "Notes")
        try:
            with dbmod.transaction(self.conn):
                self.conn.execute(
                    "UPDATE customers SET name=?, name_key=?, mobile=?, address=?, notes=?, updated_at=? WHERE id=?",
                    (name, name.casefold(), mobile, address, notes, self._now_iso(), customer_id),
                )
        except sqlite3.IntegrityError:
            raise ValidationError(f"A customer named '{name}' already exists") from None
        return self.get_customer(customer_id)

    def get_customer(self, customer_id: int) -> Customer:
        row = self.conn.execute(
            "SELECT id, name, mobile, address, notes, created_at, updated_at FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Customer not found")
        return _row_to_customer(row)

    def delete_customer(self, customer_id: int) -> None:
        """Only customers with no entries can be deleted (their khata is never destroyed silently)."""
        customer = self.get_customer(customer_id)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE customer_id = ?", (customer_id,)
        ).fetchone()[0]
        if count:
            raise ValidationError(
                f"{customer.name} has {count} khata entries. Delete or keep the customer, "
                "but a customer with entries cannot be removed."
            )
        with dbmod.transaction(self.conn):
            self.conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))

    def list_customers(self, search: str = "") -> list[CustomerSummary]:
        rows = self.conn.execute(
            """SELECT c.id, c.name, c.mobile, c.address, c.notes, c.created_at, c.updated_at,
                      COALESCE(SUM(CASE WHEN t.txn_type = 'UDHAAR' THEN t.amount_paise END), 0) AS total_udhaar,
                      COALESCE(SUM(CASE WHEN t.txn_type = 'JAMA'   THEN t.amount_paise END), 0) AS total_jama,
                      COUNT(t.id) AS txn_count,
                      MAX(t.txn_date) AS last_txn_date
                 FROM customers c LEFT JOIN transactions t ON t.customer_id = c.id
                GROUP BY c.id"""
        ).fetchall()
        needle = " ".join(search.split()).casefold()
        needle_digits = _digits(search)
        result = []
        for r in rows:
            c = _row_to_customer(r)
            if needle:
                name_hit = needle in c.name.casefold()
                phone_hit = bool(needle_digits) and needle_digits in _digits(c.mobile)
                if not (name_hit or phone_hit):
                    continue
            result.append(CustomerSummary(c, r["total_udhaar"], r["total_jama"], r["txn_count"], r["last_txn_date"]))
        result.sort(key=lambda s: s.customer.name.casefold())
        return result

    def customer_balance(self, customer_id: int) -> int:
        return int(
            self.conn.execute(
                f"SELECT COALESCE(SUM({_SIGNED_AMOUNT}), 0) FROM transactions WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()[0]
        )

    # ---- transactions -----------------------------------------------------
    def _resolve_deposit_date(self, t: str, txn_date_iso: str, deposit_date,
                              existing: Optional[Transaction]) -> Optional[str]:
        """Deposit date to store. UDHAAR: none. JAMA: the given date, else (add) the entry date.

        On edit, ``None`` keeps the deposit date already saved; an empty string resets it to the entry date.
        """
        if t != JAMA:
            if not _is_blank(deposit_date):
                raise ValidationError("A deposit date can only be set on a JAMA (deposit) entry")
            return None
        if deposit_date is None and existing is not None and existing.txn_type == JAMA and existing.deposit_date:
            return existing.deposit_date
        if _is_blank(deposit_date):
            return txn_date_iso
        try:
            return dates.parse_date(deposit_date, today=self.today())
        except dates.DateError as exc:
            raise ValidationError(f"Deposit date: {exc}") from None

    def _prepare_entry(self, txn_type, txn_date, item, amount, quantity, rate,
                       deposit_date=None, existing: Optional[Transaction] = None) -> dict:
        t = str(txn_type or "").strip().upper()
        if t not in TXN_TYPES:
            raise ValidationError("Transaction type must be UDHAAR or JAMA")
        try:
            date_iso = dates.parse_date(txn_date, today=self.today())
        except dates.DateError as exc:
            raise ValidationError(str(exc)) from None
        deposit_iso = self._resolve_deposit_date(t, date_iso, deposit_date, existing)
        if t == JAMA and _is_blank(item):
            item = DEFAULT_DEPOSIT_ITEM
        item = _clean_single_line(item, "Item / description", MAX_ITEM)
        try:
            qty = None if _is_blank(quantity) else money.parse_quantity(quantity)
            rate_paise = None if _is_blank(rate) else money.rupees_to_paise(rate, "Rate")
            if qty is not None and rate_paise is not None:
                computed = money.compute_amount_paise(qty, rate_paise)
                if not _is_blank(amount) and money.rupees_to_paise(amount) != computed:
                    raise ValidationError("Amount does not match Quantity x Rate")
                amount_paise = computed
            elif _is_blank(amount):
                raise ValidationError("Amount is required (or enter both Quantity and Rate)")
            else:
                amount_paise = money.rupees_to_paise(amount)
        except money.MoneyError as exc:
            raise ValidationError(str(exc)) from None
        return {
            "txn_type": t,
            "txn_date": date_iso,
            "deposit_date": deposit_iso,
            "item": item,
            "quantity": None if qty is None else money.quantity_to_text(qty),
            "rate_paise": rate_paise,
            "amount_paise": amount_paise,
        }

    def _recent_duplicate_exists(self, customer_id: int, f: dict, notes: str) -> bool:
        rows = self.conn.execute(
            "SELECT item, notes, created_at, deposit_date FROM transactions "
            "WHERE customer_id=? AND txn_date=? AND txn_type=? AND amount_paise=? ORDER BY id DESC LIMIT 5",
            (customer_id, f["txn_date"], f["txn_type"], f["amount_paise"]),
        ).fetchall()
        now = self.now()
        for r in rows:
            if r["item"].casefold() != f["item"].casefold() or r["notes"] != notes:
                continue
            saved_deposit = r["deposit_date"] or (f["txn_date"] if f["txn_type"] == JAMA else None)
            if saved_deposit != f["deposit_date"]:
                continue  # same payment recorded for a different deposit date is a different entry
            try:
                created = datetime.fromisoformat(r["created_at"])
            except ValueError:
                continue
            if abs((now - created).total_seconds()) <= DUPLICATE_WINDOW_SECONDS:
                return True
        return False

    def get_transaction(self, txn_id: int) -> Transaction:
        row = self.conn.execute(f"SELECT {_TXN_COLUMNS} FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        if row is None:
            raise NotFoundError("Entry not found")
        return _row_to_txn(row)

    def add_transaction(
        self, customer_id: int, txn_type, txn_date, item, amount=None, quantity=None, rate=None,
        notes="", allow_duplicate: bool = False, deposit_date=None,
    ) -> Transaction:
        self.get_customer(customer_id)
        f = self._prepare_entry(txn_type, txn_date, item, amount, quantity, rate, deposit_date)
        notes = _clean_multiline(notes, "Notes")
        with dbmod.transaction(self.conn):
            if not allow_duplicate and self._recent_duplicate_exists(customer_id, f, notes):
                raise DuplicateEntryError(
                    "An identical entry was saved a moment ago. Save it again only if it is a genuine second entry."
                )
            now = self._now_iso()
            cur = self.conn.execute(
                "INSERT INTO transactions(customer_id, txn_date, item, quantity, rate_paise, amount_paise, "
                "txn_type, notes, created_at, updated_at, deposit_date) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (customer_id, f["txn_date"], f["item"], f["quantity"], f["rate_paise"], f["amount_paise"],
                 f["txn_type"], notes, now, now, f["deposit_date"]),
            )
        return self.get_transaction(cur.lastrowid)

    def add_transactions(self, customer_id: int, entries: Sequence[dict], allow_duplicate: bool = False) -> list[Transaction]:
        """Save many entries for one customer in ONE all-or-nothing step (several items from one bill).

        Each entry is a dict with txn_type, txn_date, item, amount / quantity / rate, notes and (JAMA)
        deposit_date. Every row is validated first; if any row is wrong nothing at all is saved and the
        message names the row. An optional ``row`` key sets the row number used in that message.
        """
        self.get_customer(customer_id)
        if not entries:
            raise ValidationError("Add at least one entry")
        prepared: list[tuple[dict, str]] = []
        for n, e in enumerate(entries, 1):
            label = e.get("row", n)
            try:
                f = self._prepare_entry(e.get("txn_type"), e.get("txn_date"), e.get("item"), e.get("amount"),
                                        e.get("quantity"), e.get("rate"), e.get("deposit_date"))
                notes = _clean_multiline(e.get("notes", ""), "Notes")
            except ValidationError as exc:
                raise ValidationError(f"Row {label}: {exc}") from None
            prepared.append((f, notes))
        with dbmod.transaction(self.conn):
            if not allow_duplicate:
                for f, notes in prepared:
                    if self._recent_duplicate_exists(customer_id, f, notes):
                        raise DuplicateEntryError(
                            "An identical entry was saved a moment ago. Save again only if it is a genuine second entry."
                        )
            now = self._now_iso()
            ids = []
            for f, notes in prepared:
                cur = self.conn.execute(
                    "INSERT INTO transactions(customer_id, txn_date, item, quantity, rate_paise, amount_paise, "
                    "txn_type, notes, created_at, updated_at, deposit_date) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (customer_id, f["txn_date"], f["item"], f["quantity"], f["rate_paise"], f["amount_paise"],
                     f["txn_type"], notes, now, now, f["deposit_date"]),
                )
                ids.append(cur.lastrowid)
        return [self.get_transaction(i) for i in ids]

    def update_transaction(
        self, txn_id: int, txn_type, txn_date, item, amount=None, quantity=None, rate=None, notes="",
        deposit_date=None,
    ) -> Transaction:
        existing = self.get_transaction(txn_id)
        f = self._prepare_entry(txn_type, txn_date, item, amount, quantity, rate, deposit_date, existing)
        notes = _clean_multiline(notes, "Notes")
        with dbmod.transaction(self.conn):
            # created_at is deliberately left untouched: it is the audit timestamp.
            self.conn.execute(
                "UPDATE transactions SET txn_date=?, item=?, quantity=?, rate_paise=?, amount_paise=?, "
                "txn_type=?, notes=?, updated_at=?, deposit_date=? WHERE id=?",
                (f["txn_date"], f["item"], f["quantity"], f["rate_paise"], f["amount_paise"],
                 f["txn_type"], notes, self._now_iso(), f["deposit_date"], txn_id),
            )
        return self.get_transaction(txn_id)

    def delete_transaction(self, txn_id: int) -> None:
        self.get_transaction(txn_id)
        with dbmod.transaction(self.conn):
            self.conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))

    # ---- ledger -----------------------------------------------------------
    def _range_iso(self, date_from, date_to) -> tuple[Optional[str], Optional[str]]:
        try:
            f = None if _is_blank(date_from) else dates.parse_date(date_from, allow_future=True)
            t = None if _is_blank(date_to) else dates.parse_date(date_to, allow_future=True)
        except dates.DateError as exc:
            raise ValidationError(str(exc)) from None
        if f and t and f > t:
            raise ValidationError("'From' date cannot be after 'To' date")
        return f, t

    def ledger(self, customer_id: int, date_from=None, date_to=None, search: str = "") -> Ledger:
        customer = self.get_customer(customer_id)
        f, t = self._range_iso(date_from, date_to)

        opening = 0
        if f:
            opening = int(
                self.conn.execute(
                    f"SELECT COALESCE(SUM({_SIGNED_AMOUNT}), 0) FROM transactions "
                    f"WHERE customer_id = ? AND {_EFF} < ?",
                    (customer_id, f),
                ).fetchone()[0]
            )

        sql = f"SELECT {_TXN_COLUMNS} FROM transactions WHERE customer_id = ?"
        params: list = [customer_id]
        if f:
            sql += f" AND {_EFF} >= ?"
            params.append(f)
        if t:
            sql += f" AND {_EFF} <= ?"
            params.append(t)
        # Chronological by the date each row counts on (deposit date for a deposit); same-date entries
        # keep the order they were entered. Only THIS customer's rows are ever read.
        sql += f" ORDER BY {_EFF}, id"

        needle = " ".join(search.split()).casefold()
        balance = opening
        rows: list[LedgerRow] = []
        total_u = total_j = 0
        in_period = 0
        for r in self.conn.execute(sql, params).fetchall():
            txn = _row_to_txn(r)
            in_period += 1
            udhaar = txn.amount_paise if txn.txn_type == UDHAAR else 0
            jama = txn.amount_paise if txn.txn_type == JAMA else 0
            balance += udhaar - jama  # running balance always reflects the true account
            if needle and needle not in txn.item.casefold():
                continue
            total_u += udhaar
            total_j += jama
            rows.append(LedgerRow(txn, udhaar, jama, balance))
        return Ledger(customer, f, t, search.strip(), opening, rows, total_u, total_j, balance, in_period)

    def register(self, date_from=None, date_to=None, search: str = "",
                 customer_ids: Optional[Sequence[int]] = None) -> Register:
        """Entries across customers (no running balance), for date/customer/item filtered reports."""
        f, t = self._range_iso(date_from, date_to)
        sql = ("SELECT t.id, t.customer_id, t.txn_date, t.item, t.quantity, t.rate_paise, t.amount_paise, "
               "t.txn_type, t.notes, t.created_at, t.updated_at, t.deposit_date, c.name AS customer_name "
               "FROM transactions t JOIN customers c ON c.id = t.customer_id WHERE 1=1")
        params: list = []
        ids = None if customer_ids is None else list(customer_ids)
        if ids is not None:
            if not ids:
                return Register(f, t, search.strip(), ids, [], 0, 0)
            sql += " AND t.customer_id IN (%s)" % ",".join("?" * len(ids))
            params.extend(ids)
        if f:
            sql += f" AND {_EFF_T} >= ?"
            params.append(f)
        if t:
            sql += f" AND {_EFF_T} <= ?"
            params.append(t)
        sql += f" ORDER BY {_EFF_T}, c.name COLLATE NOCASE, t.id"
        needle = " ".join(search.split()).casefold()
        rows: list[RegisterRow] = []
        total_u = total_j = 0
        for r in self.conn.execute(sql, params).fetchall():
            txn = _row_to_txn(r)
            if needle and needle not in txn.item.casefold():
                continue
            rows.append(RegisterRow(txn, r["customer_name"]))
            if txn.txn_type == UDHAAR:
                total_u += txn.amount_paise
            else:
                total_j += txn.amount_paise
        return Register(f, t, search.strip(), ids, rows, total_u, total_j)

    # ---- dashboard --------------------------------------------------------
    def dashboard(self) -> DashboardSummary:
        today = self.today().isoformat()
        customers = self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        r = self.conn.execute(
            f"""SELECT COALESCE(SUM(CASE WHEN txn_type = 'UDHAAR' THEN amount_paise END), 0),
                      COALESCE(SUM(CASE WHEN txn_type = 'JAMA'   THEN amount_paise END), 0),
                      COALESCE(SUM(({_EFF}) = ?), 0),
                      COALESCE(SUM(({_EFF}) < ?), 0),
                      COUNT(*)
                 FROM transactions""",
            (today, today),
        ).fetchone()
        return DashboardSummary(customers, r[0], r[1], r[2], r[3], r[4])

    # ---- backup / restore -------------------------------------------------
    # ------------------------------------------------------------------ pending (aging) report
    def pending_report(self, min_days: int = 0, search: str = "") -> list[PendingRow]:
        """Customers whose balance is still owed, oldest pending first.

        Deposits are matched to the OLDEST udhaar first (in effective-date order), so "pending since" is
        the date of the oldest udhaar that is not yet covered. A deposit made before any udhaar is held as
        credit and covers the next udhaar. Customers with nothing owed (or an advance) are not listed.
        """
        today = self.today()
        customers = {s.customer.id: s.customer for s in self.list_customers()}
        needle = " ".join((search or "").split()).casefold()
        rows = self.conn.execute(
            f"SELECT customer_id, txn_type, amount_paise, ({_EFF}) AS eff FROM transactions "
            "ORDER BY customer_id, eff, id"
        ).fetchall()
        result: list[PendingRow] = []
        for cid, group in itertools.groupby(rows, key=lambda r: r["customer_id"]):
            customer = customers.get(cid)
            if customer is None:
                continue
            chunks: deque = deque()  # [date, unpaid paise] oldest first
            credit = total_u = total_d = last_amt = 0
            last_dep = None
            for r in group:
                amt = r["amount_paise"]
                if r["txn_type"] == "UDHAAR":
                    total_u += amt
                    used = min(credit, amt)
                    credit -= used
                    amt -= used
                    if amt:
                        chunks.append([r["eff"], amt])
                else:
                    total_d += amt
                    last_dep, last_amt = r["eff"], amt
                    while amt and chunks:
                        take = min(amt, chunks[0][1])
                        chunks[0][1] -= take
                        amt -= take
                        if chunks[0][1] == 0:
                            chunks.popleft()
                    credit += amt
            balance = total_u - total_d
            if balance <= 0 or not chunks:
                continue
            oldest = chunks[0][0]
            days = max(0, (today - date.fromisoformat(oldest)).days)
            if days < min_days:
                continue
            if needle and needle not in customer.name.casefold() and needle not in _digits(customer.mobile) \
                    and needle not in customer.mobile.casefold():
                continue
            result.append(PendingRow(customer, balance, total_u, total_d, oldest, days, last_dep, last_amt))
        result.sort(key=lambda p: (p.oldest_unpaid_date, -p.balance, p.customer.name.casefold()))
        return result

    # ------------------------------------------------------------------ bulk import (old data)
    def import_rows(self, rows: Sequence[dict], dry_run: bool = False) -> ImportReport:
        """Validate many rows (customer + entry) and save them all in one all-or-nothing step.

        Each row: customer, mobile, txn_type, txn_date, item, amount, quantity, rate, notes, deposit_date and an
        optional ``line`` (the spreadsheet line used in messages). Customers are matched by name (ignoring
        case); unknown names are created. Every row is checked with the same rules as normal entry. If any row
        is wrong, NOTHING is saved and every problem is reported. ``dry_run`` only reports.
        """
        existing = {r["name_key"]: r["id"] for r in self.conn.execute("SELECT id, name_key FROM customers")}
        new_customers: dict[str, list] = {}
        used_existing: set[str] = set()
        plan: list[tuple[str, dict, str]] = []
        errors: list = []
        total_u = total_j = 0
        for n, row in enumerate(rows, 1):
            line = row.get("line", n)
            try:
                name = _clean_single_line(row.get("customer"), "Customer name", MAX_NAME)
                mobile = _clean_mobile(row.get("mobile"))
                f = self._prepare_entry(row.get("txn_type"), row.get("txn_date"), row.get("item"), row.get("amount"),
                                        row.get("quantity"), row.get("rate"), row.get("deposit_date"))
                notes = _clean_multiline(row.get("notes", ""), "Notes")
            except ValidationError as exc:
                errors.append((line, str(exc)))
                continue
            key = name.casefold()
            if key in existing:
                used_existing.add(key)
            elif key not in new_customers:
                new_customers[key] = [name, mobile]
            elif mobile and not new_customers[key][1]:
                new_customers[key][1] = mobile
            plan.append((key, f, notes))
            if f["txn_type"] == "UDHAAR":
                total_u += f["amount_paise"]
            else:
                total_j += f["amount_paise"]
        duplicates = 0
        for key, f, _notes in plan:
            cid = existing.get(key)
            if cid is not None and self.conn.execute(
                "SELECT 1 FROM transactions WHERE customer_id=? AND txn_type=? AND txn_date=? AND amount_paise=? "
                "AND item = ? COLLATE NOCASE LIMIT 1", (cid, f["txn_type"], f["txn_date"], f["amount_paise"], f["item"]),
            ).fetchone():
                duplicates += 1
        report = dict(total_rows=len(rows), errors=errors, new_customers=[v[0] for v in new_customers.values()],
                      existing_customers=len(used_existing), total_udhaar=total_u, total_jama=total_j,
                      likely_duplicates=duplicates)
        if dry_run or errors or not plan:
            return ImportReport(imported=0, **report)
        now = self._now_iso()
        try:
            with dbmod.transaction(self.conn):
                for key, (name, mobile) in new_customers.items():
                    cur = self.conn.execute(
                        "INSERT INTO customers(name, name_key, mobile, address, notes, created_at, updated_at) "
                        "VALUES(?, ?, ?, '', '', ?, ?)", (name, key, mobile, now, now))
                    existing[key] = cur.lastrowid
                for key, f, notes in plan:
                    self.conn.execute(
                        "INSERT INTO transactions(customer_id, txn_date, item, quantity, rate_paise, amount_paise, "
                        "txn_type, notes, created_at, updated_at, deposit_date) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (existing[key], f["txn_date"], f["item"], f["quantity"], f["rate_paise"], f["amount_paise"],
                         f["txn_type"], notes, now, now, f["deposit_date"]))
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Import stopped, nothing was saved: {exc}") from None
        return ImportReport(imported=len(plan), **report)

    def create_backup(self, dest_path) -> Path:
        dest = Path(dest_path)
        if dest.resolve() == self.db_path.resolve():
            raise backup_mod.BackupError("Choose a different file than the live database")
        return backup_mod.create_backup(self.conn, dest)

    def restore_backup(self, backup_path, safety_dir=None) -> Path:
        """Validate a backup, snapshot the current data, then replace it.

        Returns the path of the safety backup that was written first.
        """
        source = Path(backup_path)
        if source.resolve() == self.db_path.resolve():
            raise backup_mod.BackupError("That is the live database, not a backup file")
        backup_mod.validate_backup(source)

        safety_dir = Path(safety_dir) if safety_dir else self.db_path.parent / "safety_backups"
        safety_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime("%Y%m%d-%H%M%S")
        safety = safety_dir / f"before-restore-{stamp}.db"
        n = 1
        while safety.exists():
            n += 1
            safety = safety_dir / f"before-restore-{stamp}-{n}.db"
        backup_mod.create_backup(self.conn, safety)

        staged = self.db_path.with_name(self.db_path.name + ".restore-tmp")
        try:
            shutil.copyfile(source, staged)
            dbmod.open_database(staged, premigration_backup=False).close()  # upgrade an older backup
            backup_mod.validate_backup(staged)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise

        self.conn.close()
        try:
            for suffix in ("-wal", "-shm", "-journal"):
                self.db_path.with_name(self.db_path.name + suffix).unlink(missing_ok=True)
            staged.replace(self.db_path)
        except OSError as exc:
            staged.unlink(missing_ok=True)
            self.conn = dbmod.open_database(self.db_path)
            raise backup_mod.BackupError(f"Could not replace the database: {exc}") from exc
        finally:
            if self.conn is None or not _is_open(self.conn):
                self.conn = dbmod.open_database(self.db_path)
        return safety


def _is_open(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1")
        return True
    except sqlite3.ProgrammingError:
        return False
