"""Small reusable Qt widgets and helpers."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDateEdit, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)

from .. import dates, money
from ..service import KhataError

MIN_DATE = QDate(dates.MIN_YEAR, 1, 1)
DISPLAY_FORMAT = "dd-MM-yyyy"

RED = "#FF6B63"  # udhaar / outstanding (soft coral, readable on the dark theme)
GREEN = "#32D74B"  # jama (emerald)


class DateField(QDateEdit):
    """Date picker (calendar popup) that also accepts typing in DD-MM-YYYY."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat(DISPLAY_FORMAT)
        self.setCalendarPopup(True)
        self.setMinimumDate(MIN_DATE)
        self.set_today()

    def set_today(self) -> None:
        today = QDate.currentDate()
        self.setMaximumDate(today)
        self.setDate(today)

    def refresh_limits(self) -> None:
        self.setMaximumDate(QDate.currentDate())

    def text_dmy(self) -> str:
        return self.date().toString(DISPLAY_FORMAT)

    def set_iso(self, iso: str) -> None:
        self.setDate(QDate.fromString(iso, "yyyy-MM-dd"))


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setHighlightSections(False)
    table.setWordWrap(False)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)  # glides instead of jumping a row
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    return table


def set_cell(table: QTableWidget, row: int, col: int, text: str, right: bool = False,
             data=None, color: Optional[str] = None, bold: bool = False) -> QTableWidgetItem:
    from PySide6.QtGui import QBrush, QColor, QFont

    item = QTableWidgetItem(text)
    if right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if color:
        item.setForeground(QBrush(QColor(color)))
    if bold:
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)
    item.setToolTip(text)
    table.setItem(row, col, item)
    return item


def balance_color(paise: int) -> Optional[str]:
    if paise > 0:
        return RED  # customer owes
    if paise < 0:
        return GREEN  # advance / overpaid
    return None


def selected_id(table: QTableWidget, col: int = 0) -> Optional[int]:
    rows = table.selectionModel().selectedRows()
    if not rows:
        return None
    item = table.item(rows[0].row(), col)
    return None if item is None else item.data(Qt.ItemDataRole.UserRole)


def populate_customer_combo(combo: QComboBox, customers, keep_id=None, include_all: bool = False) -> None:
    """Fill a combo with customers; item data = customer id (None for 'All customers')."""
    if keep_id is None and combo.currentIndex() >= 0:
        keep_id = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    if include_all:
        combo.addItem("All customers", None)
    for s in customers:
        combo.addItem(s.customer.name, s.customer.id)
    index = combo.findData(keep_id) if keep_id is not None else -1
    if index >= 0:
        combo.setCurrentIndex(index)
    elif combo.count():
        combo.setCurrentIndex(0)
    combo.blockSignals(False)


