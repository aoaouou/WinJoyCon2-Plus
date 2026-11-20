# -*- coding: utf-8 -*-
"""HD 震动（JC2 → JC1 震动块翻译）验收。

═══════════════════════════════════════════════════════════════════════════
这次修的是什么
═══════════════════════════════════════════════════════════════════════════
现象：虚拟 Joy-Con 1 在 Windows / 模拟器里**完全不震**，或者只有
"嗡一下"没有强弱。三个独立根因，逐个用测试钉住：

  根因 1（通道选错）
    震动块被当成 XInput 的 large/small motor，走 command 0x0A 的预置样本。
    JC2 真正的 HD 通道是 GATT 0x0012 的 Output Report 0x01（16 字节）。

  根因 2（功能位没开）
    feature bit 5 = Rumble（s2r_commands.md:794）。不发 0x0C subcmd 02/04
    带上 0x27 掩码，手柄会**静默丢弃**所有震动包。

  根因 3（保真度丢失 + 回调签名错）
    - 旧代码 `small = min(255, blk[1])` 把"频率码+振幅"混合字节当强度，
      中间力度全丢。
    - 旧代码把 cb 当 vgamepad 的 6 参数回调，而 hid.rumble_cb 是
      2 参数（left_block, right_block），每次调用都 TypeError 被吞掉。

═══════════════════════════════════════════════════════════════════════════
判据
═══════════════════════════════════════════════════════════════════════════
  A. 编码与 SDL 的 EncodeHDRumble 逐位同构（含 29000 限幅）
  B. 振幅映射与 SDL 的 hfa/lfa 原表逐项一致（不能自己造指数近似）
  C. 中性块 → 静音；非中性块 → 有强度
  D. 组帧 17 字节、report ID 0、序号在 0..0xF 循环
  E. 发送器：节流、去重、超时静音、失败降级
  F. 源码接线：vjoy_out 无旧二值化闭包；main.py 先开功能位；GUI 开关接 HD
"""
from __future__ import annotations

import inspect
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from virtual import rumble_hd as R  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    tail = f"  {detail}" if detail else ""
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{tail}")


# ══════════════════════════════════════════════════════════════════════════ #
print("=" * 76)
print("A. 编码与 SDL EncodeHDRumble 同构")
print("=" * 76)

# SDL 原始实现（逐行照抄，用于对照）
def sdl_encode(high_freq, high_amp, low_freq, low_amp):
    return bytes((
        high_freq & 0xFF,
        ((high_amp >> 4) & 0xFC) | ((high_freq >> 8) & 0x03),
        (high_amp >> 12) | (low_freq << 4),
        (low_amp & 0xC0) | ((low_freq >> 4) & 0x3F),
        low_amp >> 8,
    )) if False else bytes((
        high_freq & 0xFF,
        ((high_amp >> 4) & 0xFC) | ((high_freq >> 8) & 0x03),
        ((high_amp >> 12) & 0xFF) | ((low_freq << 4) & 0xF0),
        (low_amp & 0xC0) | ((low_freq >> 4) & 0x3F),
        (low_amp >> 8) & 0xFF,
    ))


mismatch = []
for amp16 in (0, 1, 100, 514, 4096, 29000, 40000, 65535):
    hf = int(round(amp16 * R.JC2_RUMBLE_MAX / 65535.0))
    expect = sdl_encode(R.JC2_HF_FREQ, hf, R.JC2_LF_FREQ, hf)
    got = R.encode_jc2(float(amp16), float(amp16))
    if got != expect:
        mismatch.append((amp16, expect.hex(), got.hex()))
check("encode_jc2 与 SDL 逐字节一致（8 个振幅采样点）", not mismatch,
      str(mismatch[:2]))

check("默认频率码 = SDL 的 0x187 / 0x112",
      R.JC2_HF_FREQ == 0x187 and R.JC2_LF_FREQ == 0x112,
      f"{R.JC2_HF_FREQ:#x}/{R.JC2_LF_FREQ:#x}")
