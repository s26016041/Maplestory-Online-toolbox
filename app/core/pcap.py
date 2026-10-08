"""Npcap（wpcap.dll）的最小 ctypes 包裝：只有「開網卡、收封包」要用到的那幾支。

為什麼需要：Windows 的 raw socket 旁聽（SIO_RCVALL）會被 Windows 防火牆擋掉
**接收方向** —— 實測只看得到遊戲送出的、看不到伺服器回的。Npcap 是掛在 NDIS 層的
驅動，兩個方向都收得到，也不受防火牆影響。有裝 Wireshark 的電腦就有 Npcap。

沒裝 Npcap → load() 回 None，sniffer 退回 raw socket（並提示接收方向可能看不到）。
"""
from __future__ import annotations

import ctypes
import os
import socket
from ctypes import POINTER, Structure, c_char_p, c_int, c_long, c_ubyte, c_uint, \
    c_uint32, c_ushort, c_void_p

AF_INET = 2
DLT_NULL, DLT_EN10MB, DLT_RAW = 0, 1, 12
_ERRBUF = 256


class _sockaddr(Structure):
    _fields_ = [("sa_family", c_ushort), ("sa_data", c_ubyte * 14)]


class _pcap_addr(Structure):
    pass


_pcap_addr._fields_ = [
    ("next", POINTER(_pcap_addr)),
    ("addr", POINTER(_sockaddr)),
    ("netmask", POINTER(_sockaddr)),
    ("broadaddr", POINTER(_sockaddr)),
    ("dstaddr", POINTER(_sockaddr)),
]


class _pcap_if(Structure):
    pass


_pcap_if._fields_ = [
    ("next", POINTER(_pcap_if)),
    ("name", c_char_p),
    ("description", c_char_p),
    ("addresses", POINTER(_pcap_addr)),
    ("flags", c_uint),
]


class _timeval(Structure):
    _fields_ = [("tv_sec", c_long), ("tv_usec", c_long)]   # Windows 的 long 是 32 位元


class _pkthdr(Structure):
    _fields_ = [("ts", _timeval), ("caplen", c_uint32), ("len", c_uint32)]


class _bpf_program(Structure):
    _fields_ = [("bf_len", c_uint), ("bf_insns", c_void_p)]


class PcapError(RuntimeError):
    pass


