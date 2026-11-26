# WinJoyCon2-Plus v2.0 — 原生 Joy-Con 1 模拟（HIDMaestro 后端）

**WinJoyCon2-Plus，堂堂登场！**

> 把物理 **Joy-Con 2**（BLE）模拟成两只**独立的 Joy-Con 1**，让只认 JC1 的
> 模拟器 / 游戏 / PC 转译游戏能用。Joy-Con 1 桥接、鼠标 / 陀螺仪鼠标 / 宏，
> 一个不少。

*WinJoyCon2-Plus, grandly arriving!*

---

## v2.0，堂堂更新！

*v2.0, grandly updated!*

这一版重构到 HIDMaestro 单一路径，旧 USB/IP 全套推倒重来，一批实机问题
连根拔起。

- **彻底删除旧 USB/IP**：vjoy_out / usbip / bridge / hid_function / descriptors /
  usbip_setup / 安装包，约 4100 行，一并清走。
- **修 IMU 死锁**：profile 的 IMU 块原包在 `when:"imu"` 里，而该状态要主机发
  EnableIMU 才激活 —— SDL 只在「已收到过 IMU 数据」后才发，鸡生蛋，IMU 恒为零。
  改为无条件填充，与真机默认行为一致。
- **修无震动**：`Delegate.CreateDelegate` 签名与
  `Action<HMController,HMOutputPacket>` 不兼容，异常被 `catch` 吞掉，事件从未订阅。
  改用 Expression 构造匹配签名的委托。
- **修回中心失效**：`pynput.mouse.Controller` 没有 `size` 属性，异常被吞，静默失败。
  改用 Qt primaryScreen / Win32 GetSystemMetrics 三级回退。
- **修退出断连重连**：退出时只清 `Unknown` 节点，活跃空壳被跳过，Windows 反复枚举。
  改为按 PID 无条件移除自建设备。
- **连接提速**：去掉 `sleep(1)` + `sleep(6)` 盲等，改端口轮询，约 9 秒压到 2~3 秒。
- **DPI 降一档**：400 / 800 / 1600 / 3200，默认第 2 档。
- **L3/R3 更名 LS/RS**：JoyCon 本来的叫法，旧配置自动迁移。

---

## 核心能力

### 忠实桥接，Joy-Con 2，堂堂桥接！

*Joy-Con 2, grandly bridging!*

- 输出层为 **HIDMaestro**（纯用户态，自带 usbip 后端），彻底舍弃旧 USB/IP。
- VID `057E`，PID `2006`(L) / `2007`(R) —— 真机 Joy-Con 1 身份。
- 自带真机 profile `joycon-l.json` / `joycon-r.json`，170 字节真机描述符。
- `0x30`（带 IMU 的完整报告）+ `0x3F`（简单报告）。
- 平台自动把左右两只组合成 `Joy-Con (L/R)`，无需手动开关。
- SDL2 / SDL3 模拟器、Steam 全部实测可用。

### 光学鼠标，堂堂切换！

*Optical mouse, grandly switching!*

- 光学传感器与陀螺仪（银河手感）双模式，主页面一键切换。
- 4 档 DPI：400 / 800 / 1600 / 3200，默认第 2 档。
- **LS / RS** 一键回屏幕中心，自适应任意分辨率与缩放。

### 银河手感，堂堂模拟！

*Galaxy-style gyro, grandly simulated!*

- JC2 raw → 语义 g/dps（16.384 raw/dps），profile 按 scale / negate 填 wire。
- IMU 三组同值填充 —— 只填一组，灵敏度会掉到三分之一。
- SDL 侧 6 个传感器（ACCEL / GYRO 及 `_L` / `_R` 变体）全部可用。

### 宏指令，堂堂触发！

*Macros, grandly triggered!*

- SL / SR 触发，支持录制与自定义绑定。
- C 键在 Switch 2 实机是语音聊天键，PC 无法实现，保留系统级切换设计。

### HD 震动，堂堂还原！

*HD rumble, grandly restored!*

- HIDMaestro `OutputReceived` 原始 4 字节块 → `jc1_block_to_jc2`。
- SDL 权威振幅表 + 中性判定 + 频率锁 JC2 原生，直送真 JC2 GATT `0x0012`。

### 体验细节，堂堂打磨！

*Details, grandly polished!*

- 按键 / 摇杆 / IMU 参数逐项对齐旧方案，ABXY 实测校准。
- 连接提速、退出清理、链路自愈，一处不落。

---

## 安装与使用

1. 双击 `WinJoyCon2-Plus.exe`（请求管理员权限 —— HIDMaestro 建设备必需）。
2. 按手柄 SYNC，**双手柄，堂堂连接！** 平台自动认出两只 Joy-Con 1 并组合。
3. 鼠标 / 陀螺仪 / 宏，主页面三个模式入口，**杰作，堂堂享用！**

*Both Joy-Con, grandly connecting! A masterpiece, grandly enjoying!*

---

## 从源码构建

源码在 `D:\Games\Nintendo\tool\Joycon2-hidmaestro`，PyInstaller 打包：

```powershell
cd D:\Games\Nintendo\tool\Joycon2-hidmaestro\_src
python -m PyInstaller --noconfirm --clean WinJoyCon2-Plus.spec
```

**源码，堂堂构建！**

*Source code, grandly building!*

---

## 实测（本机）

- SetupAPI：只有 `VID_057E&PID_2006` / `PID_2007` 各一个，状态 OK。
- SDL3（Ryujinx Canary）：认出 `Nintendo Switch Joy-Con (L/R)`，自动组合。
- 直读 `0x30` 报告：IMU 三组一致非零，accel / gyro 六项传感器全部可读。
- 震动链路：SDL `RumbleJoystick` → HD 块喂入 L/R 各数十帧。
- SDL2 / SDL3 模拟器、Steam 均可正常使用。

---

## 已知事项

- **时之笛转译版（Longshot）不支持**：该游戏输入层只接受
  DualSense / DualShock 4 / Switch Pro / Xbox，二进制内无 JoyCon 判定；
  单独 Joy-Con 在 SDL 中是 `JOYCON_LEFT/RIGHT` 类型，不在其支持集合内。
  这是游戏侧限制，该游戏请用 Pro 手柄。
- 退出时杀 HmBridge 并按 PID 移除自建设备节点，避免残留导致断连重连；
  HmBridge 从 `bridge_runtime/`（不在 PyInstaller `_MEI` 临时目录）启动，
  避免退出时弹 "Failed to remove temporary directory"。
- TCP 3250（Python ↔ 桥接）。

---

## 致谢

**先行者，堂堂致谢！** 感谢 HIDMaestro 与 SDL 的逆向先行者，铺好了路。

*Pioneers, grandly thanking!*

**WinJoyCon2-Plus，堂堂开源！**

*WinJoyCon2-Plus, grandly open-sourced!*