check("振幅上限 = SDL RUMBLE_MAX(29000)", R.JC2_RUMBLE_MAX == 29000)

# 限幅：超过 29000 的编码不能溢出到别的字段
top = R.decode_jc2(R.encode_jc2(65535.0, 65535.0))
check("满幅编码还原 = 0x7140（29000 丢低 4 位）",
      top == (0x7140, 0x7140), str(tuple(hex(x) for x in top)))

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 76)
print("B. 振幅映射必须用 SDL 原表（不能自己造指数近似）")
print("=" * 76)

# sdl_switch.c 的 hfa[] 抽样（真实值）
HFA_SAMPLES = {
    0x00: 0, 0x02: 514, 0x04: 775, 0x10: 2192, 0x20: 7698,
    0x40: 15067, 0x80: 30134, 0xC8: 65535,
}
bad = [(hex(c), R.jc1_hf_amp16(c), v) for c, v in HFA_SAMPLES.items()
       if R.jc1_hf_amp16(c) != v]
check("HF 映射与 hfa[] 原表逐项相等（8 个采样）", not bad, str(bad[:2]))

# 反函数自洽
rt_bad = [hex(c) for c in range(0x00, 0xCA, 0x02)
          if R.jc1_hf_amp16_to_code(R.jc1_hf_amp16(c)) != c]
check("HF 正反函数自洽（101 档全覆盖）", not rt_bad, str(rt_bad[:3]))

# 指数近似会给 0x10 → 724，真表 2192（差 3 倍）—— 显式记录这个坑
approx = 514.0 * ((65535.0 / 514.0) ** ((0x10 - 0x02) / (0xC8 - 0x02)))
check("指数近似会差 3 倍（0x10：近似 %.0f vs 真表 2192）" % approx,
      abs(approx - 2192) > 1000, f"ratio={2192/approx:.2f}x")

check("LF 零点 0x40 → 0", R.jc1_lf_amp16(0x40) == 0.0)
check("LF 满幅 0x72 → 65535", R.jc1_lf_amp16(0x72) == 65535.0)
check("LF 中间档 bit8 生效（0x140 → 超出 0）",
      R.jc1_lf_amp16(0x140) > 0, str(R.jc1_lf_amp16(0x140)))

# 单调
prev = -1
mono = True
for c in range(0x00, 0xCA, 0x02):
    cur = R.decode_jc2(R.encode_jc2(R.jc1_hf_amp16(c), 0))[0]
    if cur < prev:
        mono = False
        break
    prev = cur
check("HF 101 档编码单调不减", mono)

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 76)
print("C. 中性判定")
print("=" * 76)

check("标准中性块 [00 01 40 40] → 不震", R.is_neutral(R.JC1_NEUTRAL))
check("全零块 → 不震", R.is_neutral(bytes(4)))
check("振幅 0 但频率码不同 → 仍判不震",
      R.is_neutral(bytes((0x50, 0x00, 0x22, 0x40))))
check("真实震动块 → 在震",
      not R.is_neutral(bytes((0x74, 0x40, 0x3D, 0x50))))
# 中性块 → None（调用方据此发正式静音帧）。
# 2026-11-17 改为返回 None：这样"静音"与"有效震动"在类型层面就分开了，
# 避免把静音编码成带频率的帧（会被 LRA 当微弱驱动）。
check("中性块 → None（由调用方发静音帧）",
      R.jc1_block_to_jc2(R.JC1_NEUTRAL) is None)

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 76)
print("D. 组帧")
print("=" * 76)

