"""全域淺色主題（Maple Light）。

在 QApplication 套一份「QSS 樣式表 + 字體 + 調色盤 + 樣式代理」，讓主視窗與所有
分頁 / 元件外觀一致。要調整整體外觀只改這裡，各分頁不需要動。

用法（見 main.py）：
    from app.theme import apply_theme
    apply_theme(app)

## 設計規格

- 色票：白底（視窗底 #F6F7F9、卡片 #FFFFFF、邊線 #E2E5EA）、主色楓葉橘 #F97316、
  主文字 #1F2937、次文字 #6B7280、成功 #059669、警告 #A16207、危險 #DC2626。
  ⚠ 白底上的狀態色要用**深一階**的（亮黃／亮綠在白底上看不清楚）；
    警告用暗黃褐不用橘，免得跟主色分不出來。
  （2026-09-20 使用者：深色版「太醜」，改白底。）
- 8px 網格：控制項一律 32px 高（輸入框／下拉／數字框／按鈕），小控制項圓角 6px、
  大容器（群組框／分頁內容區／表格）圓角 10px。
- 左側分類欄比視窗底略灰，選中的項目左緣 3px 橘條；上方子分頁扁平、選中只畫 2px 橘底線。
- 主要動作按鈕加 `primary` 動態屬性＝實心橘底白字；其他按鈕一律低調灰底。
- 表格：表頭靠左、不畫直的格線、列高 34px、隔列微淡。

## 各分頁怎麼用顏色

⛔ 分頁裡**不准再寫死色碼** —— 一律引用這裡的語意常數：
    theme.TEXT_MUT / theme.MUTED   次要說明文字（狀態列、提示）
    theme.OK / theme.SUCCESS       成功、連線中
    theme.WARN / theme.WARNING     警告
    theme.BAD / theme.DANGER       錯誤、停機、危險動作
    theme.SEND / theme.RECV        封包方向（送出／接收）
    theme.TEXT_DIS                 停用
改色只改這一個檔，全部分頁一起變。
⚠ assets/ui/radio.svg 的圓點色碼是寫在 SVG 裡的，改主色要一起改。
"""
from __future__ import annotations

from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QHeaderView, QProxyStyle, QWidget

from app.paths import resource

# 介面字體：打包在 assets/fonts/ 裡，不依賴使用者電腦有沒有裝。
# 載入失敗（檔案缺了 / 打包漏收）就退回系統內建的微軟正黑體，不讓程式開不起來。
UI_FONT_FILE = "assets/fonts/Iansui-Regular.ttf"
UI_FONT_FALLBACK = "Microsoft JhengHei UI"
UI_FONT_SIZE = 10

# 程式圖示：同一顆 .ico 供「視窗左上角」與「工作列」使用（Qt 這兩個是同一個設定）。
# exe 檔本身在檔案總管/桌面顯示的圖示是另一條路 —— 由 spec 的 icon= 嵌進去。
APP_ICON_FILE = "assets/icon.ico"

# 勾選框的勾、單選鈕的點、下拉框的箭頭：QSS 一旦自己畫 indicator，Qt 就不再畫
# 原生的勾，所以要自備一張圖。SVG 由 Qt 內建的 qsvg 外掛載入；載不到（打包漏收
# 外掛）只是少一個勾（橘底方塊仍然看得出有沒有勾），不會出錯。
UI_CHECK_SVG = "assets/ui/check.svg"
UI_RADIO_SVG = "assets/ui/radio.svg"
UI_CHEVRON_SVG = "assets/ui/chevron.svg"
UI_CHEVRON_DIS_SVG = "assets/ui/chevron_dis.svg"

