"""資源檔路徑：開發時相對專案根目錄，打包成 exe 後在 PyInstaller 的解壓目錄。

所有資源集中在專案根目錄的 assets/（打包時要整包列進 spec 的 datas，
否則打包後會找不到）：
    assets/icon.ico          程式圖示（exe、工作列、視窗左上）
    assets/icon.png          去背後的圖示（tools/make_icon.py 產生）
    assets/icon_source.jpg   圖示的來源圖，改圖後重跑 py tools/make_icon.py
    assets/fonts/*.ttf       介面字體
    assets/ui/*.svg          勾選框／單選鈕／下拉箭頭
"""
from __future__ import annotations

import sys
from pathlib import Path


def resource(rel: str) -> Path:
    """取得資源檔的實際路徑。rel 是相對專案根目錄的路徑，例如 "fonts/X.ttf"。"""
    if hasattr(sys, "_MEIPASS"):          # PyInstaller 打包後的解壓目錄
        return Path(sys._MEIPASS) / rel
    return Path(__file__).resolve().parents[1] / rel
