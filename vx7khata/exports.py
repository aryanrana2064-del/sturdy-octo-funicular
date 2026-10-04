"""PDF and Excel statements / reports, branded SHREEJI BOXES (mark: SJB).

Everything exported comes from the Ledger / Register / customer-summary objects built from the saved
database, so the PDF and the Excel file always show the same numbers.

Branding
* PDF: a large light SJB watermark is drawn first on EVERY page (so it sits behind the table), with a
  SHREEJI BOXES header band and a footer carrying the brand, the generation time and "Page n of N".
* Excel: SHREEJI BOXES / SJB in the sheet title, the same watermark picture as a page-header picture
  (prints behind the data on every printed page), a very light tiled sheet background for on-screen
  viewing, and a SHREEJI BOXES footer with page numbers.
* A website is printed only when one is passed in (configured in Backup & Settings).

Money: "TOTAL DEPOSIT (₹)" holds the amount deposited on that row only; "DEPOSIT BALANCE (₹)" is the
running outstanding balance (opening balance + udhaar - deposits, in date order) - never mixed.
"""
from __future__ import annotations

import os
import re
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, Sequence
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import APP_NAME, branding, dates, money
from .service import CustomerSummary, Ledger, Register

PAGE_W, PAGE_H = landscape(A4)
MARGIN_X = 12 * mm
WATERMARK_PT = 230  # font size of the big SJB on each PDF page

# --------------------------------------------------------------------------- common
_FONTS: Optional[tuple[str, str, str]] = None


def _fonts() -> tuple[str, str, str]:
    """(regular, bold, currency symbol). Uses the bundled DejaVu Sans so the rupee sign prints."""
    global _FONTS
    if _FONTS is None:
        base = Path(__file__).resolve().parent / "assets" / "fonts"
        regular, bold = base / "DejaVuSans.ttf", base / "DejaVuSans-Bold.ttf"
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("VX7Sans", str(regular)))
            pdfmetrics.registerFont(TTFont("VX7Sans-Bold", str(bold)))
            pdfmetrics.registerFontFamily("VX7Sans", normal="VX7Sans", bold="VX7Sans-Bold")
            _FONTS = ("VX7Sans", "VX7Sans-Bold", "₹")
        else:  # font files missing: still produce a correct PDF, with "Rs." instead of the rupee sign
            _FONTS = ("Helvetica", "Helvetica-Bold", "Rs.")
    return _FONTS


def _period_text(date_from: Optional[str], date_to: Optional[str]) -> str:
    if not date_from and not date_to:
        return "All dates"
    start = dates.format_date(date_from) if date_from else "Beginning"
    end = dates.format_date(date_to) if date_to else "Latest"
    return f"{start} to {end}"


def _stamp(generated_at: Optional[datetime] = None) -> str:
    return (generated_at or datetime.now()).strftime("%d-%m-%Y %H:%M")


def _tmp_path(path: Path) -> Path:
    return path.with_name(path.name + ".part")


def _qty_rate_text(quantity: Optional[str], rate_paise: Optional[int], sym: str) -> str:
    """'Qty 3 × Rate ₹200.00' - kept in the description so the 7-column statement loses nothing."""
    parts = []
    if quantity:
        parts.append(f"Qty {quantity}")
    if rate_paise:
        parts.append(f"Rate {sym}{money.format_inr(rate_paise, symbol=False)}")
    return " × ".join(parts)


def _inr(paise: int, sym: str = "₹") -> str:
    """₹1,234.00 / -₹300.00 using the symbol that the active PDF font can print."""
    text = money.format_inr(abs(paise), symbol=False)
    return f"-{sym}{text}" if paise < 0 else f"{sym}{text}"


def _show_shop(shop_name: str) -> str:
    """The optional business name from Settings, shown as a secondary line (never replaces the brand)."""
    name = " ".join((shop_name or "").split())
    return "" if not name or name.casefold() in (branding.BRAND_NAME.casefold(), APP_NAME.casefold()) else name


# --------------------------------------------------------------------------- PDF
def _hex(value: str):
    return colors.HexColor(value)


def _pdf_doc(path: Path, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path), pagesize=landscape(A4), leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=28 * mm, bottomMargin=17 * mm, title=title, author=branding.BRAND_NAME,
        creator=APP_NAME,
    )


def _draw_watermark(canvas, bold: str) -> None:
    """Large light SJB, diagonal, centred. Solid light tint (no transparency) so it survives any printer."""
    canvas.saveState()
    canvas.setFillColor(_hex(branding.WATERMARK_TINT))
    canvas.setFont(bold, WATERMARK_PT)
    canvas.translate(PAGE_W / 2, PAGE_H / 2)
    canvas.rotate(30)
    canvas.drawCentredString(0, -WATERMARK_PT * 0.36, branding.BRAND_MARK)
    canvas.restoreState()


