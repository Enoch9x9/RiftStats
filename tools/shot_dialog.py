"""单独截一张"录入一场对局"对话框，带示例截图。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import theme  # noqa: E402
from app.ui.image_dialog import ImageImportDialog  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    img = ROOT / "samples" / "scoreboard.png"
    dlg = ImageImportDialog(str(img) if img.exists() else "")
    dlg.resize(1180, 760)
    dlg.show()
    for _ in range(10):
        app.processEvents()
    out = ROOT / "shots" / "dialog.png"
    dlg.grab().save(str(out))
    print("saved", out)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
