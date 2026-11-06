#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""串口助手 (Serial Assistant)

基于 PySide6 + pyserial 的串口调试工具，界面参考 Windows 11 Fluent Design。

运行方式:
    python main.py
"""

from __future__ import annotations

import codecs
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

from PySide6.QtCore import QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIntValidator,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BAUD_RATES = [
    "9600",
    "19200",
    "38400",
    "57600",
    "115200",
    "128000",
    "230400",
    "256000",
    "460800",
    "921600",
]

DATA_BITS = [("5", serial.FIVEBITS), ("6", serial.SIXBITS), ("7", serial.SEVENBITS), ("8", serial.EIGHTBITS)]

STOP_BITS = [
    ("1", serial.STOPBITS_ONE),
    ("1.5", serial.STOPBITS_ONE_POINT_FIVE),
    ("2", serial.STOPBITS_TWO),
]

PARITIES = [
    ("无 (None)", serial.PARITY_NONE),
    ("奇校验 (Odd)", serial.PARITY_ODD),
    ("偶校验 (Even)", serial.PARITY_EVEN),
    ("标记 (Mark)", serial.PARITY_MARK),
    ("空格 (Space)", serial.PARITY_SPACE),
]

# (显示文本, (rtscts, xonxoff))
FLOW_CONTROLS = [
    ("无 (None)", (False, False)),
    ("硬件流控 (RTS/CTS)", (True, False)),
    ("软件流控 (XON/XOFF)", (False, True)),
]


def parse_hex_text(text: str) -> bytes:
    """把用户输入的 HEX 字符串解析成字节序列。

    支持空格、逗号、分号、换行分隔，也支持 0x 前缀。
    """
    parts = re.split(r"[,;\s]+", text.strip())
    chunks: list[str] = []
    for part in parts:
        if not part:
            continue
        token = part[2:] if part.lower().startswith("0x") else part
        if not re.fullmatch(r"[0-9A-Fa-f]+", token):
            raise ValueError(f"无法解析的 HEX 片段：{part}")
        chunks.append(token)
    joined = "".join(chunks)
    if not joined:
        return b""
    if len(joined) % 2:
        raise ValueError("HEX 内容的字节数必须为偶数：每两个十六进制字符表示 1 个字节。")
    return bytes.fromhex(joined)


# ---------------------------------------------------------------------------
# 串口读取线程
# ---------------------------------------------------------------------------

class SerialReader(QThread):
    """后台读取串口数据，通过信号把字节流交给界面线程。"""

    data_received = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, port: serial.Serial, parent: QWidget | None = None):
        super().__init__(parent)
        self._port = port
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        while self._running:
            try:
                chunk = self._port.read(128)
            except (serial.SerialException, OSError, TypeError) as exc:
                if self._running:
                    self.error_occurred.emit(str(exc))
                return
            if chunk:
                self.data_received.emit(bytes(chunk))


# ---------------------------------------------------------------------------
# 分段切换控件（文本 / HEX）
# ---------------------------------------------------------------------------

class SegmentedControl(QWidget):
    changed = Signal(int)

    def __init__(self, options: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._index = 0
        self._buttons: list[QToolButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        for index, text in enumerate(options):
            button = QToolButton(self)
            button.setObjectName("Segment")
            button.setText(text)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked=False, i=index: self._on_clicked(i))
            layout.addWidget(button)
            self._buttons.append(button)

    def _on_clicked(self, index: int) -> None:
        if index == self._index:
            return
        self._index = index
        self.changed.emit(index)

    def current_index(self) -> int:
        return self._index


# ---------------------------------------------------------------------------
# 样式表
# ---------------------------------------------------------------------------

STYLESHEET = """
QMainWindow, QWidget#Central {
    background-color: #F3F3F3;
}

QFrame#Card {
    background-color: #FFFFFF;
    border: 1px solid #E6E6E6;
    border-radius: 10px;
}

