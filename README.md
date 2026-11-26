# WinJoyCon2-Plus — 原生 Joy-Con 1 模拟（HIDMaestro 后端）

## 这一版做了什么

把物理 **Joy-Con 2**（BLE）模拟成两只**独立的 Joy-Con 1**，让只认 JC1 的
模拟器/游戏/PC 转译游戏能用。**Joy-Con 1 桥接、鼠标 / 陀螺仪鼠标 / 宏全部保留**。

输出层改用 **HIDMaestro**（纯用户态，自带 usbip 后端），彻底舍弃旧 USB/IP：
- 旧 USB/IP 只支持 SDL2 模拟器
- HIDMaestro 的独立 JoyCon1 profile 让平台自动组合 L/R，**全平台兼容**

## 唯一设备形态

- VID `057E`，PID `2006`(L) / `2007`(R) —— 真机 Joy-Con 1 身份
- HIDMaestro 自带真机 profile `joycon-l.json` / `joycon-r.json`（170 字节真机描述符）
- `0x30`（带 IMU 的完整报告）+ `0x3F`（简单报告）
- 平台自动把左右两只组合成 `Joy-Con (L/R)`，无需手动开关

## 功能（按旧 USB/IP 方案的实现，逐项对齐）

- **按键**：JC2 语义位 → 真机 profile 的错位 HMButton 位表（实测校准 ABXY）
- **摇杆**：JC2 原始 12 位 → 重基准 2048 + 死区 96 + 行程拉伸（与旧方案一致）
- **HD 震动**：HIDMaestro `OutputDecoded.Fields`（leftMotor/rightMotor）→ HD LRA 块 → 真 JC2 GATT 0x0012
- **陀螺仪**：JC2 raw → 语义 g/dps（量纲 16.384 raw/dps + 轴向变换）→ profile 自己填 wire，无中间补丁层
- **C 键**：Switch 2 实机为语音聊天键，PC 无法实现，保留系统级切换设计

## 使用

1. 双击 `WinJoyCon2-Plus.exe`（请求管理员权限——HIDMaestro 建设备必需）。
2. 按手柄 SYNC 连接。平台自动认出两只 Joy-Con 1 并组合。
3. 鼠标/陀螺仪/宏：主页面的三个模式入口。

## 实测（本机）

- SetupAPI：只有 `VID_057E&PID_2006` / `PID_2007` 各一个，状态 OK
- SDL3（Ryujinx Canary）：认出 `Nintendo Switch Joy-Con (L/R)` 自动组合，摇杆与按键有数据
- 推 A → SDL 读到 A（ABXY 位序正确）

## 实现依据

- 按键/摇杆/IMU/震动参数：项目专题笔记（`n-mwkdpulbztyb` / `n-mwkdulhsw1jn` /
  `n-mwkdu8ihidvn` / `n-mwkdv9vu2o2n` / `n-mwg1hfrfrgrb`）
- HIDMaestro SDK：`StateOps.cs` / `VendorBlobCodec.cs` / `HMOutputDecodedEventArgs.cs`
- SDL：`SDL_hidapi_switch.c` `HandleCombinedControllerStateL/R`

## 已知事项

- 退出时杀 HmBridge 并清理设备节点；HmBridge 从 `bridge_runtime/`（不在 PyInstaller
  `_MEI` 临时目录）启动，避免退出时弹 "Failed to remove temporary directory"。
- TCP 3250（Python ↔ 桥接）。
