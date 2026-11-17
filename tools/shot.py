"""离屏截图：不弹窗口，把每一页画成 PNG，方便检查排版。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main import build_app  # noqa: E402

OUT = ROOT / "shots"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    app, win = build_app([sys.argv[0]])
    win.resize(1400, 880)
    win.show()
    for _ in range(6):
        app.processEvents()

    names = ["dashboard", "matches", "teammates", "recommend", "import"]
    for i, name in enumerate(names):
        win.group.button(i).setChecked(True)
        win._goto(i)
        for _ in range(8):
            app.processEvents()
        path = OUT / f"{name}.png"
        win.grab().save(str(path))
        print("saved", path)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
