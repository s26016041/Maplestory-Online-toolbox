"""查某個行程目前有哪些 TCP 連線。封包擷取靠這個把「遊戲的封包」挑出來。

用 iphlpapi 的 GetExtendedTcpTable 列出整張連線表再依 PID 過濾。純查詢、不改任何
系統狀態；一次呼叫是微秒等級。
"""
from __future__ import annotations

import ctypes
import socket
import struct
from ctypes import wintypes
from dataclasses import dataclass

AF_INET = 2
TCP_TABLE_OWNER_PID_ALL = 5

TCP_STATES = {
    1: "CLOSED", 2: "LISTEN", 3: "SYN_SENT", 4: "SYN_RCVD", 5: "ESTABLISHED",
    6: "FIN_WAIT1", 7: "FIN_WAIT2", 8: "CLOSE_WAIT", 9: "CLOSING",
    10: "LAST_ACK", 11: "TIME_WAIT", 12: "DELETE_TCB",
}


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


@dataclass(frozen=True)
class Conn:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    state: int

    @property
    def key(self) -> tuple[str, int, str, int]:
        return (self.local_ip, self.local_port, self.remote_ip, self.remote_port)

    @property
    def state_name(self) -> str:
        return TCP_STATES.get(self.state, str(self.state))


def _ip(dw: int) -> str:
    # 表裡的位址是網路位元組序直接當 DWORD 放 → 用 little-endian 打包回原本的 4 bytes。
    return socket.inet_ntoa(struct.pack("<I", dw))


def _port(dw: int) -> int:
    # 埠號也是網路位元組序，只有低 16 位元有意義。
    return socket.ntohs(dw & 0xFFFF)


def connections(pid: int) -> list[Conn] | None:
    """回傳該 PID 的所有 TCP(IPv4) 連線（不含 LISTEN）。

    ⚠ 查詢失敗回 **None**，不是空串列 —— 呼叫端要分得出「查不到」跟「沒有連線」，
      不能因為 API 失敗就把已知連線全部丟掉。
    """
    try:
        dll = ctypes.WinDLL("iphlpapi.dll")
        size = wintypes.DWORD(0)
        # 第一次呼叫只是為了問「要多大的緩衝區」
        dll.GetExtendedTcpTable(None, ctypes.byref(size), False, AF_INET,
                                TCP_TABLE_OWNER_PID_ALL, 0)
        # 兩次呼叫之間表可能變大，多留一點
        size = wintypes.DWORD(size.value + 4096)
        buf = ctypes.create_string_buffer(size.value)
        rc = dll.GetExtendedTcpTable(buf, ctypes.byref(size), False, AF_INET,
                                     TCP_TABLE_OWNER_PID_ALL, 0)
        if rc != 0:
            return None
        n = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
        rows = ctypes.cast(
            ctypes.byref(buf, ctypes.sizeof(wintypes.DWORD)),
            ctypes.POINTER(MIB_TCPROW_OWNER_PID * n)).contents
        out = []
        for r in rows:
            if int(r.dwOwningPid) != pid or r.dwState == 2:
                continue
            out.append(Conn(_ip(r.dwLocalAddr), _port(r.dwLocalPort),
                            _ip(r.dwRemoteAddr), _port(r.dwRemotePort),
                            int(r.dwState)))
        return out
    except Exception:
        return None
