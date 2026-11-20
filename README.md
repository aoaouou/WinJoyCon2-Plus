# WinJoyCon2-Plus

### 把 Switch 2 的 Joy-Con 2，变成 PC 上无所不能的操控神器

**前无古人。这不是又一个手柄映射器 —— 这是 Joy-Con 2 在 Windows 上的完全体。**

<div align="center">

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?style=for-the-badge)](https://www.microsoft.com/windows)
[![Controller](https://img.shields.io/badge/Controller-Joy--Con%202-E6007D?style=for-the-badge)](https://www.nintendo.com/us/store/products/joy-con-2/)
[![Protocol](https://img.shields.io/badge/Transport-USB%2FIP-28A745?style=for-the-badge)](https://en.wikipedia.org/wiki/USB_over_IP)
[![Language](https://img.shields.io/badge/UI-%E4%B8%AD%E6%96%87%20%2F%20English-FF6FAE?style=for-the-badge)](./README.md)

</div>

---

> **中文** · [English](#english)

## 为什么它前无古人？

任天堂造出了 Joy-Con 2 —— 带**光学鼠标传感器**、**高精度陀螺仪**、**HD 震动 2** 的革命性手柄。但在 PC 上，它几乎是一块砖：SDL 的 `InitBluetooth()` 至今是空实现，官方从未让它真正连上 Windows。

于是我们做了别人没做过的事：**不靠模拟器施舍，直接用 USB/IP 把它桥接成虚拟 Joy-Con 1，再把 JC2 的全部硬件潜力，一寸不落地搬到 Windows。**

结果是一个**在整体体验上超越 NS2 实机、也超越 Windows 原生鼠标**的操控系统：

- NS2 实机的鼠标模式只允许平放桌面、按键写死、滚轮只能倾斜摇杆 —— 我们把它**彻底解放**：三种输入模式、全按键自定义、宏系统、组合键切换，想怎么用就怎么用。
- Windows 原生滚轮一格跳三行、生硬顿挫 —— 我们用**亚格精度连续滚动 + 力度平方曲线**，做到了比真鼠标还丝滑、轻推慢滚满推快滚的模拟量手感。
- NS2 陀螺仪只在个别游戏里当辅助 —— 我们做成了**银河式陀螺仪鼠标**，全系统通用，漂移了一键回中。

**这是把游戏主机的硬件，做成了 PC 上真正通用的输入设备。没有人这么做过。**

## 核心能力

### 🎮 faithful 桥接（这件事本身已是首创）
- 把 **Joy-Con 2（BLE）** 桥接为 **Switch 1 的 Joy-Con 1**（VID `057E` / PID `2006`·`2007`）
- Ryujinx / Eden 等只认 JC1 的模拟器直接可用，识别为**左右分体**而非 Pro
- 摇杆照 viiper 方案标定：center 2048 / 行程 2047 / 物理拉伸 900，回中精准、推满到边
- HD 震动 2、IMU 六轴、全按键，逐字节保真
- 一键并发连接双柄 + 断线重连 + 幽灵设备自动清理

### 🖱 光学鼠标模式（超越 NS2 官方）
- **双柄独立**：左右手柄各自是独立鼠标，系统原生叠加，可单独或同时开启
- 光标走光学传感器原生通道，跟手无延迟
- **力度滚轮**：推得越狠滚得越快，平方曲线低速细腻、高速畅快；亚格精度滚动，比 Windows 原生滚轮丝滑得多
- **四挡 DPI**：800 / 1600 / 3200 / 6400，加键升挡、减键降挡（双手柄到顶停住，单手柄循环）
- 全按键可自定义映射：左/右键、中键、前进/后退侧键、滚轮、光标回中

### 🌀 陀螺仪鼠标（把马力欧银河搬进 Windows）
- **角速度积分式**光标控制 —— 超级马力欧银河 NS 版的体感逻辑，全系统通用
- 绕竖直轴转动 = 水平移动，绕长轴俯仰 = 垂直移动，停手即停
- 灵敏度、X/Y 反转独立可调，默认已按银河手感标定
- **摇杆按下 = 光标一键回屏幕中心**，漂移即刻归位
- 完美支持 FPS 精细瞄准、桌面浏览、任何需要指针的场景

### ⚙ 宏系统
- C 键 + SL/SR 触发宏，四个侧键各绑一套
- GUI 内录制 / 保存 / 开关，宏与按键配置全部持久化，重启不丢
- 双手柄模式一键同步切换：手柄 / 鼠标 / 陀螺仪

### 🌐 体验细节
- **中英双语界面**，右上角一键切换
- 最小化到托盘、托盘右键快速切模式、关闭即干净退出
- 页面内跳转的设置面板、可滚动布局、内置使用说明
- 所有自定义即时生效并落盘

## 安装与使用

1. 安装 USB/IP（本机路径 `C:\Program Files\USBip\usbip.exe`）
2. 下载 Release 中的 `WinJoyCon2-Plus.exe`（或按下方命令自行构建）
3. 手柄按 SYNC 键进入配对模式，程序内点击「一键连接手柄」
4. 右上角切换 中文 / English；设置面板里开启你想要的模式
5. 开始享受 —— 你会再也回不去普通手柄了

## 从源码构建

```bash
cd _src
pip install bleak pynput pyqt5
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WinJoyCon2-Plus --icon logo_256.ico --hidden-import theme --hidden-import i18n --hidden-import virtual --hidden-import virtual.bridge --hidden-import virtual.descriptors --hidden-import virtual.hid_function --hidden-import virtual.reports --hidden-import virtual.usbip --hidden-import virtual.vjoy_out --hidden-import virtual.imu_proc --hidden-import virtual.scroll --hidden-import virtual.rumble_hd --hidden-import virtual.jc2_frame --hidden-import device_cleanup --hidden-import hidden_exec --hidden-import control_type --hidden-import control_type.duo_joycon --hidden-import control_type.single_joycon --hidden-import control_type.mouse_mode --hidden-import controllers --hidden-import controllers.JoyconL --hidden-import controllers.JoyconR --hidden-import error_handler gui.py
```

需要 Windows 10/11 与 Python 3.10+。

## 致谢与声明

- 摇杆标定参考 Alia5/VIIPER 的成熟实现
- 协议研究参考 ndeadly/switch2_controller_research 与 SDL `SDL_hidapi_switch2`
- 本项目为独立逆向工程成果，与任天堂无关。Joy-Con、Nintendo Switch 为任天堂商标。

**为所有想把 JC2 用到极致的人而造。**

---

<a name="english"></a>

## English

### Turn the Switch 2 Joy-Con 2 into an all-powerful controller on PC

**Unprecedented. This is not another gamepad mapper — it is the complete form of the Joy-Con 2 on Windows.**

> **English** · [中文](#why-it-is-unprecedented)

### Why it is unprecedented?

Nintendo built a revolutionary controller — an **optical mouse sensor**, **precision gyroscope**, and **HD Rumble 2**. On PC it was nearly a brick: SDL's `InitBluetooth()` is still a stub, and Nintendo never made it work on Windows.

So we did what nobody else did: **instead of waiting for emulator support, we bridge it over USB/IP as a virtual Joy-Con 1, then unlock every bit of the JC2's hardware potential on Windows.**

The result is a control system that **surpasses the NS2 console itself and Windows' native mouse experience**:

- On NS2, mouse mode only works lying flat, buttons are hardwired, and scroll is a crude stick tilt. We **set it free**: three input modes, fully remappable buttons, macros, combo-key switching — your controller, your rules.
- Windows native scroll jumps 3 lines per notch, stiff and jarring. We built **sub-notch continuous scrolling with a squared force curve** — smoother than a real mouse, slow when you nudge, fast when you push.
- NS2 limits gyro to a few games. We built a **Galaxy-style gyro mouse** — system-wide, with one-click re-centering when it drifts.

**This turns console hardware into a truly universal PC input device. Nobody has done this before.**

### Core features

- 🎮 **Faithful bridging (a first in itself)**: Joy-Con 2 (BLE) → virtual Joy-Con 1 (`057E`/`2006`·`2007`), works in Ryujinx/Eden, split L/R, viiper stick calibration, HD rumble + IMU + all buttons.
- 🖱 **Optical mouse mode (beyond NS2)**: two independent mice, optical sensor cursor, **force-based scroll** with sub-notch smoothness, **4 DPI levels** (800/1600/3200/6400) via Plus/Minus, fully remappable buttons.
- 🌀 **Gyro mouse (Super Mario Galaxy on Windows)**: angular-velocity cursor control, system-wide, tunable sensitivity + axis inversion, **stick-press re-centers cursor**.
- ⚙ **Macro system**: C+SL/SR triggers, four bindable side keys, record/save in GUI, persistent config.
- 🌐 **Polish**: **bilingual UI (Chinese/English)**, tray minimize + quick mode switch, scrollable in-page settings, built-in help.

### Install

1. Install USB/IP
2. Grab `WinJoyCon2-Plus.exe` from Releases (or build from source)
3. Hold SYNC on the controllers, click "Connect Both"
4. Switch language at top-right, enable your favorite mode
5. Enjoy — you'll never go back to a normal controller

### Build from source

```bash
cd _src
pip install bleak pynput pyqt5
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WinJoyCon2-Plus --icon logo_256.ico --hidden-import theme --hidden-import i18n --hidden-import virtual --hidden-import virtual.bridge --hidden-import virtual.descriptors --hidden-import virtual.hid_function --hidden-import virtual.reports --hidden-import virtual.usbip --hidden-import virtual.vjoy_out --hidden-import virtual.imu_proc --hidden-import virtual.scroll --hidden-import virtual.rumble_hd --hidden-import virtual.jc2_frame --hidden-import device_cleanup --hidden-import hidden_exec --hidden-import control_type --hidden-import control_type.duo_joycon --hidden-import control_type.single_joycon --hidden-import control_type.mouse_mode --hidden-import controllers --hidden-import controllers.JoyconL --hidden-import controllers.JoyconR --hidden-import error_handler gui.py
```

### Credits

Stick calibration inspired by Alia5/VIIPER; protocol research from ndeadly/switch2_controller_research and SDL `SDL_hidapi_switch2`. Independent reverse-engineering work, not affiliated with Nintendo. Joy-Con and Nintendo Switch are trademarks of Nintendo.

**Built for everyone who wants to push the JC2 to its absolute limit.**
