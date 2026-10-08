"""系統管理員權限：查詢，以及用 UAC 重新啟動自己。

封包擷取用的 raw socket 一定要系統管理員；遊戲若以系統管理員身分執行，
讀它的記憶體也要同等權限。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """跳 UAC 以系統管理員身分再開一份自己。回傳 True＝新的那份已經啟動
    （呼叫端應該接著關掉現在這份）；使用者按了「否」回 False。"""
    if getattr(sys, "frozen", False):          # 打包後：exe 自己就是程式
        exe, args = sys.executable, sys.argv[1:]
    else:
        # ⚠ 提權後的新行程起始目錄不保證跟現在一樣，腳本路徑要給絕對的。
        exe = sys.executable
        args = [os.path.abspath(sys.argv[0])] + sys.argv[1:]
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    rc = shell32.ShellExecuteW(
        None, "runas", exe, subprocess.list2cmdline(args), os.getcwd(), 1)
    return (rc or 0) > 32                      # ≤32 是錯誤碼（5＝使用者拒絕）
