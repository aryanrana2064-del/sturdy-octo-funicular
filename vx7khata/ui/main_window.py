"""Main window: Dashboard, Customers, Quick Entry, Ledger, Reports, Backup."""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPropertyAnimation, QSequentialAnimationGroup,
    QStandardPaths, Qt, QUrl, QVariantAnimation,
)
from PySide6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, backup, branding, dates, exports, importer, money, paths, whatsapp
from ..service import DuplicateEntryError, KhataError, KhataService, effective_date
from . import theme
from .dialogs import CustomerDialog, EditEntryDialog
from .widgets import (
    GREEN, RED, BulkUdhaarForm, DateField, EntryForm, balance_color, customer_id_from_combo, fit_columns, make_customer_combo,
    make_table, populate_customer_combo, selected_id, set_cell,
)

(TAB_DASHBOARD, TAB_CUSTOMERS, TAB_ENTRY, TAB_MULTI, TAB_JAMA,
 TAB_LEDGER, TAB_PENDING, TAB_REPORTS, TAB_BACKUP) = range(9)


def _safe_filename(text: str) -> str:
    return re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_") or "khata"


def _documents_dir() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())


def _animations_enabled() -> bool:
    """Short UI animations are skipped under the headless test platform and when VX7_NO_ANIM is set."""
    import os
    return os.environ.get("QT_QPA_PLATFORM", "") != "offscreen" and not os.environ.get("VX7_NO_ANIM")


