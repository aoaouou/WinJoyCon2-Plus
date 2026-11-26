<div align="center">

# WinJoyCon2-Plus v2.1

### 把 Switch 2 的 Joy-Con 2，变成 PC 上无所不能的操控神器

**这不是又一个手柄映射器 —— 这是 Joy-Con 2 在 Windows 上的完全体。**

**WinJoyCon2-Plus，堂堂登场！**

[![Version](https://img.shields.io/badge/Version-2.1-brightgreen?style=for-the-badge)](./README.md)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?style=for-the-badge&logo=windows)](https://www.microsoft.com/windows)
[![Controller](https://img.shields.io/badge/Controller-Joy--Con%202-E6007D?style=for-the-badge)](https://www.nintendo.com/us/store/products/joy-con-2/)
[![Protocol](https://img.shields.io/badge/Backend-HIDMaestro-6f42c1?style=for-the-badge)](https://github.com/BrikWork/HIDMaestro)
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

于是我们选择了一条不同的路：**不依赖模拟器施舍，直接把它桥接成两只独立的虚拟 Joy-Con 1，再把 JC2 的全部硬件潜力，一寸不落地搬到 Windows。**

输出层采用 **HIDMaestro**（纯用户态 + 自带 usbip 后端），彻底舍弃旧 USB/IP 方案。平台自动把左右两只组合成 `Joy-Con (L/R)`，SDL2 / SDL3 模拟器与 Steam 全部识别使用。

结果是一个**在整体体验上超越 NS2 实机、也超越 Windows 原生鼠标**的操控系统：

- NS2 实机的鼠标模式只允许平放桌面、按键写死、滚轮只能倾斜摇杆 —— 我们把它**彻底解放**：三种输入模式、全按键自定义、宏系统、组合键切换，想怎么用就怎么用。
- Windows 原生滚轮一格跳三行、生硬顿挫 —— 我们用**亚格精度连续滚动 + 力度平方曲线**，做到了比真鼠标还丝滑、轻推慢滚满推快滚的模拟量手感。
- NS2 陀螺仪只在个别游戏里当辅助 —— 我们做成了**银河式陀螺仪鼠标**，全系统通用，漂移了一键回中。

**这是把游戏主机的硬件，做成了 PC 上真正通用的输入设备。走的就是这条路。**

## v2.1，堂堂更新！

*v2.1, grandly updated!*

- **GL/GR，堂堂兼容！** 充电握把的两个背键（左手 GLL/GRL、右手 GLR/GRR）现已支持：默认无功能，可在「自定义按键」页映射成任意键，并可像 SL/SR 一样绑定与录制宏（C + 背键触发）。握把背键在 0x05 报告的 buttons byte3（bit1=GL、bit0=GR），照权威位表解析；未接握把时恒为 0，完全不影响原有功能。

## v2.0，堂堂更新！

*v2.0, grandly updated!*

这一版输出层全面重构到 HIDMaestro，旧 USB/IP 推倒重来，一批实机问题连根拔起。

- **彻底删除旧 USB/IP 全套**（约 4100 行）：vjoy_out / usbip / bridge / hid_function / descriptors / usbip_setup / 内置安装包，一并清走。输出层只剩 HIDMaestro 一条路径。
- **修 IMU 死锁**：profile 的 IMU 块原包在 `when:"imu"` 里，主机与 SDL 互相等对方先发数据，导致 IMU 恒为零。改为无条件填充，陀螺仪 / 加速度计全部可用。
- **修无震动**：事件委托签名不兼容、异常被吞，导致事件从未订阅。改用 Expression 构造正确委托，震动链路打通，直送真 JC2 GATT `0x0012`。
- **修回中心失效**：`pynput.Controller` 无 `size` 属性导致静默失败，改为 Qt / Win32 三级取屏幕尺寸，自适应任意分辨率。
- **修退出后断连重连**：退出时按 PID 无条件移除自建设备节点，不再留空壳让 Windows 反复枚举。
- **连接提速**：去掉 7 秒盲等改端口轮询，约 9 秒压到 2~3 秒。
- **DPI 降一档**：400 / 800 / 1600 / 3200，默认第 2 档；**LS / RS** 一键回中心。
- **删掉「模拟器兼容」死代码选项**；版本号 1.2 → 2.0。

### 🛡 已验证与未支持的运行环境

- ✅ **已测试**：SDL2 / SDL3 模拟器（含 Ryujinx 1.3.3、Canary）、Steam —— 手柄按键、摇杆、HD 震动、陀螺仪全部识别使用。
- ❌ **不支持**：时之笛转译版（Longshot）—— 该游戏输入层只接受 DualSense / DualShock 4 / Switch Pro / Xbox，二进制内无 JoyCon 判定；单独 Joy-Con 在 SDL 里是 `JOYCON_LEFT/RIGHT` 类型，不在其支持集合内。这是游戏侧限制，该游戏请用 Pro 手柄。

> 两个程序请勿**同时占用同一只手柄** —— 与真实 USB 手柄一样，设备同一时间只能被一个主机独占；同时连接会导致后连者抢占、先连者按键错位，重连即可恢复。

## 核心能力

### 🎮 忠实桥接

**Joy-Con 2，堂堂桥接！** 一只 Joy-Con 2 进去，一只 Joy-Con 1 出来，平台毫无察觉。

- 把 **Joy-Con 2（BLE）** 桥接为两只**独立的 Switch 1 Joy-Con 1**（VID `057E` / PID `2006`·`2007`）
- 输出层为 **HIDMaestro**（纯用户态 + 自带 usbip 后端），彻底舍弃旧 USB/IP
- 平台自动把左右两只组合成 `Joy-Con (L/R)`，无需手动开关
- 自带真机 profile `joycon-l.json` / `joycon-r.json`（170 字节真机描述符）
- 摇杆照 viiper 方案标定：center 2048 / 行程 2047 / 物理拉伸 900，回中精准、推满到边
- HD 震动 2、IMU 六轴、全按键，逐字节保真；SDL 侧 6 个传感器全部可用

### 🖱 光学鼠标模式（超越 NS2 官方）

**光学鼠标，堂堂切换！** 手柄一放平，它就成了一只能滚能点、推得越狠滚得越快的鼠标。

- **双柄独立**：左右手柄各自是独立鼠标，系统原生叠加，可单独或同时开启
- 光标走光学传感器原生通道，跟手无延迟
- **力度滚轮**：推得越狠滚得越快，平方曲线低速细腻、高速畅快；亚格精度滚动，比 Windows 原生滚轮丝滑得多
- **四挡 DPI**：400 / 800 / 1600 / 3200，默认第 2 档（加键升挡、减键降挡）
- **LS / RS 一键回屏幕中心**，自适应任意分辨率与缩放
- 全按键可自定义映射：左/右键、中键、前进/后退侧键、滚轮、光标回中

### 🌀 陀螺仪鼠标（把马力欧银河搬进 Windows）

**银河手感，堂堂模拟！** 手腕一转，光标便走 —— 银河的手感搬进了 Windows 桌面。

- **角速度积分式**光标控制 —— 超级马力欧银河 NS 版的体感逻辑，全系统通用
- 绕竖直轴转动 = 水平移动，绕长轴俯仰 = 垂直移动，停手即停
- 灵敏度、X/Y 反转独立可调，默认已按银河手感标定
- IMU 三组同值填充 —— 只填一组，灵敏度会掉到三分之一
- **摇杆按下 = 光标一键回屏幕中心**，漂移即刻归位
- 完美支持 FPS 精细瞄准、桌面浏览、任何需要指针的场景

### ⚙ 宏系统

**宏指令，堂堂触发！** 一键按下，串好的动作便逐帧还原，无需再手忙脚乱。

- C 键 + SL/SR 触发宏，四个侧键各绑一套；**充电握把 GL/GR 背键同样可绑**（C + 背键触发，共八选一）
- GUI 内录制 / 保存 / 开关，宏与按键配置全部持久化，重启不丢
- 双手柄模式一键同步切换：手柄 / 鼠标 / 陀螺仪

### 🌐 体验细节

**细节，堂堂打磨！** 每个按钮想怎么配就怎么配，配完立刻生效，重启也不丢。

- **HD 震动，堂堂还原！** 原始 4 字节块 → `jc1_block_to_jc2`，SDL 权威振幅表 + 频率锁 JC2 原生，直送真 JC2 GATT `0x0012`
- 连接提速（2~3 秒）、退出清理、链路自愈，一处不落
- **中英双语界面**，右上角一键切换
- 最小化到托盘、托盘右键快速切模式、关闭即干净退出
- 页面内跳转的设置面板、可滚动布局、内置使用说明
- 所有自定义即时生效并落盘

## 安装与使用

1. 下载 Release 中的 `WinJoyCon2-Plus.exe`（绿色单文件，双击即用）。
2. 双击运行并按提示**请求管理员权限** —— HIDMaestro 建设备必需。**HIDMaestro，堂堂接管！**
3. 按手柄 SYNC 连接。平台自动认出两只 Joy-Con 1 并组合 —— **双手柄，堂堂连接！**
4. 右上角切换 中文 / English；设置面板里开启你想要的模式。
5. 开始享受 —— 你会再也回不去普通手柄了。**杰作，堂堂享用！**

## 从源码构建

源码在 `D:\Games\Nintendo\tool\Joycon2-hidmaestro`，桥接（C#）与 Python 打包分两步：

```powershell
cd D:\Games\Nintendo\tool\Joycon2-hidmaestro\_src

# ① 桥接（改过 hidmaestro_bridge 下的 .cs 时）
dotnet build -c Release -o .\hidmaestro_bridge\buildout .\hidmaestro_bridge
# 把 buildout 下 HmBridge.dll/.exe/.deps.json/.runtimeconfig.json/HIDMaestro.Core.dll 复制到 bin/ 与 bridge_runtime/

# ② Python 打包
python -m PyInstaller --noconfirm --clean WinJoyCon2-Plus.spec
```

需要 Python 3.10+（`pip install bleak pynput pyqt5`）与 Windows 10/11。

**源码，堂堂构建！** 一个 exe，绿色便携，双击即用。

## 致谢

本项目站在以下先行者的工作之上，谨致谢意：

- [Joy2Win](https://github.com/Logan-Gaillard/Joy2Win) —— 本项目的前身与起点：**GUI 的地基**与**连接手柄的实现**均来自它
- [XinHeLianSheng-Pro2-Bridge](https://github.com/LeonChrome/XinHeLianSheng-Pro2-Bridge)（`source/final-three-in-one`）：在**各个方面**都为本项目提供了宝贵参考
- [HIDMaestro](https://github.com/BrikWork/HIDMaestro) —— v2.0 的输出层基石：纯用户态虚拟手柄框架与真机 profile
- [cezanne/usbip-win](https://github.com/cezanne/usbip-win)（usbip-win2）：v1.x 时代的 USB/IP 驱动，为早期方案提供关键参考
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

So we took a different path: **instead of waiting for emulator support, we bridge it as two independent virtual Joy-Con 1s, then unlock every bit of the JC2's hardware potential on Windows.**

The output layer uses **HIDMaestro** (pure user-mode with a built-in usbip backend), completely replacing the old USB/IP approach. The platform automatically combines the two halves into `Joy-Con (L/R)` — SDL2 / SDL3 emulators and Steam all recognize it.

The result is a control system that **surpasses the NS2 console itself and Windows' native mouse experience**:

- On NS2, mouse mode only works lying flat, buttons are hardwired, and scroll is a crude stick tilt. We **set it free**: three input modes, fully remappable buttons, macros, combo-key switching — your controller, your rules.
- Windows native scroll jumps 3 lines per notch, stiff and jarring. We built **sub-notch continuous scrolling with a squared force curve** — smoother than a real mouse, slow when you nudge, fast when you push.
- NS2 limits gyro to a few games. We built a **Galaxy-style gyro mouse** — system-wide, with one-click re-centering when it drifts.

**This turns console hardware into a truly universal PC input device. This path, grandly chosen!**

### v2.1, grandly updated!

*v2.1, grandly updated!*

- **GL/GR, grandly supported!** The two grip back buttons (left GLL/GRL, right GLR/GRR) are now supported: unmapped by default, remappable to any key in the Custom Keys page, and recordable as macros just like SL/SR (C + back button to trigger). Grip back buttons live in the 0x05 report's buttons byte3 (bit1=GL, bit0=GR), parsed per the authoritative bit table; with no grip attached they read zero and change nothing.

### v2.0, grandly updated!

*v2.0, grandly updated!*

This release rebuilds the output layer on HIDMaestro, tears down the old USB/IP stack, and fixes a batch of real-world issues at the root.

- **Old USB/IP stack completely removed** (~4,100 lines): vjoy_out / usbip / bridge / hid_function / descriptors / usbip_setup / bundled installer. HIDMaestro is now the only output path.
- **Fixed the IMU deadlock**: the profile's IMU block was wrapped in `when:"imu"`, which needed a host EnableIMU command that SDL only sends after it has already seen IMU data — a chicken-and-egg loop leaving IMU permanently zero. It is now filled unconditionally, so gyro and accelerometer all work.
- **Fixed "no rumble"**: an incompatible event-delegate signature plus a swallowed exception meant the event was never subscribed. Switched to an Expression-built delegate; the rumble path now reaches the real JC2 over GATT `0x0012`.
- **Fixed re-centering**: `pynput.Controller` has no `size` attribute and the exception was swallowed — silent failure. Now uses a Qt / Win32 three-tier screen-size lookup that adapts to any resolution.
- **Fixed post-exit reconnect loops**: on exit, self-created device nodes are now removed by PID unconditionally, instead of leaving hollow nodes for Windows to re-enumerate forever.
- **Faster connection**: removed 7 seconds of blind sleeps in favor of port polling — about 9 s down to 2–3 s.
- **DPI lowered one notch**: 400 / 800 / 1600 / 3200, default 2nd level; **LS / RS** re-center the cursor.
- **Removed the dead "emulator compatibility" option**; version bumped 1.2 → 2.0.

#### 🛡 Verified and unsupported environments

- ✅ **Tested**: SDL2 / SDL3 emulators (including Ryujinx 1.3.3 and Canary), Steam — buttons, sticks, HD rumble, and gyro all recognized and working.
- ❌ **Not supported**: Ocarina of Time translation (Longshot) — its input layer only accepts DualSense / DualShock 4 / Switch Pro / Xbox and contains no JoyCon handling. A single Joy-Con appears to SDL as `JOYCON_LEFT/RIGHT`, outside its supported set. This is a game-side limitation; use a Pro controller for that game.

> Please do **not** let two programs occupy the same controller at once — just like a real USB controller, a device can be owned by only one host at a time. Connecting both makes the later one take over and the earlier one's buttons misalign; reconnect to recover.

### Core features

#### 🎮 Faithful bridging

**Joy-Con 2, grandly bridging!** A Joy-Con 2 goes in, a Joy-Con 1 comes out — the platform never notices.

- Bridges **Joy-Con 2 (BLE)** into two **independent Switch 1 Joy-Con 1s** (VID `057E` / PID `2006`·`2007`)
- Output layer is **HIDMaestro** (pure user-mode + built-in usbip backend), fully replacing the old USB/IP stack
- The platform automatically combines left and right into `Joy-Con (L/R)` — no manual toggles
- Bundles real-device profiles `joycon-l.json` / `joycon-r.json` (170-byte real descriptor)
- viiper stick calibration: center 2048 / travel 2047 / physical stretch 900
- HD Rumble 2, 6-axis IMU, all buttons — byte-for-byte faithful; all six SDL sensors available

#### 🖱 Optical mouse mode (beyond NS2)

**Optical mouse, grandly switching!** Lay it flat and it becomes a mouse that clicks, scrolls, and scrolls faster the harder you push.

- **Two independent mice**: each Joy-Con is its own mouse, natively composited by the OS
- Cursor driven by the optical sensor's native channel — zero added latency
- **Force-based scroll**: squared curve, fine at low speed, fast when pushed; sub-notch smoothness
- **4 DPI levels**: 400 / 800 / 1600 / 3200, default 2nd level (Plus raises, Minus lowers)
- **LS / RS re-center the cursor**, adapting to any resolution and scaling
- Fully remappable: left/right/middle, forward/back side keys, scroll, cursor-centering

#### 🌀 Gyro mouse (Super Mario Galaxy on Windows)

**Galaxy feel, grandly simulating!** A turn of the wrist moves the cursor — Galaxy's feel, brought to the Windows desktop.

- **Angular-velocity** cursor control — Galaxy-style motion logic, system-wide
- Rotate about the vertical axis = horizontal; pitch about the long axis = vertical; stops when you stop
- Sensitivity and X/Y inversion independently tunable, pre-calibrated to the Galaxy feel
- IMU filled with the same value in all three slots — filling only one would drop sensitivity to a third
- **Stick press = cursor back to screen center**, instantly
- Perfect for FPS aiming, desktop browsing, anything needing a pointer

#### ⚙ Macro system

**Macros, grandly triggering!** One key press replays the whole recorded sequence, frame by frame.

- C + SL/SR triggers, one macro per side key (four total); **grip GL/GR back buttons work too** (C + back button, eight total)
- Record / save / toggle in the GUI; macros and mappings all persisted
- Sync all controllers to one mode: gamepad / mouse / gyro

#### 🌐 Polish

**Details, grandly polished!** Every button maps the way you want it, effective instantly, persistent across restarts.

- **HD rumble, grandly restored!** Raw 4-byte blocks → `jc1_block_to_jc2`, SDL's authoritative amplitude table + JC2-native frequencies, delivered over GATT `0x0012`
- Faster connection (2–3 s), clean exit, link self-healing — nothing left out
- **Bilingual UI** (Chinese/English), switch at top-right
- Minimize to tray, tray menu for quick mode switch, clean exit on close
- In-page settings, scrollable layout, built-in help
- All customizations applied instantly and written to disk

### Install

1. Grab `WinJoyCon2-Plus.exe` from Releases (portable single file, double-click to run).
2. Run it and **grant administrator privileges** when prompted — required for HIDMaestro to create devices. **HIDMaestro, grandly taking over!**
3. Press SYNC on the controllers. The platform recognizes both Joy-Con 1s and combines them — **Both Joy-Con, grandly connecting!**
4. Switch language at top-right, enable your favorite mode in settings.
5. Enjoy — you'll never go back to a normal controller. **A masterpiece, grandly enjoying!**

### Build from source

Source: `D:\Games\Nintendo\tool\Joycon2-hidmaestro`. The bridge (C#) and the Python package are two steps:

```powershell
cd D:\Games\Nintendo\tool\Joycon2-hidmaestro\_src

# ① Bridge (only when .cs under hidmaestro_bridge changed)
dotnet build -c Release -o .\hidmaestro_bridge\buildout .\hidmaestro_bridge
# Copy HmBridge.dll/.exe/.deps.json/.runtimeconfig.json/HIDMaestro.Core.dll from buildout into bin/ and bridge_runtime/

# ② Python package
python -m PyInstaller --noconfirm --clean WinJoyCon2-Plus.spec
```

Requires Windows 10/11 and Python 3.10+ (`pip install bleak pynput pyqt5`).

**Source code, grandly building!** One exe, portable and ready to double-click.

### Credits

This project stands on the shoulders of the following prior work — with thanks:

- [Joy2Win](https://github.com/Logan-Gaillard/Joy2Win) — the predecessor and starting point of this project: both the **foundation of the GUI** and the **controller connection implementation** come from it
- [XinHeLianSheng-Pro2-Bridge](https://github.com/LeonChrome/XinHeLianSheng-Pro2-Bridge) (`source/final-three-in-one`): provided valuable reference across **every aspect** of this project
- [HIDMaestro](https://github.com/BrikWork/HIDMaestro) — the foundation of v2.0's output layer: a pure user-mode virtual-controller framework with real-device profiles
- [cezanne/usbip-win](https://github.com/cezanne/usbip-win) (usbip-win2): the USB/IP driver behind the v1.x approach, a key reference for the early design
- [Alia5/VIIPER](https://github.com/Alia5/ViGEmBus): mature stick-calibration implementation
- [ndeadly/switch2_controller_research](https://github.com/ndeadly/switch2_controller_research) and SDL `SDL_hidapi_switch2`: protocol research
- Inspired by Nintendo's hardware engineering and the wonderful gyro interaction of Super Mario Galaxy.

**Pioneers, grandly thanking!** Without these pioneers, this project would not exist today.

**WinJoyCon2-Plus, grandly open-sourced!** — with dignity and confidence. Built for everyone who wants to push the JC2 to its absolute limit.

### Disclaimer & Tribute

This project is an **unofficial** personal technical work and is **in no way affiliated with, sponsored by, or endorsed by Nintendo**. It exists purely for **technical exchange and interoperability research**, exploring what public protocols can do on general-purpose operating systems, and is not intended for any purpose that infringes on others' rights.

This project **does not contain, distribute, or provide** any Nintendo proprietary firmware, keys, signing material, copyrighted audio/visual assets, or trademark artwork. Names such as Joy-Con, Nintendo Switch, and Super Mario Galaxy appear only to describe compatibility; their trademarks remain the property of Nintendo. Users must **provide their own legally owned** hardware and use it in compliance with local law and applicable service terms. The author is not responsible for any ban, data loss, account irregularity, or other consequence arising from the use of this software with any game, platform, or service.

We offer our deepest respect to **Nintendo's decades of hardware engineering achievement**: the Joy-Con 2's optical mouse sensor and precision gyroscope are genuinely admirable designs, and the way *Super Mario Galaxy* turned motion into an elegant language is exactly the inspiration behind this project's gyro mouse. We encourage all lawful, legitimate uses that respect intellectual property. **Should the rights holder raise any objection or concern, we are ready to engage, cooperate, and adjust or take the project down promptly.** Technology should expand what legally owned hardware can do — never harm anyone's legitimate interests.
