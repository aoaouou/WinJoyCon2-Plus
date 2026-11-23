# -*- coding: utf-8 -*-
"""
WinJoyCon2-Plus GUI —— 把 Joy-Con 2 (BLE) 桥接成 Switch 1 的 Joy-Con 1 (USB/IP)

1.0 正式版。
"""

import sys
import asyncio

# ── 应用标识（1.0 正式版）─────────────────────────────────
APP_NAME = "WinJoyCon2-Plus"
APP_VERSION = "1.2"
APP_TITLE = f"{APP_NAME} v{APP_VERSION} · Joy-Con 2 → Joy-Con 1"

from PyQt5.QtWidgets import (
    QStyledItemDelegate,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QCheckBox,
    QProgressBar, QFrame, QSplitter, QMessageBox, QSystemTrayIcon, QMenu,
    QComboBox, QFormLayout, QDialog, QGridLayout, QListWidget, QListWidgetItem,
    QScrollArea, QTabWidget, QDoubleSpinBox, QLineEdit, QStackedWidget, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QMetaObject, QPoint, Q_ARG, QEvent, QObject
from PyQt5.QtGui import (QFont, QIcon, QPixmap, QPainter, QColor, QBrush,
                         QPolygon, QPen, QPalette)

import os

# Import logging module
from logger_config import info, warning, error, debug
import i18n
from i18n import tr
import theme

# Import controller manager
from controller_manager import get_controller_manager
from config import Config
from app_paths import app_path, config_path  # noqa: E402




def fix_combo_popup(combo):
    """让下拉框弹出列表可读（深梅紫底 + 浅粉字）。

    只动调色板和样式表，**不用自定义 delegate** ——
    QStyledItemDelegate 子类在 PyQt5 上会破坏内部信号连接导致段错误。
    """
    theme.style_combo_popup(combo)


class _NoWheelComboFilter(QObject):
    """事件过滤器：让 QComboBox / QSpinBox 上的滚轮不改值，而是透传给父 QScrollArea 滚动页面。
    用户想滚页面，却因为鼠标停在下拉框上变成改选项——这个过滤器解决它。"""
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QDoubleSpinBox)):
            # 找到最近的 QScrollArea，把滚轮事件转给它
            p = obj.parent()
            while p is not None:
                if isinstance(p, QScrollArea):
                    QApplication.sendEvent(p, event)
                    return True
                p = p.parent()
            return True   # 找不到滚动区也吞掉，至少不改选项
        return False


class _HelpDialog(QDialog):
    """纯文本使用说明弹窗。"""
    def __init__(self, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 420)
        lay = QVBoxLayout(self)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(text)
        te.setStyleSheet("color:#5c2340; background:#fffafd; border:1px solid #f3a8c9;"
                         " border-radius:6px; font-size:13px;")
        lay.addWidget(te)
        btn = QPushButton(tr("关闭"))
        btn.clicked.connect(self.accept)
        lay.addWidget(btn)


