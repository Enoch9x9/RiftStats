"""数据导入页：客户端直连 / 截图录入 / 演示数据，三条路通到一个仓库。"""

from __future__ import annotations

import time
import traceback

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import diag
from ..models import Match
from ..sources import demo, lcu
from . import theme, widgets
from .image_dialog import ImageImportDialog


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn(self.progress.emit))
        except Exception:
            self.failed.emit(traceback.format_exc(limit=3))


class ImportPage(QWidget):
    data_changed = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._worker: Worker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("导入数据")
        title.setObjectName("PageTitle")
        sub = QLabel("一个仓库，三条路。优先用客户端直连——不用截图，数据还全。")
        sub.setObjectName("PageSub")
        box.addWidget(title)
        box.addWidget(sub)
        root.addLayout(box)

        # --- 1. 客户端直连
        p1, lay1 = widgets.panel()
        head1 = QHBoxLayout()
        head1.addWidget(widgets.SectionTitle("① 客户端直连（推荐）"))
        self.lcu_state = widgets.badge("未检测", theme.TEXT_DIM)
        head1.addWidget(self.lcu_state)
        head1.addStretch(1)
        lay1.addLayout(head1)
        desc1 = QLabel(
            "读取英雄联盟客户端本地接口（LCU），无需 API key。要求：游戏客户端保持登录并正在运行。\n"
            "注意：客户端本地只缓存 20 场，想拉更多历史要用下面的「深度采集」——"
            "打开客户端的对局记录往下滚，滚一页抓 20 场。"
        )
        desc1.setObjectName("CardHint")
        desc1.setWordWrap(True)
        lay1.addWidget(desc1)
        row1 = QHBoxLayout()
        self.btn_probe = QPushButton("检测客户端")
        self.btn_probe.clicked.connect(self._probe)
        self.btn_sync = QPushButton("同步最新 20 场")
        self.btn_sync.setObjectName("Primary")
        self.btn_sync.clicked.connect(self._sync)
        self.btn_logs = QPushButton("从本地日志恢复历史")
        self.btn_logs.clicked.connect(self._harvest_logs)
        self.btn_harvest = QPushButton("深度采集（跟滚 4 分钟）")
        self.btn_harvest.clicked.connect(self._harvest)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self._stop_harvest)
        self.btn_stop.setEnabled(False)
        self.btn_manual = QPushButton("手动指定 lockfile…")
        self.btn_manual.clicked.connect(self._pick_lockfile)
        self.btn_manual.setToolTip("自动找不到客户端时，直接指到客户端目录里的 lockfile 文件")
        self.btn_check = QPushButton("生成自检报告")
        self.btn_check.clicked.connect(self._selfcheck)
        self.btn_check.setToolTip("把找到的 lockfile、日志目录、端口是否可用全写进诊断日志，方便发给别人看")
        row1.addWidget(self.btn_probe)
        row1.addWidget(self.btn_sync)
        row1.addWidget(self.btn_logs)
        row1.addWidget(self.btn_harvest)
        row1.addWidget(self.btn_stop)
        row1.addWidget(self.btn_manual)
        row1.addWidget(self.btn_check)
        row1.addStretch(1)
        lay1.addLayout(row1)

        row1b = QHBoxLayout()
        row1b.addWidget(QLabel("读取范围"))
        self.range_combo = QComboBox()
        self.range_combo.addItem("最近 1 个月", 30)
        self.range_combo.addItem("最近 3 个月", 90)
        self.range_combo.addItem("最近半年", 180)
        self.range_combo.addItem("全部历史", 0)
        self.range_combo.setCurrentIndex(1)
        self.range_combo.setToolTip(
            "限制从日志里翻历年对局的时间跨度。\n"
            "客户端日志越久，候选 id 越多，验证花费的时间越长；\n"
            "选小一点能快很多，选「全部历史」就是全量翻。"
        )
        row1b.addWidget(self.range_combo)
        row1b.addStretch(1)
        lay1.addLayout(row1b)
        hint1 = QLabel(
            "客户端界面只缓存 20 条，但客户端日志里记着每一场的 gameId——"
            "「从本地日志恢复历史」会把它们捞出来逐条反查，实测能找回 3 个月的对局。"
        )
        hint1.setObjectName("CardHint")
        hint1.setWordWrap(True)
        lay1.addWidget(hint1)
        root.addWidget(p1)

        # --- 2. 截图录入
        p2, lay2 = widgets.panel()
        lay2.addWidget(widgets.SectionTitle("② 截图识别 / 手动录入"))
        desc2 = QLabel(
            "适合没有客户端、或者想补录别人的局。导入赛后计分板图，按队伍里从上到下的顺序填进表格，"
            "识别结果可以逐格改，确认后存成一场对局。"
        )
        desc2.setObjectName("CardHint")
        desc2.setWordWrap(True)
        lay2.addWidget(desc2)
        row2 = QHBoxLayout()
        btn_img = QPushButton("导入图片…")
        btn_img.clicked.connect(self._import_image)
        row2.addWidget(btn_img)
        row2.addStretch(1)
        lay2.addLayout(row2)
        root.addWidget(p2)

        # --- 3. 演示数据
        p3, lay3 = widgets.panel()
        lay3.addWidget(widgets.SectionTitle("③ 演示数据"))
        desc3 = QLabel("先用假数据把界面和统计跑通。演示数据 match_id 带 demo: 前缀，可以单独清掉。")
        desc3.setObjectName("CardHint")
        desc3.setWordWrap(True)
        lay3.addWidget(desc3)
        row3 = QHBoxLayout()
        btn_demo = QPushButton("载入 48 场演示数据")
        btn_demo.clicked.connect(self._load_demo)
        btn_clear_demo = QPushButton("清空演示数据")
        btn_clear_demo.clicked.connect(self._clear_demo)
        row3.addWidget(btn_demo)
        row3.addWidget(btn_clear_demo)
        row3.addStretch(1)
        lay3.addLayout(row3)
        root.addWidget(p3)

        # --- 日志
        log_panel, log_lay = widgets.panel()
        log_head = QHBoxLayout()
        log_head.addWidget(widgets.SectionTitle("运行日志"))
        log_head.addStretch(1)
        self.diag_hint = QLabel(f"诊断日志：{diag.log_path() or '未启用'}")
        self.diag_hint.setObjectName("CardHint")
        log_head.addWidget(self.diag_hint)
        btn_open_log = QPushButton("打开日志目录")
        btn_open_log.clicked.connect(self._open_log_dir)
        log_head.addWidget(btn_open_log)
        log_lay.addLayout(log_head)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(150)
        log_lay.addWidget(self.log)
        root.addWidget(log_panel, 1)

        try:
            self.manual_lock = self.store.get_setting("manual_lockfile", "")
        except Exception:
            self.manual_lock = ""
        if self.manual_lock:
            self._log(f"使用手动指定的 lockfile：{self.manual_lock}")
        self._log(f"数据目录：{self.store.path.parent}")
        self._log("提示：先点「检测客户端」，能连上就完全不用截图了。")

    # ---- 工具 ------------------------------------------------------------
    def _selfcheck(self) -> None:
        self._log("开始自检…（结果会同时写进诊断日志）")
        try:
            for line in lcu.selfcheck():
                self._log("  " + line)
        except Exception as exc:
            self._log(f"自检失败：{exc}")
        self._log(f"自检完成，日志：{diag.log_path()}")

    def _pick_lockfile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择客户端的 lockfile", "", "lockfile (lockfile);;所有文件 (*.*)"
        )
        if not path:
            return
        self.manual_lock = path
        try:
            self.store.set_setting("manual_lockfile", path)
        except Exception:
            pass
        self._log(f"已手动指定：{path}")
        self._probe()

    def _open_log_dir(self) -> None:
        p = diag.log_path()
        target = p.parent if p else self.store.path.parent
        try:
            import os

            os.startfile(str(target))  # noqa: S606
            self._log(f"已打开：{target}")
        except Exception as exc:
            self._log(f"打不开文件夹：{exc}")

    def _log(self, text: str) -> None:
        self.log.append(time.strftime("[%H:%M:%S] ") + text)

    def _busy(self, busy: bool, text: str = "") -> None:
        for b in (self.btn_probe, self.btn_sync, self.btn_harvest, self.btn_logs):
            b.setEnabled(not busy)
        if text:
            self._log(text)
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor) if busy else QApplication.restoreOverrideCursor()

    def _save(self, matches: list[Match]) -> int:
        fresh = sum(1 for m in matches if self.store.upsert(m))
        self._log(f"入库完成：新增 {fresh} 场，更新 {len(matches) - fresh} 场")
        self.data_changed.emit()
        return fresh

    # ---- 客户端 ----------------------------------------------------------
    def _probe(self) -> None:
        self._log("正在查找客户端连接…")
        lock, why = lcu.diagnose(getattr(self, "manual_lock", "") or None)
        diag.info("检测结果：%s" % why)
        self._log(f"· {why}")
        if lock is None:
            self.lcu_state.setText("未连接")
            self.lcu_state.setStyleSheet(
                f"color: {theme.LOSS}; border: 1px solid {theme.LOSS}; border-radius: 8px;"
                "padding: 1px 8px; font-size: 10px;"
            )
            self._log("✗ 现在连不上。LCU 只在客户端运行、并且已经进入大区之后才可用。")
            self._log("  排查顺序：")
            self._log("   ① 任务栏里是不是只有「启动器」——客户端要进到生涯页面那种")
            self._log("   ② 是否已经登录成功、选好了大区")
            self._log("   ③ 客户端是不是用管理员权限启动的（那本程序也要用管理员启动）")
            self._log(f"   ④ 详细记录见 {diag.log_path()}")
            return
        try:
            client = lcu.LcuClient(lock)
            diag.info("检测客户端：lockfile=%s" % lock)
            diag.dump_client(client)
            me = client.current_summoner()
            phase = client.gameflow_phase()
            name = me.get("gameName") or me.get("displayName") or "未知召唤师"
            self.lcu_state.setText(f"已连接 {name}")
            self.lcu_state.setStyleSheet(
                f"color: {theme.WIN}; border: 1px solid {theme.WIN}; border-radius: 8px;"
                "padding: 1px 8px; font-size: 10px;"
            )
            self._log(f"✓ 当前召唤师：{name}  ·  客户端状态：{phase}")
        except Exception as exc:
            diag.exception("检测客户端时接口失败")
            self._log(f"✗ 接口访问失败：{exc}")
            self._log(f"  详细情况已写入诊断日志：{diag.log_path()}")

    def _sync(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._log("开始同步最新 20 场…")
        self._busy(True)

        def job(emit):
            return lcu.fetch_matches(limit=20)

        self._worker = Worker(job, self)
        self._worker.done.connect(self._on_sync_done)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    # ---- 深度采集 --------------------------------------------------------
    def _harvest_logs(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._stop_flag = False
        self.btn_stop.setEnabled(True)
        self._busy(True)
        self._log("=== 从本地日志恢复历史 ===")

        days = self.range_combo.currentData() or None
        self._log(f"读取范围：{self.range_combo.currentText()}")

        def job(emit):
            return lcu.harvest_from_logs(
                self.store,
                progress=emit,
                should_stop=lambda: getattr(self, "_stop_flag", False),
                days=days,
            )

        self._worker = Worker(job, self)
        self._worker.progress.connect(self._log)
        self._worker.done.connect(self._on_logs_done)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_logs_done(self, result) -> None:
        self._busy(False)
        self.btn_stop.setEnabled(False)
        if not isinstance(result, dict):
            return
        if result.get("aborted"):
            self._log(f"⚠ {result['aborted']}")
            return
        if result.get("error"):
            self._log(f"✗ {result['error']}")
            return
        self._log(
            f"=== 完成：检查 {result['checked']} 个候选，新增 {result['saved']} 场，"
            f"库里共 {self.store.count()} 场 ==="
        )
        self.data_changed.emit()

    def _harvest(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._stop_flag = False
        self.btn_stop.setEnabled(True)
        self._busy(True)
        self._log("=== 深度采集开始（4 分钟）===")
        self._log("步骤：客户端 → 生涯/对局记录 → 一直往下滚。滚一页这里多 20 场。")

        def job(emit):
            return lcu.harvest(
                self.store,
                duration_s=240,
                progress=emit,
                should_stop=lambda: getattr(self, "_stop_flag", False),
            )

        self._worker = Worker(job, self)
        self._worker.progress.connect(self._log)
        self._worker.done.connect(self._on_harvest_done)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _stop_harvest(self) -> None:
        self._stop_flag = True
        self._log("已请求停止，等当前窗口处理完…")

    def _on_harvest_done(self, result) -> None:
        self._busy(False)
        self.btn_stop.setEnabled(False)
        if not isinstance(result, dict):
            return
        if result.get("error"):
            self._log(f"✗ {result['error']}")
            return
        self._log(
            f"=== 采集结束：{result['pages']} 个窗口，{result['saved']} 场，"
            f"库里共 {self.store.count()} 场 ==="
        )
        self.data_changed.emit()

    def _on_sync_done(self, payload) -> None:
        self._busy(False)
        matches, logs = payload
        for line in logs:
            self._log(line)
        if matches:
            self._save(matches)
        else:
            self._log("没有拿到对局。可以先手动截图录入，或者检查客户端是否在运行。")

    def _on_worker_failed(self, tb: str) -> None:
        self._busy(False)
        self._log("✗ 出错：\n" + tb)

    # ---- 图片 ------------------------------------------------------------
    def _import_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择赛后截图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return
        dlg = ImageImportDialog(path, self)
        if dlg.exec():
            match = dlg.result_match()
            if match:
                self._save([match])
                self._log(f"已保存 1 场：{match.created_at_str} {'胜' if match.win else '负'}")

    # ---- 演示 ------------------------------------------------------------
    def _load_demo(self) -> None:
        matches = demo.generate(48)
        self._save(matches)
        self._log("演示数据已载入 —— 这 48 场都是随机生成的，不是你的真实战绩。")

    def _clear_demo(self) -> None:
        self.store.clear(source="demo")
        self._log("演示数据已清空")
        self.data_changed.emit()
