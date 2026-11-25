# WinJoyCon2-Plus v1.5 — 原生 Joy-Con 2 / 充电握把双模式（HIDMaestro）

## 这一版做了什么

从 **v1.2.0** 基线重做 JC2 输出层，**JoyCon1 桥接与鼠标/陀螺仪/宏原样保留**。
用 HIDMaestro 提供两种设备形态，运行时切换。

## 两种模式

| output_mode | 设备形态 | SDL 里的表现 | 适用场景 |
|---|---|---|---|
| `hidmaestro`/`jc2` | 原生 Joy-Con 2，`057E:2067`(L)/`2066`(R)，100 字节真机描述符，0x05/0x07/0x08 报告 | 认出真 JC2 身份；但按资料 `n-mwud4kmjni71` 第七节，SDL 的 switch2 驱动要 libusb 第二接口（虚拟设备不可达），**组合/陀螺仪/HD 震动在 SDL 系不可用** | 需要真 JC2 身份的场合 |
| `grip` | 充电握把 `057E:200E`，真机原版 profile `joycon-l-usb`/`joycon-r-usb` | SDL 里组合/分开都正常，**全部按键 + 双摇杆 + 陀螺仪 + HD 震动可用**；组合由 SDL「组合手柄」开关决定 | 模拟器 / PC 转译游戏（主场景） |
| `joycon1` | 虚拟 Joy-Con 1（旧 USB/IP 路径） | Ryujinx/Eden 老版本 | 旧场景 |

用 `switch_output_mode.bat` 切换（1=jc2 / 2=grip / 3=joycon1）。

## v1.5 修复的三个实质 bug（依据 SDL 官方源码 + HIDMaestro SDK 静态推导）

1. **按键位序**：真机握把 profile 的 stateBlock 用 `"#n"` 把 HMButton 位搬到
   0x30 报告特定位，SDL `HandleCombinedControllerStateL/R` 又按自己的位置名读，
   两者合成的是"故意错位"的映射（MINUS 要给 `1<<8`、HOME 给 `1<<12`、
   L1/R1 给 `1<<14`、R 半 A/B/X/Y 给 `1<<3/1/2/0`…）。v1.4 用直觉语义位，
   所以只有碰巧对位的键能用。已按推导表改正。
2. **方向键整帧报废**：DPAD_* 是 32 位以外的 sentinel（`1<<34..37`），桥接用
   `uint.Parse` 解析 → OverflowException → 整帧 STATE 失败，连带摇杆/IMU 全丢。
   已扩展桥接协议：STATE 增加第 7 参数 hat 角度，桥接写 `HMGamepadState.HatDegrees`
   （VendorBlobCodec.cs:1112-1137），方向键走 hat，不再进按钮掩码。ZL/ZR 的
   `1<<32/33` 同样移除，只给 `1<<15` 走模拟满拉。
3. **HD 震动**：`HMOutputDecodedEventArgs` 没有 `LeftMotor`/`RightMotor` 字段，
   震动幅度在它的 `Fields` 字典里（key=`leftMotor`/`rightMotor`，来源 grip profile
   的 `protocol.decoders.rumble`）。v1.4 的 HookOutput 找不存在的字段 → 事件没挂上。
   已改为从 `Fields` 字典读，并保留 RawBytes 兜底。

## 资料依据（全部在 sessions 与笔记，未瞎猜）

- `n-mwud4kmjni71`《Switch2 手柄 USB HID 协议资料汇编》：0x05/0x07/0x08 逐字节位表
- `n-mwu8qauyp1v5`《原生 JC2 实现记录》：SDL 驱动不可达的根因与实测
- `ref/sdl32/SDL_hidapi_switch.c` `HandleCombinedControllerStateL/R`（2306/2351）
- `ref/sdl32/SDL_hidapi_switch2.c` `InitUSB`（380-403，需 libusb）
- `ref/hidmaestro/.../joycon-l-usb.json` / `joycon-r-usb.json`（真机抓包原版）
- HIDMaestro SDK `StateOps.cs` / `VendorBlobCodec.cs` / `HMOutputDecodedEventArgs.cs`

## 使用

1. `switch_output_mode.bat` 选模式（主场景选手柄握把 = 2）。
2. 双击 `WinJoyCon2-Plus.exe`（请求管理员权限，HIDMaestro 建设备必需）。
3. grip 模式下在 Steam 按需开/关「组合手柄」：开→一只 Joy-Con (L/R)，关→两只独立。
4. C 键：Switch 2 实机为语音聊天键，PC 无法实现，保留系统级切换设计。

## 已知事项

- 退出时杀 HmBridge 并清理设备节点；桥接需与 `HIDMaestro.Core.dll`、
  `hidmaestro_profiles/*.json` 同目录（打包已含）。
- TCP 3250（Python↔桥接）；HIDMaestro usbip 用随机端口，不占 3240/3241/3242。
