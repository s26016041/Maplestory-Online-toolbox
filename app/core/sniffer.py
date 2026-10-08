"""被動式封包擷取：只聽自己網卡上的流量，依遊戲行程的 TCP 連線過濾。

原理
----
旁聽網卡上進出的每一個 IP 封包（跟 Wireshark 一樣），再用
`netconn.connections(pid)` 查出遊戲行程的連線（本機埠 ↔ 伺服器 IP:埠），
只留下屬於它的。旁聽有兩條路，start() 自動挑：

1. **Npcap**（app/core/pcap.py，有裝 Wireshark 就有）：NDIS 層驅動，送出／接收都收得到。
2. **raw socket + SIO_RCVALL**（沒裝 Npcap 的退路）：不需要任何驅動，但
   ⚠ 實測 Windows 防火牆會擋掉**接收方向**，只看得到遊戲送出的；還要系統管理員。

★ **完全不碰遊戲行程**：不注入、不掛鉤、不改它的記憶體 —— 遊戲看不到這支工具，
  遊戲當掉也不會是這裡造成的。代價是拿到的是**線上的原始 bytes**：
  - 楓之谷的封包內容有加密，這裡看到的是密文（亂度接近 8）。
  - TCP 是串流：一個 TCP 段 ≠ 一個遊戲封包，可能半包、也可能好幾包黏在一起。
    這裡照 TCP 段逐筆列，不猜遊戲封包的邊界。

限制
----
- 只看 IPv4 / TCP。
- raw socket 那條路要**系統管理員**權限，沒有的話 start() 會丟 SnifferError。
"""
from __future__ import annotations

import math
import select
import socket
import struct
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass

from app.core import netconn
from app.core.pcap import Pcap, PcapError

CAP = 4096                # 每筆最多留幾 bytes 內容（長度欄照樣記實際長度）
_REFRESH_SECS = 0.5       # 多久重查一次遊戲的連線表
_PENDING_SECS = 3.0       # 還認不出歸屬的封包暫留多久
_PENDING_MAX = 4000
_KEY_LINGER_SECS = 5.0    # 連線從表上消失後，還繼續認它多久（收尾的封包）
_QUEUE_MAX = 20000        # GUI 來不及收時最多積幾筆，超過丟最舊的

_SIO_RCVALL = getattr(socket, "SIO_RCVALL", 0x98000001)
_RCVALL_ON = getattr(socket, "RCVALL_ON", 1)
_RCVALL_OFF = getattr(socket, "RCVALL_OFF", 0)

ConnKey = tuple[str, int, str, int]     # (本機 IP, 本機埠, 遠端 IP, 遠端埠)


class SnifferError(RuntimeError):
    pass


def entropy(data: bytes) -> float:
    """Shannon 亂度（0~8）。越接近 8 越像加密/壓縮。"""
    if not data:
        return 0.0
    c = Counter(data)
    n = len(data)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


@dataclass
class Packet:
    seq: int              # 本次擷取的流水號
    ts: float             # time.time()
    outgoing: bool        # True＝遊戲送出，False＝遊戲收到
    conn: ConnKey
    length: int           # TCP 段的實際內容長度
    data: bytes           # 內容（截斷到 CAP）
    tcp_seq: int

    @property
    def remote(self) -> str:
        return f"{self.conn[2]}:{self.conn[3]}"

    @property
    def entropy(self) -> float:
        return entropy(self.data)

    def hexdump(self, width: int = 16, maxlen: int = 1024) -> str:
        lines = []
        d = self.data[:maxlen]
        for i in range(0, len(d), width):
            chunk = d[i:i + width]
            h = " ".join(f"{b:02X}" for b in chunk)
            t = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{i:04X}  {h:<{width * 3}} {t}")
        if self.length > len(d):
            lines.append(f"…（共 {self.length} bytes，只顯示前 {len(d)}）")
        return "\n".join(lines)


def local_ipv4() -> list[str]:
    """這台電腦的 IPv4 位址（不含 127.x —— raw socket 在 loopback 上聽不到東西）。"""
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        ips = []
    return [ip for ip in ips if not ip.startswith("127.")]


