"""Dialogs: customer add/edit, entry edit."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from ..service import Customer, KhataError, KhataService, Transaction
from .widgets import EntryForm


class CustomerDialog(QDialog):
    def __init__(self, service: KhataService, customer: Customer | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.customer = customer
        self.saved: Customer | None = None
        self.setWindowTitle("Edit customer" if customer else "Add customer")
        self.setMinimumWidth(440)

        self.name = QLineEdit(customer.name if customer else "")
        self.name.setMaxLength(120)
        self.mobile = QLineEdit(customer.mobile if customer else "")
        self.mobile.setPlaceholderText("optional")
        self.address = QPlainTextEdit(customer.address if customer else "")
        self.address.setFixedHeight(64)
        self.notes = QPlainTextEdit(customer.notes if customer else "")
        self.notes.setFixedHeight(64)

        form = QFormLayout()
        form.addRow("Name *", self.name)
        form.addRow("Mobile", self.mobile)
        form.addRow("Address", self.address)
        form.addRow("Notes", self.notes)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.name.setFocus()

    def _save(self) -> None:
        args = (self.name.text(), self.mobile.text(), self.address.toPlainText(), self.notes.toPlainText())
        try:
            if self.customer:
                self.saved = self.service.update_customer(self.customer.id, *args)
            else:
                self.saved = self.service.add_customer(*args)
        except KhataError as exc:
            QMessageBox.warning(self, "Cannot save customer", str(exc))
            return
        self.accept()


class EditEntryDialog(QDialog):
    """Edit date, amount, type, item description, notes (and qty/rate) of a saved entry."""

    def __init__(self, service: KhataService, txn: Transaction, customer_name: str, parent=None):
        super().__init__(parent)
        self.service = service
        self.txn = txn
        self.saved: Transaction | None = None
        self.setWindowTitle(f"Edit entry – {customer_name}")
        self.setMinimumWidth(560)

        self.form = EntryForm(with_customer=False)
        self.form.set_values(txn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        layout.addWidget(buttons)

    def _save(self) -> None:
        try:
            self.saved = self.service.update_transaction(self.txn.id, **self.form.values())
        except KhataError as exc:
            QMessageBox.warning(self, "Cannot save entry", str(exc))
            return
        self.accept()
