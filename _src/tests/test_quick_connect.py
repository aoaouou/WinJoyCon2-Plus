# -*- coding: utf-8 -*-
"""一键连接优化的验收（不碰真机，验证契约）。

覆盖 2026-11-16 三项优化：
  1. 所有 subprocess 调用都带 CREATE_NO_WINDOW（不再闪黑窗口）
  2. ensure_side 增量补侧，不拆已连的侧
  3. 连接重试逻辑存在
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
print("=" * 72)
print("1. ★ 不再闪黑窗口：所有 subprocess 调用必须走 run_hidden")
print("=" * 72)

py_files = [p for p in SRC.rglob("*.py")
            if "__pycache__" not in str(p) and "tests" not in str(p)]
bare = []
for f in py_files:
    if f.name == "hidden_exec.py":
        continue
    txt = f.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(txt.splitlines(), 1):
        if "subprocess.run(" in line and "def " not in line:
            bare.append(f"{f.relative_to(SRC)}:{i}")

print(f"  扫描 {len(py_files)} 个源文件")
if bare:
    for b in bare:
        print(f"    ! {b}")
check("无裸 subprocess.run", not bare, f"{len(bare)} 处" if bare else "0 处")

# run_hidden 必须真的设置 CREATE_NO_WINDOW
from hidden_exec import CREATE_NO_WINDOW, run_hidden  # noqa: E402
check("CREATE_NO_WINDOW = 0x08000000", CREATE_NO_WINDOW == 0x08000000,
      hex(CREATE_NO_WINDOW))
check("run_hidden 强制注入 creationflags",
      "creationflags=CREATE_NO_WINDOW" in inspect.getsource(run_hidden))

# --------------------------------------------------------------------------- #
print()
print("=" * 72)
print("2. ★ ensure_side 必须增量补侧，不能整体 teardown 重建")
print("=" * 72)
from virtual.vjoy_out import VirtualJoyCon1  # noqa: E402

src = inspect.getsource(VirtualJoyCon1.ensure_side)
print("  ensure_side 源码检查：")
check("有 _add_sides 增量路径", "_add_sides" in src)
# 判"是否有实际调用"：排除注释与 docstring 说明（形如 "原实现是 `_teardown()`"）
_real_calls = [ln for ln in src.splitlines()
               if ln.strip().startswith("self._teardown()")]
check("不再无条件 _teardown", not _real_calls,
      f"{len(_real_calls)} 处实际调用" if _real_calls else "无实际调用（仅说明文字）")
check("已有 server 时不重建", "self._server is None" in src)

check("_add_sides 方法存在", hasattr(VirtualJoyCon1, "_add_sides"))
add_src = inspect.getsource(VirtualJoyCon1._add_sides)
# 判据更新（2026-11-16 左手失灵修复后）：
# 旧实现靠 `if busid in server._devices: continue` 跳过撞号，
# 但 busid 按侧写死，左手永远算成 "1-1" → 直接跳过 → 左手建不出来。
# 现在改成 _alloc_busid() 取空闲编号，唯一性由分配器保证，
# 不再需要"查已存在就跳过"这种被动防守。
check("_add_sides 用 _alloc_busid 取空闲 busid",
      "_alloc_busid(server)" in add_src)
check("分配器确实读 _devices 判断占用",
      "_devices" in inspect.getsource(VirtualJoyCon1._alloc_busid))

# --------------------------------------------------------------------------- #
print()
print("=" * 72)
print("3. ★ 连接重试：单次超时缩短 + 3 次退避")
print("=" * 72)
import main  # noqa: E402

csrc = inspect.getsource(main.connect_joycon)
check("单次超时 8.0s（快失败好重试）", "timeout=8.0" in csrc,
      "timeout=8.0" if "timeout=8.0" in csrc else "未找到")
check("有 3 次重试循环", "range(1, 4)" in csrc)
check("失败后有 disconnect 释放句柄", "await client.disconnect()" in csrc)
check("退避等待存在", "asyncio.sleep(delay)" in csrc)

# --------------------------------------------------------------------------- #
print()
print("=" * 72)
print("4. 一键连接必须并行（不串行 for 循环）")
print("=" * 72)
gui_src = (SRC / "gui.py").read_text(encoding="utf-8", errors="replace")
i = gui_src.find("class _AutoConnectThread")
j = gui_src.find("class ", i + 10)
quick = gui_src[i:j] if j > i else gui_src[i:]

check("使用 asyncio.gather 并发", "asyncio.gather" in quick)
check("无串行 'for item in (left, right)' 连接循环",
      "for item in (left, right)" not in quick)
check("_probe_known_macs 仍是并行任务", "_probe_known_macs" in quick)
check("扫描结果可补充/替换探测结果",
      "item.get(\"device\")" in quick or "item.get('device')" in quick)

# --------------------------------------------------------------------------- #
print()
print("=" * 72)
print("5. 探活不再双重连接")
print("=" * 72)
probe_src = inspect.getsource(main._probe_known_macs)
check("_try 不做 connect+disconnect 探活",
      "await cl.connect()" not in probe_src,
      "已移除" if "await cl.connect()" not in probe_src else "仍存在")

# --------------------------------------------------------------------------- #
print()
print("=" * 72)
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
print("=" * 72)
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
    raise SystemExit(1)
print("  全部通过")