class InputSettingsWidget(QWidget):
    """内嵌的三页面输入设置：鼠标 / 陀螺仪鼠标 / 宏，页面内跳转不弹新窗口。"""

    @staticmethod
    def action_items():
        return [(tr("不映射"), ""), (tr("鼠标左键"), "left"), (tr("鼠标右键"), "right"),
                (tr("鼠标中键"), "middle"), (tr("前进(X2)"), "forward"),
                (tr("后退(X1)"), "back"), (tr("滚轮上"), "scroll_up"),
                (tr("滚轮下"), "scroll_down"), (tr("光标回中心"), "center")]

    @staticmethod
    def button_items():
        # 系统功能键不可自定义、不可录宏：C键=模式切换/宏；+/-=DPI
        return [(tr("左肩键 L"), ["L"]), (tr("左扳机 ZL"), ["ZL"]),
                (tr("左摇杆按下 L3"), ["L3"]), (tr("截图键"), ["Capture"]),
                (tr("十字 上"), ["Up"]), (tr("十字 下"), ["Down"]),
                (tr("十字 左"), ["Left"]), (tr("十字 右"), ["Right"]),
                (tr("左手柄 SL"), ["SLL"]), (tr("左手柄 SR"), ["SRL"]),
                (tr("右肩键 R"), ["R"]), (tr("右扳机 ZR"), ["ZR"]),
                (tr("右摇杆按下 R3"), ["R3"]), (tr("HOME 键"), ["Home"]),
                ("A", ["A"]), ("B", ["B"]), ("X", ["X"]), ("Y", ["Y"]),
                (tr("右手柄 SL"), ["SLR"]), (tr("右手柄 SR"), ["SRR"])]

    HELP = {
        "mouse": "【鼠标模式说明】\n\n切换：按住右手柄 C 键，再按 R → 右手柄进鼠标模式；按 L → 左手柄进鼠标模式。\n退出：再次按同一组合键（如 C+R）→ 回手柄模式；或长按 C 键 2 秒全部复位。\n\n操作：\n  • 平放手柄滑动 = 移动光标（光学传感器）\n  • 摇杆前/后 = 滚动（推得越狠越快）\n  • 按键功能在「自定义按键」页设置（默认 L/R=左键、ZL/ZR=右键、截图/HOME=中键、十字键或XYAB=前进后退）\n  • 灵敏度四挡 800/1600/3200/6400，默认第2挡\n\n固定功能键（不可自定义、不可录宏）：\n  • 加键 + / 减键 −：永远只调灵敏度挡位\n  • C 键：永远只做模式切换/宏触发\n",
        "gyro": "【陀螺仪鼠标说明 · 超级马力欧银河 NS 版逻辑】\n\n切换：按住 C 键，再按 ZL → 左手柄陀螺仪；按 ZR → 右手柄陀螺仪。\n退出：再次按同一组合键（如 C+ZR）→ 回手柄模式；或长按 C 键 2 秒全部复位。\n\n操作逻辑（银河式）：\n  • 手柄侧放，绕竖直轴左右转动 = 光标水平移动\n  • 绕长轴前后俯仰 = 光标垂直移动\n  • 转动越快光标移动越快，停手即停（角速度积分，非倾斜绝对角度）\n\n因握持姿势与光学鼠标不同，按键功能请在「自定义按键」页单独设置；灵敏度用下方「陀螺仪灵敏度」调节（默认值已按银河手感标定）。",
        "macro": "【宏系统说明】\n\n开启：勾选下方「启用宏系统」（默认关闭）。\n\n录制：\n  1. 选好宏名称与绑定键（左手柄 SL/SR、右手柄 SL/SR 四选一）\n  2. 点「开始录制」，依次按下想录的动作键\n  3. 点「停止保存」，宏即绑定到该 SL/SR 键\n\n触发：按住 C 键 + 对应 SL/SR 键 → 回放该宏。\n\n所有自定义按键与宏都会自动保存到配置，重启后保留。四个 SL/SR 键可各绑一个宏。",
    }

    def __init__(self, pair_id, parent=None):
        super().__init__(parent)
        self.pair_id = pair_id
        import control_type.mouse_mode as mm
        self.mm = mm
        # 本控件只提供「鼠标/陀螺仪/宏」三个页面，由外层 ControllerPairTab 的
        # QStackedWidget 统一切换（页0=主界面，页1/2/3=这三个）。
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.stack.addWidget(self._wrap_scroll(self._mouse_page()))
        self.stack.addWidget(self._wrap_scroll(self._gyro_page()))
        self.stack.addWidget(self._wrap_scroll(self._macro_page()))
        self._wheel_filter = _NoWheelComboFilter(self)
        for w in self.findChildren((QComboBox, QDoubleSpinBox)):
            w.installEventFilter(self._wheel_filter)
        self._refresh()

    def _wrap_scroll(self, widget):
        from PyQt5.QtWidgets import QSizePolicy
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(widget)
        sa.setMinimumHeight(360)
        sa.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 滚动条留边，避免遮挡右侧内容
        sa.setStyleSheet(
            "QScrollArea { border: none; }"
            "QScrollBar:vertical { width: 14px; margin: 0; background:#fff5fa; }"
            "QScrollBar::handle:vertical { background:#ffb8d8; border-radius:7px; min-height:24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }")
        return sa

    def _nav_bar(self, title, help_key):
        """每页顶部：返回 + 标题 + 使用说明。返回由外层 ControllerPairTab 回主页。"""
        row = QHBoxLayout()
        back = QPushButton(tr("← 返回"))
        back.clicked.connect(self._back_to_home)
        row.addWidget(back)
        lbl = QLabel(title)
        lbl.setStyleSheet("color:#ff6fae; font-size:15px; font-weight:bold;")
        row.addWidget(lbl)
        row.addStretch()
        help_btn = QPushButton(tr("❓ 使用说明"))
        help_btn.clicked.connect(lambda: _HelpDialog(title + " · " + tr("使用说明"),
                                                      tr(self.HELP[help_key]), self).exec_())
        row.addWidget(help_btn)
        w = QWidget()
        w.setLayout(row)
        return w

    def _back_to_home(self):
        """通知外层 ControllerPairTab 切回主页面（页0）。"""
        p = self.parent()
        while p is not None:
            if hasattr(p, "show_home_page"):
                p.show_home_page()
                return
            p = p.parent()

    # ── 鼠标页 ───────────────────────────────────────────────────────────
    def _mouse_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._nav_bar(tr("鼠标模式"), "mouse"))
        mg = QGroupBox(tr("当前模式"))
        mf = QFormLayout()
        self.mode_left_combo = self._mode_combo("mode_left")
        self.mode_right_combo = self._mode_combo("mode_right")
        mf.addRow(tr("左手柄") + ":", self.mode_left_combo)
        mf.addRow(tr("右手柄") + ":", self.mode_right_combo)
        mg.setLayout(mf)
        lay.addWidget(mg)
        og = QGroupBox(tr("动作开关"))
        of = QFormLayout()
        for label, key in ((tr("启用滚轮"), "mouse_scroll"), (tr("反转滚轮方向"), "mouse_scroll_rev")):
            cb = QCheckBox(label)
            cb.setChecked(bool(self.mm.get_option(self.pair_id, key)))
            cb.stateChanged.connect(lambda s, k=key: self.mm.set_option(
                self.pair_id, k, s == Qt.Checked, persist=True))
            of.addRow("", cb)
        og.setLayout(of)
        lay.addWidget(og)
        lay.addWidget(QLabel(tr("灵敏度挡位：{s}（加减键切换，可在自定义按键页改键）", s=self.mm.get_dpi_label(self.pair_id))))
        lay.addWidget(self._keymap_group(self.mm.MODE_MOUSE, "鼠标模式按键映射"))
        lay.addStretch()
        return w

    # ── 陀螺仪页 ─────────────────────────────────────────────────────────
    def _gyro_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._nav_bar(tr("陀螺仪鼠标模式"), "gyro"))
        og = QGroupBox(tr("陀螺仪设置"))
        of = QFormLayout()
        gs = QDoubleSpinBox()
        gs.setRange(0.1, 5.0)
        gs.setSingleStep(0.1)
        gs.setValue(float(self.mm.get_option(self.pair_id, "gyro_scale")))
        gs.valueChanged.connect(lambda v: self.mm.set_option(
            self.pair_id, "gyro_scale", v, persist=True))
        of.addRow(tr("灵敏度") + ":", gs)
        for label, key in ((tr("反转水平"), "gyro_invert_x"), (tr("反转垂直"), "gyro_invert_y")):
            cb = QCheckBox(label)
            cb.setChecked(bool(self.mm.get_option(self.pair_id, key)))
            cb.stateChanged.connect(lambda s, k=key: self.mm.set_option(
                self.pair_id, k, s == Qt.Checked, persist=True))
            of.addRow("", cb)
        # 模拟器兼容模式（热切换，立即生效）：不同模拟器对重复缓存帧的积分不同
        from virtual.imu_proc import get_imu_compat_mode, set_imu_compat_mode
        compat = QComboBox()
        compat.addItem(tr("Ryujinx（默认）"), "ryujinx")
        compat.addItem(tr("Eden"), "eden")
        ci = compat.findData(get_imu_compat_mode())
        compat.setCurrentIndex(ci if ci >= 0 else 0)
        compat.currentIndexChanged.connect(
            lambda i, c=compat: set_imu_compat_mode(c.itemData(i), persist=True))
        of.addRow(tr("模拟器兼容") + ":", compat)
        hint = QLabel(tr("体感太快选 Eden，太慢/正常保持 Ryujinx。切换立即生效，无需重连。"))
        hint.setStyleSheet("color:#96617f; font-size:11px;")
        hint.setWordWrap(True)
        of.addRow("", hint)
        og.setLayout(of)
        lay.addWidget(og)
        lay.addWidget(self._keymap_group(self.mm.MODE_GYRO, "陀螺仪鼠标模式按键映射"))
        lay.addStretch()
        return w

    # ── 宏页 ─────────────────────────────────────────────────────────────
    def _macro_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._nav_bar(tr("宏系统"), "macro"))
        en = QCheckBox(tr("启用宏系统（C+SL/SR 触发）"))
        en.setChecked(bool(self.mm.get_option(self.pair_id, "macro_enabled")))
        en.stateChanged.connect(lambda s: self.mm.set_option(
            self.pair_id, "macro_enabled", s == Qt.Checked, persist=True))
        lay.addWidget(en)

        # 显示已保存的宏
        saved = self.mm.get_config(self.pair_id).get("macro_bindings", {})
        if saved:
            txt = "已绑定：\n" + "\n".join(f"  {k} → {v}" for k, v in saved.items())
        else:
            txt = "暂无已保存的宏。"
        self.macro_status = QLabel(txt)
        self.macro_status.setStyleSheet("color:#5c2340; background:#fff5fa; border:1px solid #f3a8c9;"
                                        " border-radius:6px; padding:8px;")
        self.macro_status.setWordWrap(True)
        lay.addWidget(self.macro_status)

        lay.addWidget(QLabel(tr("宏名称:")))
        self.macro_name = QLineEdit("macro1")
        lay.addWidget(self.macro_name)
        lay.addWidget(QLabel(tr("绑定到 SL/SR 键:")))
        self.macro_bind_combo = QComboBox()
        for label, val in ((tr("左手柄 SL"), "sll"), (tr("左手柄 SR"), "srl"),
                           (tr("右手柄 SL"), "slr"), (tr("右手柄 SR"), "srr")):
            self.macro_bind_combo.addItem(label, val)
        lay.addWidget(self.macro_bind_combo)
        row = QHBoxLayout()
        rec = QPushButton(tr("● 开始录制"))
        stop = QPushButton(tr("■ 停止保存"))
        rec.clicked.connect(self._on_rec_start)
        stop.clicked.connect(self._on_rec_stop)
        row.addWidget(rec)
        row.addWidget(stop)
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _on_rec_start(self):
        bind = self.macro_bind_combo.currentData()
        self.mm.start_macro_record(self.pair_id, trigger=bind)
        self.macro_status.setText(tr("录制中 → {b}（现在按手柄的动作键会被记录）", b=bind))

    def _on_rec_stop(self):
        name = self.mm.stop_macro_record(self.pair_id, name=self.macro_name.text().strip())
        if name:
            saved = self.mm.get_config(self.pair_id).get("macro_bindings", {})
            self.macro_status.setText(tr("已绑定：\n") + "\n".join(
                f"  {k} → {v}" for k, v in saved.items()))

    # ── 通用组件 ─────────────────────────────────────────────────────────
    def _mode_combo(self, key):
        cb = QComboBox()
        for label, val in ((tr("手柄模式"), "gamepad"), (tr("鼠标模式"), "mouse"),
                           (tr("陀螺仪鼠标"), "gyro")):
            cb.addItem(label, val)
        idx = cb.findData(self.mm.get_config(self.pair_id)[key])
        cb.setCurrentIndex(idx if idx >= 0 else 0)
        cb.currentIndexChanged.connect(lambda i, k=key, c=cb: self.mm.set_option(
            self.pair_id, k, c.itemData(i), persist=True))
        return cb

    def _keymap_group(self, mode, title):
        grp = QGroupBox(title)
        form = QFormLayout()
        km = self.mm.get_keymap(self.pair_id, mode)
        combos = []
        for label, bnames in self.button_items():
            combo = QComboBox()
            for alab, aval in self.action_items():
                combo.addItem(alab, aval)
            cur = next((km[b] for b in bnames if b in km), "")
            ci = combo.findData(cur)
            combo.setCurrentIndex(ci if ci >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda i, bn=bnames, md=mode, c=combo: self._on_key_map(md, bn, c.itemData(i)))
            combos.append((bnames, combo))
            form.addRow(label, combo)
        reset = QPushButton(tr("↩ 还原默认按键"))
        reset.clicked.connect(lambda: (self.mm.reset_keymap(self.pair_id, mode, persist=True),
                                       self._refresh()))
        form.addRow("", reset)
        grp.setLayout(form)
        return grp

    def _on_key_map(self, mode, bnames, action):
        km = self.mm.get_keymap(self.pair_id, mode)
        for b in bnames:
            if action:
                km[b] = action
            else:
                km.pop(b, None)
        self.mm.set_keymap(self.pair_id, mode, km, persist=True)

    def _refresh(self):
        """从配置重新同步模式下拉（组合键切换后调用可让 GUI 跟上）。"""
        cfg = self.mm.get_config(self.pair_id)
        for combo, key in ((getattr(self, "mode_left_combo", None), "mode_left"),
                           (getattr(self, "mode_right_combo", None), "mode_right")):
            if combo is None:
                continue
            idx = combo.findData(cfg[key])
            if idx >= 0 and combo.currentIndex() != idx:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)


# 兼容旧名字（若别处还引用 MouseSettingsDialog）
MouseSettingsDialog = InputSettingsWidget

