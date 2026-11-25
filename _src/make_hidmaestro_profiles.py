# -*- coding: utf-8 -*-
"""生成 HIDMaestro 的 Joy-Con 2 profile（左右各一份）。

一手依据
--------
1. HID 报告描述符（真机 100 字节）：
   sessions/2026-11-12_.../ref/switch2_research/02-USB描述符/descriptors.md
   「Joy-Con 2 (L)」的 HID Report Descriptor 原文；R 侧仅 Report ID 7→8 不同。
   描述符里 0x05 是 63 字节 vendor 报告，0x07/0x08 声明 16 个 Button usage
   与一组 12bit 的 X/Y，0x01 是 63 字节输出报告。
2. 报告布局与按钮位表：
   .../01-协议文档/hid_reports.md
   0x05 共通报告：counter@0x0(4B) buttons@0x4(4B) 左摇杆@0xA(3B) 右摇杆@0xD(3B)
   Motion@0x2A；Button Format 表给出 4 字节按钮位序。
   0x07（L）/0x08（R）：counter@0x0(1B) power@0x1 buttons@0x2(2B) stick@0x5(3B)。
3. SDL3 的 switch2 驱动（SDL_hidapi_switch2.c）：
   按 PID 分发（2067→HandleMiniControllerStateL、2066→…R），**不看 report ID**，
   读 data[6]/data[7] 的按钮位与 data[11..13] 的左摇杆；
   陀螺仪读 data[0x2B] 的时间戳与 data[0x31..0x3C] 的 accel/gyro
   （HandleSwitchProState 段的 accel_scale = g*8/INT16_MAX、gyro_coeff 34.8）。
   data[11:14] 与真机 0x05 的左摇杆位置一致，data[0x2B:] 与真机 0x05 的
   Motion Data 起点一致 —— 故 SDL 读的是 0x05 报告。
4. HIDMaestro profile 机制：profiles/schema.json 与
   profiles/nintendo/switch2-pro-composite.json（stateBlock + inputReports 的
   program：const / counter / copy / bits / pack12 / when）。

两条消费路径的分工
----------------
· SDL3（Canary / Steam）读 0x05：按钮位取 data[6]/data[7]，摇杆取 data[11:14]，
  IMU 取 data[0x2B:]。
· 浏览器 Gamepad API / DirectInput / Windows GameInput 读 0x07/0x08：
  按描述符里的 Button usage 与 X/Y 解析，字节位置是 data[3:5] 与 data[6:9]。

所以 stateBlock 里放两套按钮位图，各 2 字节：
  byte 0-1：0x05 用（SDL 读的 data[6]/data[7] 位序）
  byte 2-3：0x07/0x08 用（真机 Button Format 位序）
"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hidmaestro_profiles")

# ---- 真机 Joy-Con 2 的 100 字节 HID 报告描述符（descriptors.md 原文）----
_RD_HEAD = (
    "05010905a101"                       # Usage Page GD / Usage Game Pad / Collection App
    "8505"                               # Report ID (5)
    "05ff0901" "1500" "26ff00"           # Usage Page FF / Usage 01 / Min 0 / Max 255
    "953f" "7508" "8102"                 # Count 63 / Size 8 / Input
    "8507"                               # Report ID (7) ← R 侧 8508
    "0901" "9502" "8102"                 # Usage 01 / Count 2 / Input
    "0509" "1901" "2910" "2501"          # Button page / Min 1 / Max 16 / LogicalMax 1
    "9510" "7501" "8102"                 # Count 16 / Size 1 / Input
    "05ff0901" "26ff00" "9501" "7508" "8102"     # FF/01 Max255 Count1 Size8 Input
    "0501" "0901" "a100"                 # GD / Pointer / Collection Physical
    "0930" "0931" "26ff0f" "9502" "750c" "8102" # X / Y / Max4095 / Count2 / Size12 Input
    "c0"                                 # End Collection
    "05ff0902" "26ff00" "9537" "7508" "8102"     # FF/02 Max255 Count55 Size8 Input
    "8501" "0901" "953f" "9102"           # Report ID (1) / Usage 01 / Count63 / Output
    "c0"                                 # End Collection
)


def report_descriptor(side: str) -> str:
    return _RD_HEAD.replace("8507", "8507" if side == "left" else "8508")


# ---- 0x05 报告里 data[6]/data[7] 的位序（SDL3 switch2 驱动期望）----
# SDL 读到的位：data[6]: 0x01 START, 0x08 LEFT_STICK, 0x10 SHARE, 0x20 GUIDE
#                data[7]: 0x01 WEST(B), 0x02 NORTH(Y), 0x04 SOUTH(A), 0x08 EAST(X),
#                        0x10 RIGHT_SHOULDER, 0x20 LEFT_SHOULDER,
#                        0x40 LEFT_PADDLE1, 0x80 LEFT_PADDLE2
# 其余位（0x02/0x04/0x40/0x80 of data[6]）SDL 不读，按真机 0x05 的
# byte1 位序补上：Minus / Plus / RStick / C。
# 注意这与 GATT 侧 hid_reports.md 的 byte1 位序不同（USB 固件的差异），
# 以 SDL 实际读取的位置为准。
_SDL_BYTES_L = [
    ["Start", "_", "_", "LeftStick", "Share", "Guide", "_", "_"],
    ["B", "Y", "A", "X", "RightBumper", "LeftBumper",
     "RightPaddle2", "LeftPaddle2"],
]
_SDL_BYTES_R = [
    ["Start", "_", "_", "RightStick", "Share", "Guide", "_", "_"],
    ["B", "Y", "A", "X", "RightBumper", "LeftBumper",
     "RightPaddle2", "LeftPaddle2"],
]

# ---- 真机 0x07（L）/ 0x08（R）的 16 位按钮位表（hid_reports.md）----
# 描述符在这两个报告里声明 16 个 Button usage，所以 SDK 按钮位图 16 位，
# layout 的 buttonIndex 必须落在 0..15。
#
# L 侧（0x07）Button Format：
#   byte0: 0x80=Stick 0x40=Minus 0x20=ZL 0x10=L 0x08=Up 0x04=Left 0x02=Right 0x01=Down
#   byte1: 0x80=SL 0x40=SR 0x01=Capture
# R 侧（0x08）Button Format：
#   byte0: 0x80=Stick 0x40=Plus 0x20=ZR 0x10=R 0x08=X 0x04=Y 0x02=A 0x01=B
#   byte1: 0x80=SL 0x40=SR 0x10=C 0x01=Home
#
# 序号 = Button usage 序号（byte0 bit0 → 0 … byte1 bit7 → 15）。
_MINI_BUTTONS_LEFT = [
    ["DPAD_DOWN", "DPAD_RIGHT", "DPAD_LEFT", "DPAD_UP",
     "LeftBumper", "LT_DIGITAL", "Back", "LeftStick"],
    ["Share", "_", "_", "_", "_", "_", "RightPaddle", "LeftPaddle"],
]
_MINI_BUTTONS_RIGHT = [
    ["B", "A", "Y", "X",
     "RightBumper", "RT_DIGITAL", "Start", "RightStick"],
    ["Guide", "Misc1", "_", "_", "_", "_", "RightPaddle", "LeftPaddle"],
]


def build_state_block(side: str):
    """SubmitState 填充的状态块。

    byte 0-1：0x05 用的按钮位图（SDL 读的位序）
    byte 2-3：0x07/0x08 用的按钮位图（真机 Button Format）
    byte 4-11：左/右摇杆各 4 字节（int16，0..4095，Y 反转）
    byte 12-23：IMU（accel×3 + gyro×3，int16）
    """
    sdl_bytes = _SDL_BYTES_L if side == "left" else _SDL_BYTES_R
    mini_bytes = _MINI_BUTTONS_LEFT if side == "left" else _MINI_BUTTONS_RIGHT
    fields = [
        {"byte": 0, "type": "button-mask", "buttons": sdl_bytes[0]},
        {"byte": 1, "type": "button-mask", "buttons": sdl_bytes[1]},
        {"byte": 2, "type": "button-mask", "buttons": mini_bytes[0]},
        {"byte": 3, "type": "button-mask", "buttons": mini_bytes[1]},
        {"byte": 4, "type": "int16-axis", "semantic": "leftStickX",
         "min": 0, "max": 4095},
        {"byte": 6, "type": "int16-axis", "semantic": "leftStickY",
         "min": 0, "max": 4095, "invert": True},
        {"byte": 8, "type": "int16-axis", "semantic": "rightStickX",
         "min": 0, "max": 4095},
        {"byte": 10, "type": "int16-axis", "semantic": "rightStickY",
         "min": 0, "max": 4095, "invert": True},
        {"byte": 12, "type": "int16-le", "semantic": "accelGX", "scale": [4096, 2]},
        {"byte": 14, "type": "int16-le", "semantic": "accelGY", "scale": [4096, 2]},
        {"byte": 16, "type": "int16-le", "semantic": "accelGZ", "scale": [4096, 2]},
        {"byte": 18, "type": "int16-le", "semantic": "gyroDpsX",
         "scale": 16.433679195430518},
        {"byte": 20, "type": "int16-le", "semantic": "gyroDpsY",
         "scale": 16.433679195430518},
        {"byte": 22, "type": "int16-le", "semantic": "gyroDpsZ",
         "scale": 16.433679195430518},
    ]
    return {"size": 24, "fields": fields}


def build_common_report():
    """0x05 共通报告：SDL3 switch2 驱动读的位置。"""
    return {
        "name": "common",
        "reportId": "0x05",
        "size": 64,
        "send": "clock",
        "program": [
            {"const": {"0": "05", "2": "25"}},
            {"counter": "reportsSent", "at": 1, "width": 32, "scale": 4},
            # 按钮位图 stateBlock[0:2]（SDL 位序）→ 报告 data[6:8]
            {"copy": "0-1", "to": 6},
            # 左摇杆 stateBlock[4:8] → data[11:14]（12bit 打包）
            {"pack12": [4, 6], "to": 11},
            # 右摇杆 stateBlock[8:12] → data[14:17]
            {"pack12": [8, 10], "to": 14},
            # IMU stateBlock[12:24] → data[43:61]（Motion Data 起点 0x2A+3）
            {"copy": "12-23", "to": 43},
        ],
    }


def build_mini_report(side: str):
    """0x07（L）/ 0x08（R）：带标准 Button usage 的那一份。"""
    is_left = side == "left"
    # 真机 0x07/0x08（含 report ID）：
    #   data[1] counter, data[2] power, data[3:5] buttons, data[5] unknown,
    #   data[6:9] 本侧摇杆(12bit×2), data[9..] vendor
    prog = [
        {"const": {"0": "07" if is_left else "08", "2": "25", "5": "07"}},
        {"counter": "reportsSent", "at": 1, "width": 8},
    ]
    if is_left:
        prog.append({"pack12": [4, 6], "to": 6})
    else:
        prog.append({"pack12": [8, 10], "to": 6})
    # 按钮位图 stateBlock[2:4]（真机 Button Format）→ 报告 data[3:5]
    prog.append({"copy": "2-3", "to": 3})
    return {
        "name": "mini",
        "reportId": "0x07" if is_left else "0x08",
        "size": 64,
        "send": "clock",
        "program": prog,
    }


def build_protocol():
    """设备协议：状态寄存器、计数器、输入节拍。

    ★ 关键：不写 `input.while`（或让 reportsOn 初始为真）。
      参照 switch2-pro-composite.json，它的 reportsOn 由厂商命令 03/0D
      置真——那份 profile 带完整命令协议。我们这份**不做厂商协议**，
      若沿用 while:"reportsOn" 又没有命令去置位，reportsOn 永远为假，
      报告就**一帧都不会发**（表现：设备管理器一切正常、SDL 认出型号但
      数据全 0）。所以这里让输入节拍无条件运行。
    """
    return {
        "state": [
            {"name": "featureMask", "bits": 8},
            {"name": "featureEnabled", "bits": 8},
        ],
        "counters": [
            {"name": "reportsSent", "bits": 32, "on": "report"},
        ],
        "input": {
            # UMDF2 后端：报告走 HID 驱动，没有端点可命名，故不写 endpoint。
            "clock": {"periodMs": 4, "origin": "inputOpened", "missedTick": "owe"},
        },
    }


def build_profile(side: str) -> dict:
    is_left = side == "left"
    mini_bytes = _MINI_BUTTONS_LEFT if is_left else _MINI_BUTTONS_RIGHT
    product = "Joy-Con 2 (L)" if is_left else "Joy-Con 2 (R)"
    pid = "0x2067" if is_left else "0x2066"
    if is_left:
        sdl = ("a:b10,b:b12,x:b15,y:b14,"
               "leftshoulder:b13,rightshoulder:b9,"
               "back:b16,start:b0,guide:b11,"
               "leftstick:b11,rightstick:b15,"
               "dpup:b3,dpdown:b0,dpleft:b2,dpright:b1,"
               "leftx:a0,lefty:a1,"
               "lefttrigger:b5,righttrigger:b4,"
               "paddle1:b14,paddle2:b15,"
               "hint:!SDL_GAMECONTROLLER_USE_BUTTON_LABELS:=1,platform:Windows,")
        face = [("face_b", 12), ("face_a", 10), ("face_y", 14), ("face_x", 15)]
        shoulder = [("left_bumper", 13), ("right_bumper", 9),
                    ("left_trigger_click", 5), ("right_trigger_click", 4)]
        system = [("start", 0), ("back", 15), ("home", 11), ("capture", 8)]
        dpad = {"encoding": "buttons", "upButton": 3, "downButton": 0,
                "leftButton": 2, "rightButton": 1}
    else:
        sdl = ("a:b2,b:b0,x:b3,y:b1,"
               "leftshoulder:b5,rightshoulder:b4,"
               "back:b14,start:b6,guide:b9,"
               "leftstick:b7,rightstick:b8,"
               "dpup:b3,dpdown:b0,dpleft:b2,dpright:b1,"
               "rightx:a0,righty:a1,"
               "lefttrigger:b15,righttrigger:b14,"
               "paddle1:b12,paddle2:b13,"
               "hint:!SDL_GAMECONTROLLER_USE_BUTTON_LABELS:=1,platform:Windows,")
        face = [("face_b", 0), ("face_a", 2), ("face_y", 1), ("face_x", 3)]
        shoulder = [("left_bumper", 5), ("right_bumper", 4),
                    ("left_trigger_click", 15), ("right_trigger_click", 14)]
        system = [("start", 6), ("back", 12), ("home", 9), ("capture", 8)]
        dpad = {"encoding": "buttons", "upButton": 3, "downButton": 0,
                "leftButton": 2, "rightButton": 1}
    return {
        "id": f"switch2-joycon-{side}",
        "name": f"Nintendo Switch 2 Joy-Con ({'L' if is_left else 'R'})",
        "vendor": "Nintendo",
        "vid": "0x057E",
        "pid": pid,
        "productString": product,
        "manufacturerString": "Nintendo Co., Ltd.",
        "type": "gamepad",
        "connection": "usb",
        "descriptor": report_descriptor(side),
        "inputReportSize": 64,
        "extendedReport": {
            # ★ 指向 0x07/0x08（带标准 Button usage 的那一份）：HIDMaestro 的
            #   HidReportBuilder 只解析一个报告的字段，profile 的
            #   extendedReport.reportId 优先（HidReportBuilder.cs:637-638）；
            #   0x05 是纯 vendor 报告（63 字节无 usage），指向它会得到
            #   "Declared axes: []"。0x05 仍由 inputReports 发出给 SDL。
            "reportId": "0x07" if is_left else "0x08",
            "size": 64,
            "alwaysArmed": True,
            "fields": [
                {"byte": 1, "type": "uint8-rolling", "semantic": "sequenceNum",
                 "initial": 0},
                {"byte": 2, "type": "uint8", "semantic": "powerInfo", "initial": 37},
                {"byte": 3, "type": "button-mask", "buttons": mini_bytes[0]},
                {"byte": 4, "type": "button-mask", "buttons": mini_bytes[1]},
                {"byte": 6, "type": "stick12-pair", "semantic": "leftStick"},
                {"byte": 9, "type": "stick12-pair", "semantic": "rightStick"},
            ],
        },
        "layout": {
            "kind": "gamepad",
            "source": "Nintendo Switch 2 Joy-Con 2 real-device capture",
            "sticks": [
                # 真机每半只声明一组轴，usage 都是 X/Y（descriptors.md：
                # L 与 R 的 Physical Collection 里都是 Usage (X)/Usage (Y)）。
                {"side": "left" if is_left else "right",
                 "xAxis": "X", "yAxis": "Y",
                 "clickButton": 7 if is_left else 7},
            ],
            "triggers": [
                {"axis": None, "side": "left", "kind": "digital"},
                {"axis": None, "side": "right", "kind": "digital"},
            ],
            "dpad": dpad,
            "faceButtons": [{"role": r, "buttonIndex": i} for r, i in face],
            "shoulderButtons": [{"role": r, "buttonIndex": i} for r, i in shoulder],
            "systemButtons": [{"role": r, "buttonIndex": i} for r, i in system],
            "haptics": {"rumble": "None"},
            "imu": {"accelerometer": True, "gyroscope": True,
                    "magnetometer": False},
        },
        "axisMap": {"0x30": "leftStickX", "0x31": "leftStickY"},
        "sdlMapping": sdl,
        "stateBlock": build_state_block(side),
        "inputReports": [build_mini_report(side), build_common_report()],
        "protocol": build_protocol(),
        "notes": (
            "Joy-Con 2 (L/R) of Nintendo Switch 2 over USB. The HID report "
            "descriptor is the real device's 100 bytes, byte for byte, from "
            "switch2_controller_research (descriptors.md, Joy-Con 2 (L)); the "
            "right half differs only in Report ID (8 instead of 7). Two input "
            "reports are built from the 24-byte state block. 0x05, the common "
            "report, carries the counter, the buttons at data[6]/data[7], both "
            "12-bit packed sticks at data[11:14]/data[14:17] and the Motion "
            "Data block at data[0x2B:] — the offsets SDL's switch2 driver "
            "reads (SDL_hidapi_switch2.c HandleMiniControllerStateL and the "
            "sensor block of HandleSwitchProState). 0x07/0x08, the structured "
            "report, carries the buttons at data[3:5] in the real device's "
            "Button Format order and the stick at data[6:9], so the plain HID "
            "path (browser Gamepad API, DirectInput, Windows GameInput) can "
            "parse the Button usages the descriptor declares. No vendor "
            "interface and no command protocol: the device streams reports "
            "from the first frame."
        ),
    }


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    for side in ("left", "right"):
        d = build_profile(side)
        p = os.path.join(OUT_DIR, f"switch2-joycon-{side}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print(f"{p}\n   desc {len(d['descriptor'])//2}B pid={d['pid']} "
              f"reports={[r['reportId'] for r in d['inputReports']]}")