class Pcap:
    """載入後的 wpcap.dll。用 Pcap.load() 取得；沒裝 Npcap 回 None。"""

    _instance: "Pcap | None" = None
    _tried = False

    @classmethod
    def load(cls) -> "Pcap | None":
        if cls._tried:
            return cls._instance
        cls._tried = True
        folder = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                              "System32", "Npcap")
        path = os.path.join(folder, "wpcap.dll")
        if not os.path.exists(path):
            return None
        try:
            # wpcap.dll 相依同資料夾的 Packet.dll，要把那個資料夾加進 DLL 搜尋路徑。
            os.add_dll_directory(folder)
            cls._instance = cls(ctypes.CDLL(path))
        except OSError:
            cls._instance = None
        return cls._instance

    def __init__(self, dll) -> None:
        # ⚠ 控制代碼一律宣告成 c_void_p：不宣告的話 ctypes 當 32 位元 int，
        #   64 位元 Python 上指標被截半 = 當場存取違規。
        d = self._d = dll
        d.pcap_findalldevs.argtypes = [POINTER(POINTER(_pcap_if)), c_char_p]
        d.pcap_findalldevs.restype = c_int
        d.pcap_freealldevs.argtypes = [POINTER(_pcap_if)]
        d.pcap_freealldevs.restype = None
        d.pcap_open_live.argtypes = [c_char_p, c_int, c_int, c_int, c_char_p]
        d.pcap_open_live.restype = c_void_p
        d.pcap_compile.argtypes = [c_void_p, POINTER(_bpf_program), c_char_p,
                                   c_int, c_uint32]
        d.pcap_compile.restype = c_int
        d.pcap_setfilter.argtypes = [c_void_p, POINTER(_bpf_program)]
        d.pcap_setfilter.restype = c_int
        d.pcap_freecode.argtypes = [POINTER(_bpf_program)]
        d.pcap_freecode.restype = None
        d.pcap_datalink.argtypes = [c_void_p]
        d.pcap_datalink.restype = c_int
        d.pcap_next_ex.argtypes = [c_void_p, POINTER(POINTER(_pkthdr)),
                                   POINTER(POINTER(c_ubyte))]
        d.pcap_next_ex.restype = c_int
        d.pcap_geterr.argtypes = [c_void_p]
        d.pcap_geterr.restype = c_char_p
        d.pcap_close.argtypes = [c_void_p]
        d.pcap_close.restype = None

    def devices(self) -> list[tuple[bytes, str, list[str]]]:
        """所有網卡：(裝置名, 說明, [IPv4…])。"""
        head = POINTER(_pcap_if)()
        err = ctypes.create_string_buffer(_ERRBUF)
        if self._d.pcap_findalldevs(ctypes.byref(head), err) != 0:
            raise PcapError(err.value.decode(errors="replace"))
        out = []
        try:
            dev = head
            while dev:
                ips = []
                a = dev.contents.addresses
                while a:
                    sa = a.contents.addr
                    if sa and sa.contents.sa_family == AF_INET:
                        ips.append(socket.inet_ntoa(bytes(sa.contents.sa_data[2:6])))
                    a = a.contents.next
                desc = (dev.contents.description or b"").decode(errors="replace")
                out.append((dev.contents.name, desc, ips))
                dev = dev.contents.next
        finally:
            self._d.pcap_freealldevs(head)
        return out

    def open(self, name: bytes, bpf: str = "ip and tcp") -> "Capture":
        err = ctypes.create_string_buffer(_ERRBUF)
        # snaplen 65535、不開混雜模式（只要自己的流量）、每 200ms 交一次貨
        h = self._d.pcap_open_live(name, 65535, 0, 200, err)
        if not h:
            raise PcapError(err.value.decode(errors="replace"))
        prog = _bpf_program()
        if self._d.pcap_compile(h, ctypes.byref(prog), bpf.encode(), 1,
                                0xFFFFFFFF) == 0:
            self._d.pcap_setfilter(h, ctypes.byref(prog))
            self._d.pcap_freecode(ctypes.byref(prog))
        # 過濾器編不過不致命：parse_tcp 本來就會自己挑 TCP。
        return Capture(self._d, h)


class Capture:
    """一張開著的網卡。"""

    def __init__(self, dll, handle) -> None:
        self._d = dll
        self._h = handle
        self.linktype = dll.pcap_datalink(handle)

    def next(self) -> bytes | None:
        """下一個封包，**已去掉鏈路層標頭**（從 IP 標頭開始）。
        逾時或不是 IPv4 回 None；裝置出錯丟 PcapError。"""
        hdr = POINTER(_pkthdr)()
        data = POINTER(c_ubyte)()
        rc = self._d.pcap_next_ex(self._h, ctypes.byref(hdr), ctypes.byref(data))
        if rc == 0:
            return None
        if rc < 0:
            msg = self._d.pcap_geterr(self._h) or b""
            raise PcapError(msg.decode(errors="replace") or f"pcap_next_ex={rc}")
        raw = ctypes.string_at(data, hdr.contents.caplen)
        lt = self.linktype
        if lt == DLT_EN10MB:
            if len(raw) < 14:
                return None
            off, etype = 14, raw[12:14]
            if etype == b"\x81\x00" and len(raw) >= 18:     # VLAN 標籤
                off, etype = 18, raw[16:18]
            return raw[off:] if etype == b"\x08\x00" else None
        if lt == DLT_NULL:
            return raw[4:]
        if lt == DLT_RAW:
            return raw
        return None

    def close(self) -> None:
        if self._h:
            self._d.pcap_close(self._h)
            self._h = None
