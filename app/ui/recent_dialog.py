"""同步完最近 20 场后弹出来的评价窗。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..stats import RecentReport
from . import theme

GRADE_COLOR = {
    "S": theme.GOLD,
    "A": theme.WIN,
    "B": theme.ACCENT,
    "C": "#E8A33D",
    "D": theme.LOSS,
}


class RecentDialog(QDialog):
    """点哪儿都关，关掉之后主窗口自动回总览。"""

    def __init__(self, report: RecentReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("近期评价")
        self.setModal(True)
        self.setMinimumWidth(640)
        # 主窗口前面：强制置顶 + 抢焦点，否则任务栏一闪就没了
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 24, 30, 20)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(22)
        grade = QLabel(report.grade)
        grade.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grade.setFixedWidth(120)
        grade.setStyleSheet(
            f"color: {GRADE_COLOR.get(report.grade, theme.TEXT)};"
            "font-size: 88px; font-weight: 800;"
        )
        top.addWidget(grade)

        right = QVBoxLayout()
        right.setSpacing(6)
        title = QLabel(
            f"最近 {report.games} 场 · {report.score:.0f} 分 · 胜率 {report.win_rate*100:.0f}%"
        )
        title.setObjectName("PageTitle")
        right.addWidget(title)
        note = QLabel(report.mode_note or "以输出为主要口径")
        note.setObjectName("CardHint")
        right.addWidget(note)
        top.addLayout(right, 1)
        root.addLayout(top)

        comment = QLabel(report.comment)
        comment.setWordWrap(True)
        comment.setStyleSheet(f"color: {theme.TEXT}; font-size: 15px;")
        root.addWidget(comment)

        line = QLabel(
            f"每分钟伤害 {report.dpm:,.0f}（平时 {report.dpm_base:,.0f}）    "
            f"队内占比 {report.share*100:.1f}%（平时 {report.share_base*100:.1f}%）    "
            f"KDA {report.kda:.2f}（平时 {report.kda_base:.2f}）"
        )
        line.setObjectName("CardHint")
        root.addWidget(line)

        buttons = QHBoxLayout()
        hint = QLabel("点任意位置或按 Esc 关闭")
        hint.setObjectName("CardHint")
        buttons.addWidget(hint)
        buttons.addStretch(1)
        go = QPushButton("去看对局记录")
        go.clicked.connect(self.accept)
        buttons.addWidget(go)
        root.addLayout(buttons)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.accept()
