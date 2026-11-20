# -*- coding: utf-8 -*-
"""端到端：JC2 raw → PadState → 0x3F 报告 → 主机归一化 → 圆度。

验证整条链路，而不只是单点换算。判据来自现成资料：
  * 0x3F 的轴语义 —— JOYCON_REPORT_DESCRIPTOR（hidparse 解析）
  * 主机归一化 —— SDL ApplySimpleStickCalibration / Windows HID gamepad
    （logical 0..65535，中心 0x8000）
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from virtual.reports import JoyConEncoder, PadState  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def host_norm(v16: int) -> float:
    """主机归一化：logical 0..65535，中心 0x8000 → -1..+1。"""
    return (v16 - 0x8000) / 0x8000


# 中心与行程全部从 JoyConEncoder 常量读取，不写死数字
CEN_LX, CEN_LY = JoyConEncoder.STICK_CENTER_XY["L"]
CEN_RX, CEN_RY = JoyConEncoder.STICK_CENTER_XY["R"]
SPAN = JoyConEncoder.STICK_TRAVEL   # 0x3F 的 _stick16 归一化行程


def build(side: str, lx: int, ly: int):
    """构造一帧报告，返回 (X轴归一, Y轴归一)。"""
    enc = JoyConEncoder(side, 12)
    st = PadState()
    st.lx = st.ly = st.rx = st.ry = 2048
    if side == "L":
        st.lx, st.ly = lx, ly
        off = 4
    else:
        st.rx, st.ry = lx, ly
        off = 8
    rep = enc.encode_simple(st)
    return (host_norm(int.from_bytes(rep[off:off + 2], "little")),
            host_norm(int.from_bytes(rep[off + 2:off + 4], "little")))


# --------------------------------------------------------------------------- #
print("=" * 74)
print("1. 静止 → 主机读到精确 0")
print("=" * 74)
for side, (cx, cy) in (("L", (CEN_LX, CEN_LY)), ("R", (CEN_RX, CEN_RY))):
    x, y = build(side, cx, cy)     # 用真实中心作静止点
    check(f"{side} 静止（raw=真实中心）输出 (0,0)",
          abs(x) < 1e-9 and abs(y) < 1e-9, f"({x:.6f},{y:.6f})")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("2. 推到四端点 → 主机读到 ±1（画满外圈）")
print("=" * 74)
cases = [
    ("右", CEN_LX + SPAN, CEN_LY, "x=+1"),
    ("左", CEN_LX - SPAN, CEN_LY, "x=-1"),
    ("上", CEN_LX, CEN_LY + SPAN, "y=+1"),
    ("下", CEN_LX, CEN_LY - SPAN, "y=-1"),
]
for label, lx, ly, expect in cases:
    x, y = build("L", lx, ly)
    val = x if "x=" in expect else y
    target = 1.0 if "+1" in expect else -1.0
    check(f"{label}推到底 → {expect}", abs(val - target) < 0.01, f"{val:+.4f}")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("3. 圆形输入 → 圆形输出（各推杆幅度）")
print("=" * 74)
for frac in (1.0, 0.9, 0.75, 0.5):
    vals = []
    for i in range(72):
        th = 2 * math.pi * i / 72
        lx = int(CEN_LX + math.cos(th) * SPAN * frac)
        ly = int(CEN_LY + math.sin(th) * SPAN * frac)
        x, y = build("L", lx, ly)
        vals.append(math.hypot(x, y))
    err = (max(vals) - min(vals)) / max(vals) * 100
    print(f"  {frac*100:>4.0f}%: 幅值 {min(vals):.4f}..{max(vals):.4f}  圆度误差 {err:.4f}%")
    check(f"{frac*100:.0f}% 推杆为正圆", err < 0.5, f"{err:.4f}%")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("4. 满幅覆盖（raw 到端点时归一 ≥ 0.99）")
print("=" * 74)
x, _ = build("L", CEN_LX + SPAN, CEN_LY)
check("raw=center+travel → 归一 ≥0.99", x >= 0.99, f"{x:.4f}")
x, _ = build("L", CEN_LX - SPAN, CEN_LY)
check("raw=center-travel → 归一 ≤-0.99", x <= -0.99, f"{x:.4f}")
print("  → 这就是「画满虚线外圈」的判据")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("5. 左右独立、互不干扰")
print("=" * 74)
# ⚠ 2026-11-17 轴分配修正：每只 Joy-Con 只有一个摇杆，一律走主摇杆 X/Y。
#   左 encoder 只认 lx/ly，右 encoder 只认 rx/ry，必须分开建。
#   第 3/4 轴（描述符里是 Z / Rx）恒中性，不再承载摇杆。
enc = JoyConEncoder("L", 12)
st = PadState()
# 满幅：中心 + 行程（2026-11-19：行程改 2047，与 SPI 声明一致）
#   enc.stick_center 现在 = (2048,2048)（标准中心）
_cx, _cy = enc.stick_center
st.lx = _cx + SPAN
st.ly = _cy + SPAN
rep = enc.encode_simple(st)
lv = [host_norm(int.from_bytes(rep[o:o + 2], "little")) for o in (4, 6)]
check("左手柄满值（center+travel）", all(v > 0.99 for v in lv), f"{lv}")

encR = JoyConEncoder("R", 12)
stR = PadState()
stR.rx, stR.ry = 0, 0
repR = encR.encode_simple(stR)
# 右手柄也走 X/Y（前两轴 4/6）
rv = [host_norm(int.from_bytes(repR[o:o + 2], "little")) for o in (4, 6)]
check("右手柄满负值（X/Y）", all(v < -0.99 for v in rv), f"{rv}")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("6. 报告结构与描述符一致")
print("=" * 74)
enc = JoyConEncoder("L", 12)
st = PadState()
st.lx = st.ly = st.rx = st.ry = 2048
rep = enc.encode_simple(st)
check("报告长度 12 字节（含 ID）", len(rep) == 12, str(len(rep)))
check("report id = 0x3F", rep[0] == 0x3F, hex(rep[0]))
check("hat 在中性位 (8)", rep[3] == 8, str(rep[3]))
check("4 个轴共 8 字节 = b[4:12]", len(rep[4:12]) == 8)

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
print("=" * 74)
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
    raise SystemExit(1)
print("  全部通过")
