# -*- coding: utf-8 -*-
"""摇杆输出层契约 —— 重基准 / 死区 / 行程拉伸 / 边界保护。

★ 设计原则（2026-11-19 重构）：
  **不写死任何魔法数字**，全部从源码常量读取；断言只描述行为契约。
  这样换硬件参数（中心/行程/死区）时，本测试无需修改。

契约：
  1. 物理中心 -> 标准中心（报告中心 == SPI 声明中心）
  2. 死区内 -> 精确中心
  3. 死区外 -> 单调放大，推满饱和到 0/4095
  4. 越界输入被夹到 0..4095，不产生负数/溢出
  5. 左右两路互不干扰
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from virtual.vjoy_out import VirtualJoyCon1  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


v = VirtualJoyCon1("both")

STD = v._STD_CENTER
DZ = v.STICK_DEADBAND
PHYS = v._PHYS_CENTER
LO, HI = 0, 4095

print("=" * 70)
print(f"源码参数: 标准中心={STD} 死区={DZ} 物理中心={PHYS} 行程基准={v._PHYS_TRAVEL}")
print("=" * 70)

print()
print("1. 物理中心 -> 标准中心")
for side, key in (("left", "L"), ("right", "R")):
    px, py = PHYS[key]
    v.set_stick(side, px, py)
    got = v._stick_l if side == "left" else v._stick_r
    check(f"  {side} 物理中心{PHYS[key]} -> ({STD},{STD})",
          got == (STD, STD), str(got))

print()
print("2. 死区内 -> 精确中心")
for side, key in (("left", "L"), ("right", "R")):
    px, py = PHYS[key]
    for d in (DZ // 2, DZ):
        v.set_stick(side, px + d, py - d)
        got = v._stick_l if side == "left" else v._stick_r
        check(f"  {side} 偏移±{d} -> 中心", got == (STD, STD), str(got))

print()
print("3. 死区外单调放大 + 推满饱和")
px, py = PHYS["L"]
seq = []
for d in (DZ + 100, DZ + 400, DZ + 800, 1500):
    v.set_stick("left", px + d, py)
    seq.append(v._stick_l[0])
check("  单调递增", all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)), str(seq))
check("  推满饱和到上界", seq[-1] == HI, str(seq[-1]))
v.set_stick("left", px - 1500, py)
check("  反向推满饱和到下界", v._stick_l[0] == LO, str(v._stick_l[0]))

print()
print("4. 越界输入被夹到 0..4095")
v.set_stick("left", -99999, 99999)
check("  极值输入夹到 (0,4095)", v._stick_l == (LO, HI), str(v._stick_l))

print()
print("5. 左右互不干扰")
v.set_stick("left", PHYS["L"][0] + 1500, PHYS["L"][1])
v.set_stick("right", PHYS["R"][0] - 1500, PHYS["R"][1])
lv, rv = v._stick_l, v._stick_r
check("  左推右不受影响（左到上界）", lv[0] == HI, str(lv))
check("  右推左不受影响（右到下界）", rv[0] == LO, str(rv))

print()
print("=" * 70)
print("源码守卫")
print("=" * 70)
src = (SRC / "virtual" / "vjoy_out.py").read_text(encoding="utf-8")
check("_push 用 set_stick 缓存的 _stick_l/_stick_r", "_stick_l" in src)
check("有重基准（_PHYS_CENTER）", "_PHYS_CENTER" in src)
check("有行程拉伸（_PHYS_TRAVEL）", "_PHYS_TRAVEL" in src)

print()
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("全部通过")
