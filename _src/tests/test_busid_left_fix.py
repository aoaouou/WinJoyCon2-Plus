# -*- coding: utf-8 -*-
"""左手柄失灵（虚拟设备建不出来）验收。

═══════════════════════════════════════════════════════════════════════════
现象
═══════════════════════════════════════════════════════════════════════════
右手先连 → 只建了 right（057e:2007）。
左手后连 → BLE 连上了、能震（震动走 BLE GATT，不经过 usbip），
但 Windows 里**根本没有** PID_2006 设备，按键/摇杆/陀螺仪全无。

═══════════════════════════════════════════════════════════════════════════
根因
═══════════════════════════════════════════════════════════════════════════
两条建设备路径用了不同的 busid 编号规则：

    _ensure()      targets 顺序 enumerate(start=1)  → right 得 "1-1"
    _add_sides()   按侧写死 left=1 / right=2        → left 也算 "1-1"

_add_sides 里 `if busid in server._devices: continue` → 撞号直接跳过，
left 一个字节都没建。而且因为 _slots["left"] 没被设置，
ensure_side 每次都重试、每次都撞同一堵墙。

═══════════════════════════════════════════════════════════════════════════
判据
═══════════════════════════════════════════════════════════════════════════
  A. _alloc_busid 分配空闲编号，不撞已占用的
  B. 模拟「先右手、再左手」的真实顺序：两只设备都建出来，busid 互不相同
  C. 反向顺序（先左后右）同样成立
  D. 只有一侧时，busid 从 1-1 开始（不加空洞）
  E. 源码里 没有 按侧写死的 busid 计算
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from virtual.vjoy_out import VirtualJoyCon1  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


class FakeServer:
    """只保留 _devices 容器，够 _alloc_busid 用。"""
    def __init__(self, existing=()):
        self._devices = {b: (None, None) for b in existing}


alloc = VirtualJoyCon1._alloc_busid

# ──────────────────────────────────────────────────────────────────────── #
print("=" * 74)
print("A. busid 分配器")
print("=" * 74)

check("空 server → 1-1", alloc(FakeServer()) == "1-1", alloc(FakeServer()))
check("已占 1-1 → 1-2", alloc(FakeServer(["1-1"])) == "1-2",
      alloc(FakeServer(["1-1"])))
check("已占 1-2 → 1-1（补空洞）", alloc(FakeServer(["1-2"])) == "1-1",
      alloc(FakeServer(["1-2"])))
check("已占 1-1/1-2 → 1-3", alloc(FakeServer(["1-1", "1-2"])) == "1-3",
      alloc(FakeServer(["1-1", "1-2"])))
check("已占 1-1/1-3 → 1-2（补空洞）",
      alloc(FakeServer(["1-1", "1-3"])) == "1-2",
      alloc(FakeServer(["1-1", "1-3"])))
check("畸形 busid 不炸", alloc(FakeServer(["weird"])) == "1-1",
      alloc(FakeServer(["weird"])))

# ──────────────────────────────────────────────────────────────────────── #
print()
print("=" * 74)
print("B. 真实顺序：先右手，再追加左手（这是用户的实际场景）")
print("=" * 74)


class MiniVirtual(VirtualJoyCon1):
    """绕开真 USB/IP，只验证 busid 分配与 slot 登记。"""
    def __init__(self):
        self.side = "right"
        self._lock = __import__("threading").Lock()
        self._buttons = set()
        self._lx = self._ly = self._rx = self._ry = 0
        self._bridge = None
        self._slots = {}
        self._ready = True
        self._pushed = 0
        self._failed = 0
        self._vibration_cb = None
        self._bits_l = 0
        self._bits_r = 0
        self._stick_l = (2048, 2048)
        self._stick_r = (2048, 2048)
        self._imuraw_l = None
        self._imuraw_r = None
        self._logged_buttons = set()
        self._server = FakeServer()

    def _register(self, side):
        busid = self._alloc_busid(self._server)
        self._server._devices[busid] = (side, None)
        self._slots[side] = {"busid": busid}
        return busid


v = MiniVirtual()
assert v._register("right") == "1-1", "右手应先拿 1-1"
assert v._register("left") not in (None, "1-1"), "左手不能复用 1-1"
print(f"  right → {v._slots['right']['busid']}, left → {v._slots['left']['busid']}")
check("先右手：right=1-1", v._slots["right"]["busid"] == "1-1")
check("再左手：left 拿到不同的 busid",
      v._slots["left"]["busid"] != v._slots["right"]["busid"],
      v._slots["left"]["busid"])
check("两侧都登记进 _slots", set(v._slots) == {"left", "right"}, str(set(v._slots)))
check("server 里有两个设备", len(v._server._devices) == 2,
      str(list(v._server._devices)))

# ──────────────────────────────────────────────────────────────────────── #
print()
print("=" * 74)
print("C. 反向顺序：先左手，再追加右手")
print("=" * 74)

v2 = MiniVirtual()
v2._register("left")
v2._register("right")
check("先左手：left=1-1", v2._slots["left"]["busid"] == "1-1",
      v2._slots["left"]["busid"])
check("再右手：right=1-2", v2._slots["right"]["busid"] == "1-2",
      v2._slots["right"]["busid"])
check("两 busid 不同", v2._slots["left"]["busid"] != v2._slots["right"]["busid"])

# ──────────────────────────────────────────────────────────────────────── #
print()
print("=" * 74)
print("D. 双侧一次性建（_ensure 的 both 路径）")
print("=" * 74)

v3 = MiniVirtual()
v3._register("left")
v3._register("right")
check("both：1-1 + 1-2，无空洞",
      sorted(x["busid"] for x in v3._slots.values()) == ["1-1", "1-2"],
      str(sorted(x["busid"] for x in v3._slots.values())))

# ──────────────────────────────────────────────────────────────────────── #
print()
print("=" * 74)
print("E. 源码：不再按侧写死 busid")
print("=" * 74)

src = (ROOT / "virtual" / "vjoy_out.py").read_text(encoding="utf-8")

live = [ln for ln in src.splitlines()
        if "idx = 1 if s_ == " in ln or "idx = 1 if s ==" in ln]
check("没有 `idx = 1 if side == 'left' else 2` 这类活代码", not live, str(live))

check("_alloc_busid 存在", "_alloc_busid" in src)

# 两处建设备都必须调用分配器
calls = [ln.strip() for ln in src.splitlines()
         if "busid = self._alloc_busid(server)" in ln]
check("_ensure 与 _add_sides 都用分配器", len(calls) == 2, str(calls))

check("_add_sides 不再靠 continue 跳过撞号",
      "if busid in getattr(server, \"_devices\", {}):" not in src)

# ──────────────────────────────────────────────────────────────────────── #
print()
print("=" * 74)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    print("=" * 74)
    sys.exit(1)
print("全部通过")
print("=" * 74)
