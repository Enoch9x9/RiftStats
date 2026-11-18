"""对局列表页：所有记录的原始表，可筛选、可删除、可导出 CSV。"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import Match, mode_display
from ..stats import (
    assist_share,
    feed_share,
    feed_vs_enemy,
    gold_given,
    match_contributions,
    match_scores,
    player_score,
)
from . import theme, widgets


class MatchesPage(QWidget):
    changed = Signal()  # 数据被删/导出等，需要外层刷新

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._matches: list[Match] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        head = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("对局记录")
        title.setObjectName("PageTitle")
        self.sub = QLabel("—")
        self.sub.setObjectName("PageSub")
        box.addWidget(title)
        box.addWidget(self.sub)
        head.addLayout(box)
        head.addStretch(1)

        self.filter = QComboBox()
        self.filter.addItems(["全部", "只看胜局", "只看败局"])
        self.filter.currentIndexChanged.connect(self._apply_filter)
        head.addWidget(self.filter)

        self.mate_combo = QComboBox()
        self.mate_combo.setMinimumWidth(150)
        self.mate_combo.currentIndexChanged.connect(self._apply_filter)
        self.mate_combo.setToolTip("只看和某位队友同队的对局，下面会显示这段样本的胜率和团队贡献率")
        head.addWidget(self.mate_combo)

        btn_export = QPushButton("导出 CSV")
        btn_export.clicked.connect(self._export)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._delete_selected)
        btn_clear = QPushButton("清空全部")
        btn_clear.clicked.connect(self._clear_all)
        head.addWidget(btn_export)
        head.addWidget(btn_del)
        head.addWidget(btn_clear)
        root.addLayout(head)

        # 队友筛选后的汇总条
        self.mate_summary = QLabel("")
        self.mate_summary.setObjectName("PageSub")
        self.mate_summary.setVisible(False)
        root.addWidget(self.mate_summary)

        self.table = widgets.make_table(
            ["时间", "伤害评分", "模式", "结果", "英雄", "KDA", "输出", "承伤", "队内占比", "队友"]
        )
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._show_selected)
        root.addWidget(self.table, 3)

        # 单场详情：10 人伤害评分 + 团队贡献率 + 助攻占比 + 送经济占比
        detail, detail_lay = widgets.panel(margins=14, spacing=8)
        head2 = QHBoxLayout()
        head2.addWidget(widgets.SectionTitle("单场详情"))
        self.detail_title = QLabel("点上面任意一局，看这局的 10 个人")
        self.detail_title.setObjectName("CardHint")
        head2.addWidget(self.detail_title)
        head2.addStretch(1)
        self.detail_score = QLabel("")
        self.detail_score.setStyleSheet(
            f"color: {theme.GOLD}; font-size: 20px; font-weight: 700;"
        )
        head2.addWidget(self.detail_score)
        head2.addStretch(1)
        detail_lay.addLayout(head2)
        self.detail = widgets.make_table(
            ["队伍", "玩家", "位次", "伤害评分", "团队贡献率", "KDA", "输出", "承伤",
             "助攻占比", "送经济占比", ""]
        )
        hdr = self.detail.horizontalHeader()
        hdr.setStretchLastSection(True)
        self._install_tooltips()
        self.detail.setRowCount(10)
        self.detail.setFixedHeight(345)
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self.detail, 1)

        score_card = QFrame()
        score_card.setObjectName("Card")
        score_card.setFixedWidth(230)
        sc_lay = QVBoxLayout(score_card)
        sc_lay.setContentsMargins(16, 14, 16, 14)
        sc_lay.setSpacing(6)
        sc_title = QLabel("本局伤害评分")
        sc_title.setObjectName("CardHint")
        sc_lay.addWidget(sc_title)
        self.score_big = QLabel("--")
        self.score_big.setStyleSheet(
            f"color: {theme.GOLD}; font-size: 64px; font-weight: 800;"
        )
        sc_lay.addWidget(self.score_big)
        self.score_grade = QLabel("点一局看这局的表现")
        self.score_grade.setObjectName("CardHint")
        self.score_grade.setWordWrap(True)
        sc_lay.addWidget(self.score_grade)
        sc_lay.addStretch(1)
        body.addWidget(score_card)

        detail_lay.addLayout(body)
        root.addWidget(detail, 2)

    def _install_tooltips(self) -> None:
        tips = {
            3: "单局伤害评分（0~100）：每分钟伤害 35% + 队内输出占比 30% + 伤害转化率 20% + 生存 15%，"
               "人头多但伤害低会额外扣分。",
            4: "团队贡献率 = 该玩家本局伤害评分 ÷ 本队 5 人伤害评分之和。\n"
               "队伍平均是 20%，超过 25% 说明这局主要靠他扛，低于 15% 基本就是在划水。",
            8: "助攻占比 = 该玩家助攻数 ÷ 本队总助攻数。\n"
               "越高说明参团越多，不参团的局这个数会很低。",
            9: "送经济占比 = 该玩家送出金币 ÷ 本队 5 人送出金币之和，五个人加起来正好 100%。\n"
               "每次死亡按 300 + min(300, 40×击杀数) 估算赏金——人头越多，死一次越亏。",
        }
        for col, text in tips.items():
            item = self.detail.horizontalHeaderItem(col)
            if item:
                item.setToolTip(text)
        self.detail.setToolTip(
            "把鼠标移到「伤害评分 / 团队贡献率 / 助攻占比 / 送经济占比」的表头上，能看到每项怎么算的。"
        )

    # ---- 数据 ------------------------------------------------------------
    def set_matches(self, matches: list[Match], viewer: str | None = None) -> None:
        self._matches = matches
        self._viewer = viewer
        self.sub.setText(f"{len(matches)} 条记录 · 数据库 {self.store.path}")
        self._sync_mates(matches)
        self._apply_filter()

    def _sync_mates(self, matches: list[Match]) -> None:
        """按出现次数重建队友下拉，保留当前选择。"""
        counts: dict[str, int] = {}
        for m in matches:
            for p in m.teammates:
                if p.name:
                    counts[p.name] = counts.get(p.name, 0) + 1
        wanted = [("", "全部队友")] + [
            (name, f"{name}（{n}）")
            for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:80]
        ]
        current = self.mate_combo.currentData() or ""
        existing = [
            (self.mate_combo.itemData(i) or "", self.mate_combo.itemText(i))
            for i in range(self.mate_combo.count())
        ]
        if existing == wanted:
            return
        self.mate_combo.blockSignals(True)
        self.mate_combo.clear()
        for data, label in wanted:
            self.mate_combo.addItem(label, data)
        idx = next((i for i, (d, _) in enumerate(wanted) if d == current), 0)
        self.mate_combo.setCurrentIndex(idx)
        self.mate_combo.blockSignals(False)

    def _apply_filter(self) -> None:
        mode = self.filter.currentIndex()
        mate = self.mate_combo.currentData() or ""
        rows = [
            m for m in self._matches
            if mode == 0 or (mode == 1 and m.win) or (mode == 2 and not m.win)
        ]
        if mate:
            rows = [m for m in rows if any(p.name == mate for p in m.teammates_of(getattr(self, '_viewer', None)))]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for m in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            me = m.player_for(getattr(self, '_viewer', None))
            team_dmg = sum(x.damage_dealt for x in m.team(me.side)) if me else 0
            score = player_score(me, team_dmg, m.duration_s) if me else 0.0
            cells = [
                m.created_at_str,
                f"{score:.0f}",
                mode_display(m.mode),
                "胜" if m.win else "负",
                me.champion if me else "—",
                f"{me.kills}/{me.deaths}/{me.assists}" if me else "—",
                widgets.fmt_int(me.damage_dealt) if me else "—",
                widgets.fmt_int(me.damage_taken) if me else "—",
                f"{m.share_for(me)*100:.0f}%",
                "、".join(p.name for p in m.teammates_of(getattr(self, '_viewer', None))),
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in range(1, 9):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 3:
                    item.setForeground(QColor(theme.WIN if m.win else theme.LOSS))
                if c == 1:
                    item.setForeground(
                        QColor(theme.WIN if score >= 60 else (theme.TEXT if score >= 40 else theme.LOSS))
                    )
                if c == 0:
                    item = widgets.NumItem.make(text, m.created_at)
                    item.setData(Qt.ItemDataRole.UserRole + 1, m.match_id)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)  # 最新的在最上面
        self.table.resizeColumnsToContents()
        self._update_mate_summary(rows, mate)
        if self.table.rowCount() and not self.table.selectedItems():
            self.table.selectRow(0)

    def _update_mate_summary(self, rows: list[Match], mate: str) -> None:
        if not mate:
            self.mate_summary.setVisible(False)
            return
        n = len(rows)
        if not n:
            self.mate_summary.setText(f"与「{mate}」没有符合当前条件的对局")
            self.mate_summary.setVisible(True)
            return
        wins = sum(1 for m in rows if m.win)
        my_contrib: list[float] = []
        mate_contrib: list[float] = []
        for m in rows:
            contrib = match_contributions(m)
            for i, p in enumerate(m.participants):
                if p.is_self:
                    my_contrib.append(contrib.get(i, 0.0))
                elif p.name == mate and p.side == m.self_side:
                    mate_contrib.append(contrib.get(i, 0.0))
        my_avg = sum(my_contrib) / len(my_contrib) * 100 if my_contrib else 0.0
        mate_avg = sum(mate_contrib) / len(mate_contrib) * 100 if mate_contrib else 0.0
        self.mate_summary.setText(
            f"与「{mate}」同队 {n} 场 · 胜率 {wins/n*100:.1f}%（{wins} 胜 {n-wins} 负）"
            f" · 我的团队贡献率 {my_avg:.1f}% · TA 的 {mate_avg:.1f}%"
            f"　（队伍平均 20%，只统计同队对局）"
        )
        self.mate_summary.setVisible(True)

    # ---- 单场详情 --------------------------------------------------------
    def _show_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        item = self.table.item(min(rows), 0)
        mid = None
        if item is not None:
            mid = item.data(Qt.ItemDataRole.UserRole + 1) or item.data(Qt.ItemDataRole.UserRole)
        match = next((m for m in self._matches if m.match_id == mid), None)
        if match is None and self._matches:
            match = self._matches[0]
        if match:
            self._render_detail(match)

    def _render_detail(self, match: Match) -> None:
        self.detail_title.setText(
            f"{match.created_at_str} · {mode_display(match.mode)} · "
            f"{'胜利' if match.win else '失败'} · 时长 {match.duration_s//60} 分钟"
        )
        scores = match_scores(match)
        contribs = match_contributions(match)
        viewer_name = getattr(self, "_viewer", None)
        target = match.player_for(viewer_name)
        if target is not None:
            team_dmg = sum(x.damage_dealt for x in match.team(target.side))
            sc = player_score(target, team_dmg, match.duration_s)
            share = match.share_for(target)
            color = theme.WIN if sc >= 60 else (theme.TEXT if sc >= 40 else theme.LOSS)
            self.score_big.setText(f"{sc:.0f}")
            self.score_big.setStyleSheet(
                f"color: {color}; font-size: 64px; font-weight: 800;"
            )
            self.score_grade.setText(
                f"{'胜利' if match.win else '失败'} · 队内占比 {share*100:.0f}% · "
                f"输出 {target.damage_dealt:,} · 承伤 {target.damage_taken:,}"
            )
            self.detail_score.setText("")
        self.detail.setRowCount(0)
        mine: dict[str, list[tuple[int, float]]] = {
            "score": [], "contrib": [], "dmg": [], "taken": [], "assist": [], "feed": []
        }
        tips = {
            3: "单局伤害评分（0~100）：每分钟伤害 35% + 队内输出占比 30% + 伤害转化率 20% + 生存 15%",
            4: "团队贡献率 = 该玩家伤害评分 ÷ 本队 5 人伤害评分之和，队伍平均是 20%",
            8: "助攻占比 = 该玩家助攻 ÷ 本队总助攻，反映参团程度",
            9: "送经济占比 = 该玩家死亡送出的金币 ÷ 敌方总经济，人头越多死一次越亏",
        }
        for i, p in enumerate(match.participants):
            side_team = match.team(p.side)
            enemy_team = (
                match.enemy_team if p.side == match.self_side
                else match.team(100 if match.self_side == 200 else 200)
            )
            is_mine = p.side == match.self_side
            score = scores.get(i, 0.0)
            contrib = contribs.get(i, 0.0) * 100
            assist = assist_share(p, side_team) * 100
            feed = feed_share(p, side_team) * 100
            feed_enemy = feed_vs_enemy(p, enemy_team) * 100
            r = self.detail.rowCount()
            self.detail.insertRow(r)
            cells = [
                "我方" if is_mine else "敌方",
                p.name + ("（视角）" if (p.is_self if not getattr(self, '_viewer', None) else p.name == getattr(self, '_viewer', None)) else ""),
                p.role if match.mode.upper() in ("CLASSIC", "URF") else f"{p.slot + 1}",
                f"{score:.0f}",
                f"{contrib:.0f}%",
                f"{p.kills}/{p.deaths}/{p.assists}",
                widgets.fmt_int(p.damage_dealt),
                widgets.fmt_int(p.damage_taken),
                f"{assist:.0f}%",
                f"{feed:.0f}%",
                "",
            ]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c in (0, 2, 3, 4, 5, 6, 7, 8, 9):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not is_mine and c == 0:
                    cell.setForeground(QColor(theme.LOSS))
                if p.is_self:
                    cell.setForeground(QColor(theme.GOLD))
                if c in tips:
                    cell.setToolTip(tips[c])
                if c == 9:
                    cell.setToolTip(
                        "送经济占比 = 他送出的金币 ÷ 本队 5 人送出金币之和（5 人相加 = 100%）。\n"
                        f"本局他约送出 {int(gold_given(p)):,} 金币，"
                        f"相当于敌方总经济的 {feed_enemy:.1f}%。"
                    )
                self.detail.setItem(r, c, cell)
            if is_mine:
                mine["score"].append((r, score))
                mine["contrib"].append((r, contrib))
                mine["dmg"].append((r, float(p.damage_dealt)))
                mine["taken"].append((r, float(p.damage_taken)))
                mine["assist"].append((r, assist))
                mine["feed"].append((r, feed))
        self.detail.resizeColumnsToContents()
        self._highlight_extremes(mine)

    # 表头列号 → (数据键, 越大越好还是越小越好)
    _EXTREME_COLS = [
        (3, "score", "high"),
        (4, "contrib", "high"),
        (6, "dmg", "high"),
        (7, "taken", "neutral"),
        (8, "assist", "high"),
        (9, "feed", "low"),
    ]

    def _highlight_extremes(self, mine: dict[str, list[tuple[int, float]]]) -> None:
        """把我方 5 人的每一项最高/最低标出来。

        越大越好的（伤害评分/输出/助攻占比）→ 最高绿、最低红；
        越小越好的（送经济占比）→ 最高红、最低绿；
        中性的（承伤）→ 只把最高标成橙色。
        """
        if len(mine.get("score") or []) < 2:
            return
        for col, key, direction in self._EXTREME_COLS:
            rows = mine.get(key) or []
            if len(rows) < 2:
                continue
            hi = max(rows, key=lambda x: x[1])
            lo = min(rows, key=lambda x: x[1])
            if hi[1] == lo[1]:
                continue
            if direction == "high":
                self._paint(hi[0], col, theme.WIN)
                self._paint(lo[0], col, theme.LOSS)
            elif direction == "low":
                self._paint(hi[0], col, theme.LOSS)
                self._paint(lo[0], col, theme.WIN)
            else:
                self._paint(hi[0], col, theme.WARN)

    def _paint(self, row: int, col: int, color: str) -> None:
        item = self.detail.item(row, col)
        if item is None:
            return
        item.setForeground(QColor(color))
        f = item.font()
        f.setBold(True)
        item.setFont(f)

    # ---- 操作 ------------------------------------------------------------
    def _delete_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            QMessageBox.information(self, "提示", "先选中要删的行")
            return
        ids = []
        for r in rows:
            item = self.table.item(r, 0)
            if item and (item.data(Qt.ItemDataRole.UserRole + 1) or item.data(Qt.ItemDataRole.UserRole)):
                ids.append(
                    item.data(Qt.ItemDataRole.UserRole + 1) or item.data(Qt.ItemDataRole.UserRole)
                )
        for mid in ids:
            self.store.delete(mid)
        self.changed.emit()

    def _clear_all(self) -> None:
        if QMessageBox.question(self, "确认", "清空所有对局记录？此操作不可撤销。") != QMessageBox.StandardButton.Yes:
            return
        self.store.clear()
        self.changed.emit()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "riftstats.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["时间", "模式", "来源", "结果", "英雄", "击杀", "死亡", "助攻",
                        "输出", "承伤", "队内占比", "队友"])
            for m in self._matches:
                me = m.me
                w.writerow([
                    m.created_at_str, m.mode, m.source, "胜" if m.win else "负",
                    me.champion if me else "",
                    me.kills if me else 0, me.deaths if me else 0, me.assists if me else 0,
                    me.damage_dealt if me else 0, me.damage_taken if me else 0,
                    f"{m.damage_share:.4f}",
                    "|".join(p.name for p in m.teammates),
                ])
        QMessageBox.information(self, "完成", f"已导出到\n{Path(path)}")
