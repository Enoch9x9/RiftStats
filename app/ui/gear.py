"""出装与海克斯强化统计页。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import Match
from ..stats import GearRow, gear_table, summarize
from . import theme, widgets


class GearPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._matches: list[Match] = []
        self._viewer: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        head = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("出装与强化")
        title.setObjectName("PageTitle")
        self.sub = QLabel("—")
        self.sub.setObjectName("PageSub")
        box.addWidget(title)
        box.addWidget(self.sub)
        head.addLayout(box)
        head.addStretch(1)
        head.addWidget(QLabel("英雄"))
        self.champ_box = QComboBox()
        self.champ_box.setMinimumWidth(150)
        self.champ_box.currentIndexChanged.connect(self._rebuild)
        head.addWidget(self.champ_box)
        head.addWidget(QLabel("最少场次"))
        self.min_games = QComboBox()
        self.min_games.addItems(["1", "2", "3", "5", "10"])
        self.min_games.setCurrentIndex(2)
        self.min_games.currentIndexChanged.connect(self._rebuild)
        head.addWidget(self.min_games)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)

        item_panel, item_lay = widgets.panel()
        item_lay.addWidget(widgets.SectionTitle("装备"))
        self.item_table = widgets.make_table(["装备", "场次", "出现率", "胜率", "相对基线"])
        item_lay.addWidget(self.item_table)
        body.addWidget(item_panel, 1)

        aug_panel, aug_lay = widgets.panel()
        aug_lay.addWidget(widgets.SectionTitle("海克斯强化"))
        self.aug_table = widgets.make_table(["强化", "场次", "出现率", "胜率", "相对基线"])
        aug_lay.addWidget(self.aug_table)
        body.addWidget(aug_panel, 1)

        root.addLayout(body, 1)

        self.tip = QLabel("")
        self.tip.setObjectName("CardHint")
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

    # ---- 数据 ------------------------------------------------------------
    def set_data(self, matches: list[Match], viewer: str | None = None) -> None:
        self._matches = matches
        self._viewer = viewer
        self._sync_champions()
        self._rebuild()

    def _sync_champions(self) -> None:
        counts: dict[str, int] = {}
        for m in self._matches:
            p = m.player_for(self._viewer)
            if p and p.champion:
                counts[p.champion] = counts.get(p.champion, 0) + 1
        items = [("", "全部英雄")] + [(n, f"{n}（{c}）") for n, c in
                                     sorted(counts.items(), key=lambda kv: -kv[1])[:60]]
        current = self.champ_box.currentData() or ""
        self.champ_box.blockSignals(True)
        self.champ_box.clear()
        for data, label in items:
            self.champ_box.addItem(label, data)
        idx = next((i for i, (d, _) in enumerate(items) if d == current), 0)
        self.champ_box.setCurrentIndex(idx)
        self.champ_box.blockSignals(False)

    def _rebuild(self) -> None:
        champion = self.champ_box.currentData() or None
        min_g = int(self.min_games.currentText())
        items, augs, games = gear_table(
            self._matches, viewer=self._viewer, champion=champion, min_games=min_g
        )
        s = summarize(self._matches, viewer=self._viewer)

        if not games or (not items and not augs):
            self.sub.setText("还没有装备/强化数据")
            self.tip.setText(
                "这个功能需要每局的装备与强化明细，早期入库的对局没存。"
                "去「导入数据」页点一次「补全装备与强化」，会把已有对局重新拉一遍（约 5 分钟）。"
            )
            self.item_table.setRowCount(0)
            self.aug_table.setRowCount(0)
            return

        self.sub.setText(
            f"{games} 场参与统计 · 基线胜率 {sum(1 for m in self._matches if m.win and m.player_for(self._viewer))/max(games,1)*100:.1f}%"
            f" · 装备 {len(items)} 件 · 强化 {len(augs)} 个"
        )
        self.tip.setText(
            f"「相对基线」= 这个装备/强化出现时的胜率，减去你自己的 {s.win_rate*100:.1f}%。"
            "小样本会很不稳（3 场赢 2 场就 +33 个点），把「最少场次」调高再看结论。"
        )
        self._fill(self.item_table, items)
        self._fill(self.aug_table, augs)

    def _fill(self, table, rows: list[GearRow]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for r in rows:
            i = table.rowCount()
            table.insertRow(i)
            cells = [
                r.name,
                str(r.games),
                f"{r.share*100:.0f}%",
                f"{r.win_rate*100:.1f}%",
                f"{r.delta:+.1f}",
            ]
            numeric = {1: r.games, 2: r.share, 3: r.win_rate, 4: r.delta}
            for c, text in enumerate(cells):
                item = (
                    widgets.NumItem.make(text, numeric[c])
                    if c in numeric
                    else QTableWidgetItem(text)
                )
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    color = theme.WIN if r.delta > 0 else (theme.LOSS if r.delta < 0 else theme.TEXT_DIM)
                    item.setForeground(QColor(color))
                table.setItem(i, c, item)
        table.setSortingEnabled(True)
        table.sortItems(3, Qt.SortOrder.DescendingOrder)
        table.resizeColumnsToContents()
