<div align="center">

# WinJoyCon2-Plus

### 把 Switch 2 的 Joy-Con 2，变成 PC 上无所不能的操控神器

**这不是又一个手柄映射器 —— 这是 Joy-Con 2 在 Windows 上的完全体。**

**WinJoyCon2-Plus，堂堂登场！**

[![Version](https://img.shields.io/badge/Version-1.1-brightgreen?style=for-the-badge)](./README.md)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?style=for-the-badge&logo=windows)](https://www.microsoft.com/windows)
[![Controller](https://img.shields.io/badge/Controller-Joy--Con%202-E6007D?style=for-the-badge)](https://www.nintendo.com/us/store/products/joy-con-2/)
[![Protocol](https://img.shields.io/badge/Transport-USB%2FIP-28A745?style=for-the-badge)](https://en.wikipedia.org/wiki/USB_over_IP)
[![Language](https://img.shields.io/badge/UI-%E4%B8%AD%E6%96%87%20%2F%20English-FF6FAE?style=for-the-badge)](./README.md)

</div>

---

> **中文** · [English](#english)

> **致任天堂 / A Tribute to Nintendo**
>
> 本项目是一项个人逆向工程与互操作（interoperability）研究作品，源于对任天堂工程成就的深深敬意。我们与任天堂公司无任何隶属、赞助或背书关系。Joy-Con、Nintendo Switch、Super Mario Galaxy 等均为任天堂商标。本项目仅供合法拥有相关硬件的用户在自有设备上使用；我们尊重知识产权，并始终鼓励正当、合法的用途。
>
> *A Tribute to Nintendo — This project is a personal reverse-engineering and interoperability research effort, born of deep respect for Nintendo's engineering achievements. It is in no way affiliated with, sponsored by, or endorsed by Nintendo. Joy-Con, Nintendo Switch, and Super Mario Galaxy are trademarks of Nintendo. This project is intended solely for use with legally owned hardware; we respect intellectual property rights and encourage lawful, legitimate use.*

## 为什么它与众不同？

任天堂造出了 Joy-Con 2 —— 带**光学鼠标传感器**、**高精度陀螺仪**、**HD 震动 2** 的革命性手柄。但在 PC 上，它几乎是一块砖：SDL 的 `InitBluetooth()` 至今是空实现，官方从未让它真正连上 Windows。

于是我们选择了一条不同的路：**不依赖模拟器施舍，直接用 USB/IP 把它桥接成虚拟 Joy-Con 1，再把 JC2 的全部硬件潜力，一寸不落地搬到 Windows。**

结果是一个**在整体体验上超越 NS2 实机、也超越 Windows 原生鼠标**的操控系统：

- NS2 实机的鼠标模式只允许平放桌面、按键写死、滚轮只能倾斜摇杆 —— 我们把它**彻底解放**：三种输入模式、全按键自定义、宏系统、组合键切换，想怎么用就怎么用。
- Windows 原生滚轮一格跳三行、生硬顿挫 —— 我们用**亚格精度连续滚动 + 力度平方曲线**，做到了比真鼠标还丝滑、轻推慢滚满推快滚的模拟量手感。
- NS2 陀螺仪只在个别游戏里当辅助 —— 我们做成了**银河式陀螺仪鼠标**，全系统通用，漂移了一键回中。

**这是把游戏主机的硬件，做成了 PC 上真正通用的输入设备。走的就是这条路。**

## v1.1，堂堂更新！

### 🔀 分开连接模式：陌生手柄也能认清左右
- **陌生 Joy-Con 2 首次使用，必须手动选择左 / 右分开连接**：先连左手就认作左、先连右手就认作右，从源头杜绝左右混淆。
- 连接后程序会**记住每只手柄的左右（KnownSides）**，下一次认得清清楚楚，无需重复指定。
- **只有左右都认清之后，才解锁「一键连接」快速模式**：已建立左右记忆的手柄，日常一键并发连接，快如既往。
- 这一改动彻底解决了「陌生手柄分不出左右」的老大难问题，新手柄开箱即用。

### 🔌 USB/IP 自动检测与一键安装
- **首次启动弹出使用须知**，把依赖与操作讲清楚再上手。
- **检测不到 USB/IP 时，直接提供「一键安装」按钮**，不必再翻文档、找路径。
- **安装按钮常驻界面**：即使误删了 USB/IP，也能随时点一下重装，永不抓瞎。

## 核心能力

### 🎮 忠实桥接

**Joy-Con 2，堂堂桥接！** 一只 Joy-Con 2 进去，一只 Joy-Con 1 出来，模拟器毫无察觉。

- 把 **Joy-Con 2（BLE）** 桥接为 **Switch 1 的 Joy-Con 1**（VID `057E` / PID `2006`·`2007`）
- Ryujinx / Eden 等只认 JC1 的模拟器直接可用，识别为**左右分体**而非 Pro
- 摇杆照 viiper 方案标定：center 2048 / 行程 2047 / 物理拉伸 900，回中精准、推满到边
- HD 震动 2、IMU 六轴、全按键，逐字节保真
- 一键并发连接双柄 + 断线重连 + 幽灵设备自动清理

### 🖱 光学鼠标模式（超越 NS2 官方）

**光学鼠标，堂堂切换！** 手柄一放平，它就成了一只能滚能点、推得越狠滚得越快的鼠标。

- **双柄独立**：左右手柄各自是独立鼠标，系统原生叠加，可单独或同时开启
- 光标走光学传感器原生通道，跟手无延迟
- **力度滚轮**：推得越狠滚得越快，平方曲线低速细腻、高速畅快；亚格精度滚动，比 Windows 原生滚轮丝滑得多
- **四挡 DPI**：800 / 1600 / 3200 / 6400，加键升挡、减键降挡（双手柄到顶停住，单手柄循环）
- 全按键可自定义映射：左/右键、中键、前进/后退侧键、滚轮、光标回中

### 🌀 陀螺仪鼠标（把马力欧银河搬进 Windows）

**银河手感，堂堂模拟！** 手腕一转，光标便走 —— 银河的手感搬进了 Windows 桌面。

- **角速度积分式**光标控制 —— 超级马力欧银河 NS 版的体感逻辑，全系统通用
- 绕竖直轴转动 = 水平移动，绕长轴俯仰 = 垂直移动，停手即停
- 灵敏度、X/Y 反转独立可调，默认已按银河手感标定
- **摇杆按下 = 光标一键回屏幕中心**，漂移即刻归位
- 完美支持 FPS 精细瞄准、桌面浏览、任何需要指针的场景

### ⚙ 宏系统

**宏指令，堂堂触发！** 一键按下，串好的动作便逐帧还原，无需再手忙脚乱。

- C 键 + SL/SR 触发宏，四个侧键各绑一套
- GUI 内录制 / 保存 / 开关，宏与按键配置全部持久化，重启不丢
- 双手柄模式一键同步切换：手柄 / 鼠标 / 陀螺仪

### 🌐 体验细节

**细节，堂堂打磨！** 每个按钮想怎么配就怎么配，配完立刻生效，重启也不丢。

- **中英双语界面**，右上角一键切换
- 最小化到托盘、托盘右键快速切模式、关闭即干净退出
- 页面内跳转的设置面板、可滚动布局、内置使用说明
- 所有自定义即时生效并落盘

## 安装与使用

1. 安装 [USB/IP](https://github.com/cezanne/usbip-win)（本机路径 `C:\Program Files\USBip\usbip.exe`）；**1.1 起若未检测到，程序内可一键安装** —— **USB/IP，堂堂安装！**
2. 下载 Release 中的 `WinJoyCon2-Plus.exe`（或按下方命令自行构建）
3. **首次启动会弹出使用须知**；陌生手柄请先按提示**手动分开连接左 / 右**，程序会记住左右（KnownSides），此后即可「一键连接」—— **双手柄，堂堂连接！**
4. 右上角切换 中文 / English；设置面板里开启你想要的模式
5. 开始享受 —— 你会再也回不去普通手柄了。**杰作，堂堂享用！**

## 从源码构建

```bash
cd _src
python -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name WinJoyCon2-Plus --icon logo_256.ico \
  --hidden-import theme --hidden-import i18n \
  --hidden-import virtual --hidden-import virtual.bridge \
  --hidden-import virtual.descriptors --hidden-import virtual.hid_function \
  --hidden-import virtual.reports --hidden-import virtual.usbip \
  --hidden-import virtual.vjoy_out --hidden-import virtual.imu_proc \
  --hidden-import virtual.scroll --hidden-import virtual.rumble_hd \
  --hidden-import virtual.jc2_frame --hidden-import device_cleanup \
  --hidden-import hidden_exec --hidden-import control_type \
  --hidden-import control_type.duo_joycon --hidden-import control_type.single_joycon \
  --hidden-import control_type.mouse_mode --hidden-import controllers \
  --hidden-import controllers.JoyconL --hidden-import controllers.JoyconR \
  --hidden-import error_handler gui.py
```

需要 Python 3.10+（`pip install bleak pynput pyqt5`）与 Windows 10/11。

**源码，堂堂构建！** 一条命令，一个 exe，绿色便携，双击即用。

## 致谢

本项目站在以下先行者的工作之上，谨致谢意：

- [Joy2Win](https://github.com/Logan-Gaillard/Joy2Win) —— 本项目的前身与起点：**GUI 的地基**与**连接手柄的实现**均来自它
- [XinHeLianSheng-Pro2-Bridge](https://github.com/LeonChrome/XinHeLianSheng-Pro2-Bridge)（`source/final-three-in-one`）：在**各个方面**都为本项目提供了宝贵参考，包括内置 usbip-win2 v0.9.7.7 的 USB/IP 安装包与运行时定位思路
- [cezanne/usbip-win](https://github.com/cezanne/usbip-win)（usbip-win2）：提供 Windows 上的 USB/IP 驱动
- [Alia5/VIIPER](https://github.com/Alia5/ViGEmBus)：摇杆标定方案的成熟实现
- [ndeadly/switch2_controller_research](https://github.com/ndeadly/switch2_controller_research) 与 SDL `SDL_hidapi_switch2`：协议研究成果
- 灵感来自任天堂的硬件工程，以及《超级马力欧银河》那套令人惊叹的陀螺仪交互

**先行者，堂堂致谢！** 没有这些先行者，就没有今天这个项目。

**WinJoyCon2-Plus，堂堂开源！** 为所有想把 JC2 用到极致的人而造。

### 免责与致敬声明

本项目是一个**非官方**的个人技术作品，**与任天堂公司没有任何隶属、赞助或背书关系**（not affiliated with, sponsored by, or endorsed by Nintendo）。它以纯粹的**技术交流与互操作（interoperability）研究**为目的，探索公开协议在通用操作系统上的可能性，绝不用于任何侵犯他人权益的用途。

本项目**不包含、不分发、也不提供**任何任天堂专有固件、密钥、签名材料、受版权保护的音画资源或商标图案；仓库中出现的 Joy-Con、Nintendo Switch、Super Mario Galaxy 等名称仅用于说明兼容性，其商标权归任天堂所有。使用者需**自行准备合法拥有**的硬件，并在符合当地法律与外设服务条款的前提下使用；作者不对任何游戏、平台或服务因使用本软件而产生的封禁、数据损失、账号异常或其他任何后果负责。

我们以最大的诚意**致敬任天堂数十年来的硬件工程成就**：Joy-Con 2 的光学鼠标传感器与高精度陀螺仪是真正令人敬佩的设计；《超级马力欧银河》把体感做成一种优雅的语言，正是这种交互灵感推动了本项目陀螺仪鼠标的实现。我们鼓励一切正当、合法、尊重知识产权的用途；**若权利方对项目有任何异议或意见，我们愿意第一时间沟通、配合调整或下架**。技术应当用来扩展合法硬件的可能性，而非损害任何人的正当权益。

---

<a name="english"></a>

## English

### Turn the Switch 2 Joy-Con 2 into an all-powerful controller on PC

**This is not another gamepad mapper — it is the complete form of the Joy-Con 2 on Windows.**

**WinJoyCon2-Plus, grandly arriving!**

> **English** · [中文](#why-it-is-different)

### Why it is different?

Nintendo built a revolutionary controller — an **optical mouse sensor**, **precision gyroscope**, and **HD Rumble 2**. On PC it was nearly a brick: SDL's `InitBluetooth()` is still a stub, and Nintendo never made it work on Windows.

So we took a different path: **instead of waiting for emulator support, we bridge it over USB/IP as a virtual Joy-Con 1, then unlock every bit of the JC2's hardware potential on Windows.**

The result is a control system that **surpasses the NS2 console itself and Windows' native mouse experience**:

- On NS2, mouse mode only works lying flat, buttons are hardwired, and scroll is a crude stick tilt. We **set it free**: three input modes, fully remappable buttons, macros, combo-key switching — your controller, your rules.
- Windows native scroll jumps 3 lines per notch, stiff and jarring. We built **sub-notch continuous scrolling with a squared force curve** — smoother than a real mouse, slow when you nudge, fast when you push.
- NS2 limits gyro to a few games. We built a **Galaxy-style gyro mouse** — system-wide, with one-click re-centering when it drifts.

**This turns console hardware into a truly universal PC input device. This path, grandly chosen!**

### v1.1, grandly updated!

#### 🔀 Separate connection mode: even unfamiliar controllers know left from right
- **An unfamiliar Joy-Con 2 must be connected manually as left or right on first use**: whichever you pair first is registered as that side, eliminating left/right confusion at the source.
- The app then **remembers each controller's side (KnownSides)**, so the next time it just knows — no repeated setup.
- **One-click "Connect Both" unlocks only once both sides are identified**: with left/right memorized, daily use is a single fast concurrent connection.
- This finally solves the old headache of "can't tell left from right on a new controller" — new units work right out of the box.

#### 🔌 USB/IP auto-detection and one-click install
- **A usage guide pops up on first launch**, explaining dependencies and operation before you start.
- **If USB/IP is not detected, a one-click "Install" button is right there** — no more hunting through docs and paths.
- **The install button stays available at all times**: even if USB/IP is accidentally removed, one click reinstalls it.

### Core features

#### 🎮 Faithful bridging

**Joy-Con 2, grandly bridging!** A Joy-Con 2 goes in, a Joy-Con 1 comes out — the emulator never notices.

- Joy-Con 2 (BLE) → virtual Joy-Con 1 (`057E` / `2006`·`2007`)
- Works in Ryujinx/Eden as **split left/right**, not a Pro controller
- viiper stick calibration: center 2048 / travel 2047 / physical stretch 900
- HD Rumble 2, 6-axis IMU, all buttons — byte-for-byte faithful
- Concurrent dual connect + auto-reconnect + ghost device cleanup

#### 🖱 Optical mouse mode (beyond NS2)

**Optical mouse, grandly switching!** Lay it flat and it becomes a mouse that clicks, scrolls, and scrolls faster the harder you push.

- **Two independent mice**: each Joy-Con is its own mouse, natively composited by the OS
- Cursor driven by the optical sensor's native channel — zero added latency
- **Force-based scroll**: squared curve, fine at low speed, fast when pushed; sub-notch smoothness
- **4 DPI levels**: 800 / 1600 / 3200 / 6400 via Plus/Minus
- Fully remappable: left/right/middle, forward/back side keys, scroll, cursor-centering

#### 🌀 Gyro mouse (Super Mario Galaxy on Windows)

**Galaxy feel, grandly simulating!** A turn of the wrist moves the cursor — Galaxy's feel, brought to the Windows desktop.

- **Angular-velocity** cursor control — Galaxy-style motion logic, system-wide
- Rotate about the vertical axis = horizontal; pitch about the long axis = vertical; stops when you stop
- Sensitivity and X/Y inversion independently tunable, pre-calibrated to the Galaxy feel
- **Stick press = cursor back to screen center**, instantly
- Perfect for FPS aiming, desktop browsing, anything needing a pointer

#### ⚙ Macro system

**Macros, grandly triggering!** One key press replays the whole recorded sequence, frame by frame.

- C + SL/SR triggers, one macro per side key (four total)
- Record / save / toggle in the GUI; macros and mappings all persisted
- Sync all controllers to one mode: gamepad / mouse / gyro

#### 🌐 Polish

**Details, grandly polished!** Every button maps the way you want it, effective instantly, persistent across restarts.

- **Bilingual UI** (Chinese/English), switch at top-right
- Minimize to tray, tray menu for quick mode switch, clean exit on close
- In-page settings, scrollable layout, built-in help
- All customizations applied instantly and written to disk

### Install

1. Install [USB/IP](https://github.com/cezanne/usbip-win) — **as of 1.1, the app offers a one-click install if it is not detected** — **USB/IP, grandly installing!**
2. Grab `WinJoyCon2-Plus.exe` from Releases (or build from source below)
3. **A usage guide appears on first launch**; for an unfamiliar controller, **connect left/right manually** as prompted — the app remembers the sides (KnownSides), after which "Connect Both" works instantly — **Both Joy-Con, grandly connecting!**
4. Switch language at top-right, enable your favorite mode in settings
5. Enjoy — you'll never go back to a normal controller. **A masterpiece, grandly enjoying!**

### Build from source

```bash
cd _src
pip install bleak pynput pyqt5
python -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name WinJoyCon2-Plus --icon logo_256.ico \
  --hidden-import theme --hidden-import i18n \
  --hidden-import virtual --hidden-import virtual.bridge \
  --hidden-import virtual.descriptors --hidden-import virtual.hid_function \
  --hidden-import virtual.reports --hidden-import virtual.usbip \
  --hidden-import virtual.vjoy_out --hidden-import virtual.imu_proc \
  --hidden-import virtual.scroll --hidden-import virtual.rumble_hd \
  --hidden-import virtual.jc2_frame --hidden-import device_cleanup \
  --hidden-import hidden_exec --hidden-import control_type \
  --hidden-import control_type.duo_joycon --hidden-import control_type.single_joycon \
  --hidden-import control_type.mouse_mode --hidden-import controllers \
  --hidden-import controllers.JoyconL --hidden-import controllers.JoyconR \
  --hidden-import error_handler gui.py
```

Requires Windows 10/11 and Python 3.10+.

**Source code, grandly building!** One command, one exe, portable and ready to double-click.

### Credits

This project stands on the shoulders of the following prior work — with thanks:

- [Joy2Win](https://github.com/Logan-Gaillard/Joy2Win) — the predecessor and starting point of this project: both the **foundation of the GUI** and the **controller connection implementation** come from it
- [XinHeLianSheng-Pro2-Bridge](https://github.com/LeonChrome/XinHeLianSheng-Pro2-Bridge) (`source/final-three-in-one`): provided valuable reference across **every aspect** of this project, including its bundled usbip-win2 v0.9.7.7 USB/IP installer and its approach to locating the runtime.
- [cezanne/usbip-win](https://github.com/cezanne/usbip-win) (usbip-win2): USB/IP driver for Windows.
- [Alia5/VIIPER](https://github.com/Alia5/ViGEmBus): mature stick-calibration implementation.
- [ndeadly/switch2_controller_research](https://github.com/ndeadly/switch2_controller_research) and SDL `SDL_hidapi_switch2`: protocol research.
- Inspired by Nintendo's hardware engineering and the wonderful gyro interaction of Super Mario Galaxy.

**Pioneers, grandly thanking!** Without these pioneers, this project would not exist today.

**WinJoyCon2-Plus, grandly open-sourced!** — with dignity and confidence. Built for everyone who wants to push the JC2 to its absolute limit.

### Disclaimer & Tribute

This project is an **unofficial** personal technical work and is **in no way affiliated with, sponsored by, or endorsed by Nintendo**. It exists purely for **technical exchange and interoperability research**, exploring what public protocols can do on general-purpose operating systems, and is not intended for any purpose that infringes on others' rights.

This project **does not contain, distribute, or provide** any Nintendo proprietary firmware, keys, signing material, copyrighted audio/visual assets, or trademark artwork. Names such as Joy-Con, Nintendo Switch, and Super Mario Galaxy appear only to describe compatibility; their trademarks remain the property of Nintendo. Users must **provide their own legally owned** hardware and use it in compliance with local law and applicable service terms. The author is not responsible for any ban, data loss, account irregularity, or other consequence arising from the use of this software with any game, platform, or service.

We offer our deepest respect to **Nintendo's decades of hardware engineering achievement**: the Joy-Con 2's optical mouse sensor and precision gyroscope are genuinely admirable designs, and the way *Super Mario Galaxy* turned motion into an elegant language is exactly the inspiration behind this project's gyro mouse. We encourage all lawful, legitimate uses that respect intellectual property. **Should the rights holder raise any objection or concern, we are ready to engage, cooperate, and adjust or take the project down promptly.** Technology should expand what legally owned hardware can do — never harm anyone's legitimate interests.