def _draw_header(canvas, font: str, bold: str, title: str, subtitle: str) -> None:
    top = PAGE_H
    canvas.saveState()
    # monogram badge
    canvas.setFillColor(_hex(branding.NAVY))
    canvas.roundRect(MARGIN_X, top - 19.5 * mm, 15 * mm, 10 * mm, 1.6 * mm, stroke=0, fill=1)
    canvas.setFillColor(_hex(branding.GOLD))
    canvas.setFont(bold, 10)
    canvas.drawCentredString(MARGIN_X + 7.5 * mm, top - 16.4 * mm, branding.BRAND_MARK)
    # brand name
    canvas.setFillColor(_hex(branding.NAVY))
    canvas.setFont(bold, 17)
    canvas.drawString(MARGIN_X + 19 * mm, top - 16.6 * mm, branding.BRAND_NAME)
    # report title (right)
    canvas.setFont(bold, 11)
    canvas.drawRightString(PAGE_W - MARGIN_X, top - 13.6 * mm, title)
    if subtitle:
        canvas.setFont(font, 8)
        canvas.setFillColor(_hex("#555555"))
        canvas.drawRightString(PAGE_W - MARGIN_X, top - 18.2 * mm, subtitle)
    # gold rule + hairline
    canvas.setStrokeColor(_hex(branding.GOLD))
    canvas.setLineWidth(1.6)
    canvas.line(MARGIN_X, top - 22.2 * mm, PAGE_W - MARGIN_X, top - 22.2 * mm)
    canvas.setStrokeColor(_hex(branding.NAVY))
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN_X, top - 23.2 * mm, PAGE_W - MARGIN_X, top - 23.2 * mm)
    canvas.restoreState()


def _numbered_canvas(font: str, bold: str, stamp: str, website: str):
    """Canvas class that writes the footer with 'Page n of N' once the page count is known."""

    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages: list[dict] = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self._draw_footer(total)
                super().showPage()
            super().save()

        def _draw_footer(self, total: int) -> None:
            self.saveState()
            self.setStrokeColor(_hex(branding.GOLD))
            self.setLineWidth(0.8)
            self.line(MARGIN_X, 12.5 * mm, PAGE_W - MARGIN_X, 12.5 * mm)
            y = 8 * mm
            self.setFillColor(_hex(branding.NAVY))
            self.setFont(bold, 8.5)
            self.drawString(MARGIN_X, y, branding.BRAND_NAME)
            x = MARGIN_X + pdfmetrics.stringWidth(branding.BRAND_NAME, bold, 8.5)
            self.setFillColor(_hex("#555555"))
            self.setFont(font, 8)
            tail = f"   |   Generated {stamp} by {APP_NAME}"
            if website:
                tail += f"   |   {website}"
            self.drawString(x, y, tail)
            self.setFont(font, 8.5)
            self.drawRightString(PAGE_W - MARGIN_X, y, f"Page {self._pageNumber} of {total}")
            self.restoreState()

    return NumberedCanvas


def _styles(font: str, bold: str) -> dict[str, ParagraphStyle]:
    return {
        "sub": ParagraphStyle("s", fontName=font, fontSize=9.5, leading=13, textColor=_hex("#333333")),
        "cell": ParagraphStyle("c", fontName=font, fontSize=8.5, leading=10.5),
        "cellb": ParagraphStyle("cb", fontName=bold, fontSize=8.5, leading=10.5),
        "th": ParagraphStyle("th", fontName=bold, fontSize=7.8, leading=9.6, alignment=TA_CENTER,
                             textColor=colors.white),
        "box": ParagraphStyle("box", fontName=font, fontSize=8, leading=15),
        "note": ParagraphStyle("note", fontName=font, fontSize=8, leading=11, textColor=_hex("#555555")),
    }


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


def _item_para(item: str, quantity: Optional[str], rate_paise: Optional[int], sym: str, st) -> Paragraph:
    markup = escape(item or "").replace("\n", "<br/>")
    extra = _qty_rate_text(quantity, rate_paise, sym)
    if extra:
        markup += f'<br/><font size="7" color="#6B7280">{escape(extra)}</font>'
    return Paragraph(markup, st["cell"])


def _heads(headings: Sequence[str], st) -> list:
    return [Paragraph(escape(h), st["th"]) for h in headings]


