# VX7 KHATA PRO

Offline customer khata-bahi (udhaar / jama) manager for Windows. Python + PySide6 + SQLite.
Scope is customer khata only: no inventory, stock or billing/POS.

## What is in the box

| Area | Where |
|---|---|
| Database, schema (v3), migrations, FK/indexes | `vx7khata/db.py` |
| Customers, entries, ledger, balances, dashboard | `vx7khata/service.py` |
| Backup / validation / restore | `vx7khata/backup.py` (+ `KhataService.restore_backup`) |
| PDF + Excel exports (SHREEJI BOXES / SJB branded) | `vx7khata/exports.py`, `vx7khata/branding.py` |
| Desktop UI (sidebar shell, Dashboard, Customers, Quick Entry, Multi Udhaar, Quick Jama, Ledger, Reports, Backup) | `vx7khata/ui/` |
| Dark glass theme (one style sheet + palette; UI only) | `vx7khata/ui/theme.py` |
| Tests | `tests/` |
| Windows build (PyInstaller, Inno Setup, CI) | `packaging/`, `.github/workflows/` |

## Run from source

```
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Data is stored in `%APPDATA%\VX7 KHATA PRO\khata.db`. Set `VX7_DATA_DIR` to use another folder (e.g. a USB stick).

## Design decisions worth knowing

* **Money is integer paise.** No floating point anywhere in totals. Amounts accept at most 2 decimals; quantities at most 3.
* **Balances are never stored.** Every total and running balance is computed from the saved rows, so adding, editing or deleting an old entry cannot leave a wrong balance.
* **Three dates, kept apart.** `txn_date` is the transaction date you pick (may be years ago). `deposit_date` (JAMA only) is the day the money was really received; it can be any past date and can be edited. `created_at` is when the row was really entered and is never changed, not even by an edit (`updated_at` records edits).
* **Deposit columns.** `TOTAL DEPOSIT (₹)` holds only the amount deposited on that row; `DEPOSIT BALANCE (₹)` is the running outstanding balance (opening balance + udhaar − deposits, in date order). They are never mixed. Outstanding balance = Total Udhaar − Total Deposit.
* **Ordering.** A deposit counts on its deposit date, an udhaar on its transaction date. Ledger order, date-range filters, opening balances and the dashboard all use that date, then entry order, so same-day entries are stable. Adding, editing or deleting an old deposit re-computes every later balance. Balances only ever use the selected customer's rows.
* **Legacy deposits.** Migration 3 adds `deposit_date` and back-fills each existing deposit with its own entry date; a deposit with no date still works (it falls back to its entry date). A safety copy of your database is written before the upgrade.
* **Entry screens.** *Quick Entry* = one entry (a deposit needs no item). *Udhaar (Multi Item)* = any number of items for one customer in one table, each row with its own editable date, Qty × Rate or Amount, saved all-or-nothing. *Quick Jama* = pick customer and date, type only the amount (the ledger shows "Deposit received (Jama)").
* **Item search keeps true balances.** When you search by item, the running balance column still shows the real account balance.
* **Dates.** Entered/shown as DD-MM-YYYY; future dates are rejected; earliest year 1990.
* **Dashboard.** "Today's transactions" = entries dated today (a deposit counts on its deposit date). "Historical transactions" = entries dated before today.
* **Branding.** Every PDF page carries a large light **SJB** watermark (drawn behind the table), a **SHREEJI BOXES** header, and a footer with the brand, generation time and "Page n of N". Excel files carry SHREEJI BOXES / SJB in the title, the same watermark as a page-header picture (prints behind the data on every page), a very light on-screen background and a branded footer. No website is printed unless you enter one in Backup & Settings.
* **Statement columns (PDF and Excel).** Transaction Date, Item / Description, Udhaar, Total Deposit, Deposit Date, Deposit Balance, Notes, plus Opening Balance, Total Udhaar, Total Deposit and Final Deposit Balance. Quantity × Rate, when entered, is shown under the item description. The Excel statement uses live formulas (running balance, totals, summary) and also stores their results, so previews show the same numbers as the PDF.
* **Negative balance** means the customer has paid in advance. Shown in green; positive (customer owes you) in red.
* **Duplicate protection.** The Save button is disabled while saving, and the service rejects an identical entry (same customer, date, type, item, amount, notes) saved within 10 seconds; the UI then asks whether it is a genuine second entry.
* **Deleting.** Every entry delete needs confirmation. A customer that has entries cannot be deleted (their khata is never destroyed silently).
* **Backup.** Uses SQLite's online-backup API, then re-opens and checks the copy. **Restore** validates the file (SQLite header, integrity check, schema, foreign keys, entry sanity, not from a newer app version), writes a safety copy to `safety_backups\` next to your data, then swaps the file in. Backups from an older schema are upgraded on restore. The pre-upgrade copy of the database is also kept when the app itself upgrades your data file.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest -q tests          # or: python -m unittest discover -s tests -t .
```

