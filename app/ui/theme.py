"""视觉主题：深海军蓝 + 海克斯金，模仿客户端但更适合长时间看数据。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

# ---- 调色板 ----------------------------------------------------------------
BG = "#080D12"
SIDEBAR = "#0C141B"
PANEL = "#121C25"
PANEL_ALT = "#16232E"
BORDER = "#22323F"
GOLD = "#C8AA6E"
GOLD_DIM = "#8C7748"
TEXT = "#E8E4D9"
TEXT_DIM = "#8D9AA7"
WIN = "#57C7A3"
LOSS = "#E06A6A"
ACCENT = "#3FA9F5"
WARN = "#E0A038"


def qcolor(hex_str: str, alpha: int = 255) -> QColor:
    c = QColor(hex_str)
    c.setAlpha(alpha)
    return c


def font(size: int = 10, weight: int = 400, family: str = "Microsoft YaHei UI") -> QFont:
    f = QFont(family, size)
    f.setWeight(QFont.Weight(weight))
    return f


STYLESHEET = f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    color: {TEXT};
}}
QMainWindow, QWidget#Root {{
    background: {BG};
}}
QWidget#Sidebar {{
    background: {SIDEBAR};
    border-right: 1px solid {BORDER};
}}
QLabel#Brand {{
    color: {GOLD};
    font-size: 19px;
    font-weight: 700;
    letter-spacing: 2px;
}}
QLabel#BrandSub {{
    color: {TEXT_DIM};
    font-size: 10px;
    letter-spacing: 1px;
}}
QPushButton#Nav {{
    text-align: left;
    padding: 11px 16px;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    background: transparent;
    color: {TEXT_DIM};
    font-size: 13px;
}}
QPushButton#Nav:hover {{
    background: {PANEL};
    color: {TEXT};
    border-radius: 0;
}}
QPushButton#Nav:checked {{
    background: {PANEL};
    color: {GOLD};
    border-left: 3px solid {GOLD};
    border-radius: 0;
    font-weight: 600;
}}
QWidget#Panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#PageTitle {{
    font-size: 21px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#PageSub {{
    font-size: 11px;
    color: {TEXT_DIM};
}}
QLabel#CardLabel {{
    font-size: 11px;
    color: {TEXT_DIM};
}}
QLabel#CardValue {{
    font-size: 25px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#CardHint {{
    font-size: 10px;
    color: {TEXT_DIM};
}}
QLabel#SectionTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {GOLD};
}}
QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
}}
QPushButton:hover {{
    border-color: {GOLD_DIM};
    background: #1B2A36;
}}
QPushButton:pressed {{
    background: #0F1A22;
}}
QPushButton#Primary {{
    background: {GOLD};
    color: #12100A;
    border: 1px solid {GOLD};
    font-weight: 700;
}}
QPushButton#Primary:hover {{
    background: #D8BD85;
}}
QPushButton:disabled {{
    color: #55606B;
    border-color: #1B2731;
    background: #0F171E;
}}
QTableWidget, QTableView {{
    background: {PANEL};
    alternate-background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    selection-background-color: #24323F;
    selection-color: {TEXT};
}}
QHeaderView {{
    background: {PANEL};
    border: none;
}}
QHeaderView::section {{
    background: {PANEL_ALT};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px 6px;
    font-size: 11px;
}}
QTableCornerButton::section {{
    background: {PANEL_ALT};
    border: none;
}}
QTableWidget::item {{
    padding: 6px 4px;
    font-size: 12px;
}}
QTextEdit, QPlainTextEdit {{
    background: #0B1319;
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: #9FB0BF;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    min-height: 16px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 14px;
    background: #1B2A36;
    border: none;
}}
QSpinBox::up-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {TEXT_DIM};
}}
QSpinBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_DIM};
}}
QCheckBox {{
    color: {TEXT_DIM};
    font-size: 11px;
    spacing: 4px;
}}
QCheckBox::indicator {{
    width: 12px;
    height: 12px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {PANEL_ALT};
}}
QCheckBox::indicator:checked {{
    background: {GOLD};
    border-color: {GOLD};
}}
QDialog {{
    background: {BG};
}}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: #24323F;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2A3A47;
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0;
    background: transparent;
}}
QScrollBar:horizontal {{
    height: 10px;
    background: transparent;
}}
QScrollBar::handle:horizontal {{
    background: #2A3A47;
    border-radius: 5px;
}}
QSplitter::handle {{
    background: {BORDER};
}}
QToolTip {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {GOLD_DIM};
    padding: 4px;
}}
QStatusBar {{
    background: {SIDEBAR};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
}}
"""


def align_center() -> Qt.AlignmentFlag:
    return Qt.AlignmentFlag.AlignCenter
