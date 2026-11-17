"""可复用的小组件：KPI 卡片、区块标题、图表工厂。"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalBarSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import QMargins, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


class Card(QFrame):
    """KPI 卡片：小标题 + 大数字 + 一行备注。"""

    def __init__(self, label: str, value: str = "--", hint: str = "", accent: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)

        self._label = QLabel(label)
        self._label.setObjectName("CardLabel")
        self._value = QLabel(value)
        self._value.setObjectName("CardValue")
        if accent:
            self._value.setStyleSheet(f"color: {accent};")
        self._hint = QLabel(hint)
        self._hint.setObjectName("CardHint")

        lay.addWidget(self._label)
        lay.addWidget(self._value)
        lay.addWidget(self._hint)
        lay.addStretch(1)

    def set_value(self, value: str, hint: str | None = None, color: str | None = None) -> None:
        self._value.setText(value)
        if color:
            self._value.setStyleSheet(f"color: {color};")
        if hint is not None:
            self._hint.setText(hint)


class SectionTitle(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


def panel(*, margins: int = 16, spacing: int = 12) -> tuple[QFrame, QVBoxLayout]:
    """返回一个带边框的容器和它的竖向布局。"""
    frame = QFrame()
    frame.setObjectName("Panel")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return frame, lay


def hline() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.BORDER};")
    return line


def _style_chart(chart: QChart, title: str = "", legend: bool = True, left: int = 10) -> None:
    chart.setBackgroundBrush(QColor(theme.PANEL))
    chart.setPlotAreaBackgroundVisible(False)
    chart.setMargins(QMargins(left, 6, 10, 6))
    if title:
        chart.setTitle(title)
        chart.setTitleBrush(QColor(theme.TEXT_DIM))
        chart.setTitleFont(theme.font(9, 500))
    legend_obj = chart.legend()
    legend_obj.setVisible(legend)
    legend_obj.setLabelColor(QColor(theme.TEXT_DIM))
    legend_obj.setFont(theme.font(9))
    legend_obj.setAlignment(Qt.AlignmentFlag.AlignTop)
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)


def _axis(chart: QChart, axis, align) -> None:
    chart.addAxis(axis, align)
    axis.setLabelsColor(QColor(theme.TEXT_DIM))
    axis.setGridLineColor(QColor(theme.BORDER))
    axis.setLinePenColor(QColor(theme.BORDER))
    axis.setLabelsFont(theme.font(8))


def _nice_ceil(v: float) -> float:
    """把最大值向上取整到 1/2/2.5/5/10 × 10^n，刻度看起来才不别扭。"""
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= v:
            return m * exp
    return 10 * exp


def bar_chart(
    categories: Sequence[str],
    series: dict[str, Sequence[float]],
    colors: Sequence[str],
    *,
    title: str = "",
    horizontal: bool = False,
    value_fmt: str = "{:.0f}",
    min_height: int = 240,
    bar_width: float = 0.0,
) -> QChartView:
    chart = QChart()
    _style_chart(chart, title, left=150 if horizontal else 10)

    base = QHorizontalBarSeries() if horizontal else QBarSeries()
    if bar_width:
        base.setBarWidth(bar_width)
    for (name, values), color in zip(series.items(), colors):
        bar = QBarSet(name)
        bar.setColor(QColor(color))
        bar.setBorderColor(QColor(color))
        bar.append([float(v) for v in values])
        bar.setLabelColor(QColor(theme.TEXT_DIM))
        base.append(bar)
    base.setLabelsVisible(False)
    chart.addSeries(base)

    cat_axis = QBarCategoryAxis()
    cat_axis.append(list(categories))
    value_axis = QValueAxis()
    top = max((max(v) for v in series.values() if v), default=1.0)
    value_axis.setRange(0, _nice_ceil(top * 1.08))
    value_axis.setTickCount(5)
    value_axis.setLabelFormat("%.0f")

    if horizontal:
        _axis(chart, cat_axis, Qt.AlignmentFlag.AlignLeft)
        _axis(chart, value_axis, Qt.AlignmentFlag.AlignBottom)
    else:
        _axis(chart, cat_axis, Qt.AlignmentFlag.AlignBottom)
        _axis(chart, value_axis, Qt.AlignmentFlag.AlignLeft)
    base.attachAxis(cat_axis)
    base.attachAxis(value_axis)

    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setMinimumHeight(min_height)
    view.setStyleSheet("background: transparent;")
    return view


def donut_chart(wins: int, losses: int, *, title: str = "") -> QChartView:
    chart = QChart()
    _style_chart(chart, title, legend=True)
    series = QPieSeries()
    series.setHoleSize(0.62)
    total = max(wins + losses, 1)
    for label, value, color in (
        ("胜", wins, theme.WIN),
        ("负", losses, theme.LOSS),
    ):
        if value <= 0:
            continue
        sl = series.append(f"{label} {value}", value)
        sl.setBrush(QColor(color))
        sl.setPen(QColor(theme.PANEL))
        sl.setLabelColor(QColor(theme.TEXT))
        sl.setLabel(f"{label} {value}")
        sl.setLabelVisible(False)
    chart.addSeries(series)

    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setMinimumHeight(220)
    view.setStyleSheet("background: transparent;")
    return view


def fmt_int(v: float) -> str:
    return f"{int(round(v)):,}"


def fmt_k(v: float) -> str:
    """12,345 -> 12.3k"""
    if v >= 10000:
        return f"{v/1000:.1f}k"
    return fmt_int(v)


def badge(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color}; border: 1px solid {color}; border-radius: 8px;"
        f"padding: 1px 8px; font-size: 10px;"
    )
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
    return lbl


class NumItem:
    """按数值排序的单元格。"""

    @staticmethod
    def make(text: str, value: float):
        from PySide6.QtWidgets import QTableWidgetItem

        class _NumItem(QTableWidgetItem):
            def __lt__(self, other):
                try:
                    return float(self.data(Qt.ItemDataRole.UserRole)) < float(
                        other.data(Qt.ItemDataRole.UserRole)
                    )
                except (TypeError, ValueError):
                    return super().__lt__(other)

        item = _NumItem(text)
        item.setData(Qt.ItemDataRole.UserRole, float(value))
        return item


def make_table(headers: Sequence[str], *, stretch_last: bool = False):
    """统一风格的数据表格。"""
    from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget

    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch_last:
        table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setDefaultSectionSize(30)
    return table


def row(*widgets: QWidget, spacing: int = 12) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for it in widgets:
        lay.addWidget(it)
    return w


class HBarList(QWidget):
    """自己画的横向条形榜单。

    QtCharts 的横向 bar 会把中文类目标签挤成 "…"，不如手绘可控：
    左边名字、右边条形、末尾数值，另带一条参考线（比如 50% 胜率）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, float, str]] = []
        self._color = theme.GOLD
        self._marker: float | None = None
        self._max = 100.0
        self._name_w = 120
        self.setMinimumHeight(80)

    def set_items(
        self,
        items: list[tuple[str, float, str]],
        *,
        color: str | None = None,
        marker: float | None = None,
        max_value: float | None = None,
        name_width: int = 120,
    ) -> None:
        self._items = items
        self._color = color or theme.GOLD
        self._marker = marker
        self._max = max_value or max([v for _, v, _ in items] + [1.0])
        self._name_w = name_width
        self.setMinimumHeight(max(80, 30 * len(items) + 16))
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(400, max(80, 30 * len(self._items) + 16))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._items:
            p.setPen(QColor(theme.TEXT_DIM))
            p.setFont(theme.font(9))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "没有数据")
            return

        row_h = 30
        bar_h = 12
        pad = 8
        left = self._name_w + 12
        right_pad = 62
        usable = max(60, self.width() - left - right_pad)
        max_v = self._max or 1.0

        p.setFont(theme.font(9))
        for i, (name, value, text) in enumerate(self._items):
            y = pad + i * row_h
            mid = y + row_h / 2

            # 名字
            p.setPen(QColor(theme.TEXT))
            p.drawText(
                0, y, self._name_w, row_h,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                name,
            )

            # 轨道
            track = QRectF(left, mid - bar_h / 2, usable, bar_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.PANEL_ALT))
            p.drawRoundedRect(track, bar_h / 2, bar_h / 2)

            # 条形
            w = usable * max(0.0, min(1.0, value / max_v))
            if w > 2:
                p.setBrush(QColor(self._color))
                p.drawRoundedRect(QRectF(left, mid - bar_h / 2, w, bar_h), bar_h / 2, bar_h / 2)

            # 数值
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(
                left + usable + 8, y, right_pad, row_h,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )

        # 参考线
        if self._marker is not None and 0 < self._marker < max_v:
            x = left + usable * (self._marker / max_v)
            pen = QPen(QColor(theme.TEXT_DIM))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(1)
            p.setPen(pen)
            p.drawLine(int(x), pad - 2, int(x), pad + row_h * len(self._items) - 4)
