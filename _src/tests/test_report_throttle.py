# -*- coding: utf-8 -*-
"""所有报告模式都必须按 15ms 节流 —— 防测试网站 10000Hz 空转。

═══════════════════════════════════════════════════════════════════════════
真实 bug（2026-11-18）
═══════════════════════════════════════════════════════════════════════════
现象：测试网站测回报率显示 10000Hz、抖动 0.29ms、掉包 0%，
      动不动手柄都没变化（一直空转返回同一份状态）。

根因：pending_in 的节流被 `has_imu` 条件限制，只在 0x30 模式生效。
      测试网站用 WebHID 读 0x3F（简单报告，无 IMU）→ 完全不节流
      → 主机无阻塞高速拉取（实测 99999Hz）。

修法：节流对所有模式生效（0x30 和 0x3F 都按 15ms = 66Hz），与 JC1 真机一致。

═══════════════════════════════════════════════════════════════════════════
2026-11-19 语义更新：缓存报告路径
═══════════════════════════════════════════════════════════════════════════
`pending_in` 现在采用**缓存报告**策略（见 vjoy_out / 震动专题笔记）：
主机轮询快于报告节拍时，直接返回上一份缓存帧，不再 sleep 也不挂起。

因此衡量口径必须从「调用返回率」改为「**内容更新率**」：
  · 调用可以每次都返回（缓存帧），这是设计使然
  · 但**新内容**只在 `_last_send` 推进时产生 → 这才是节流的真实语义
  · `_last_send` 的推进速率必须 ≈ 66Hz，否则就是空转

判据：
  1. 0x3F / 0x30 两种模式的**内容更新率**都在 40~90Hz
  2. `_last_send` 的推进间隔约 15ms
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from virtual import descriptors as D  # noqa: E402
from virtual.hid_function import Switch1HidFunction, DEFAULT_PERIOD_MS  # noqa: E402
from virtual.reports import PadState  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


print("=" * 70)
print("周期参数")
print("=" * 70)
check("DEFAULT_PERIOD_MS = 15ms（JC1 原生）",
      abs(DEFAULT_PERIOD_MS - 15.0) < 0.01, f"{DEFAULT_PERIOD_MS}ms")

print()
print("=" * 70)
print("所有报告模式都节流（防 10000Hz 空转）—— 按内容更新率衡量")
print("=" * 70)
DURATION = 0.60      # 采样窗口（秒）
for mode in (0x3F, 0x30):
    h = Switch1HidFunction(D.DEVICES["joyconL"], "joyconL")
    h.input_mode = mode
    h.set_state(PadState())
    h.pending_in(1)   # 建立基线

    # 统计 _last_send 的推进次数 = 真正产生新内容的次数
    updates = 0
    n = 0
    t0 = time.monotonic()
    prev = h._last_send
    while time.monotonic() - t0 < DURATION:
        h.pending_in(1)
        n += 1
        if h._last_send != prev:
            updates += 1
            prev = h._last_send
    dt = time.monotonic() - t0
    hz = updates / dt if dt > 0 else 0
    check(f"0x{mode:02X} 内容更新率 40~90Hz（非 10000Hz）",
          40 <= hz <= 90, f"{hz:.0f}Hz（调用 {n} 次）")

print()
print("=" * 70)
print("缓存路径：调用可以高频返回，但内容不跟着高频更新")
print("=" * 70)
h = Switch1HidFunction(D.DEVICES["joyconL"], "joyconL")
h.input_mode = 0x30
h.set_state(PadState())
h.pending_in(1)
n_call, prev, updates = 0, h._last_send, 0
t0 = time.monotonic()
while time.monotonic() - t0 < 0.30:
    h.pending_in(1)
    n_call += 1
    if h._last_send != prev:
        updates += 1
        prev = h._last_send
check("30ms 内调用次数远多于内容更新次数",
      n_call > updates * 1.5, f"调用{n_call}次 / 更新{updates}次")

print()
print("=" * 70)
print("源码守卫")
print("=" * 70)
hf = (SRC / "virtual" / "hid_function.py").read_text(encoding="utf-8")
check("节流不依赖 has_imu",
      "if wait > 0" in hf and "if wait > 0 and has_imu" not in hf)
check("缓存帧 + 模拟器兼容热切换",
      "get_imu_compat_mode" in hf and "cached" in hf)
check("注释记录 10000Hz bug", "10000Hz" in hf)

print()
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("全部通过")
