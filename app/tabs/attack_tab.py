"""自動攻擊分頁（前景版）。

固定或隨機間隔，每次對遊戲送出 X 下指定按鍵。

★ 只在遊戲是前景時送鍵（新楓之谷只讀鍵盤硬體狀態、不理背景視窗訊息；背景送法
  全部無效，見 memory background-key-input-dead-end）。切到別的視窗會**自動暫停**，
  切回遊戲自動繼續 —— 這樣絕不會把按鍵打進使用者正在用的程式。

⛔ 做不到「真背景」：那需要注入遊戲行程騙過反外掛，本工具不做。要邊掛邊用電腦，
  把遊戲＋工具放到另一台機器或虛擬機當前景跑。
"""
from __future__ import annotations

import random
import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from app import theme
from app.config import config
from app.core import keyinput
from app.tabs.base_tab import GROUP_AUTO, BaseTab, find_game


class AttackWorker(QThread):
    """背景計時執行緒：到點就送一輪按鍵。送鍵前一定先確認前景是遊戲。"""

    tick = Signal(int)          # 累計送出次數
    paused = Signal(bool)       # True＝暫停（遊戲不在前景）

    def __init__(self, pid: int, scan: int, extended: bool, interval_fn,
                 count: int, gap_s: float, hold_s: float) -> None:
        super().__init__()
        self._pid = pid
        self._scan = scan
        self._ext = extended
        self._interval_fn = interval_fn
        self._count = count
        self._gap = gap_s
        self._hold = hold_s
        self._stop = threading.Event()
        self._total = 0
        self._is_paused = False

    def stop(self) -> None:
        self._stop.set()

    def _wait(self, secs: float) -> bool:
        """可中斷的等待。回 False＝收到停止。"""
        return not self._stop.wait(secs)

    def _ensure_foreground(self) -> bool:
        """擋在每一次送鍵前面：不是遊戲在前景就等，等到回來或停止。
        回 False＝停止了。"""
        while keyinput.foreground_pid() != self._pid:
            if not self._is_paused:
                self._is_paused = True
                self.paused.emit(True)
            if self._stop.wait(0.1):
                return False
        if self._is_paused:
            self._is_paused = False
            self.paused.emit(False)
        return True

    def run(self) -> None:
        while not self._stop.is_set():
            if not self._wait(self._interval_fn()):
                break
            for i in range(self._count):
                if not self._ensure_foreground():
                    return
                keyinput.tap(self._scan, self._ext, self._hold)
                self._total += 1
                self.tick.emit(self._total)
                if i < self._count - 1 and not self._wait(self._gap):
                    return


