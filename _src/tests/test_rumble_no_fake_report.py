# -*- coding: utf-8 -*-
"""子命令 reply 必须携带真实摇杆值 —— 根因回归测试。

═══════════════════════════════════════════════════════════════════════════
根因（2026-11-17 最终确认）
═══════════════════════════════════════════════════════════════════════════
现象：触发震动/主机写 Output Report 时，摇杆往固定方向（左下）跳。

根因链：
  1. 主机写 Output Report（0x01 是 rumble+子命令复合包，0x11/0x12 是子命令）
  2. hid_function._build_reply() 生成 0x21 子命令应答
  3. **旧代码的 reply 里摇杆字段 buf[6:12] 全是 0**（从未填 state）
  4. pending_in() 优先返回 pending reply
  5. 主机把 12 位摇杆 (0,0) 归一化成 (-1,-1) = 满量程左下 → 跳变

为什么之前所有修复都无效：
  · 改映射层 / stick_map：假报告绕过映射层，直接是最终字节
  · 改 BLE 震动频率 / 傻震对照：假报告来自 Output Report 处理，与 BLE 写入无关
  · 砍掉 0x01 的 reply：0x01 是复合包，砍了 SDL 握手失败 → 手柄失灵

正确修复：
  · 保留 0x01 的 reply（握手需要）
  · 在 _reply_header 里把真实 state 的摇杆填进 buf[6:12]
  · 这样 reply 与正常 0x30 报告的摇杆字节一致，主机不再读到 (0,0)

═══════════════════════════════════════════════════════════════════════════
判据
═══════════════════════════════════════════════════════════════════════════
  A. 子命令 reply 的摇杆字段 = 当前真实 state（非全 0）
  B. 0x01 复合包仍产生 reply（SDL 握手，手柄可用）
  C. 摇杆变化时 reply 跟随变化（不是固定值）
  D. 兜底：无 state 时填中心值 0x8000，绝不全 0
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from virtual import descriptors as D  # noqa: E402
from virtual.hid_function import Switch1HidFunction  # noqa: E402
from virtual.reports import PadState, _pack_stick12  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def mk_hid(side="L"):
    spec = D.DEVICES["joyconL" if side == "L" else "joyconR"]
    return Switch1HidFunction(spec, "joyconL" if side == "L" else "joyconR",
                              period_ms=15.0)


def send_subcmd(hid, rid, subcmd, seq=1):
    pkt = bytearray(49)
    pkt[0] = rid
    pkt[1] = seq
    pkt[2:10] = bytes.fromhex("74 c8 3d 72 74 c8 3d 72")
    pkt[10] = subcmd
    if subcmd == 0x03:
        pkt[11] = 0x30
    hid._handle_output_report(bytes(pkt))
    return hid._pending_replies[-1] if hid._pending_replies else None


# ══════════════════════════════════════════════════════════════════════════ #
print("=" * 78)
print("A. ★ 子命令 reply 的摇杆字段 = 真实 state（非全 0）")
print("=" * 78)

hid = mk_hid()
st = PadState()
st.lx, st.ly, st.rx, st.ry = 1234, 2345, 3456, 1234
hid.set_state(st)

rep = send_subcmd(hid, 0x01, 0x02)
check("0x01 复合包仍产生 reply（握手需要）", rep is not None)
if rep:
    left_bytes = bytes(rep[6:9])
    right_bytes = bytes(rep[9:12])
    check("★ 左摇杆字段 != 全 0", left_bytes != b"\x00\x00\x00",
          left_bytes.hex(" "))
    check("★ 右摇杆字段 != 全 0", right_bytes != b"\x00\x00\x00",
          right_bytes.hex(" "))
    check("左摇杆字段 = state 打包值",
          left_bytes == _pack_stick12(st.lx, st.ly),
          f"{left_bytes.hex(' ')} vs {_pack_stick12(st.lx, st.ly).hex(' ')}")
    check("右摇杆字段 = state 打包值",
          right_bytes == _pack_stick12(st.rx, st.ry),
          f"{right_bytes.hex(' ')} vs {_pack_stick12(st.rx, st.ry).hex(' ')}")

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 78)
print("B. 0x01 复合包 reply 保留（手柄可用性）")
print("=" * 78)

# 0x01 是 rumble+subcmd，SDL 用它设输入模式、读校准
# 砍掉 reply 会导致 SDL "手柄列出但打不开"
for subcmd in (0x02, 0x03, 0x04, 0x10, 0x21, 0x40, 0x48):
    h = mk_hid()
    r = send_subcmd(h, 0x01, subcmd)
    check(f"0x01 subcmd=0x{subcmd:02X} 有 reply（握手不失败）", r is not None)

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 78)
print("C. 摇杆变化时 reply 跟随变化")
print("=" * 78)

hid = mk_hid()
vals = []
for lx, ly in ((1000, 2000), (3000, 500), (2048, 2048)):
    st = PadState()
    st.lx, st.ly = lx, ly
    hid.set_state(st)
    r = send_subcmd(hid, 0x11, 0x02, seq=lx & 0xFF)
    vals.append(bytes(r[6:9]) if r else None)

check("reply 摇杆随 state 变化（3 个不同值）",
      len(set(vals)) == 3, str([v.hex(" ") if v else None for v in vals]))

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 78)
print("D. pending_in 优先返回 reply 时也是真实摇杆")
print("=" * 78)

hid = mk_hid()
st = PadState()
st.lx, st.ly, st.rx, st.ry = 1500, 2500, 1800, 2200
hid.set_state(st)
# 先塞一个 reply
send_subcmd(hid, 0x01, 0x02)
# ★ 2026-11-19：reply 不再无条件抢占输入帧 —— 每发 1 条输入帧才放行 1 条
#   reply（防震动期 reply 洪泛把 0x30 饿死）。所以这里多取几次，
#   期间 reply 一定会被发出，且之后恢复正常输入报告。
out = None
for _ in range(4):
    o = hid.pending_in(1)
    if o and o[0] == 0x21:
        out = o
        break
check("pending_in 会发出 0x21 reply（不饿死）", out is not None,
      f"id=0x{out[0]:02X}" if out else "未发出")
if out:
    lx12 = out[6] | ((out[7] & 0x0F) << 8)
    check("★ 主机读到的摇杆不是 0", lx12 != 0, f"lx12={lx12}")
    check("主机读到的摇杆 = state", lx12 == st.lx, f"{lx12} vs {st.lx}")
# reply 发完后必须恢复正常输入报告
o2 = hid.pending_in(1)
check("reply 之后恢复输入报告", o2 and o2[0] != 0x21,
      f"id=0x{o2[0]:02X}" if o2 else "None")

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 78)
print("E. 源码守卫")
print("=" * 78)

src = (ROOT / "virtual" / "hid_function.py").read_text(encoding="utf-8")
check("0x01 在 reply 分支中（未误砍）",
      "if rid not in (0x01, 0x11, 0x12, 0x82):" in src)
# ★ 2026-11-19：0x10 是纯震动报告（官方 bluetooth_hid_notes.md：
#   "otherwise only rumble with x10 command"），不含子命令，
#   必须**排除**在 reply 分支之外，否则震动期每条都生成 reply 挤占输入帧。
check("0x10 已被排除在 reply 分支外（纯震动无子命令）",
      "0x10" not in src.split("if rid not in (")[1].split(")")[0],
      "0x10 不应出现在 reply 判据里")
check("_reply_header 填真实摇杆",
      "buf[6:9] = _pack_stick12(st.lx, st.ly)" in src)
check("关键注释存在", "根因修复：把真实摇杆值填进 reply" in src)

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
