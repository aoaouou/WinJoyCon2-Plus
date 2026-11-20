# -*- coding: utf-8 -*-
"""VirtualJoyCon1 构造/双侧建设备验收 —— 防"第二只手柄连不上"。

═══════════════════════════════════════════════════════════════════════════
真实 bug（2026-11-17）
═══════════════════════════════════════════════════════════════════════════
现象：一次只能连一个手柄，另一个一直 `AttributeError:
      'VirtualJoyCon1' object has no attribute '_server'`。

根因：
  __init__ 末尾调用 self._ensure() → ensure_side() → 开头读 self._server，
  但 __init__ 从未初始化 self._server（只在 _ensure 内部某处赋过值），
  → 首次构造即 AttributeError → 第二只手柄的虚拟设备建不出来。

附带 bug：vjoy_out 两处 `from virtual.hid_function import Switch1HidFunction`
  只 import 了类，却在使用 DEFAULT_PERIOD_MS → NameError 被吞掉，
  设备"启动失败"。

判据：
  1. 构造不抛异常
  2. 双侧 ensure_side 后 _slots 有 left+right
  3. _server 属性在 __init__ 后即存在
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


print("=" * 70)
print("1. 构造与双侧建设备")
print("=" * 70)
from virtual.vjoy_out import VirtualJoyCon1  # noqa: E402

try:
    v = VirtualJoyCon1("both")
    ok_ctor = True
    err = ""
except Exception as e:  # noqa: BLE001
    v, ok_ctor, err = None, False, f"{type(e).__name__}: {e}"
check("构造不抛异常", ok_ctor, err)

if v:
    check("__init__ 后已有 _server 属性", hasattr(v, "_server"),
          f"_server={getattr(v,'_server','<缺失>')}")
    try:
        v.ensure_side(True, True)
        ok_ens = True
        eerr = ""
    except Exception as e:  # noqa: BLE001
        ok_ens, eerr = False, f"{type(e).__name__}: {e}"
    check("ensure_side(True,True) 不抛异常", ok_ens, eerr)
    check("双侧虚拟设备都建出（left+right）",
          set(v._slots.keys()) == {"left", "right"},
          str(list(v._slots.keys())))

print()
print("=" * 70)
print("2. 源码守卫")
print("=" * 70)
src = (SRC / "virtual" / "vjoy_out.py").read_text(encoding="utf-8")
check("__init__ 里初始化了 _server",
      "self._server = None" in src.split("def _ensure")[0])
# 两处 import 都必须带 DEFAULT_PERIOD_MS
import re
imports = re.findall(r"from virtual\.hid_function import ([^\n]+)", src)
bad = [i for i in imports if "DEFAULT_PERIOD_MS" not in i and "DEFAULT_PERIOD_MS" in src]
check("所有 hid_function import 都带 DEFAULT_PERIOD_MS",
      all("DEFAULT_PERIOD_MS" in i for i in imports),
      f"imports={imports}")

print()
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    sys.exit(1)
print("全部通过")