# --- 調色盤（Modern Tech Dark）----------------------------------------------
# ★ QSS 是用 string.Template 從這些常數生出來的 —— 色碼**只有這一份**，改這裡就好。
BG         = "#F6F7F9"   # 視窗底
SIDEBAR    = "#ECEEF2"   # 左側分類欄（比視窗底更深一階）
BASE       = "#FFFFFF"   # 輸入框底
PANEL      = "#FFFFFF"   # 卡片 / 群組框 / 分頁內容區
PANEL_HDR  = "#F1F3F6"   # 表頭
PANEL_HOV  = "#F3F4F6"   # 清單／選單項目 hover
BTN        = "#FFFFFF"   # 次要按鈕底
BTN_HOV    = "#F3F4F6"   # 次要按鈕 hover
BTN_PRS    = "#E5E7EB"   # 次要按鈕按下
BTN_BRD    = "#D1D5DB"   # 次要按鈕邊框（比底色亮一階，才看得出輪廓）
TAB_PANE   = PANEL       # 分頁內容區
TABLE_BG   = "#FFFFFF"
TABLE_ALT  = "#F9FAFB"   # 隔列
BORDER     = "#E2E5EA"   # 邊線 / 分隔線
BORDER_HL  = "#B8BEC9"   # hover 時的邊線
GRID       = "#E2E5EA"
ACCENT     = "#F97316"   # 主色（楓葉橘）
ACCENT_HOV = "#FB8A3C"
ACCENT_PRS = "#EA580C"
ACCENT_DIS = "#FCD9BD"   # 主要按鈕停用時的底
ACCENT_DIS_TEXT = "#FFFFFF"
SEL_BG     = "#FFE8D4"   # 清單／表格選取列（主色 35% 疊在卡片上）
SIDEBAR_SEL = "#FFFFFF"  # 左側分類選中的柔和底
TEXT       = "#1F2937"
TEXT_MUT   = "#6B7280"   # 次要 / 狀態文字
TEXT_DIS   = "#A3A9B3"   # 停用
SUCCESS    = "#059669"   # 成功、連線中
WARNING    = "#A16207"   # 警告
DANGER     = "#DC2626"   # 錯誤、停機、危險動作
SEND       = "#EA580C"   # 封包方向：送出（橘，跟主色同系）
RECV       = "#0284C7"   # 封包方向：接收（天藍，圖示角色的配色）

# 供各分頁沿用主題色的語意常數（取代原本寫死的 "gray" / "green"）。
MUTED = TEXT_MUT
OK = SUCCESS
WARN = WARNING
BAD = DANGER

# 控制項尺寸（8px 網格）
CONTROL_H = 32          # 輸入框／下拉／數字框／按鈕的總高度
ROW_H = 34              # 表格列高
RADIUS_SM = 6           # 小控制項圓角
RADIUS_LG = 10          # 大容器圓角

# 控制項高度的算法：min-height（內容）+ 上下 padding + 上下 1px 邊框 = CONTROL_H。
# ⚠ QSS 的 min-height 指**內容區**（不含 padding／border），所以是 32 − 10 − 2 = 20。
_CTRL_INNER = CONTROL_H - 5 * 2 - 1 * 2
# ⚠ 數字框例外：Fusion 替上下箭頭多算 3px，內容區要少給 3px 才會跟其他控制項一樣 32px
#   （離屏實測：min-height 20 → 35px、17 → 32px）。
_SPIN_INNER = _CTRL_INNER - 3

