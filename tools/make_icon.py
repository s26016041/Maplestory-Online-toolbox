"""從來源圖產生程式圖示：assets/icon.png（去背）與 assets/icon.ico（多尺寸）。

    py tools\\make_icon.py

來源圖 assets/icon_source.jpg 是 JPG —— **沒有透明通道**，看起來像透明的灰白
棋盤格其實是畫死在圖上的。做法：把「低彩度、偏亮」的像素當背景候選，只收
**跟圖片邊緣連通**的那一塊（角色有黑色外框線擋著，肚子／臉上的白毛不會被吃掉）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "icon_source.jpg"
OUT_PNG = ROOT / "assets" / "icon.png"
OUT_ICO = ROOT / "assets" / "icon.ico"
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def cutout(rgb: np.ndarray) -> np.ndarray:
    """回傳 alpha（uint8）。"""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # 棋盤格＝白 + 淺灰：彩度很低、亮度高。JPG 壓縮雜訊留一點餘裕。
    cand = ((hsv[..., 1] < 28) & (hsv[..., 2] > 175)).astype(np.uint8)
    n, labels = cv2.connectedComponents(cand, connectivity=4)
    border = np.concatenate(
        [labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    bg_ids = np.unique(border[border > 0])
    bg = np.isin(labels, bg_ids)
    # 背景往內推 2px 吃掉外框線外緣的 JPG 光暈，再羽化 1px 讓邊緣不鋸齒。
    bg = cv2.dilate(bg.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2)
    alpha = np.where(bg > 0, 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(alpha, (3, 3), 0)


def main() -> int:
    if not SRC.exists():
        print(f"找不到來源圖：{SRC}")
        return 1
    rgb = np.array(Image.open(SRC).convert("RGB"))
    alpha = cutout(rgb)
    rgba = np.dstack([rgb, alpha])

    # 裁到角色本體再補成正方形（圖示小，留白越少越清楚）。
    ys, xs = np.where(alpha > 16)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = Image.fromarray(rgba[y0:y1, x0:x1], "RGBA")
    side = int(max(crop.size) * 1.04)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))

    png = canvas.resize((512, 512), Image.LANCZOS)
    png.save(OUT_PNG)
    png.save(OUT_ICO, sizes=[(s, s) for s in ICO_SIZES])
    opaque = float((alpha > 127).mean())
    print(f"ok  png={OUT_PNG.name} ico={OUT_ICO.name} 不透明比例={opaque:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