def _table_style(font: str, bold: str, numeric_cols: Sequence[int], centre_cols: Sequence[int],
                 opening_row: Optional[int], total_rows: Sequence[int], final_cell: Optional[tuple[int, int]]):
    """Transparent body (so the watermark shows through); only header and total rows are filled."""
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), _hex(branding.TABLE_NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, _hex("#B8BFC9")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, _hex(branding.GOLD)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for col in numeric_cols:
        cmds.append(("ALIGN", (col, 1), (col, -1), "RIGHT"))
    for col in centre_cols:
        cmds.append(("ALIGN", (col, 1), (col, -1), "CENTER"))
    if opening_row is not None:
        cmds.append(("BACKGROUND", (0, opening_row), (-1, opening_row), colors.Color(0.12, 0.23, 0.37, alpha=0.06)))
        cmds.append(("FONTNAME", (0, opening_row), (-1, opening_row), bold))
    for row in total_rows:
        cmds.append(("BACKGROUND", (0, row), (-1, row), colors.Color(0.69, 0.55, 0.24, alpha=0.16)))
        cmds.append(("FONTNAME", (0, row), (-1, row), bold))
        cmds.append(("LINEABOVE", (0, row), (-1, row), 1.2, _hex(branding.NAVY)))
    if final_cell is not None:
        cmds.append(("TEXTCOLOR", final_cell, final_cell, _hex(branding.NAVY)))
        cmds.append(("FONTSIZE", final_cell, final_cell, 9.5))
    return TableStyle(cmds)


def _summary_boxes(items: Sequence[tuple[str, str]], st, bold: str) -> Table:
    """Strip of label-over-value boxes (Opening Balance, Total Udhaar, Total Deposit, Final Deposit Balance)."""
    cells = [
        Paragraph(
            f'<font size="8" color="#6B6B6B">{escape(label)}</font><br/>'
            f'<font name="{bold}" size="12.5" color="{branding.NAVY}">{escape(value)}</font>', st["box"])
        for label, value in items
    ]
    table = Table([cells], colWidths=[(PAGE_W - 2 * MARGIN_X) / len(cells)] * len(cells), hAlign="LEFT")
    cmds = [
        ("BOX", (0, 0), (-1, -1), 0.6, _hex("#B8BFC9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
    ]
    for i in range(len(cells)):
        cmds.append(("LINEBEFORE", (i, 0), (i, 0), 2.4, _hex(branding.GOLD)))
    table.setStyle(TableStyle(cmds))
    return table


def _build_pdf(path: Path, doc: SimpleDocTemplate, story: list, font: str, bold: str,
               title: str, subtitle: str, stamp: str, website: str) -> Path:
    path = Path(path)
    tmp = _tmp_path(path)
    doc.filename = str(tmp)

    def decorate(canvas, _doc):
        _draw_watermark(canvas, bold)  # first, so it is behind everything else on the page
        _draw_header(canvas, font, bold, title, subtitle)

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate,
              canvasmaker=_numbered_canvas(font, bold, stamp, website))
    os.replace(tmp, path)
    return path


def _details_block(left: list[str], right: list[str], st) -> Table:
    def cell(lines):
        return [Paragraph(line, st["sub"]) for line in lines]

    half = (PAGE_W - 2 * MARGIN_X) / 2
    table = Table([[cell(left), cell(right)]], colWidths=[half, half], hAlign="LEFT")
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _check_reconciles(ledger: Ledger) -> None:
    """Internal guard: Outstanding = opening + Total Udhaar - Total Deposit (when no item filter hides rows)."""
    if not ledger.search and ledger.opening_balance + ledger.total_udhaar - ledger.total_jama != ledger.closing_balance:
        raise RuntimeError("Ledger totals do not reconcile; refusing to export inconsistent figures")


def export_statement_pdf(ledger: Ledger, path, shop_name: str = "", *, website: str = "",
                         generated_at: Optional[datetime] = None) -> Path:
    _check_reconciles(ledger)
    font, bold, sym = _fonts()
    st = _styles(font, bold)
    stamp = _stamp(generated_at)
    path = Path(path)
    c = ledger.customer
    doc = _pdf_doc(path, f"Statement - {c.name}")

    left = [f"<b>Customer:</b> {escape(c.name)}"]
    if c.mobile:
        left.append(f"<b>Mobile:</b> {escape(c.mobile)}")
    if c.address:
        left.append(f"<b>Address:</b> {escape(c.address).replace(chr(10), '<br/>')}")
    right = [f"<b>Period:</b> {_period_text(ledger.date_from, ledger.date_to)}",
             f"<b>Report generated:</b> {stamp}",
             f"<b>Entries listed:</b> {len(ledger.rows)}"]
    if ledger.search:
        right.append(f"<b>Item filter:</b> {escape(ledger.search)} "
                     "<i>(balances shown are the true account balance)</i>")
    story: list = [_details_block(left, right, st), Spacer(1, 4 * mm)]
    story.append(_summary_boxes([
        ("Opening Balance", _inr(ledger.opening_balance, sym)),
        ("Total Udhaar", _inr(ledger.total_udhaar, sym)),
        ("Total Deposit", _inr(ledger.total_deposit, sym)),
        ("Final Deposit Balance", _inr(ledger.deposit_balance, sym)),
    ], st, bold))
    story.append(Spacer(1, 4 * mm))

    headings = ["TRANSACTION DATE", "ITEM / DESCRIPTION", f"UDHAAR ({sym})", f"TOTAL DEPOSIT ({sym})",
                "DEPOSIT DATE", f"DEPOSIT BALANCE ({sym})", "NOTES"]
    data: list[list] = [_heads(headings, st)]
    data.append(["", _para("Opening Balance", st["cellb"]), "", "", "", _inr_plain(ledger.opening_balance), ""])
    for row in ledger.rows:
        t = row.txn
        data.append([
            dates.format_date(t.txn_date), _item_para(t.item, t.quantity, t.rate_paise, sym, st),
            money.format_inr(row.udhaar, symbol=False) if row.udhaar else "",
            money.format_inr(row.deposit, symbol=False) if row.deposit else "",
            dates.format_date(row.deposit_date) if row.deposit_date else "",
            _inr_plain(row.balance), _para(t.notes, st["cell"]),
        ])
    data.append(["", _para("TOTAL", st["cellb"]), _inr_plain(ledger.total_udhaar), _inr_plain(ledger.total_deposit),
                 "", _inr_plain(ledger.deposit_balance), ""])
    widths = [30, 62, 30, 32, 26, 34, 59]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    last = len(data) - 1
    table.setStyle(_table_style(font, bold, [2, 3, 5], [0, 4], 1, [last], (5, last)))
    story.append(table)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "Deposit Balance = Total Udhaar - Total Deposit, running in date order (a deposit counts on its Deposit "
        "Date). Positive balance = customer owes; negative = advance / overpaid.", st["note"]))
    return _build_pdf(path, doc, story, font, bold, "CUSTOMER STATEMENT", _show_shop(shop_name),
                      stamp, website)