_QSS_TEMPLATE = """
/* ---- 基底 ---- */
QWidget {
    color: $TEXT;
    font-size: 10pt;
}
QMainWindow, QDialog, QMessageBox, QInputDialog, QFileDialog, QProgressDialog {
    background-color: $BG;
}
QLabel { background: transparent; }
QLabel:disabled { color: $TEXT_DIS; }

/* ---- 左側分類欄（主視窗的 QListWidget，objectName = sidebar）---- */
/* ⚠ 字級 13 是「長時間自動化」六個字在 100px 寬剛好放得下的上限；
   14 會被省略成「長時間自動…」。左邊 3px 是選中指示條的位置，沒選中時透明佔位，
   這樣選中／沒選中文字不會左右跳。 */
QListWidget#sidebar {
    background-color: $SIDEBAR;
    border: none;
    border-right: 1px solid $BORDER;
    font-size: 13px;
    outline: none;
    padding: 8px 0;
}
QListWidget#sidebar::item {
    padding: 14px 4px 14px 5px;
    margin: 0;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    color: $TEXT_MUT;
    background: transparent;
}
QListWidget#sidebar::item:hover {
    color: $TEXT;
    background: $SIDEBAR_SEL;
}
QListWidget#sidebar::item:selected {
    color: $TEXT;
    background: $SIDEBAR_SEL;
    border-left: 3px solid $ACCENT;
}

/* ---- 上方子分頁：扁平、只畫底線 ---- */
QTabWidget::pane {
    border: 1px solid $BORDER;
    border-radius: $RADIUS_LG px;
    background-color: $TAB_PANE;
    top: -1px;
}
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent;
    color: $TEXT_MUT;
    padding: 8px 16px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover { color: $TEXT; }
QTabBar::tab:selected {
    color: $ACCENT;
    border-bottom: 2px solid $ACCENT;
}
QTabBar::tab:disabled { color: $TEXT_DIS; }

/* ---- 群組框（卡片）---- */
/* 內距＝這裡的 padding + 版面自己的 margin（Fusion 預設 11px）。 */
QGroupBox {
    background-color: $PANEL;
    border: 1px solid $BORDER;
    border-radius: $RADIUS_LG px;
    margin-top: 14px;
    padding: 12px 6px 4px 6px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    color: $TEXT;
}
QGroupBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid $BORDER_HL; border-radius: 4px;
    background: $BASE;
}
QGroupBox::indicator:checked { background: $ACCENT; border-color: $ACCENT; image: url("$CHECK"); }

/* ---- 按鈕 ---- */
/* 預設＝次要／工具按鈕（重新整理、瀏覽、停止…）：低調灰底。 */
QPushButton, QToolButton {
    background-color: $BTN;
    color: $TEXT;
    border: 1px solid $BTN_BRD;
    border-radius: $RADIUS_SM px;
    padding: 5px 14px;
    min-height: $CTRL_INNER px;
}
QPushButton:hover, QToolButton:hover { background-color: $BTN_HOV; border-color: $BORDER_HL; }
QPushButton:pressed, QToolButton:pressed { background-color: $BTN_PRS; }
QPushButton:checked, QToolButton:checked {
    background-color: $SEL_BG; border-color: $ACCENT; color: $TEXT;
}
QPushButton:disabled, QToolButton:disabled {
    color: $TEXT_DIS; background-color: #F3F4F6; border-color: $BORDER;
}
/* 主要動作按鈕（一鍵登入、開始、傳送…）：setProperty("primary", True) 即為實心橘底 */
QPushButton[primary="true"] {
    background-color: $ACCENT;
    color: #ffffff;
    border: 1px solid $ACCENT;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background-color: $ACCENT_HOV; border-color: $ACCENT_HOV; }
QPushButton[primary="true"]:pressed { background-color: $ACCENT_PRS; border-color: $ACCENT_PRS; }
QPushButton[primary="true"]:disabled {
    background-color: $ACCENT_DIS; border-color: $ACCENT_DIS; color: $ACCENT_DIS_TEXT;
}
/* 危險動作（停機、全部分解…）：setProperty("danger", True) 即為紅字描邊 */
QPushButton[danger="true"] { color: $DANGER; border-color: #F5B5B5; font-weight: 600; }
QPushButton[danger="true"]:hover { background-color: #FEECEC; border-color: $DANGER; }
QPushButton[danger="true"]:disabled { color: $TEXT_DIS; border-color: $BORDER; }

/* ---- 輸入類 ---- */
/* ⚠⚠ 一定要寫 QAbstractSpinBox，不能只寫 QSpinBox ——
   **QDoubleSpinBox 不是 QSpinBox 的子類別**（兩個都直接繼承 QAbstractSpinBox），
   只寫 QSpinBox 的話小數框完全吃不到樣式：高度只有 19px（整數框是 31px），
   上下箭頭被壓到剩一半。使用者回報的「數字框框都被砍到一半」就是這個。 */
QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit {
    background-color: $BASE;
    color: $TEXT;
    border: 1px solid $BORDER;
    border-radius: $RADIUS_SM px;
    padding: 5px 8px;
    min-height: $CTRL_INNER px;
    selection-background-color: $ACCENT;
    selection-color: #ffffff;
}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover { border-color: $BORDER_HL; }
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid $ACCENT;
}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled,
QPlainTextEdit:disabled, QTextEdit:disabled {
    color: $TEXT_DIS; background-color: #F3F4F6; border-color: $BORDER;
}
QLineEdit:read-only { background-color: #F3F4F6; }
/* 數字框的左右內距縮小：它右邊還有上下箭頭要佔位置，
   沿用上面那組的 8px 會讓每個框平白多 8px，一整列就多出幾十 px。
   上下維持 5px —— 那是把框撐到 32px 的關鍵。 */
QAbstractSpinBox { padding: 5px 3px; min-height: $SPIN_INNER px; }
/* ⛔ 不要去設 ::up-button / ::down-button ——
   樣式表一碰那兩個子控制項，Qt 就**不再畫預設的上下箭頭**，
   按鈕會變成一塊空白（試過，只剩一條分隔線）。
   上面那組基本樣式本來就會留位置給箭頭，讓 Qt 自己畫就好。 */
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: right;
    width: 24px; border: none;
}
QComboBox::down-arrow { image: url("$CHEVRON"); width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: url("$CHEVRON_DIS"); }
QComboBox QAbstractItemView {
    background-color: $PANEL_HDR;
    color: $TEXT;
    border: 1px solid $BORDER_HL;
    border-radius: $RADIUS_SM px;
    padding: 4px;
    selection-background-color: $SEL_BG;
    selection-color: $TEXT;
    outline: none;
}
QComboBox QAbstractItemView::item { min-height: 26px; padding: 2px 8px; border-radius: 4px; }
QComboBox QAbstractItemView::item:hover { background-color: $PANEL_HOV; }
QComboBox QAbstractItemView::item:selected { background-color: $SEL_BG; color: $TEXT; }

/* ---- 勾選框／單選鈕 ---- */
QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox:disabled, QRadioButton:disabled { color: $TEXT_DIS; }
QCheckBox::indicator, QRadioButton::indicator, QAbstractItemView::indicator {
    width: 16px; height: 16px;
    border: 1px solid $BORDER_HL;
    background: $BASE;
}
QCheckBox::indicator, QAbstractItemView::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: $ACCENT; }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {
    background: $ACCENT; border-color: $ACCENT; image: url("$CHECK");
}
QRadioButton::indicator:checked {
    background: $BASE; border-color: $ACCENT; image: url("$RADIO");
}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    border-color: $BORDER; background: #F3F4F6;
}
QCheckBox::indicator:checked:disabled, QAbstractItemView::indicator:checked:disabled {
    background: $ACCENT_DIS; border-color: $ACCENT_DIS;
}

/* ---- 表格 ---- */
/* 直的格線不畫（qproperty-showGrid）、每張表都隔列微淡（qproperty-alternatingRowColors），
   表頭靠左（qproperty-defaultAlignment）。列高 34px 由 _Style.polish() 設（QSS 設不到）。 */
QTableView, QTableWidget {
    background-color: $TABLE_BG;
    alternate-background-color: $TABLE_ALT;
    gridline-color: $GRID;
    border: 1px solid $BORDER;
    border-radius: $RADIUS_LG px;
    selection-background-color: $SEL_BG;
    selection-color: $TEXT;
    outline: none;
    qproperty-showGrid: false;
    qproperty-alternatingRowColors: true;
}
QTableView::item { padding: 4px 8px; border: none; }
QTableView::item:selected { background-color: $SEL_BG; color: $TEXT; }
QTableView::item:hover { background-color: $PANEL_HOV; }
QHeaderView { background-color: $PANEL_HDR; qproperty-defaultAlignment: "AlignLeft|AlignVCenter"; }
QHeaderView::section {
    background-color: $PANEL_HDR;
    color: $TEXT_MUT;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid $BORDER;
    font-weight: 600;
}
QHeaderView::section:vertical { padding: 4px 8px; border-right: 1px solid $BORDER; }
QTableCornerButton::section { background-color: $PANEL_HDR; border: none; border-bottom: 1px solid $BORDER; }

/* ---- 清單 ---- */
QListView, QListWidget {
    background-color: $TABLE_BG;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: $SEL_BG;
    selection-color: $TEXT;
}
/* 上下 3px：視窗高度固定 700，列表列高每多 1px、五列就多 5px（副本腳本製作頁實測 5px 會把
   步驟清單撐到蓋住下面的按鈕）。 */
QListView::item { padding: 3px 8px; border-radius: 4px; }
QListView::item:hover { background-color: $PANEL_HOV; }
QListView::item:selected { background-color: $SEL_BG; color: $TEXT; }

/* ---- 選單 ---- */
QMenu {
    background-color: $PANEL_HDR;
    color: $TEXT;
    border: 1px solid $BORDER_HL;
    border-radius: $RADIUS_SM px;
    padding: 6px;
}
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 4px; }
QMenu::item:selected { background-color: $SEL_BG; }
QMenu::item:disabled { color: $TEXT_DIS; }
QMenu::separator { height: 1px; background: $BORDER; margin: 6px 4px; }

/* ---- 進度條 ---- */
QProgressBar {
    background-color: $BASE;
    border: 1px solid $BORDER;
    border-radius: $RADIUS_SM px;
    text-align: center;
    color: $TEXT;
    min-height: 16px;
}
QProgressBar::chunk { background-color: $ACCENT; border-radius: 5px; }

/* ---- 捲軸 ---- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #C9CED6; min-height: 30px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: $BORDER_HL; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #C9CED6; min-width: 30px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: $BORDER_HL; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ---- 其他 ---- */
QScrollArea { border: none; background: transparent; }
/* QScrollArea.setWidget() 會把內容 widget 的 autoFillBackground 打開 → 用視窗底色填滿，
   在卡片色的分頁內容區裡多出一塊更深的方框（收益監控的卡片區實拍到）。
   `.QWidget`（前面有點）只認**正好是 QWidget** 的容器：自己畫圖的 canvas／IconGrid
   是子類別，不受影響。表格的 viewport 也不在這條裡（父層不是 QScrollArea）。 */
QScrollArea > QWidget#qt_scrollarea_viewport { background: transparent; }
QScrollArea > QWidget#qt_scrollarea_viewport > .QWidget { background: transparent; }
QSplitter::handle { background: $BORDER; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }
QStatusBar { background-color: $SIDEBAR; color: $TEXT_MUT; border-top: 1px solid $BORDER; }
QStatusBar::item { border: none; }
QToolTip {
    background-color: $PANEL_HDR; color: $TEXT;
    border: 1px solid $BORDER_HL; padding: 6px 8px; border-radius: $RADIUS_SM px;
}
"""


