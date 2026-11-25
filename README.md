# WinJoyCon2-Plus v1.3 — 原生 Joy-Con 2（HIDMaestro 后端）

## 这一版做了什么

从 **v1.2.0**（JC2 原生开发开始前的早期版本）重新起步，只重做 Joy-Con 2 部分：
**Joy-Con 1 桥接和鼠标 / 陀螺仪鼠标 / 宏全部原样保留**。

虚拟设备不再是 usbip/VIIPER 那套，改用 **HIDMaestro**（纯用户态 UMDF2 / 自带 usbip 后端）呈现：

- VID `057E`，PID `2067`(L) / `2066`(R) —— 真正的 Joy-Con 2 身份
- 真机 100 字节 HID 报告描述符（`0x05` 共通 / `0x07`(L)·`0x08`(R) 结构化 / `0x01` 输出）
- 两个 input report 同时发：
  - `0x07`/`0x08`：带标准 Button/X/Y usage，浏览器 Gamepad API、DirectInput、Windows GameInput、SDL 通用 HID 路径都能解析
  - `0x05`：SDL3 switch2 驱动读的共通报告（按钮 data[6:8]、摇杆 data[11:14]、IMU data[0x2B:]）
- HD 震动保留：HIDMaestro 的 output report → 桥接 `OUT` 消息 → GATT 0x0012 的 HD LRA 块
- C 键保持系统级模式切换（Switch 2 实机为语音聊天键，PC 无法实现）

## 实测结果（本机）

| 软件 | 结果 |
|---|---|
| Ryujinx Canary SDL3 | 认出 `Nintendo Joy-Con 2 (L/R)`，摇杆与按键数据非零 |
| Steam SDL3 | 同上 |
| SetupAPI HID 枚举 | 命中 2 个 `057E` HID 接口，报告 id=0x07/0x08，数据非零 |
| 原始 VIIPER 方案 | 设备认得出但数据全 0（已弃用） |

## 为什么以前不行（根因，有据可查）

1. **UMDF2 后端不注册 HID 设备接口类**：SetupAPI 枚举到 25 个 HID 接口，0 个来自 UMDF2 设备。hidapi/SDL 拿不到句柄 → 设备管理器正常但数据全 0。
2. **usbip 后端的 HidUsb 会正常注册 HID 接口**，这是现在的方案。
3. SDL3 的 switch2 驱动需要第二接口 bulk + libusb（`SDL_hidapi_switch2.c` 的 `FindBulkEndpoints` / `InitUSB`），虚拟设备做不到；但**普通 HID 路径**可以，只要设备持续发带 usage 的报告。

## 使用

1. `config\config.ini` 里 `output_mode = hidmaestro`（默认即是）。
2. 双击 `WinJoyCon2-Plus.exe`（会请求管理员权限——HIDMaestro 建设备需要管理员 token）。
3. 按手柄 SYNC，程序连上后即出现两只原生 Joy-Con 2。

切换输出模式：运行 `switch_output_mode.bat`（1=原生 JC2，2=旧 Joy-Con 1）。

## 已知事项

- 程序退出时会杀掉 HmBridge 并清理残留设备节点（`device_cleanup.cleanup_on_exit`）。
- `HmBridge.exe` 需与 `HIDMaestro.Core.dll`、`hidmaestro_profiles\*.json` 同目录（打包已包含）。
- 端口：Python ↔ HmBridge 用 TCP 3250；HIDMaestro 自带 usbip 服务随机端口，不占用 3240/3241/3242（与 Pro2 项目不冲突）。