def _inr_plain(paise: int) -> str:
    return money.format_inr(paise, symbol=False)


def export_register_pdf(register: Register, path, shop_name: str = "", customer_label: str = "All customers", *,
                        website: str = "", generated_at: Optional[datetime] = None) -> Path:
    font, bold, sym = _fonts()
    st = _styles(font, bold)
    stamp = _stamp(generated_at)
    path = Path(path)
    doc = _pdf_doc(path, "Transaction Register")
    left = [f"<b>Customers:</b> {escape(customer_label)}", f"<b>Period:</b> {_period_text(register.date_from, register.date_to)}"]
    right = [f"<b>Report generated:</b> {stamp}", f"<b>Entries listed:</b> {len(register.rows)}"]
    if register.search:
        right.append(f"<b>Item filter:</b> {escape(register.search)}")
    story: list = [_details_block(left, right, st), Spacer(1, 4 * mm)]
    story.append(_summary_boxes([
        ("Total Udhaar", _inr(register.total_udhaar, sym)),
        ("Total Deposit", _inr(register.total_deposit, sym)),
        ("Net Outstanding (Udhaar - Deposit)", _inr(register.net, sym)),
    ], st, bold))
    story.append(Spacer(1, 4 * mm))

    headings = ["TRANSACTION DATE", "CUSTOMER", "ITEM / DESCRIPTION", "QTY", f"RATE ({sym})", f"UDHAAR ({sym})",
                f"TOTAL DEPOSIT ({sym})", "DEPOSIT DATE", "NOTES"]
    data: list[list] = [_heads(headings, st)]
    for row in register.rows:
        t = row.txn
        is_dep = t.txn_type == "JAMA"
        dep_date = (t.deposit_date or t.txn_date) if is_dep else None
        data.append([
            dates.format_date(t.txn_date), _para(row.customer_name, st["cell"]), _para(t.item, st["cell"]),
            t.quantity or "", money.format_inr(t.rate_paise, symbol=False) if t.rate_paise else "",
            "" if is_dep else _inr_plain(t.amount_paise), _inr_plain(t.amount_paise) if is_dep else "",
            dates.format_date(dep_date) if dep_date else "", _para(t.notes, st["cell"]),
        ])
    data.append(["", _para("TOTAL", st["cellb"]), "", "", "", _inr_plain(register.total_udhaar),
                 _inr_plain(register.total_deposit), "", ""])
    data.append(["", _para("Net outstanding (udhaar - deposit)", st["cellb"]), "", "", "", _inr_plain(register.net),
                 "", "", ""])
    widths = [30, 36, 48, 14, 22, 26, 28, 24, 45]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(_table_style(font, bold, [3, 4, 5, 6], [0, 7], None, [len(data) - 2, len(data) - 1], None))
    story.append(table)
    return _build_pdf(path, doc, story, font, bold, "TRANSACTION REGISTER", _show_shop(shop_name), stamp, website)


def export_customers_pdf(summaries: Sequence[CustomerSummary], path, shop_name: str = "", filter_text: str = "", *,
                         website: str = "", generated_at: Optional[datetime] = None) -> Path:
    font, bold, sym = _fonts()
    st = _styles(font, bold)
    stamp = _stamp(generated_at)
    path = Path(path)
    doc = _pdf_doc(path, "Customer Balances")
    left = [f"<b>As on:</b> {(generated_at or datetime.now()).strftime('%d-%m-%Y')}"]
    if filter_text:
        left.append(f"<b>Customer filter:</b> {escape(filter_text)}")
    right = [f"<b>Report generated:</b> {stamp}", f"<b>Customers listed:</b> {len(summaries)}"]
    tu = sum(s.total_udhaar for s in summaries)
    td = sum(s.total_deposit for s in summaries)
    story: list = [_details_block(left, right, st), Spacer(1, 4 * mm)]
    story.append(_summary_boxes([
        ("Total Udhaar", _inr(tu, sym)), ("Total Deposit", _inr(td, sym)),
        ("Final Deposit Balance", _inr(tu - td, sym)),
    ], st, bold))
    story.append(Spacer(1, 4 * mm))
    headings = ["#", "CUSTOMER", "MOBILE", "ENTRIES", f"TOTAL UDHAAR ({sym})", f"TOTAL DEPOSIT ({sym})",
                f"DEPOSIT BALANCE ({sym})"]
    data: list[list] = [_heads(headings, st)]
    for i, s in enumerate(summaries, 1):
        data.append([str(i), _para(s.customer.name, st["cell"]), s.customer.mobile, str(s.txn_count),
                     _inr_plain(s.total_udhaar), _inr_plain(s.total_deposit), _inr_plain(s.balance)])
    data.append(["", _para("Overall total", st["cellb"]), "", "", _inr_plain(tu), _inr_plain(td), _inr_plain(tu - td)])
    widths = [10, 68, 36, 18, 46, 46, 49]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    last = len(data) - 1
    table.setStyle(_table_style(font, bold, [3, 4, 5, 6], [0], None, [last], (6, last)))
    story.append(table)
    return _build_pdf(path, doc, story, font, bold, "CUSTOMER BALANCE SUMMARY", _show_shop(shop_name), stamp, website)


