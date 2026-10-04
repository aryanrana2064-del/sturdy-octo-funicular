"""UI smoke test. Runs only where PySide6 is installed (it is skipped otherwise).

    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_ui_smoke -v
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class TestUiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from vx7khata.service import KhataService
        from vx7khata.ui.main_window import MainWindow

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svc = KhataService(os.path.join(self.tmp.name, "khata.db"))
        self.addCleanup(self.svc.close)
        self.win = MainWindow(self.svc)
        self.addCleanup(self.win.close)
        self.messages = []
        self.answers = []  # scripted answers for confirm()
        self.win.warn = lambda title, text: self.messages.append(("warn", text))
        self.win.info = lambda title, text: self.messages.append(("info", text))
        self.win.confirm = lambda *a, **k: self.answers.pop(0) if self.answers else True

    def _select_customer(self, customer_id):
        self.win.entry_form.select_customer(customer_id)

    def _enter(self, kind, qdate, item, amount):
        form = self.win.entry_form
        (form.udhaar if kind == "UDHAAR" else form.jama).setChecked(True)
        form.date.setDate(qdate)
        form.item.setText(item)
        form.amount.setText(amount)
        self.win._save_entry()

    def _show_ledger(self, customer_id):
        self.win.ledger_customer.setCurrentIndex(self.win.ledger_customer.findData(customer_id))
        self.win._refresh_ledger()

    def test_empty_window(self):
        self.assertEqual(self.win.cards["customers"].value.text(), "0")
        self.assertEqual(self.win.cust_table.rowCount(), 0)

    def test_backdated_entries_through_the_form(self):
        c = self.svc.add_customer("Rahul")
        self.win.refresh_all()
        self._select_customer(c.id)
        self._enter("UDHAAR", QDate(2025, 1, 10), "Old udhaar", "5000")
        self._enter("JAMA", QDate(2025, 1, 15), "Payment", "2000")
        self._enter("UDHAAR", QDate(2025, 1, 12), "Extra", "1000")
        self.assertEqual(self.messages, [])

        self._show_ledger(c.id)
        table = self.win.ledger_table
        self.assertEqual(table.rowCount(), 3)
        self.assertEqual([table.item(r, 0).text() for r in range(3)], ["10-01-2025", "12-01-2025", "15-01-2025"])
        self.assertEqual([table.item(r, 7).text() for r in range(3)], ["5,000.00", "6,000.00", "4,000.00"])  # deposit balance
        self.assertEqual(self.win.cards["net"].value.text(), "₹4,000.00")
        self.assertEqual(self.win.cards["historical"].value.text(), "3")
        self.assertEqual(self.win.cust_table.item(0, 5).text(), "₹4,000.00")

    def test_deposit_date_follows_transaction_date_until_changed_and_is_saved(self):
        c = self.svc.add_customer("Rahul")
        self.win.refresh_all()
        self._select_customer(c.id)
        self._enter("UDHAAR", QDate(2025, 1, 10), "Old udhaar", "5000")
        form = self.win.entry_form
        form.udhaar.setChecked(True)
        self.assertTrue(form.deposit_date.isHidden())  # deposit date only applies to a deposit
        form.jama.setChecked(True)
        self.assertFalse(form.deposit_date.isHidden())
        form.date.setDate(QDate(2025, 6, 1))
        self.assertEqual(form.deposit_date.date(), QDate(2025, 6, 1))  # follows the transaction date ...
        form.deposit_date.setDate(QDate(2025, 1, 20))  # ... until the user picks the real date
        form.date.setDate(QDate(2025, 6, 2))
        self.assertEqual(form.deposit_date.date(), QDate(2025, 1, 20))
        form.item.setText("Cash received")
        form.amount.setText("2000")
        self.win._save_entry()
        self.assertEqual(self.messages, [])
        self._show_ledger(c.id)
        table = self.win.ledger_table
        self.assertEqual([table.item(r, 6).text() for r in range(2)], ["", "20-01-2025"])  # deposit date column
        self.assertEqual([table.item(r, 5).text() for r in range(2)], ["", "2,000.00"])  # total deposit column
        self.assertEqual([table.item(r, 7).text() for r in range(2)], ["5,000.00", "3,000.00"])  # balance column
        self.assertEqual(self.svc.get_transaction(self.svc.ledger(c.id).rows[1].txn.id).txn_date, "2025-06-02")

    def test_quantity_times_rate_autofills_amount(self):
        form = self.win.entry_form
        form.quantity.setText("3")
        form.rate.setText("200")
        self.assertEqual(form.amount.text(), "600.00")
        self.assertTrue(form.amount.isReadOnly())

    def test_duplicate_submission_asks_before_saving_again(self):
        c = self.svc.add_customer("Rahul")
        self.win.refresh_all()
        self._select_customer(c.id)
        self._enter("UDHAAR", QDate(2025, 1, 10), "Chain", "100")
        self.answers = [False]  # user declines the "possible duplicate" prompt
        self._enter("UDHAAR", QDate(2025, 1, 10), "Chain", "100")
        self.assertEqual(len(self.svc.ledger(c.id).rows), 1)

    def test_delete_requires_confirmation_and_recalculates(self):
        c = self.svc.add_customer("Rahul")
        self.svc.add_transaction(c.id, "UDHAAR", "10-01-2025", "A", amount="100")
        self.svc.add_transaction(c.id, "UDHAAR", "11-01-2025", "B", amount="200")
        self.win.refresh_all()
        self._show_ledger(c.id)
        self.win.ledger_table.selectRow(0)
        self.answers = [False]
        self.win._delete_entry()
        self.assertEqual(len(self.svc.ledger(c.id).rows), 2)  # declined: nothing deleted
        self.answers = [True]
        self.win._delete_entry()
        self.assertEqual(self.svc.ledger(c.id).closing_balance, 20000)
        self.assertEqual(self.win.ledger_table.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
