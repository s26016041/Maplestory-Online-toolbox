"""視窗列舉：找出遊戲視窗與它的 PID。

純查詢（EnumWindows），不搶焦點、不動視窗。
"""
from __future__ import annotations

from dataclasses import dataclass

import win32gui
import win32process


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    class_name: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


def enumerate_windows(
    title_contains: str | None = None,
    visible_only: bool = True,
) -> list[WindowInfo]:
    """列舉最上層視窗。可用 title_contains 過濾標題（不分大小寫）。"""
    results: list[WindowInfo] = []

    def _callback(hwnd: int, _extra) -> bool:
        if visible_only and not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        if title_contains and title_contains.lower() not in title.lower():
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
        results.append(
            WindowInfo(hwnd=hwnd, pid=pid, title=title, class_name=class_name, rect=rect)
        )
        return True

    win32gui.EnumWindows(_callback, None)
    return results
