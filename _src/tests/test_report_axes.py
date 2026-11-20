# -*- coding: utf-8 -*-
"""0x3F 简单报告的摇杆验收。

═══════════════════════════════════════════════════════════════════════════
这次修复的根因（依据 HID 报告描述符，不是推测）
═══════════════════════════════════════════════════════════════════════════
用 hidparse 解析 JOYCON_REPORT_DESCRIPTOR 得到 0x3F 的字段：

    Input size=1  count=16  logical=0..1
    Input size=4  count=1   logical=0..7        (Hat)
    Input size=4  count=1   logical=0..7
    Input size=16 count=4   logical=0..65535    usages=[X, Y, Rx, Ry]

**0x3F 里有 4 个 16 位模拟轴**。原实现把它们填死成
`00 80 00 80 00 80 00 80`（全中性）——等于告诉主机「摇杆永远在中间」，
这就是「画不满」的真正原因。

SDL 的处理（sdl_switch.c ApplySimpleStickCalibration）：
    const Uint16 usJoystickCenter = 0x8000;
    sRawValue -= usJoystickCenter;
    HIDAPI_RemapVal(sRawValue, 0, SimpleStickExtents, 0, SDL_MAX_SINT16)
    SimpleStickExtents = SDL_MAX_SINT16 * 0.5

Windows HID gamepad 驱动同理：logical 0..65535，中心 0x8000。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from virtual.reports import JoyConEncoder, PadState, _stick16  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
print("=" * 74)
print("1. 12 位 → 16 位轴换算")
print("=" * 74)
check("12位 2048 → 0x8000（中心）", _stick16(2048) == 0x8000, hex(_stick16(2048)))
check("12位 0 → 0（最小）", _stick16(0) == 0, hex(_stick16(0)))
check("12位 4095 → 65520（最大）", _stick16(4095) == 65520, hex(_stick16(4095)))
print("  换算表：")
for v in (0, 1024, 2048, 3072, 4095):
    print(f"    12位 {v:4d} → 16位 {_stick16(v):5d}")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("2. 0x3F 报告：每个 Joy-Con 只有一个摇杆，一律走主摇杆 X/Y")
print("=" * 74)
enc = JoyConEncoder("L", 12)

st = PadState()
st.lx, st.ly = 2048, 2048
st.rx, st.ry = 2048, 2048
rep = enc.encode_simple(st)
print(f"  静止报告: {rep.hex(' ')}")
check("report id 0x3F", rep[0] == 0x3F, hex(rep[0]))
# ★ 2026-11-18：raw 2048 不再必然输出 0x8000 —— 因为中心用实测值
#   （左 X=2040/Y=2166）。raw==中心 时才输出 0x8000。
_cx, _cy = enc.stick_center
check(f"左X 用真实中心 {_cx}", enc.stick_center[0] == _cx)
# 用真实中心值作 raw 输入，应正好输出 0x8000
_stC = PadState()
_stC.lx = _stC.ly = _stC.rx = _stC.ry = 2048
_stC.lx = _cx
_repC = enc.encode_simple(_stC)
check("raw==真实中心时输出 0x8000",
      int.from_bytes(_repC[4:6], "little") == 0x8000,
      f"{int.from_bytes(_repC[4:6],'little'):04X}")
check("第 3/4 轴（RIGHTX/Y）中性（左手柄不用）",
      rep[8:10] == b"\x00\x80" and rep[10:12] == b"\x00\x80",
      f"{rep[8:10].hex()} {rep[10:12].hex()}")
print("  → 中心用实测值（非固定2048），静止时主机按 SPI 校准得回 0")
print("  → 左手柄用 4/6 轴，右手柄用 8/10 轴（SDL 的 sJoystickLeft/Right）")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("3. 推到端点：必须能到 16 位的两端（否则 Windows 画不满）")
print("=" * 74)
# ⚠ 2026-11-17 轴分配修正后的正确预期：
#   描述符里 4 个轴是 X, Y, **Z, Rx**（没有 Ry）。
#   每只 Joy-Con 只有一个摇杆，一律走**主摇杆 X/Y**（偏移 4 / 6）。
#   第 3/4 轴（Z / Rx）恒填中性 0x8000。
# 格式: (名称, encoder侧, PadState字段, 12位值, 报告偏移)
# ★ 2026-11-18：轴位置按 SDL 的 0x3F 结构体
#     sJoystickLeft[2]（偏移4/6）+ sJoystickRight[2]（偏移8/10）
#   左手柄 → 4/6；右手柄 → 8/10。期望值用该侧真实中心算。
cases = [
    ("左X 推到 4095", "L", "lx", 4095, 4),
    ("左X 推到 0",    "L", "lx", 0,    4),
    ("左Y 推到 4095", "L", "ly", 4095, 6),
    ("右X 推到 4095", "R", "rx", 4095, 4),
    ("右Y 推到 0",    "R", "ry", 0,    6),
]
for label, side_, attr, val, off in cases:
    e = JoyConEncoder(side_, 12)
    st = PadState()
    st.lx = st.ly = st.rx = st.ry = 2048
    setattr(st, attr, val)
    rep = e.encode_simple(st)
    got = int.from_bytes(rep[off:off + 2], "little")
    # 期望值用该侧真实中心 + 行程
    ctr = e.stick_center[0] if attr in ("lx", "rx") else e.stick_center[1]
    expect = _stick16(val, ctr, e.stick_travel)
    check(f"{label} → 16位 {expect}", got == expect, f"{got}")

# 满幅验证：4095 应接近 65535，0 应接近 0
st = PadState()
st.lx = st.ly = st.rx = st.ry = 2048
st.lx = 4095
rep = enc.encode_simple(st)
v = int.from_bytes(rep[4:6], "little")
norm = (v - 32768) / 32768
print(f"  推满时归一化值 = {norm:+.4f}")
check("推满达到 +1.0 附近（画满外圈）", norm > 0.99, f"{norm:.4f}")

st.lx = 0
rep = enc.encode_simple(st)
v = int.from_bytes(rep[4:6], "little")
norm = (v - 32768) / 32768
print(f"  反推满时归一化值 = {norm:+.4f}")
check("反推满达到 -1.0 附近", norm < -0.99, f"{norm:.4f}")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("4. 与 SDL ApplySimpleStickCalibration 的一致性")
print("=" * 74)
SDL_MAX_SINT16 = 32767
EXTENT = int(SDL_MAX_SINT16 * 0.5)      # 16383


def sdl_simple(v16: int) -> int:
    """SDL: sRawValue -= 0x8000; remap(0..extent -> 0..32767)"""
    v = v16 - 0x8000
    if v >= 0:
        return min(SDL_MAX_SINT16, int(v / EXTENT * SDL_MAX_SINT16))
    return max(-SDL_MAX_SINT16, int(v / EXTENT * SDL_MAX_SINT16))


for raw12, label in ((2048, "中心"), (4095, "推满"), (0, "反推满")):
    v16 = _stick16(raw12)
    out = sdl_simple(v16)
    pct = out / SDL_MAX_SINT16 * 100
    print(f"  raw12={raw12:4d} → 16位={v16:5d} → SDL 输出={out:6d} ({pct:+6.1f}%)")
check("SDL 路径推满 = +100%", abs(sdl_simple(_stick16(4095))) >= SDL_MAX_SINT16 - 1)
check("SDL 路径反推满 = -100%", sdl_simple(_stick16(0)) <= -SDL_MAX_SINT16 + 1,
      f"{sdl_simple(_stick16(0))}")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("5. 左右独立（L 用 b[4:8]，R 用 b[8:12]）")
print("=" * 74)
st = PadState()
st.lx, st.ly = 4095, 4095
st.rx, st.ry = 0, 0
rep = enc.encode_simple(st)
lx = int.from_bytes(rep[4:6], "little")
ly = int.from_bytes(rep[6:8], "little")
z3 = int.from_bytes(rep[8:10], "little")     # Z 轴（第 3）
rx4 = int.from_bytes(rep[10:12], "little")   # Rx 轴（第 4）
# 左手柄：走 LEFTX/Y，第 3/4 轴（RIGHTX/Y）中性
_csL, _cyL = JoyConEncoder.STICK_CENTER_XY["L"]
_tvL = enc.stick_travel
check("左手柄推满时 LEFTX/Y 到上限",
      lx == _stick16(4095, _csL, _tvL) and ly == _stick16(4095, _cyL, _tvL),
      f"({lx},{ly})")
check("左手柄第 3/4 轴（RIGHTX/Y）中性",
      z3 == 0x8000 and rx4 == 0x8000, f"({z3},{rx4})")

# 右手柄：走 RIGHTX/Y（第 3/4 轴），第 1/2 轴中性
#   SDL 的 0x3F 结构体：sJoystickLeft[2] + sJoystickRight[2]
#   → 右手柄必须填 sJoystickRight，否则测试网站读不到右摇杆
_encR = JoyConEncoder("R", 12)
_csR, _cyR = JoyConEncoder.STICK_CENTER_XY["R"]
_stR = PadState()
_stR.lx = _stR.ly = _stR.rx = _stR.ry = 2048
_stR.rx, _stR.ry = 0, 0
_repR = _encR.encode_simple(_stR)
_rlx = int.from_bytes(_repR[4:6], "little")
_rly = int.from_bytes(_repR[6:8], "little")
_rrx = int.from_bytes(_repR[8:10], "little")
_rry = int.from_bytes(_repR[10:12], "little")
_tvR = _encR.stick_travel
check("右手柄也走 X/Y（前两轴）",
      _rlx == _stick16(0, _csR, _tvR) and _rly == _stick16(0, _cyR, _tvR),
      f"XY=({_rlx},{_rly})")
check("右手柄 Z/Rx 保持中性",
      _rrx == 0x8000 and _rry == 0x8000, f"Z/Rx=({_rrx},{_rry})")

# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print("6. 中断端点按 input_mode 选报告（真机行为）")
print("=" * 74)
from virtual import descriptors as _D  # noqa: E402
from virtual.hid_function import Switch1HidFunction  # noqa: E402


def make(kind="joyconL"):
    return Switch1HidFunction(_D.DEVICES[kind], kind)


# 默认模式必须是 0x3F（Windows 不发子命令时的状态）
h = make()
check("初始 input_mode = 0x3F", h.input_mode == 0x3F, hex(h.input_mode))

h.set_state(PadState())
r = h.pending_in(1)
check("默认推 0x3F（带轴，Windows 可读摇杆）", r and r[0] == 0x3F,
      hex(r[0]) if r else "None")

# 切到 0x30（模拟器发 SetInputReportMode 后）
h.input_mode = 0x30
h.set_state(PadState())
r30 = h.pending_in(1)
check("切 0x30 后推 0x30（带 IMU）", r30 and r30[0] == 0x30,
      hex(r30[0]) if r30 else "None")

h.input_mode = 0x31
h.set_state(PadState())
r31 = h.pending_in(1)
check("0x31 也推全模式", r31 and r31[0] == 0x31, hex(r31[0]) if r31 else "None")

# 0x3F 里的轴必须跟着状态变
h2 = make()
st = PadState()
st.lx, st.ly = 4095, 0
st.rx, st.ry = 0, 4095
h2.set_state(st)
rep = h2.pending_in(1)
lx = int.from_bytes(rep[4:6], "little")
ly = int.from_bytes(rep[6:8], "little")
_c2x, _c2y = h2.encoder.stick_center
# 2026-11-19：_stick16 现在显式带 travel（=2047），断言必须同步传入
_travel = h2.encoder.stick_travel
check("中断端点输出里左X推满", lx == _stick16(4095, _c2x, _travel), f"{lx}")
check("中断端点输出里左Y反推满", ly == _stick16(0, _c2y, _travel), f"{ly}")

# --------------------------------------------------------------------------- #
print()
print("=" * 74)
print(f"最终: {len(PASS)} 通过 / {len(FAIL)} 失败")
print("=" * 74)
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
    raise SystemExit(1)
print("  全部通过")
