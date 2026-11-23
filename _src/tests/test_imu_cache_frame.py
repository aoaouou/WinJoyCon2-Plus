# -*- coding: utf-8 -*-
"""回归：模拟器兼容模式下缓存帧的 gyro 处理（Ryujinx 保留 / Eden 清零）。"""
import sys, os, struct, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  [PASS] {name}")
    else:
        failed += 1; print(f"  [FAIL] {name} {extra}")

from virtual import descriptors as D
from virtual.hid_function import Switch1HidFunction
from virtual.reports import PadState
from virtual.imu_proc import set_imu_compat_mode, get_imu_compat_mode

def gyros(payload):
    return [struct.unpack("<h", payload[13 + i*12 + 6:13 + i*12 + 8])[0]
            for i in range(3)]

def accels(payload):
    return [struct.unpack("<h", payload[13 + i*12:13 + i*12 + 2])[0]
            for i in range(3)]

def make_h():
    h = Switch1HidFunction(D.DEVICES["joyconL"], "joyconL")
    h.input_mode = 0x30
    st = PadState()
    st.gyro = (1000, -2000, 3000)
    h.set_state(st)
    return h

print("=" * 70)
print("模拟器兼容模式：缓存帧 gyro 处理")
print("=" * 70)

# ── Ryujinx 模式（默认）：缓存帧原样带 gyro ──
set_imu_compat_mode("ryujinx", persist=False)
h = make_h()
fresh = h.pending_in(1)
check("Ryujinx 新帧 gyro 非零", any(v != 0 for v in gyros(fresh)))
cached = h.pending_in(1)   # 立刻再取，命中缓存
check("Ryujinx 缓存帧 gyro 保留（非 None）", cached is not None)
check("Ryujinx 缓存帧 gyro 仍带真值", any(v != 0 for v in gyros(cached)),
      f"gyro={gyros(cached)}")

# ── Eden 模式：缓存帧 gyro 清零 ──
set_imu_compat_mode("eden", persist=False)
h = make_h()
fresh = h.pending_in(1)
check("Eden 新帧 gyro 非零", any(v != 0 for v in gyros(fresh)))
a_fresh = accels(fresh)
cached = h.pending_in(1)
check("Eden 缓存帧存在", cached is not None)
check("Eden 缓存帧 gyro 全为 0", all(v == 0 for v in gyros(cached)),
      f"gyro={gyros(cached)}")
check("Eden 缓存帧 accel 保留", accels(cached) == a_fresh)
check("Eden 缓存帧 report_id 保留", cached[0] == 0x30)

# ── 热切换：运行时改模式立即生效，无需重建对象 ──
check("模式确为 eden", get_imu_compat_mode() == "eden")
set_imu_compat_mode("ryujinx", persist=False)
h2 = make_h()
h2.pending_in(1)
c2 = h2.pending_in(1)
check("热切换到 ryujinx 后缓存帧 gyro 恢复", any(v != 0 for v in gyros(c2)),
      f"gyro={gyros(c2)}")

print("=" * 70)
print(f"结果: {passed} PASS / {failed} FAIL")
print("=" * 70)
sys.exit(1 if failed else 0)