def parse_tcp(raw: bytes):
    """IPv4 封包 → (src, sport, dst, dport, tcp_seq, payload)；不是 TCP 或壞包回 None。"""
    if len(raw) < 40 or raw[0] >> 4 != 4 or raw[9] != 6:
        return None
    ihl = (raw[0] & 0x0F) * 4
    if ihl < 20 or len(raw) < ihl + 20:
        return None
    # 分片的後續片段沒有 TCP 標頭，解下去是垃圾（遊戲流量實務上不會分片）。
    if struct.unpack_from("!H", raw, 6)[0] & 0x1FFF:
        return None
    total = struct.unpack_from("!H", raw, 2)[0]
    # ⚠ 送出方向開了 LSO（網卡代切大包）時 total_length 會是 0，長度以實收為準。
    end = total if ihl + 20 <= total <= len(raw) else len(raw)
    sport, dport, tseq = struct.unpack_from("!HHI", raw, ihl)
    doff = (raw[ihl + 12] >> 4) * 4
    if doff < 20 or ihl + doff > end:
        return None
    src = socket.inet_ntoa(raw[12:16])
    dst = socket.inet_ntoa(raw[16:20])
    return src, sport, dst, dport, tseq, raw[ihl + doff:end]


class Sniffer:
    """針對單一 PID 的封包擷取器。start() 之後在背景執行緒收，GUI 用 read_new() 取。"""

    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._socks: list[socket.socket] = []
        self._caps: list = []                      # Npcap 開著的網卡
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        # RLock：Npcap 一張網卡一條執行緒，_on_raw／_refresh 整段要互斥，
        # 裡面的 _emit 又會再拿一次。
        self._lock = threading.RLock()
        self._next_refresh = 0.0
        self._queue: deque[Packet] = deque(maxlen=_QUEUE_MAX)
        self._seq = 0
        self._keys: dict[ConnKey, float] = {}      # 已知連線 → 最後一次在表上看到的時刻
        self._pending: deque = deque(maxlen=_PENDING_MAX)
        self._next: dict[tuple[ConnKey, bool], int] = {}   # 各方向下一個預期的 tcp seq
        self.error: str | None = None      # 背景執行緒死掉的原因
        self.retransmits = 0               # 濾掉的重傳段數
        self.bound: list[str] = []         # 實際有在聽的本機 IP
        self.backend = ""                  # "Npcap" 或 "raw socket"

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def active(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def connections(self) -> list[ConnKey]:
        with self._lock:
            return list(self._keys)

    # ------------------------------------------------------------------
    def start(self) -> None:
        conns = netconn.connections(self._pid) or []
        ips = local_ipv4()
        for c in conns:
            if c.local_ip not in ips and not c.local_ip.startswith("127."):
                ips.append(c.local_ip)
        if not ips:
            raise SnifferError("找不到可用的本機 IPv4 位址（沒有連上網路？）。")
        if not self._start_pcap(ips):
            self._start_raw(ips)
        now = time.monotonic()
        for c in conns:
            self._keys[c.key] = now
        self._stop.clear()
        for t in self._threads:
            t.start()

    def _start_pcap(self, ips: list[str]) -> bool:
        """有 Npcap 就用它。任何一步不行都回 False 讓 start() 退回 raw socket。"""
        pcap = Pcap.load()
        if pcap is None:
            return False
        try:
            devs = pcap.devices()
        except PcapError:
            return False
        for name, _desc, dev_ips in devs:
            hit = [ip for ip in dev_ips if ip in ips]
            if not hit:
                continue
            try:
                cap = pcap.open(name)
            except PcapError:
                continue
            self._caps.append(cap)
            self.bound.extend(hit)
            self._threads.append(threading.Thread(
                target=self._run_pcap, args=(cap,), name="sniffer-pcap",
                daemon=True))
        if not self._caps:
            return False
        self.backend = "Npcap"
        return True

    def _start_raw(self, ips: list[str]) -> None:
        errors = []
        for ip in ips:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            except PermissionError as exc:
                raise SnifferError(
                    "開 raw socket 被拒絕 —— 沒裝 Npcap 時，封包擷取需要系統管理員權限。"
                ) from exc
            except OSError as exc:
                raise SnifferError(f"開 raw socket 失敗：{exc}") from exc
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                s.bind((ip, 0))
                s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
                s.ioctl(_SIO_RCVALL, _RCVALL_ON)
            except OSError as exc:
                s.close()
                errors.append(f"{ip}: {exc}")
                continue
            self._socks.append(s)
            self.bound.append(ip)
        if not self._socks:
            raise SnifferError(
                "沒有任何網卡能開始旁聽（需要系統管理員權限）：\n" + "\n".join(errors))
        self.backend = "raw socket"
        self._threads.append(threading.Thread(
            target=self._run_raw, name="sniffer-raw", daemon=True))

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(2.0)
        # ⚠ 執行緒沒收乾淨就不關控制代碼（在 select／pcap_next_ex 腳下抽走）；
        #   daemon 執行緒跟著行程結束，OS 會回收。
        if not self.active:
            self._close_socks()
            for cap in self._caps:
                cap.close()
            self._caps = []
        self._threads = []

    def _close_socks(self) -> None:
        for s in self._socks:
            try:
                s.ioctl(_SIO_RCVALL, _RCVALL_OFF)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        self._socks = []

    def read_new(self) -> list[Packet]:
        with self._lock:
            out = list(self._queue)
            self._queue.clear()
        return out

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now >= self._next_refresh:
                self._next_refresh = now + _REFRESH_SECS
                self._refresh(now)

    def _run_pcap(self, cap) -> None:
        try:
            while not self._stop.is_set():
                self._tick()
                raw = cap.next()           # 最多卡 200ms（pcap_open_live 的逾時）
                if raw:
                    self._on_raw(raw)
        except Exception as exc:                   # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"

    def _run_raw(self) -> None:
        try:
            while not self._stop.is_set():
                self._tick()
                ready, _, _ = select.select(self._socks, [], [], 0.2)
                for s in ready:
                    try:
                        raw = s.recv(65535)
                    except OSError as exc:
                        # 10040＝封包比緩衝區大（被截斷），這筆放掉就好
                        if getattr(exc, "winerror", None) == 10040:
                            continue
                        raise
                    self._on_raw(raw)
        except Exception as exc:                   # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"

    def _refresh(self, now: float) -> None:
        """重查遊戲的連線表；新冒出來的連線，把暫留區裡屬於它的封包補發。"""
        conns = netconn.connections(self._pid)
        if conns is None:
            return                     # 查不到 ≠ 沒有連線：這一拍跳過，不動已知連線
        fresh = False
        with self._lock:
            for c in conns:
                if c.key not in self._keys:
                    fresh = True
                self._keys[c.key] = now
            for k in [k for k, t in self._keys.items()
                      if now - t > _KEY_LINGER_SECS]:
                del self._keys[k]
                self._next.pop((k, True), None)
                self._next.pop((k, False), None)
        while self._pending and now - self._pending[0][0] > _PENDING_SECS:
            self._pending.popleft()
        if fresh and self._pending:
            keep = deque(maxlen=_PENDING_MAX)
            for item in self._pending:
                if not self._emit(*item[1:]):
                    keep.append(item)
            self._pending = keep

    def _on_raw(self, raw: bytes) -> None:
        p = parse_tcp(raw)
        if p is None or not p[5]:
            return                     # 不是 TCP，或是沒內容的純 ACK／握手段
        ts = time.time()
        with self._lock:
            if not self._emit(ts, *p):
                # 連線表還沒更新到（剛連上的頭幾包）→ 暫留，下次 _refresh 補認。
                self._pending.append((time.monotonic(), ts, *p))

    def _emit(self, ts, src, sport, dst, dport, tseq, payload) -> bool:
        with self._lock:
            if (src, sport, dst, dport) in self._keys:
                key, out = (src, sport, dst, dport), True
            elif (dst, dport, src, sport) in self._keys:
                key, out = (dst, dport, src, sport), False
            else:
                return False
            # 重傳過濾：整段都落在已經看過的序號之前 → 丟掉（差值當有號 32 位元比）。
            # ⚠ 亂序到達（後段先到）的前段也會被當重傳丟掉；本機旁聽很少見，
            #   retransmits 計數看得到有沒有發生。
            end = (tseq + len(payload)) & 0xFFFFFFFF
            exp = self._next.get((key, out))
            if exp is not None and (
                    end == exp or ((end - exp) & 0xFFFFFFFF) >= 0x80000000):
                self.retransmits += 1
                return True
            self._next[(key, out)] = end
            self._seq += 1
            self._queue.append(Packet(
                self._seq, ts, out, key, len(payload), bytes(payload[:CAP]), tseq))
            return True