QLabel#CardTitle {
    color: #1A1A1A;
    font-size: 15px;
    font-weight: 600;
}

QLabel#FieldLabel {
    color: #6E6E6E;
    font-size: 12px;
}

QLabel#Hint {
    color: #8C8C8C;
    font-size: 12px;
}

QLabel#StatusChip {
    border-radius: 12px;
    padding: 3px 12px;
    font-size: 12px;
}
QLabel#StatusChip[state="off"] {
    background-color: #F2F2F2;
    color: #6E6E6E;
    border: 1px solid #E3E3E3;
}
QLabel#StatusChip[state="on"] {
    background-color: #DFF6DD;
    color: #0F7B0F;
    border: 1px solid #C6EAC3;
}

QComboBox, QSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #DCDCDC;
    border-radius: 6px;
    min-height: 32px;
    padding-left: 10px;
    padding-right: 6px;
    color: #1A1A1A;
    font-size: 13px;
    selection-background-color: #CFE4F5;
    selection-color: #1A1A1A;
}
QComboBox:hover, QSpinBox:hover {
    border-color: #BDBDBD;
}
QComboBox:focus, QSpinBox:focus {
    border-color: #0067C0;
}
QComboBox:disabled, QSpinBox:disabled {
    background-color: #F7F7F7;
    color: #9A9A9A;
    border-color: #ECECEC;
}
QComboBox QLineEdit {
    border: none;
    background: transparent;
    padding: 0;
    min-height: 0;
    font-size: 13px;
    color: #1A1A1A;
}
QComboBox::drop-down {
    border: none;
    width: 26px;
}
QComboBox::down-arrow {
    image: url("__DOWN__");
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #DCDCDC;
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: #E8F2FC;
    selection-color: #005FB8;
}
QComboBox QAbstractItemView::item {
    min-height: 28px;
    padding-left: 8px;
    border-radius: 4px;
}

QSpinBox::up-button, QSpinBox::down-button {
    width: 20px;
    border: none;
    background: transparent;
}
QSpinBox::up-arrow {
    image: url("__UP__");
    width: 9px;
    height: 9px;
}
QSpinBox::down-arrow {
    image: url("__DOWN__");
    width: 9px;
    height: 9px;
}

QPlainTextEdit {
    background-color: #FFFFFF;
    border: 1px solid #E1E1E1;
    border-radius: 8px;
    padding: 10px;
    color: #202020;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 12px;
    selection-background-color: #CFE4F5;
    selection-color: #101010;
}
QPlainTextEdit:focus {
    border-color: #0067C0;
}
QPlainTextEdit[readOnly="true"] {
    background-color: #FCFCFC;
}

QPushButton {
    font-size: 13px;
    border-radius: 6px;
}
QPushButton#Primary {
    background-color: #0067C0;
    color: #FFFFFF;
    border: 1px solid #0067C0;
    padding: 8px 24px;
    font-weight: 600;
}
QPushButton#Primary:hover {
    background-color: #1672CB;
    border-color: #1672CB;
}
QPushButton#Primary:pressed {
    background-color: #005A9E;
    border-color: #005A9E;
}
QPushButton#Primary:disabled {
    background-color: #F0F0F0;
    color: #A6A6A6;
    border-color: #E6E6E6;
}

QPushButton#Secondary {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #D6D6D6;
    padding: 7px 16px;
}
QPushButton#Secondary:hover {
    background-color: #F6F6F6;
    border-color: #C4C4C4;
}
QPushButton#Secondary:pressed {
    background-color: #EFEFEF;
}
QPushButton#Secondary:disabled {
    color: #9C9C9C;
    background-color: #FAFAFA;
    border-color: #E0E0E0;
}

QPushButton#Ghost {
    background-color: transparent;
    color: #4A4A4A;
    border: none;
    padding: 6px 12px;
}
QPushButton#Ghost:hover {
    background-color: #EFEFEF;
}
QPushButton#Ghost:pressed {
    background-color: #E5E5E5;
}
QPushButton#Ghost:disabled {
    color: #ABABAB;
}

