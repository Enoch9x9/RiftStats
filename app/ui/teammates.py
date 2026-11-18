"""队友分析页：谁跟你一起就赢，谁跟你一起就输。

这一页就是上次那张"内鬼检测"表的正式版，但加了置信区间和最小样本过滤，
避免 6 局 1 胜就被判成内鬼。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import Match
from ..stats import TeammateRow, summarize, teammate_table
from . import theme, widgets


class TeammatesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._matches: list[Match] = []
        self._friends: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        head = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("队友分析")
        title.setObjectName("PageTitle")
        self.sub = QLabel("—")
        self.sub.setObjectName("PageSub")
        box.addWidget(title)
        box.addWidget(self.sub)
        head.addLayout(box)
        head.addStretch(1)
        head.addWidget(QLabel("最少同队场次"))
        self.min_games = QComboBox()
        self.min_games.addItems(["1", "3", "5", "10", "20"])
        self.min_games.currentIndexChanged.connect(self._rebuild)
        head.addWidget(self.min_games)
        root.addLayout(head)

        chart_panel, chart_lay = widgets.panel()
        head2 = QHBoxLayout()
        head2.addWidget(widgets.SectionTitle("同队胜率"))
        head2.addStretch(1)
        self.marker_hint = QLabel("")
        self.marker_hint.setObjectName("CardHint")
        head2.addWidget(self.marker_hint)
        chart_lay.addLayout(head2)
        self.chart_slot = QVBoxLayout()
        chart_lay.addLayout(self.chart_slot)
        root.addWidget(chart_panel, 0)

        self.verdict = QLabel("")
        self.verdict.setObjectName("CardHint")
        self.verdict.setWordWrap(True)
        root.addWidget(self.verdict)

        table_panel, table_lay = widgets.panel()
        table_lay.addWidget(widgets.SectionTitle("明细"))
        self.table = widgets.make_table(
            ["队友", "类型", "同队", "胜", "胜率", "95% CI", "相对自己",
             "场均输出", "场均承伤", "队内占比", "综合评分"]
        )
        self.table.setSortingEnabled(True)
        table_lay.addWidget(self.table)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(table_panel, 1)

        suspect_card = QFrame()
        suspect_card.setObjectName("Card")
        suspect_card.setFixedWidth(250)
        sc = QVBoxLayout(suspect_card)
        sc.setContentsMargins(16, 14, 16, 14)
        sc.setSpacing(6)
        cap = QLabel("最像内鬼的人")
        cap.setObjectName("CardHint")
        sc.addWidget(cap)
        self.suspect_name = QLabel("--")
        self.suspect_name.setWordWrap(True)
        self.suspect_name.setStyleSheet(
            "color: " + theme.LOSS + "; font-size: 26px; font-weight: 800;"
        )
        sc.addWidget(self.suspect_name)
        self.suspect_score = QLabel("")
        self.suspect_score.setStyleSheet(
            "color: " + theme.TEXT + "; font-size: 44px; font-weight: 800;"
        )
        sc.addWidget(self.suspect_score)
        self.suspect_detail = QLabel("")
        self.suspect_detail.setObjectName("CardHint")
        self.suspect_detail.setWordWrap(True)
        sc.addWidget(self.suspect_detail)
        sc.addStretch(1)
        row.addWidget(suspect_card)

        root.addLayout(row, 1)

    # ---- 刷新 ------------------------------------------------------------
    def set_data(self, matches: list[Match], friends: set[str] | None = None,
                 viewer: str | None = None) -> None:
        self._matches = matches
        self._friends = friends or set()
        self._viewer = viewer
        self._rebuild()

    def _rebuild(self) -> None:
        matches = self._matches
        base = summarize(matches, viewer=getattr(self, '_viewer', None)).win_rate
        min_g = int(self.min_games.currentText())
        rows = teammate_table(matches, min_games=1, friend_names=self._friends,
                              viewer=getattr(self, '_viewer', None))
        shown = [r for r in rows if r.games >= min_g]

        self.sub.setText(
            f"你自己胜率 {base*100:.1f}% 为基准 · 共 {len(rows)} 位队友"
            f" · 当前显示 {len(shown)} 位（≥{min_g} 场）"
        )
        self.marker_hint.setText(f"虚线 = 你自己 {base*100:.1f}%｜按同队场次排序，最多 8 人")


        # 图表
        while self.chart_slot.count():
            item = self.chart_slot.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)   # 不解除父子关系的话，旧图会留在原地继续画，叠在一起
                w.deleteLater()
        top = sorted(shown, key=lambda r: -r.games)[:8]
        if top:
            chart = widgets.HBarList()
            chart.set_items(
                [(r.name, r.win_rate * 100, f"{r.win_rate*100:.1f}%") for r in top],
                marker=base * 100,
                max_value=100.0,
                name_width=130,
            )
            self.chart_slot.addWidget(chart)
        else:
            empty = QLabel("没有满足条件的队友")
            empty.setObjectName("CardHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.chart_slot.addWidget(empty)

        # 综合评分：胜率 40% + 场均输出 35% + 队内占比 25%，都取在"这伙队友里"的百分位
        def pct(vals: list[float], v: float) -> float:
            n = len(vals)
            if n <= 1:
                return 0.5
            rank = sum(1 for x in vals if x <= v)
            return (rank - 0.5) / n

        pool = [r for r in shown if r.games >= 5] or shown
        wr_pool = [r.win_rate for r in pool]
        dmg_pool = [r.dmg_avg for r in pool]
        share_pool = [r.share_avg for r in pool]
        score_of: dict[str, float] = {}
        for r in shown:
            score_of[r.name] = 100.0 * (
                0.40 * pct(wr_pool, r.win_rate)
                + 0.35 * pct(dmg_pool, r.dmg_avg)
                + 0.25 * pct(share_pool, r.share_avg)
            )

        # 最像内鬼：样本 ≥10 场里综合分最低的那个
        eligible = [r for r in shown if r.games >= 10] or shown
        suspect = min(eligible, key=lambda r: score_of.get(r.name, 0)) if eligible else None
        if suspect is not None and suspect.games >= 10:
            verdict = (
                f"综合评分最低的是「{suspect.name}」：{suspect.games} 场，胜率 "
                f"{suspect.win_rate*100:.1f}%（你 {base*100:.1f}%，相对 {suspect.delta:+.1f}）"
                f"，队内占比 {suspect.share_avg*100:.1f}%。"
                f"样本 {suspect.games} 场，95% 区间 {suspect.ci_text}——区间越窄结论越硬。"
            )
        else:
            verdict = "样本还太少，先多打几场再看谁是内鬼。"
        self.verdict.setText(verdict)
        if suspect is not None and suspect.games >= 10:
            self.suspect_name.setText(suspect.name)
            self.suspect_score.setText("%.0f 分" % score_of.get(suspect.name, 0))
            self.suspect_detail.setText(
                "%d 场 · 胜率 %.1f%%\n相对你 %+.1f 个百分点\n队内占比 %.1f%%"
                % (suspect.games, suspect.win_rate * 100, suspect.delta,
                   suspect.share_avg * 100)
            )
        else:
            self.suspect_name.setText("--")
            self.suspect_score.setText("")
            self.suspect_detail.setText("样本太少")

        # 表格
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for r in sorted(shown, key=lambda r: -r.games):
            i = self.table.rowCount()
            self.table.insertRow(i)
            cells = [
                r.name,
                "常一起玩" if r.games >= 3 else "偶遇",
                str(r.games),
                str(r.wins),
                f"{r.win_rate*100:.1f}%",
                r.ci_text,
                f"{r.delta:+.1f}",
                widgets.fmt_int(r.dmg_avg),
                widgets.fmt_int(r.taken_avg),
                f"{r.share_avg*100:.1f}%",
                f"{score_of.get(r.name, 0):.0f}",
            ]
            numeric = {2: r.games, 3: r.wins, 4: r.win_rate, 6: r.delta,
                       7: r.dmg_avg, 8: r.taken_avg, 9: r.share_avg,
                       10: score_of.get(r.name, 0)}
            for c, text in enumerate(cells):
                item = (
                    widgets.NumItem.make(text, numeric[c])
                    if c in numeric
                    else QTableWidgetItem(text)
                )
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 6:
                    item.setForeground(QColor(theme.WIN if r.delta >= 0 else theme.LOSS))
                if c == 1 and r.games >= 3:
                    item.setForeground(QColor(theme.TEXT_DIM))
                if c == 10 and suspect is not None and r.name == suspect.name:
                    item.setForeground(QColor(theme.LOSS))
                    item.setToolTip(
                        f"综合评分最低（{r.games} 场，胜率 {r.win_rate*100:.1f}%）。"
                        "评分 = 胜率 40% + 场均输出 35% + 队内占比 25%"
                    )
                self.table.setItem(i, c, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(2, Qt.SortOrder.DescendingOrder)
        self.table.resizeColumnsToContents()
