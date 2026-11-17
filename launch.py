"""启动入口（源码运行 + PyInstaller 打包都用它）。

  python launch.py                 正常启动
  python launch.py --shot <dir>    离屏渲染四页到 PNG，验证打包是否完整
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_libs() -> Path | None:
    """依赖目录：先看环境变量，再看项目内，最后看 D 盘的公共位置。"""
    env = os.environ.get("RIFTSTATS_LIBS")
    candidates = [
        Path(env) if env else None,
        ROOT / "libs",
        Path(r"D:\GetKun\dev\libs"),
    ]
    for c in candidates:
        if c and c.is_dir():
            return c
    return None


LIBS = find_libs()
if LIBS and str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_streams() -> None:
    """没有控制台时（打包后双击），补一个日志流，免得写日志把程序顶死。"""
    if not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        base = Path(sys.executable).resolve().parent
        logdir = base / "data"
        logdir.mkdir(parents=True, exist_ok=True)
        fh = open(logdir / "launch.log", "a", encoding="utf-8", errors="ignore")
        fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 ===\n")
        fh.flush()
        sys.stdout = fh
        sys.stderr = fh
    except OSError:
        pass


def _hide_own_console() -> None:
    """双击启动时会带出一个黑框，自己拥有控制台时把它藏掉。"""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        buf = (ctypes.c_uint * 4)()
        attached = k32.GetConsoleProcessList(buf, 4)
        if attached <= 1:  # 只有自己，说明是从资源管理器双击起来的
            hwnd = k32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _excepthook(exc_type, exc, tb) -> None:
    import traceback

    try:
        sys.stderr.write("".join(traceback.format_exception(exc_type, exc, tb)))
        sys.stderr.flush()
    except Exception:
        pass


_ensure_streams()
_hide_own_console()

from app import diag  # noqa: E402
from app.store import data_dir  # noqa: E402

diag.set_dir(data_dir())
diag.dump_env()


def _hook(exc_type, exc, tb) -> None:
    try:
        diag.log("未捕获异常:\n" + "".join(traceback.format_exception(exc_type, exc, tb)), "ERROR")
    except Exception:
        pass
    _excepthook(exc_type, exc, tb)


sys.excepthook = _hook

from app.main import build_app, main  # noqa: E402

PAGES = ["dashboard", "matches", "teammates", "recommend", "import"]


def _shot(out_dir: str) -> int:
    """不弹窗，把四页各画一张图——用来确认冻结后的 exe 里 Qt 和图表都在。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication

    app, win = build_app([sys.argv[0]])
    win.resize(1400, 880)
    win.show()
    for _ in range(6):
        app.processEvents()
    for i, name in enumerate(PAGES):
        win.group.button(i).setChecked(True)
        win._goto(i)
        for _ in range(8):
            app.processEvents()
        win.grab().save(str(out / f"{name}.png"))
    # 让窗口和 QApplication 按顺序销毁，否则解释器退出时会在 Qt 里崩一下
    win.close()
    win.deleteLater()
    for _ in range(3):
        app.processEvents()
    del win
    app.quit()
    del app
    return 0


if __name__ == "__main__":
    if "--shot" in sys.argv:
        idx = sys.argv.index("--shot")
        target = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "shots_exe"
        raise SystemExit(_shot(target))
    raise SystemExit(main())