# --------------------------------------------------------------------------- Excel
_HEADER_FILL = PatternFill("solid", fgColor=branding.TABLE_NAVY.lstrip("#"))
_TOTAL_FILL = PatternFill("solid", fgColor=branding.GOLD_TINT.lstrip("#"))
_FINAL_FILL = PatternFill("solid", fgColor=branding.NAVY.lstrip("#"))
_THIN = Side(style="thin", color="B8BFC9")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_GOLD_RULE = Border(bottom=Side(style="medium", color=branding.GOLD.lstrip("#")))
_INR_FMT = "[$₹-4009] #,##0.00;[Red]-[$₹-4009] #,##0.00"
_DATE_FMT = "dd-mm-yyyy"
_NAVY_HEX = branding.NAVY.lstrip("#")
_GOLD_HEX = branding.GOLD.lstrip("#")


class _Cache:
    """Cached results of formulas, written into the file so previews and other readers show numbers."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def formula(self, ws, row: int, col: int, formula: str, paise: int, bold: bool = False):
        cell = ws.cell(row=row, column=col, value=formula)
        self.values[cell.coordinate] = str(money.paise_to_decimal(paise))
        cell.number_format = _INR_FMT
        cell.alignment = Alignment(horizontal="right", vertical="top")
        if bold:
            cell.font = Font(bold=True)
        return cell


def _text(ws, row: int, col: int, value: str, bold: bool = False, wrap: bool = False):
    cell = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        cell.data_type = "s"  # never let user text be interpreted as a formula
    if bold:
        cell.font = Font(bold=True)
    if wrap:
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    return cell


def _money(ws, row: int, col: int, paise: Optional[int], bold: bool = False):
    cell = ws.cell(row=row, column=col)
    if paise is not None:
        cell.value = money.paise_to_decimal(paise)
        cell.number_format = _INR_FMT
    cell.alignment = Alignment(horizontal="right", vertical="top")
    if bold:
        cell.font = Font(bold=True)
    return cell


def _date_cell(ws, row: int, col: int, iso: str):
    cell = ws.cell(row=row, column=col, value=dates.to_date(iso))
    cell.number_format = _DATE_FMT
    cell.alignment = Alignment(horizontal="center", vertical="top")


def _qty_cell(ws, row: int, col: int, quantity: Optional[str]):
    cell = ws.cell(row=row, column=col)
    if quantity:
        cell.value = Decimal(quantity)
        cell.number_format = "0.###"
    cell.alignment = Alignment(horizontal="right", vertical="top")


def _header_row(ws, row: int, headers: Sequence[str]) -> None:
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = _BORDER
    ws.row_dimensions[row].height = 32


def _style_range(ws, first_row: int, last_row: int, ncols: int, total_rows: Sequence[int] = ()) -> None:
    for r in range(first_row, last_row + 1):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = _BORDER
            if r in total_rows:
                cell.fill = _TOTAL_FILL
                cell.font = Font(bold=True)


def _widths(ws, widths: Sequence[float]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _brand_sheet(ws, ncols: int, subtitle: str, shop_name: str, website: str, stamp: str) -> None:
    """SHREEJI BOXES / SJB title rows, print setup, header-picture slot, branded footer."""
    ws.sheet_view.showGridLines = False
    ws.cell(row=1, column=1, value=branding.BRAND_NAME).font = Font(bold=True, size=20, color=_NAVY_HEX)
    mark = ws.cell(row=1, column=ncols, value=branding.BRAND_MARK)
    mark.font = Font(bold=True, size=22, color=_GOLD_HEX)
    mark.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[1].height = 30
    sub = ws.cell(row=2, column=1, value=subtitle)
    sub.font = Font(italic=True, size=11, color=_GOLD_HEX)
    shop = _show_shop(shop_name)
    if shop:
        s = _text(ws, 2, ncols, shop)
        s.font = Font(size=10, color="555555")
        s.alignment = Alignment(horizontal="right")
    for col in range(1, ncols + 1):
        ws.cell(row=2, column=col).border = _GOLD_RULE
    # print: landscape, fit to one page wide, branded footer, SJB picture in the page header
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top, ws.page_margins.bottom = 0.6, 0.7
    ws.oddHeader.center.text = "&G"  # the picture itself is attached in _finish_workbook
    ws.oddFooter.left.text = branding.BRAND_NAME + (f"   |   {website}" if website else "")
    ws.oddFooter.left.size = 9
    ws.oddFooter.left.font = "Calibri,Bold"
    ws.oddFooter.center.text = f"Generated {stamp}"
    ws.oddFooter.center.size = 8
    ws.oddFooter.right.text = "Page &P of &N"
    ws.oddFooter.right.size = 9


_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_VML_TEMPLATE = """<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">
 <o:shapelayout v:ext="edit">
  <o:idmap v:ext="edit" data="1"/>
 </o:shapelayout><v:shapetype id="_x0000_t75" coordsize="21600,21600" o:spt="75" o:preferrelative="t" path="m@4@5l@4@11@9@11@9@5xe" filled="f" stroked="f">
  <v:stroke joinstyle="miter"/>
  <v:formulas>
   <v:f eqn="if lineDrawn pixelLineWidth 0"/>
   <v:f eqn="sum @0 1 0"/>
   <v:f eqn="sum 0 0 @1"/>
   <v:f eqn="prod @2 1 2"/>
   <v:f eqn="prod @3 21600 pixelWidth"/>
   <v:f eqn="prod @3 21600 pixelHeight"/>
   <v:f eqn="sum @0 0 1"/>
   <v:f eqn="prod @6 1 2"/>
   <v:f eqn="prod @7 21600 pixelWidth"/>
   <v:f eqn="sum @8 21600 0"/>
   <v:f eqn="prod @7 21600 pixelHeight"/>
   <v:f eqn="sum @10 21600 0"/>
  </v:formulas>
  <v:path o:extrusionok="f" gradientshapeok="t" o:connecttype="rect"/>
  <o:lock v:ext="edit" aspectratio="t"/>
 </v:shapetype><v:shape id="CH" o:spid="_x0000_s1025" type="#_x0000_t75" style="position:absolute;margin-left:0;margin-top:0;width:{w}pt;height:{h}pt;z-index:1">
  <v:imagedata o:relid="rId1" o:title="SJB watermark"/>
  <o:lock v:ext="edit" rotation="t"/>
 </v:shape></xml>"""
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _inject_cached_values(sheet_xml: str, cached: dict[str, str]) -> str:
    """Put the known result of each formula into its <v> so the number shows without a recalculation."""
    def fill(match):
        coord = match.group(1)
        if coord not in cached:
            return match.group(0)
        return f'<c r="{coord}"{match.group(2)}><f>{match.group(3)}</f><v>{cached[coord]}</v></c>'

    return re.sub(r'<c r="([A-Z]+[0-9]+)"([^>]*)><f>(.*?)</f><v\s*(?:/>|></v>)</c>', fill, sheet_xml)


def _finish_workbook(wb: Workbook, path, cache: Optional[_Cache] = None) -> Path:
    """Save, then add what openpyxl cannot: cached formula results and the SJB watermark pictures."""
    from openpyxl.workbook.properties import CalcProperties

    path = Path(path)
    tmp = _tmp_path(path)
    wb.properties.title = f"{branding.BRAND_NAME} - report"
    wb.properties.creator = f"{branding.BRAND_NAME} / {APP_NAME}"
    wb.calculation = CalcProperties(fullCalcOnLoad=True)  # Excel recalculates on open; cached values serve previews
    wb.save(str(tmp))

    with zipfile.ZipFile(tmp) as zin:
        parts = {name: zin.read(name) for name in zin.namelist()}
    sheet_name = "xl/worksheets/sheet1.xml"
    sheet = parts[sheet_name].decode("utf-8")
    if cache and cache.values:
        sheet = _inject_cached_values(sheet, cache.values)

    # header picture (prints behind the data on every page) + on-screen tiled background
    sheet = sheet.replace("<worksheet ", f'<worksheet xmlns:r="{_NS_R}" ', 1)
    sheet = sheet.replace("</worksheet>", '<legacyDrawingHF r:id="rId1"/><picture r:id="rId2"/></worksheet>', 1)
    parts[sheet_name] = sheet.encode("utf-8")
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_REL_BASE}/vmlDrawing" Target="../drawings/vmlDrawing1.vml"/>'
        f'<Relationship Id="rId2" Type="{_REL_BASE}/image" Target="../media/image2.png"/></Relationships>'
    ).encode("utf-8")
    parts["xl/drawings/vmlDrawing1.vml"] = _VML_TEMPLATE.replace("{w}", "675").replace("{h}", "450").encode("utf-8")
    parts["xl/drawings/_rels/vmlDrawing1.vml.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_REL_BASE}/image" Target="../media/image1.png"/></Relationships>'
    ).encode("utf-8")
    parts["xl/media/image1.png"] = branding.excel_print_watermark()
    parts["xl/media/image2.png"] = branding.excel_screen_background()
    ctypes = parts["[Content_Types].xml"].decode("utf-8")
    additions = ""
    if 'Extension="png"' not in ctypes:
        additions += '<Default Extension="png" ContentType="image/png"/>'
    if 'Extension="vml"' not in ctypes:
        additions += '<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>'
    parts["[Content_Types].xml"] = ctypes.replace("<Default ", additions + "<Default ", 1).encode("utf-8")

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("[Content_Types].xml", parts.pop("[Content_Types].xml"))
        for name, data in parts.items():
            zout.writestr(name, data)
    os.replace(tmp, path)
    return path


def export_statement_xlsx(ledger: Ledger, path, shop_name: str = "", *, website: str = "",
                          generated_at: Optional[datetime] = None) -> Path:
    _check_reconciles(ledger)
    wb = Workbook()
    ws = wb.active
    ws.title = "Statement"
    cache = _Cache()
    stamp = _stamp(generated_at)
    c = ledger.customer
    _brand_sheet(ws, 7, "Customer Statement (Khata)", shop_name, website, stamp)
    for row, (label, value) in enumerate((
            ("Customer", c.name), ("Mobile", c.mobile), ("Address", c.address),
            ("Period", _period_text(ledger.date_from, ledger.date_to)),
            ("Item filter", ledger.search or "None"), ("Generated", stamp)), start=3):
        _text(ws, row, 1, label, bold=True)
        _text(ws, row, 2, value)

    head = 10
    _header_row(ws, head, ["TRANSACTION DATE", "ITEM / DESCRIPTION", "UDHAAR (₹)", "TOTAL DEPOSIT (₹)",
                           "DEPOSIT DATE", "DEPOSIT BALANCE (₹)", "NOTES"])
    opening_row = head + 1
    _text(ws, opening_row, 2, "Opening Balance", bold=True)
    _money(ws, opening_row, 6, ledger.opening_balance, bold=True)
    r = opening_row
    chain = not ledger.search  # with an item filter the rows shown are not consecutive: keep true balances as values
    for row in ledger.rows:
        r += 1
        t = row.txn
        _date_cell(ws, r, 1, t.txn_date)
        item = t.item
        extra = _qty_rate_text(t.quantity, t.rate_paise, "₹")
        _text(ws, r, 2, f"{item}\n{extra}" if extra else item, wrap=True)
        _money(ws, r, 3, row.udhaar or None)
        _money(ws, r, 4, row.deposit or None)  # the deposited amount only, never a balance
        if row.deposit_date:
            _date_cell(ws, r, 5, row.deposit_date)
        if chain:
            cache.formula(ws, r, 6, f"=F{r - 1}+C{r}-D{r}", row.balance)
        else:
            _money(ws, r, 6, row.balance)
        _text(ws, r, 7, t.notes, wrap=True)
    last = r
    total_row = last + 1
    _text(ws, total_row, 2, "TOTAL", bold=True)
    if ledger.rows:
        cache.formula(ws, total_row, 3, f"=SUM(C{opening_row + 1}:C{last})", ledger.total_udhaar, bold=True)
        cache.formula(ws, total_row, 4, f"=SUM(D{opening_row + 1}:D{last})", ledger.total_deposit, bold=True)
    else:
        _money(ws, total_row, 3, 0, bold=True)
        _money(ws, total_row, 4, 0, bold=True)
    if chain:
        cache.formula(ws, total_row, 6, f"=F{opening_row}+C{total_row}-D{total_row}", ledger.deposit_balance, bold=True)
    else:
        _money(ws, total_row, 6, ledger.deposit_balance, bold=True)
    _style_range(ws, opening_row, total_row, 7, total_rows=[total_row])
    final = ws.cell(row=total_row, column=6)
    final.fill = _FINAL_FILL
    final.font = Font(bold=True, color="FFFFFF")

    # separate summary section
    r = total_row + 2
    for col in (2, 3):
        cell = ws.cell(row=r, column=col)
        cell.fill = _HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.border = _BORDER
    ws.cell(row=r, column=2, value="SUMMARY")
    summary = (("Opening Balance", f"=F{opening_row}", ledger.opening_balance),
               ("Total Udhaar", f"=C{total_row}", ledger.total_udhaar),
               ("Total Deposit", f"=D{total_row}", ledger.total_deposit),
               ("Final Deposit Balance", f"=F{total_row}", ledger.deposit_balance))
    for label, formula, paise in summary:
        r += 1
        _text(ws, r, 2, label, bold=True).border = _BORDER
        cache.formula(ws, r, 3, formula, paise, bold=True).border = _BORDER
    ws.cell(row=r, column=2).fill = _TOTAL_FILL
    ws.cell(row=r, column=3).fill = _TOTAL_FILL
    r += 1
    _text(ws, r, 2, "Transactions listed", bold=True).border = _BORDER
    count = ws.cell(row=r, column=3, value=len(ledger.rows))
    count.border = _BORDER
    count.alignment = Alignment(horizontal="right")
    r += 2
    note = ("Deposit Balance = Total Udhaar - Total Deposit (plus any opening balance), running in date order; "
            "a deposit counts on its Deposit Date. Positive = customer owes you; negative = advance / overpaid.")
    if ledger.search:
        note += " Item filter active: balances shown are the true account balance."
    _text(ws, r, 2, note).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=7)
    ws.row_dimensions[r].height = 30

    _widths(ws, [18, 40, 18, 19, 16, 21, 36])
    ws.freeze_panes = ws.cell(row=head + 1, column=1)
    ws.auto_filter.ref = f"A{head}:G{last}" if ledger.rows else f"A{head}:G{opening_row}"
    ws.print_title_rows = f"{head}:{head}"
    return _finish_workbook(wb, path, cache)


def export_register_xlsx(register: Register, path, shop_name: str = "", customer_label: str = "All customers", *,
                         website: str = "", generated_at: Optional[datetime] = None) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Register"
    stamp = _stamp(generated_at)
    ncols = 9
    _brand_sheet(ws, ncols, "Transaction Register", shop_name, website, stamp)
    for row, (label, value) in enumerate((
            ("Customers", customer_label), ("Period", _period_text(register.date_from, register.date_to)),
            ("Item filter", register.search or "None"), ("Generated", stamp)), start=3):
        _text(ws, row, 1, label, bold=True)
        _text(ws, row, 2, value)
    head = 8
    _header_row(ws, head, ["TRANSACTION DATE", "CUSTOMER", "ITEM / DESCRIPTION", "QUANTITY", "RATE (₹)", "UDHAAR (₹)",
                           "TOTAL DEPOSIT (₹)", "DEPOSIT DATE", "NOTES"])
    r = head
    for row in register.rows:
        r += 1
        t = row.txn
        is_dep = t.txn_type == "JAMA"
        _date_cell(ws, r, 1, t.txn_date)
        _text(ws, r, 2, row.customer_name, wrap=True)
        _text(ws, r, 3, t.item, wrap=True)
        _qty_cell(ws, r, 4, t.quantity)
        _money(ws, r, 5, t.rate_paise)
        _money(ws, r, 6, None if is_dep else t.amount_paise)
        _money(ws, r, 7, t.amount_paise if is_dep else None)
        if is_dep:
            _date_cell(ws, r, 8, t.deposit_date or t.txn_date)
        _text(ws, r, 9, t.notes, wrap=True)
    r += 1
    _text(ws, r, 2, "TOTAL", bold=True)
    _money(ws, r, 6, register.total_udhaar, bold=True)
    _money(ws, r, 7, register.total_deposit, bold=True)
    r += 1
    _text(ws, r, 2, "Net outstanding (udhaar - deposit)", bold=True)
    _money(ws, r, 6, register.net, bold=True)
    _style_range(ws, head + 1, r, ncols, total_rows=[r - 1, r])
    _widths(ws, [18, 26, 38, 11, 14, 18, 19, 16, 34])
    ws.freeze_panes = ws.cell(row=head + 1, column=1)
    ws.auto_filter.ref = f"A{head}:{get_column_letter(ncols)}{max(head + len(register.rows), head + 1)}"
    ws.print_title_rows = f"{head}:{head}"
    return _finish_workbook(wb, path)


def export_customers_xlsx(summaries: Sequence[CustomerSummary], path, shop_name: str = "", filter_text: str = "", *,
                          website: str = "", generated_at: Optional[datetime] = None) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Customer balances"
    stamp = _stamp(generated_at)
    ncols = 7
    _brand_sheet(ws, ncols, "Customer Balance Summary", shop_name, website, stamp)
    _text(ws, 3, 1, "As on", bold=True)
    _text(ws, 3, 2, (generated_at or datetime.now()).strftime("%d-%m-%Y"))
    _text(ws, 4, 1, "Customer filter", bold=True)
    _text(ws, 4, 2, filter_text or "None")
    head = 6
    _header_row(ws, head, ["#", "CUSTOMER", "MOBILE", "ENTRIES", "TOTAL UDHAAR (₹)", "TOTAL DEPOSIT (₹)",
                           "DEPOSIT BALANCE (₹)"])
    r = head
    tu = td = 0
    for i, s in enumerate(summaries, 1):
        r += 1
        ws.cell(row=r, column=1, value=i)
        _text(ws, r, 2, s.customer.name)
        _text(ws, r, 3, s.customer.mobile)
        ws.cell(row=r, column=4, value=s.txn_count)
        _money(ws, r, 5, s.total_udhaar)
        _money(ws, r, 6, s.total_deposit)
        _money(ws, r, 7, s.balance)
        tu += s.total_udhaar
        td += s.total_deposit
    r += 1
    _text(ws, r, 2, "Overall total", bold=True)
    _money(ws, r, 5, tu, bold=True)
    _money(ws, r, 6, td, bold=True)
    _money(ws, r, 7, tu - td, bold=True)
    _style_range(ws, head + 1, r, ncols, total_rows=[r])
    final = ws.cell(row=r, column=7)
    final.fill = _FINAL_FILL
    final.font = Font(bold=True, color="FFFFFF")
    _widths(ws, [7, 32, 18, 10, 20, 20, 22])
    ws.freeze_panes = ws.cell(row=head + 1, column=1)
    ws.auto_filter.ref = f"A{head}:G{max(head + len(summaries), head + 1)}"
    ws.print_title_rows = f"{head}:{head}"
    return _finish_workbook(wb, path)
