"""RiftStats 入口。

python -m app.main        # 需要 libs 在 PYTHONPATH 里（tools/run.ps1 会处理）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import QApplication

from .store import Store
from .ui import theme
from .ui.main_window import MainWindow


def resource_dir() -> Path:
    """打包后资源在 _MEIPASS，源码运行在项目根。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def asset(name: str) -> Path | None:
    p = resource_dir() / "assets" / name
    return p if p.exists() else None


def app_icon() -> QIcon:
    for name in ("riftstats.ico", "riftstats.png"):
        p = asset(name)
        if p:
            return QIcon(str(p))
    return QIcon()


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("RiftStats")
    app.setOrganizationName("RiftStats")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setWindowIcon(app_icon())
    app.setStyleSheet(theme.STYLESHEET)
    store = Store()
    window = MainWindow(store)
    window.setWindowIcon(app_icon())
    return app, window


def main() -> int:
    app, window = build_app()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
