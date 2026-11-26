# -*- coding: utf-8 -*-
"""中英双语支持 —— WinJoyCon2-Plus。

所有 UI 文本用 tr("中文") 包裹；当前语言存 config.ini [General] language=zh|en。
切换语言后写配置并提示重启（界面控件在启动时按语言构建，重启最稳妥）。
"""
from __future__ import annotations

import configparser
import os

from app_paths import config_path

LANG = "zh"   # 全局当前语言，GUI 启动时从配置加载

# 翻译表：key 是简体中文原文，value 是英文。
# 未收录的条目原样返回中文（渐进补全，不破坏功能）。
T = {
    # ── 通用 ──
    "关闭": "Close", "完成": "Done", "确定": "OK", "取消": "Cancel",
    "提示": "Info", "连接": "Connect", "未连接": "Not Connected",
    "已连接": "Connected", "未知": "Unknown", "充电中 %p%": "Charging %p%",
    "就绪": "Ready", "正在连接 ...": "Connecting ...", "连接中...": "Connecting...",
    "已定位": "Located", "在线": "Online", "失败": "Failed",

    # ── 主窗口 ──
    "手柄组 {n}": "Controller Pair {n}",
    "手柄组 {n} {short}": "Controller Pair {n} {short}",
    "[双]": "[L+R]", "[左]": "[L]", "[右]": "[R]",
    "连接状态": "Connection Status", "左手柄": "Left Joy-Con",
    "右手柄": "Right Joy-Con", "手柄组日志": "Pair Log",
    "⚡ 一键连接手柄": "⚡ Connect Both", "- 断开手柄": "- Disconnect",
    "🎯 摇杆说明": "🎯 Stick Info",
    "就绪 - 点击「一键连接手柄」自动连上左右两只 Joy-Con 2":
        "Ready - click \"Connect Both\" to pair both Joy-Con 2",
    "输入模式:": "Input Mode:",
    "🖱 鼠标 / 陀螺仪 / 宏 设置": "🖱 Mouse / Gyro / Macro Settings",

    # ── 输入模式面板 ──
    "输入模式设置（点击选择，页面内跳转）：": "Input mode settings (click to switch pages):",
    "🖱 鼠标模式": "🖱 Mouse Mode", "🌀 陀螺仪鼠标": "🌀 Gyro Mouse",
    "⚙ 宏系统": "⚙ Macro System", "← 返回": "← Back",
    "❓ 使用说明": "❓ Help", " · 使用说明": " · Help",
    "鼠标模式": "Mouse Mode", "陀螺仪鼠标模式": "Gyro Mouse Mode",
    "陀螺仪鼠标": "Gyro Mouse", "宏系统": "Macro System",
    "手柄模式": "Gamepad Mode", "鼠标模式": "Mouse Mode",
    "当前模式": "Current Mode", "动作开关": "Action Toggles",
    "启用滚轮": "Enable Scroll", "反转滚轮方向": "Invert Scroll",
    "灵敏度挡位：{s}（加减键切换，可在自定义按键页改键）":
        "Sensitivity: {s} (+/- keys; remappable in Key Mapping)",
    "鼠标模式按键映射": "Mouse Mode Key Mapping",
    "陀螺仪鼠标模式按键映射": "Gyro Mouse Key Mapping",
    "陀螺仪设置": "Gyro Settings", "灵敏度:": "Sensitivity:",
    "反转水平": "Invert Horizontal", "反转垂直": "Invert Vertical",
    "启用宏系统（C+SL/SR 触发）": "Enable Macros (trigger with C+SL/SR)",
    "已绑定：\n": "Bound:\n", "暂无已保存的宏。": "No macros saved yet.",
    "宏名称:": "Macro Name:", "绑定到 SL/SR 键:": "Bind to SL/SR key:",
    "● 开始录制": "● Record", "■ 停止保存": "■ Stop & Save",
    "录制中 → {b}（现在按手柄的动作键会被记录）":
        "Recording → {b} (press controller buttons to record)",
    "↩ 还原默认按键": "↩ Restore Defaults",

    # ── 动作选项 ──
    "不映射": "Unmapped", "鼠标左键": "Left Click", "鼠标右键": "Right Click",
    "鼠标中键": "Middle Click", "前进(X2)": "Forward (X2)",
    "后退(X1)": "Back (X1)", "滚轮上": "Scroll Up", "滚轮下": "Scroll Down",
    "光标回中心": "Center Cursor",

    # ── 按钮名 ──
    "左肩键 L": "Left Shoulder L", "左扳机 ZL": "Left Trigger ZL",
    "左摇杆按下 LS": "Left Stick Press LS", "截图键": "Capture",
    "十字 上": "D-Pad Up", "十字 下": "D-Pad Down",
    "十字 左": "D-Pad Left", "十字 右": "D-Pad Right",
    "左手柄 SL": "Left SL", "左手柄 SR": "Left SR",
    "右肩键 R": "Right Shoulder R", "右扳机 ZR": "Right Trigger ZR",
    "右摇杆按下 RS": "Right Stick Press RS", "HOME 键": "HOME",
    "右手柄 SL": "Right SL", "右手柄 SR": "Right SR",
    "A": "A", "B": "B", "X": "X", "Y": "Y",

    # ── 托盘 ──
    "🎮 手柄模式": "🎮 Gamepad", "🖱 鼠标模式": "🖱 Mouse",
    "🌀 陀螺仪模式": "🌀 Gyro", "退出程序": "Exit",
    "已将所有手柄切换为{g}模式": "All controllers switched to {g} mode",
    "手柄": "Gamepad", "陀螺仪": "Gyro",
    "程序已隐藏到系统托盘，双击图标或右键菜单显示窗口":
        "Hidden to tray. Double-click the icon or use the context menu to show.",

    # ── 弹窗/连接 ──
    "摇杆（原样透传）": "Stick (Passthrough)",
    "正在连接中，请稍候": "Connecting, please wait",
    "本组已连接左右两只手柄": "Both Joy-Con already connected in this pair",
    "连接未完成": "Connection Incomplete",
    "手柄组 {n} 未连接": "Controller Pair {n} not connected",
    "确认断开": "Confirm Disconnect", "确定要断开手柄组 {n} 吗？":
        "Disconnect Controller Pair {n}?",
    "开始一键连接：请确保两只手柄都已唤醒（按任意键）":
        "Connecting: make sure both controllers are awake (press any button)",
    "  找到 {s}: {m}": "  Found {s}: {m}",
    "✓ 两只手柄都已连接": "✓ Both controllers connected",
    "已连接 1 只手柄。另一只请确认已唤醒后再次点击连接。":
        "1 controller connected. Wake the other and click connect again.",
    "连接失败，请重试。": "Connection failed, please retry.",
    "连接异常: {e}": "Connection error: {e}",
    "成功连接 {n}": "Connected {n}", "连接 {n} 失败": "Failed to connect {n}",
    "连接出错：{e}": "Connection error: {e}",
    "正在连接 {n}...": "Connecting {n}...",
    "连接第二个手柄": "Connect Second Controller", "第一个手柄已连接":
        "First controller connected",
    "请长按{s}的同步按钮 3-5 秒，然后点击\"确定\"开始连接":
        "Hold {s} SYNC button 3-5s, then click OK to connect",
    "开始连接第二个手柄：{s}": "Connecting second controller: {s}",
    "已取消连接第二个手柄": "Cancelled second controller connection",
    "已断开连接": "Disconnected", "断开出错: {e}": "Disconnect error: {e}",
    "没有扫描到手柄。请按一下手柄任意键唤醒后重试。":
        "No controller found. Press any button to wake it and retry.",

    # ── 添加手柄对话框 ──
    "添加手柄 - 手柄组 {n}": "Add Controller - Pair {n}",
    "请长按同步按钮...": "Hold SYNC button...", "请选择手柄侧:": "Select side:",
    "左手柄 (L)": "Left (L)", "右手柄 (R)": "Right (R)",
    "正在扫描...请长按同步按钮": "Scanning... hold SYNC button",
    "找到：{n} ({s})": "Found: {n} ({s})", "找到设备，但无法识别左右":
        "Device found, side unknown",
    "未找到设备，请重新长按同步按钮": "No device found, hold SYNC again",
    "扫描出错：{e}": "Scan error: {e}",
    # ── 1.1 分开连接 / USB-IP ──
    "🔀 分开连接": "🔀 Connect Separately",
    "一键连接（左右已记忆）": "Connect Both (sides remembered)",
    "首次使用请点「分开连接」分别选左右": "First use: click Connect Separately to pick Left/Right",
    "手动选择左手柄或右手柄，连接后记住左右": "Pick Left or Right; the side is remembered after connecting",
    "分开连接 - 手柄组 {n}": "Connect Separately - Pair {n}",
    "分开连接：请选择这只手柄是左手柄还是右手柄，连接后会被记住。":
        "Separate connection: pick whether this controller is Left or Right; it will be remembered.",
    "分开连接 {s}手柄：{m}": "Connecting {s} controller: {m}",
    "左": "Left", "右": "Right",
    "🔧 一键安装 USB/IP": "🔧 Install USB/IP",
    "🔧 重装/修复 USB/IP": "🔧 Reinstall/Repair USB/IP",
    "🧹 重置左右记忆": "🧹 Reset Side Memory",
    "已清空左右记忆，下次请重新分开连接。重启程序使首次须知再次出现。":
        "Side memory cleared. Please connect Left/Right separately again. "
        "Restart to see the first-run notice again.",
    "重置会清除已记住的左右手柄，确定吗？":
        "Reset will clear remembered controller sides. Continue?",
    "⚙ 输入模式设置": "⚙ Input Settings",
    "输入模式设置": "Input Mode Settings",
    "已连接{s1}手柄。请唤醒{s2}手柄并长按 SYNC，然后选侧连接。":
        "{s1} controller connected. Wake the {s2} controller, hold SYNC, then connect.",
    "{n}/4 组手柄": "{n}/4 Pairs",
    "鼠标": "Mouse",

    # ── 帮助长文本 ──
    "【鼠标模式说明】\n\n切换：按住右手柄 C 键，再按 R → 右手柄进鼠标模式；按 L → 左手柄进鼠标模式。\n退出：再次按同一组合键（如 C+R）→ 回手柄模式；或长按 C 键 2 秒全部复位。\n\n操作：\n  • 平放手柄滑动 = 移动光标（光学传感器）\n  • 摇杆前/后 = 滚动（推得越狠越快）\n  • 按键功能在「自定义按键」页设置（默认 L/R=左键、ZL/ZR=右键、截图/HOME=中键、十字键或XYAB=前进后退）\n  • 灵敏度四挡 800/1600/3200/6400，默认第2挡\n\n固定功能键（不可自定义、不可录宏）：\n  • 加键 + / 减键 −：永远只调灵敏度挡位\n  • C 键：永远只做模式切换/宏触发\n":
        "[Mouse Mode]\n\nSwitch: hold right C then press R = right mouse; L = left mouse.\nExit: press the same combo again (e.g. C+R) = back to gamepad; or hold C for 2s to reset all.\n\nControls:\n  • Slide the flat controller = move cursor (optical sensor)\n  • Stick forward/back = scroll (faster when pushed further)\n  • Button functions set in Key Mapping page (default L/R=left click, ZL/ZR=right click, Capture/HOME=middle, D-pad/XYAB=back/forward)\n  • 4 DPI levels 800/1600/3200/6400, default level 2\n\nFixed keys (not remappable, not recordable):\n  • Plus/Minus: always adjusts DPI level\n  • C key: only for mode switch/macro trigger\n",
    "【陀螺仪鼠标说明 · 超级马力欧银河 NS 版逻辑】\n\n切换：按住 C 键，再按 ZL → 左手柄陀螺仪；按 ZR → 右手柄陀螺仪。\n退出：再次按同一组合键（如 C+ZR）→ 回手柄模式；或长按 C 键 2 秒全部复位。\n\n操作逻辑（银河式）：\n  • 手柄侧放，绕竖直轴左右转动 = 光标水平移动\n  • 绕长轴前后俯仰 = 光标垂直移动\n  • 转动越快光标移动越快，停手即停（角速度积分，非倾斜绝对角度）\n\n因握持姿势与光学鼠标不同，按键功能请在「自定义按键」页单独设置；灵敏度用下方「陀螺仪灵敏度」调节（默认值已按银河手感标定）。":
        "[Gyro Mouse · Super Mario Galaxy NS style]\n\nSwitch: hold C then press ZL = left gyro; ZR = right gyro.\nExit: press the same combo again (e.g. C+ZR) = back to gamepad; or hold C for 2s to reset all.\n\nLogic (Galaxy style):\n  • Controller laid flat, rotate around vertical axis = cursor horizontal\n  • Pitch around long axis = cursor vertical\n  • Faster rotation = faster cursor, stops when you stop (angular velocity integration, not absolute tilt)\n\nGrip differs from optical mouse, so set buttons separately in Key Mapping; tune with Gyro Sensitivity below (default calibrated to Galaxy feel).",
    "【宏系统说明】\n\n开启：勾选下方「启用宏系统」（默认关闭）。\n\n录制：\n  1. 选好宏名称与绑定键（左手柄 SL/SR、右手柄 SL/SR 四选一）\n  2. 点「开始录制」，依次按下想录的动作键\n  3. 点「停止保存」，宏即绑定到该 SL/SR 键\n\n触发：按住 C 键 + 对应 SL/SR 键 → 回放该宏。\n\n所有自定义按键与宏都会自动保存到配置，重启后保留。四个 SL/SR 键可各绑一个宏。":
        "[Macro System]\n\nEnable: check \"Enable Macros\" below (off by default).\n\nRecord:\n  1. Choose macro name and bind key (Left SL/SR, Right SL/SR - pick one of four)\n  2. Click Record, press the buttons to record in order\n  3. Click Stop & Save; macro binds to that SL/SR key\n\nTrigger: hold C + the bound SL/SR key = replay the macro.\n\nAll custom keys and macros are auto-saved to config and persist across restarts. Each of the four SL/SR keys can hold a macro.",
}


def set_language(lang: str, persist: bool = True):
    """设置当前语言：'zh' 或 'en'。"""
    global LANG
    if lang not in ("zh", "en"):
        return
    LANG = lang
    if persist:
        try:
            parser = configparser.ConfigParser()
            path = config_path()
            if os.path.exists(path):
                parser.read(path, encoding="utf-8")
            if "General" not in parser:
                parser["General"] = {}
            parser["General"]["language"] = lang
            with open(path, "w", encoding="utf-8") as f:
                parser.write(f)
        except Exception:
            pass


def load_language():
    """从 config.ini 读取语言设置。"""
    try:
        parser = configparser.ConfigParser()
        path = config_path()
        if os.path.exists(path):
            parser.read(path, encoding="utf-8")
            lang = parser.get("General", "language", fallback="zh").strip().lower()
            if lang in ("zh", "en"):
                set_language(lang, persist=False)
    except Exception:
        pass


def tr(text: str, **kwargs) -> str:
    """翻译：中文原文 → 当前语言。支持 {占位符} 格式化。"""
    if LANG == "en":
        out = T.get(text, text)
    else:
        out = text
    if kwargs:
        try:
            out = out.format(**kwargs)
        except Exception:
            pass
    return out
