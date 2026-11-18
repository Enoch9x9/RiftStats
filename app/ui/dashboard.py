"""总览页：一眼看懂"我最近打得怎么样"。"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QScrollArea,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import Match, mode_display
from ..stats import (
    recent_report,
    Summary,
    best_and_worst_champion,
    champion_table,
    recent_scores,
    summarize,
    win_streak,
)
from . import theme, widgets


class _MiniStat(QFrame):
    """小方块：一行说明 + 一个大数字，用来放"胜局/败局占比"这种对比指标。"""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {theme.PANEL_ALT}; border: 1px solid {theme.BORDER};"
            f"border-radius: 8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(0)
        self.setMinimumHeight(54)
        self._label = QLabel(label)
        self._label.setObjectName("CardHint")
        self._value = QLabel("--")
        self._value.setStyleSheet(f"font-size: 19px; font-weight: 700; color: {theme.TEXT};")
        lay.addWidget(self._label)
        lay.addWidget(self._value)

    def set_value(self, text: str, color: str = theme.TEXT) -> None:
        self._value.setText(text)
        self._value.setStyleSheet(f"font-size: 19px; font-weight: 700; color: {color};")


class _ClickCatcher(QObject):
    """把面板上的点击转成信号（标签会把鼠标事件吃掉，所以装过滤器）。"""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            self._callback()
        return False


class DashboardPage(QWidget):
    open_matches = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet(f"background: {theme.BG};")
        self._scroll = scroll

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(2)
        title = QLabel("总览")
        title.setObjectName("PageTitle")
        self.sub = QLabel("—")
        self.sub.setObjectName("PageSub")
        head.addWidget(title)
        head.addWidget(self.sub)
        root.addLayout(head)

        # 近期评价（最近 20 场）
        eval_panel, eval_lay = widgets.panel()
        eval_row = QHBoxLayout()
        eval_row.setSpacing(16)
        self.report_grade = QLabel("--")
        self.report_grade.setObjectName("BigGrade")
        self.report_grade.setFixedWidth(96)
        self.report_grade.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eval_row.addWidget(self.report_grade)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.report_title = QLabel("近期评价")
        self.report_title.setObjectName("SectionTitle")
        self.report_comment = QLabel("还没有足够数据")
        self.report_comment.setObjectName("PageSub")
        self.report_comment.setWordWrap(True)
        mid.addWidget(self.report_title)
        mid.addWidget(self.report_comment)
        eval_row.addLayout(mid, 1)

        self.report_stats = QLabel("")
        self.report_stats.setObjectName("CardHint")
        self.report_stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.report_stats.setMinimumWidth(260)
        eval_row.addWidget(self.report_stats)

        eval_lay.addLayout(eval_row)
        for child in eval_panel.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._report_click = _ClickCatcher(self.open_matches.emit, self)
        eval_panel.installEventFilter(self._report_click)
        eval_panel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.report_box = eval_panel
        root.addWidget(eval_panel)

        # KPI 网格（4 列 × 2 行）
        grid = QGridLayout()
        grid.setSpacing(12)
        self.card_rate = widgets.Card("胜率", "--", "还没有数据")
        self.card_dmg = widgets.Card("场均输出", "--", "对英雄伤害 / 场")
        self.card_win_total = widgets.Card("胜局输出总量", "--", "所有获胜局累计")
        self.card_win_avg = widgets.Card("胜局场均输出", "--", "赢的局打了多少")
        self.card_loss_avg = widgets.Card("败局场均输出", "--", "输的局打了多少")
        self.card_taken = widgets.Card("败局场均承伤", "--", "输的局挨了多少打")
        self.card_best_champ = widgets.Card("胜率最高英雄", "--", "同英雄至少 10 场")
        self.card_worst_champ = widgets.Card("胜率最低英雄", "--", "同英雄至少 10 场")
        cards = [
            self.card_rate, self.card_dmg, self.card_win_total, self.card_win_avg,
            self.card_loss_avg, self.card_taken, self.card_best_champ, self.card_worst_champ,
        ]
        for i, card in enumerate(cards):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            grid.addWidget(card, i // 4, i % 4)
        root.addLayout(grid)

        # 三块图表：胜负构成 / 输出承伤对比 / 英雄 TOP5
        charts = QHBoxLayout()
        charts.setSpacing(12)

        left, left_lay = widgets.panel()
        left_lay.addWidget(widgets.SectionTitle("胜负构成"))
        self.donut_slot = QVBoxLayout()
        left_lay.addLayout(self.donut_slot)
        share_row = QHBoxLayout()
        share_row.setSpacing(10)
        self.share_win = _MiniStat("胜局输出占比")
        self.share_loss = _MiniStat("败局输出占比")
        share_row.addWidget(self.share_win)
        share_row.addWidget(self.share_loss)
        left_lay.addLayout(share_row)
        left.setFixedWidth(320)

        middle, middle_lay = widgets.panel()
        middle_lay.addWidget(widgets.SectionTitle("胜局 vs 败局：输出 / 承伤"))
        self.bar_slot = QVBoxLayout()
        middle_lay.addLayout(self.bar_slot)
        self.dmg_note = QLabel("")
        self.dmg_note.setObjectName("CardHint")
        self.dmg_note.setWordWrap(True)
        middle_lay.addWidget(self.dmg_note)

        right, right_lay = widgets.panel()
        right_lay.addWidget(widgets.SectionTitle("英雄 TOP 5 · 按出场场次"))
        right_lay.setSpacing(8)
        self.champ_chart = widgets.HBarList()
        self.champ_hint = QLabel("条形长度 = 该英雄的胜率，虚线是你自己的总胜率；排序按场次，不是按胜率")
        self.champ_hint.setObjectName("CardHint")
        self.champ_hint.setWordWrap(True)
        right_lay.addWidget(self.champ_hint)
        self.champ_chart.setMinimumHeight(170)
        right_lay.addWidget(self.champ_chart, 0, Qt.AlignmentFlag.AlignTop)
        right_lay.addStretch(1)
        right.setFixedWidth(330)

        charts.addWidget(left)
        charts.addWidget(middle, 1)
        charts.addWidget(right)
        root.addLayout(charts, 4)

        # 最近对局
        recent, recent_lay = widgets.panel()
        top = QHBoxLayout()
        top.addWidget(widgets.SectionTitle("最近对局"))
        top.addStretch(1)
        self.streak_lbl = QLabel("")
        self.streak_lbl.setObjectName("CardHint")
        top.addWidget(self.streak_lbl)
        recent_lay.addLayout(top)

        self.table = widgets.make_table(
            ["时间", "模式", "结果", "英雄", "KDA", "输出", "承伤", "队内输出占比", "队友"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setFixedHeight(150)
        recent_lay.addWidget(self.table)
        root.addWidget(recent, 2)

        self._summary = Summary()

    # ---- 刷新 ------------------------------------------------------------
    def refresh(self, matches: list[Match], viewer: str | None = None) -> None:
        s = summarize(matches, viewer=viewer)
        self._summary = s

        rep = recent_report(matches, viewer=viewer, window=20)
        if rep is None:
            self.report_grade.setText("--")
            self.report_comment.setText("还没有足够数据，先拉点对局")
            self.report_stats.setText("")
        else:
            self.report_grade.setText(rep.grade)
            color = {"S": theme.GOLD, "A": theme.WIN, "B": theme.ACCENT,
                     "C": "#E8A33D", "D": theme.LOSS}.get(rep.grade, theme.TEXT)
            self.report_grade.setStyleSheet(f"color: {color};")
            self.report_title.setText(
                f"近期评价 · 最近 {rep.games} 场 · {rep.score:.0f} 分 · 胜率 {rep.win_rate*100:.0f}%"
            )
            note = f"（{rep.mode_note}）" if rep.mode_note else ""
            self.report_comment.setText(rep.comment + note)
            self.report_stats.setText(
                f"每分钟伤害 {rep.dpm:,.0f}（平时 {rep.dpm_base:,.0f}）\n"
                f"队内占比 {rep.share*100:.1f}%（平时 {rep.share_base*100:.1f}%）\n"
                f"KDA {rep.kda:.2f}（平时 {rep.kda_base:.2f}）"
            )

        if not matches:
            self.sub.setText("还没有对局数据 —— 去「导入数据」拉客户端记录，或先载入演示数据")
        else:
            span = matches[0].created_at_str[:10] + " ~ " + matches[-1].created_at_str[:10]
            scored = recent_scores(matches, len(matches), viewer=viewer)
            avg_score = sum(v for _, v in scored) / len(scored) if scored else 0.0
            self.sub.setText(
                f"{s.games} 场 · {s.wins} 胜 {s.losses} 负 · 数据区间 {span}"
                f" · 场均 {s.avg_duration_min:.1f} 分钟 · 平均伤害评分 {avg_score:.0f}"
            )

        rate_txt = f"{s.win_rate*100:.1f}%" if s.games else "--"
        lo, hi = s.win_rate_ci
        self.card_rate.set_value(
            rate_txt,
            f"95% CI {lo*100:.1f}% ~ {hi*100:.1f}% · {s.wins} 胜 {s.losses} 负",
            color=theme.WIN if s.win_rate >= 0.5 else theme.LOSS,
        )
        self.card_dmg.set_value(
            widgets.fmt_int(s.dmg_avg) if s.games else "--",
            f"折合 {s.dmg_per_min:.0f}/分钟 · 队内占比 {s.share_avg*100:.1f}%",
        )
        self.card_win_total.set_value(
            widgets.fmt_int(s.dmg_win_total) if s.games else "--",
            f"{s.wins} 场获胜局累计",
        )
        self.card_win_avg.set_value(
            widgets.fmt_int(s.dmg_win_avg) if s.wins else "--",
            f"KDA {s.kda:.2f}",
            color=theme.WIN,
        )
        self.card_loss_avg.set_value(
            widgets.fmt_int(s.dmg_loss_avg) if s.losses else "--",
            f"{s.losses} 场失败局平均",
            color=theme.LOSS,
        )
        self.card_taken.set_value(
            widgets.fmt_int(s.taken_loss_avg) if s.losses else "--",
            f"胜局承伤 {widgets.fmt_int(s.taken_win_avg)}",
            color=theme.LOSS,
        )

        best, worst = best_and_worst_champion(matches, viewer=viewer)
        if best:
            self.card_best_champ.set_value(
                best.name,
                f"胜率 {best.win_rate*100:.1f}% · {best.games} 场 · 场均 {widgets.fmt_int(best.dmg_avg)}",
                color=theme.WIN,
            )
        else:
            self.card_best_champ.set_value("--", "还没有足够的英雄数据", color=theme.TEXT_DIM)
        if worst:
            self.card_worst_champ.set_value(
                worst.name,
                f"胜率 {worst.win_rate*100:.1f}% · {worst.games} 场 · 场均 {widgets.fmt_int(worst.dmg_avg)}",
                color=theme.LOSS,
            )
        else:
            self.card_worst_champ.set_value("--", "还没有足够的英雄数据", color=theme.TEXT_DIM)

        # 环形图 + 占比
        _clear(self.donut_slot)
        if s.games:
            donut = widgets.donut_chart(s.wins, s.losses)
            donut.setFixedHeight(150)
            self.donut_slot.addWidget(donut)
        self.share_win.set_value(f"{s.share_win_avg*100:.1f}%", theme.WIN)
        self.share_loss.set_value(f"{s.share_loss_avg*100:.1f}%", theme.LOSS)

        # 输出 / 承伤对比
        _clear(self.bar_slot)
        if s.games:
            self.bar_slot.addWidget(
                widgets.bar_chart(
                    ["胜局", "败局"],
                    {
                        "场均输出": [s.dmg_win_avg, s.dmg_loss_avg],
                        "场均承伤": [s.taken_win_avg, s.taken_loss_avg],
                    },
                    [theme.ACCENT, theme.WARN],
                    horizontal=False,
                    bar_width=0.26,
                )
            )

        # 胜局 vs 败局的差距，用人话解释一下
        try:
            if s.dmg_loss_avg > 0:
                diff = (s.dmg_win_avg - s.dmg_loss_avg) / s.dmg_loss_avg * 100
                if diff >= 15:
                    msg = (
                        f"赢的局你场均多打 {diff:.0f}%——**输赢取决于你有没有真的打出输出**，"
                        "不打满就容易输，你是这队的主要火力。"
                    )
                elif diff <= -15:
                    msg = (
                        f"输的局反而多打 {abs(diff):.0f}%——你输出够了但队伍跟不上，"
                        "再多打也换不来胜利，这时候该看的是队友而不是自己。"
                    )
                else:
                    msg = (
                        f"输赢的输出只差 {diff:+.0f}%——赢的时候你没多打，输的时候也没少打，"
                        "说明胜负基本不由你的输出决定，你是跟着队伍走的那个人。"
                    )
            else:
                msg = "还没有足够数据判断输出与胜负的关系。"
        except Exception:
            msg = ""
        self.dmg_note.setText(msg.replace("**", ""))

        # 英雄 TOP 5
        top_champs = champion_table(matches, viewer=viewer)[:5]
        self.champ_chart.set_items(
            [(r.name, r.win_rate * 100, f"{r.win_rate*100:.0f}%") for r in top_champs],
            color=theme.GOLD,
            marker=50.0,
            max_value=100.0,
            name_width=82,
        )

        # 最近对局
        self.table.setRowCount(0)
        for m in matches[:12]:
            r = self.table.rowCount()
            self.table.insertRow(r)
            me = m.player_for(viewer)
            win_txt = "胜利" if m.win else "失败"
            cells = [
                m.created_at_str[5:],
                mode_display(m.mode),
                win_txt,
                me.champion if me else "—",
                f"{me.kills}/{me.deaths}/{me.assists}" if me else "—",
                widgets.fmt_int(me.damage_dealt) if me else "—",
                widgets.fmt_int(me.damage_taken) if me else "—",
                f"{m.share_for(me)*100:.1f}%",
                "、".join(p.name for p in m.teammates_of(viewer)),
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c not in (0, 8):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 2:
                    item.setForeground(QColor(theme.WIN if m.win else theme.LOSS))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

        streak = win_streak(matches)
        if streak > 0:
            self.streak_lbl.setText(f"当前 {streak} 连胜")
        elif streak < 0:
            self.streak_lbl.setText(f"当前 {abs(streak)} 连败")
        else:
            self.streak_lbl.setText("")


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
