"""英雄推荐页：把"该练谁"变成一个有依据的结论。"""

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
from ..stats import ChampAdvice, champion_advice, feature_weights, summarize
from . import theme, widgets

GRADE_COLOR = {"S": theme.GOLD, "A": theme.WIN, "B": theme.ACCENT, "C": theme.LOSS,
               "样本不足": theme.TEXT_DIM}


class RecommendPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._matches: list[Match] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        head = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("英雄推荐")
        title.setObjectName("PageTitle")
        self.sub = QLabel("—")
        self.sub.setObjectName("PageSub")
        box.addWidget(title)
        box.addWidget(self.sub)
        head.addLayout(box)
        head.addStretch(1)
        head.addWidget(QLabel("最少场次"))
        self.min_games = QComboBox()
        self.min_games.addItems(["3", "5", "8", "10", "15"])
        self.min_games.setCurrentIndex(2)
        self.min_games.currentIndexChanged.connect(self._rebuild)
        head.addWidget(self.min_games)
        root.addLayout(head)

        # 三张推荐卡
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.cards: list[widgets.Card] = []
        for label in ("① 最推荐", "② 次选", "③ 备选"):
            card = widgets.Card(label, "--", "还没有足够数据")
            card.setSizePolicy(card.sizePolicy())
            self.cards.append(card)
            cards.addWidget(card)
        root.addLayout(cards)

        body = QHBoxLayout()
        body.setSpacing(12)

        chart_panel, chart_lay = widgets.panel()
        chart_lay.addWidget(widgets.SectionTitle("综合评分 TOP 10"))
        self.chart = widgets.HBarList()
        self.chart.setFixedHeight(340)
        chart_lay.addWidget(self.chart, 0, Qt.AlignmentFlag.AlignTop)
        chart_lay.addStretch(1)
        chart_panel.setFixedWidth(380)
        body.addWidget(chart_panel)

        table_panel, table_lay = widgets.panel()
        table_lay.addWidget(widgets.SectionTitle("明细（按评分排序，可点表头重排）"))
        self.table = widgets.make_table(
            ["英雄", "评级", "评分", "场次", "选取率", "胜率",
             "场均输出", "胜局输出", "败局输出", "场均承伤"]
        )
        self.table.horizontalHeaderItem(5).setToolTip("95% 置信区间见下方说明；这一列只放点估计")
        self.table.horizontalHeaderItem(8).setToolTip("只有获胜局才会统计，没赢过就是 0")
        self.table.setSortingEnabled(True)
        hdr = self.table.horizontalHeader()
        from PySide6.QtWidgets import QHeaderView

        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_lay.addWidget(self.table)
        body.addWidget(table_panel, 1)
        root.addLayout(body, 1)

        self.tip = QLabel("")
        self.tip.setObjectName("CardHint")
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

    # ---- 刷新 ------------------------------------------------------------
    def set_data(self, matches: list[Match], viewer: str | None = None) -> None:
        self._matches = matches
        self._viewer = viewer
        self._rebuild()

    def _rebuild(self) -> None:
        min_g = int(self.min_games.currentText())
        viewer = getattr(self, '_viewer', None)
        weights = feature_weights(self._matches, viewer=viewer)
        rows = champion_advice(self._matches, min_games=min_g, weights=weights, viewer=viewer)
        self.tip.setText(
            "评分 = 五项在你所有英雄里的百分位加权，权重按你自己的数据算："
            f"胜率 {weights['win_rate']*100:.0f}%（用 95% 置信下界）、"
            f"KDA {weights['kda']*100:.0f}%、"
            f"场均输出 {weights['dmg']*100:.0f}%、"
            f"场均承伤 {weights['taken']*100:.0f}%、"
            f"选取率 {weights['pick']*100:.0f}%。"
            "「样本不足」的行不参与推荐。"
        )
        picked = [r for r in rows if r.grade != "样本不足"]
        s = summarize(self._matches, viewer=getattr(self, '_viewer', None))

        self.sub.setText(
            f"{s.games} 场 · 玩过 {len(rows)} 个英雄 · 达标（≥{min_g} 场）{len(picked)} 个"
            f"（评级 S {sum(1 for r in picked if r.grade=='S')} 个）"
            f" · 另有 {len(rows) - len(picked)} 个因场次不足未列出"
        )

        for card, row in zip(self.cards, picked[:3]):
            self._fill_card(card, row)
        for card in self.cards[len(picked[:3]):]:
            card.set_value("--", "样本还不够，多打几局再看", color=theme.TEXT_DIM)

        self.chart.set_items(
            [(r.name, r.score, f"{r.score:.0f}") for r in picked[:10]],
            color=theme.GOLD,
            marker=None,
            max_value=100.0,
            name_width=92,
        )

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for r in picked:
            i = self.table.rowCount()
            self.table.insertRow(i)
            cells = [
                r.name, r.grade, f"{r.score:.1f}", str(r.games),
                f"{r.pick_rate*100:.1f}%", f"{r.win_rate*100:.1f}%",
                widgets.fmt_int(r.dmg_avg), widgets.fmt_int(r.dmg_win_avg),
                widgets.fmt_int(r.dmg_loss_avg), widgets.fmt_int(r.taken_avg),
            ]
            numeric = {2: r.score, 3: r.games, 4: r.pick_rate, 5: r.win_rate,
                       6: r.dmg_avg, 7: r.dmg_win_avg, 8: r.dmg_loss_avg,
                       9: r.taken_avg}
            for c, text in enumerate(cells):
                item = (
                    widgets.NumItem.make(text, numeric[c]) if c in numeric
                    else QTableWidgetItem(text)
                )
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 1:
                    item.setForeground(QColor(GRADE_COLOR.get(r.grade, theme.TEXT)))
                if c == 5:
                    item.setToolTip(f"95% 置信区间 {r.ci_text}")
                if c in (6, 7, 8, 9):
                    item.setToolTip(item.text())
                self.table.setItem(i, c, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(2, Qt.SortOrder.DescendingOrder)

    def _fill_card(self, card: widgets.Card, r: ChampAdvice) -> None:
        card.set_value(
            r.name,
            f"评分 {r.score:.1f} · {r.grade} 级 · {r.games} 场 · 胜率 {r.win_rate*100:.1f}%",
            color=GRADE_COLOR.get(r.grade, theme.TEXT),
        )
