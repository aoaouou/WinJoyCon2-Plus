# -*- coding: utf-8 -*-
"""验证 hidmaestro_out 后端：建设备 → 推状态 → SDL 应读到数据。"""
import sys, time, subprocess
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\Games\Nintendo\tool\Joycon2-hidmaestro\_src")

from virtual.hidmaestro_out import HidMaestroJoyCon2
from virtual.reports import Ns2Bit

# 清理
for n in ("HmBridge.exe",):
    subprocess.run(["taskkill", "/F", "/IM", n], capture_output=True, creationflags=0x08000000)
time.sleep(2)
sys.path.insert(0, r"D:\Games\Nintendo\tool\Joycon2-hidmaestro\_src")
import device_cleanup
device_cleanup.remove_ghosts_elevated()

print("创建 HidMaestroJoyCon2…")
jc = HidMaestroJoyCon2(side="both")
print("started =", jc._started)

# L: A + ZL + 摇杆偏移；R: B + X + ZR
jc.set_buttons(left_bits=Ns2Bit.A | Ns2Bit.ZL, right_bits=Ns2Bit.B | Ns2Bit.X | Ns2Bit.ZR)
jc.set_stick("left", 3000, 1200)
jc.set_stick("right", 1200, 3000)

print("持续 update 60 秒（可并行跑 SDL 扫描）…")
end = time.time() + 60
while time.time() < end:
    jc.update()
    time.sleep(0.015)

jc.close()
print("done")
