#!/usr/bin/env python
"""Lance l'interface graphique du RGP Downloader Lahocy (Phase 4)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Sans accélération GPU disponible (poste sans pilote graphique adapté, session
# distante/VM...), QtWebEngine affiche une zone de carte totalement noire. On
# repasse en rendu logiciel — plus lent, mais fiable sur tous les postes.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")
os.environ.setdefault("QT_OPENGL", "software")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# Recommandé par Qt avant toute création de QApplication utilisant QtWebEngine.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
