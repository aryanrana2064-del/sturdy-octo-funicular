"""Visual theme for VX7 KHATA PRO: iOS-style frosted glass on a deep, colourful backdrop.

UI only. Nothing here touches data, calculations or the database. The whole look is one
Qt style sheet (``STYLE``) plus a matching dark palette, so every existing screen, dialog and
message box picks it up and the screens keep their original widgets and handlers.
"""
from __future__ import annotations

# ---- colour tokens (iOS system colours on a deep, colourful backdrop) --------
BG = "#0A1330"
PANEL = "#1B2350"       # solid surfaces: popups, dialogs
PANEL_HI = "#232D63"
TEXT = "#F2F5FF"
MUTED = "#A5B0D6"
BLUE = "#0A84FF"        # iOS blue
CYAN = "#64D2FF"        # iOS teal / light blue
GREEN = "#32D74B"       # iOS green (jama)
CORAL = "#FF6B63"       # iOS red, a touch softer (udhaar / outstanding)
AMBER = "#FF9F0A"
VIOLET = "#BF5AF2"

STYLE = """
* { font-family: "SF Pro Display", "SF Pro Text", "Segoe UI Variable Display", "Segoe UI Variable Text",
                 "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px; color: #F2F5FF; }
QMainWindow { background: #0A1330; }
QDialog, QMessageBox { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1A2552, stop:1 #140F33); }
QLabel { background: transparent; }
QToolTip { background: #1B2350; color: #F2F5FF; border: 1px solid rgba(255, 255, 255, 0.25);
           padding: 6px 10px; border-radius: 10px; }

/* ---------- shell: frosted sidebar + top bar ---------- */
QFrame#sidebar { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                     stop:0 rgba(255, 255, 255, 0.11), stop:1 rgba(255, 255, 255, 0.04));
                 border: none; border-right: 1px solid rgba(255, 255, 255, 0.16); }
QLabel#logoBadge { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0A84FF, stop:1 #64D2FF);
                   color: #FFFFFF; font-weight: bold; font-size: 15px; border-radius: 14px;
                   border: 1px solid rgba(255, 255, 255, 0.45); }
QLabel#logoTitle { font-size: 16px; font-weight: bold; color: #FFFFFF; }
QLabel#logoSub { color: #64D2FF; font-size: 10px; font-weight: bold; }
QPushButton#navButton { text-align: left; padding: 11px 14px; border: 1px solid transparent; border-radius: 14px;
                        background: transparent; color: rgba(255, 255, 255, 0.70); font-weight: bold; }
QPushButton#navButton:hover { background: rgba(255, 255, 255, 0.09); color: #FFFFFF; }
QPushButton#navButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 rgba(255, 255, 255, 0.22), stop:1 rgba(255, 255, 255, 0.12));
                                border: 1px solid rgba(255, 255, 255, 0.28); color: #FFFFFF; }
QPushButton#navButton:pressed { padding-top: 12px; padding-bottom: 10px; }
QPushButton#navButton:focus { border: 1px solid rgba(100, 210, 255, 0.85); }
QFrame#profile { background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.18);
                 border-radius: 18px; }
QLabel#avatar { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #BF5AF2, stop:1 #0A84FF);
                color: #FFFFFF; font-weight: bold; border-radius: 18px; border: 1px solid rgba(255, 255, 255, 0.4); }
QLabel#profileName { font-weight: bold; color: #FFFFFF; }
QLabel#profileSub { color: rgba(255, 255, 255, 0.55); font-size: 11px; }
QPushButton#profileButton { padding: 5px 10px; font-size: 12px; }
QPushButton#navToggle { padding: 0px; font-size: 16px; border-radius: 19px; }
QLabel#pageTitle { font-size: 24px; font-weight: bold; color: #FFFFFF; }
QLabel#pageSub { color: rgba(255, 255, 255, 0.60); }
QLabel#chip { background: rgba(255, 255, 255, 0.09); border: 1px solid rgba(255, 255, 255, 0.20);
              border-radius: 14px; padding: 6px 14px; color: rgba(255, 255, 255, 0.85); }
QTabWidget::pane { background: transparent; border: none; }
QFrame#content { background: transparent; border: none; }

/* ---------- frosted glass cards and panels ---------- */
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                  stop:0 rgba(255, 255, 255, 0.17), stop:1 rgba(255, 255, 255, 0.06));
              border: 1px solid rgba(255, 255, 255, 0.20); border-top: 1px solid rgba(255, 255, 255, 0.40);
              border-radius: 22px; }
QFrame#card[hover="true"] { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                  stop:0 rgba(255, 255, 255, 0.24), stop:1 rgba(255, 255, 255, 0.09));
              border: 1px solid rgba(255, 255, 255, 0.34); border-top: 1px solid rgba(255, 255, 255, 0.60); }
QLabel#cardTitle { color: rgba(255, 255, 255, 0.68); font-size: 12px; font-weight: bold; }
QLabel#cardValue { font-size: 26px; font-weight: bold; color: #FFFFFF; }
QGroupBox { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(255, 255, 255, 0.11), stop:1 rgba(255, 255, 255, 0.04));
            border: 1px solid rgba(255, 255, 255, 0.17); border-top: 1px solid rgba(255, 255, 255, 0.32);
            border-radius: 22px; margin-top: 16px; padding: 22px 16px 14px 16px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 20px; padding: 0 8px;
                   color: rgba(255, 255, 255, 0.72); }
QLabel#hint { color: rgba(255, 255, 255, 0.55); }
QLabel#success { color: #32D74B; font-weight: bold; }
QLabel#badgeOk { background: rgba(50, 215, 75, 0.18); border: 1px solid rgba(50, 215, 75, 0.60);
                 color: #5CE673; border-radius: 13px; padding: 6px 13px; font-weight: bold; }
QLabel#badgeWarn { background: rgba(255, 159, 10, 0.18); border: 1px solid rgba(255, 159, 10, 0.65);
                   color: #FFB840; border-radius: 13px; padding: 6px 13px; font-weight: bold; }
QLabel#badgeInfo { background: rgba(10, 132, 255, 0.20); border: 1px solid rgba(64, 156, 255, 0.70);
                   color: #7DBBFF; border-radius: 13px; padding: 6px 13px; font-weight: bold; }
QLabel#toast { background: rgba(24, 32, 72, 0.94); border: 1px solid rgba(255, 255, 255, 0.30);
               border-top: 1px solid rgba(255, 255, 255, 0.50); border-radius: 18px; padding: 13px 22px;
               color: #FFFFFF; font-weight: bold; }

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QComboBox, QDateEdit { background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.16); border-radius: 12px; padding: 8px 12px;
        color: #F2F5FF; selection-background-color: #0A84FF; }
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QDateEdit:hover { border: 1px solid rgba(255, 255, 255, 0.30);
        background: rgba(255, 255, 255, 0.11); }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus { border: 1px solid #0A84FF;
        background: rgba(255, 255, 255, 0.13); }
QLineEdit:read-only { color: rgba(255, 255, 255, 0.65); background: rgba(255, 255, 255, 0.05); }
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QDateEdit:disabled { color: rgba(255, 255, 255, 0.35);
        background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08); }
QComboBox QAbstractItemView { background: #1B2350; border: 1px solid rgba(255, 255, 255, 0.20); border-radius: 12px;
        padding: 4px; outline: 0; selection-background-color: rgba(10, 132, 255, 0.65); color: #F2F5FF; }
QCalendarWidget QWidget { background: #1B2350; color: #F2F5FF; }
QCalendarWidget QAbstractItemView:enabled { background: #1B2350; color: #F2F5FF;
        selection-background-color: #0A84FF; selection-color: #FFFFFF; }
QCalendarWidget QAbstractItemView:disabled { color: rgba(255, 255, 255, 0.30); }
QCalendarWidget QToolButton { background: transparent; color: #F2F5FF; border: none; padding: 4px 8px;
        border-radius: 8px; }
QCalendarWidget QToolButton:hover { background: rgba(255, 255, 255, 0.14); }

/* segmented Udhaar / Jama toggle */
QRadioButton { spacing: 0px; padding: 10px 20px; border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 15px;
               background: rgba(255, 255, 255, 0.07); color: rgba(255, 255, 255, 0.72); font-weight: bold; }
QRadioButton::indicator { width: 0px; height: 0px; }
QRadioButton:hover { border: 1px solid rgba(255, 255, 255, 0.34); color: #FFFFFF; background: rgba(255, 255, 255, 0.11); }
QRadioButton:focus { border: 1px solid rgba(100, 210, 255, 0.85); }
QRadioButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3D9BFF, stop:1 #0A84FF);
                       border: 1px solid rgba(255, 255, 255, 0.45); color: #FFFFFF; }
QRadioButton#segUdhaar:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF857E, stop:1 #FF453A);
                                 border: 1px solid rgba(255, 255, 255, 0.45); color: #FFFFFF; }
QRadioButton#segJama:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5BE36F, stop:1 #30D158);
                               border: 1px solid rgba(255, 255, 255, 0.45); color: #FFFFFF; }
QCheckBox { spacing: 8px; color: rgba(255, 255, 255, 0.85); }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 9px; border: 1px solid rgba(255, 255, 255, 0.35);
                       background: rgba(255, 255, 255, 0.08); }
QCheckBox::indicator:hover { border: 1px solid rgba(255, 255, 255, 0.65); }
QCheckBox::indicator:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3D9BFF, stop:1 #0A84FF);
                               border: 1px solid rgba(255, 255, 255, 0.55); }

/* ---------- glass pill buttons ---------- */
QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                  stop:0 rgba(255, 255, 255, 0.20), stop:1 rgba(255, 255, 255, 0.09));
              border: 1px solid rgba(255, 255, 255, 0.22); border-top: 1px solid rgba(255, 255, 255, 0.42);
              border-radius: 15px; padding: 9px 18px; color: #FFFFFF; font-weight: bold; }
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 0.30), stop:1 rgba(255, 255, 255, 0.15));
                    border: 1px solid rgba(255, 255, 255, 0.38); border-top: 1px solid rgba(255, 255, 255, 0.60); }
QPushButton:pressed { background: rgba(255, 255, 255, 0.07); border: 1px solid rgba(255, 255, 255, 0.20);
                      padding-top: 10px; padding-bottom: 8px; }
QPushButton:focus { border: 1px solid rgba(100, 210, 255, 0.90); }
QPushButton:disabled { color: rgba(255, 255, 255, 0.35); background: rgba(255, 255, 255, 0.05);
                       border: 1px solid rgba(255, 255, 255, 0.08); }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4DA3FF, stop:1 #0A84FF);
                      border: 1px solid rgba(255, 255, 255, 0.40); border-top: 1px solid rgba(255, 255, 255, 0.70);
                      color: #FFFFFF; }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6BB4FF, stop:1 #2B95FF);
                            border: 1px solid rgba(255, 255, 255, 0.55); border-top: 1px solid rgba(255, 255, 255, 0.85); }
QPushButton#primary:pressed { background: #0A6FDB; border: 1px solid rgba(255, 255, 255, 0.30);
                              padding-top: 10px; padding-bottom: 8px; }
QPushButton#primary:disabled { background: rgba(10, 132, 255, 0.28); color: rgba(255, 255, 255, 0.45);
                               border: 1px solid rgba(255, 255, 255, 0.12); }
QPushButton#danger { background: rgba(255, 69, 58, 0.20); border: 1px solid rgba(255, 105, 97, 0.65);
                     border-top: 1px solid rgba(255, 150, 144, 0.85); color: #FF9A94; }
QPushButton#danger:hover { background: rgba(255, 69, 58, 0.40); color: #FFFFFF; }
QPushButton#danger:pressed { background: rgba(255, 69, 58, 0.55); padding-top: 10px; padding-bottom: 8px; }

/* ---------- tables ---------- */
QTableWidget, QTableView { background: rgba(8, 14, 40, 0.42); alternate-background-color: rgba(255, 255, 255, 0.045);
        border: 1px solid rgba(255, 255, 255, 0.16); border-top: 1px solid rgba(255, 255, 255, 0.28);
        border-radius: 18px; gridline-color: transparent;
        selection-background-color: rgba(10, 132, 255, 0.55); selection-color: #FFFFFF; outline: 0; }
QTableWidget::item, QTableView::item { padding: 6px 8px; border: none; }
QTableWidget::item:hover, QTableView::item:hover { background: rgba(255, 255, 255, 0.09); }
QTableWidget::item:selected, QTableView::item:selected { background: rgba(10, 132, 255, 0.60); color: #FFFFFF; }
QHeaderView { background: transparent; }
QHeaderView::section { background: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.78); padding: 10px 8px;
                       border: none; border-bottom: 1px solid rgba(255, 255, 255, 0.16); font-weight: bold; }
QHeaderView::section:vertical { border-bottom: 1px solid rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.45);
                                padding: 4px 8px; }
QTableCornerButton::section { background: rgba(255, 255, 255, 0.08); border: none; }

/* ---------- scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.28); border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.50); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: rgba(255, 255, 255, 0.28); border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 0.50); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: none; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

QDialogButtonBox QPushButton { min-width: 84px; }
QMessageBox QLabel { color: #F2F5FF; }
"""


def apply_palette(app) -> None:
    """Dark palette so any widget the style sheet does not cover (native popups etc.) still matches."""
    from PySide6.QtGui import QColor, QPalette

    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG, QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: "#121A42", QPalette.ColorRole.AlternateBase: PANEL_HI,
        QPalette.ColorRole.Text: TEXT, QPalette.ColorRole.Button: PANEL_HI,
        QPalette.ColorRole.ButtonText: TEXT, QPalette.ColorRole.ToolTipBase: "#1B2350",
        QPalette.ColorRole.ToolTipText: TEXT, QPalette.ColorRole.Highlight: BLUE,
        QPalette.ColorRole.HighlightedText: "#FFFFFF", QPalette.ColorRole.PlaceholderText: "#8591BA",
        QPalette.ColorRole.BrightText: "#FFFFFF", QPalette.ColorRole.Link: CYAN,
    }
    for role, colour in roles.items():
        p.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6F7BA3"))
    app.setPalette(p)