`tests/test_acceptance.py` maps one-to-one to acceptance tests A-F (E is also run across two separate Python processes).
`tests/test_deposit_update.py` covers deposit dates, chronological balances, the v2→v3 migration, backups, and reads real PDF/XLSX files back (watermark on every page, headings, totals, Excel/PDF agreement; a LibreOffice recalculation check runs when LibreOffice is installed).
`tests/test_ui_smoke.py` drives the real Qt window headlessly; it is skipped automatically if PySide6 is not installed.

## Build the Windows executable and installer

Requirements: Windows 10/11 (64-bit), Python 3.10+ from python.org, and optionally [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer.

```
packaging\build_windows.bat
```

It creates a venv, installs dependencies, **runs the tests (and stops if they fail)**, builds `dist\VX7 KHATA PRO\VX7 KHATA PRO.exe` with PyInstaller, and builds `dist\installer\VX7_KHATA_PRO_Setup_1.0.0.exe` if Inno Setup is installed.

Manual steps if you prefer:

```
pip install -r requirements-dev.txt
pyinstaller packaging\vx7_khata_pro.spec --noconfirm --clean
ISCC packaging\installer.iss
```

`.github/workflows/windows-build.yml` does the same on GitHub Actions (`windows-latest`) and uploads the exe and installer as artifacts.

Notes: the installer is unsigned, so Windows SmartScreen may warn on first run. Uninstalling does not delete your data in `%APPDATA%\VX7 KHATA PRO`.

## Known limitations

* **PDF text rendering** uses the bundled DejaVu Sans font. English text and the rupee sign are fine. ReportLab does not do complex-script shaping, so Hindi (Devanagari) item names will not shape correctly in PDFs. They are stored, shown in the app and exported to Excel correctly. If you need Hindi in PDFs, use the Excel export, or tell me and I will switch the PDF engine.
* One customer name must be unique (case-insensitive). Add a locality to tell two people apart ("Rahul (Market Road)").
* Single user, single machine. Two people editing one data file over a network share is not supported.

## Look and feel

The interface uses an iOS-style frosted-glass theme defined in `vx7khata/ui/theme.py`: translucent panels with light edges on a deep gradient backdrop with soft coloured light blobs (painted once per resize, no timers), iOS system colours, pill buttons and large corner radii. Navigation is a sidebar (it turns into an icon rail on narrow windows). Animations are small and light: page fade, card lift on hover, dashboard numbers counting up to the exact saved figure, a glow on hovered action buttons, a smoothly collapsing sidebar (☰ button), a "✓ Saved" toast, and pixel-smooth table scrolling and are switched off by setting the environment variable `VX7_NO_ANIM=1`. The theme changes appearance only: data, database and calculations are untouched.

## Pending list, reminders, WhatsApp and import

* **Pending tab.** Customers who still owe money, oldest first. Deposits are matched to the oldest udhaar first, so *Pending since* is the date of the oldest udhaar not yet covered. The "Pending for" filter (default 30+ days) also drives the reminder banner on the Dashboard. Buttons: WhatsApp reminder, Add jama, Open ledger.
* **WhatsApp.** *WhatsApp statement* (Ledger) saves the PDF and opens the customer's chat with the message typed; *WhatsApp reminder* (Pending) does the same with a reminder text. WhatsApp cannot accept a file from another program (that needs the paid WhatsApp Business API), so attach the saved PDF with the 📎 button. Numbers of 10 digits are treated as Indian (+91).
* **Import old data.** Backup & Settings → *Download template* / *Import file…* (.xlsx or .csv). Headers are matched by name (English or Hindi). All rows are checked first; nothing is imported unless every row is valid, a safety copy is saved before importing, and entries that look like ones already saved are flagged.
