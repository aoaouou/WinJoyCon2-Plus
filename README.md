# WinJoyCon2-Plus v1.4 — 原生 Joy-Con 2（HIDMaestro 后端）

## 这一版做了什么

从 **v1.2.0**（JC2 原生开发开始前的早期版本）重新起步，只重做 Joy-Con 2 部分：
**Joy-Con 1 桥接和鼠标 / 陀螺仪鼠标 / 宏全部原样保留**。

虚拟设备不再是 usbip/VIIPER 那套，改用 **HIDMaestro** 呈现两只原生设备。

## 关键结论：为什么设备形态是「充电握把 057E:200E」

SDL 上游（Valve 维护）的事实，全部来自 SDL 官方源码：

- `src/hidapi/SDL_hidapijoystick.c:43-117`：驱动数组里 `SDL_HIDAPI_DriverJoyCons`
  （Switch 1 握把 / JC，纯 HID 路径）**排在** `SDL_HIDAPI_DriverSwitch2`
  （Switch 2 JC，需要 libusb + 第二接口 bulk）**前面**。
- `src/joystick/hidapi/SDL_hidapi_switch.c:1300-1319`：`DriverJoyCons`
  只认 `0x2006 / 0x2007 / 0x200E`，**不认独立 JC2 的 `2067 / 2066`**。
- `src/joystick/hidapi/SDL_hidapi_switch2.c:380-403`：`InitUSB` 必须
  libusb + interface 1 bulk + claim 成功，**没有 fallback**；usbip-win2 的
  UDE 驱动下 libusb 打不开接口（实测 pyusb 对真实可用的 Pro2 也 Access denied）。
- `SDL_hidapijoystick.c:533-535`：`InitDevice` 失败 → driver 置 NULL →
  不组合、没有数据。这就是先前「独立 JC2 认得出型号但按键全无反应、
  不成对」的根因。

**真机 JC2 插充电握把时，PC 看到的就是 `057E:200E`**（Switch 2 的握把沿用
Switch 1 握把固件协议）。SDL issue #16824（Valve 官方 issue 库，2026-11-24）
记录的真机日志正是：握把两个 interface 的 `Joy-Con (L)` / `Joy-Con (R)`
组合成 `Joy-Con (L/R)`，PID 0x2068。

**所以本项目用 HIDMaestro 自带的真机原版握把 profile**
（`joycon-l-usb` / `joycon-r-usb`，逐字节来自真机抓包）：
- VID `057E`，PID `200E`（Joy-Con Charging Grip）
- 双 HID 接口：interface 1 = 左槽，interface 0 = 右槽
- 报告 `0x30`：3 字节按钮 + 打包 12 位双摇杆 + IMU 块
- 完整握手序列（Handshake / HighSpeed / ForceUSB / SPI 校准块），
  与 SDL 的 `BTrySetupUSB`、`ReadJoyConControllerType` 逐字节对齐

## 两种模式（组合 / 分开）

两种模式由 **SDL 的「组合手柄」开关**决定（Steam 里就有这个选项，
对应 hint `SDL_JOYSTICK_HIDAPI_COMBINE_JOY_CONS`）——真机 JC2 插握把在
Steam 里也是这个行为：

| 组合开关 | SDL 看到的设备 |
|---|---|
| 开（默认） | 一只 `Nintendo Switch Joy-Con (L/R)`，6 轴 16 键 |
| 关 | 两只独立 `Nintendo Switch Joy-Con (L)` / `(R)`，各 6 轴 16 键 |

**实测（本机，Ryujinx Canary 与 Steam 的 SDL3，端到端走本项目 Python 后端 → 桥接 → HIDMaestro）**：

- 组合开：`Nintendo Switch Joy-Con (L/R)` 轴 `[17221, 10240, -10241, -17222, ...]`，按键 `B/Y` 有反应
- 组合关：`Joy-Con (L)` + `Joy-Con (R)` 两只，各自独立
- SetupAPI：4 个 `VID_057E&PID_200E` HID 节点，状态 OK

## HD 震动 / 陀螺仪 / C 键

- **HD 震动**：HIDMaestro 的 output report → 桥接 `OUT` 消息 → GATT 0x0012 的 HD LRA 块（保真 LRA，不是 XInput 预设）。
- **陀螺仪**：Python 后端 `set_imu_raw` → 桥接 `IMU` → 握把 0x30 报告的 IMU 块（g / dps）。
- **C 键**：Switch 2 实机为语音聊天键，PC 无法实现，保留系统级切换设计。

## 使用

1. `config/config.ini` 里 `output_mode = hidmaestro`（默认即是）。
2. 双击 `WinJoyCon2-Plus.exe`（会请求管理员权限——HIDMaestro 建设备需要管理员 token）。
3. 按手柄 SYNC，程序连上后出现握把设备；在 Steam 里按需开/关「组合手柄」。

切换输出模式：运行 `switch_output_mode.bat`（1=原生 JC2/HIDMaestro，2=旧 Joy-Con 1）。

## 已知事项

- 程序退出时会杀掉 HmBridge 并清理残留设备节点（`device_cleanup.cleanup_on_exit`）。
- `HmBridge.exe` 需与 `HIDMaestro.Core.dll`、`hidmaestro_profiles/*.json` 同目录（打包已包含）。
- 端口：Python ↔ HmBridge 用 TCP 3250；HIDMaestro 自带 usbip 服务随机端口，不占用 3240/3241/3242（与 Pro2 项目不冲突）。
- 独立 JC2 形态（2067/2066）在 SDL 系软件里不可用（根因见上），已弃用；profile 文件仍保留在包内仅作存档。