def _qss() -> str:
    """把調色盤與圖檔路徑代進樣板。SVG 用絕對路徑（打包後在 _MEI 暫存目錄）。"""
    values = {k: v for k, v in globals().items()
              if isinstance(v, (str, int)) and k.isupper()}
    values["CTRL_INNER"] = _CTRL_INNER
    values["SPIN_INNER"] = _SPIN_INNER
    values["CHECK"] = resource(UI_CHECK_SVG).as_posix()
    values["RADIO"] = resource(UI_RADIO_SVG).as_posix()
    values["CHEVRON"] = resource(UI_CHEVRON_SVG).as_posix()
    values["CHEVRON_DIS"] = resource(UI_CHEVRON_DIS_SVG).as_posix()
    # "$RADIUS_LG px" 這種寫法是為了讓 Template 認得出名字的結尾；代完把空格收掉。
    return Template(_QSS_TEMPLATE).substitute(values).replace(" px", "px")


class _Style(QProxyStyle):
    """Fusion 之上的一層薄代理：只負責 QSS 設不到的東西。

    - 表格列高 34px：`QHeaderView` 的 defaultSectionSize 不吃 QSS（試過
      `QHeaderView::section:vertical { min-height }` 完全沒反應；
      `qproperty-defaultSectionSize` 會連橫表頭的預設欄寬一起改成 34 → 不能用）。
      所以在 polish() 逮到每一個直表頭補設。只放大不縮小：分頁自己設了更大的列高
      （login_tab 依字高算）就尊重它。
    ⚠ 只覆寫 polish()，**不要**覆寫 pixelMetric()：那支每次重畫要被叫上千次，
      走 Python 會拖慢整個介面。
    """

    def polish(self, target):  # noqa: D102  (Qt 的三個 overload 都會進來)
        if isinstance(target, QWidget):
            super().polish(target)
            if (isinstance(target, QHeaderView)
                    and target.orientation() == Qt.Vertical
                    and target.defaultSectionSize() < ROW_H):
                target.setDefaultSectionSize(ROW_H)
            return None
        return super().polish(target)


