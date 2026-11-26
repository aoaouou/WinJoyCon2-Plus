import sys
import platform
import os
import ctypes
import struct

STICK_CENTER = 2048    # 12 位摇杆中位



def _unpack_stick12(buf) -> tuple:
    """12 位打包摇杆 -> (x, y) 原始值。

    格式（与 virtual/reports.py 的 _unpack_stick12 一致）：
        x = b0 | ((b1 & 0x0F) << 8)
        y = (b1 >> 4) | (b2 << 4)
    """
    if buf is None or len(buf) < 3:
        return STICK_CENTER, STICK_CENTER
    b0, b1, b2 = buf[0], buf[1], buf[2]
    return (b0 | ((b1 & 0x0F) << 8)), ((b1 >> 4) | (b2 << 4))


class JoyConLeft:
    def __init__(self):
        self.name = "Joy-Con"
        self.side = "Left"
        self.mac_address = ""
        
        self.buttons = {
            #these buttons is mapped to Upright usage (it need to invert the mapping for a sideways usage)
            "ZL": False,
            "L": False,
            "Minus": False,
            "SLL": False,
            "SRL": False,
            "GLL": False,   # 充电握把 GL（0x05 buttons byte3 = datas[7] bit1）
            "GRL": False,   # 充电握把 GR（0x05 buttons byte3 = datas[7] bit0）
            "Left": False,
            "Down": False,
            "Up": False,
            "Right": False,
            "LS": False,
            "Capture": False,
        }
        self.analog_stick = {
            #these values is mapped to Upright usage (it need to invert the mapping for a sideways usage)
            "X": 0,
            "Y": 0
        }

        self.accelerometer = {
            "X": 0.0,
            "Y": 0.0,
            "Z": 0.0,
        }
        
        self.gyroscope = {
            "X": 0.0, # Pitch
            "Y": 0.0, # Roll
            "Z": 0.0, # Yaw
        }

        self.mouse = {
            "X": 0.0,
            "Y": 0.0,
            "distance": "0C"
        }

        self.mouseBtn = {
            "Left": False,     # 鼠标左键 = L
            "Right": False,    # 鼠标右键 = ZL
            "middle": False,   # 鼠标中键 = 截图(Capture)
            "forward": False,  # 侧键2(前进) = 十字上 或 十字左
            "back": False,     # 侧键1(后退) = 十字下 或 十字右
            "scrollX": 0.0,
            "scrollY": 0.0,
        }

        self.timestamp = bytes.fromhex("00000000") 
        self.motionTimestamp = bytes.fromhex("00000000")
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
        # 实抓 63 字节帧（12:56:35）：
        #   9b 26 00 00 00 00 00 e0 ff 0f fc 97 87 ff f7 7f ...
        #                        [10:13]=fc 97 87 → (2044, 2169)  ← 摇杆
        #
        #   [4][5][6] 恒为 00（固定填充，不是摇杆！）
        #   [10:13] 稳定在 (2044,2169)，与标定 center=(2034,2151) 吻合
        #
        # ⚠ 教训：曾按 s2r_bluetooth_interface.md 的「0x5」改成 datas[5:8]，
        #   结果读到 (0, 3584) —— [4][5][6] 是常量 0，那是固定填充。
        #   该文档的 0x5 是**子命令响应**布局，不适用于主动通知帧。
        #   以真机帧为准：Left = 0x0A(10)。
        # ═══ 字段偏移统一由 virtual/jc2_frame.py 提供 ═══
        #
        # 2026-11-17 重做：以前这里自己维护一套偏移，而 virtual/reports.py
        # 里还有另一套（parse_report，实测零引用），两边互相矛盾导致
        # 「改了没效果」。现在偏移只在 jc2_frame 定义一次。
        from virtual.jc2_frame import parse_frame
        _fr = parse_frame(datas)
        if not _fr.valid:
            return
        self.frame = _fr
        # 旧字段保留给鼠标/滚动等遗留代码用
        btnDatas = (datas[5] << 8 | datas[6]) if len(datas) > 6 else 0
        JoystickDatas = datas[10:13] if len(datas) >= 13 else b"\x00\x01\x40"
        mouseDatas = datas[16:24] if len(datas) >= 24 else bytes(8)

        self.mouse["X"], self.mouse["Y"] = struct.unpack("<hh", mouseDatas[:4])
        self.mouse["distance"] = mouseDatas[7:8].hex()

        self.timestamp = bytes.fromhex(datas[0:4].hex())

        if len(datas) >= 0x3C:
            # 纯原始值，不做任何轴向变换。
            # 量纲换算（gyro 14.247->16.4）统一在 virtual/imu_proc.py 的 imu() 里做。
            a = struct.unpack("<3h", datas[0x30:0x36])
            g = struct.unpack("<3h", datas[0x36:0x3C])
            self.imu_raw = (a[0], a[1], a[2], g[0], g[1], g[2])

        self.buttons["SLL"] = bool(btnDatas & 0x0020)
        self.buttons["SRL"] = bool(btnDatas & 0x0010)
        # 充电握把背键在 0x05 通用报告的 buttons byte3 = datas[7]：bit1=GL、bit0=GR
        self.buttons["GLL"] = bool(len(datas) > 7 and (datas[7] & 0x02))
        self.buttons["GRL"] = bool(len(datas) > 7 and (datas[7] & 0x01))
        self.buttons["Minus"] = bool(btnDatas & 0x0100)
        self.buttons["L"] = bool(btnDatas & 0x0040)
        self.buttons["ZL"] = bool(btnDatas & 0x0080)
        self.buttons["Left"] = bool(btnDatas & 0x0008)
        self.buttons["Down"] = bool(btnDatas & 0x0001)
        self.buttons["Up"] = bool(btnDatas & 0x0002)
        self.buttons["Right"] = bool(btnDatas & 0x0004)
        self.buttons["LS"] = bool(btnDatas & 0x0800)
        self.buttons["Capture"] = bool(btnDatas & 0x2000)

        # 摇杆：从统一解析层取**按侧**的值
        # （单只 Joy-Con 帧里两个字段都在，另一侧是占位 —— 见 jc2_frame）
        from virtual.jc2_frame import stick_for_side
        self.stick_raw = stick_for_side(_fr, "left")
        self.analog_stick["X"], self.analog_stick["Y"] = self.stick_raw

        self.mouseBtn["Left"] = bool(btnDatas & 0x0040) #L → 鼠标左键
        self.mouseBtn["Right"] = bool(btnDatas & 0x0080) #ZL → 鼠标右键
        # 鼠标中键 = 截图键；侧键2(前进)=十字上/左；侧键1(后退)=十字下/右
        self.mouseBtn["middle"] = self.buttons["Capture"]
        self.mouseBtn["forward"] = self.buttons["Up"] or self.buttons["Left"]
        self.mouseBtn["back"] = self.buttons["Down"] or self.buttons["Right"]
        from virtual.scroll import scroll_from_raw
        rx_s, ry_s = self.stick_raw
        self.mouseBtn["scrollX"], self.mouseBtn["scrollY"] = scroll_from_raw(rx_s, ry_s)

        self.is_connected = True

    def print_status(self, datas):
        sys.stdout.write(f"\033[2;0H")
        print(f"JoyCon Left Status:")
        print(f"  Buttons: {self.buttons}                    ")
        print(f"  Analog Stick: {self.analog_stick}                    ")
        #print(f"  Accelerometer: {self.accelerometer}")
        #print(f"  Gyroscope: {self.gyroscope}")
        print(f"  Battery Level: {self.battery_level}%                    ")
        print(f"  Connected: {self.is_connected}                    ")
        #print(f"  Datas received: " + str(datas.hex()))

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