class ControllerPairTab(QWidget):
    """Tab page for a single controller pair"""
    
    def __init__(self, pair_id, parent=None):
        super().__init__(parent)
        self.pair_id = pair_id
        self.init_ui()
    
    def init_ui(self):
        """页0 = 主页面（连接状态+按钮+日志）；页1/2/3 = 鼠标/陀螺仪/宏设置。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ══════════ 页 0：主页面 ══════════
        home = QWidget()
        layout = QVBoxLayout(home)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # Connection status group
        status_group = QGroupBox(tr("连接状态"))
        self._status_group = status_group
        status_layout = QVBoxLayout()
        
        # Mode display
        self.mode_label = QLabel(tr("未连接"))
        self.mode_label.setStyleSheet("color: gray; font-size: 16px; font-weight: bold;")
        self.mode_label.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.mode_label)
        
        # Left and Right status
        joycon_layout = QHBoxLayout()
        
        # Left Joy-Con
        left_group = QGroupBox(tr("左手柄"))
        left_layout = QVBoxLayout()
        self.left_status = QLabel(tr("未连接"))
        self.left_status.setStyleSheet("color: gray;")
        self.left_status.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.left_status)
        self.left_battery = QProgressBar()
        self.left_battery.setRange(0, 100)
        self.left_battery.setValue(0)
        self.left_battery.setTextVisible(True)
        self.left_battery.setStyleSheet("""
            QProgressBar {
                border: 1px solid gray;
                border-radius: 8px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #ff6fae;
            }
        """)
        left_layout.addWidget(self.left_battery)
        left_group.setLayout(left_layout)
        joycon_layout.addWidget(left_group)
        
        # Right Joy-Con
        right_group = QGroupBox(tr("右手柄"))
        right_layout = QVBoxLayout()
        self.right_status = QLabel(tr("未连接"))
        self.right_status.setStyleSheet("color: gray;")
        self.right_status.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.right_status)
        self.right_battery = QProgressBar()
        self.right_battery.setRange(0, 100)
        self.right_battery.setValue(0)
        self.right_battery.setTextVisible(True)
        self.right_battery.setStyleSheet("""
            QProgressBar {
                border: 1px solid gray;
                border-radius: 8px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #ff6fae;
            }
        """)
        right_layout.addWidget(self.right_battery)
        right_group.setLayout(right_layout)
        joycon_layout.addWidget(right_group)
        
        status_layout.addLayout(joycon_layout)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # 连接模式/输入模式开关/震动开关均已移除（项目简化）：
        # 始终双手柄连接、震动默认开启、输入模式设置面板常驻显示。

        # 设置控件容器（三个页面），稍后加入 pages 作为页1/2/3
        self.input_panel = InputSettingsWidget(self.pair_id, self)
        self.input_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Control buttons for this pair
        btn_layout = QHBoxLayout()
        
        self.add_btn = QPushButton(tr("⚡ 一键连接手柄"))
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #c4407c;
                color: #5c2340;
                border: none;
                border-radius: 5px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #e04a8f;
            }
        """)
        
        self.disconnect_btn = QPushButton(tr("- 断开手柄"))
        self.disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff5f97;
                color: #5c2340;
                border: none;
                border-radius: 5px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #c42f6b;
            }
        """)
        
        self.calib_btn = QPushButton(tr("🎯 摇杆说明"))
        self.calib_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffa6cd;
                color: #5c2340;
                border: none;
                border-radius: 5px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #ff8fbe;
            }
        """)
        self.calib_btn.clicked.connect(self.on_calibrate_gyro)

        # 1.1 分开连接：陌生手柄必须手动选左/右，连上后记住
        self.add_separate_btn = QPushButton(tr("🔀 分开连接"))
        # 三个模式入口：分别直达页1/2/3
        self.mouse_page_btn = QPushButton(tr("🖱 鼠标模式"))
        self.gyro_page_btn = QPushButton(tr("🌀 陀螺仪鼠标"))
        self.macro_page_btn = QPushButton(tr("⚙ 宏系统"))
        for b, idx in ((self.mouse_page_btn, 1), (self.gyro_page_btn, 2), (self.macro_page_btn, 3)):
            b.setStyleSheet(
                "QPushButton { background:#f7c5db; color:#5c2340; border:1px solid #f3a8c9;"
                " border-radius:5px; padding:10px; }"
                "QPushButton:hover { background:#ffd9e9; }")
            b.clicked.connect(lambda _, i=idx: self.show_page(i))
        self.settings_btn = self.mouse_page_btn   # 兼容旧引用
        self.add_separate_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffd9e9; color: #5c2340;
                border: 1px solid #f3a8c9; border-radius: 5px; padding: 10px;
            }
            QPushButton:hover { background-color: #ffb8d8; }
        """)
        # 按钮分三行：连接 / 模式入口 / 其它，避免挤在一行
        row1 = QHBoxLayout()
        row1.addWidget(self.add_btn)
        row1.addWidget(self.add_separate_btn)
        row2 = QHBoxLayout()
        row2.addWidget(self.mouse_page_btn)
        row2.addWidget(self.gyro_page_btn)
        row2.addWidget(self.macro_page_btn)
        row3 = QHBoxLayout()
        row3.addWidget(self.calib_btn)
        row3.addWidget(self.disconnect_btn)
        btns = QWidget()
        bl = QVBoxLayout(btns)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        bl.addLayout(row1)
        bl.addLayout(row2)
        bl.addLayout(row3)
        self._btn_bar = btns
        layout.addWidget(btns)
        self._refresh_connect_mode()
        
        # Log output for this pair
        log_group = QGroupBox(tr("手柄组日志"))
        self._log_group = log_group
        log_layout = QVBoxLayout()
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.document().setMaximumBlockCount(100)  # Limit log lines
        self.log_output.setStyleSheet("""
            QTextEdit {
                background-color: #fffafd;
                color: #5c2340;
                border: 1px solid #f3a8c9;
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 13px;
            }
        """)
        # 日志区吃掉剩余全部高度，不再固定 90px 留空白
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.document().setMaximumBlockCount(200)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background-color: #fffafd;
                color: #5c2340;
                border: 1px solid #f3a8c9;
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 13px;
            }
        """)
        self.log_output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)   # stretch=1：日志填满剩余空间

        # ══════════ 组装：复用 input_panel.stack 作为 4 页容器 ══════════
        # 不再另建 pages + reparent（那会触发 C++ 层崩溃），直接把主页面
        # insert 到 input_panel.stack 的最前面：0=主页面 1=鼠标 2=陀螺仪 3=宏
        self.pages = self.input_panel.stack
        self.pages.insertWidget(0, home)
        # input_panel 外层 layout 只用来承载 stack，直接把整个 input_panel 放进 outer
        outer.addWidget(self.input_panel)
        self.setLayout(outer)
        self.pages.setCurrentIndex(0)   # 默认显示主页面

    def show_page(self, idx: int):
        """切换到指定页（0=主页面，1=鼠标，2=陀螺仪，3=宏）。"""
        if 0 <= idx < self.pages.count():
            self.pages.setCurrentIndex(idx)
            if idx > 0 and hasattr(self, "input_panel"):
                self.input_panel._refresh()

    def show_home_page(self):
        self.show_page(0)

    def set_focus_mode(self, focused: bool):
        """兼容旧调用：True=进设置页，False=回主页。"""
        self.show_page(1 if focused else 0)
    
    @staticmethod
    def _set_battery_display(progress_bar, battery_level, connected, is_charging=False):
        color = "#777777"
        if not connected:
            progress_bar.setFormat("%p%")
            progress_bar.setValue(0)
        elif battery_level is None:
            progress_bar.setValue(0)
            progress_bar.setFormat("未知")
        else:
            progress_bar.setFormat("充电中 %p%" if is_charging else "%p%")
            progress_bar.setValue(max(0, min(100, int(battery_level))))
            if is_charging:
                color = "#ff6fae"
            elif battery_level <= 11:
                color = "#ff5f97"
            elif battery_level <= 33:
                color = "#ffa6cd"
            else:
                color = "#ff6fae"
        progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid gray;
                border-radius: 8px;
                text-align: center;
                height: 20px;
            }}
            QProgressBar::chunk {{ background-color: {color}; }}
        """)

    def update_status(self, pair):
        """Update display with pair status"""
        if not pair or not pair.is_active():
            self.mode_label.setText(tr("未连接"))
            self.mode_label.setStyleSheet("color: gray; font-size: 16px; font-weight: bold;")
            self.left_status.setText(tr("未连接"))
            self.left_status.setStyleSheet("color: gray;")
            self._set_battery_display(self.left_battery, None, False)
            self.right_status.setText(tr("未连接"))
            self.right_status.setStyleSheet("color: gray;")
            self._set_battery_display(self.right_battery, None, False)
            return
        
        # Update mode
        mode_text = pair.get_mode_display()
        self.mode_label.setText(mode_text)
        
        if pair.mode.value == 3:  # BOTH
            self.mode_label.setStyleSheet("color: #ff6fae; font-size: 16px; font-weight: bold;")
        elif pair.mode.value in [1, 2]:  # LEFT_ONLY or RIGHT_ONLY
            self.mode_label.setStyleSheet("color: #c4407c; font-size: 16px; font-weight: bold;")
        else:
            self.mode_label.setStyleSheet("color: gray; font-size: 16px; font-weight: bold;")
        
        # Update Left
        if pair.left.is_connected:
            self.left_status.setText(tr("已连接"))
            self.left_status.setStyleSheet("color: #ff6fae;")
            self._set_battery_display(
                self.left_battery, pair.left.battery_level, True, pair.left.is_charging
            )
        else:
            self.left_status.setText(tr("未连接"))
            self.left_status.setStyleSheet("color: gray;")
            self._set_battery_display(self.left_battery, None, False)
        
        # Update Right
        if pair.right.is_connected:
            self.right_status.setText(tr("已连接"))
            self.right_status.setStyleSheet("color: #ff6fae;")
            self._set_battery_display(
                self.right_battery, pair.right.battery_level, True, pair.right.is_charging
            )
        else:
            self.right_status.setText(tr("未连接"))
            self.right_status.setStyleSheet("color: gray;")
            self._set_battery_display(self.right_battery, None, False)

    def sync_input_modes(self):
        """供状态定时器调用：组合键切换后让 GUI 模式下拉跟随。"""
        if self.input_panel is not None:
            self.input_panel._refresh()


    def set_focus_mode(self, focused: bool):
        """专注模式：设置面板独占整个 tab（隐藏连接状态/按钮/日志）。"""
        for attr in ("_status_group", "_btn_bar", "_log_group"):
            w = getattr(self, attr, None)
            if w is not None:
                w.setVisible(not focused)
        if hasattr(self, "input_panel") and self.input_panel is not None:
            self.input_panel.setVisible(focused)
            self.input_panel.setMinimumHeight(0 if focused else 360)

    def _refresh_connect_mode(self):
        """1.1：左右未认清时禁用一键连接，强制走分开连接。"""
        try:
            import usbip_setup
            calibrated = usbip_setup.sides_calibrated()
        except Exception:
            calibrated = True   # 模块异常时不阻挡用户
        self.add_btn.setEnabled(bool(calibrated))
        if hasattr(self, "add_separate_btn"):
            # 分开连接永远可用：随时可纠正选错的左右，不限首次
            self.add_separate_btn.setEnabled(True)
            tip = (tr("一键连接（左右已记忆）") if calibrated else
                   tr("左右未记忆，请先分开连接"))
            self.add_btn.setToolTip(tip)
            self.add_separate_btn.setToolTip(
                tr("随时手动选左/右（可纠正之前选错的），连接后记住"))

    def on_calibrate_gyro(self):
        """摇杆说明（沿用旧槽名）。

        摇杆数据原样透传：JC2 raw 就是 12 位满量程，
        虚拟设备的 0x3F 报告用 4 个 16 位轴（X/Y/Rx/Ry, logical 0..65535）
        承载模拟量，由主机的 gamepad 驱动按 0x8000 中心归一化。
        不做任何中间层变换 —— 那会与主机映射二次叠加导致变形。
        """
        QMessageBox.information(
            self, "摇杆（原样透传）",
            "摇杆数据直接透传，由系统 gamepad 驱动归一化。\n\n"
            "* 12 位输入映射到 0x3F 报告的 16 位轴（0x8000 = 中心）\n"
            "* 圆度、死区由游戏/模拟器的摇杆设置决定\n"
            "* 无需手动标定\n\n"
            "如果感觉死区偏大或响应曲线不线性，那是游戏/模拟器自身的"
            "摇杆设置，请检查其死区与响应曲线选项。")

    def log_message(self, message):
        """Add message to this pair's log output"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")
        # Auto scroll to bottom
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_log(self):
        """Clear this pair's log output"""
        self.log_output.clear()


