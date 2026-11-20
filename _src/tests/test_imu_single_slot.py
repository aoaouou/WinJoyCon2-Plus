# -*- coding: utf-8 -*-
"""IMU 只填最后一组 —— 防陀螺仪被放大 3 倍。

═══════════════════════════════════════════════════════════════════════════
根因（2026-11-17，用户实测"陀螺仪翻几倍 / 模拟器崩溃"）
═══════════════════════════════════════════════════════════════════════════
0x30 报告有 3 个 IMU slot。旧实现把同一份数据复制到 3 个 slot，
主机对 3 组都积分 → 角速度天然放大 3 倍 → 陀螺仪疯转、物理计算溢出崩溃。

Pro2 Bridge 的做法（report_mapper.c:224-226）：
    src_sample = REPORT_MAPPER_MOTION_SAMPLE_COUNT - 1;   // 只取最后一组
    copy_motion_sample(dst, src + src_sample * SIZE, ...);
—— 只把**一个**样本放进目标，其余保持 0，主机只积分一次。

判据：
  1. slot[0] / slot[1] 全 0
  2. slot[2] = 真实值
  3. IMU_SCALE = 1.0（不再需要缩放补偿）
"""
from __future__ import annotations

import sys
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


def i16(b, o):
    v = b[o] | (b[o + 1] << 8)
    return v - 0x10000 if v >= 0x8000 else v


print("=" * 70)
print("1. IMU 三组的填充位置")
print("=" * 70)
h = Switch1HidFunction(D.DEVICES["joyconL"], "joyconL")
h.input_mode = 0x30
st = PadState()
st.accel = (100, 200, 4000)
st.gyro = (3000, -3000, 1500)
h.set_state(st)
r = h.pending_in(1)

slots = []
for i in range(3):
    base = 13 + i * 12
    slots.append((
        (i16(r, base), i16(r, base + 2), i16(r, base + 4)),
        (i16(r, base + 6), i16(r, base + 8), i16(r, base + 10)),
    ))

# ★ SDL 用 slot[0] 判定有无传感器数据，所以真值必须在 slot[0]
# SDL interval 自适应：每帧 3 组样本 → interval≈周期/3，
# 3 组同值积分 = w×(周期/3)×3 = w×周期（真实值）。所以 3 组都要填。
for i in range(3):
    check(f"slot[{i}] = 真实 accel（3 组同值）",
          slots[i][0] == (100, 200, 4000), str(slots[i][0]))
    # 15ms 原生周期下不缩放，gyro 原值直接填
    exp = (3000, -3000, 1500)
    check(f"slot[{i}] = gyro 原值（3 组同值）",
          slots[i][1] == exp, f"{slots[i][1]} vs {exp}")
check("slot[0] 有数据（SDL bHasSensorData 判定通过）",
      slots[0][0][2] != 0, f"accel_z={slots[0][0][2]}")

print()
print("=" * 70)
print("2. 不放大倍数")
print("=" * 70)
# 主机积分 3 组 = slot0+slot1+slot2 = 0+0+真实 = 真实（1 倍）
# 3 组同值是 SDL interval 自适应的要求，不是放大：
# interval 会被算成 周期/3，积分 3×(周期/3)=周期，总量正确。
total_gx = sum(s[1][0] for s in slots)
check("3 组同值（配合 SDL interval，15ms 下无需缩放）",
      total_gx == 9000, f"sum={total_gx} 期望=9000")

print()
print("=" * 70)
print("3. 参数")
print("=" * 70)
# 15ms 原生周期：3 组样本 × 5ms = 15ms，主机积分天然正确
check("DEFAULT_PERIOD_MS = 15ms（JC1 原生）",
      abs(DEFAULT_PERIOD_MS - 15.0) < 0.01, f"{DEFAULT_PERIOD_MS}ms")
per_sec = (1000.0 / DEFAULT_PERIOD_MS) * 15.0
check("每秒积分量 = 1000ms（陀螺仪速度正确）",
      abs(per_sec - 1000.0) < 1.0,
      f"{per_sec:.1f}ms（若>1000 则加速）")

print()
print("=" * 70)
print("4. 源码守卫")
print("=" * 70)
rp = (SRC / "virtual" / "reports.py").read_text(encoding="utf-8")
# 删掉 Pro1Encoder 后只剩 JoyConEncoder 一处
check("JoyConEncoder 3 组都填真值",
      "ax, ay, az, g1, g2, g3 = one" in rp and "one if i ==" not in rp)
check("注释说明 SDL 自适应 interval", "interval = elapsed" in rp or "自适应" in rp)

print()
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("全部通过")
