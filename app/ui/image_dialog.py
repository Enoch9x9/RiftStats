"""单场录入对话框：图片在左，可编辑的 10 行表格在右。

这一版是"人工+半自动"：表格按截图的行序排好，你照着填/改，确认后入库。
OCR 是下一步接进来的——接口已经留好（fill_from_rows），识别结果直接灌进这张表，
人再修一遍，比全自动可靠得多。
"""

from __future__ import annotations

import time
from typing import Iterable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import BLUE, RED, Match, Participant
from . import theme, widgets

COLUMNS = ["队伍", "位置", "召唤师 ID", "英雄", "击杀", "死亡", "助攻", "输出", "承伤"]


class ImageView(QLabel):
    """按控件大小等比缩放显示图片，不会被裁掉。"""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(placeholder, parent)
        self._pix: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(420)

    def load(self, path: str) -> bool:
        pix = QPixmap(path)
        if pix.isNull():
            self._pix = None
            self.setText("这张图打不开")
            return False
        self._pix = pix
        self.setText("")
        self.update()
        return True

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pix is None:
            return
        area = self.rect().adjusted(4, 4, -4, -4)
        scaled = self._pix.scaled(
            area.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        p = QPainter(self)
        p.drawPixmap(
            area.x() + (area.width() - scaled.width()) // 2,
            area.y() + (area.height() - scaled.height()) // 2,
            scaled,
        )


class ImageImportDialog(QDialog):
    def __init__(self, image_path: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("录入一场对局")
        self.resize(1180, 760)
        self._path = image_path
        self._match: Match | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # 左：预览
        left, left_lay = widgets.panel()
        left.setFixedWidth(430)
        title = widgets.SectionTitle("截图")
        left_lay.addWidget(title)
        self.preview = ImageView("拖一张图进来，\n或者点下面选图")
        self.preview.setStyleSheet(
            f"background: #0B1319; border: 1px dashed {theme.BORDER};"
            f"border-radius: 8px; color: {theme.TEXT_DIM};"
        )
        left_lay.addWidget(self.preview, 1)

        btn_pick = QPushButton("选择图片…")
        btn_pick.clicked.connect(self._pick)
        self.btn_ocr = QPushButton("识别图片内容")
        self.btn_ocr.setObjectName("Primary")
        self.btn_ocr.clicked.connect(self._ocr)
        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_pick)
        btn_row.addWidget(self.btn_ocr)
        left_lay.addLayout(btn_row)

        self.ocr_state = QLabel("识别引擎：未接入（v0.2 接 RapidOCR，先人工填）")
        self.ocr_state.setObjectName("CardHint")
        self.ocr_state.setWordWrap(True)
        left_lay.addWidget(self.ocr_state)
        root.addWidget(left)

        # 右：元信息 + 表格
        right = QVBoxLayout()
        right.setSpacing(10)

        meta_panel, meta_lay = widgets.panel(margins=14, spacing=8)
        meta_lay.addWidget(widgets.SectionTitle("对局信息"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.cmb_result = QComboBox()
        self.cmb_result.addItems(["胜利", "失败"])
        self.cmb_side = QComboBox()
        self.cmb_side.addItems(["我在队伍 1（上）", "我在队伍 2（下）"])
        self.cmb_side.currentIndexChanged.connect(self._repaint_side_colors)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["ARAM", "CLASSIC", "URF", "CHERRY"])
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(1, 120)
        self.spin_duration.setSuffix(" 分钟")
        self.spin_duration.setValue(25)
        self.spin_self_row = QSpinBox()
        self.spin_self_row.setRange(1, 10)
        self.spin_self_row.setValue(1)
        self.spin_self_row.valueChanged.connect(self._mark_self)

        form.addRow("结果", self.cmb_result)
        form.addRow("我方队伍", self.cmb_side)
        form.addRow("模式", self.cmb_mode)
        form.addRow("时长", self.spin_duration)
        form.addRow("我是第几行", self.spin_self_row)
        meta_lay.addLayout(form)
        right.addWidget(meta_panel)

        table_panel, table_lay = widgets.panel(margins=14, spacing=8)
        head = QHBoxLayout()
        head.addWidget(widgets.SectionTitle("10 名玩家的数据"))
        head.addStretch(1)
        hint = QLabel("行序 = 截图从上到下；队伍 1 是前 5 行")
        hint.setObjectName("CardHint")
        head.addWidget(hint)
        table_lay.addLayout(head)

        self.table = QTableWidget(10, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(2, 180)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self._reset_rows()
        table_lay.addWidget(self.table)
        right.addWidget(table_panel, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("保存这场对局")
        btn_save.setObjectName("Primary")
        btn_save.clicked.connect(self._save)
        foot.addWidget(btn_cancel)
        foot.addWidget(btn_save)
        right.addLayout(foot)

        root.addLayout(right, 1)

        if image_path:
            self._show_image(image_path)

    # ---- 图片 ------------------------------------------------------------
    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择截图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._show_image(path)

    def _show_image(self, path: str) -> None:
        if self.preview.load(path):
            self._path = path

    def _ocr(self) -> None:
        try:
            from ..sources import ocr  # 可选模块
        except Exception:
            QMessageBox.information(
                self,
                "还没接识别",
                "识别引擎还没装。这一版先把表格填好就能入库；\n"
                "下一版接 RapidOCR（离线中文+数字），识别结果会直接填进右边这张表，你再改几格。",
            )
            return
        if not ocr.available():
            QMessageBox.warning(self, "缺少依赖", "rapidocr_onnxruntime 未安装。")
            return
        self.ocr_state.setText("识别中…")
        rows = ocr.parse_scoreboard(self._path)
        self.fill_from_rows(rows)
        self.ocr_state.setText(f"识别完成：{len(rows)} 行，请核对数字")

    # ---- 表格 ------------------------------------------------------------
    def _reset_rows(self) -> None:
        for r in range(10):
            side_item = QTableWidgetItem("队伍 1" if r < 5 else "队伍 2")
            side_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            side_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 0, side_item)
            role_item = QTableWidgetItem(str((r % 5) + 1))
            role_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            role_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 1, role_item)
            for c in range(2, len(COLUMNS)):
                self.table.setItem(r, c, QTableWidgetItem(""))

    def fill_from_rows(self, rows: Iterable[dict]) -> None:
        """OCR 或外部数据的入口：每行一个 dict，键名同 COLUMNS 的语义。"""
        for r, row in enumerate(rows):
            if r >= 10:
                break
            for c, key in enumerate(["name", "champion", "kills", "deaths", "assists",
                                     "damage_dealt", "damage_taken"], start=2):
                if key in row and row[key] not in (None, ""):
                    self.table.setItem(r, c, QTableWidgetItem(str(row[key])))

    def _repaint_side_colors(self) -> None:
        self._mark_self()

    def _mark_self(self) -> None:
        """自己那一行描金、我方队伍整块淡蓝，方便对着截图核对。"""
        me_row = self.spin_self_row.value() - 1
        my_side = BLUE if me_row < 5 else RED
        for r in range(10):
            row_side = BLUE if r < 5 else RED
            if r == me_row:
                bg = QColor(200, 170, 110, 60)
            elif row_side == my_side:
                bg = QColor(63, 169, 245, 22)
            else:
                bg = QColor(0, 0, 0, 0)
            for c in range(len(COLUMNS)):
                item = self.table.item(r, c)
                if item:
                    item.setBackground(bg)

    # ---- 保存 ------------------------------------------------------------
    def result_match(self) -> Match | None:
        return self._match

    def _save(self) -> None:
        rows = []
        for r in range(10):
            def txt(c: int) -> str:
                item = self.table.item(r, c)
                return item.text().strip() if item else ""

            def num(c: int) -> int:
                raw = txt(c).replace(",", "").replace("，", "")
                try:
                    return int(float(raw)) if raw else 0
                except ValueError:
                    return 0

            name = txt(2)
            if not name:
                QMessageBox.warning(self, "还差一点", f"第 {r+1} 行的召唤师 ID 是空的。")
                return
            rows.append(
                Participant(
                    name=name,
                    side=BLUE if r < 5 else RED,
                    slot=r % 5,
                    champion=txt(3),
                    kills=num(4),
                    deaths=num(5),
                    assists=num(6),
                    damage_dealt=num(7),
                    damage_taken=num(8),
                )
            )

        me_row = self.spin_self_row.value() - 1
        rows[me_row].is_self = True
        self_side = BLUE if me_row < 5 else RED
        self._match = Match(
            match_id=f"manual:{int(time.time())}-{me_row}",
            created_at=int(time.time()),
            duration_s=self.spin_duration.value() * 60,
            mode=self.cmb_mode.currentText(),
            win=self.cmb_result.currentIndex() == 0,
            self_side=self_side,
            self_slot=me_row % 5,
            self_name=rows[me_row].name,
            source="manual",
            participants=rows,
        )
        self.accept()
