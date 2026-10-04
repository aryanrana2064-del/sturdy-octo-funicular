"""Application bootstrap."""
from __future__ import annotations

import sys

from . import APP_NAME, paths
from .ui import theme

STYLE = theme.STYLE  # the premium dark glass theme lives in ui/theme.py


def run() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import db
    from .service import KhataService
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    theme.apply_palette(app)
    app.setStyleSheet(STYLE)

    try:
        service = KhataService(paths.db_path())
    except (db.DatabaseError, OSError) as exc:
        QMessageBox.critical(None, APP_NAME, f"The data file could not be opened:\n\n{exc}\n\n{paths.db_path()}")
        return 1

    window = MainWindow(service)
    window.show()
    code = app.exec()
    service.close()
    return code