_style_ref: _Style | None = None   # setStyle 交給 Qt 持有，這裡留一份免得 Python 端先被回收


def _palette() -> QPalette:
    """給 Fusion 底層與原生繪製的元件用的調色盤（QSS 沒覆蓋到的部分靠它）。"""
    p = QPalette()
    p.setColor(QPalette.Window, QColor(BG))
    p.setColor(QPalette.WindowText, QColor(TEXT))
    p.setColor(QPalette.Base, QColor(BASE))
    p.setColor(QPalette.AlternateBase, QColor(TABLE_ALT))
    p.setColor(QPalette.Text, QColor(TEXT))
    p.setColor(QPalette.Button, QColor(BTN))
    p.setColor(QPalette.ButtonText, QColor(TEXT))
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.Highlight, QColor(ACCENT))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ToolTipBase, QColor(PANEL_HDR))
    p.setColor(QPalette.ToolTipText, QColor(TEXT))
    p.setColor(QPalette.PlaceholderText, QColor(TEXT_MUT))
    p.setColor(QPalette.Link, QColor(ACCENT))
    p.setColor(QPalette.Mid, QColor(BORDER))
    p.setColor(QPalette.Dark, QColor(SIDEBAR))
    p.setColor(QPalette.Light, QColor(BORDER_HL))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_DIS))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_DIS))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(TEXT_DIS))
    return p


def _ui_font() -> QFont:
    """載入內附字體；載不到就退回系統字體（不讓程式因為缺字體而開不起來）。"""
    path = resource(UI_FONT_FILE)
    if path.exists():
        fid = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(fid)
        if families:
            return QFont(families[0], UI_FONT_SIZE)
    return QFont(UI_FONT_FALLBACK, UI_FONT_SIZE)


def apply_theme(app: QApplication) -> None:
    """在 QApplication 套用主題（圖示 + 字體 + 調色盤 + 樣式代理 + QSS）。"""
    global _style_ref
    _style_ref = _Style("Fusion")   # 統一底層繪製，QSS 才會在各元件一致生效
    app.setStyle(_style_ref)
    icon = resource(APP_ICON_FILE)
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    app.setFont(_ui_font())
    app.setPalette(_palette())
    app.setStyleSheet(_qss())
