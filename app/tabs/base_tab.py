"""分頁基底類別。

所有工具分頁都繼承 BaseTab。主視窗靠這個共同介面來自動載入分頁：
每個分頁只要設定 TAB_TITLE（分頁標題）、GROUP（左側分類）與 ORDER（排序），
並實作 build_ui() 建立自己的介面即可。
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from app.core import window as win

# ★ 左側分類（主視窗照這個順序排）。沒有分頁的分類不會出現在左邊。
GROUP_AUTO = "自動化"
GROUP_DEV = "開發工具"
GROUPS = (GROUP_AUTO, GROUP_DEV)

# 視窗標題過濾的預設關鍵字（台版新楓之谷的視窗標題是 MapleStory）。
GAME_TITLE_KEYWORD = "MapleStory"
# 遊戲視窗的類別名開頭（台版實測 MapleStoryClassTW）。
# ⚠ 光靠標題會誤中：專案資料夾就叫 Maplestory-…，VS Code／檔案總管的標題都含這個字。
GAME_CLASS_PREFIX = "MapleStoryClass"


def game_first(windows: list) -> tuple[list, int]:
    """把真正的遊戲視窗排到最前面。回傳 (排好的清單, 遊戲**行程**數)。

    ⚠ 同一個遊戲行程會有不只一個同類別的最上層視窗（實測同 PID 出現兩列），
      所以同 PID 只留一列、數量也照 PID 算 —— 不然「只有一台就自動選」永遠不成立。
    """
    games, seen = [], set()
    for w in windows:
        if w.class_name.startswith(GAME_CLASS_PREFIX) and w.pid not in seen:
            seen.add(w.pid)
            games.append(w)
    others = [w for w in windows if not w.class_name.startswith(GAME_CLASS_PREFIX)]
    return games + others, len(games)


def find_game():
    """直接抓遊戲視窗（楓之谷只能開一個，不必讓使用者選）。找不到回 None。

    同一個遊戲行程會有不只一個最上層視窗，取面積最大的當主視窗。
    """
    games = [w for w in win.enumerate_windows(visible_only=False)
             if w.class_name.startswith(GAME_CLASS_PREFIX)]
    if not games:
        return None
    return max(games, key=lambda w: w.width * w.height)


class BaseTab(QWidget):
    """所有功能分頁的基底類別。

    子類別需要覆寫：
        TAB_TITLE：顯示在分頁上的標題文字。
        ORDER：分頁排序（數字越小越靠左），可選。
        build_ui()：建立此分頁的介面內容。
    """

    TAB_TITLE: str = "未命名分頁"
    ORDER: int = 100
    # 設為 False 可讓自動載入器略過此分頁（例如尚未完成的功能）。
    ENABLED: bool = True
    # 左側分類（見 GROUPS）。沒設就落在最後一個分類，不會不見。
    GROUP: str = GROUP_DEV

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.build_ui()

    def build_ui(self) -> None:
        """建立分頁介面。子類別必須覆寫。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 必須實作 build_ui() 方法"
        )

    def on_show(self) -> None:
        """分頁被切換到（顯示）時呼叫，可選覆寫。"""

    def on_close(self) -> None:
        """應用程式關閉前呼叫，用於釋放資源，可選覆寫。"""
