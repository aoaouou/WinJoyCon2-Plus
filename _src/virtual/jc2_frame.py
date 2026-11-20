# -*- coding: utf-8 -*-
"""Joy-Con 2 的 BLE 帧解析 —— **唯一**的数据入口。

═══════════════════════════════════════════════════════════════════════════
为什么重写这一层
═══════════════════════════════════════════════════════════════════════════
旧代码有**两条互不相干的解析路径**：

  ① `virtual/reports.py` 的 `parse_report()` / `_apply_unified()`（781 行）
     —— 实测**零外部引用**，纯死代码
  ② `controllers/JoyconL.py` / `JoyconR.py` 的 `update()`
     —— 实际在用的那条

两条路径各自维护一套字段偏移，而且互相矛盾。这是「改了半天没效果」的
直接原因：我在改 ①，运行时跑的是 ②（或反过来）。

本文件是**唯一入口**。所有字段偏移只在这里定义一次。

═══════════════════════════════════════════════════════════════════════════
字段偏移的依据（真机帧实测，不是查文档猜的）
═══════════════════════════════════════════════════════════════════════════
实抓 63 字节有效载荷（12:56:35，静止状态）：

    Left : 9b 26 00 00 00 00 00 e0 ff 0f fc 97 87 ff f7 7f ...
    Right: df 29 00 00 00 00 00 e0 ff 0f ff f7 7f bd 27 7c ...

变化字节分布（多帧比对）：

    [0][1]      消息计数器（递增）
    [4..7]      恒为 00 —— **固定填充，不是摇杆**
    [8][9]      恒为 e0 ff
    [10:13]     Left 的摇杆：静止 (2044, 2169)，稳定
    [13:16]     Right 的摇杆：静止 (1981, 1986)，稳定
    [20..]      IMU 等

⚠ 踩过的坑（务必别再改）：
  · `s2r_bluetooth_interface.md` 写 BLE 摇杆在 `0x5` —— **错的**，
    [5] 恒为 0。实测 `datas[5:8]` 给 (0, 3584)，是固定填充。
  · `s2r_hid_reports.md` 写 `0xA`/`0xD`，对 Left 有效但 Right 是 `0xD`；
    而单只 Joy-Con 的帧里两个字段**都会出现**（另一侧是占位）。

═══════════════════════════════════════════════════════════════════════════
打包格式（12 位摇杆）
═══════════════════════════════════════════════════════════════════════════
    3 字节装 2 个 12 位值：
        x = b0 | ((b1 & 0x0F) << 8)
        y = (b1 >> 4) | (b2 << 4)

    验证：Left 静止帧 `fc 97 87`
        x = 0xFC | ((0x97 & 0x0F) << 8) = 0xFC | 0x700 = 0x7FC = 2044 ✓
        y = (0x97 >> 4) | (0x87 << 4)   = 0x9 | 0x870 = 0x879 = 2169 ✓
"""
from __future__ import annotations

from dataclasses import dataclass

# ── 字段偏移（唯一真源）────────────────────────────────────────────────────
OFF_COUNTER = 0          # 2 字节计数器
OFF_BUTTONS = 4          # 按钮位（见 BUTTONS_*）
OFF_STICK_L = 10         # 左摇杆 3 字节
OFF_STICK_R = 13         # 右摇杆 3 字节
# IMU 起（accel xyz + gyro xyz，6×int16 小端，共 12 字节）
#
# ⚠ 这个偏移**尚未用真机数据确认**。
#   原因：以前抓的 CAP/ODD 帧为了省日志只打了前 32 字节，
#   而 IMU 需要到 32 之后才完整，所以拿不到真值来对齐。
#
#   现有 IMU 通路（controllers/JoyconL.py 的 datas[0x30:0x3C]）是
#   之前验证过能工作的，本文件暂时保留同一位置，**不做改动**。
#   要重新确认需抓完整 63 字节帧 —— 已在 docs 里留待办。
OFF_IMU = 0x30           # 与 JoyconL 现有实现一致（48）
MIN_LEN = 16             # 少于这个长度视为无效帧
IMU_MIN_LEN = 0x3C + 12  # 0x3C=60，加 12 字节 IMU = 72？实际取 len>=0x3C

# 真机有效载荷是 63 字节；IMU 在 0x30..0x3C（48..60）
IMU_MIN_LEN = 0x3C       # 60

STICK_CENTER = 2048
STICK_MAX = 4095


@dataclass
class Frame:
    """一帧解析结果 —— 只装数据，不带任何业务逻辑。"""
    seq: int = 0
    buttons: int = 0             # 原始位域
    lx: int = STICK_CENTER
    ly: int = STICK_CENTER
    rx: int = STICK_CENTER
    ry: int = STICK_CENTER
    # IMU：原始 int16 报告值（未做任何轴向变换，变换在上层做）
    ax: int = 0
    ay: int = 0
    az: int = 4096
    gx: int = 0
    gy: int = 0
    gz: int = 0
    valid: bool = False


def unpack_stick12(b0: int, b1: int, b2: int) -> tuple:
    """3 字节 → (x, y)，各 12 位。"""
    x = b0 | ((b1 & 0x0F) << 8)
    y = (b1 >> 4) | (b2 << 4)
    return x, y


def _i16(data: bytes, off: int) -> int:
    """小端 int16，越界返回 0。"""
    if off + 2 > len(data):
        return 0
    v = data[off] | (data[off + 1] << 8)
    return v - 0x10000 if v >= 0x8000 else v


def parse_frame(data: bytes) -> Frame:
    """解析一帧 BLE 通知。无效返回 valid=False 的 Frame。

    **不做任何轴向变换、不做任何校准、不做任何滤波。**
    这一层只负责「字节 → 数字」，其余全部交给上层。
    """
    st = Frame()
    if data is None or len(data) < MIN_LEN:
        return st

    st.valid = True
    st.seq = data[OFF_COUNTER] | (data[OFF_COUNTER + 1] << 8)
    st.buttons = (data[OFF_BUTTONS] | (data[OFF_BUTTONS + 1] << 8)
                  | (data[OFF_BUTTONS + 2] << 16) | (data[OFF_BUTTONS + 3] << 24))

    lx, ly = unpack_stick12(data[OFF_STICK_L], data[OFF_STICK_L + 1],
                            data[OFF_STICK_L + 2])
    rx, ry = unpack_stick12(data[OFF_STICK_R], data[OFF_STICK_R + 1],
                            data[OFF_STICK_R + 2])
    st.lx, st.ly, st.rx, st.ry = lx, ly, rx, ry

    if len(data) >= IMU_MIN_LEN:
        o = OFF_IMU
        st.ax, st.ay, st.az = _i16(data, o), _i16(data, o + 2), _i16(data, o + 4)
        st.gx, st.gy, st.gz = _i16(data, o + 6), _i16(data, o + 8), _i16(data, o + 10)

    return st


def stick_for_side(fr: Frame, side: str) -> tuple:
    """按手柄侧取它自己的摇杆。

    ⚠ 关键：单只 Joy-Con 的帧里**两个字段都出现**，另一侧是占位。
    所以必须按侧挑，不能“左帧读 A、右帧读 B”。

    依据（静止帧实测）：
        Left  帧：[10:13]=(2044,2169)  [13:16]=(2047,2047)
        Right 帧：[10:13]=(2047,2047)  [13:16]=(1981,1986)
    每侧只有自己那个字段偏离中心，另一个恒为 2047。
    """
    return (fr.lx, fr.ly) if side == "left" else (fr.rx, fr.ry)
