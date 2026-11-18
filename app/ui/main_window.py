"""主窗口：左侧导航 + 右侧页面栈。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..models import Match, mode_display
from ..sources import demo
from ..stats import summarize
from . import theme, widgets
from .dashboard import DashboardPage
from .importer import ImportPage
from .recent_dialog import RecentDialog
from .matches import MatchesPage
from .recommend import RecommendPage
from .teammates import TeammatesPage

NAV = [
    ("总览", "总览"),
    ("对局记录", "对局"),
    ("队友分析", "队友"),
    ("英雄推荐", "推荐"),
    ("导入数据", "导入"),
]


class MainWindow(QMainWindow):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.setWindowTitle("RiftStats · 峡谷数据台")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 侧边栏
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(196)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 22, 0, 16)
        side_lay.setSpacing(4)

        brand_box = QVBoxLayout()
        brand_box.setContentsMargins(20, 0, 12, 14)
        brand_box.setSpacing(2)
        brand = QLabel("RIFTSTATS")
        brand.setObjectName("Brand")
        brand_sub = QLabel("峡谷数据台 · v0.1")
        brand_sub.setObjectName("BrandSub")
        brand_box.addWidget(brand)
        brand_box.addWidget(brand_sub)
        side_lay.addLayout(brand_box)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER}; margin: 0 16px;")
        side_lay.addWidget(sep)

        self.stack = QStackedWidget()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        self.pages: list[QWidget] = []
        for index, (label, _short) in enumerate(NAV):
            btn = QPushButton(label)
            btn.setObjectName("Nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(btn, index)
            side_lay.addWidget(btn)
            self.pages.append(btn)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self._goto)

        side_lay.addStretch(1)

        # 主角：整站数据按谁来看
        who = QVBoxLayout()
        who.setContentsMargins(20, 0, 14, 8)
        who.setSpacing(4)
        who_lbl = QLabel("主角")
        who_lbl.setObjectName("BrandSub")
        who.addWidget(who_lbl)
        self.viewer_combo = QComboBox()
        self.viewer_combo.addItem("我", "")
        self.viewer_combo.setToolTip("换一个玩家，整个软件按他的视角重新算：胜率、输出、评分、推荐都会变")
        self.viewer_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        who.addWidget(self.viewer_combo)
        side_lay.addLayout(who)

        # 统计范围：最近 N 场（100 起步，最多到库里的总场次）
        scope = QVBoxLayout()
        scope.setContentsMargins(20, 0, 14, 8)
        scope.setSpacing(4)
        scope_lbl = QLabel("模式")
        scope_lbl.setObjectName("BrandSub")
        scope.addWidget(scope_lbl)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("全部模式", "")
        self.mode_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        scope.addWidget(self.mode_combo)

        scope.addSpacing(6)
        scope_lbl2 = QLabel("统计范围")
        scope_lbl2.setObjectName("BrandSub")
        scope.addWidget(scope_lbl2)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.range_spin = QSpinBox()
        self.range_spin.setRange(100, 100)
        self.range_spin.setSingleStep(100)
        self.range_spin.setSuffix(" 场")
        self.range_spin.setFixedWidth(96)
        self.range_spin.valueChanged.connect(lambda _v: self.refresh())
        self.chk_all = QCheckBox("全部")
        self.chk_all.setStyleSheet("font-size: 10px; color: #8D9AA7;")
        self.chk_all.toggled.connect(self._on_scope_toggled)
        row.addWidget(self.range_spin)
        row.addWidget(self.chk_all)
        scope.addLayout(row)
        side_lay.addLayout(scope)

        self.side_status = QLabel("")
        self.side_status.setObjectName("BrandSub")
        self.side_status.setWordWrap(True)
        self.side_status.setContentsMargins(20, 0, 12, 0)
        side_lay.addWidget(self.side_status)

        self.side_hint = QLabel("")
        self.side_hint.setObjectName("BrandSub")
        self.side_hint.setWordWrap(True)
        self.side_hint.setContentsMargins(20, 6, 12, 0)
        side_lay.addWidget(self.side_hint)

        lay.addWidget(side)

        # ---- 页面
        self.dashboard = DashboardPage()
        self.matches_page = MatchesPage(store)
        self.teammates_page = TeammatesPage()
        self.recommend_page = RecommendPage()
        self.import_page = ImportPage(store)
        for page in (self.dashboard, self.matches_page, self.teammates_page,
                     self.recommend_page, self.import_page):
            self.stack.addWidget(page)
        lay.addWidget(self.stack, 1)

        self.matches_page.changed.connect(self.refresh)
        self.import_page.data_changed.connect(self.refresh)
        self.import_page.synced.connect(self._show_recent_dialog)
        self.dashboard.open_matches.connect(lambda: self._goto(1))

        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_msg = QLabel("就绪")
        bar.addWidget(self.status_msg)

        self._seed_if_empty()
        self.chk_all.setChecked(False)
        total = max(100, self.store.count())
        self.range_spin.setMaximum(total)
        self.range_spin.setValue(min(300, total))
        self.refresh()

    # ---- 导航 ------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_chrome_done", False):
            self._chrome_done = True
            try:
                from .window_chrome import apply_dark_titlebar

                apply_dark_titlebar(int(self.winId()), caption=theme.BG, text=theme.TEXT)
            except Exception:
                pass

    def _show_recent_dialog(self) -> None:
        """同步完最近 20 场：弹一张评价卡，关掉就回总览。"""
        from ..stats import recent_report

        viewer = self.viewer_combo.currentData() or None
        matches = self.store.all()
        if viewer:
            matches = [m for m in matches if m.has_player(viewer)]
        rep = recent_report(matches, viewer=viewer, window=20)
        if rep is None:
            return
        dlg = RecentDialog(rep, self)
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()
        dlg.exec()
        self._goto(0)

    def _goto(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    # ---- 数据 ------------------------------------------------------------
    def _seed_if_empty(self) -> None:
        """第一次打开什么数据都没有，先放 48 场演示局，免得界面是空的。"""
        if self.store.count() == 0:
            for m in demo.generate(48):
                self.store.upsert(m)
            self._seeded_demo = True

    def _sync_viewers(self, matches: list[Match]) -> None:
        """把对局里出现过的玩家列进下拉，按出现次数排序。"""
        counts: dict[str, int] = {}
        for m in matches:
            for p in m.participants:
                if p.name:
                    counts[p.name] = counts.get(p.name, 0) + 1
        me_name = matches[0].self_name if matches else ""
        items = [("", f"我（{me_name}）" if me_name else "我")]
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:40]:
            if name == me_name:
                continue
            items.append((name, f"{name}（{n}）"))
        current = self.viewer_combo.currentData() or ""
        existing = [
            (self.viewer_combo.itemData(i) or "", self.viewer_combo.itemText(i))
            for i in range(self.viewer_combo.count())
        ]
        if existing == items:
            return
        self.viewer_combo.blockSignals(True)
        self.viewer_combo.clear()
        for data, label in items:
            self.viewer_combo.addItem(label, data)
        idx = next((i for i, (d, _) in enumerate(items) if d == current), 0)
        self.viewer_combo.setCurrentIndex(idx)
        self.viewer_combo.blockSignals(False)

    def refresh(self) -> None:
        all_matches: list[Match] = self.store.all()
        total = len(all_matches)
        self._sync_viewers(all_matches)
        viewer = self.viewer_combo.currentData() or None

        # 模式下拉：只按库里实际出现的模式重建，保留当前选择
        self._sync_mode_combo(all_matches)

        chosen = self.mode_combo.currentData() or ""
        scoped = [m for m in all_matches if not chosen or m.mode == chosen]

        # 同步范围控件的上限，不要把值撑爆
        cap = max(100, len(scoped))
        self.range_spin.blockSignals(True)
        self.range_spin.setMaximum(cap)
        if self.range_spin.value() > cap:
            self.range_spin.setValue(cap)
        self.range_spin.blockSignals(False)
        self.range_spin.setEnabled(len(scoped) > 100 and not self.chk_all.isChecked())

        if self.chk_all.isChecked() or len(scoped) <= 100:
            matches = scoped
        else:
            matches = scoped[: self.range_spin.value()]

        picked = len(matches)
        if viewer:
            # 视角玩家没参加的对局不能算进他的数据
            matches = [m for m in matches if m.has_player(viewer)]
            skipped = picked - len(matches)
            if skipped:
                self.side_hint.setText(f"已跳过 {skipped} 场（{viewer} 不在场）")

        self.dashboard.refresh(matches, viewer=viewer)
        self.matches_page.set_matches(matches, viewer=viewer)
        self.teammates_page.set_data(matches, viewer=viewer)
        self.recommend_page.set_data(matches, viewer=viewer)

        s = summarize(matches, viewer=viewer)
        demo_count = sum(1 for m in matches if m.source == "demo")
        real = len(matches) - demo_count
        self.side_status.setText(f"共 {len(matches)} 场 · 胜率 {s.win_rate*100:.1f}%")
        if demo_count and not real:
            self.side_hint.setText("⚠ 当前全是演示数据\n去「导入」连客户端或录入真实对局")
        elif demo_count:
            self.side_hint.setText(f"演示 {demo_count} 场 / 真实 {real} 场")
        else:
            self.side_hint.setText(f"总库 {total} 场" if len(matches) < total else "数据来源：客户端 / 截图录入")
        self.status_msg.setText(
            f"{len(matches)} 场 · {s.wins} 胜 {s.losses} 负 · 数据库 {self.store.path}"
        )

    def _sync_mode_combo(self, matches: list[Match]) -> None:
        """按库里现有的模式重建下拉项，尽量保留用户当前选的那个。"""
        counts: dict[str, int] = {}
        for m in matches:
            counts[m.mode] = counts.get(m.mode, 0) + 1
        wanted = [("", "全部模式")] + [
            (mode, f"{mode_display(mode)}（{n}）")
            for mode, n in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
        current = self.mode_combo.currentData() or ""
        existing = [
            (self.mode_combo.itemData(i) or "", self.mode_combo.itemText(i))
            for i in range(self.mode_combo.count())
        ]
        if existing == wanted:
            return
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        for data, label in wanted:
            self.mode_combo.addItem(label, data)
        idx = next((i for i, (d, _) in enumerate(wanted) if d == current), 0)
        self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.blockSignals(False)

    def _on_scope_toggled(self, checked: bool) -> None:
        self.refresh()