f = R.build_frame(R.neutral_jc2())
check("帧长 17（reportID + 16 字节 HD payload）", len(f) == 17, str(len(f)))
check("report ID = 0x00（蓝牙）", f[0] == 0x00)
check("byte1 高 4 位 = 0x50（SDL 同款）", (f[1] & 0xF0) == 0x50)
check("载荷 5 字节落在 [2:7]", f[2:7] == R.neutral_jc2())
# 2026-11-19：一包写 3 个子帧（照 viiper/Pro2 结构），一次覆盖 3 个时间片。
# hd 模式下三个子帧内容相同；basic 模式只有第 1 个，其余留 0。
if getattr(R, "RUMBLE_MODE", "hd") == "hd":
    check("3 子帧内容一致（hd 模式）",
          f[2:7] == f[7:12] == f[12:17])
else:
    check("其余字节为 0（basic 模式）", f[7:] == bytes(10))

seqs = [(R.build_frame(R.neutral_jc2())[1] & 0x0F) for _ in range(18)]
# _seq 是进程级全局，前面的用例已推进过，所以只验证"连续 17 帧是模 16 递增"
ok_cycle = all((seqs[i] + 1) % 16 == seqs[i + 1] for i in range(17))
check("序号模 16 连续递增（跨 0xF→0x0 回绕）", ok_cycle, str(seqs[:18]))

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 76)
print("E. 发送器行为（假 client / 假 loop，不碰蓝牙）")
print("=" * 76)


class FakeClient:
    """记录写调用，不碰蓝牙。"""

    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, uuid, data, response=False):
        self.writes.append((uuid, bytes(data)))


class BrokenClient(FakeClient):
    """任何写都失败，用于验证降级。"""

    async def write_gatt_char(self, uuid, data, response=False):
        self.writes.append((uuid, bytes(data)))
        raise RuntimeError("simulated BLE write failure")


def make_sender(side, client):
    """返回已绑定 client 的发送器，写操作同步直落 FakeClient。

    注入 writer，而不是 monkeypatch `asyncio.run_coroutine_threadsafe` ——
    后者的作用域只覆盖调用点，而振动写发生在**独立线程**里，
    线程跑起来时 monkeypatch 早已恢复，结果打在真函数上、
    loop 是假的 → AttributeError: 'object' has no attribute
    'call_soon_threadsafe'，测出来"一次都没写"其实是测试环境坏了。
    """
    s = R.HdRumbleSender(side)

    def sync_writer(cl, uuid, data, loop):
        coro = cl.write_gatt_char(uuid, data, response=False)
        try:
            coro.send(None)          # 协程体只有 append，一步即结束
        except StopIteration:
            pass

    s._writer = sync_writer
    s.attach(client, object())
    return s


STRONG = bytes((0x74, 0xC8, 0x3D, 0x72))     # HF 满、LF 满
WEAK = bytes((0x74, 0x10, 0x3D, 0x48))       # 中等强度

# E1 节流：短时间灌 50 帧，写出次数被压到很少
fc = FakeClient()
s = make_sender("left", fc)
for _ in range(50):
    s.feed_block(STRONG)
time.sleep(0.06)
# MIN_INTERVAL_S=10ms，60ms 窗口理论上最多 6 次
check("节流：50 帧只写出 ≤7 次", len(fc.writes) <= 7,
      f"writes={len(fc.writes)} dropped={s.dropped}")
check("丢弃计数在涨（只保留最新一帧）", s.dropped > 30, f"dropped={s.dropped}")
check("确实写出过（>0）", len(fc.writes) >= 1, f"writes={len(fc.writes)}")
s.stop()

# E2 ★ 震动保持：相同块也要周期性重发（SDL RUMBLE_REFRESH_FREQUENCY_MS）
#
# 这是「轻弹一下 → 持续震动」的核心行为，必须验证：
#   · 主机写一次震动后，worker 应按 REFRESH_S 持续重发，马达才不停
#   · SDL 源码注释原文："How often you have to refresh a long duration
#     rumble to keep the motors running" = 50ms
fc2 = FakeClient()
s2 = make_sender("right", fc2)
s2.feed_block(STRONG)
time.sleep(0.04)
n1 = len(fc2.writes)
check("首次震动已写出", n1 >= 1, f"writes={n1}")