QPushButton#PauseBtn {
    background-color: #FFFFFF;
    color: #1A1A1A;
    border: 1px solid #D6D6D6;
    padding: 6px 14px;
}
QPushButton#PauseBtn:hover {
    background-color: #F6F6F6;
}
QPushButton#PauseBtn:checked {
    background-color: #EAF2FC;
    color: #005FB8;
    border-color: #0067C0;
}

QToolButton#Segment {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px 14px;
    color: #5C5C5C;
    font-size: 12px;
}
QToolButton#Segment:hover {
    background-color: #E8E8E8;
}
QToolButton#Segment:checked {
    background-color: #0067C0;
    color: #FFFFFF;
}

QWidget#Segmented {
    background-color: #F2F2F2;
    border: 1px solid #E2E2E2;
    border-radius: 9px;
}

QCheckBox {
    spacing: 7px;
    color: #1F1F1F;
    font-size: 12px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid #C9C9C9;
    background-color: #FFFFFF;
}
QCheckBox::indicator:hover {
    border-color: #9F9F9F;
    background-color: #F7F7F7;
}
QCheckBox::indicator:checked {
    background-color: #0067C0;
    border-color: #0067C0;
    image: url("__CHECK__");
}
QCheckBox::indicator:checked:hover {
    background-color: #1672CB;
    border-color: #1672CB;
}
QCheckBox:disabled {
    color: #A0A0A0;
}
QCheckBox::indicator:disabled {
    border-color: #E5E5E5;
    background-color: #F5F5F5;
}

