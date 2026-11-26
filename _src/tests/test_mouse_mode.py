# -*- coding: utf-8 -*-
"""输入模式引擎纯逻辑验收 —— 不构造任何虚拟设备、不碰 USBIP（铁律5/6）。

覆盖：三态模式 / C 组合键 / keymap / 还原默认 / 挡位 / 滚轮曲线 / 亚格平滑 /
陀螺仪光标 / 宏录制回放。全部纯内存逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import control_type.mouse_mode as mm  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def feed(pair, c=0, l=0, zl=0, r=0, zr=0, sll=0, srl=0, slr=0, srr=0,
         gl=0, gr=0):
    return mm.feed_combo(pair, c, l, zl, r, zr, sll, srl, slr, srr,
                         gl, gr)


print("=" * 78)
print("A. 三态模式默认")
print("=" * 78)
mm.reset_pair(1)
check("左默认 gamepad", mm.get_mode(1, "Left") == mm.MODE_GAMEPAD)
check("右默认 gamepad", mm.get_mode(1, "Right") == mm.MODE_GAMEPAD)
check("默认不在指针模式", not mm.is_in_pointer_mode(1, "Left"))

print()
print("=" * 78)
print("B. C 组合键切换四模式 + 单 C 复位")
print("=" * 78)
check("C+L→左鼠标", feed(1, 1, l=1) == "left_mouse" and mm.get_mode(1, "Left") == mm.MODE_MOUSE)
check("C+ZL→左陀螺", feed(1, 0) == "" and feed(1, 1, zl=1) == "left_gyro"
      and mm.get_mode(1, "Left") == mm.MODE_GYRO)
check("C+R→右鼠标", feed(1, 0) == "" and feed(1, 1, r=1) == "right_mouse"
      and mm.get_mode(1, "Right") == mm.MODE_MOUSE)
check("C+ZR→右陀螺", feed(1, 0) == "" and feed(1, 1, zr=1) == "right_gyro"
      and mm.get_mode(1, "Right") == mm.MODE_GYRO)
# 单C短按不复位（长按2秒才复位）
check("单C短按不复位", feed(1, 0) == "" and feed(1, 1) == ""
      and mm.get_mode(1, "Right") == mm.MODE_GYRO)
# 模拟长按：把 C 按下时刻往前拨 3 秒
mm._combo_prev[1]["c_down_at"] -= 3.0
check("长按C→全复位", feed(1, 1) == "reset"
      and mm.get_mode(1, "Left") == mm.MODE_GAMEPAD
      and mm.get_mode(1, "Right") == mm.MODE_GAMEPAD)
# 长按触发只一次
check("长按只触发一次", feed(1, 1) == "")
# 组合键=切换开关：reset 后第一次开启，再次触发关闭
check("C+L开启", feed(1, 0) == "" and feed(1, 1, l=1) == "left_mouse"
      and mm.get_mode(1, "Left") == mm.MODE_MOUSE)
check("C+L再按→回手柄", feed(1, 0) == "" and feed(1, 1, l=1) == "left_mouse_off"
      and mm.get_mode(1, "Left") == mm.MODE_GAMEPAD)
check("C+L三次→再开", feed(1, 0) == "" and feed(1, 1, l=1) == "left_mouse"
      and mm.get_mode(1, "Left") == mm.MODE_MOUSE)
# 组合键消费标记：mark 后修饰键被标记，clear 后清除（防进模式误触点击）
mm.mark_consumed(1, "left_mouse")
check("组合键消费L", mm.is_consumed(1, "L") and not mm.is_consumed(1, "R"))
mm.clear_consumed(1)
check("清除消费", not mm.is_consumed(1, "L"))
# 托盘批量切换全部手柄模式
mm.set_all_mode(mm.MODE_GYRO, pair_count=4, persist=False)
check("托盘全切陀螺仪", all(mm.get_mode(p, s) == mm.MODE_GYRO
                          for p in range(4) for s in ("Left", "Right")))
mm.set_all_mode(mm.MODE_GAMEPAD, pair_count=4, persist=False)
check("托盘全切手柄", all(mm.get_mode(p, s) == mm.MODE_GAMEPAD
                        for p in range(4) for s in ("Left", "Right")))

print()
print("=" * 78)
print("C. C+SL/SR 触发宏")
print("=" * 78)
check("C+SLR→macro_slr", feed(1, 0) == "" and feed(1, 1, slr=1) == "macro_slr")
check("C+SLL→macro_sll", feed(1, 0) == "" and feed(1, 1, sll=1) == "macro_sll")
# 充电握把 GL/GR 只触发宏，不切换模式：触发后无需再按一次复位
check("C+GL→macro_gl", feed(1, 0) == "" and feed(1, 1, gl=1) == "macro_gl")
check("C+GR→macro_gr", feed(1, 0) == "" and feed(1, 1, gr=1) == "macro_gr")

print()
print("=" * 78)
print("D. keymap 默认 / 自定义 / 还原")
print("=" * 78)
km = mm.get_keymap(1, mm.MODE_MOUSE)
check("默认 L=左键", km.get("L") == mm.ACT_LEFT)
check("默认 ZL=右键", km.get("ZL") == mm.ACT_RIGHT)
check("默认 X=前进", km.get("X") == mm.ACT_FWD)
check("默认 LS=回中心", km.get("LS") == mm.ACT_CENTER and km.get("RS") == mm.ACT_CENTER)
check("陀螺仪默认同款", mm.get_keymap(1, mm.MODE_GYRO).get("Capture") == mm.ACT_MIDDLE)
km2 = dict(km)
km2["A"] = mm.ACT_MIDDLE
mm.set_keymap(1, mm.MODE_MOUSE, km2, persist=False)
check("自定义生效", mm.get_keymap(1, mm.MODE_MOUSE).get("A") == mm.ACT_MIDDLE)
mm.reset_keymap(1, persist=False)
check("还原默认", mm.get_keymap(1, mm.MODE_MOUSE).get("A") == mm.ACT_FWD)

print()
print("=" * 78)
print("E. 灵敏度挡位")
print("=" * 78)
mm.get_config(1)["mouse_dpi_index"] = 1
check("默认第2挡(现1.0x)", mm.get_dpi_index(1) == 1 and mm.get_dpi_scale(1) == 1.0)
check("1挡=0.5x(整体降一档)", mm.DPI_LEVELS[0] == (400, 0.5))
check("4挡=4.0x", mm.DPI_LEVELS[3] == (3200, 4.0))
# 双柄：升到底停住
mm._dpi_prev.pop(1, None)
for _ in range(5):
    mm.feed_dpi_keys(1, True, False, both_in_pointer=True)
    mm.feed_dpi_keys(1, False, False, both_in_pointer=True)
check("双柄升到底=4挡", mm.get_dpi_index(1) == 3, f"idx={mm.get_dpi_index(1)}")
mm.feed_dpi_keys(1, False, True, both_in_pointer=True)
mm.feed_dpi_keys(1, False, False, both_in_pointer=True)
check("双柄降一挡", mm.get_dpi_index(1) == 2)
# 单柄：升到顶循环
mm._dpi_prev.pop(1, None)
mm.get_config(1)["mouse_dpi_index"] = 3
mm.feed_dpi_keys(1, True, False, both_in_pointer=False)
mm.feed_dpi_keys(1, False, False, both_in_pointer=False)
check("单柄到顶循环回1挡", mm.get_dpi_index(1) == 0)
check("挡位标签", "DPI" in mm.get_dpi_label(1))

print()
print("=" * 78)
print("F. 滚轮：方向 / 力度曲线 / 亚格平滑")
print("=" * 78)
C = 2048
check("R前(y+)与右(x+)同向",
      mm.wheel_direction("Right", C, C + 700) == mm.wheel_direction("Right", C + 700, C))
check("R后(y-)与左(x-)同向",
      mm.wheel_direction("Right", C, C - 700) == mm.wheel_direction("Right", C - 700, C))
check("L前(y+)与左(x-)同上",
      mm.wheel_direction("Left", C, C + 700) == mm.wheel_direction("Left", C - 700, C) == 1)
d_light = abs(mm.wheel_delta("Right", C, C + 300))
d_full = abs(mm.wheel_delta("Right", C, C + 1000))
check("满推=1.0", abs(d_full - 1.0) < 0.01)
check("轻推被压低", d_light < 0.1, f"light={d_light:.3f}")
out, _ = mm.accumulate_wheel(0.0, 0.3)
check("亚格浮点滚动", 0 < out < 1 and int(out * 120) < 120, f"md={int(out*120)}")
s0, acc0 = mm.accumulate_wheel(0.0, 0.01)   # 极小力攒着不发
check("阈值下发", s0 == 0 and acc0 > 0)

print()
print("=" * 78)
print("G. 陀螺仪光标")
print("=" * 78)
mm.get_config(1)["gyro_scale"] = 1.0
mm.get_config(1)["gyro_invert_x"] = False
mm.get_config(1)["gyro_invert_y"] = False
mm.get_config(1)["mouse_dpi_index"] = 1
# imu_raw=(ax,ay,az,gx,gy,gz)；gz(yaw)→水平，gx(pitch)→垂直
h, v = mm.gyro_cursor_delta("Right", (0, 0, 0, 0, 0, 1000), 1)
check("陀螺gz→水平非零", abs(h) > 0, f"h={h:.1f}")
check("仅gz时垂直为0", abs(v) < 0.01)
hv, vv = mm.gyro_cursor_delta("Right", (0, 0, 0, 1000, 0, 0), 1)
check("陀螺gx→垂直非零", abs(vv) > 0, f"v={vv:.1f}")
# ★ 最终定案：左右手方向完全一致（不做镜像）
check("左右手水平相同", mm.gyro_cursor_delta("Left", (0, 0, 0, 0, 0, 1000), 1)[0] == h)
check("左右手垂直相同", mm.gyro_cursor_delta("Left", (0, 0, 0, 1000, 0, 0), 1)[1] == vv)
check("静止死区", mm.gyro_cursor_delta("Right", (0, 0, 0, 0, 0, 0), 1) == (0.0, 0.0))
check("灵敏度范围合理(1000LSB: 10~35px/帧)", 10 < abs(h) < 35, f"h={abs(h):.1f}")

print()
print("=" * 78)
print("H. 宏录制/回放")
print("=" * 78)
mm.start_macro_record(1, trigger="m1")
mm.record_macro_step(1, mm.ACT_LEFT)
mm.record_macro_step(1, mm.ACT_MIDDLE)
name = mm.stop_macro_record(1, name="m1", persist=False)
check("宏保存", name == "m1" and mm.get_config(1)["macros"]["m1"] == [mm.ACT_LEFT, mm.ACT_MIDDLE])
check("宏默认关闭", mm.is_macro_enabled(1) is False)
mm.set_option(1, "macro_enabled", True, persist=False)
check("宏可开启", mm.is_macro_enabled(1) is True)

print()
print("=" * 78)
print(f"结果: {len(PASS)} PASS / {len(FAIL)} FAIL")
print("=" * 78)
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