class ScanThread(QThread):
    """Thread for scanning Joy-Cons"""
    scan_finished = pyqtSignal(list)
    scan_error = pyqtSignal(str)

    def __init__(self, include_connected=False):
        super().__init__()
        self.include_connected = include_connected

    def run(self):
        """Run the scan"""
        try:
            import main
            # Run async scan in new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Scan for first device（分开连接时允许扫已连接手柄）
            device = loop.run_until_complete(
                main.scan_for_joycons(include_connected=self.include_connected))
            loop.close()
            
            # Convert to list format for compatibility
            devices = []
            if device:
                mac = device.address
                device_name = device.name if device.name else "Joy-Con"
                
                # Detect side from name - comprehensive detection
                side = "Unknown"
                if device_name:
                    name_upper = device_name.upper()
                    # Check for Joy-Con (L) / Joy-Con (R) pattern
                    if '(L)' in name_upper or 'LEFT' in name_upper or name_upper.endswith(' L') or ' L ' in name_upper:
                        side = 'Left'
                    elif '(R)' in name_upper or 'RIGHT' in name_upper or name_upper.endswith(' R') or ' R ' in name_upper:
                        side = 'Right'
                    # Also check for "Joy-Con L" or "Joy-Con R" without parentheses
                    elif 'JOY' in name_upper:
                        if ' L' in name_upper or name_upper.endswith('L'):
                            side = 'Left'
                        elif ' R' in name_upper or name_upper.endswith('R'):
                            side = 'Right'
                
                devices.append({
                    'name': device_name,
                    'address': device.address,
                    'mac': mac,
                    'side': side,
                    'rssi': -50,  # Default RSSI
                    'device': device
                })
                
                debug(f"Scan found: {device_name} ({side}) [{mac}]")
            
            self.scan_finished.emit(devices)
        except Exception as e:
            self.scan_error.emit(str(e))


class ConnectThread(QThread):
    """Thread for connecting to a Joy-Con"""
    connect_finished = pyqtSignal(str, int, bool)  # device_name, pair_id, success
    connect_error = pyqtSignal(str, int, str)  # device_name, pair_id, error

    def __init__(self, device_info, pair_id, mode="both"):
        super().__init__()
        self.device_info = device_info
        self.pair_id = pair_id
        self.mode = mode

    def run(self):
        """Run the connection using global event loop"""
        try:
            import main
            # Get or create the global event loop
            loop = main.get_event_loop()
            
            if not loop:
                # Create a new event loop if none exists (shouldn't happen)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                main.set_event_loop(loop)
            
            # Set mode in device_info
            self.device_info['mode'] = self.mode
            
            # Run connection in the global loop
            future = asyncio.run_coroutine_threadsafe(
                main.connect_device(self.device_info),
                loop
            )
            
            # Wait for result with timeout
            success = future.result(timeout=15.0)
            
            # Emit result
            self.connect_finished.emit(self.device_info.get('name', 'Unknown'), self.pair_id, success)
            
        except Exception as e:
            self.connect_error.emit(self.device_info.get('name', 'Unknown'), self.pair_id, str(e))


class _AutoConnectThread(QThread):
    """一键连接：扫描 -> 自动分左右 -> 连接两只手柄。

    整个过程不弹对话框，只发进度信号。
    """
    progress = pyqtSignal(str, str)      # side, mac
    finished_all = pyqtSignal(bool, str)  # 成功?, 消息

    def __init__(self, pair_id: int, parent=None):
        super().__init__(parent)
        self.pair_id = pair_id

    def run(self):
        try:
            import main
            loop = main.get_event_loop()
            if not loop:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                main.set_event_loop(loop)

            # ---- 1. 快速探测与扫描**并行** ----
            #
            # 实测：Joy-Con 的 BLE 广播周期很长，扫描经常要 20 秒才收到
            # 第一包（两只手柄都在 20s 后才出现）。而按 MAC 直连只要 2 秒。
            #
            # 所以不串行等待：两个任务同时跑，谁先拿到就用谁。
            # 已连上的那侧就不再等扫描。
            self.progress.emit("", "正在连接 ...")

            def on_prog(side, mac):
                self.progress.emit(side, mac)

            async def _parallel():
                """探测与扫描并行，谁先给结果用谁。

                ⚠ 2026-11-16 优化：
                  * 探测（按已知 MAC）现在立即返回，不等 connect 探活
                  * 扫描作为**补充**：若扫描到 device 对象，优先用它
                    （BleakClient 用 device 对象比纯 MAC 连得更快更稳）
                  * 扫描一旦两只都拿到就立即结束，不再干等 40 秒
                """
                probe_t = asyncio.ensure_future(
                    main._probe_known_macs(timeout=4.0))
                scan_t = asyncio.ensure_future(
                    main.scan_both_joycons(timeout=40.0, on_progress=on_prog))
                got = {"Left": None, "Right": None}

                def _fill(side, entry):
                    got[side] = entry

                while True:
                    # 两只都有 device 对象 = 最优结果，直接收工
                    if all(got[k] and got[k].get("device") for k in got):
                        break
                    # 两只都至少有 MAC，且扫描已结束 = 没更多信息了
                    if all(got.values()) and scan_t.done():
                        break

                    pending = [t for t in (probe_t, scan_t)
                               if not t.done()]
                    if not pending:
                        break

                    done, _ = await asyncio.wait(
                        pending, timeout=0.5,
                        return_when=asyncio.FIRST_COMPLETED)

                    if probe_t in done and not probe_t.cancelled():
                        try:
                            for side, mac in (probe_t.result() or {}).items():
                                if not got[side]:
                                    _fill(side, {"device": None,
                                                 "mac": mac, "name": "",
                                                 "side": side})
                                    self.progress.emit(side, f"{mac} 在线")
                        except Exception:
                            pass

                    if scan_t in done and not scan_t.cancelled():
                        try:
                            sl, sr = scan_t.result()
                            for side, item in (("Left", sl), ("Right", sr)):
                                if not item:
                                    continue
                                cur = got[side]
                                # 扫描到 device 对象时优先替换（连接更快更稳）
                                if cur is None or item.get("device"):
                                    _fill(side, item)
                                    if cur is not None:
                                        self.progress.emit(
                                            side, f"{item['mac']} 已定位")
                        except Exception:
                            pass

                for t in (probe_t, scan_t):
                    if not t.done():
                        t.cancel()
                return got["Left"], got["Right"]

            fut = asyncio.run_coroutine_threadsafe(_parallel(), loop)
            left, right = fut.result(timeout=50.0)

            if not left and not right:
                self.finished_all.emit(
                    False, "没有扫描到手柄。请按一下手柄任意键唤醒后重试。")
                return

            # ---- 2. 并行连接两只（不串行）----
            #
            # 原实现是 for 循环串行：左连完才连右，一只 BLE 连接 2~5 秒，
            # 两只就要 10 秒以上，用户感知"连接太慢"且"总是先左后右"。
            #
            # 实测 BLE 栈支持两只手柄同时连接（不同 MAC，无资源竞争），
            # 所以改成 asyncio.gather 并发，总耗时 ≈ 单只耗时。
            #
            # 并发还解决了另一个问题：串行时若左手的 connect 占住事件循环
            # 较久，右手的扫描结果可能过期，表现就是"只连上一个"。
            async def _connect_all():
                async def _one(item):
                    if not item:
                        return None
                    dev_info = {
                        "name": item["name"],
                        "address": item["mac"],
                        "mac": item["mac"],
                        "side": item["side"],
                        "rssi": -50,
                        "device": item["device"],
                        "mode": "both",
                    }
                    try:
                        ok = await main.connect_device(dev_info)
                        self.progress.emit(
                            item["side"],
                            f"{item['mac']} {'已连接' if ok else '失败'}")
                        return item["side"] if ok else None
                    except Exception as exc:
                        self.progress.emit(
                            item["side"], f"{item['mac']} 失败: {exc}")
                        return None

                results = await asyncio.gather(
                    _one(left), _one(right), return_exceptions=True)
                return [r for r in results
                        if isinstance(r, str)]

            fut2 = asyncio.run_coroutine_threadsafe(_connect_all(), loop)
            connected = fut2.result(timeout=40.0)
            ok_count = len(connected)

            if ok_count >= 2:
                self.finished_all.emit(True, "✓ 两只手柄都已连接")
            elif ok_count == 1:
                self.finished_all.emit(
                    True, "已连接 1 只手柄。另一只请确认已唤醒后再次点击连接。")
            else:
                self.finished_all.emit(False, "连接失败，请重试。")

        except Exception as e:
            self.finished_all.emit(False, f"连接异常: {e}")


