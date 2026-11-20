"""泡泡糖粉（Bubblegum Pink）主题 —— 浅色调。

浅粉底 + 深梅紫文字，整体明亮柔和，对比度足够阅读。
所有颜色集中在这里，改主题只动这一个文件。
"""

# --------------------------------------------------------------------------- #
# 主色板（浅色调）
# --------------------------------------------------------------------------- #
BG = "#ffeaf3"            # 主背景：极浅粉
BG_ALT = "#ffdff0"        # 次级背景（组框内部）
BG_INPUT = "#fff5fa"      # 输入框/下拉框背景：近白偏粉
BORDER = "#f3a8c9"        # 边框：柔和粉

PINK = "#ff6fae"          # 主泡泡糖粉（按钮、选中）
PINK_LIGHT = "#ffa6cd"    # 浅粉（hover）
PINK_DARK = "#e04a8f"     # 深粉（按下态）
PINK_SOFT = "#ffd0e4"     # 极浅粉

TEXT = "#5c2340"          # 主文字：深梅紫
TEXT_DIM = "#96617f"      # 次要文字：灰紫

ACCENT = "#ff6fae"        # 强调色
BAR_BG = "#ffd6e8"        # 进度条槽

# --------------------------------------------------------------------------- #
# 尺寸（统一调大，1920 以上屏幕看着舒服）
# --------------------------------------------------------------------------- #
FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'
FONT_SIZE = 13            # 全局基准字号 pt
FONT_SIZE_SMALL = 11      # 日志/次要信息
RADIUS = 8                # 控件圆角
PADDING_V = 10            # 垂直内边距
PADDING_H = 16            # 水平内边距
MIN_HEIGHT = 40           # 按钮/下拉框最小高度

WIN_W = 920               # 主窗口宽
WIN_H = 1020              # 主窗口高

# --------------------------------------------------------------------------- #
# 全局样式表
# --------------------------------------------------------------------------- #
GLOBAL_QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE}pt;
}}

QLabel {{
    color: {TEXT};
    font-size: {FONT_SIZE}pt;
}}

QGroupBox {{
    font-weight: bold;
    font-size: {FONT_SIZE}pt;
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    margin-top: 16px;
    padding-top: 16px;
    background-color: {BG_ALT};
    color: {TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {PINK_DARK};
    font-size: {FONT_SIZE}pt;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG_ALT};
    border-radius: {RADIUS}px;
}}
QTabBar::tab {{
    background-color: {PINK_SOFT};
    color: {TEXT_DIM};
    padding: 12px 26px;
    margin-right: 3px;
    font-size: {FONT_SIZE}pt;
    border-top-left-radius: {RADIUS}px;
    border-top-right-radius: {RADIUS}px;
}}
QTabBar::tab:selected {{
    background-color: {PINK};
    color: #ffffff;
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background-color: {PINK_LIGHT};
    color: {TEXT};
}}

QPushButton {{
    background-color: {PINK};
    color: #ffffff;
    border: none;
    border-radius: {RADIUS}px;
    padding: {PADDING_V}px {PADDING_H}px;
    font-weight: bold;
    font-size: {FONT_SIZE}pt;
}}
QPushButton:hover {{
    background-color: {PINK_LIGHT};
}}
QPushButton:pressed {{
    background-color: {PINK_DARK};
}}
QPushButton:disabled {{
    background-color: {PINK_SOFT};
    color: {TEXT_DIM};
}}

QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 0px 10px;
    font-size: {FONT_SIZE}pt;
}}
QComboBox:hover {{
    border: 1px solid {PINK};
}}
QComboBox::drop-down {{
    border: none;
    width: 32px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_INPUT};
    color: {TEXT};
    selection-background-color: {PINK};
    selection-color: #ffffff;
    border: 1px solid {BORDER};
    outline: 0;
    font-size: {FONT_SIZE}pt;
}}
QComboBox QAbstractItemView::item {{
    color: {TEXT};
    background-color: {BG_INPUT};
    min-height: 34px;
    padding-left: 10px;
    font-size: {FONT_SIZE}pt;
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {PINK};
    color: #ffffff;
}}

QCheckBox {{
    color: {TEXT};
    spacing: 10px;
    font-size: {FONT_SIZE}pt;
    min-height: 30px;
}}
QCheckBox::indicator {{
    width: 22px;
    height: 22px;
    border: 1px solid {BORDER};
    border-radius: 5px;
    background-color: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {PINK};
    border: 1px solid {PINK};
}}

QTextEdit, QListWidget {{
    background-color: #fffafd;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    font-size: {FONT_SIZE_SMALL}pt;
    padding: 6px;
}}

QProgressBar {{
    background-color: {BAR_BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    text-align: center;
    color: {TEXT};
    height: 24px;
    font-size: {FONT_SIZE_SMALL}pt;
}}
QProgressBar::chunk {{
    background-color: {PINK};
    border-radius: 6px;
}}

QStatusBar {{
    background-color: {BG_ALT};
    color: {TEXT_DIM};
    font-size: {FONT_SIZE_SMALL}pt;
}}

QScrollBar:vertical {{
    background: {BG};
    width: 14px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {PINK_LIGHT};
    border-radius: 7px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {PINK};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def style_combo_popup(combo):
    """给下拉框的弹出列表设色（近白粉底 + 深梅紫字）。

    只动调色板和样式表，不动 delegate —— 自定义 delegate 在
    PyQt5 上会破坏内部信号连接并导致段错误（已踩过）。
    """
    try:
        from PyQt5.QtGui import QColor, QPalette

        view = combo.view()
        pal = view.palette()
        pal.setColor(QPalette.Base, QColor(BG_INPUT))
        pal.setColor(QPalette.Text, QColor(TEXT))
        pal.setColor(QPalette.Window, QColor(BG_INPUT))
        pal.setColor(QPalette.WindowText, QColor(TEXT))
        pal.setColor(QPalette.Highlight, QColor(PINK))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        view.setPalette(pal)
        view.setStyleSheet(f"""
            QAbstractItemView {{
                background-color: {BG_INPUT};
                color: {TEXT};
                selection-background-color: {PINK};
                selection-color: #ffffff;
                border: 1px solid {BORDER};
                outline: 0;
            }}
            QAbstractItemView::item {{
                color: {TEXT};
                background-color: {BG_INPUT};
                min-height: 24px;
                padding-left: 6px;
            }}
            QAbstractItemView::item:selected {{
                background-color: {PINK};
                color: #ffffff;
            }}
        """)
    except Exception:  # noqa: BLE001
        pass
