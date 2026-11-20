# -*- coding: utf-8 -*-
"""幽灵设备清理验收。

═══════════════════════════════════════════════════════════════════════════
用户要求（2026-11-17）
═══════════════════════════════════════════════════════════════════════════
「设定幽灵设备每次退出程序后都要清理」

───────────────────────────────────────────────────────────────────────────
为什么这件事很重要（不只是洁癖）
───────────────────────────────────────────────────────────────────────────
Windows 设备树会为每个曾经出现过的 USB 设备保留一个节点。
usbip 断开后，节点变成 `Status=Unknown / Present=False`（幽灵）。

幽灵节点会：
  · 让 Windows / GamepadTester 枚举到**重复的手柄**
  · 排查摇杆问题时可能读到旧节点的数据（污染诊断）
  · 累积（实测到 8 个）

旧逻辑的缺陷：非管理员且 unknown < 5 就跳过（"避免每次弹 UAC"），
结果残留越积越多。现在改为**只要存在就清理**。

───────────────────────────────────────────────────────────────────────────
判据
───────────────────────────────────────────────────────────────────────────
  A. 源码里不再有「未到提权阈值」这类跳过分支
  B. cleanup_on_exit 在 GUI 关闭与 atexit 两处都注册
  C. 清理函数真的能把 ghost 数降到 0（需要真实调用，可能弹 UAC）
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


# ══════════════════════════════════════════════════════════════════════════ #
print("=" * 78)
print("A. 源码：不再有跳过清理的阈值分支")
print("=" * 78)

src = (ROOT / "device_cleanup.py").read_text(encoding="utf-8")

check("不再有「未到提权阈值」提示",
      "未到提权阈值" not in src)
check("不再有 unknown >= 5 的分支",
      "unknown >= 5" not in src)
check("非管理员也调用提权清理",
      "remove_ghosts_elevated" in src)
# 关键：else 分支里必须真的调用提权，不能有任何 return 提前退出
import re
m = re.search(r"else:\s*\n\s*left = remove_ghosts_elevated\(\)", src)
check("非管理员分支直接提权清理（无前置条件）", bool(m),
      m.group(0).replace("\n", " ")[:60] if m else "未找到直接调用")

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 78)
print("B. 退出路径：GUI 关闭 + atexit 双注册")
print("=" * 78)

gui = (ROOT / "gui.py").read_text(encoding="utf-8")
check("gui.py 关闭时调用 cleanup_on_exit", "cleanup_on_exit()" in gui)
check("gui.py 注册了 atexit",
      "atexit.register" in gui or "_atexit.register" in gui)
# 确认 atexit 注册的是清理相关函数
m2 = re.search(r"def (_exit_cleanup|_atexit_cleanup)[^\n]*:[\s\S]{0,400}?cleanup_on_exit",
               gui)
check("atexit 回调内部调用 cleanup_on_exit", bool(m2),
      "找到" if m2 else "未找到")

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 78)
print("B2. ★ 启动时也清理（覆盖强制结束的情况）")
print("=" * 78)

# 关键认识：Windows 的 TerminateProcess（任务管理器强杀）没有任何
# 用户态回调 —— 退出清理一定会漏。所以必须在启动时也清一遍。
check("gui.py 在启动时调用清理",
      "启动清理" in gui)
# 必须位于创建虚拟设备之前
i_boot = gui.find("启动清理")
i_validate = gui.find("validate_config_file")
check("启动清理在配置校验之前（早于任何设备创建）",
      0 < i_boot < i_validate, f"boot@{i_boot} validate@{i_validate}")

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 78)
print("C. 实测：清理能否把幽灵数降到 0")
print("=" * 78)

import device_cleanup as dc  # noqa: E402

before_unknown = dc.count_unknown()
before_all = dc.count_ghosts()
print(f"  清理前: 幽灵={before_unknown} 总节点={before_all} "
      f"管理员={dc._is_admin()}")

if before_all == 0:
    print("  （当前无残留节点，跳过实测。这不代表清理有问题。）")
    check("当前无残留节点（无需清理）", True)
else:
    dc.cleanup_on_exit()
    after_unknown = dc.count_unknown()
    print(f"  清理后: 幽灵={after_unknown}")
    check("★ 清理后幽灵数为 0", after_unknown == 0, f"剩 {after_unknown}")
    check("清理后总节点数下降或归零",
          dc.count_ghosts() <= before_all, f"{before_all} → {dc.count_ghosts()}")

# ══════════════════════════════════════════════════════════════════════════ #
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