def make_customer_combo() -> QComboBox:
    """Searchable customer picker (type part of a name to filter)."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return combo


def customer_id_from_combo(combo: QComboBox) -> int:
    text = combo.currentText().strip()
    if not text:
        raise KhataError("Select a customer")
    index = combo.findText(text, Qt.MatchFlag.MatchFixedString)  # case-insensitive exact match
    if index < 0:
        raise KhataError(f"No customer named '{text}'. Pick one from the list or use '+ New customer'.")
    return combo.itemData(index)


class BulkUdhaarForm(QWidget):
    """Many udhaar items for one customer in one go (like copying a page of the bahi).

    One row per item; every row has its own date (it starts as the common date above and can be edited).
    A new empty row appears by itself when you type in the last one. Save stores all rows together,
    or none of them if any row is wrong.
    """

    HEADERS = ["Date", "Item / Description", "Qty", "Rate (₹)", "Amount (₹)", "Notes"]
    C_DATE, C_ITEM, C_QTY, C_RATE, C_AMOUNT, C_NOTES = range(6)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.customer = make_customer_combo()
        self.new_customer_button = QPushButton("+ New customer")
        self.date = DateField()
        self.date.setToolTip("Common date for all rows. Each row's date can still be changed in the table.")
        top.addWidget(QLabel("Customer"))
        top.addWidget(self.customer, 1)
        top.addWidget(self.new_customer_button)
        top.addWidget(QLabel("Date for all rows"))
        top.addWidget(self.date)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.C_ITEM, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.C_NOTES, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.add_row_button = QPushButton("+ Add row")
        self.remove_row_button = QPushButton("Remove selected row")
        self.remove_row_button.setObjectName("danger")
        self.clear_button = QPushButton("Clear all")
        self.total_label = QLabel("")
        self.total_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #64D2FF;")
        self.save_button = QPushButton("Save all items")
        self.save_button.setObjectName("primary")
        self.save_button.setDefault(True)
        buttons.addWidget(self.add_row_button)
        buttons.addWidget(self.remove_row_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.total_label)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.status = QLabel("")
        self.status.setObjectName("success")
        layout.addWidget(self.status)
        hint = QLabel("Type Qty and Rate and the Amount fills itself, or type just the Amount. "
                      "A new row appears automatically. Dates can be typed as DD-MM-YYYY.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._last_common = self.date.text_dmy()
        self.table.itemChanged.connect(self._on_item_changed)
        self.date.dateChanged.connect(self._on_common_date_changed)
        self.add_row_button.clicked.connect(self._add_row_and_focus)
        self.remove_row_button.clicked.connect(self.remove_selected_rows)
        self.clear_button.clicked.connect(self.clear_rows)
        self.clear_rows()

    # -- rows -------------------------------------------------------------
    def _put(self, row: int, col: int, text: str, right: bool = False, editable: bool = True) -> None:
        item = QTableWidgetItem(text)
        if right:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, col, item)

    def _text(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        return item.text().strip() if item is not None else ""

    def _new_row(self) -> int:
        self._busy = True
        try:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._put(row, self.C_DATE, self.date.text_dmy())
            self._put(row, self.C_ITEM, "")
            self._put(row, self.C_QTY, "", right=True)
            self._put(row, self.C_RATE, "", right=True)
            self._put(row, self.C_AMOUNT, "", right=True)
            self._put(row, self.C_NOTES, "")
        finally:
            self._busy = False
        return row

    def _row_is_blank(self, row: int) -> bool:
        return not any(self._text(row, c) for c in (self.C_ITEM, self.C_QTY, self.C_RATE, self.C_AMOUNT, self.C_NOTES))

    def _ensure_blank_last_row(self) -> None:
        if self.table.rowCount() == 0 or not self._row_is_blank(self.table.rowCount() - 1):
            self._new_row()

    def _add_row_and_focus(self) -> None:
        if self.table.rowCount() == 0 or not self._row_is_blank(self.table.rowCount() - 1):
            self._new_row()
        row = self.table.rowCount() - 1
        self.table.setCurrentCell(row, self.C_ITEM)
        self.table.editItem(self.table.item(row, self.C_ITEM))

    def clear_rows(self) -> None:
        self._busy = True
        try:
            self.table.setRowCount(0)
        finally:
            self._busy = False
        self._new_row()
        self._update_total()

    def remove_selected_rows(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        self._busy = True
        try:
            for row in rows:
                self.table.removeRow(row)
        finally:
            self._busy = False
        self._ensure_blank_last_row()
        self._update_total()

    # -- behaviour --------------------------------------------------------
    def _on_common_date_changed(self, _qdate) -> None:
        new = self.date.text_dmy()
        self._busy = True
        try:
            for row in range(self.table.rowCount()):
                if self._text(row, self.C_DATE) == self._last_common:  # rows the user did not date themselves
                    self._put(row, self.C_DATE, new)
        finally:
            self._busy = False
        self._last_common = new

    def _computed_amount(self, row: int) -> int | None:
        q, r = self._text(row, self.C_QTY), self._text(row, self.C_RATE)
        if q and r:
            try:
                return money.compute_amount_paise(money.parse_quantity(q), money.rupees_to_paise(r, "Rate"))
            except money.MoneyError:
                return None
        return None

    def _row_amount(self, row: int) -> int | None:
        computed = self._computed_amount(row)
        if computed is not None:
            return computed
        text = self._text(row, self.C_AMOUNT)
        if not text:
            return None
        try:
            return money.rupees_to_paise(text)
        except money.MoneyError:
            return None

    def _on_item_changed(self, item) -> None:
        if self._busy:
            return
        row, col = item.row(), item.column()
        if col in (self.C_QTY, self.C_RATE):
            computed = self._computed_amount(row)
            self._busy = True
            try:
                if computed is not None:
                    self._put(row, self.C_AMOUNT, money.plain_amount(computed), right=True, editable=False)
                elif self.table.item(row, self.C_AMOUNT) is not None and \
                        not (self.table.item(row, self.C_AMOUNT).flags() & Qt.ItemFlag.ItemIsEditable):
                    self._put(row, self.C_AMOUNT, "", right=True)  # qty/rate no longer both given: free the amount
            finally:
                self._busy = False
        if row == self.table.rowCount() - 1 and not self._row_is_blank(row):
            self._new_row()
        self._update_total()

    def _update_total(self) -> None:
        total = 0
        count = 0
        for row in range(self.table.rowCount()):
            if self._row_is_blank(row):
                continue
            count += 1
            amount = self._row_amount(row)
            if amount:
                total += amount
        self.total_label.setText(f"{count} items   |   Total udhaar {money.format_inr(total)}" if count else "")

    # -- values -----------------------------------------------------------
    def customer_id(self) -> int:
        return customer_id_from_combo(self.customer)

    def select_customer(self, customer_id: int) -> None:
        index = self.customer.findData(customer_id)
        if index >= 0:
            self.customer.setCurrentIndex(index)

    def entries(self) -> list[dict]:
        """One dict per non-empty row, ready for KhataService.add_transactions."""
        result = []
        for row in range(self.table.rowCount()):
            if self._row_is_blank(row):
                continue
            q, r = self._text(row, self.C_QTY), self._text(row, self.C_RATE)
            both = bool(q and r)
            result.append({
                "row": row + 1,
                "txn_type": "UDHAAR",
                "txn_date": self._text(row, self.C_DATE) or self.date.text_dmy(),
                "item": self._text(row, self.C_ITEM),
                "amount": None if both else self._text(row, self.C_AMOUNT),
                "quantity": q,
                "rate": r,
                "notes": self._text(row, self.C_NOTES),
            })
        return result


class EntryForm(QWidget):
    """Fields of one khata entry. Used by Quick Entry and by the edit dialog."""

    def __init__(self, with_customer: bool, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form = form

        self.customer = QComboBox()
        self.customer.setEditable(True)
        self.customer.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.customer.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.customer.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.customer.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        if with_customer:
            self.new_customer_button = QPushButton("+ New customer")
            row = QHBoxLayout()
            row.addWidget(self.customer, 1)
            row.addWidget(self.new_customer_button)
            form.addRow("Customer", row)

        self.udhaar = QRadioButton("UDHAAR  (customer took on credit)")
        self.jama = QRadioButton("JAMA  (customer paid)")
        self.udhaar.setObjectName("segUdhaar")  # coloured pills: coral for udhaar, emerald for jama
        self.jama.setObjectName("segJama")
        self.udhaar.setChecked(True)
        type_row = QHBoxLayout()
        type_row.addWidget(self.udhaar)
        type_row.addWidget(self.jama)
        type_row.addStretch(1)
        form.addRow("Type", type_row)

        self.date = DateField()
        self.date.setToolTip("Pick a date or type it as DD-MM-YYYY. Past dates are fine for old entries.")
        form.addRow("Transaction date", self.date)

        # Deposit date: the day the money was really received (JAMA only). It follows the transaction
        # date until you change it yourself; previous months and years are fine.
        self.deposit_date = DateField()
        self.deposit_date.setToolTip(
            "The day the deposit was actually received. Old dates (previous months or years) are fine; "
            "the ledger puts the deposit at this date.")
        form.addRow("Deposit date", self.deposit_date)
        self._deposit_label = form.labelForField(self.deposit_date)
        self._deposit_touched = False
        self._syncing = False

        self.item = QLineEdit()
        self.item.setPlaceholderText("e.g. Gold box set, Cartons  (not needed for a deposit)")
        self.item.setMaxLength(200)
        form.addRow("Item / description", self.item)

        self.quantity = QLineEdit()
        self.quantity.setPlaceholderText("optional")
        self.rate = QLineEdit()
        self.rate.setPlaceholderText("optional (₹)")
        qr = QHBoxLayout()
        qr.addWidget(QLabel("Qty"))
        qr.addWidget(self.quantity)
        qr.addWidget(QLabel("× Rate"))
        qr.addWidget(self.rate)
        form.addRow("Quantity × Rate", qr)
        self._qr_layout = qr

        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.00")
        self.amount_hint = QLabel("")
        self.amount_hint.setObjectName("hint")
        amount_row = QHBoxLayout()
        amount_row.addWidget(self.amount, 1)
        amount_row.addWidget(self.amount_hint)
        form.addRow("Amount (₹)", amount_row)

        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(60)
        form.addRow("Notes", self.notes)

        self.quantity.textChanged.connect(self._recalculate)
        self.rate.textChanged.connect(self._recalculate)
        self.date.dateChanged.connect(self._date_changed)
        self.deposit_date.dateChanged.connect(self._deposit_changed)
        self.jama.toggled.connect(self._type_changed)
        self._type_changed()

    # -- behaviour --------------------------------------------------------
    def _set_deposit_date(self, qdate) -> None:
        self._syncing = True
        try:
            self.deposit_date.setDate(qdate)
        finally:
            self._syncing = False

    def _date_changed(self, qdate) -> None:
        if not self._deposit_touched:
            self._set_deposit_date(qdate)

    def _deposit_changed(self, _qdate) -> None:
        if not self._syncing:
            self._deposit_touched = True  # the user chose a deposit date: stop following the transaction date

    def _type_changed(self, *_args) -> None:
        is_jama = self.jama.isChecked()
        # A deposit is just money received: no item, quantity or rate to type (a label is stored for the ledger).
        self._form.setRowVisible(self.item, not is_jama)
        self._form.setRowVisible(self._qr_layout, not is_jama)
        self.deposit_date.setVisible(is_jama)
        if self._deposit_label is not None:
            self._deposit_label.setVisible(is_jama)
        if is_jama and not self._deposit_touched:
            self._set_deposit_date(self.date.date())

    def _recalculate(self) -> None:
        q, r = self.quantity.text().strip(), self.rate.text().strip()
        if q and r:
            try:
                amount = money.compute_amount_paise(money.parse_quantity(q), money.rupees_to_paise(r, "Rate"))
            except money.MoneyError:
                self.amount.setReadOnly(False)
                self.amount_hint.setText("")
                return
            self.amount.setText(money.plain_amount(amount))
            self.amount.setReadOnly(True)
            self.amount_hint.setText("= Qty × Rate")
        else:
            self.amount.setReadOnly(False)
            self.amount_hint.setText("")

    def customer_id(self) -> int:
        text = self.customer.currentText().strip()
        if not text:
            raise KhataError("Select a customer")
        index = self.customer.findText(text, Qt.MatchFlag.MatchFixedString)  # case-insensitive exact match
        if index < 0:
            raise KhataError(f"No customer named '{text}'. Pick one from the list or use '+ New customer'.")
        return self.customer.itemData(index)

    def select_customer(self, customer_id: int) -> None:
        index = self.customer.findData(customer_id)
        if index >= 0:
            self.customer.setCurrentIndex(index)

    def values(self) -> dict:
        both = bool(self.quantity.text().strip() and self.rate.text().strip())
        return {
            "txn_type": "UDHAAR" if self.udhaar.isChecked() else "JAMA",
            "txn_date": self.date.text_dmy(),
            "deposit_date": self.deposit_date.text_dmy() if self.jama.isChecked() else None,
            "item": self.item.text(),
            "amount": None if both else self.amount.text(),
            "quantity": self.quantity.text(),
            "rate": self.rate.text(),
            "notes": self.notes.toPlainText(),
        }

    def set_values(self, txn) -> None:
        # An existing deposit keeps its own saved deposit date even if the transaction date is edited.
        self._deposit_touched = txn.txn_type == "JAMA"
        (self.udhaar if txn.txn_type == "UDHAAR" else self.jama).setChecked(True)
        self.date.setMaximumDate(QDate.currentDate())
        self.deposit_date.setMaximumDate(QDate.currentDate())
        self.date.set_iso(txn.txn_date)
        if txn.txn_type == "JAMA":
            self._set_deposit_date(QDate.fromString(txn.deposit_date or txn.txn_date, "yyyy-MM-dd"))
        self.item.setText(txn.item)
        self.quantity.setText(txn.quantity or "")
        self.rate.setText(money.plain_amount(txn.rate_paise) if txn.rate_paise else "")
        self.amount.setText(money.plain_amount(txn.amount_paise))
        self.notes.setPlainText(txn.notes)
        self._recalculate()

    def clear_for_next(self) -> None:
        """Keep customer, type and date; clear the rest so the next entry can be typed straight away."""
        self.item.clear()
        self.quantity.clear()
        self.rate.clear()
        self.amount.clear()
        self.amount.setReadOnly(False)
        self.amount_hint.setText("")
        self.notes.clear()
        self.item.setFocus()


def fit_columns(table: QTableWidget, stretch_col: int) -> None:
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
