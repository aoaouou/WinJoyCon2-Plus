import sys
import platform
import os
import ctypes
import struct

STICK_CENTER = 2048    # 12 位摇杆中位



def _unpack_stick12(buf) -> tuple:
    """12 位打包摇杆 -> (x, y) 原始值。格式同 JoyconL。"""
    if buf is None or len(buf) < 3:
        return STICK_CENTER, STICK_CENTER
    b0, b1, b2 = buf[0], buf[1], buf[2]
    return (b0 | ((b1 & 0x0F) << 8)), ((b1 >> 4) | (b2 << 4))


class JoyConRight:
    def __init__(self):
        self.name = "Joy-Con"
        self.side = "Right"
        self.mac_address = ""

        self.buttons = {
            #these buttons is mapped to Upright usage (it need to invert the mapping for a sideways usage)
            "ZR": False,
            "R": False,
            "Plus": False,
            "SLR": False,
            "SRR": False,
            "GLR": False,   # 充电握把 GL（0x05 buttons byte3 = datas[7] bit1）
            "GRR": False,   # 充电握把 GR（0x05 buttons byte3 = datas[7] bit0）
            "Y": False,
            "B": False,
            "X": False,
            "A": False,
            "RS": False,
            "Home": False,
            "GameChat": False,
        }

        self.analog_stick = {
            #these values is mapped to Upright usage (it need to invert the mapping for a sideways usage)
            "X": 0,
            "Y": 0
        }

        # I hope i can implement this later with HID
        self.accelerometer = {
            "X": 0.0,
            "Y": 0.0,
            "Z": 0.0,
        }

        # I hope i can implement this later with HID
        self.gyroscope = {
            "X": 0.0, # Roll
            "Y": 0.0, # Pitch
            "Z": 0.0, # Yaw
        }

        self.mouse = {
            "X": 0.0,
            "Y": 0.0,
            "distance": "0C"
        }

        self.mouseBtn = {
            "Left": False,     # 鼠标左键 = R
            "Right": False,    # 鼠标右键 = ZR
            "middle": False,   # 鼠标中键 = HOME
            "forward": False,  # 侧键2(前进) = X 或 A
            "back": False,     # 侧键1(后退) = Y 或 B
            "scrollX": 0.0,
            "scrollY": 0.0,
        }

        self.timestamp = bytes.fromhex("00000000") 
        self.motionTimestamp = bytes.fromhex("00000000")  # Placeholder for motion timestamp
        # Battery is queried through the dedicated command-response channel.
        self.battery_level = None
        self.alertSent = False
        self.is_connected = False

    async def update(self, datas):
        # Button/stick/mouse fields end at byte 23.  IMU fields are optional
        # and only occupy the final 12 bytes of the 60-byte report.
        if len(datas) < 24:
            print(f"[WARNING] Data too short: {len(datas)} bytes (expected at least 24)")
            return
        
        # ═══ JC2 BLE 帧字段偏移（2026-11-17 用真机帧验证）═══
        #
        # 实抓 63 字节帧：
        #   df 29 00 00 00 00 00 e0 ff 0f ff f7 7f bd 27 7c ...
        #                            [13:16]=bd 27 7c → (1981, 1986) ← 摇杆
        #
        #   与标定 center=(1995,1986) 吻合。
        # ⚠ 与 Left 一样：不要用文档的 0x8，那里是固定填充。
        # 字段偏移统一由 virtual/jc2_frame.py 提供（详见 JoyconL 说明）
        from virtual.jc2_frame import parse_frame
        _fr = parse_frame(datas)
        if not _fr.valid:
            return
        self.frame = _fr
        btnDatas = (datas[4] << 8 | datas[5]) if len(datas) > 5 else 0
        JoystickDatas = datas[13:16] if len(datas) >= 16 else b"\xff\xf7\x7f"
        mouseDatas = datas[16:24] if len(datas) >= 24 else bytes(8)

        self.mouse["X"], self.mouse["Y"] = struct.unpack("<hh", mouseDatas[:4])
        self.mouse["distance"] = mouseDatas[7:8].hex()

        #print(f"JoyCon Right Datas: {mouseDatas.hex()}, Mouse X: {self.mouse['X']}, Mouse Y: {self.mouse['Y']}, Mouse Distance: {self.mouse['distance']}")

        self.timestamp = bytes.fromhex(datas[0:4].hex())

        if len(datas) >= 0x3C:
            # 纯原始值，不做任何轴向变换、不取负。
            # 量纲换算（gyro 14.247->16.4）统一在 virtual/imu_proc.py 的 imu() 里做。
            a = struct.unpack("<3h", datas[0x30:0x36])
            g = struct.unpack("<3h", datas[0x36:0x3C])
            self.imu_raw = (a[0], a[1], a[2], g[0], g[1], g[2])


        self.buttons["ZR"] = bool(btnDatas & 0x8000)
        self.buttons["R"] = bool(btnDatas & 0x4000)
        self.buttons["Plus"] = bool(btnDatas & 0x0002)
        self.buttons["SLR"] = bool(btnDatas & 0x2000)
        self.buttons["SRR"] = bool(btnDatas & 0x1000)
        # 充电握把背键在 0x05 通用报告的 buttons byte3 = datas[7]：bit1=GL、bit0=GR
        self.buttons["GLR"] = bool(len(datas) > 7 and (datas[7] & 0x02))
        self.buttons["GRR"] = bool(len(datas) > 7 and (datas[7] & 0x01))
        self.buttons["Y"] = bool(btnDatas & 0x0100)
        self.buttons["B"] = bool(btnDatas & 0x0400)
        self.buttons["X"] = bool(btnDatas & 0x0200)
        self.buttons["A"] = bool(btnDatas & 0x0800)
        self.buttons["RS"] = bool(btnDatas & 0x0004)
        self.buttons["Home"] = bool(btnDatas & 0x0010)
        self.buttons["GameChat"] = bool(btnDatas & 0x0040)

        # 摇杆：JC2 原始 12 位直接透传，仅支持垂直方向（无换轴）。
        from virtual.jc2_frame import stick_for_side
        self.stick_raw = stick_for_side(_fr, "right")
        self.analog_stick["X"], self.analog_stick["Y"] = self.stick_raw

        self.mouseBtn["Left"] = bool(btnDatas & 0x4000) #R → 鼠标左键
        self.mouseBtn["Right"] = bool(btnDatas & 0x8000) #ZR → 鼠标右键
        # 鼠标中键 = HOME；侧键2(前进)=X/A；侧键1(后退)=Y/B
        self.mouseBtn["middle"] = self.buttons["Home"]
        self.mouseBtn["forward"] = self.buttons["X"] or self.buttons["A"]
        self.mouseBtn["back"] = self.buttons["Y"] or self.buttons["B"]
        from virtual.scroll import scroll_from_raw
        rx_s, ry_s = self.stick_raw
        self.mouseBtn["scrollX"], self.mouseBtn["scrollY"] = scroll_from_raw(rx_s, ry_s)

        #print(f"{self.mouseBtn['scrollX']}, {self.mouseBtn['scrollY']}")

        self.is_connected = True

    def setMacAddress(self, mac_address):
        self.mac_address = mac_address

    def notify_low_battery(self):
        msg = f"{self.name} {self.side} : low battery ({self.battery_level}%)"

        if platform.system() == "Windows":
            import threading
            # Run MessageBox in a separate thread to avoid blocking the
            # BLE notification/event-loop thread that processes input.
            threading.Thread(
                target=ctypes.windll.user32.MessageBoxW,
                args=(0, msg, "Alert Joy-Con", 0),
                daemon=True
            ).start()
        elif platform.system() == "Linux":
            os.system(f'notify-send "Alert Joy-Con" "{msg}"')
        else:
            print(f"[Alert] {msg}")
# 摇杆 12 位解包见文件顶部 _unpack_stick12()。
# 旧的 joystick_decoder / scroll_decoder 已删除：
#   * 它们用硬编码 MIN/MAX(780/3260, 820/3250) 压缩行程 ->
#     静止时凭空产生 +44/+20 LSB 偏移（回中不准的直接原因）
#   * 行程上下不对称（X 差 55 LSB, Y 差 25 LSB）-> 圆度偏
#   * 摇杆现在走原生透传，校准由主机负责，这里不做第二次映射