class DisconnectThread(QThread):
    """Thread for disconnecting a pair"""
    disconnect_finished = pyqtSignal(int)  # pair_id
    disconnect_error = pyqtSignal(int, str)  # pair_id, error

    def __init__(self, pair_id):
        super().__init__()
        self.pair_id = pair_id

    def run(self):
        """Run the disconnection using global event loop"""
        try:
            import main
            # Get or create the global event loop
            loop = main.get_event_loop()
            
            if not loop:
                # Create a new event loop if none exists (shouldn't happen)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                main.set_event_loop(loop)
            
            # Run disconnect in the global loop
            future = asyncio.run_coroutine_threadsafe(
                main.disconnect_pair_by_id(self.pair_id),
                loop
            )
            
            # Wait for result with timeout
            future.result(timeout=5.0)
            
            # Emit result
            self.disconnect_finished.emit(self.pair_id)
            
        except Exception as e:
            self.disconnect_error.emit(self.pair_id, str(e))


class AddControllerDialog(QDialog):
    """Dialog for scanning and adding new controllers"""

    device_selected = pyqtSignal(dict)  # Signal emitted when device is selected

    def __init__(self, parent=None, connection_mode="both", pair_state=None, pair_id=None):
        super().__init__(parent)
        self.connection_mode = connection_mode  # "left", "right", "both"
        self.pair_state = pair_state or {}  # Current pair connection state
        self.pair_id = pair_id  # Store the pair_id (0-based)
        self.setWindowTitle(tr("添加手柄 - 手柄组 {n}", n=(pair_id + 1 if pair_id is not None else "?")))
        self.setGeometry(240, 200, 520, 320)
        self.setStyleSheet("""
            QDialog {
                background-color: #ffeaf3;
            }
            QLabel {
                color: #5c2340;
            }
        """)
        self.found_device = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Instructions based on connection mode
        mode_text = {
            "left": "请确保左手柄已关机\n然后长按同步按钮（顶部滑轨内侧小孔）3-5 秒\n直到指示灯左右滚动闪烁",
            "right": "请确保右手柄已关机\n然后长按同步按钮（顶部滑轨内侧小孔）3-5 秒\n直到指示灯左右滚动闪烁",
            "both": "请确保手柄已关机\n然后长按同步按钮（顶部滑轨内侧小孔）3-5 秒\n直到指示灯左右滚动闪烁"
        }
        
        # For dual mode, show which Joy-Con to connect
        if self.connection_mode == "both":
            # Check if any Joy-Con is already connected
            manager = get_controller_manager()
            pair = manager.get_pair(self.pair_id)
            
            if pair:
                left_connected = pair.left.is_connected
                right_connected = pair.right.is_connected
                
                if left_connected and not right_connected:
                    mode_text["both"] = "第一个手柄（左手柄）已连接\n\n请确保右手柄已关机\n然后长按同步按钮（顶部滑轨内侧小孔）3-5 秒\n直到指示灯左右滚动闪烁"
                elif right_connected and not left_connected:
                    mode_text["both"] = "第一个手柄（右手柄）已连接\n\n请确保左手柄已关机\n然后长按同步按钮（顶部滑轨内侧小孔）3-5 秒\n直到指示灯左右滚动闪烁"
                else:
                    mode_text["both"] = "双手柄模式\n\n请先连接左手柄或右手柄\n长按同步按钮 3-5 秒直到指示灯左右滚动闪烁"
        
        instructions = QLabel(mode_text.get(self.connection_mode, mode_text["both"]))
        instructions.setStyleSheet("color: #ff6fae; font-size: 15px; qproperty-alignment: AlignCenter;")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Status label
        self.status_label = QLabel(tr("请长按同步按钮..."))
        self.status_label.setStyleSheet("color: #c4407c; font-size: 14px; qproperty-alignment: AlignCenter;")
        layout.addWidget(self.status_label)
        
        # Side selection (if auto-detection fails)
        self.side_widget = QWidget()
        side_layout = QHBoxLayout()
        side_layout.setContentsMargins(0, 0, 0, 0)
        
        side_label = QLabel(tr("请选择手柄侧:"))
        side_label.setStyleSheet("color: #5c2340;")
        side_layout.addWidget(side_label)
        
        self.side_combo = QComboBox()
        self.side_combo.addItem(tr("左手柄 (L)"), "Left")
        self.side_combo.addItem(tr("右手柄 (R)"), "Right")
        # 浅粉底 + 深梅紫字，和整体主题一致。
        # 原先 background #444 + color #5c2340 两个都偏深，看不出差别。
        self.side_combo.setStyleSheet("""
            QComboBox {
                background-color: #fff5fa;
                color: #5c2340;
                border: 1px solid #f3a8c9;
                border-radius: 8px;
                padding: 0px 10px;
                min-height: 34px;
                font-size: 13pt;
            }
            QComboBox:hover {
                border: 1px solid #ff6fae;
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
            }
        """)
        fix_combo_popup(self.side_combo)
        side_layout.addWidget(self.side_combo)
        side_layout.addStretch()
        
        self.side_widget.setLayout(side_layout)
        self.side_widget.setVisible(False)  # Hidden by default
        layout.addWidget(self.side_widget)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.ok_btn = QPushButton(tr("连接"))
        self.ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff6fae;
                color: #5c2340;
                border: none;
                border-radius: 5px;
                padding: 10px 30px;
            }
            QPushButton:hover {
                background-color: #e04a8f;
            }
            QPushButton:disabled {
                background-color: #f3a8c9;
            }
        """)
        self.ok_btn.setEnabled(False)  # Disabled until device found
        
        self.ok_btn.clicked.connect(self.connect_device)
        
        cancel_btn = QPushButton(tr("取消"))
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f3a8c9;
                color: #5c2340;
                border: none;
                border-radius: 5px;
                padding: 10px 30px;
            }
            QPushButton:hover {
                background-color: #f3a8c9;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        
        # Auto-start scanning
        QTimer.singleShot(100, self.start_scan)
    
    def start_scan(self):
        """Start scanning for devices"""
        self.status_label.setText(tr("正在扫描...请长按同步按钮"))
        self.status_label.setStyleSheet("color: #c4407c;")
        
        # Run scan in background using QThread
        self.scan_thread = ScanThread(include_connected=getattr(self, "force_side_select", False))
        self.scan_thread.scan_finished.connect(self.on_scan_finished)
        self.scan_thread.scan_error.connect(self.on_scan_error)
        self.scan_thread.start()
    
    def on_scan_finished(self, devices):
        """Handle scan completion - show device and let user confirm side"""
        
        if devices:
            device = devices[0]
            self.found_device = device
            
            # Show device info
            side = device.get('side', 'Unknown')
            device_name = device.get('name', 'Unknown')
            
            if side != 'Unknown' and not getattr(self, "force_side_select", False):
                # Auto-detected side
                self.status_label.setText(f"找到：{device_name} ({side})")
                self.status_label.setStyleSheet("color: #ff6fae;")
                self.side_widget.setVisible(False)
            elif side != 'Unknown' and getattr(self, "force_side_select", False):
                # 分开连接模式：即使识别出侧也让用户确认
                self.status_label.setText(f"找到：{device_name} ({side}) — 请确认左右")
                self.status_label.setStyleSheet("color: #ff6fae;")
                self.side_combo.setCurrentIndex(0 if side == "Left" else 1)
                self.side_widget.setVisible(True)
            else:
                # Could not detect side - show selection
                self.status_label.setText(tr("找到设备，但无法识别左右"))
                self.status_label.setStyleSheet("color: #c4407c;")
                self.side_widget.setVisible(True)

                # Auto-select the opposite side based on what's already connected
                if self.connection_mode == "left":
                    self.side_combo.setCurrentIndex(0)  # Left
                elif self.connection_mode == "right":
                    self.side_combo.setCurrentIndex(1)  # Right
                elif self.connection_mode == "both":
                    # In dual mode, auto-select the side that isn't connected yet
                    manager = get_controller_manager()
                    pair = manager.get_pair(self.pair_id)
                    if pair:
                        if pair.left.is_connected and not pair.right.is_connected:
                            self.side_combo.setCurrentIndex(1)  # Right
                        elif pair.right.is_connected and not pair.left.is_connected:
                            self.side_combo.setCurrentIndex(0)  # Left
            
            # Enable connect button
            self.ok_btn.setEnabled(True)
            
        else:
            self.status_label.setText(tr("未找到设备，请重新长按同步按钮"))
            self.status_label.setStyleSheet("color: #ff5f97;")
            self.ok_btn.setEnabled(False)
            self.side_widget.setVisible(False)
    
    def on_scan_error(self, error_msg):
        """Handle scan error"""
        self.status_label.setText(f"扫描出错：{error_msg}")
        self.status_label.setStyleSheet("color: #ff5f97;")
    
    def connect_device(self):
        """Emit signal with device and close"""
        
        # Always use found_device
        device = self.found_device
        
        if device:
            # Only override side from combo box when the selection widget is visible
            # (i.e. auto-detection failed). Otherwise keep the auto-detected side.
            if self.side_widget.isVisible():
                selected_side = self.side_combo.currentData()
                device['side'] = selected_side

            # Add pair_id to device info
            if self.pair_id is not None:
                device['pair_id'] = self.pair_id

            self.device_selected.emit(device)

            # 分开连接流程：连上第一只后**不关闭窗口**，就地等第二只
            if getattr(self, "force_side_select", False):
                # 直接回调主窗口发起连接（不靠 exec_ 返回值）
                if hasattr(self, "on_device") and callable(self.on_device):
                    self.on_device(device)
                other = "Right" if device.get("side") == "Left" else "Left"
                self.status_label.setText(
                    tr("已连接{s1}手柄。请唤醒{s2}手柄并长按 SYNC，然后选侧连接。",
                       s1=tr("左") if device.get("side") == "Left" else tr("右"),
                       s2=tr("右") if other == "Right" else tr("左")))
                self.connected_sides = getattr(self, "connected_sides", set())
                self.connected_sides.add(device.get("side"))
                self.side_combo.setCurrentIndex(0 if other == "Left" else 1)
                self.ok_btn.setEnabled(False)
                self.found_device = None
                # 立刻重新扫描第二只（不等用户手点）
                QTimer.singleShot(1200, self.start_scan)
            else:
                self.accept()
        else:
            pass  # No device found


class Joy2WinGUI(QMainWindow):
    """Main GUI window for Joy2Win"""
    
    # Signal for thread-safe log updates
    log_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()

        # Global lock for adding controllers (prevent multiple tabs from scanning simultaneously)
        self.adding_controller_lock = False

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_controller_status)
        self.status_timer.start(1000)  # Update every second

        self.init_ui()
        self.setup_tray_icon()

    
    def init_ui(self):
        self.setWindowTitle(APP_TITLE)
        self.setGeometry(80, 60, theme.WIN_W, theme.WIN_H)
        self.setMinimumSize(720, 860)
        # 全局泡泡糖粉主题（颜色集中在 theme.py）
        self.setStyleSheet(theme.GLOBAL_QSS)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Set window icon
        self.setWindowIcon(QIcon(self.create_logo_pixmap()))

        # Title with logo
        title_layout = QHBoxLayout()
        logo_label = QLabel()
        logo_pixmap = self.create_logo_pixmap()
        logo_label.setPixmap(logo_pixmap)
        logo_label.setFixedSize(56, 56)
        logo_label.setScaledContents(True)
        title_layout.addWidget(logo_label)

        # 名称 + 版本 + 一句话说明（垂直排列，与 logo 并排）
        title_box = QVBoxLayout()
        title_box.setSpacing(0)

        name_label = QLabel(APP_NAME)
        name_label.setFont(QFont("Arial", 22, QFont.Bold))
        name_label.setStyleSheet("color: #ff6fae;")
        title_box.addWidget(name_label)

        ver_label = QLabel(f"v{APP_VERSION} · Joy-Con 2 → Joy-Con 1")
        ver_label.setFont(QFont("Arial", 9))
        ver_label.setStyleSheet("color: #96617f;")
        title_box.addWidget(ver_label)

        title_layout.addLayout(title_box)
        title_layout.addStretch()

        # 右上角语言选择：切换后写配置并提示重启
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("简体中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(0 if i18n.LANG == "zh" else 1)
        self.lang_combo.setStyleSheet(
            "QComboBox { padding:0px 8px; border:1px solid #f3a8c9; border-radius:8px;"
            " background:#fff5fa; color:#5c2340; }")
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        title_layout.addWidget(self.lang_combo)

        main_layout.addLayout(title_layout)
        
        # Tab widget for 4 controller pairs
        self.tab_widget = QTabWidget()
        self.controller_tabs = []
        
        for i in range(4):
            tab = ControllerPairTab(i)
            self.controller_tabs.append(tab)
            self.tab_widget.addTab(tab, tr("手柄组 {n}", n=i+1))
            
            # Connect tab buttons
            tab.add_btn.clicked.connect(lambda checked, idx=i: self.add_controller_to_pair(idx))
            tab.add_separate_btn.clicked.connect(
                lambda checked, idx=i: self.add_controller_separate(idx))
            tab.disconnect_btn.clicked.connect(lambda checked, idx=i: self.disconnect_pair(idx))
        
        main_layout.addWidget(self.tab_widget)

        # 1.1 USB/IP 状态条 + 常驻安装按钮（误删后可随时重装）
        import usbip_setup as _us
        usbip_bar = QHBoxLayout()
        self.usbip_status = QLabel()
        self.usbip_status.setStyleSheet("color:#5c2340;")
        usbip_bar.addWidget(self.usbip_status)
        usbip_bar.addStretch()
        self.install_usbip_btn = QPushButton(
            tr("🔧 一键安装 USB/IP") if _us.is_usbip_installed() is False
            else tr("🔧 重装/修复 USB/IP"))
        self.install_usbip_btn.setStyleSheet(
            "QPushButton { background:#ffd9e9; color:#5c2340; border:1px solid #f3a8c9;"
            " border-radius:5px; padding:4px 12px; }"
            "QPushButton:hover { background:#ffb8d8; }")
        self.install_usbip_btn.clicked.connect(self.on_install_usbip)
        usbip_bar.addWidget(self.install_usbip_btn)

        # 重置左右记忆：纯净测试 / 纠正选错左右
        self.reset_sides_btn = QPushButton(tr("🧹 重置左右记忆"))
        self.reset_sides_btn.setStyleSheet(
            "QPushButton { background:#fff0f7; color:#5c2340; border:1px solid #f3a8c9;"
            " border-radius:5px; padding:4px 12px; }"
            "QPushButton:hover { background:#ffd9e9; }")
        self.reset_sides_btn.clicked.connect(self.on_reset_sides)
        usbip_bar.addWidget(self.reset_sides_btn)
        usbip_bar.setContentsMargins(4, 2, 4, 2)
        usbip_bar_w = QWidget()
        usbip_bar_w.setLayout(usbip_bar)
        main_layout.addWidget(usbip_bar_w)
        self._refresh_usbip_status()

        # Status bar
        self.statusBar().showMessage(tr("就绪 - 点击「一键连接手柄」自动连上左右两只 Joy-Con 2"))

        # 1.1 首次启动：弹须知弹窗（延迟到窗口显示后）
        QTimer.singleShot(300, self.check_first_run)

    def create_logo_pixmap(self):
        """加载应用图标（WinJoyCon2-Plus：JC2 → JC1，泡泡糖粉主题）。

        图标由 make_icon.py 生成（logo_256.png / logo_256.ico），
        构图：深梅紫圆角底 + 左 JC2(粉) + 右 JC1(浅粉) + 中间转换箭头。
        运行时按 app_path 定位；找不到就退回纯粉色圆角块，不阻塞启动。
        """
        from pathlib import Path

        from app_paths import app_path

        for name in ("logo_256.png", "logo_256.ico"):
            try:
                p = app_path(name)
            except Exception:
                p = ""
            if p and os.path.exists(p):
                pm = QPixmap(str(p))
                if not pm.isNull():
                    return pm.scaled(256, 256,
                                     Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)

        # 兜底：粉色圆角块，避免界面空白
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor("#ff6fae")))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
        painter.end()
        return pixmap

    def setup_tray_icon(self):
        """Setup system tray icon"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(self.create_logo_pixmap()))

        tray_menu = QMenu()
        # 三个模式按钮与退出程序平级：同时作用于两个手柄（所有手柄组）
        for label, mode in ((tr("🎮 手柄模式"), "gamepad"),
                            (tr("🖱 鼠标模式"), "mouse"),
                            (tr("🌀 陀螺仪模式"), "gyro")):
            act = tray_menu.addAction(label)
            act.triggered.connect(lambda _, m=mode: self.tray_set_mode(m))
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction(tr("退出程序"))
        quit_action.triggered.connect(self.quit_application)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def tray_set_mode(self, mode):
        """托盘切换所有手柄的模式，并立即刷新 GUI。"""
        try:
            import control_type.mouse_mode as mm
            mm.set_all_mode(mode, pair_count=len(self.controller_tabs))
            for tab in self.controller_tabs:
                tab.sync_input_modes()
            self.tray_icon.showMessage(
                APP_NAME,
                tr("已将所有手柄切换为{g}模式", g=tr("手柄") if mode == "gamepad" else (tr("鼠标") if mode == "mouse" else tr("陀螺仪"))),
                QSystemTrayIcon.Information, 1500)
        except Exception as e:  # noqa: BLE001
            warning(f"托盘切换模式失败: {e}")

    def _refresh_usbip_status(self):
        import usbip_setup as _us
        ok = _us.is_usbip_installed()
        txt = (_us.I18N["usbip_ok_zh"] if i18n.LANG == "zh" else _us.I18N["usbip_ok_en"]) if ok \
            else (_us.I18N["usbip_missing_zh"] if i18n.LANG == "zh" else _us.I18N["usbip_missing_en"])
        self.usbip_status.setText(("✅ " if ok else "⚠ ") + txt)
        self.usbip_status.setStyleSheet(
            "color:#2a8a4a;" if ok else "color:#c4407c;")

    def on_install_usbip(self):
        """一键安装/重装 USB/IP。"""
        import usbip_setup as _us
        if _us.is_usbip_installed():
            reply = QMessageBox.question(
                self,
                "USB/IP" if i18n.LANG == "en" else "USB/IP",
                ("USB/IP is already installed. Reinstall anyway?"
                 if i18n.LANG == "en" else "USB/IP 已安装，是否仍要重新安装？"),
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        ok, msg = _us.install_usbip()
        if i18n.LANG == "en":
            QMessageBox.information(self, "Install USB/IP", msg)
        else:
            QMessageBox.information(self, "安装 USB/IP", msg)
        QTimer.singleShot(1500, self._refresh_usbip_status)

    def on_reset_sides(self):
        """清空左右记忆 → 恢复纯净状态，重新走分开连接。"""
        reply = QMessageBox.question(
            self,
            "Reset" if i18n.LANG == "en" else "重置左右记忆",
            tr("重置会清除已记住的左右手柄，确定吗？"),
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            import usbip_setup as _us
            ok, msg = _us.reset_known_sides()
            if ok:
                self._refresh_all_connect_modes()
            QMessageBox.information(
                self,
                ("Done" if ok else "Failed") if i18n.LANG == "en" else ("已重置" if ok else "重置失败"),
                msg)

    def check_first_run(self):
        """1.1 首次启动须知：弹一次，说明左右分开连接 + USB/IP。"""
        import usbip_setup as _us
        if _us.first_run_done():
            return
        lang = i18n.LANG
        title = _us.I18N["notice_title_en" if lang == "en" else "notice_title_zh"]
        body = _us.I18N["notice_en" if lang == "en" else "notice_zh"]
        QMessageBox.information(self, title, body)
        _us.mark_first_run_done()
        self._refresh_usbip_status()
        self._refresh_all_connect_modes()

    def on_language_changed(self, index):
        """切换语言：写配置并提示重启（界面控件在启动时按语言构建）。"""
        lang = self.lang_combo.itemData(index)
        i18n.set_language(lang, persist=True)
        QMessageBox.information(
            self,
            "Language / 语言" if lang == "en" else "语言 / Language",
            ("Language changed to English.\nPlease restart the app for full effect."
             if lang == "en" else
             "已切换为简体中文。\n请重启程序以完全生效。"))

    def show_and_raise(self):
        """Show and raise window"""
        self.show()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_and_raise()

    def quit_application(self):
        """真正退出应用程序（不弹确认，干净利落）。"""
        # Stop the status timer
        self.status_timer.stop()

        # Restore stdout/stderr before exit
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

        # Hide tray icon
        self.tray_icon.hide()

        # 退出前清理虚拟设备残留（detach usbip + 移除幽灵节点）
        try:
            from device_cleanup import cleanup_on_exit
            cleanup_on_exit()
        except Exception as e:  # noqa: BLE001
            warning(f"退出清理失败: {type(e).__name__}: {e}")

        # Force exit immediately
        info("Force exiting...")
        import os
        os._exit(0)

    def add_controller_separate(self, pair_id: int):
        """1.1 分开连接：让用户在对话框里手动选左/右，逐个连接并记忆。"""
        if self.adding_controller_lock:
            QMessageBox.information(self, tr("提示"), tr("正在连接中，请稍候"))
            return
        dlg = AddControllerDialog(self, connection_mode="both", pair_id=pair_id)
        dlg.force_side_select = True   # 即使自动识别也让用户确认左右
        dlg.setWindowTitle(tr("分开连接 - 手柄组 {n}", n=pair_id + 1))
        if hasattr(dlg, "side_widget"):
            dlg.side_widget.setVisible(True)
        if hasattr(dlg, "instructions"):
            dlg.instructions.setText(tr("分开连接：请选择这只手柄是左手柄还是右手柄，连接后会被记住。"))

        # 关键：点「连接」时直接回调主窗口发起连接，不依赖 exec_() 返回值。
        # （对话框在连续模式下不会 accept，靠返回值拿设备会导致连接请求永远发不出去）
        def _do_connect(info):
            info = dict(info)
            info["pair_id"] = pair_id
            side = info.get("side", "Left")
            self.controller_tabs[pair_id].log_message(
                tr("分开连接 {s}手柄：{m}", s=tr("左") if side == "Left" else tr("右"),
                   m=info.get("mac", "")))
            self.on_device_selected_for_pair(info, pair_id)
            QTimer.singleShot(2500, self._refresh_all_connect_modes)

        dlg.on_device = _do_connect
        # 两只手柄都连上后自动关闭对话框
        self._watch_pair_complete(dlg, pair_id)
        dlg.exec_()

    def _watch_pair_complete(self, dlg, pair_id):
        """轮询检查该组是否左右都连上，是则关闭分开连接对话框。"""
        timer = QTimer(dlg)
        timer.setInterval(500)

        def _check():
            try:
                pair = get_controller_manager().get_pair(pair_id)
                if pair and pair.left.is_connected and pair.right.is_connected:
                    timer.stop()
                    dlg.accept()      # 关闭对话框
            except Exception:
                pass

        timer.timeout.connect(_check)
        timer.start()

    def _refresh_all_connect_modes(self):
        for tab in self.controller_tabs:
            tab._refresh_connect_mode()

    def add_controller_to_pair(self, pair_id: int):
        """一键连接：自动扫描并连上左右两只 Joy-Con。

        不再弹「请选择手柄侧」对话框 —— 左右由广播名/MAC 自动判定，
        判定不出来的按到达顺序分配。整个过程都在后台线程里跑，
        GUI 只显示进度。
        """
        if self.adding_controller_lock:
            QMessageBox.information(self, tr("提示"), tr("正在连接中，请稍候"))
            return

        tab = self.controller_tabs[pair_id]
        manager = get_controller_manager()
        pair = manager.get_pair(pair_id)
        if pair and pair.mode.value == 3:
            QMessageBox.information(self, tr("提示"), tr("本组已连接左右两只手柄"))
            return

        self.adding_controller_lock = True
        tab.add_btn.setEnabled(False)
        tab.add_btn.setText(tr("连接中..."))
        tab.log_message("开始一键连接：请确保两只手柄都已唤醒（按任意键）")

        self._auto_connect_thread = _AutoConnectThread(pair_id, self)
        self._auto_connect_thread.progress.connect(
            lambda side, mac: tab.log_message(f"  找到 {side}: {mac}"))
        self._auto_connect_thread.finished_all.connect(
            lambda ok, msg: self._on_auto_connect_done(pair_id, ok, msg))
        self._auto_connect_thread.start()

    def _on_auto_connect_done(self, pair_id: int, ok: bool, msg: str):
        """一键连接结束后的收尾。"""
        tab = self.controller_tabs[pair_id]
        self.adding_controller_lock = False
        tab.add_btn.setEnabled(True)
        tab.add_btn.setText(tr("⚡ 一键连接手柄"))
        tab.log_message(msg)
        if ok:
            # refresh_all_tabs 这个方法并不存在（写的时候想当然），
            # 调用它会抛 AttributeError，表现就是"刚连上就崩溃"。
            # 正确做法是调用已有的 update_controller_status。
            try:
                self.update_controller_status()
            except Exception:
                pass
        else:
            QMessageBox.warning(self, tr("连接未完成"), msg)

    def on_device_selected_for_pair(self, device_info, pair_id: int):
        """Handle device selection for specific pair"""
        message = f"正在连接 {device_info['name']}..."
        self.log_message(f"{message} 到手柄组 {pair_id + 1}")
        # Also log to pair's own log
        if 0 <= pair_id < len(self.controller_tabs):
            self.controller_tabs[pair_id].log_message(message)

        # 连接模式已移除：始终双手柄
        mode = "both"

        # Create connect thread with mode
        self.connect_thread = ConnectThread(device_info, pair_id, mode=mode)
        self.connect_thread.connect_finished.connect(self.on_connect_finished)
        self.connect_thread.connect_error.connect(self.on_connect_error)
        self.connect_thread.start()

    def on_connect_finished(self, device_name, pair_id, success):
        """Handle connect completion"""
        if 0 <= pair_id < len(self.controller_tabs):
            if success:
                self.controller_tabs[pair_id].log_message(f"成功连接 {device_name}")
                
                # 1.1: 不再弹补连对话框——分开连接在同一窗口内继续扫第二只
            else:
                self.controller_tabs[pair_id].log_message(f"连接 {device_name} 失败")

    def on_connect_error(self, device_name, pair_id, error_msg):
        """Handle connect error"""
        if 0 <= pair_id < len(self.controller_tabs):
            self.controller_tabs[pair_id].log_message(f"连接出错：{error_msg}")
        
    def show_dual_connect_prompt(self, pair_id, second_side):
        """Show prompt to connect second Joy-Con in dual mode"""
        side_name = "左手柄" if second_side == "Left" else "右手柄"
            
        msg_box = QMessageBox()
        msg_box.setWindowTitle(tr("连接第二个手柄"))
        msg_box.setText(tr("第一个手柄已连接"))
        msg_box.setInformativeText(tr("请长按{s}的同步按钮 3-5 秒，然后点击\"确定\"开始连接", s=side_name))
        msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg_box.button(QMessageBox.Ok).setText(tr("确定"))
        msg_box.button(QMessageBox.Cancel).setText(tr("取消"))
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #ffeaf3;
            }
            QLabel {
                color: #5c2340;
            }
            QPushButton {
                background-color: #ff6fae;
                color: #5c2340;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #e04a8f;
            }
        """)
            
        result = msg_box.exec_()
            
        if result == QMessageBox.Ok:
            # User wants to connect second Joy-Con now
            self.log_message(f"开始连接第二个手柄：{side_name}")
            # Simulate clicking add button for this pair
            if 0 <= pair_id < len(self.controller_tabs):
                self.controller_tabs[pair_id].add_btn.click()
        else:
            self.log_message(tr("已取消连接第二个手柄"))
        
    def on_add_dialog_finished(self):
        """Called when AddControllerDialog closes - release lock"""
        self.adding_controller_lock = False
        self.statusBar().showMessage(tr("就绪"))

    def disconnect_pair(self, pair_id: int):
        """Disconnect a specific pair"""
        manager = get_controller_manager()
        pair = manager.get_pair(pair_id)

        if not pair or not pair.is_active():
            QMessageBox.information(self, tr("提示"), tr("手柄组 {n} 未连接", n=pair_id+1))
            return

        reply = QMessageBox.question(
            self, "确认断开",
            tr("确定要断开手柄组 {n} 吗？", n=pair_id+1),
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.start_disconnect_thread(pair_id)
    
    def start_disconnect_thread(self, pair_id: int):
        """Start a thread to disconnect a pair"""
        self.disconnect_thread = DisconnectThread(pair_id)
        self.disconnect_thread.disconnect_finished.connect(self.on_disconnect_finished)
        self.disconnect_thread.disconnect_error.connect(self.on_disconnect_error)
        self.disconnect_thread.start()

    def on_disconnect_finished(self, pair_id):
        """Handle disconnect completion"""
        if 0 <= pair_id < len(self.controller_tabs):
            self.controller_tabs[pair_id].log_message("已断开连接")

    def on_disconnect_error(self, pair_id, error_msg):
        """Handle disconnect error"""
        if 0 <= pair_id < len(self.controller_tabs):
            self.controller_tabs[pair_id].log_message(f"断开出错: {error_msg}")
    
    def log_message(self, message, pair_id=None):
        """Add message to specific pair's log or current tab's log"""
        if pair_id is not None and 0 <= pair_id < len(self.controller_tabs):
            self.controller_tabs[pair_id].log_message(message)
        else:
            # Log to currently selected tab
            current_tab = self.tab_widget.currentIndex()
            if 0 <= current_tab < len(self.controller_tabs):
                self.controller_tabs[current_tab].log_message(message)

    def update_controller_status(self):
        """Update controller connection and battery status for all pairs"""
        try:
            manager = get_controller_manager()
            
            # Update title with count
            active_count = manager.get_connected_count()
            self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} (" + tr("{n}/4 组手柄", n=active_count) + ")")
            
            # Update each tab
            for i, tab in enumerate(self.controller_tabs):
                pair = manager.get_pair(i)
                if pair:
                    tab.update_status(pair)
                    tab.sync_input_modes()   # 组合键切换后 GUI 模式下拉跟随
                    # Update tab text to show status
                    mode_short = ""
                    if pair.mode.value == 3:
                        mode_short = "[双]"
                    elif pair.mode.value == 1:
                        mode_short = "[左]"
                    elif pair.mode.value == 2:
                        mode_short = "[右]"
                    self.tab_widget.setTabText(i, tr("手柄组 {n} {short}", n=i+1, short=mode_short))
                else:
                    tab.update_status(None)
                    self.tab_widget.setTabText(i, tr("手柄组 {n}", n=i+1))
                
        except Exception as e:
            # Silently fail during shutdown
            pass
    
    def changeEvent(self, event):
        """最小化按钮 → 隐藏到系统托盘（关闭按钮走 closeEvent → 真正退出）。"""
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            event.ignore()
            self.hide()
            self.showNormal()   # 复位窗口状态，避免下次 show 仍是最小化态
            self.hide()
            self.tray_icon.showMessage(
                APP_NAME,
                "程序已隐藏到系统托盘，双击图标或右键菜单显示窗口",
                QSystemTrayIcon.Information,
                2000
            )
            return
        super().changeEvent(event)

    def closeEvent(self, event):
        """关闭按钮 → 直接退出程序（不再隐藏托盘）。"""
        event.ignore()
        self.quit_application()


def main():
    import sys
    import threading

    # 加载界面语言（必须在创建窗口前，tr() 才能取到正确语言）
    i18n.load_language()
    # 加载陀螺仪模拟器兼容模式（Ryujinx/Eden）
    try:
        from virtual.imu_proc import load_imu_compat_mode
        load_imu_compat_mode()
    except Exception:
        pass

    # ---- 全局异常钩子：把任何未捕获异常写进 crash.log ----
    # 打包版没有控制台，崩溃时什么都看不到。这个钩子保证一定能留痕。
    import traceback as _tb
    import os as _os

    def _hook(exc_type, exc_val, exc_tb):
        try:
            with open(_os.path.join(_os.path.dirname(_os.path.abspath(sys.argv[0])),
                                    "logs", "crash.log"), "a", encoding="utf-8") as fh:
                fh.write("\n" + "=" * 60 + "\n")
                fh.write("".join(_tb.format_exception(exc_type, exc_val, exc_tb)))
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_val, exc_tb)

    sys.excepthook = _hook

    def _thread_hook(args):
        _hook(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = _thread_hook

    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    # 退出清理兜底：即使异常退出也尽量 detach / 清残留。
    # quit_application 里已显式调用一次；这里覆盖未走那条路径的情况
    # （未捕获异常、sys.exit 等）。重复调用是幂等的。
    import atexit as _atexit
    def _exit_cleanup():
        try:
            from device_cleanup import cleanup_on_exit
            cleanup_on_exit()
        except Exception:
            pass
    _atexit.register(_exit_cleanup)

    # ── Windows 控制台/注销/关机事件兜底 ──
    #
    # 为什么还需要这一层：
    #   quit_application() 末尾是 `os._exit(0)` —— 它**不执行 atexit**。
    #   所以 atexit 只在没走 quit_application 时才生效。
    #   而 SetConsoleCtrlHandler 能在这些情况下拿到回调：
    #     · 窗口被任务管理器结束
    #     · 用户注销 / 关机
    #     · Ctrl+C / Ctrl+Break
    #   回调里做清理，保证「每次退出都清幽灵设备」。
    def _install_console_handler():
        try:
            import ctypes
            from ctypes import wintypes

            HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

            def _on_event(evt):
                # 0=CTRL_C 1=CTRL_BREAK 2=CTRL_CLOSE 5=LOGOFF 6=SHUTDOWN
                try:
                    from device_cleanup import cleanup_on_exit
                    cleanup_on_exit()
                except Exception:      # noqa: BLE001
                    pass
                return False           # 让默认处理继续

            handler = HANDLER(_on_event)
            ok = ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
            # 必须保住引用，否则回调会被 GC
            _install_console_handler._keep = handler
            return bool(ok)
        except Exception:      # noqa: BLE001
            return False

    _install_console_handler()

    # ═══ 启动时清理上次残留（2026-11-17 新增，用户要求）═══
    #
    # 为什么放在启动而不是只放在退出：
    #   Windows 上「任务管理器强制结束」走的是 TerminateProcess，
    #   **任何用户态代码都无法拦截**（没有回调、没有 atexit）。
    #   所以只做退出清理一定会漏 —— 上次如果是被强杀，
    #   幽灵节点就会留在设备树里，累积到 GamepadTester 里
    #   出现重复手柄（排查摇杆时读到旧节点数据，污染诊断）。
    #
    #   启动时清理覆盖了所有退出方式：无论上次怎么没的，
    #   这次启动都会先扫干净再建新设备。
    #
    # ★★ 2026-11-19 重大修复：必须先 detach 所有 usbip **活动端口** ★★
    #
    # 之前这里只清"幽灵 PnP 节点"（count_ghosts），**完全没管 usbip port**。
    # 于是上次被强杀后残留的活动端口还在，本次启动又在同一端口上再 attach
    # 一份 → 同一只手柄被导出两次（实测出现 Port01=R、Port02=R 重复），
    # SDL/模拟器枚举到重复设备 → 方向错乱、卡顿、甚至失效。
    #
    # 现在顺序固定为：
    #   ① detach 所有 usbip 活动端口（消掉重复导出，无需提权）
    #   ② 清幽灵 PnP 节点（需提权，失败静默）
    # 两步都在创建新设备之前完成。
    try:
        import device_cleanup as _dc
        # ① 先断开所有活动端口 —— 这是重复导出的直接来源
        _detached = _dc.detach_all_usbip()
        if _detached:
            info(f"[启动清理] 已 detach {_detached} 个残留 usbip 端口")
        # ② 再清幽灵节点
        _n = _dc.count_ghosts()
        if _n:
            info(f"[启动清理] 发现 {_n} 个上次残留节点，开始清理…")
            _dc.cleanup_on_exit()
            info(f"[启动清理] 完成，剩余 {_dc.count_ghosts()}")
    except Exception as _e:      # noqa: BLE001
        warning(f"[启动清理] 失败（不影响启动）: {type(_e).__name__}: {_e}")

    # Validate config file on startup
    from error_handler import validate_config_file
    if not validate_config_file():
        QMessageBox.critical(None, "错误", "配置文件验证失败，请检查文件权限")
        sys.exit(1)

    # 摇杆采用原生透传，无需任何标定模块
    
    # Create and start the global event loop (like original Joy2Win)
    import main as main_module
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main_module.set_event_loop(loop)
    
    # Start the event loop in a background thread
    def run_event_loop():
        loop.run_forever()
    
    loop_thread = threading.Thread(target=run_event_loop, daemon=True)
    loop_thread.start()
    
    window = Joy2WinGUI()
    window.show()
    
    exit_code = app.exec_()
    
    # Stop the event loop on exit
    loop.call_soon_threadsafe(loop.stop)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