def _rgba(hex_colour: str, alpha: float) -> str:
    c = QColor(hex_colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


class StatCard(QFrame):
    """Raised glass card: icon badge, title, large value and a coloured accent bar.

    Keeps the original API (``.title``, ``.value``, ``set(text, colour)``). On hover the card lifts
    (its shadow grows) - a tiny 120 ms animation of one shadow effect.
    """

    def __init__(self, title: str, icon: str = "", accent: str = theme.BLUE, compact: bool = False):
        super().__init__()
        self.setObjectName("card")
        self._accent = accent
        self.setMinimumHeight(86 if compact else 124)
        self.setMouseTracking(True)

        self.icon = QLabel(icon)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setFixedSize(40 if compact else 46, 40 if compact else 46)
        self.icon.setStyleSheet(
            f"background: {_rgba(accent, 0.20)}; color: {accent}; border: 1px solid {_rgba(accent, 0.55)}; "
            f"border-radius: 14px; font-size: {17 if compact else 20}px; font-weight: bold;")
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("-")
        self.value.setObjectName("cardValue")
        if compact:
            self.value.setStyleSheet("font-size: 20px;")
        self.bar = QFrame()
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {_rgba(accent, 0.0)}); "
            "border: none; border-radius: 1px;")

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.value)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addLayout(text, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.addLayout(top, 1)
        layout.addWidget(self.bar)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(26)
        self._shadow.setOffset(0, 8)
        self._shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(self._shadow)
        self._lift_anim = None

    def _style_value(self, color: str | None) -> None:
        base = "font-size: 20px;" if self.value.styleSheet().startswith("font-size: 20px;") else ""
        self.value.setStyleSheet(base + (f" color: {color};" if color else ""))

    def set(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        self._style_value(color)

    def set_number(self, number: int, fmt, color: str | None = None) -> None:
        """Show ``fmt(number)``. When the number changed, it counts up/down to the exact new value (~0.5 s)."""
        self._style_value(color)
        previous = getattr(self, "_shown", None)
        self._shown = number
        if getattr(self, "_count_anim", None) is not None:
            self._count_anim.stop()
        if previous == number or not _animations_enabled():
            self.value.setText(fmt(number))
            return
        anim = QVariantAnimation(self)
        anim.setDuration(700 if previous is None else 450)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(float(previous or 0))
        anim.setEndValue(float(number))
        anim.valueChanged.connect(lambda v: self.value.setText(fmt(int(v))))
        anim.finished.connect(lambda: self.value.setText(fmt(number)))  # always land on the exact saved figure
        self._count_anim = anim
        anim.start()

    def _lift(self, up: bool) -> None:
        self.setProperty("hover", up)
        self.style().unpolish(self)
        self.style().polish(self)
        blur, offset = (44, 16) if up else (26, 8)
        if not _animations_enabled():
            self._shadow.setBlurRadius(blur)
            self._shadow.setOffset(0, offset)
            return
        if self._lift_anim is not None:
            self._lift_anim.stop()
        anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        anim.setDuration(120)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setEndValue(float(blur))
        anim.start()
        self._shadow.setOffset(0, offset)
        self._lift_anim = anim

    def enterEvent(self, event):
        self._lift(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._lift(False)
        super().leaveEvent(event)


class GlassBackground(QWidget):
    """Window backdrop: a deep gradient with soft coloured light blobs.

    The translucent panels sit on top of it, so they read as frosted glass (like iOS). Painted once per
    resize - no timers, no per-frame cost.
    """

    _BLOBS = ((0.10, 0.08, 0.60, "#0A84FF", 165), (0.92, 0.14, 0.52, "#BF5AF2", 130),
              (0.62, 1.02, 0.62, "#30D5C8", 105), (0.00, 0.98, 0.42, "#FF375F", 70))

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        base = QLinearGradient(0, 0, w, h)
        base.setColorAt(0.0, QColor("#0A1330"))
        base.setColorAt(0.55, QColor("#0D1A46"))
        base.setColorAt(1.0, QColor("#160F36"))
        painter.fillRect(self.rect(), base)
        for cx, cy, radius, colour, alpha in self._BLOBS:
            glow = QRadialGradient(cx * w, cy * h, radius * max(w, h))
            centre = QColor(colour)
            centre.setAlpha(alpha)
            edge = QColor(colour)
            edge.setAlpha(0)
            glow.setColorAt(0.0, centre)
            glow.setColorAt(1.0, edge)
            painter.fillRect(self.rect(), glow)
        painter.end()


class _GlowFilter(QObject):
    """Soft coloured glow that fades in around a button while the mouse is over it."""

    def __init__(self, button, colour: str):
        super().__init__(button)
        self._effect = QGraphicsDropShadowEffect(button)
        self._effect.setBlurRadius(0)
        self._effect.setOffset(0, 0)
        self._effect.setColor(QColor(colour))
        button.setGraphicsEffect(self._effect)
        button.installEventFilter(self)
        self._anim = None

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Enter and obj.isEnabled():
            self._go(26)
        elif kind == QEvent.Type.Leave:
            self._go(0)
        return False

    def _go(self, blur: float) -> None:
        if not _animations_enabled():
            return
        if self._anim is not None:
            self._anim.stop()
        anim = QPropertyAnimation(self._effect, b"blurRadius", self)
        anim.setDuration(160)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setEndValue(float(blur))
        anim.start()
        self._anim = anim


# (label, icon glyph, short subtitle) for every page, in tab order
NAV_ITEMS = [
    ("Dashboard", "▦", "Your khata at a glance"),
    ("Customers", "☺", "Everyone who has an account with you"),
    ("Quick Entry", "✎", "Record one udhaar or jama - any date, including old dates"),
    ("Multi Udhaar", "☰", "Many udhaar items for one customer in one go"),
    ("Quick Jama", "↓", "Money received: customer, date, amount"),
    ("Ledger", "▤", "Statement with running balance"),
    ("Pending", "◔", "Who owes you, oldest first - send WhatsApp reminders"),
    ("Reports", "▥", "Filter, preview and export PDF / Excel"),
    ("Backup && Settings", "⚙", "Protect your data and set up statement headers"),
]


class MainWindow(QMainWindow):
    def __init__(self, service: KhataService):
        super().__init__()
        self.svc = service
        self.setWindowTitle(f"{APP_NAME}  –  Khata-Bahi")
        self.resize(1240, 780)
        self.setMinimumSize(980, 620)
        self._saving = False
        self._compact = False
        self._manual_compact = None  # None = follow the window width; True/False = chosen with the ☰ button
        self._side_anim = None
        self._toast_group = None
        self._fade = None  # (widget, animation) of the running page fade-in
        self._last_backup_text = "No backup made in this session"

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()  # navigation lives in the sidebar; the pages themselves are unchanged
        self._build_dashboard()
        self._build_customers()
        self._build_entry()
        self._build_multi()
        self._build_jama()
        self._build_ledger()
        self._build_pending()
        self._build_reports()
        self._build_backup()
        self._build_shell()
        for button in self.findChildren(QPushButton):  # glow on the main action buttons
            if button.objectName() == "primary":
                _GlowFilter(button, theme.BLUE)
            elif button.objectName() == "danger":
                _GlowFilter(button, theme.CORAL)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.refresh_all()
        self._sync_nav(self.tabs.currentIndex())

    # ------------------------------------------------------------ shared
    def info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def confirm(self, title: str, text: str, default_no: bool = True) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No if default_no else QMessageBox.StandardButton.Yes)
        return box.exec() == QMessageBox.StandardButton.Yes

    def shop_name(self) -> str:
        return self.svc.get_setting("shop_name", "")

    def website(self) -> str:
        """Printed on reports only when the user has configured one."""
        return " ".join(self.svc.get_setting("website", "").split())

    def toast(self, text: str) -> None:
        """Small "✓ Saved" pill that fades in at the bottom right and fades out by itself."""
        parent = self.centralWidget()
        label = getattr(self, "_toast", None)
        if label is None:
            label = self._toast = QLabel(parent)
            label.setObjectName("toast")
            label.hide()
            self._toast_effect = QGraphicsOpacityEffect(label)
            label.setGraphicsEffect(self._toast_effect)
        if self._toast_group is not None:
            self._toast_group.stop()
        label.setText(text)
        label.adjustSize()
        label.move(max(0, parent.width() - label.width() - 28), max(0, parent.height() - label.height() - 28))
        label.show()
        label.raise_()
        if not _animations_enabled():
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1800, label.hide)
            return
        group = QSequentialAnimationGroup(self)
        fade_in = QPropertyAnimation(self._toast_effect, b"opacity", group)
        fade_in.setDuration(160)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        group.addAnimation(fade_in)
        group.addPause(1500)
        fade_out = QPropertyAnimation(self._toast_effect, b"opacity", group)
        fade_out.setDuration(450)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        group.addAnimation(fade_out)
        group.finished.connect(label.hide)
        self._toast_group = group
        group.start()

    # ------------------------------------------------------------ shell: sidebar + top bar + page transitions
    def _build_shell(self) -> None:
        shell = GlassBackground()
        row = QHBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # ---- sidebar
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(236)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(14, 18, 14, 14)
        side.setSpacing(6)

        logo = QHBoxLayout()
        logo.setSpacing(10)
        badge = QLabel("VX7")
        badge.setObjectName("logoBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(44, 44)
        self.logo_text = QWidget()
        lt = QVBoxLayout(self.logo_text)
        lt.setContentsMargins(0, 0, 0, 0)
        lt.setSpacing(0)
        title = QLabel("VX7 KHATA")
        title.setObjectName("logoTitle")
        sub = QLabel("P R O")
        sub.setObjectName("logoSub")
        lt.addWidget(title)
        lt.addWidget(sub)
        logo.addWidget(badge)
        logo.addWidget(self.logo_text, 1)
        side.addLayout(logo)
        side.addSpacing(18)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for index, (label, icon, _sub) in enumerate(NAV_ITEMS):
            button = QPushButton()
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(label.replace("&&", "&"))
            button.clicked.connect(lambda _checked=False, i=index: self.tabs.setCurrentIndex(i))
            self._nav_group.addButton(button, index)
            self._nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch(1)

        # ---- profile / settings area
        self.profile = QFrame()
        self.profile.setObjectName("profile")
        pf = QHBoxLayout(self.profile)
        pf.setContentsMargins(10, 10, 10, 10)
        pf.setSpacing(10)
        self.avatar = QLabel(branding.BRAND_MARK[:1])
        self.avatar.setObjectName("avatar")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setFixedSize(36, 36)
        who = QVBoxLayout()
        who.setSpacing(0)
        name = QLabel(branding.BRAND_NAME)
        name.setObjectName("profileName")
        self.profile_sub = QLabel(f"v{__version__}  ·  offline")
        self.profile_sub.setObjectName("profileSub")
        who.addWidget(name)
        who.addWidget(self.profile_sub)
        gear = QPushButton("⚙")
        gear.setObjectName("profileButton")
        gear.setToolTip("Settings")
        gear.setFixedWidth(36)
        gear.clicked.connect(lambda: self.tabs.setCurrentIndex(TAB_BACKUP))
        pf.addWidget(self.avatar)
        pf.addLayout(who, 1)
        pf.addWidget(gear)
        self._profile_text = [name, self.profile_sub]
        self._profile_gear = gear
        side.addWidget(self.profile)

        # ---- right side: top bar + pages
        content = QFrame()
        content.setObjectName("content")
        col = QVBoxLayout(content)
        col.setContentsMargins(22, 16, 22, 16)
        col.setSpacing(10)
        top = QHBoxLayout()
        self.nav_toggle = QPushButton("☰")
        self.nav_toggle.setObjectName("navToggle")
        self.nav_toggle.setToolTip("Collapse / expand the sidebar")
        self.nav_toggle.setFixedSize(38, 38)
        self.nav_toggle.clicked.connect(self._toggle_sidebar)
        top.addWidget(self.nav_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        heads = QVBoxLayout()
        heads.setSpacing(0)
        self.page_title = QLabel("")
        self.page_title.setObjectName("pageTitle")
        self.page_sub = QLabel("")
        self.page_sub.setObjectName("pageSub")
        heads.addWidget(self.page_title)
        heads.addWidget(self.page_sub)
        chip = QLabel(datetime.now().strftime("%a, %d %b %Y"))
        chip.setObjectName("chip")
        top.addLayout(heads, 1)
        top.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(top)
        col.addWidget(self.tabs, 1)

        row.addWidget(self.sidebar)
        row.addWidget(content, 1)
        self.setCentralWidget(shell)
        self._apply_nav_mode(compact=False)

    def _toggle_sidebar(self) -> None:
        self._manual_compact = not self._compact
        self._apply_nav_mode(self._manual_compact, animate=True)

    def _apply_nav_mode(self, compact: bool, animate: bool = False) -> None:
        """Wide: icon + label. Narrow window or ☰ button: icon-only rail (the width glides, 200 ms)."""
        self._compact = compact
        target = 78 if compact else 236
        if animate and _animations_enabled():
            if self._side_anim is not None:
                self._side_anim.stop()
            group = QParallelAnimationGroup(self)
            for prop in (b"minimumWidth", b"maximumWidth"):
                a = QPropertyAnimation(self.sidebar, prop, group)
                a.setDuration(200)
                a.setEasingCurve(QEasingCurve.Type.InOutCubic)
                a.setStartValue(self.sidebar.width())
                a.setEndValue(target)
                group.addAnimation(a)
            self._side_anim = group
            group.start()
        else:
            self.sidebar.setFixedWidth(target)
        for button, (label, icon, _sub) in zip(self._nav_buttons, NAV_ITEMS):
            button.setText(icon if compact else f"{icon}    {label}")
            if compact:
                button.setStyleSheet("text-align: center; padding-left: 0px; padding-right: 0px;")
            else:
                button.setStyleSheet("")
        self.logo_text.setVisible(not compact)
        for widget in self._profile_text:
            widget.setVisible(not compact)
        self._profile_gear.setVisible(not compact)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_nav_buttons", None) and self._manual_compact is None:
            compact = self.width() < 1080
            if compact != self._compact:
                self._apply_nav_mode(compact)

    def _sync_nav(self, index: int) -> None:
        if not getattr(self, "_nav_buttons", None) or not 0 <= index < len(self._nav_buttons):
            return
        self._nav_buttons[index].setChecked(True)
        label, _icon, sub = NAV_ITEMS[index]
        self.page_title.setText(label.replace("&&", "&"))
        self.page_sub.setText(sub)

    def _fade_in(self, widget) -> None:
        """Quick 150 ms opacity fade of the page that was just opened (skipped when animations are off)."""
        if widget is None or not _animations_enabled():
            return
        try:
            if self._fade is not None:
                old_widget, old_anim = self._fade
                old_anim.stop()
                old_widget.setGraphicsEffect(None)
        except RuntimeError:  # the old widget is already gone
            pass
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def done() -> None:
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                pass
            self._fade = None

        anim.finished.connect(done)
        self._fade = (widget, anim)
        anim.start()

    def _on_tab_changed(self, index: int) -> None:
        self._sync_nav(index)
        self.refresh_all()
        self._fade_in(self.tabs.widget(index))

    def refresh_all(self) -> None:
        summaries = self.svc.list_customers()
        self._refresh_dashboard()
        self._refresh_customers(summaries)
        populate_customer_combo(self.entry_form.customer, summaries)
        populate_customer_combo(self.multi_form.customer, summaries)
        populate_customer_combo(self.jama_customer, summaries)
        populate_customer_combo(self.ledger_customer, summaries)
        populate_customer_combo(self.report_customer, summaries, include_all=True)
        self.entry_form.date.refresh_limits()
        self.entry_form.deposit_date.refresh_limits()
        self.multi_form.date.refresh_limits()
        self.jama_date.refresh_limits()
        self._update_jama_balance()
        self.ledger_from.refresh_limits()
        self.ledger_to.refresh_limits()
        self.rep_from.refresh_limits()
        self.rep_to.refresh_limits()
        self._refresh_ledger()
        self._refresh_pending()
        self._refresh_report_preview()
        self._refresh_backup_info()

    def _export_path(self, title: str, default_name: str, pattern: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(self, title, str(Path(_documents_dir()) / default_name), pattern)
        return path or None

    def _offer_open(self, path) -> None:
        if self.confirm("Export complete", f"Saved:\n{path}\n\nOpen it now?", default_no=False):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------ dashboard
    def _build_dashboard(self) -> None:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setSpacing(14)
        self.pending_banner = QWidget()
        pb = QHBoxLayout(self.pending_banner)
        pb.setContentsMargins(0, 0, 0, 0)
        self.pending_banner_label = QLabel("")
        self.pending_banner_label.setObjectName("badgeWarn")
        view_pending = QPushButton("View pending list")
        view_pending.clicked.connect(lambda: self.tabs.setCurrentIndex(TAB_PENDING))
        pb.addWidget(self.pending_banner_label, 1)
        pb.addWidget(view_pending)
        outer.addWidget(self.pending_banner)
        grid = QGridLayout()
        grid.setSpacing(16)
        self.cards = {
            "customers": StatCard("Total Customers", "☺", theme.CYAN),
            "udhaar": StatCard("Total Udhaar", "↑", theme.CORAL),
            "jama": StatCard("Total Jama", "↓", theme.GREEN),
            "net": StatCard("Net Outstanding Balance", "₹", theme.BLUE),
            "today": StatCard("Today's Transactions", "◷", theme.AMBER),
            "historical": StatCard("Historical Transactions", "▤", theme.VIOLET),
        }
        for i, card in enumerate(self.cards.values()):
            grid.addWidget(card, i // 3, i % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        outer.addLayout(grid)
        note = QLabel(
            "Today's = entries dated today (a deposit counts on its deposit date).  Historical = dated before today.   "
            "Net outstanding = total udhaar − total jama (positive: customers owe you)."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        outer.addWidget(note)

        box = QGroupBox("Recent transactions (latest entries saved)")
        inner = QVBoxLayout(box)
        self.recent_txns = make_table(["Date", "Customer", "Item / Description", "Type", "Amount"])
        fit_columns(self.recent_txns, 2)
        self.recent_txns.setMinimumHeight(190)
        inner.addWidget(self.recent_txns)
        outer.addWidget(box, 1)
        self.tabs.addTab(page, "Dashboard")

    def _refresh_dashboard(self) -> None:
        d = self.svc.dashboard()
        self.cards["customers"].set_number(d.total_customers, str)
        self.cards["udhaar"].set_number(d.total_udhaar, money.format_inr, RED if d.total_udhaar else None)
        self.cards["jama"].set_number(d.total_jama, money.format_inr, GREEN if d.total_jama else None)
        self.cards["net"].set_number(d.net_outstanding, money.format_inr, balance_color(d.net_outstanding))
        self.cards["today"].set_number(d.todays_transactions, str)
        self.cards["historical"].set_number(d.historical_transactions, str)
        days = self._reminder_days()
        due = self.svc.pending_report(min_days=days)
        self.pending_banner.setVisible(bool(due))
        if due:
            self.pending_banner_label.setText(
                f"⚠  Reminder: {len(due)} customer{'s' if len(due) != 1 else ''} pending for {days}+ days  ·  "
                f"{money.format_inr(sum(p.balance for p in due))} to collect")
        # Recent transactions: read-only view of the saved entries (the same register the reports use),
        # newest saved first. Nothing is calculated here.
        rows = sorted(self.svc.register().rows, key=lambda r: (r.txn.created_at, r.txn.id), reverse=True)[:8]
        self.recent_txns.setRowCount(len(rows))
        for r, row in enumerate(rows):
            t = row.txn
            jama = t.txn_type == "JAMA"
            set_cell(self.recent_txns, r, 0, dates.format_date(effective_date(t)))
            set_cell(self.recent_txns, r, 1, row.customer_name)
            set_cell(self.recent_txns, r, 2, t.item)
            set_cell(self.recent_txns, r, 3, "JAMA" if jama else "UDHAAR", color=GREEN if jama else RED, bold=True)
            set_cell(self.recent_txns, r, 4, money.format_inr(t.amount_paise), right=True,
                     color=GREEN if jama else RED, bold=True)

    # ------------------------------------------------------------ customers
    def _build_customers(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        self.cust_search = QLineEdit()
        self.cust_search.setPlaceholderText("⌕   Search by name or phone…")
        self.cust_search.setClearButtonEnabled(True)
        self.cust_search.textChanged.connect(lambda _t: self._refresh_customers())
        add = QPushButton("Add customer")
        edit = QPushButton("Edit")
        ledger = QPushButton("Open ledger")
        entry = QPushButton("Add entry")
        delete = QPushButton("Delete customer")
        add.setObjectName("primary")
        delete.setObjectName("danger")
        add.clicked.connect(self._add_customer)
        edit.clicked.connect(self._edit_customer)
        ledger.clicked.connect(self._open_customer_ledger)
        entry.clicked.connect(self._entry_for_customer)
        delete.clicked.connect(self._delete_customer)
        top.addWidget(self.cust_search, 1)
        for b in (add, edit, ledger, entry, delete):
            top.addWidget(b)
        layout.addLayout(top)

        self.cust_table = make_table(["Name", "Mobile", "Address", "Total Udhaar", "Total Jama", "Balance"])
        fit_columns(self.cust_table, 2)
        self.cust_table.doubleClicked.connect(lambda _i: self._open_customer_ledger())
        layout.addWidget(self.cust_table, 1)
        self.cust_total = QLabel("")
        self.cust_total.setStyleSheet("font-weight: bold; font-size: 14px; color: #64D2FF;")
        layout.addWidget(self.cust_total)
        self.tabs.addTab(page, "Customers")

    def _refresh_customers(self, summaries=None) -> None:
        all_summaries = summaries if summaries is not None else self.svc.list_customers()
        needle = self.cust_search.text()
        shown = self.svc.list_customers(needle) if needle.strip() else all_summaries
        keep = selected_id(self.cust_table)
        self.cust_table.setRowCount(len(shown))
        for r, s in enumerate(shown):
            c = s.customer
            set_cell(self.cust_table, r, 0, c.name, data=c.id)
            set_cell(self.cust_table, r, 1, c.mobile)
            set_cell(self.cust_table, r, 2, c.address.replace("\n", " "))
            set_cell(self.cust_table, r, 3, money.format_inr(s.total_udhaar), right=True)
            set_cell(self.cust_table, r, 4, money.format_inr(s.total_jama), right=True,
                     color=GREEN if s.total_jama else None)
            set_cell(self.cust_table, r, 5, money.format_inr(s.balance), right=True,
                     color=balance_color(s.balance), bold=True)
            if keep == c.id:
                self.cust_table.selectRow(r)
        tu = sum(s.total_udhaar for s in all_summaries)
        tj = sum(s.total_jama for s in all_summaries)
        self.cust_total.setText(
            f"Overall (all {len(all_summaries)} customers):  Udhaar {money.format_inr(tu)}   "
            f"Jama {money.format_inr(tj)}   Balance {money.format_inr(tu - tj)}"
        )

    def _current_customer_id(self) -> int | None:
        cid = selected_id(self.cust_table)
        if cid is None:
            self.info("Select a customer", "Click a customer row first.")
        return cid

    def _add_customer(self) -> None:
        dlg = CustomerDialog(self.svc, parent=self)
        if dlg.exec():
            self.refresh_all()

    def _edit_customer(self) -> None:
        cid = self._current_customer_id()
        if cid is None:
            return
        dlg = CustomerDialog(self.svc, self.svc.get_customer(cid), parent=self)
        if dlg.exec():
            self.refresh_all()

    def _delete_customer(self) -> None:
        cid = self._current_customer_id()
        if cid is None:
            return
        customer = self.svc.get_customer(cid)
        if not self.confirm("Delete customer", f"Delete customer '{customer.name}'?\n"
                            "Only customers with no khata entries can be deleted."):
            return
        try:
            self.svc.delete_customer(cid)
        except KhataError as exc:
            self.warn("Cannot delete", str(exc))
            return
        self.refresh_all()

    def _open_customer_ledger(self) -> None:
        cid = self._current_customer_id()
        if cid is None:
            return
        self.ledger_customer.setCurrentIndex(max(0, self.ledger_customer.findData(cid)))
        self.tabs.setCurrentIndex(TAB_LEDGER)

    def _entry_for_customer(self) -> None:
        cid = self._current_customer_id()
        if cid is None:
            return
        self.entry_form.select_customer(cid)
        self.tabs.setCurrentIndex(TAB_ENTRY)
        self.entry_form.item.setFocus()

    # ------------------------------------------------------------ quick entry
    def _build_entry(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Quick entry – record udhaar or jama (any date, including old dates)")
        inner = QVBoxLayout(box)
        self.entry_form = EntryForm(with_customer=True)
        self.entry_form.new_customer_button.clicked.connect(self._quick_new_customer)
        self.entry_form.item.returnPressed.connect(self._save_entry)
        self.entry_form.amount.returnPressed.connect(self._save_entry)
        inner.addWidget(self.entry_form)
        buttons = QHBoxLayout()
        self.entry_save = QPushButton("Save entry")
        self.entry_save.setObjectName("primary")
        self.entry_save.setDefault(True)
        self.entry_save.clicked.connect(self._save_entry)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.entry_form.clear_for_next)
        buttons.addStretch(1)
        buttons.addWidget(clear)
        buttons.addWidget(self.entry_save)
        inner.addLayout(buttons)
        layout.addWidget(box)

        hint = QLabel("After saving, the customer, type and date stay selected so you can enter the next item immediately.")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        layout.addWidget(QLabel("Entries saved in this session:"))
        self.recent_table = make_table(["Customer", "Transaction date", "Item / Description", "Type", "Amount", "Deposit date", "Saved at"])
        fit_columns(self.recent_table, 2)
        layout.addWidget(self.recent_table, 1)
        self.tabs.addTab(page, "Quick Entry")

    def _quick_new_customer(self) -> None:
        dlg = CustomerDialog(self.svc, parent=self)
        if dlg.exec() and dlg.saved:
            self.refresh_all()
            self.entry_form.select_customer(dlg.saved.id)

    def _save_entry(self) -> None:
        if self._saving:
            return
        self._saving = True
        self.entry_save.setEnabled(False)
        try:
            try:
                cid = self.entry_form.customer_id()
                values = self.entry_form.values()
                try:
                    txn = self.svc.add_transaction(cid, **values)
                except DuplicateEntryError as exc:
                    if not self.confirm("Possible duplicate", f"{exc}\n\nSave it again anyway?"):
                        return
                    txn = self.svc.add_transaction(cid, allow_duplicate=True, **values)
            except KhataError as exc:
                self.warn("Cannot save entry", str(exc))
                return
            customer = self.svc.get_customer(cid)
            row = 0
            self.recent_table.insertRow(row)
            set_cell(self.recent_table, row, 0, customer.name)
            set_cell(self.recent_table, row, 1, dates.format_date(txn.txn_date))
            set_cell(self.recent_table, row, 2, txn.item)
            set_cell(self.recent_table, row, 3, txn.txn_type)
            set_cell(self.recent_table, row, 4, money.format_inr(txn.amount_paise), right=True, bold=True,
                     color=balance_color(txn.amount_paise if txn.txn_type == "UDHAAR" else -txn.amount_paise))
            set_cell(self.recent_table, row, 5, dates.format_date(txn.deposit_date) if txn.deposit_date else "")
            set_cell(self.recent_table, row, 6, datetime.fromisoformat(txn.created_at).strftime("%H:%M:%S"))
            self.entry_form.clear_for_next()
            self.refresh_all()
            self.toast(f"✓  Saved {txn.txn_type.title()} {money.format_inr(txn.amount_paise)} for {customer.name}")
        finally:
            self._saving = False
            self.entry_save.setEnabled(True)

    # ------------------------------------------------------------ multi-item udhaar
    def _build_multi(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Udhaar – many items at once (copy a bahi page: any dates, any number of items)")
        inner = QVBoxLayout(box)
        self.multi_form = BulkUdhaarForm()
        self.multi_form.new_customer_button.clicked.connect(self._multi_new_customer)
        self.multi_form.save_button.clicked.connect(self._save_multi)
        inner.addWidget(self.multi_form)
        layout.addWidget(box, 1)
        self.tabs.addTab(page, "Udhaar (Multi Item)")

    def _multi_new_customer(self) -> None:
        dlg = CustomerDialog(self.svc, parent=self)
        if dlg.exec() and dlg.saved:
            self.refresh_all()
            self.multi_form.select_customer(dlg.saved.id)

    def _save_multi(self) -> None:
        if self._saving:
            return
        self._saving = True
        form = self.multi_form
        form.save_button.setEnabled(False)
        try:
            try:
                cid = form.customer_id()
                entries = form.entries()
                if not entries:
                    raise KhataError("Type at least one item first")
                try:
                    txns = self.svc.add_transactions(cid, entries)
                except DuplicateEntryError as exc:
                    if not self.confirm("Possible duplicate", f"{exc}\n\nSave all rows again anyway?"):
                        return
                    txns = self.svc.add_transactions(cid, entries, allow_duplicate=True)
            except KhataError as exc:
                self.warn("Nothing was saved", str(exc))
                return
            customer = self.svc.get_customer(cid)
            total = sum(t.amount_paise for t in txns)
            form.clear_rows()
            form.status.setText(f"Saved {len(txns)} items for {customer.name}. Total udhaar "
                                f"{money.format_inr(total)}.  New balance {money.format_inr(self.svc.customer_balance(cid))}.")
            self.refresh_all()
            self.toast(f"✓  {len(txns)} items saved for {customer.name}")
        finally:
            self._saving = False
            form.save_button.setEnabled(True)

    # ------------------------------------------------------------ quick jama (money received)
    def _build_jama(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Quick Jama – pick the customer and the date, type only the amount")
        form = QFormLayout(box)
        self.jama_customer = make_customer_combo()
        self.jama_new = QPushButton("+ New customer")
        row = QHBoxLayout()
        row.addWidget(self.jama_customer, 1)
        row.addWidget(self.jama_new)
        form.addRow("Customer", row)
        self.jama_date = DateField()
        self.jama_date.setToolTip("The day the money was received. Any past date is fine.")
        form.addRow("Date (day money received)", self.jama_date)
        self.jama_amount = QLineEdit()
        self.jama_amount.setPlaceholderText("0.00")
        form.addRow("Amount (₹)", self.jama_amount)
        self.jama_notes = QLineEdit()
        self.jama_notes.setPlaceholderText("optional")
        form.addRow("Notes", self.jama_notes)
        self.jama_balance = QLabel("")
        self.jama_balance.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {theme.TEXT};")
        form.addRow("Balance now", self.jama_balance)
        buttons = QHBoxLayout()
        self.jama_save = QPushButton("Save jama")
        self.jama_save.setObjectName("primary")
        self.jama_save.setDefault(True)
        buttons.addStretch(1)
        buttons.addWidget(self.jama_save)
        form.addRow(buttons)
        layout.addWidget(box)

        layout.addWidget(QLabel("Jama saved in this session:"))
        self.jama_recent = make_table(["Customer", "Date", "Amount", "Saved at"])
        fit_columns(self.jama_recent, 0)
        layout.addWidget(self.jama_recent, 1)

        self.jama_new.clicked.connect(self._jama_new_customer)
        self.jama_save.clicked.connect(self._save_jama)
        self.jama_amount.returnPressed.connect(self._save_jama)
        self.jama_notes.returnPressed.connect(self._save_jama)
        self.jama_customer.currentIndexChanged.connect(lambda _i: self._update_jama_balance())
        self.tabs.addTab(page, "Quick Jama")

    def _jama_new_customer(self) -> None:
        dlg = CustomerDialog(self.svc, parent=self)
        if dlg.exec() and dlg.saved:
            self.refresh_all()
            index = self.jama_customer.findData(dlg.saved.id)
            if index >= 0:
                self.jama_customer.setCurrentIndex(index)

    def _update_jama_balance(self) -> None:
        cid = self.jama_customer.currentData() if self.jama_customer.currentIndex() >= 0 else None
        if cid is None:
            self.jama_balance.setText("")
            return
        balance = self.svc.customer_balance(cid)
        self.jama_balance.setText(money.format_inr(balance))
        self.jama_balance.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {balance_color(balance) or theme.TEXT};")

    def _save_jama(self) -> None:
        if self._saving:
            return
        self._saving = True
        self.jama_save.setEnabled(False)
        try:
            try:
                cid = customer_id_from_combo(self.jama_customer)
                day = self.jama_date.text_dmy()
                values = {"txn_type": "JAMA", "txn_date": day, "deposit_date": day, "item": "",
                          "amount": self.jama_amount.text(), "notes": self.jama_notes.text()}
                try:
                    txn = self.svc.add_transaction(cid, **values)
                except DuplicateEntryError as exc:
                    if not self.confirm("Possible duplicate", f"{exc}\n\nSave it again anyway?"):
                        return
                    txn = self.svc.add_transaction(cid, allow_duplicate=True, **values)
            except KhataError as exc:
                self.warn("Cannot save jama", str(exc))
                return
            customer = self.svc.get_customer(cid)
            self.jama_recent.insertRow(0)
            set_cell(self.jama_recent, 0, 0, customer.name)
            set_cell(self.jama_recent, 0, 1, dates.format_date(txn.deposit_date or txn.txn_date))
            set_cell(self.jama_recent, 0, 2, money.format_inr(txn.amount_paise), right=True, color=GREEN)
            set_cell(self.jama_recent, 0, 3, datetime.fromisoformat(txn.created_at).strftime("%H:%M:%S"))
            self.jama_amount.clear()
            self.jama_notes.clear()
            self.refresh_all()
            self.jama_amount.setFocus()
            self.toast(f"✓  Jama {money.format_inr(txn.amount_paise)} saved for {customer.name}")
        finally:
            self._saving = False
            self.jama_save.setEnabled(True)

    # ------------------------------------------------------------ ledger
    def _build_ledger(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        filters = QHBoxLayout()
        self.ledger_customer = QComboBox()
        self.ledger_customer.setMinimumWidth(220)
        self.ledger_range = QCheckBox("Date range")
        self.ledger_range.setToolTip("Udhaar is filtered by its transaction date, deposits by their deposit date.")
        self.ledger_from = DateField()
        self.ledger_to = DateField()
        self.ledger_from.setEnabled(False)
        self.ledger_to.setEnabled(False)
        self.ledger_search = QLineEdit()
        self.ledger_search.setPlaceholderText("⌕   Search item description…")
        self.ledger_search.setClearButtonEnabled(True)
        filters.addWidget(QLabel("Customer"))
        filters.addWidget(self.ledger_customer)
        filters.addWidget(self.ledger_range)
        filters.addWidget(QLabel("From"))
        filters.addWidget(self.ledger_from)
        filters.addWidget(QLabel("To"))
        filters.addWidget(self.ledger_to)
        filters.addWidget(self.ledger_search, 1)
        layout.addLayout(filters)

        self.ledger_customer.currentIndexChanged.connect(lambda _i: self._refresh_ledger())
        self.ledger_range.toggled.connect(self._ledger_range_toggled)
        self.ledger_from.dateChanged.connect(lambda _d: self._refresh_ledger())
        self.ledger_to.dateChanged.connect(lambda _d: self._refresh_ledger())
        self.ledger_search.textChanged.connect(lambda _t: self._refresh_ledger())

        self.ledger_table = make_table(["Transaction Date", "Item / Description", "Qty", "Rate", "Udhaar (₹)", "Total Deposit (₹)",
                                   "Deposit Date", "Deposit Balance (₹)", "Notes"])
        fit_columns(self.ledger_table, 1)
        self.ledger_table.doubleClicked.connect(lambda _i: self._edit_entry())
        layout.addWidget(self.ledger_table, 1)

        self.ledger_summary = QLabel("")
        self.ledger_summary.setStyleSheet("font-weight: bold; font-size: 14px; color: #64D2FF;")
        self.ledger_note = QLabel("")
        self.ledger_note.setObjectName("hint")
        self.ledger_note.setWordWrap(True)
        layout.addWidget(self.ledger_summary)
        layout.addWidget(self.ledger_note)

        buttons = QHBoxLayout()
        add = QPushButton("Add entry")
        edit = QPushButton("Edit selected")
        delete = QPushButton("Delete selected")
        pdf = QPushButton("Export statement PDF")
        xlsx = QPushButton("Export statement Excel")
        wa = QPushButton("WhatsApp statement")
        wa.setToolTip("Saves the PDF and opens this customer's WhatsApp chat with the message ready")
        wa.clicked.connect(self._whatsapp_statement)
        add.setObjectName("primary")
        pdf.setObjectName("primary")
        xlsx.setObjectName("primary")
        delete.setObjectName("danger")
        add.clicked.connect(self._ledger_add_entry)
        edit.clicked.connect(self._edit_entry)
        delete.clicked.connect(self._delete_entry)
        pdf.clicked.connect(lambda: self._export_statement("pdf"))
        xlsx.clicked.connect(lambda: self._export_statement("xlsx"))
        for b in (add, edit, delete):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(wa)
        buttons.addWidget(pdf)
        buttons.addWidget(xlsx)
        layout.addLayout(buttons)
        self.tabs.addTab(page, "Ledger")

    def _ledger_range_toggled(self, on: bool) -> None:
        self.ledger_from.setEnabled(on)
        self.ledger_to.setEnabled(on)
        self._refresh_ledger()

    def _ledger_args(self) -> dict:
        args = {"search": self.ledger_search.text()}
        if self.ledger_range.isChecked():
            args["date_from"] = self.ledger_from.text_dmy()
            args["date_to"] = self.ledger_to.text_dmy()
        return args

    def _current_ledger(self):
        cid = self.ledger_customer.currentData()
        if cid is None:
            return None
        return self.svc.ledger(cid, **self._ledger_args())

    def _refresh_ledger(self) -> None:
        self.ledger_table.setRowCount(0)
        try:
            led = self._current_ledger()
        except KhataError as exc:
            self.ledger_summary.setText("")
            self.ledger_note.setText(str(exc))
            return
        if led is None:
            self.ledger_summary.setText("Add a customer to begin.")
            self.ledger_note.setText("")
            return
        self.ledger_table.setRowCount(len(led.rows))
        for r, row in enumerate(led.rows):
            t = row.txn
            set_cell(self.ledger_table, r, 0, dates.format_date(t.txn_date), data=t.id)
            set_cell(self.ledger_table, r, 1, t.item)
            set_cell(self.ledger_table, r, 2, t.quantity or "", right=True)
            set_cell(self.ledger_table, r, 3, money.format_inr(t.rate_paise, symbol=False) if t.rate_paise else "", right=True)
            set_cell(self.ledger_table, r, 4, money.format_inr(row.udhaar, symbol=False) if row.udhaar else "",
                     right=True, color=RED_IF(row.udhaar))
            set_cell(self.ledger_table, r, 5, money.format_inr(row.jama, symbol=False) if row.jama else "",
                     right=True, color=GREEN if row.jama else None)
            set_cell(self.ledger_table, r, 6, dates.format_date(row.deposit_date) if row.deposit_date else "")
            set_cell(self.ledger_table, r, 7, money.format_inr(row.balance, symbol=False), right=True,
                     color=balance_color(row.balance), bold=True)
            set_cell(self.ledger_table, r, 8, t.notes.replace("\n", " "))
        self.ledger_summary.setText(
            f"Opening {money.format_inr(led.opening_balance)}   |   "
            f"Total Udhaar {money.format_inr(led.total_udhaar)}   Total Deposit {money.format_inr(led.total_deposit)}   "
            f"({len(led.rows)} entries)   |   Final Deposit Balance {money.format_inr(led.deposit_balance)}"
        )
        note = ("Entries are in date order; a deposit sits at its Deposit Date, not the day it was entered. "
                "Entries on the same date keep the order they were entered.")
        if led.search:
            note = "Item search is active: running balance still shows the true account balance. " + note
        self.ledger_note.setText(note)

    def _ledger_add_entry(self) -> None:
        cid = self.ledger_customer.currentData()
        if cid is not None:
            self.entry_form.select_customer(cid)
        self.tabs.setCurrentIndex(TAB_ENTRY)

    def _selected_txn_id(self) -> int | None:
        tid = selected_id(self.ledger_table)
        if tid is None:
            self.info("Select an entry", "Click an entry row first.")
        return tid

    def _edit_entry(self) -> None:
        tid = self._selected_txn_id()
        if tid is None:
            return
        txn = self.svc.get_transaction(tid)
        customer = self.svc.get_customer(txn.customer_id)
        dlg = EditEntryDialog(self.svc, txn, customer.name, parent=self)
        if dlg.exec():
            self.refresh_all()

    def _delete_entry(self) -> None:
        tid = self._selected_txn_id()
        if tid is None:
            return
        txn = self.svc.get_transaction(tid)
        when = dates.format_date(txn.txn_date)
        if txn.txn_type == "JAMA":
            when += f"  (deposit date {dates.format_date(txn.deposit_date or txn.txn_date)})"
        text = (f"Delete this entry?\n\n{when}  {txn.txn_type}  "
                f"{money.format_inr(txn.amount_paise)}\n{txn.item}\n\nThis cannot be undone. "
                "All balances will be recalculated.")
        if not self.confirm("Delete entry", text):
            return
        try:
            self.svc.delete_transaction(tid)
        except KhataError as exc:
            self.warn("Cannot delete", str(exc))
            return
        self.refresh_all()

    def _export_statement(self, kind: str) -> None:
        try:
            led = self._current_ledger()
        except KhataError as exc:
            self.warn("Cannot export", str(exc))
            return
        if led is None:
            self.info("No customer", "Select a customer first.")
            return
        period = ""
        if led.date_from or led.date_to:
            period = f"_{led.date_from or 'start'}_{led.date_to or 'latest'}"
        default = f"Statement_{_safe_filename(led.customer.name)}{period}.{kind}"
        pattern = "PDF files (*.pdf)" if kind == "pdf" else "Excel files (*.xlsx)"
        path = self._export_path("Export statement", default, pattern)
        if not path:
            return
        try:
            fn = exports.export_statement_pdf if kind == "pdf" else exports.export_statement_xlsx
            fn(led, path, self.shop_name(), website=self.website())
        except (OSError, KhataError) as exc:
            self.warn("Export failed", str(exc))
            return
        self._offer_open(path)

    # ------------------------------------------------------------ pending list + reminders
    def _reminder_days(self) -> int:
        try:
            return max(0, min(3650, int(self.svc.get_setting("reminder_days", "30"))))
        except ValueError:
            return 30

    def _build_pending(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Pending list - customers who still owe you, oldest first")
        inner = QVBoxLayout(box)
        filt = QHBoxLayout()
        self.pending_days = QComboBox()
        for label, days in (("All pending", 0), ("7+ days", 7), ("15+ days", 15), ("30+ days", 30),
                            ("45+ days", 45), ("60+ days", 60), ("90+ days", 90)):
            self.pending_days.addItem(label, days)
        index = self.pending_days.findData(self._reminder_days())
        self.pending_days.setCurrentIndex(index if index >= 0 else 3)
        self.pending_days.setToolTip("Also decides the reminder shown on the Dashboard")
        self.pending_search = QLineEdit()
        self.pending_search.setPlaceholderText("⌕   Search customer name or phone…")
        self.pending_search.setClearButtonEnabled(True)
        filt.addWidget(QLabel("Pending for"))
        filt.addWidget(self.pending_days)
        filt.addWidget(self.pending_search, 1)
        inner.addLayout(filt)
        layout.addWidget(box)

        self.pending_table = make_table(["Customer", "Mobile", "Pending since", "Days", "Balance",
                                         "Last jama", "Last jama date"])
        fit_columns(self.pending_table, 0)
        layout.addWidget(self.pending_table, 1)
        self.pending_summary = QLabel("")
        self.pending_summary.setStyleSheet("font-weight: bold; font-size: 14px; color: #64D2FF;")
        note = QLabel("\"Pending since\" = the date of the oldest udhaar not yet covered by jama "
                      "(jama is matched to the oldest udhaar first).")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(self.pending_summary)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        remind = QPushButton("WhatsApp reminder")
        remind.setObjectName("primary")
        add_jama = QPushButton("Add jama")
        ledger = QPushButton("Open ledger")
        remind.clicked.connect(self._whatsapp_reminder)
        add_jama.clicked.connect(self._pending_add_jama)
        ledger.clicked.connect(self._pending_open_ledger)
        self.pending_table.doubleClicked.connect(lambda _i: self._pending_open_ledger())
        buttons.addWidget(remind)
        buttons.addWidget(add_jama)
        buttons.addWidget(ledger)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._pending_rows = {}
        self.pending_days.currentIndexChanged.connect(self._pending_filter_changed)
        self.pending_search.textChanged.connect(lambda _t: self._refresh_pending())
        self.tabs.addTab(page, "Pending")

    def _pending_filter_changed(self, _index: int) -> None:
        days = self.pending_days.currentData()
        if days is not None:
            self.svc.set_setting("reminder_days", str(days))
        self._refresh_pending()
        self._refresh_dashboard()

    def _refresh_pending(self) -> None:
        days = self.pending_days.currentData() or 0
        rows = self.svc.pending_report(min_days=days, search=self.pending_search.text())
        keep = selected_id(self.pending_table)
        self._pending_rows = {p.customer.id: p for p in rows}
        self.pending_table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            tone = RED if p.days_pending >= 60 else (theme.AMBER if p.days_pending >= 30 else None)
            set_cell(self.pending_table, r, 0, p.customer.name, data=p.customer.id)
            set_cell(self.pending_table, r, 1, p.customer.mobile)
            set_cell(self.pending_table, r, 2, dates.format_date(p.oldest_unpaid_date))
            set_cell(self.pending_table, r, 3, str(p.days_pending), right=True, color=tone, bold=True)
            set_cell(self.pending_table, r, 4, money.format_inr(p.balance), right=True, color=RED, bold=True)
            set_cell(self.pending_table, r, 5, money.format_inr(p.last_deposit_paise) if p.last_deposit_date else "",
                     right=True, color=GREEN if p.last_deposit_date else None)
            set_cell(self.pending_table, r, 6, dates.format_date(p.last_deposit_date) if p.last_deposit_date else "")
            if keep == p.customer.id:
                self.pending_table.selectRow(r)
        total = sum(p.balance for p in rows)
        self.pending_summary.setText(
            f"{len(rows)} customer{'s' if len(rows) != 1 else ''} pending   |   Total to collect {money.format_inr(total)}"
            if rows else "Nobody is pending for this filter.")

    def _pending_customer(self):
        cid = selected_id(self.pending_table)
        if cid is None:
            self.info("Select a customer", "Click a customer in the list first.")
            return None
        return self._pending_rows.get(cid)

    def _pending_open_ledger(self) -> None:
        p = self._pending_customer()
        if p is not None:
            self.ledger_customer.setCurrentIndex(max(0, self.ledger_customer.findData(p.customer.id)))
            self.tabs.setCurrentIndex(TAB_LEDGER)

    def _pending_add_jama(self) -> None:
        p = self._pending_customer()
        if p is not None:
            index = self.jama_customer.findData(p.customer.id)
            if index >= 0:
                self.jama_customer.setCurrentIndex(index)
            self.tabs.setCurrentIndex(TAB_JAMA)
            self.jama_amount.setFocus()

    def _open_whatsapp(self, mobile: str, text: str) -> bool:
        """Open the customer's WhatsApp chat with the text typed. Returns False when no usable number is saved."""
        phone = whatsapp.normalize_phone(mobile)
        QDesktopServices.openUrl(QUrl(whatsapp.chat_url(phone, text)))
        return phone is not None

    def _whatsapp_reminder(self) -> None:
        p = self._pending_customer()
        if p is None:
            return
        text = whatsapp.reminder_message(p.customer.name, branding.BRAND_NAME, p.balance, p.days_pending,
                                         p.oldest_unpaid_date)
        if not self._open_whatsapp(p.customer.mobile, text):
            self.info("No mobile number", f"{p.customer.name} has no valid mobile number saved, so WhatsApp "
                      "will ask whom to send it to. Save the number in Customers (Edit) to skip this next time.")

    def _reveal_file(self, path: Path) -> None:
        """Show a saved file in its folder so it can be attached in WhatsApp."""
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", str(path)])
                return
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _whatsapp_statement(self) -> None:
        try:
            led = self._current_ledger()
        except KhataError as exc:
            self.warn("Cannot send", str(exc))
            return
        if led is None:
            self.info("No customer", "Select a customer first.")
            return
        folder = Path(_documents_dir()) / "VX7 KHATA Statements"
        path = folder / f"Statement_{_safe_filename(led.customer.name)}_{datetime.now():%Y%m%d_%H%M}.pdf"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            exports.export_statement_pdf(led, path, self.shop_name(), website=self.website())
        except (OSError, KhataError) as exc:
            self.warn("Could not create the PDF", str(exc))
            return
        text = whatsapp.statement_message(led.customer.name, branding.BRAND_NAME, led.closing_balance,
                                          exports._period_text(led.date_from, led.date_to))
        has_number = self._open_whatsapp(led.customer.mobile, text)
        self._reveal_file(path)
        extra = "" if has_number else "\n\nThis customer has no valid mobile number saved, so choose the contact in WhatsApp."
        self.info("Statement ready for WhatsApp",
                  f"The PDF is saved here:\n{path}\n\nWhatsApp has opened with the message typed. WhatsApp does not "
                  "accept files from other programs, so tap the attach (📎) button in the chat, choose Document, and "
                  f"pick this PDF from the folder that just opened.{extra}")

    # ------------------------------------------------------------ import old data (Excel / CSV)
    def _download_import_template(self) -> None:
        path = self._export_path("Save import template", "VX7_KHATA_import_template.xlsx", "Excel files (*.xlsx)")
        if not path:
            return
        try:
            importer.write_template(path)
        except OSError as exc:
            self.warn("Could not save the template", str(exc))
            return
        self._offer_open(path)

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the Excel or CSV file to import", _documents_dir(),
                                              "Excel / CSV (*.xlsx *.csv)")
        if not path:
            return
        try:
            plan = importer.plan_import(self.svc, path)
        except (importer.ImportFileError, OSError) as exc:
            self.warn("This file cannot be imported", str(exc))
            return
        if plan.errors:
            shown = [f"Row {line}: {msg}" for line, msg in plan.errors[:15]]
            more = f"\n…and {len(plan.errors) - 15} more problems." if len(plan.errors) > 15 else ""
            self.warn("Nothing was imported - fix these rows first",
                      f"{len(plan.errors)} problem(s) found. Nothing is imported until every row is valid.\n\n"
                      + "\n".join(shown) + more)
            return
        if not plan.rows:
            self.info("Nothing to import", "No data rows were found under the header row.")
            return
        rep = plan.report
        names = ", ".join(rep.new_customers[:8]) + (" …" if len(rep.new_customers) > 8 else "")
        lines = [f"File: {Path(path).name}", f"Entries to import: {len(plan.rows)}",
                 f"New customers: {len(rep.new_customers)}" + (f"  ({names})" if names else ""),
                 f"Existing customers matched: {rep.existing_customers}",
                 f"Total udhaar: {money.format_inr(rep.total_udhaar)}",
                 f"Total jama: {money.format_inr(rep.total_jama)}"]
        if rep.likely_duplicates:
            lines.append(f"\n⚠ {rep.likely_duplicates} entries look identical to entries already saved. "
                         "If you already imported this file, press No.")
        lines.append("\nA safety copy of your current data is saved first. Import now?")
        if not self.confirm("Import old data?", "\n".join(lines)):
            return
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.svc.create_backup(paths.safety_backup_dir() / f"before_import_{stamp}.db")
            done = importer.run_import(self.svc, plan)
        except (backup.BackupError, importer.ImportFileError, KhataError, OSError) as exc:
            self.warn("Import stopped - nothing was saved", str(exc))
            return
        self.refresh_all()
        self.info("Import complete", f"{done.imported} entries imported ({len(done.new_customers)} new customers).")

    # ------------------------------------------------------------ reports
    def _build_reports(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        reg_box = QGroupBox("Transaction register – filter by customer, dates and item, then export exactly that selection")
        reg = QFormLayout(reg_box)
        self.report_customer = QComboBox()
        self.rep_range = QCheckBox("Limit to date range")
        self.rep_from = DateField()
        self.rep_to = DateField()
        self.rep_from.setEnabled(False)
        self.rep_to.setEnabled(False)
        self.rep_range.toggled.connect(lambda on: (self.rep_from.setEnabled(on), self.rep_to.setEnabled(on)))
        dates_row = QHBoxLayout()
        dates_row.addWidget(self.rep_range)
        dates_row.addWidget(QLabel("From"))
        dates_row.addWidget(self.rep_from)
        dates_row.addWidget(QLabel("To"))
        dates_row.addWidget(self.rep_to)
        dates_row.addStretch(1)
        self.rep_search = QLineEdit()
        self.rep_search.setPlaceholderText("Item description contains… (optional)")
        reg.addRow("Customer", self.report_customer)
        reg.addRow("Dates", dates_row)
        reg.addRow("Item search", self.rep_search)
        reg_buttons = QHBoxLayout()
        reg_pdf = QPushButton("⤓  Register PDF")
        reg_xlsx = QPushButton("⤓  Register Excel")
        reg_pdf.setObjectName("primary")
        reg_xlsx.setObjectName("primary")
        reg_pdf.clicked.connect(lambda: self._export_register("pdf"))
        reg_xlsx.clicked.connect(lambda: self._export_register("xlsx"))
        reg_buttons.addStretch(1)
        reg_buttons.addWidget(reg_pdf)
        reg_buttons.addWidget(reg_xlsx)
        reg.addRow(reg_buttons)
        layout.addWidget(reg_box)

        # live summary of exactly what the filters above select (read-only; same figures the export uses)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.rep_cards = {
            "udhaar": StatCard("Selected Udhaar", "↑", theme.CORAL, compact=True),
            "jama": StatCard("Selected Jama", "↓", theme.GREEN, compact=True),
            "net": StatCard("Net (Udhaar − Jama)", "₹", theme.BLUE, compact=True),
            "count": StatCard("Entries selected", "☰", theme.AMBER, compact=True),
        }
        for card in self.rep_cards.values():
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        self.rep_preview = make_table(["Date", "Customer", "Item / Description", "Udhaar", "Jama"])
        fit_columns(self.rep_preview, 2)
        self.rep_preview.setMinimumHeight(150)
        layout.addWidget(self.rep_preview, 1)
        self.rep_preview_note = QLabel("")
        self.rep_preview_note.setObjectName("hint")
        layout.addWidget(self.rep_preview_note)
        self.report_customer.currentIndexChanged.connect(lambda _i: self._refresh_report_preview())
        self.rep_range.toggled.connect(lambda _on: self._refresh_report_preview())
        self.rep_from.dateChanged.connect(lambda _d: self._refresh_report_preview())
        self.rep_to.dateChanged.connect(lambda _d: self._refresh_report_preview())
        self.rep_search.textChanged.connect(lambda _t: self._refresh_report_preview())

        cust_box = QGroupBox("Customer balance summary (all customers, or those matching a name/phone filter)")
        cust = QFormLayout(cust_box)
        self.rep_cust_filter = QLineEdit()
        self.rep_cust_filter.setPlaceholderText("Name or phone contains… (optional)")
        cust.addRow("Customers", self.rep_cust_filter)
        cb = QHBoxLayout()
        cpdf = QPushButton("⤓  Balances PDF")
        cxlsx = QPushButton("⤓  Balances Excel")
        cpdf.setObjectName("primary")
        cxlsx.setObjectName("primary")
        cpdf.clicked.connect(lambda: self._export_customers("pdf"))
        cxlsx.clicked.connect(lambda: self._export_customers("xlsx"))
        cb.addStretch(1)
        cb.addWidget(cpdf)
        cb.addWidget(cxlsx)
        cust.addRow(cb)
        layout.addWidget(cust_box)

        tip = QLabel("For a single customer's statement with opening/closing balance and running balance, "
                     "use the Ledger tab.")
        tip.setObjectName("hint")
        layout.addWidget(tip)
        self.tabs.addTab(page, "Reports")

    def _refresh_report_preview(self) -> None:
        """Summary cards and a preview of the entries the register export would contain."""
        cid = self.report_customer.currentData() if self.report_customer.currentIndex() >= 0 else None
        args = {"search": self.rep_search.text(), "customer_ids": None if cid is None else [cid]}
        if self.rep_range.isChecked():
            args["date_from"] = self.rep_from.text_dmy()
            args["date_to"] = self.rep_to.text_dmy()
        try:
            reg = self.svc.register(**args)
        except KhataError as exc:
            self.rep_preview.setRowCount(0)
            self.rep_preview_note.setText(str(exc))
            return
        self.rep_cards["udhaar"].set(money.format_inr(reg.total_udhaar), RED if reg.total_udhaar else None)
        self.rep_cards["jama"].set(money.format_inr(reg.total_jama), GREEN if reg.total_jama else None)
        self.rep_cards["net"].set(money.format_inr(reg.net), balance_color(reg.net))
        self.rep_cards["count"].set(str(len(reg.rows)))
        shown = reg.rows[:200]
        self.rep_preview.setRowCount(len(shown))
        for r, row in enumerate(shown):
            t = row.txn
            jama = t.txn_type == "JAMA"
            set_cell(self.rep_preview, r, 0, dates.format_date(effective_date(t)))
            set_cell(self.rep_preview, r, 1, row.customer_name)
            set_cell(self.rep_preview, r, 2, t.item)
            set_cell(self.rep_preview, r, 3, "" if jama else money.format_inr(t.amount_paise), right=True, color=RED)
            set_cell(self.rep_preview, r, 4, money.format_inr(t.amount_paise) if jama else "", right=True, color=GREEN)
        self.rep_preview_note.setText(
            f"Showing the first {len(shown)} of {len(reg.rows)} entries. The export contains all of them."
            if len(reg.rows) > len(shown) else "The export contains exactly these entries.")

    def _export_register(self, kind: str) -> None:
        cid = self.report_customer.currentData()
        args = {"search": self.rep_search.text(), "customer_ids": None if cid is None else [cid]}
        if self.rep_range.isChecked():
            args["date_from"] = self.rep_from.text_dmy()
            args["date_to"] = self.rep_to.text_dmy()
        try:
            reg = self.svc.register(**args)
        except KhataError as exc:
            self.warn("Cannot export", str(exc))
            return
        if not reg.rows:
            self.info("Nothing to export", "No entries match these filters.")
            return
        label = self.report_customer.currentText() or "All customers"
        default = f"Register_{_safe_filename(label)}.{kind}"
        pattern = "PDF files (*.pdf)" if kind == "pdf" else "Excel files (*.xlsx)"
        path = self._export_path("Export register", default, pattern)
        if not path:
            return
        try:
            fn = exports.export_register_pdf if kind == "pdf" else exports.export_register_xlsx
            fn(reg, path, self.shop_name(), label, website=self.website())
        except (OSError, KhataError) as exc:
            self.warn("Export failed", str(exc))
            return
        self._offer_open(path)

    def _export_customers(self, kind: str) -> None:
        text = self.rep_cust_filter.text()
        summaries = self.svc.list_customers(text)
        if not summaries:
            self.info("Nothing to export", "No customers match this filter.")
            return
        default = f"Customer_balances.{kind}"
        pattern = "PDF files (*.pdf)" if kind == "pdf" else "Excel files (*.xlsx)"
        path = self._export_path("Export customer balances", default, pattern)
        if not path:
            return
        try:
            fn = exports.export_customers_pdf if kind == "pdf" else exports.export_customers_xlsx
            fn(summaries, path, self.shop_name(), text.strip(), website=self.website())
        except (OSError, KhataError) as exc:
            self.warn("Export failed", str(exc))
            return
        self._offer_open(path)

    # ------------------------------------------------------------ backup & settings
    def _build_backup(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        data_box = QGroupBox("Your data")
        data = QVBoxLayout(data_box)
        badges = QHBoxLayout()
        self.badge_db = QLabel("")
        self.badge_safety = QLabel("")
        self.badge_backup = QLabel("")
        for badge in (self.badge_db, self.badge_safety, self.badge_backup):
            badges.addWidget(badge)
        badges.addStretch(1)
        data.addLayout(badges)
        self.backup_info = QLabel("")
        self.backup_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.backup_info.setWordWrap(True)
        self.backup_info.setObjectName("hint")
        data.addWidget(self.backup_info)
        open_folder = QPushButton("📁  Open data folder")
        open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.svc.db_path.parent))))
        row = QHBoxLayout()
        row.addWidget(open_folder)
        row.addStretch(1)
        data.addLayout(row)
        layout.addWidget(data_box)

        bk_box = QGroupBox("Backup and restore")
        bk = QVBoxLayout(bk_box)
        create = QPushButton("⤓  Create backup…")
        restore = QPushButton("⤒  Restore from backup…")
        create.setObjectName("primary")
        create.clicked.connect(self._create_backup)
        restore.clicked.connect(self._restore_backup)
        bk.addWidget(create)
        bk.addWidget(restore)
        restore_note = QLabel("A restore first checks the backup file, then saves a safety copy of your current data "
                              "before replacing it.")
        restore_note.setObjectName("hint")
        restore_note.setWordWrap(True)
        bk.addWidget(restore_note)
        layout.addWidget(bk_box)

        imp_box = QGroupBox("Import old data from Excel / CSV")
        imp = QVBoxLayout(imp_box)
        imp_row = QHBoxLayout()
        template = QPushButton("⤓  Download template")
        import_btn = QPushButton("⤒  Import file…")
        import_btn.setObjectName("primary")
        template.clicked.connect(self._download_import_template)
        import_btn.clicked.connect(self._import_file)
        imp_row.addWidget(template)
        imp_row.addWidget(import_btn)
        imp_row.addStretch(1)
        imp.addLayout(imp_row)
        imp_note = QLabel("Fill the template (or use your own sheet with columns like Customer, Date, Item, Udhaar, "
                          "Jama). Every row is checked first; nothing is imported unless all rows are valid, and a "
                          "safety copy of your data is saved before importing.")
        imp_note.setObjectName("hint")
        imp_note.setWordWrap(True)
        imp.addWidget(imp_note)
        layout.addWidget(imp_box)

        set_box = QGroupBox("Statement header")
        sf = QFormLayout(set_box)
        self.shop_edit = QLineEdit(self.shop_name())
        self.shop_edit.setPlaceholderText("Optional extra business name shown under the SHREEJI BOXES header")
        self.website_edit = QLineEdit(self.website())
        self.website_edit.setPlaceholderText("Optional - leave empty to print no website")
        self.website_edit.setMaxLength(120)
        save_shop = QPushButton("Save")
        save_shop.setObjectName("primary")
        save_shop.clicked.connect(self._save_shop)
        line = QHBoxLayout()
        line.addWidget(self.website_edit, 1)
        line.addWidget(save_shop)
        sf.addRow("Business name", self.shop_edit)
        sf.addRow("Website", line)
        header_note = QLabel("Every PDF and Excel report carries the SHREEJI BOXES header and SJB watermark. "
                             "A website is printed only if you enter one here.")
        header_note.setObjectName("hint")
        header_note.setWordWrap(True)
        sf.addRow(header_note)
        layout.addWidget(set_box)

        about = QLabel(f"{APP_NAME} v{__version__}  –  works fully offline.")
        about.setObjectName("hint")
        layout.addWidget(about)
        layout.addStretch(1)
        self.tabs.addTab(page, "Backup && Settings")

    def _refresh_backup_info(self) -> None:
        d = self.svc.dashboard()
        self.backup_info.setText(
            f"Data file: {self.svc.db_path}\n{d.total_customers} customers, {d.total_transactions} entries."
        )
        self._set_badge(self.badge_db, "badgeOk" if self.svc.db_path.exists() else "badgeWarn",
                        "● Database online" if self.svc.db_path.exists() else "● Database file not found")
        safety = self.svc.db_path.parent / "safety_backups"
        copies = len(list(safety.glob("*.db"))) if safety.is_dir() else 0
        self._set_badge(self.badge_safety, "badgeInfo" if copies else "badgeWarn",
                        f"● {copies} safety cop{'y' if copies == 1 else 'ies'}" if copies else "● No safety copies yet")
        self._set_badge(self.badge_backup, "badgeOk" if self._last_backup_text.startswith("Last") else "badgeWarn",
                        "● " + self._last_backup_text)

    @staticmethod
    def _set_badge(label, kind: str, text: str) -> None:
        label.setObjectName(kind)
        label.setText(text)
        label.style().unpolish(label)
        label.style().polish(label)

    def _save_shop(self) -> None:
        self.svc.set_setting("shop_name", " ".join(self.shop_edit.text().split()))
        self.svc.set_setting("website", " ".join(self.website_edit.text().split()))
        self.info("Saved", "Statement header settings saved.")

    def _create_backup(self) -> None:
        default = f"VX7_KHATA_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
        path = self._export_path("Save backup", default, "VX7 KHATA backup (*.db)")
        if not path:
            return
        try:
            self.svc.create_backup(path)
            info = backup.validate_backup(path)
        except (backup.BackupError, OSError) as exc:
            self.warn("Backup failed", str(exc))
            return
        self._last_backup_text = f"Last backup {datetime.now():%H:%M} (verified)"
        self._refresh_backup_info()
        self.info("Backup complete", f"Saved and verified:\n{path}\n\n{info.customers} customers, "
                  f"{info.transactions} entries.")

    def _restore_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a backup to restore", _documents_dir(),
                                              "VX7 KHATA backup (*.db);;All files (*)")
        if not path:
            return
        try:
            info = backup.validate_backup(path)
        except backup.BackupError as exc:
            self.warn("This backup cannot be used", str(exc))
            return
        current = self.svc.dashboard()
        text = (f"Restore this backup?\n\n{path}\n\nBackup contains {info.customers} customers and "
                f"{info.transactions} entries.\nYour current data ({current.total_customers} customers, "
                f"{current.total_transactions} entries) will be replaced.\n\n"
                "A safety copy of the current data is saved first.")
        if not self.confirm("Restore backup", text):
            return
        try:
            safety = self.svc.restore_backup(path, safety_dir=self.svc.db_path.parent / "safety_backups")
        except (backup.BackupError, KhataError, OSError) as exc:
            self.warn("Restore failed", f"{exc}\n\nYour current data was not changed.")
            return
        self.shop_edit.setText(self.shop_name())
        self.website_edit.setText(self.website())
        self.refresh_all()
        self.info("Restore complete", f"Backup restored.\n\nSafety copy of your previous data:\n{safety}")


def RED_IF(amount: int):
    return RED if amount else None
