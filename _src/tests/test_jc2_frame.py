# -*- coding: utf-8 -*-
"""jc2_frame 解析验收 —— 用真机帧做基准。

每个断言都对应一条**实测数据**，不是推导出来的。
真机帧来自 2026-11-17 12:56:35 的抓包（静止状态）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from virtual.jc2_frame import (  # noqa: E402
    parse_frame, unpack_stick12, stick_for_side,
    STICK_CENTER, MIN_LEN, OFF_STICK_L, OFF_STICK_R,
)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


# ── 真机帧（原样，来自日志）─────────────────────────────────────────────────
LEFT_FRAME = bytes.fromhex(
    "9b 26 00 00 00 00 00 e0 ff 0f fc 97 87 ff f7 7f "
    "00 00 00 00 ff 11 0b 0c 00 6d fd d0 fe 77 01 4e")
RIGHT_FRAME = bytes.fromhex(
    "df 29 00 00 00 00 00 e0 ff 0f ff f7 7f bd 27 7c "
    "00 00 00 00 ff 11 07 0c 00 66 fd 20 01 f2 fd 61")

print("=" * 78)
print("A. 12 位解包（用真机字节验证）")
print("=" * 78)

# Left 帧 [10:13] = fc 97 87
x, y = unpack_stick12(0xFC, 0x97, 0x87)
check("Left [10:13] → (2044, 2169)", (x, y) == (2044, 2169), f"({x},{y})")

# Right 帧 [13:16] = bd 27 7c
x, y = unpack_stick12(0xBD, 0x27, 0x7C)
check("Right [13:16] → (1981, 1986)", (x, y) == (1981, 1986), f"({x},{y})")

# 中心值：ff f7 7f → (2047, 2047)
x, y = unpack_stick12(0xFF, 0xF7, 0x7F)
check("中心 fff77f → (2047, 2047)", (x, y) == (2047, 2047), f"({x},{y})")

# 边界
check("全 0 → (0,0)", unpack_stick12(0, 0, 0) == (0, 0))
check("全 ff → (4095,4095)", unpack_stick12(0xFF, 0xFF, 0xFF) == (4095, 4095),
      str(unpack_stick12(0xFF, 0xFF, 0xFF)))

print()
print("=" * 78)
print("B. 整帧解析")
print("=" * 78)

fr = parse_frame(LEFT_FRAME)
check("左帧 valid", fr.valid)
check("左帧 seq=0x269b", fr.seq == 0x269B, hex(fr.seq))
check("左帧 lx/ly 正确", (fr.lx, fr.ly) == (2044, 2169), f"({fr.lx},{fr.ly})")
check("左帧 rx/ry = 占位中心", (fr.rx, fr.ry) == (2047, 2047), f"({fr.rx},{fr.ry})")

fr2 = parse_frame(RIGHT_FRAME)
check("右帧 seq=0x29df", fr2.seq == 0x29DF, hex(fr2.seq))
check("右帧 rx/ry 正确", (fr2.rx, fr2.ry) == (1981, 1986), f"({fr2.rx},{fr2.ry})")
check("右帧 lx/ly = 占位中心", (fr2.lx, fr2.ly) == (2047, 2047), f"({fr2.lx},{fr2.ly})")

print()
print("=" * 78)
print("C. ★ 按侧取摇杆（核心修复点）")
print("=" * 78)

# 这是最容易搞错的地方：单只 Joy-Con 帧里两个字段都在，
# 必须按侧挑自己的，不能"左帧读A、右帧读B"。
check("左手柄取到 (2044,2169)", stick_for_side(fr, "left") == (2044, 2169))
check("左手柄取 rx/ry 会是错的值",
      stick_for_side(fr, "left") != stick_for_side(fr, "right"),
      f"L={stick_for_side(fr,'left')} R={stick_for_side(fr,'right')}")

check("右手柄取到 (1981,1986)", stick_for_side(fr2, "right") == (1981, 1986))
check("右手柄取 lx/ly 会是错的值",
      stick_for_side(fr2, "right") != stick_for_side(fr2, "left"))

print()
print("=" * 78)
print("D. 无效帧与边界")
print("=" * 78)

check("None → invalid", not parse_frame(None).valid)
check("空 bytes → invalid", not parse_frame(b"").valid)
check(f"短于 {MIN_LEN} 字节 → invalid",
      not parse_frame(bytes(MIN_LEN - 1)).valid)
check(f"{MIN_LEN} 字节 → valid", parse_frame(bytes(MIN_LEN)).valid)

# IMU 只在够长时取
short = parse_frame(bytes(MIN_LEN))
check("短帧 IMU 保持默认（az=4096）", short.az == 4096, str(short.az))
# IMU 需要 >= 0x3C(60) 字节才取
# ⚠ 真机有效载荷是 63 字节，但历史抓包只存了前 32 字节，
#   所以这里用构造帧验证解析路径本身正确。
full = bytearray(63)
full[0:16] = LEFT_FRAME[0:16]
# 在 0x30 处放 accel=(100, 200, 4000) gyro=(0,0,0)
for i, v in enumerate((100, 200, 4000, 0, 0, 0)):
    full[0x30 + i*2] = v & 0xFF
    full[0x30 + i*2 + 1] = (v >> 8) & 0xFF
long_fr = parse_frame(bytes(full))
check("60+ 字节帧 IMU 已解析", long_fr.valid and long_fr.az == 4000, str(long_fr.az))
check("accel x/y 正确", (long_fr.ax, long_fr.ay) == (100, 200),
      f"({long_fr.ax},{long_fr.ay})")

print()
print("=" * 78)
print("E. 偏移常量自检（防止有人改错）")
print("=" * 78)

check("左摇杆偏移 = 10", OFF_STICK_L == 10)
check("右摇杆偏移 = 13", OFF_STICK_R == 13)
# 两个字段必须错开，且都在有效范围内
check("两摇杆字段不重叠", OFF_STICK_R >= OFF_STICK_L + 3,
      f"L={OFF_STICK_L} R={OFF_STICK_R}")
check("最大偏移不越界", OFF_STICK_R + 3 <= MIN_LEN,
      f"{OFF_STICK_R + 3} <= {MIN_LEN}")

print()
print("=" * 78)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    print("=" * 78)
    sys.exit(1)
print("全部通过")
print("=" * 78)
