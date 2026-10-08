"""前景送鍵：SendInput 掃描碼。

★ 只有目標視窗是前景時才送得進去（新楓之谷只讀鍵盤硬體狀態、不理視窗訊息，
  見 memory background-key-input-dead-end）。呼叫端送鍵前務必先確認前景是遊戲，
  否則會打字到使用者正在用的視窗。

用掃描碼（KEYEVENTF_SCANCODE）而不是虛擬鍵：遊戲多半直接看硬體掃描碼，
虛擬鍵送法有些遊戲不吃。掃描碼由 MapVirtualKey 從虛擬鍵反查，延伸鍵（方向鍵、
Insert/Home 那排、右 Ctrl…）會帶 0xE0 前綴，要補 EXTENDEDKEY 旗標。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_u = ctypes.windll.user32
_u.GetForegroundWindow.restype = wintypes.HWND
_u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_u.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_u.MapVirtualKeyW.restype = wintypes.UINT

MAPVK_VK_TO_VSC_EX = 4
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),   # ULONG_PTR：x64 是 8 bytes，別用 c_ulong
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_u.SendInput.restype = wintypes.UINT


def scancode_for(vk: int) -> tuple[int, bool]:
    """虛擬鍵 → (掃描碼, 是否延伸鍵)。查不到回 (0, False)。"""
    sc = _u.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX)
    extended = (sc >> 8) in (0xE0, 0xE1)
    return sc & 0xFF, extended


def _emit(scan: int, extended: bool, up: bool) -> None:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(0, scan, flags, 0, 0)
    _u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def tap(scan: int, extended: bool = False, hold_s: float = 0.04) -> None:
    """按下→放開一次。hold_s 是按住的時間（太短有些遊戲會漏，40ms 實測穩）。"""
    _emit(scan, extended, False)
    time.sleep(hold_s)
    _emit(scan, extended, True)


def foreground_pid() -> int:
    """目前前景視窗屬於哪個行程。拿不到回 0。"""
    hwnd = _u.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)
