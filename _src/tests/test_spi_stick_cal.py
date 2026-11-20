# -*- coding: utf-8 -*-
"""SPI 摇杆校准必须声明「标准中心 2048 + 满行程 2047」，且两组都填真值。

═══════════════════════════════════════════════════════════════════════════
2026-11-19 重新定案（推翻 2026-11-18 的「实测中心」方案）
═══════════════════════════════════════════════════════════════════════════
旧方案：SPI 声明 center=(2040,2166)/(1987,1984)、行程=900
  把正确性绑在「SPI 声明必须精确匹配物理回中值」上，实测出现回中随机偏移。

新方案（依据官方逆向文档 + viiper 实测）：
  · dekuNukem/Nintendo_Switch_Reverse_Engineering `spi_flash_notes.md`：
      "The Switch does various sanity checks on the calibration values.
       If these checks fail, it applies a default calibration instead."
      Pro Controller 要求各方向 delta ≥ 0x542(1346)、X max ≥ 0x4d5(1237)。
      → 旧的 900 远低于门槛，属违规值。
  · viiper（Alia5/VIIPER，Pro2 项目实际使用的虚拟手柄库）nspro 实现原文：
      "same endpoints: centre=2048, positive=2047, negative=2048.
       A 1600 calibration here clipped the last 22% of valid travel in SDL/Steam."
      stick := []byte{0xFF,0xF7,0x7F, 0,0x08,0x80, ...}
    → center=2048、行程=2047（满量程），且报告中心也用 2048。
      声明中心 == 报告中心恒成立 → 回中值必然为 0，不依赖校准协商精度。

判据：
  1. joyconL / joyconR 的 0x603D 解包 = 12 个值全为标准配置
     [2047,2047,2048,2048,2047,2047, 2048,2048,2047,2047,2047,2047]
  2. center 必须是 2048（不再是 2040/2166/1987/1984）
  3. 行程必须是 2047（不再是 900）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from virtual import descriptors as D  # noqa: E402
from virtual.hid_function import Switch1HidFunction  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def unpack12(b, count):
    bits = 0
    n = 0
    out = []
    i = 0
    while len(out) < count:
        bits |= b[i] << n
        n += 8
        i += 1
        while n >= 12 and len(out) < count:
            out.append(bits & 0xFFF)
            bits >>= 12
            n -= 12
    return out


EXPECT = [2047, 2047, 2048, 2048, 2048, 2048,
          2048, 2048, 2048, 2048, 2047, 2047]

print("=" * 70)
print("SPI 0x603D 摇杆校准（标准中心 2048 + 满行程 2047）")
print("=" * 70)

hL = Switch1HidFunction(D.DEVICES["joyconL"], "joyconL")
valsL = unpack12(hL._spi_image(0x603D, 18), 12)
check("左设备 12 值 = 标准配置", valsL == EXPECT, str(valsL))

hR = Switch1HidFunction(D.DEVICES["joyconR"], "joyconR")
valsR = unpack12(hR._spi_image(0x603D, 18), 12)
check("右设备 12 值 = 标准配置", valsR == EXPECT, str(valsR))

# 与 viiper nspro 的 18 字节逐字节一致
VIIPER_STICK = bytes([0xFF, 0xF7, 0x7F, 0, 0x08, 0x80, 0, 0x08, 0x80,
                      0, 0x08, 0x80, 0, 0x08, 0x80, 0xFF, 0xF7, 0x7F])
check("左设备 0x603D 字节 == viiper nspro 原值",
      hL._spi_image(0x603D, 18) == VIIPER_STICK,
      hL._spi_image(0x603D, 18).hex(" "))
check("右设备 0x603D 字节 == viiper nspro 原值",
      hR._spi_image(0x603D, 18) == VIIPER_STICK,
      hR._spi_image(0x603D, 18).hex(" "))

# 关键守卫：后 9 字节不能全 0（SDL 会读两组）
check("左设备后9字节非全0",
      any(hL._spi_image(0x603D, 18)[9:18]), "否则 SDL 右摇杆校准全0")
check("右设备后9字节非全0",
      any(hR._spi_image(0x603D, 18)[9:18]), "")

print()
print("=" * 70)
print("中心必须 2048、行程必须 2047（同时满足 sanity 门槛与 viiper 语义）")
print("=" * 70)
check("左组中心位（index 2,3）= 2048",
      valsL[2] == 2048 and valsL[3] == 2048, f"{valsL[2]},{valsL[3]}")
check("右组中心位（index 6,7）= 2048",
      valsR[6] == 2048 and valsR[7] == 2048, f"{valsR[6]},{valsR[7]}")
check("左行程位（index 0,1）= 2047", valsL[0] == 2047 and valsL[1] == 2047,
      f"{valsL[0]},{valsL[1]}")
check("右行程位（index 10,11）= 2047", valsR[10] == 2047 and valsR[11] == 2047,
      str(valsR[10:12]))
check("行程达 sanity 门槛（≥1237）", valsL[0] >= 1237, f"{valsL[0]}")

print()
print("=" * 70)
print("源码守卫")
print("=" * 70)
hf = (SRC / "virtual" / "hid_function.py").read_text(encoding="utf-8")
check("有 _stick_cal 方法", "def _stick_cal" in hf)
check("声明标准中心常量 _STICK_CENTER = 2048",
      "_STICK_CENTER = 2048" in hf)
check("声明行程常量 _STICK_TRAVEL = 2047",
      "_STICK_TRAVEL = 2047" in hf)
check("注释记录官方 sanity check 依据",
      "sanity" in hf.lower() or "0x542" in hf)
check("注释记录 viiper 依据", "viiper" in hf.lower())

print()
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("全部通过")
