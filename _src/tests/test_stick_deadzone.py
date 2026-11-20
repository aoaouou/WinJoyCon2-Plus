# -*- coding: utf-8 -*-
"""摇杆死区 + 行程拉伸 —— 行为契约测试。

★ 设计原则（2026-11-19 重构）：
  **不写死任何魔法数字。** 中心/死区/行程全部从源码常量读取，
  断言只描述"行为"（回中归零、推满饱和、死区连续），
  这样调整硬件参数时测试不需要跟着改。

契约：
  1. 物理回中（含死区内的抖动）→ 输出精确标准中心
  2. 任意方向推满 → 输出饱和到 0 / 4095 边界
  3. 死区边界两侧不跳变（输出连续）
  4. 死区内单调归中、死区外单调增
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

# ── 全部从源码读取，不抄数字 ──────────────────────────────
STD = v._STD_CENTER
DZ = v.STICK_DEADBAND
PHYS = v._PHYS_CENTER
LO, HI = 0, 4095

print("=" * 70)
print(f"源码参数: 标准中心={STD} 死区={DZ} 物理中心={PHYS}")
print("=" * 70)

print()
print("1. 物理回中（含死区内抖动）必须精确归中")
for side in ("left", "right"):
    px, py = PHYS["L" if side == "left" else "R"]
    for d in (0, DZ // 4, DZ // 2, DZ):
        v.set_stick(side, px + d, py - d)
        got = v._stick_l if side == "left" else v._stick_r
        check(f"  {side} 偏移±{d} -> 精确中心", got == (STD, STD), str(got))

print()
print("2. 任意方向推满必须饱和到边界")
# 用足够大的物理偏移（真实手柄行程约 1000 LSB），保证任何方向都能顶满
BIG = 1500
for side in ("left", "right"):
    px, py = PHYS["L" if side == "left" else "R"]
    for name, dx, dy, exp in (
        ("右", BIG, 0, (HI, STD)),
        ("左", -BIG, 0, (LO, STD)),
        ("下", 0, BIG, (STD, HI)),
        ("上", 0, -BIG, (STD, LO)),
    ):
        v.set_stick(side, px + dx, py + dy)
        got = v._stick_l if side == "left" else v._stick_r
        check(f"  {side} 推满{name} -> {exp}", got == exp, str(got))

print()
print("3. 死区边界连续（不跳变）")
px, py = PHYS["L"]
prev = None
max_jump = 0
for d in range(DZ - 5, DZ + 40, 5):
    v.set_stick("left", px + d, py)
    got = v._stick_l[0]
    if prev is not None:
        max_jump = max(max_jump, abs(got - prev))
    prev = got
check("  死区边界无 >200 的突跳", max_jump <= 200, f"最大跳变={max_jump}")

print()
print("4. 单调性：死区内恒为中心，死区外单调递增")
px, py = PHYS["L"]
vals = []
for d in (0, DZ, DZ + 50, DZ + 200, DZ + 500, 1200):
    v.set_stick("left", px + d, py)
    vals.append(v._stick_l[0])
mono = all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
check("  输出随偏移单调递增", mono, str(vals))
check("  死区内 = 中心", vals[0] == STD and vals[1] == STD, str(vals[:2]))
check("  死区外 > 中心", vals[2] > STD, str(vals[2]))

print()
print("=" * 70)
print("源码守卫")
print("=" * 70)
src = (SRC / "virtual" / "vjoy_out.py").read_text(encoding="utf-8")
check("set_stick 有重基准逻辑", "_PHYS_CENTER" in src and "_STD_CENTER" in src)
check("set_stick 有行程拉伸", "_PHYS_TRAVEL" in src)
check("死区常量存在", "STICK_DEADBAND" in src)

print()
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("全部通过")