QStatusBar {
    background-color: #F3F3F3;
    border-top: 1px solid #E4E4E4;
    color: #616161;
    font-size: 12px;
}
QStatusBar::item {
    border: none;
}
QLabel#StatLabel {
    color: #4F4F4F;
    font-size: 12px;
    padding: 0 10px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0;
}
QScrollBar::handle:vertical {
    background: #CACACA;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #AEAEAE;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0 2px 2px 2px;
}
QScrollBar::handle:horizontal {
    background: #CACACA;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #AEAEAE;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

QSplitter::handle {
    background-color: transparent;
}

QToolTip {
    background-color: #2B2B2B;
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
}
"""


def _build_ui_icons() -> dict[str, str]:
    """绘制界面所需的矢量图标（复选框对勾、下拉箭头），返回 PNG 路径。"""
    icon_dir = Path(tempfile.gettempdir()) / "serial_assistant_icons"
    icon_dir.mkdir(parents=True, exist_ok=True)

    specs = {
        "check": ([(0.20, 0.52), (0.42, 0.74), (0.80, 0.28)], "#FFFFFF"),
        "down": ([(0.28, 0.40), (0.50, 0.62), (0.72, 0.40)], "#5F5F5F"),
        "up": ([(0.28, 0.62), (0.50, 0.40), (0.72, 0.62)], "#5F5F5F"),
    }

    paths: dict[str, str] = {}
    size = 48
    for name, (points, color) in specs.items():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(size * 0.10)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(x * size, y * size) for x, y in points]))
        painter.end()

        path = icon_dir / f"{name}.png"
        pixmap.save(str(path), "PNG")
        paths[name] = path.as_posix()

    return paths


def build_stylesheet() -> str:
    icons = _build_ui_icons()
    return (
        STYLESHEET.replace("__CHECK__", icons["check"])
        .replace("__DOWN__", icons["down"])
        .replace("__UP__", icons["up"])
    )


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._serial: serial.Serial | None = None
        self._reader: SerialReader | None = None
        self._paused = False
        self._pause_buffer = bytearray()
        self._rx_count = 0
        self._tx_count = 0
        self._connection_desc = ""
        self._decoder = self._new_decoder()

        self._send_timer = QTimer(self)
        self._send_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._send_timer.timeout.connect(self._on_timed_tick)

        self._build_ui()
        self.refresh_ports(silent=True)
        self._update_counters()
        self._set_connected_ui(False)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.setWindowTitle("串口助手 · Serial Assistant")
        self.resize(1180, 800)
        self.setMinimumSize(1000, 700)

        central = QWidget()
        central.setObjectName("Central")
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(14)

        root.addWidget(self._build_connection_card())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(14)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_receive_card())
        splitter.addWidget(self._build_send_card())
        splitter.setSizes([540, 260])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self._build_statusbar()

    def _build_connection_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._add_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("串口连接")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.refresh_btn = QPushButton("刷新串口")
        self.refresh_btn.setObjectName("Ghost")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setToolTip("扫描并刷新当前可用的串口列表")
        self.refresh_btn.clicked.connect(lambda: self.refresh_ports())
        header.addWidget(self.refresh_btn)

        self.status_chip = QLabel("● 未连接")
        self.status_chip.setObjectName("StatusChip")
        self.status_chip.setProperty("state", "off")
        self.status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.status_chip)
        layout.addLayout(header)

        # 串口号：可下拉选择，也可手动输入
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.port_combo.lineEdit().setPlaceholderText("未检测到串口，可手动输入")
        self.port_combo.setMinimumWidth(140)
        self.port_combo.setToolTip("选择串口号，也可以直接手动输入，例如 COM5")

        # 波特率：可下拉选择常用值，也可手动输入
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.baud_combo.addItems(BAUD_RATES)
        self.baud_combo.setCurrentText("9600")
        self.baud_combo.setValidator(QIntValidator(1, 10_000_000, self))
        self.baud_combo.setToolTip("常用波特率下拉选择，也可手动输入自定义值")

        self.data_combo = QComboBox()
        self._fill_combo(self.data_combo, DATA_BITS, default_index=3)
        self.data_combo.setToolTip("数据位：5 / 6 / 7 / 8")

        self.stop_combo = QComboBox()
        self._fill_combo(self.stop_combo, STOP_BITS, default_index=0)
        self.stop_combo.setToolTip("停止位：1 / 1.5 / 2")

        self.parity_combo = QComboBox()
        self._fill_combo(self.parity_combo, PARITIES, default_index=0)
        self.parity_combo.setToolTip("校验位：无 / 奇校验 / 偶校验 / Mark / Space")

        self.flow_combo = QComboBox()
        self._fill_combo(self.flow_combo, FLOW_CONTROLS, default_index=0)
        self.flow_combo.setToolTip("流控：无 / 硬件流控 RTS/CTS / 软件流控 XON/XOFF")

        fields = QGridLayout()
        fields.setHorizontalSpacing(18)
        fields.setVerticalSpacing(14)
        for column in range(3):
            fields.setColumnStretch(column, 1)
        fields.addWidget(self._field("串口号", self.port_combo), 0, 0)
        fields.addWidget(self._field("波特率", self.baud_combo), 0, 1)
        fields.addWidget(self._field("数据位", self.data_combo), 0, 2)
        fields.addWidget(self._field("停止位", self.stop_combo), 1, 0)
        fields.addWidget(self._field("校验位", self.parity_combo), 1, 1)
        fields.addWidget(self._field("流控", self.flow_combo), 1, 2)
        layout.addLayout(fields)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.open_btn = QPushButton("打开串口")
        self.open_btn.setObjectName("Primary")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_serial)
        actions.addWidget(self.open_btn)

        self.close_btn = QPushButton("关闭串口")
        self.close_btn.setObjectName("Secondary")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close_serial)
        actions.addWidget(self.close_btn)

        actions.addStretch(1)
        hint = QLabel("提示：修改串口参数前请先关闭串口")
        hint.setObjectName("Hint")
        actions.addWidget(hint)
        layout.addLayout(actions)

        return card

    def _build_receive_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        self._add_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("接收区")
        title.setObjectName("CardTitle")
        header.addWidget(title)

        self.rx_segment = SegmentedControl(["文本", "HEX"])
        self.rx_segment.changed.connect(self._on_rx_mode_changed)
        header.addWidget(self.rx_segment)

        header.addStretch(1)

        self.overwrite_check = QCheckBox("覆盖接收")
        self.overwrite_check.setToolTip("勾选后，新接收的数据会覆盖接收区内容；不勾选则追加显示")
        header.addWidget(self.overwrite_check)

        self.pause_btn = QPushButton("暂停接收")
        self.pause_btn.setObjectName("PauseBtn")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.setToolTip("暂停后接收区不再刷新，但串口数据仍会继续读取并统计字节数")
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        header.addWidget(self.pause_btn)

        self.clear_rx_btn = QPushButton("清空接收")
        self.clear_rx_btn.setObjectName("Secondary")
        self.clear_rx_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_rx_btn.clicked.connect(self.clear_receive)
        header.addWidget(self.clear_rx_btn)

        self.save_rx_btn = QPushButton("保存数据")
        self.save_rx_btn.setObjectName("Secondary")
        self.save_rx_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_rx_btn.setToolTip("把接收区当前内容导出为 TXT 文件")
        self.save_rx_btn.clicked.connect(self.save_received)
        header.addWidget(self.save_rx_btn)

        layout.addLayout(header)

        self.rx_edit = QPlainTextEdit()
        self.rx_edit.setReadOnly(True)
        self.rx_edit.setUndoRedoEnabled(False)
        self.rx_edit.setMaximumBlockCount(200_000)
        self.rx_edit.setMinimumHeight(80)
        self.rx_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.rx_edit.setPlaceholderText("接收到的数据将显示在这里…")
        layout.addWidget(self.rx_edit, 1)

        return card

    def _build_send_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        self._add_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("发送区")
        title.setObjectName("CardTitle")
        header.addWidget(title)

        self.send_segment = SegmentedControl(["文本", "HEX"])
        self.send_segment.changed.connect(self._on_send_mode_changed)
        header.addWidget(self.send_segment)

        header.addStretch(1)

        self.newline_check = QCheckBox("发送新行")
        self.newline_check.setToolTip("发送时自动在末尾追加换行符 \\n")
        header.addWidget(self.newline_check)

        self.timed_check = QCheckBox("定时发送")
        self.timed_check.setToolTip("按设定的时间间隔循环发送当前内容")
        self.timed_check.toggled.connect(self._on_timed_toggled)
        header.addWidget(self.timed_check)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 600_000)
        self.interval_spin.setValue(1000)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setFixedWidth(112)
        self.interval_spin.setToolTip("定时发送的时间间隔（毫秒）")
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        header.addWidget(self.interval_spin)

        layout.addLayout(header)

        self.send_edit = QPlainTextEdit()
        self.send_edit.setPlaceholderText("输入要发送的内容（文本模式按 GBK 编码发送）")
        self.send_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.send_edit.setMinimumHeight(72)
        layout.addWidget(self.send_edit, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.clear_send_btn = QPushButton("清空发送")
        self.clear_send_btn.setObjectName("Secondary")
        self.clear_send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_send_btn.clicked.connect(self.send_edit.clear)
        footer.addWidget(self.clear_send_btn)

        hint = QLabel("文本按 GBK 编码发送；HEX 支持空格 / 逗号分隔与 0x 前缀")
        hint.setObjectName("Hint")
        footer.addWidget(hint)
        footer.addStretch(1)

        self.send_btn = QPushButton("发 送")
        self.send_btn.setObjectName("Primary")
        self.send_btn.setMinimumWidth(120)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(lambda: self.send_data())
        footer.addWidget(self.send_btn)

        layout.addLayout(footer)
        return card

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(True)
        bar.showMessage("就绪")

        self.rx_stat = QLabel("已接收 0 字节")
        self.rx_stat.setObjectName("StatLabel")
        self.tx_stat = QLabel("已发送 0 字节")
        self.tx_stat.setObjectName("StatLabel")
        bar.addPermanentWidget(self.rx_stat)
        bar.addPermanentWidget(self.tx_stat)

    def _field(self, label: str, control: QWidget) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        caption = QLabel(label)
        caption.setObjectName("FieldLabel")
        layout.addWidget(caption)
        layout.addWidget(control)
        return box

    @staticmethod
    def _fill_combo(combo: QComboBox, items: list[tuple[str, object]], default_index: int = 0) -> None:
        for text, data in items:
            combo.addItem(text, data)
        combo.setCurrentIndex(default_index)

    @staticmethod
    def _add_shadow(widget: QWidget, blur: int = 24, dy: int = 5, alpha: int = 20) -> None:
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setOffset(0, dy)
        effect.setColor(QColor(0, 0, 0, alpha))
        widget.setGraphicsEffect(effect)

    @staticmethod
    def _restyle(widget: QWidget, name: str | None = None) -> None:
        if name is not None:
            widget.setObjectName(name)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    # --------------------------------------------------------------- 串口操作

    def refresh_ports(self, silent: bool = False) -> None:
        current = self.port_combo.currentText().strip()
        ports = sorted(list_ports.comports(), key=lambda item: item.device)

        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for info in ports:
            self.port_combo.addItem(info.device)
            description = (info.description or "").strip()
            if description:
                self.port_combo.setItemData(
                    self.port_combo.count() - 1,
                    f"{info.device} · {description}",
                    Qt.ItemDataRole.ToolTipRole,
                )
        if current:
            self.port_combo.setCurrentText(current)
        elif ports:
            self.port_combo.setCurrentIndex(0)
        self.port_combo.blockSignals(False)

        if not silent:
            if ports:
                self.statusBar().showMessage(f"已刷新串口列表，共发现 {len(ports)} 个串口", 4000)
            else:
                self.statusBar().showMessage("未检测到可用串口，可手动输入串口号", 5000)

    def open_serial(self) -> None:
        if self._serial is not None:
            return

        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(self, "参数有误", "请选择或输入串口号。")
            return

        try:
            baud = int(self.baud_combo.currentText().strip())
            if baud <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "参数有误", "波特率必须是大于 0 的整数。")
            return

        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.bytesize = self.data_combo.currentData()
        ser.parity = self.parity_combo.currentData()
        ser.stopbits = self.stop_combo.currentData()
        rtscts, xonxoff = self.flow_combo.currentData()
        ser.rtscts = rtscts
        ser.xonxoff = xonxoff
        ser.timeout = 0.05
        ser.write_timeout = 1.0

        try:
            ser.open()
        except (serial.SerialException, ValueError, OSError) as exc:
            QMessageBox.critical(self, "打开串口失败", f"无法打开 {port}：\n{exc}")
            self.statusBar().showMessage(f"{port} 打开失败", 5000)
            return

        try:
            ser.reset_input_buffer()
        except (serial.SerialException, OSError):
            pass

        self._serial = ser
        self._reader = SerialReader(ser)
        self._reader.data_received.connect(self._on_rx_data)
        self._reader.error_occurred.connect(self._on_serial_error)
        self._reader.start()

        self._connection_desc = f"{port} · {baud} · {self._frame_text()}"
        self._set_connected_ui(True)
        self.statusBar().showMessage(f"串口 {port} 已打开（{baud} {self._frame_text()}）", 6000)

    def close_serial(self) -> None:
        if self._close_port():
            self.statusBar().showMessage("串口已关闭", 4000)

    def _close_port(self) -> bool:
        was_open = self._serial is not None

        self._send_timer.stop()
        if self.timed_check.isChecked():
            self.timed_check.blockSignals(True)
            self.timed_check.setChecked(False)
            self.timed_check.blockSignals(False)

        reader, self._reader = self._reader, None
        if reader is not None:
            for signal in (reader.data_received, reader.error_occurred):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            reader.stop()
            reader.wait(1000)

        if self._serial is not None:
            try:
                self._serial.close()
            except (serial.SerialException, OSError):
                pass
            self._serial = None

        if was_open:
            self._connection_desc = ""
            self._set_connected_ui(False)
        return was_open

    def _frame_text(self) -> str:
        parity_map = {
            serial.PARITY_NONE: "N",
            serial.PARITY_ODD: "O",
            serial.PARITY_EVEN: "E",
            serial.PARITY_MARK: "M",
            serial.PARITY_SPACE: "S",
        }
        stop_map = {
            serial.STOPBITS_ONE: "1",
            serial.STOPBITS_ONE_POINT_FIVE: "1.5",
            serial.STOPBITS_TWO: "2",
        }
        parity = parity_map.get(self.parity_combo.currentData(), "N")
        stop = stop_map.get(self.stop_combo.currentData(), "1")
        return f"{self.data_combo.currentText()}{parity}{stop}"

    def _set_connected_ui(self, connected: bool) -> None:
        for widget in (
            self.port_combo,
            self.baud_combo,
            self.data_combo,
            self.stop_combo,
            self.parity_combo,
            self.flow_combo,
            self.refresh_btn,
        ):
            widget.setEnabled(not connected)

        self.open_btn.setEnabled(not connected)
        self.close_btn.setEnabled(connected)
        self.send_btn.setEnabled(connected)
        self.timed_check.setEnabled(connected)
        self.interval_spin.setEnabled(connected)

        if connected:
            self.status_chip.setText("● 已连接")
            self.status_chip.setProperty("state", "on")
            self.status_chip.setToolTip(self._connection_desc)
        else:
            self.status_chip.setText("● 未连接")
            self.status_chip.setProperty("state", "off")
            self.status_chip.setToolTip("串口未连接")
        self._restyle(self.status_chip)

        self._restyle(self.open_btn, "Secondary" if connected else "Primary")
        self._restyle(self.close_btn, "Primary" if connected else "Secondary")

    def _on_serial_error(self, message: str) -> None:
        if self._serial is None:
            return
        self._close_port()
        self.statusBar().showMessage("串口异常断开", 6000)
        QMessageBox.warning(self, "串口错误", f"串口通信异常，连接已断开。\n\n{message}")

    # --------------------------------------------------------------- 接收逻辑

    def _new_decoder(self):
        return codecs.getincrementaldecoder("gbk")(errors="replace")

    def _reset_decoder(self) -> None:
        self._decoder = self._new_decoder()

    def _on_rx_data(self, data: bytes) -> None:
        self._rx_count += len(data)
        self._update_counters()
        if self._paused:
            self._pause_buffer.extend(data)
            return
        self._render(data)

    def _render(self, data: bytes) -> None:
        hex_mode = self.rx_segment.current_index() == 1
        if hex_mode:
            text = "\n".join(
                " ".join(f"{byte:02X}" for byte in data[index:index + 16])
                for index in range(0, len(data), 16)
            )
        else:
            text = self._decoder.decode(data)
        if not text:
            return

        if self.overwrite_check.isChecked():
            self.rx_edit.setPlainText(text)
            self.rx_edit.moveCursor(QTextCursor.MoveOperation.End)
            return

        scrollbar = self.rx_edit.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 4

        cursor = self.rx_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if hex_mode and self.rx_edit.document().characterCount() > 1:
            text = "\n" + text
        cursor.insertText(text)

        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def _on_rx_mode_changed(self, index: int) -> None:
        self._reset_decoder()
        message = "接收区已切换为 HEX 模式" if index == 1 else "接收区已切换为文本模式（GBK）"
        self.statusBar().showMessage(message, 3000)

    def _on_pause_toggled(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.setText("继续接收" if paused else "暂停接收")
        if paused:
            self.statusBar().showMessage("已暂停接收，数据仍在后台读取并统计", 4000)
            return

        if self._pause_buffer:
            pending = bytes(self._pause_buffer)
            self._pause_buffer.clear()
            self._render(pending)
        self.statusBar().showMessage("已恢复接收", 3000)

    def clear_receive(self) -> None:
        self.rx_edit.clear()
        self._pause_buffer.clear()
        self._reset_decoder()
        self.statusBar().showMessage("接收区已清空", 3000)

    def save_received(self) -> None:
        content = self.rx_edit.toPlainText()
        if not content:
            self.statusBar().showMessage("接收区没有可保存的内容", 4000)
            return

        default_name = f"串口数据_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存接收数据",
            str(Path.home() / default_name),
            "文本文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".txt"

        try:
            Path(path).write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", f"无法写入文件：\n{exc}")
            return
        self.statusBar().showMessage(f"已保存到 {path}", 6000)

    # --------------------------------------------------------------- 发送逻辑

    def _on_send_mode_changed(self, index: int) -> None:
        message = "发送区已切换为 HEX 模式" if index == 1 else "发送区已切换为文本模式（GBK）"
        self.statusBar().showMessage(message, 3000)

    def _build_payload(self) -> bytes:
        text = self.send_edit.toPlainText()
        if self.send_segment.current_index() == 1:
            payload = parse_hex_text(text)
        else:
            try:
                payload = text.encode("gbk")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    "发送内容包含 GBK 无法编码的字符（例如 Emoji），请改用 HEX 模式。"
                ) from exc

        if self.newline_check.isChecked():
            payload += b"\n"
        return payload

    def send_data(self, from_timer: bool = False) -> None:
        if self._serial is None or not self._serial.is_open:
            if from_timer:
                self._stop_timed_send()
            self.statusBar().showMessage("串口未打开，无法发送数据", 4000)
            return

        try:
            payload = self._build_payload()
        except ValueError as exc:
            if from_timer:
                self._stop_timed_send()
                self.statusBar().showMessage(f"定时发送已停止：{exc}", 8000)
            else:
                QMessageBox.warning(self, "发送失败", str(exc))
            return

        if not payload:
            if not from_timer:
                self.statusBar().showMessage("发送内容为空", 3000)
            return

        try:
            written = self._serial.write(payload)
        except (serial.SerialException, OSError) as exc:
            if from_timer:
                self._stop_timed_send()
            self.statusBar().showMessage(f"发送失败：{exc}", 6000)
            return

        self._tx_count += written if written else len(payload)
        self._update_counters()

    def _on_timed_tick(self) -> None:
        self.send_data(from_timer=True)

    def _on_timed_toggled(self, checked: bool) -> None:
        if checked:
            if self._serial is None or not self._serial.is_open:
                self.timed_check.blockSignals(True)
                self.timed_check.setChecked(False)
                self.timed_check.blockSignals(False)
                self.statusBar().showMessage("请先打开串口，再启用定时发送", 4000)
                return
            self._send_timer.start(self.interval_spin.value())
            self.statusBar().showMessage(
                f"定时发送已启动，间隔 {self.interval_spin.value()} ms", 4000
            )
        else:
            self._send_timer.stop()
            self.statusBar().showMessage("定时发送已停止", 3000)

    def _on_interval_changed(self, value: int) -> None:
        if self._send_timer.isActive():
            self._send_timer.start(value)

    def _stop_timed_send(self) -> None:
        self._send_timer.stop()
        if self.timed_check.isChecked():
            self.timed_check.blockSignals(True)
            self.timed_check.setChecked(False)
            self.timed_check.blockSignals(False)

    def _update_counters(self) -> None:
        self.rx_stat.setText(f"已接收 {self._rx_count:,} 字节")
        self.tx_stat.setText(f"已发送 {self._tx_count:,} 字节")

    # ------------------------------------------------------------------ 关闭

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._close_port()
        super().closeEvent(event)


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("串口助手")
    app.setApplicationDisplayName("串口助手")
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"])
    font.setPointSize(10)
    app.setFont(font)

    app.setStyleSheet(build_stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