class AttackTab(BaseTab):
    TAB_TITLE = "自動攻擊"
    GROUP = GROUP_AUTO
    ORDER = 10

    def build_ui(self) -> None:
        self._pid: int | None = None
        self._worker: AttackWorker | None = None
        self._capturing = False
        # 目前設定的按鍵：{vk, scan, extended, name}
        self._key = config.get("attack.key") or {
            "vk": 0xC0, "scan": 0x29, "extended": False, "name": "`"}

        self.setFocusPolicy(Qt.StrongFocus)
        root = QVBoxLayout(self)

        root.addWidget(self._build_settings_group())
        root.addWidget(self._build_run_group())
        root.addStretch(1)

        # 背景即時自動偵測遊戲：不必按鈕、不佔畫面，pid 隨遊戲開關自動跟上。
        self._detect()
        self._detect_timer = QTimer(self)
        self._detect_timer.setInterval(1500)
        self._detect_timer.timeout.connect(self._detect)
        self._detect_timer.start()
        self._sync_key_label()

    # ------------------------------------------------------------------
    def _detect(self) -> None:
        if self._worker is not None:
            return                     # 執行中不重抓，worker 已握著開始時的 pid
        g = find_game()
        self._pid = g.pid if g else None

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("① 設定")
        lay = QVBoxLayout(box)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("按鍵："))
        self.key_label = QLabel()
        self.key_label.setStyleSheet(
            f"font-weight: 600; color: {theme.ACCENT}; padding: 0 6px;")
        key_row.addWidget(self.key_label)
        self.capture_btn = QPushButton("設定按鍵")
        self.capture_btn.setCheckable(True)
        self.capture_btn.clicked.connect(self._toggle_capture)
        key_row.addWidget(self.capture_btn)
        key_row.addStretch(1)
        lay.addLayout(key_row)

        # 間隔：固定 或 隨機範圍
        self.mode_group = QButtonGroup(self)
        fixed_row = QHBoxLayout()
        self.fixed_radio = QRadioButton("固定間隔")
        self.mode_group.addButton(self.fixed_radio, 0)
        self.fixed_spin = QDoubleSpinBox()
        self.fixed_spin.setRange(0.1, 600.0)
        self.fixed_spin.setSingleStep(0.5)
        self.fixed_spin.setDecimals(1)
        self.fixed_spin.setSuffix(" 秒")
        self.fixed_spin.setValue(float(config.get("attack.fixed_s", 1.0)))
        fixed_row.addWidget(self.fixed_radio)
        fixed_row.addWidget(self.fixed_spin)
        fixed_row.addStretch(1)
        lay.addLayout(fixed_row)

        rand_row = QHBoxLayout()
        self.rand_radio = QRadioButton("隨機間隔")
        self.mode_group.addButton(self.rand_radio, 1)
        self.rand_min = QDoubleSpinBox()
        self.rand_max = QDoubleSpinBox()
        for sp, key, dv in ((self.rand_min, "attack.rand_min_s", 3.0),
                            (self.rand_max, "attack.rand_max_s", 5.0)):
            sp.setRange(0.1, 600.0)
            sp.setSingleStep(0.5)
            sp.setDecimals(1)
            sp.setSuffix(" 秒")
            sp.setValue(float(config.get(key, dv)))
        rand_row.addWidget(self.rand_radio)
        rand_row.addWidget(self.rand_min)
        rand_row.addWidget(QLabel("～"))
        rand_row.addWidget(self.rand_max)
        rand_row.addWidget(QLabel("之間隨機"))
        rand_row.addStretch(1)
        lay.addLayout(rand_row)
        (self.rand_radio if config.get("attack.mode") == "random"
         else self.fixed_radio).setChecked(True)

        # 每輪按幾下、連按間隔
        burst_row = QHBoxLayout()
        burst_row.addWidget(QLabel("每次按"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 99)
        self.count_spin.setSuffix(" 下")
        self.count_spin.setValue(int(config.get("attack.count", 1)))
        burst_row.addWidget(self.count_spin)
        burst_row.addWidget(QLabel("　連按間隔"))
        self.gap_spin = QSpinBox()
        self.gap_spin.setRange(10, 2000)
        self.gap_spin.setSingleStep(10)
        self.gap_spin.setSuffix(" 毫秒")
        self.gap_spin.setValue(int(config.get("attack.gap_ms", 80)))
        self.gap_spin.setToolTip("同一輪裡兩下之間的間隔。太短遊戲會把連按當成一下。")
        burst_row.addWidget(self.gap_spin)
        burst_row.addStretch(1)
        lay.addLayout(burst_row)
        return box

    def _build_run_group(self) -> QGroupBox:
        box = QGroupBox("② 執行")
        lay = QVBoxLayout(box)
        self.run_btn = QPushButton("開始自動攻擊")
        self.run_btn.setProperty("primary", True)
        self.run_btn.setMinimumHeight(38)
        self.run_btn.clicked.connect(self._toggle_run)
        lay.addWidget(self.run_btn)
        self.status = QLabel("就緒")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.TEXT_MUT};")
        lay.addWidget(self.status)
        return box

    # -- 按鍵擷取 -------------------------------------------------------
    def _toggle_capture(self) -> None:
        if self.capture_btn.isChecked():
            self._capturing = True
            self.capture_btn.setText("請按一個鍵…（Esc 取消）")
            self.setFocus()
            self.grabKeyboard()
        else:
            self._end_capture()

    def _end_capture(self) -> None:
        self._capturing = False
        self.releaseKeyboard()
        self.capture_btn.setChecked(False)
        self.capture_btn.setText("設定按鍵")

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名慣例)
        if not self._capturing:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape:
            self._end_capture()
            event.accept()
            return
        vk = event.nativeVirtualKey()
        if vk:
            scan, ext = keyinput.scancode_for(vk)
            if scan:
                self._key = {"vk": int(vk), "scan": scan, "extended": ext,
                             "name": self._key_name(event)}
                config.set("attack.key", self._key)
                config.save()
                self._sync_key_label()
        self._end_capture()
        event.accept()

    @staticmethod
    def _key_name(event) -> str:
        t = event.text()
        if t and t.isprintable() and t.strip():
            return t.upper() if len(t) == 1 else t
        name = QKeySequence(event.key()).toString()
        return name or f"VK 0x{event.nativeVirtualKey():X}"

    def _sync_key_label(self) -> None:
        self.key_label.setText(self._key.get("name", "?"))

    # -- 執行 ----------------------------------------------------------
    def _interval_fn(self):
        if self.rand_radio.isChecked():
            lo, hi = sorted((self.rand_min.value(), self.rand_max.value()))
            return lambda: random.uniform(lo, hi)
        v = self.fixed_spin.value()
        return lambda: v

    def _save_settings(self) -> None:
        config.set("attack.mode", "random" if self.rand_radio.isChecked() else "fixed")
        config.set("attack.fixed_s", self.fixed_spin.value())
        config.set("attack.rand_min_s", self.rand_min.value())
        config.set("attack.rand_max_s", self.rand_max.value())
        config.set("attack.count", self.count_spin.value())
        config.set("attack.gap_ms", self.gap_spin.value())
        config.save()

    def _toggle_run(self) -> None:
        if self._worker is not None:
            self._stop_run()
            return
        if not self._key.get("scan"):
            QMessageBox.information(self, "提示", "請先設定按鍵。")
            return
        pid = self._pid                # 背景計時器已即時抓好
        if pid is None:
            QMessageBox.information(
                self, "提示", "沒有找到遊戲視窗，請先開遊戲。")
            return
        self._save_settings()
        self._worker = AttackWorker(
            pid, self._key["scan"], self._key.get("extended", False),
            self._interval_fn(), self.count_spin.value(),
            self.gap_spin.value() / 1000.0, 0.04)
        self._worker.tick.connect(self._on_tick)
        self._worker.paused.connect(self._on_paused)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
        self._set_running(True)
        self.status.setText(
            f"執行中：送「{self._key['name']}」到 PID {pid}。"
            "　切到別的視窗會自動暫停。")
        self.status.setStyleSheet(f"color: {theme.OK};")

    def _stop_run(self) -> None:
        w = self._worker
        if w is not None:
            w.stop()
            w.wait(2000)

    def _on_tick(self, total: int) -> None:
        self.status.setText(f"執行中：已送出 {total} 次。")
        self.status.setStyleSheet(f"color: {theme.OK};")

    def _on_paused(self, paused: bool) -> None:
        if paused:
            self.status.setText("已暫停：遊戲不在前景。切回遊戲視窗就自動繼續。")
            self.status.setStyleSheet(f"color: {theme.WARN};")
        else:
            self.status.setText("已切回遊戲，繼續執行。")
            self.status.setStyleSheet(f"color: {theme.OK};")

    def _on_finished(self) -> None:
        self._worker = None
        self._set_running(False)
        self.status.setText("已停止。")
        self.status.setStyleSheet(f"color: {theme.TEXT_MUT};")

    def _set_running(self, running: bool) -> None:
        self.run_btn.setText("停止" if running else "開始自動攻擊")
        self.run_btn.setProperty("primary", not running)
        self.run_btn.setProperty("danger", running)
        # 重新套用樣式（動態屬性改了要 unpolish/polish 才生效）
        self.run_btn.style().unpolish(self.run_btn)
        self.run_btn.style().polish(self.run_btn)
        for wgt in (self.capture_btn,
                    self.fixed_radio, self.fixed_spin, self.rand_radio,
                    self.rand_min, self.rand_max, self.count_spin, self.gap_spin):
            wgt.setEnabled(not running)

    def on_close(self) -> None:
        self._detect_timer.stop()
        self._stop_run()
