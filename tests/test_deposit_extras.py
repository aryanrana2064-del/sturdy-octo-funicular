"""Extra deposit-date behaviour: editing keeps/clears dates, register export, legacy rows in totals."""
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from tests.helpers import ServiceTestCase
from vx7khata import exports
from vx7khata.service import ValidationError

GENERATED = datetime(2026, 10, 3, 14, 30)


class TestDepositEdits(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.c = self.svc.add_customer("Rahul")
        self.u = self.add(self.c.id, "UDHAAR", "10-01-2025", "Box", "5000")
        self.d = self.add(self.c.id, "JAMA", "01-06-2025", "Cash", "2000", deposit_date="20-01-2025")

    def test_edit_without_a_deposit_date_keeps_the_saved_one(self):
        t = self.svc.update_transaction(self.d.id, "JAMA", "01-06-2025", "Cash", amount="2500")
        self.assertEqual(t.deposit_date, "2025-01-20")
        self.assertEqual(t.amount_paise, 250000)

    def test_blank_deposit_date_on_edit_resets_to_the_entry_date(self):
        t = self.svc.update_transaction(self.d.id, "JAMA", "01-06-2025", "Cash", amount="2000", deposit_date="")
        self.assertEqual(t.deposit_date, "2025-06-01")

    def test_switching_a_deposit_to_udhaar_clears_its_deposit_date(self):
        t = self.svc.update_transaction(self.d.id, "UDHAAR", "01-06-2025", "Cash", amount="2000")
        self.assertIsNone(t.deposit_date)
        with self.assertRaises(ValidationError):
            self.svc.update_transaction(self.d.id, "UDHAAR", "01-06-2025", "Cash", amount="2000",
                                        deposit_date="01-01-2025")

    def test_switching_udhaar_to_deposit_defaults_to_its_date(self):
        t = self.svc.update_transaction(self.u.id, "JAMA", "10-01-2025", "Box", amount="5000")
        self.assertEqual(t.deposit_date, "2025-01-10")

    def test_failed_edit_changes_nothing(self):
        with self.assertRaises(ValidationError):
            self.svc.update_transaction(self.d.id, "JAMA", "01-06-2025", "Cash", amount="2000", deposit_date="31-02-2025")
        self.assertEqual(self.svc.get_transaction(self.d.id).deposit_date, "2025-01-20")


class TestRegisterExport(ServiceTestCase):
    def test_register_workbook_has_deposit_date_and_matches_the_database(self):
        a = self.svc.add_customer("A")
        b = self.svc.add_customer("B")
        self.add(a.id, "UDHAAR", "10-01-2025", "Gold ring", "1000")
        self.add(b.id, "JAMA", "11-06-2025", "Cash", "400", deposit_date="05-02-2025")
        reg = self.svc.register(date_from="01-02-2025", date_to="28-02-2025")
        self.assertEqual([r.customer_name for r in reg.rows], ["B"])  # filtered by deposit date, not entry date
        path = exports.export_register_xlsx(reg, Path(self.tmp.name) / "r.xlsx", generated_at=GENERATED)
        ws = load_workbook(path, data_only=True)["Register"]
        rows = [[c.value for c in row] for row in ws.iter_rows()]
        head = next(r for r in rows if r[0] == "TRANSACTION DATE")
        self.assertEqual(head[5:8], ["UDHAAR (₹)", "TOTAL DEPOSIT (₹)", "DEPOSIT DATE"])
        line = next(r for r in rows if r[1] == "B")
        self.assertEqual(round(float(line[6]) * 100), 40000)
        self.assertEqual(line[7].date().isoformat(), "2025-02-05")


class TestQuickJamaAndMultiItem(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.c = self.svc.add_customer("Rahul")
        self.o = self.svc.add_customer("Amit")

    def test_jama_needs_only_a_date_and_an_amount(self):
        self.clock.advance(60)
        t = self.svc.add_transaction(self.c.id, "JAMA", "05-02-2025", "", amount="750", deposit_date="05-02-2025")
        self.assertEqual(t.item, "Deposit received (Jama)")
        self.assertEqual((t.amount_paise, t.deposit_date, t.txn_date), (75000, "2025-02-05", "2025-02-05"))
        led = self.svc.ledger(self.c.id)
        self.assertEqual((led.total_deposit, led.deposit_balance), (75000, -75000))

    def test_udhaar_still_needs_an_item(self):
        with self.assertRaises(ValidationError):
            self.svc.add_transaction(self.c.id, "UDHAAR", "05-02-2025", "", amount="100")

    def test_many_items_with_their_own_dates_save_together(self):
        self.clock.advance(60)
        txns = self.svc.add_transactions(self.c.id, [
            {"txn_type": "UDHAAR", "txn_date": "10-01-2025", "item": "Gold box", "amount": "1000"},
            {"txn_type": "UDHAAR", "txn_date": "12-01-2025", "item": "Cartons", "quantity": "10", "rate": "25.50"},
            {"txn_type": "UDHAAR", "txn_date": "05-01-2025", "item": "Tape", "amount": "99.50", "notes": "page 3"},
        ])
        self.assertEqual([t.amount_paise for t in txns], [100000, 25500, 9950])
        led = self.svc.ledger(self.c.id)
        self.assertEqual([r.txn.item for r in led.rows], ["Tape", "Gold box", "Cartons"])  # date order
        self.assertEqual([r.balance for r in led.rows], [9950, 109950, 135450])
        self.assertEqual(self.svc.customer_balance(self.o.id), 0)  # nobody else touched

    def test_one_bad_row_saves_nothing_and_names_the_row(self):
        with self.assertRaises(ValidationError) as ctx:
            self.svc.add_transactions(self.c.id, [
                {"row": 1, "txn_type": "UDHAAR", "txn_date": "10-01-2025", "item": "Good", "amount": "100"},
                {"row": 4, "txn_type": "UDHAAR", "txn_date": "10-01-2025", "item": "Bad", "amount": "-5"},
            ])
        self.assertIn("Row 4", str(ctx.exception))
        self.assertEqual(self.svc.ledger(self.c.id).rows, [])

    def test_empty_batch_is_rejected_and_identical_rows_in_one_batch_are_fine(self):
        with self.assertRaises(ValidationError):
            self.svc.add_transactions(self.c.id, [])
        self.clock.advance(60)
        row = {"txn_type": "UDHAAR", "txn_date": "10-01-2025", "item": "Same", "amount": "10"}
        self.svc.add_transactions(self.c.id, [dict(row), dict(row)])
        self.assertEqual(len(self.svc.ledger(self.c.id).rows), 2)
