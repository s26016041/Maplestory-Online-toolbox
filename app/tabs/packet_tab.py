"""封包擷取分頁。

旁聽網卡，把「選定的遊戲行程」送出／收到的 TCP 內容即時列出來：方向、遠端、
長度、亂度（判斷加密）、內容。

操作流程：
  ① 在清單選遊戲程序 → 按「選定並開始擷取」。
  ② 回遊戲做動作（登入、換頻、移動…）。
  ③ 下方即時列出封包；點一列看完整 hex。
  ④ 按「停止擷取」（關閉程式也會自動停）。

★ 被動旁聽（見 app/core/sniffer.py）：不注入、不掛鉤、不碰遊戲行程。
  有裝 Npcap 就用 Npcap（雙向）；沒裝退回 raw socket（要系統管理員、多半只有送出）。
"""
from __future__ import annotations

import datetime
import pathlib

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app import theme
from app.core import admin, sniffer
from app.core import window as win
from app.core.pcap import Pcap
from app.tabs.base_tab import GAME_TITLE_KEYWORD, GROUP_DEV, BaseTab, game_first

MAX_ROWS = 2000  # 封包表最多保留筆數

DIR_ALL, DIR_OUT, DIR_IN = "all", "out", "in"


class PacketTab(BaseTab):
    TAB_TITLE = "封包擷取"
    GROUP = GROUP_DEV
    ORDER = 60

    def build_ui(self) -> None:
        self._cap: sniffer.Sniffer | None = None
        self._packets: list[sniffer.Packet] = []
        self._windows: list[win.WindowInfo] = []

        root = QVBoxLayout(self)

        hint = QLabel(
            "旁聽網卡，列出選定遊戲程序送出／收到的封包（不注入、不碰遊戲行程）。\n"
            "① 選遊戲程序 → 開始擷取 → ② 回遊戲做動作 → ③ 下方看方向、長度、亂度與內容。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ⚠ 三個區塊各自有最小高度，直接疊在 QVBoxLayout 裡、加起來超過視窗高度時
        #   Qt 不會縮，而是把最下面那段擠到看不見。用垂直分割器：空間不夠時三段
        #   一起縮，也可以自己拖拉分配。
        split = QSplitter(Qt.Vertical)
        split.addWidget(self._build_process_group())
        split.addWidget(self._build_packet_group())
        split.addWidget(self._build_detail_group())
        split.setStretchFactor(0, 0)      # 程序清單：不搶空間
        split.setStretchFactor(1, 3)      # 封包表：多出來的空間都給它
        split.setStretchFactor(2, 1)
        split.setChildrenCollapsible(False)
        split.setSizes([150, 300, 170])
        root.addWidget(split, stretch=1)

        self.status = QLabel("就緒")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.TEXT_MUT};")
        root.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll)

        self.refresh_windows()
        self._update_admin_note()

    # ------------------------------------------------------------------
    def _build_process_group(self) -> QGroupBox:
        box = QGroupBox("① 選定遊戲程序")
        lay = QVBoxLayout(box)

        row = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("依視窗標題關鍵字過濾（可留空）")
        self.filter_edit.setText(GAME_TITLE_KEYWORD)
        self.filter_edit.returnPressed.connect(self.refresh_windows)
        refresh_btn = QPushButton("重新整理")
        refresh_btn.clicked.connect(self.refresh_windows)
        row.addWidget(self.filter_edit, 1)
        row.addWidget(refresh_btn)

        self.proc_table = QTableWidget(0, 3)
        self.proc_table.setHorizontalHeaderLabels(["PID", "視窗標題", "類別"])
        self.proc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.proc_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.proc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.proc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        # ⚠ 最小值別開太大：視窗一矮，三段的最小高度加起來就超過可用高度。
        self.proc_table.setMinimumHeight(72)
        self.proc_table.setMaximumHeight(140)

        # ★ 按鈕跟過濾框擠同一列：視窗高度固定 700，這一段每省一列，
        #   下面的封包表就多看得到一筆。
        btn_row = row
        self.start_btn = QPushButton("選定並開始擷取")
        self.start_btn.setProperty("primary", True)
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn = QPushButton("停止擷取")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_capture)
        self.clear_btn = QPushButton("清空列表")
        self.clear_btn.clicked.connect(self.clear_packets)
        self.admin_btn = QPushButton("以系統管理員身分重新啟動")
        self.admin_btn.clicked.connect(self._relaunch_admin)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addWidget(self.admin_btn)
        lay.addLayout(row)
        lay.addWidget(self.proc_table)
        return box

    def _build_packet_group(self) -> QGroupBox:
        box = QGroupBox("② 封包（即時）")
        lay = QVBoxLayout(box)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("方向"))
        self.dir_combo = QComboBox()
        self.dir_combo.addItem("全部", DIR_ALL)
        self.dir_combo.addItem("只看送出", DIR_OUT)
        self.dir_combo.addItem("只看接收", DIR_IN)
        self.dir_combo.currentIndexChanged.connect(self._rebuild_table)
        ctrl.addWidget(self.dir_combo)
        ctrl.addWidget(QLabel("遠端"))
        self.remote_combo = QComboBox()
        self.remote_combo.setMinimumWidth(190)
        self.remote_combo.setToolTip(
            "遊戲同時會連好幾台伺服器（登入／頻道／聊天…），可以只看其中一條連線。")
        self.remote_combo.addItem("全部連線", "")
        self.remote_combo.currentIndexChanged.connect(self._rebuild_table)
        ctrl.addWidget(self.remote_combo)
        self.fold_chk = QCheckBox("摺疊連續重複")
        self.fold_chk.setChecked(True)
        self.fold_chk.setToolTip(
            "連續、同方向同連線同長度的封包併成一列標「×N」，順序保留。\n"
            "（內容加密、每次 bytes 都不同，不能拿內容比。）")
        self.fold_chk.toggled.connect(self._rebuild_table)
        ctrl.addWidget(self.fold_chk)
        self.follow_chk = QCheckBox("自動捲到最新")
        self.follow_chk.setChecked(True)
        ctrl.addWidget(self.follow_chk)
        ctrl.addStretch(1)
        self.copy_btn = QPushButton("複製全部")
        self.copy_btn.setToolTip("把目前篩選後的整份記錄複製到剪貼簿。")
        self.copy_btn.clicked.connect(self.copy_report)
        self.save_btn = QPushButton("匯出成檔案")
        self.save_btn.setToolTip("存成純文字檔（captures 資料夾），路徑顯示在下方狀態列。")
        self.save_btn.clicked.connect(self.save_report)
        ctrl.addWidget(self.copy_btn)
        ctrl.addWidget(self.save_btn)
        lay.addLayout(ctrl)

        self.pkt_table = QTableWidget(0, 7)
        self.pkt_table.setHorizontalHeaderLabels(
            ["#", "時間", "方向", "遠端", "長度", "亂度", "內容預覽"])
        self.pkt_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pkt_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.pkt_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pkt_table.verticalHeader().setVisible(False)
        # 欄寬手動給、最後一欄補滿 —— 不用 ResizeToContents（高頻改表時每次都重量整欄）。
        for col, w in enumerate((64, 112, 78, 170, 64, 60)):
            self.pkt_table.setColumnWidth(col, w)
        self.pkt_table.horizontalHeader().setStretchLastSection(True)
        self.pkt_table.setMinimumHeight(120)
        self.pkt_table.itemSelectionChanged.connect(self._show_detail)
        lay.addWidget(self.pkt_table)
        return box

    def _build_detail_group(self) -> QGroupBox:
        box = QGroupBox("③ 選取封包的內容（hex）")
        lay = QVBoxLayout(box)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setStyleSheet("font-family: Consolas, monospace;")
        self.detail.setMinimumHeight(90)
        lay.addWidget(self.detail)
        return box

    # ------------------------------------------------------------------
    def _update_admin_note(self) -> None:
        # 有 Npcap 就不需要系統管理員；只有走 raw socket 那條退路才要。
        need = not admin.is_admin() and Pcap.load() is None
        self.admin_btn.setVisible(need)
        if need:
            self._set_status(
                "⚠ 沒裝 Npcap 且目前不是系統管理員 —— 請按右邊"
                "「以系統管理員身分重新啟動」，或安裝 Npcap。", theme.WARN)

    def _relaunch_admin(self) -> None:
        if admin.relaunch_as_admin():
            self.window().close()
        else:
            self.status.setText("沒有取得系統管理員權限（UAC 被取消）。")

    def refresh_windows(self) -> None:
        keyword = self.filter_edit.text().strip() or None
        self._windows, games = game_first(
            win.enumerate_windows(title_contains=keyword))
        self.proc_table.setRowCount(len(self._windows))
        for r, w in enumerate(self._windows):
            self.proc_table.setItem(r, 0, QTableWidgetItem(str(w.pid)))
            self.proc_table.setItem(r, 1, QTableWidgetItem(w.title))
            self.proc_table.setItem(r, 2, QTableWidgetItem(w.class_name))
        if games == 1 or len(self._windows) == 1:
            self.proc_table.selectRow(0)       # 只有一台遊戲 → 直接幫他選好
        if not self._cap and self.admin_btn.isHidden():
            self._set_status(f"找到 {len(self._windows)} 個視窗")

    def _set_status(self, text: str, color: str | None = None) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color or theme.TEXT_MUT};")

    def _selected_window(self) -> win.WindowInfo | None:
        rows = self.proc_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "請先在清單選一個遊戲視窗。")
            return None
        return self._windows[rows[0].row()]

    def _set_enabled_capture(self, capturing: bool) -> None:
        self.start_btn.setEnabled(not capturing)
        self.stop_btn.setEnabled(capturing)
        self.proc_table.setEnabled(not capturing)
        self.filter_edit.setEnabled(not capturing)

    # ------------------------------------------------------------------
    def start_capture(self) -> None:
        w = self._selected_window()
        if not w:
            return
        cap = sniffer.Sniffer(w.pid)
        try:
            cap.start()
        except sniffer.SnifferError as exc:
            QMessageBox.critical(self, "開始擷取失敗", str(exc))
            return
        self._cap = cap
        self._set_enabled_capture(True)
        self._timer.start()
        self._set_status(
            f"擷取中（{cap.backend}）：PID {w.pid} — {w.title}　｜　"
            f"旁聽網卡 {', '.join(cap.bound)}　｜　目前 {len(cap.connections())} 條連線\n"
            + ("現在回遊戲做動作；封包會即時出現在下方。" if cap.backend == "Npcap" else
               "⚠ 沒裝 Npcap，改用 raw socket：Windows 防火牆會擋掉接收方向，"
               "多半只看得到送出。裝 Npcap（或 Wireshark）就兩個方向都有。"),
            theme.OK if cap.backend == "Npcap" else theme.WARN)

    def stop_capture(self) -> None:
        self._timer.stop()
        if self._cap:
            self._drain()
            self._cap.stop()
            note = (f"，濾掉重傳 {self._cap.retransmits} 段"
                    if self._cap.retransmits else "")
            self._cap = None
            self._set_status(f"已停止擷取（共 {len(self._packets)} 筆{note}）。")
        self._set_enabled_capture(False)

    def clear_packets(self) -> None:
        self._packets.clear()
        self.pkt_table.setRowCount(0)
        self.detail.clear()
        self._sync_remotes()

    # ------------------------------------------------------------------
    def _drain(self) -> bool:
        """把擷取器積的封包收進來。有新東西回 True。"""
        new = self._cap.read_new() if self._cap else []
        if not new:
            return False
        self._packets.extend(new)
        if len(self._packets) > MAX_ROWS:      # 超過上限裁掉最舊的
            self._packets = self._packets[-MAX_ROWS:]
        return True

    def _poll(self) -> None:
        cap = self._cap
        if cap is None:
            return
        if cap.error:
            msg = cap.error
            self.stop_capture()
            self._set_status(f"擷取中斷，已停止：{msg}", theme.BAD)
            return
        if self._drain():
            self._sync_remotes()
            self._rebuild_table()

    def _sync_remotes(self) -> None:
        """「遠端」下拉只增不減地跟上出現過的伺服器；不動使用者目前的選擇。"""
        have = {self.remote_combo.itemData(i)
                for i in range(self.remote_combo.count())}
        seen = {p.remote for p in self._packets}
        if not self._packets and self.remote_combo.count() > 1:
            self.remote_combo.blockSignals(True)
            while self.remote_combo.count() > 1:
                self.remote_combo.removeItem(1)
            self.remote_combo.setCurrentIndex(0)
            self.remote_combo.blockSignals(False)
            return
        for r in sorted(seen - have):
            self.remote_combo.addItem(r, r)

    # ---- 篩選＋摺疊 -------------------------------------------------------
    def _visible(self) -> list[sniffer.Packet]:
        d = self.dir_combo.currentData()
        remote = self.remote_combo.currentData()
        out = self._packets
        if d == DIR_OUT:
            out = [p for p in out if p.outgoing]
        elif d == DIR_IN:
            out = [p for p in out if not p.outgoing]
        if remote:
            out = [p for p in out if p.remote == remote]
        return out

    @staticmethod
    def _fold_key(pkt: sniffer.Packet) -> tuple:
        """兩筆算不算「同一種」：方向、連線、長度都相同就算。

        ⚠ 不能拿內容比 —— 內容加密，同一個動作每次的 bytes 都不一樣。
        """
        return (pkt.outgoing, pkt.conn, pkt.length)

    def _runs(self) -> list[list[sniffer.Packet]]:
        """把**連續**的同種封包併成一段，順序保留。"""
        pkts = self._visible()
        if not self.fold_chk.isChecked():
            return [[p] for p in pkts]
        out: list[list[sniffer.Packet]] = []
        for p in pkts:
            if out and self._fold_key(out[-1][0]) == self._fold_key(p):
                out[-1].append(p)
            else:
                out.append([p])
        return out

    def _rebuild_table(self) -> None:
        # 整表重畫：摺疊要看前一筆，沒辦法只補最後一列。先記住選取的封包，畫完選回去。
        keep = self._selected_seq()
        runs = self._runs()
        t = self.pkt_table
        t.blockSignals(True)
        t.setUpdatesEnabled(False)
        t.setRowCount(len(runs))
        sel_row = -1
        for r, run in enumerate(runs):
            self._fill_row(r, run)
            if keep is not None and run[0].seq <= keep <= run[-1].seq:
                sel_row = r
        if sel_row >= 0:
            t.selectRow(sel_row)
        t.setUpdatesEnabled(True)
        t.blockSignals(False)
        if self.follow_chk.isChecked() and sel_row < 0:
            t.scrollToBottom()

    def _fill_row(self, r: int, run: list[sniffer.Packet]) -> None:
        pkt = run[0]
        color = QColor(theme.SEND if pkt.outgoing else theme.RECV)
        seq = str(pkt.seq) if len(run) == 1 else f"{pkt.seq} ×{len(run)}"
        cells = (
            seq,
            datetime.datetime.fromtimestamp(pkt.ts).strftime("%H:%M:%S.%f")[:-3],
            "送出 →" if pkt.outgoing else "← 接收",
            pkt.remote,
            str(pkt.length),
            f"{pkt.entropy:.2f}",
            pkt.data[:32].hex(" "),
        )
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            if col == 0:
                it.setData(Qt.UserRole, pkt.seq)
            if col == 2:
                it.setForeground(color)
            if col in (4, 5):
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.pkt_table.setItem(r, col, it)

    def _selected_seq(self) -> int | None:
        rows = self.pkt_table.selectionModel().selectedRows()
        if not rows:
            return None
        item0 = self.pkt_table.item(rows[0].row(), 0)
        return None if item0 is None else item0.data(Qt.UserRole)

    # ---- 匯出 -------------------------------------------------------------
    def _report(self) -> str:
        runs = self._runs()
        head = [
            f"封包擷取記錄　{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
            f"共 {sum(len(r) for r in runs)} 筆，{len(runs)} 個步驟"
            "（連續且方向+連線+長度相同的算同一步）",
            "",
        ]
        body = []
        for i, run in enumerate(runs, 1):
            p = run[0]
            rng = (f"#{p.seq}" if len(run) == 1 else f"#{p.seq}~{run[-1].seq}")
            t = datetime.datetime.fromtimestamp(p.ts).strftime("%H:%M:%S.%f")[:-3]
            body.append(
                f"── 步驟 {i}　{rng}　×{len(run)}　{t}　"
                f"{'送出' if p.outgoing else '接收'}　{p.remote}　"
                f"長度 {p.length}　亂度 {p.entropy:.2f}/8")
            body.append(p.hexdump(maxlen=256))
            body.append("")
        return "\n".join(head + body)

    def copy_report(self) -> None:
        if not self._packets:
            self._set_status("還沒擷取到任何封包。")
            return
        text = self._report()
        QGuiApplication.clipboard().setText(text)
        self._set_status(f"已複製整份記錄到剪貼簿（{len(text)} 個字）。")

    def save_report(self) -> None:
        if not self._packets:
            self._set_status("還沒擷取到任何封包。")
            return
        folder = pathlib.Path.cwd() / "captures"
        path = folder / f"封包記錄_{datetime.datetime.now():%m%d_%H%M%S}.txt"
        try:
            folder.mkdir(exist_ok=True)
            path.write_text(self._report(), encoding="utf-8")
        except OSError as exc:
            self._set_status(f"存檔失敗：{exc}", theme.BAD)
            return
        self._set_status(f"已存檔：{path}")

    def _show_detail(self) -> None:
        seq = self._selected_seq()
        pkt = next((p for p in self._packets if p.seq == seq), None)
        if not pkt:
            return
        verdict = "疑似加密/壓縮" if pkt.entropy > 7.5 else "疑似明文/輕度混淆"
        if pkt.length < 64:
            verdict += "（內容太短，亂度僅供參考）"
        t = datetime.datetime.fromtimestamp(pkt.ts).strftime("%H:%M:%S.%f")[:-3]
        self.detail.setPlainText(
            f"#{pkt.seq}　{t}　{'送出' if pkt.outgoing else '接收'}　"
            f"本機 :{pkt.conn[1]} {'→' if pkt.outgoing else '←'} {pkt.remote}\n"
            f"長度 {pkt.length}　TCP seq {pkt.tcp_seq}　"
            f"亂度 {pkt.entropy:.2f}/8 → {verdict}\n\n"
            f"{pkt.hexdump()}"
        )

    # ------------------------------------------------------------------
    def on_close(self) -> None:
        self._timer.stop()
        if self._cap:
            self._cap.stop()
            self._cap = None