# 静置 200ms：期间不喂新块，全靠保持刷新
time.sleep(0.20)
n2 = len(fc2.writes)
check("★ 震动保持：静置 200ms 内持续重发（≥4 次）",
      n2 - n1 >= 4, f"{n1} -> {n2}（200ms / 12ms 约 16 次）")

# 超过 HOLD_S 后必须停（不能无限震）
time.sleep(R.HOLD_S + 0.15)
n3 = len(fc2.writes)
time.sleep(0.12)
n4 = len(fc2.writes)
check("★ 超过保持期后停止重发", n4 == n3, f"{n3} -> {n4}")

# E3 强度变化必须写出去（纯 HD 模式：振幅渐变要逐帧跟随）
#
# 2026-11-17 删除了傻震二值化/振幅阈值去重补丁 —— 那些是排查摇杆跳变时
# 的错误假说产物，把渐变震动抹成"轻弹一下"。现在恢复逐帧真实振幅。
check("不再有傻震二值化补丁", not hasattr(R, "DUMB_RUMBLE_MODE"))
check("不再有振幅阈值去重补丁", not hasattr(R, "_rumble_same"))
s2.feed_block(WEAK)
time.sleep(0.04)
check("强度变化必须写出去（HD 细腻度）",
      len(fc2.writes) > n2, f"{n2} -> {len(fc2.writes)}")

# E4 静音兜底
fc3 = FakeClient()
s3 = make_sender("left", fc3)
s3.feed_block(STRONG)
time.sleep(0.04)
before = len(fc3.writes)
time.sleep(0.40)
after = len(fc3.writes)
check("超时静音：停喂 0.40s 后自动补静音帧", after > before, f"{before} -> {after}")
check("最后一帧是静音帧",
      bool(fc3.writes) and fc3.writes[-1][1][2:7] == R.neutral_jc2(),
      fc3.writes[-1][1][2:7].hex() if fc3.writes else "-")
check("左侧写的是 GATT 0x0012 左 characteristic",
      bool(fc3.writes) and fc3.writes[-1][0] == R.UUID_RUMBLE_LEFT,
      fc3.writes[-1][0] if fc3.writes else "-")
check("右侧 UUID 与左侧不同",
      R.UUID_RUMBLE_LEFT != R.UUID_RUMBLE_RIGHT)
s2.stop()
s3.stop()

# E5 降级：HD 写一直失败 → 切到 legacy command 通道
bc = BrokenClient()
s4 = make_sender("left", bc)
for i in range(14):
    s4.feed_block(bytes((0x74, 0x40 + i, 0x3D, 0x50)))
    time.sleep(0.015)
time.sleep(0.15)
# ⚠ 2026-11-17：legacy 预置样本通道已彻底删除（照抄 Pro2 Bridge：
#   预置样本 stub 返回 NOT_SUPPORTED）。所以**不再有降级** ——
#   HD 写失败就持续失败并计数，绝不静默退化成「嗡一声」。
uuids = {u for u, _ in bc.writes}
check("HD 失败时不写 legacy UUID（该通道已删除）",
      R.HdRumbleSender.__dict__.get("LEGACY_UUID") is None,
      "LEGACY_UUID 应不存在")
check("HD 失败时仍只写 HD 通道 UUID",
      uuids <= {R.UUID_RUMBLE_LEFT, R.UUID_RUMBLE_RIGHT}, str(uuids))
check("HD 失败被计数", s4.errors > 0 or s4._hd_fail > 0,
      f"errors={s4.errors} hd_fail={s4._hd_fail}")
s4.stop()

# E7 enabled=False 时完全静默
fc5 = FakeClient()
s5 = make_sender("left", fc5)
s5.enabled = False
s5.feed_block(STRONG)
time.sleep(0.04)
check("enabled=False 时完全静默", len(fc5.writes) == 0, str(len(fc5.writes)))
s5.stop()


# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 76)
print("F. 源码接线（防止被改回去）")
print("=" * 76)

vj_src = (ROOT / "virtual" / "vjoy_out.py").read_text(encoding="utf-8")
check("vjoy_out 有 _make_rumble_cb", "_make_rumble_cb" in vj_src)
check("vjoy_out 调 get_sender().feed_block", "feed_block" in vj_src)
assigns = [ln for ln in vj_src.splitlines()
           if ln.strip().startswith("hid.rumble_cb =")]
check("两处 rumble_cb 赋值都走新回调",
      len(assigns) == 2 and all("_make_rumble_cb" in ln for ln in assigns),
      str(assigns))
code_lines = [ln for ln in vj_src.splitlines()
              if "min(255, blk[1])" in ln and not ln.lstrip().startswith("#")]
# docstring / 注释里引用旧实现是允许的（说明性），只要没有活的代码行
in_docstring = "min(255, blk[1])" in vj_src
live = [ln for ln in code_lines if "small =" in ln or "large =" in ln]
check("旧二值化只剩说明性引用，没有活代码",
      not live, str(live) if live else "(描述保留，代码已删)")
# ⚠ 2026-11-17：legacy 回调整段已删除（照抄 Pro2 Bridge 的
#   预置样本 stub = NOT_SUPPORTED）。这里改为断言它**确实不存在**。
check("legacy 回调已被彻底删除（不再调用 _vibration_cb）",
      "legacy_cb" not in vj_src)

cmd_src = (ROOT / "controller_command.py").read_text(encoding="utf-8")
check("存在 JOY2_SET_FEATURE_MASK（0x0c subcmd 02, 掩码 0x27）",
      "JOY2_SET_FEATURE_MASK" in cmd_src and "0c9101020004000027000000" in cmd_src)
check("存在 JOY2_ENABLE_FEATURES（0x0c subcmd 04, 掩码 0x27）",
      "JOY2_ENABLE_FEATURES" in cmd_src and "0c9101040004000027000000" in cmd_src)

main_src = (ROOT / "main.py").read_text(encoding="utf-8")
i_mask = main_src.find("JOY2_SET_FEATURE_MASK")
i_vib = main_src.find("JOY2_CONNECTED_VIBRATION")
check("main.py 在发震动之前先开功能位",
      0 < i_mask < i_vib, f"mask@{i_mask} vib@{i_vib}")
check("功能位用 send_command（非致命），不用 send_required",
      'send_command(client, "JOY2_SET_FEATURE_MASK")' in main_src)

gui_src = (ROOT / "gui.py").read_text(encoding="utf-8")
check("GUI 开关已接 HD 通道", "rumble_hd import set_enabled" in gui_src)

duo_src = (ROOT / "control_type" / "duo_joycon.py").read_text(encoding="utf-8")
check("duo_joycon 连接时 attach_client", "attach_client" in duo_src)
check("duo_joycon 断开时 detach_client", "detach_client" in duo_src)

single_src = (ROOT / "control_type" / "single_joycon.py").read_text(encoding="utf-8")
check("single_joycon 连接时 attach_client", "attach_client" in single_src)

# 签名一致性：hid_function 调用 rumble_cb 的方式必须是 2 参数
hid_src = (ROOT / "virtual" / "hid_function.py").read_text(encoding="utf-8")
check("hid_function 以 2 参数调用 rumble_cb（left, right）",
      "self.rumble_cb(bytes(data[2:6]), bytes(data[6:10]))" in hid_src)
check("hid 层在 0x01/0x10 上取震动块",
      "rid in (0x01, 0x10)" in hid_src)

# ══════════════════════════════════════════════════════════════════════════ #
print()
print("=" * 76)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for n in FAIL:
        print(f"  ✗ {n}")
    print("=" * 76)
    sys.exit(1)
print("全部通过")
print("=" * 76)
