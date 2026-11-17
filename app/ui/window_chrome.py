"""Windows 窗口外观微调：把系统标题栏刷成深色，跟应用背景连成一片。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_BORDER_COLOR = 34

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020


def _colorref(hex_rgb: str) -> int:
    """DWM 的颜色是 0x00BBGGRR。"""
    h = hex_rgb.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_dark_titlebar(hwnd: int, caption: str = "#080D12", text: str = "#E8E4D9") -> bool:
    """Win10 1809+ 可以只开深色模式；Win11 还能自定义标题栏底色。"""
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.windll.dwmapi
    except OSError:
        return False

    dwm.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
    ]
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long

    h = wintypes.HWND(hwnd)
    ok = False
    for attr in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
        value = ctypes.c_int(1)
        if dwm.DwmSetWindowAttribute(
            h, attr, ctypes.byref(value), ctypes.sizeof(value)
        ) == 0:
            ok = True
            break

    # Win11 专属：直接把标题栏背景刷成应用底色（Win10 会返回错误，忽略即可）
    for attr, hex_color in (
        (DWMWA_CAPTION_COLOR, caption),
        (DWMWA_TEXT_COLOR, text),
        (DWMWA_BORDER_COLOR, caption),
    ):
        value = ctypes.c_int(_colorref(hex_color))
        try:
            dwm.DwmSetWindowAttribute(h, attr, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    # 让标题栏立刻重绘
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos(
            h, wintypes.HWND(0), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    except Exception:
        pass
    return ok
