"""Joy-Con 2 输入报告解析 + Joy-Con 1 / Pro Controller 1 报告编码。

输入侧格式来自 Linux drivers/hid/hid-nintendo.c 的 switch2 分支（2026 主线）以及
Alia5/VIIPER device/ns2pro 的实测布局：

  report 0x09 (PRO)      [3..5] 按键3字节  [4] 十字  [6..8] 左摇杆  [9..11] 右摇杆
  report 0x07 (JCL)      [3..4] 按键      [6..8] 摇杆
  report 0x08 (JCR)      [3..4] 按键      [6..8] 摇杆
  report 0x05 (UNIFIED)  [5..8] 按键4字节  [7] 十字  [11..13] 左  [14..16] 右
                         0x20 电池电压  0x22 充电  0x2B 时间戳  0x31.. IMU

输出侧格式来自 dekuNukem/Nintendo_Switch_Reverse_Engineering（0x30/0x3F）以及
HIDMaestro profiles/nintendo/switch-pro.json 的 stateBlock 字段表。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag
from typing import Dict, Optional

STICK_MIN = 0
STICK_CENTER = 2048
STICK_MAX = 4095


# --------------------------------------------------------------------------- #
# 按键位（Joy-Con 2 raw，对应内核 NS2_BTN* 宏）
# --------------------------------------------------------------------------- #

class Ns2Bit(IntFlag):
    """Joy-Con 2 上**真实存在**的按键，语义位（与具体报告格式无关）。

    位顺序按 hid-nintendo.c 的定义归类，而不是按报告字节位置——同一物理按键
    在不同报告里位置不同，语义位只表示"这个键被按下了"。

    这里只收录手柄本体上能按到的键。以下三位**刻意不收**：

      * GR / GL —— 只存在于「Joy-Con 2 充电握把」这个选配外设上，
                   手柄本体没有背键。内核里 GR/GL 的映射是给握把用的。
      * HEADSET —— U4 的 bit5 是耳机在位检测，只有 Pro Controller 2 有
                   3.5mm 孔；Joy-Con 2 没有耳机孔，这个位永远是 0。

    保留它们的位定义没有好处，反而会让"按键总数"虚高、让人以为手柄上有这些键。
    """
    # --- NS2_BTNR_* : Pro 专用报告的右半 ---
    B = 1 << 0
    A = 1 << 1
    Y = 1 << 2
    X = 1 << 3
    R = 1 << 4
    ZR = 1 << 5
    PLUS = 1 << 6
    RS = 1 << 7
    # --- NS2_BTNL_* : Pro 专用报告的左半 ---
    DOWN = 1 << 8
    RIGHT = 1 << 9
    LEFT = 1 << 10
    UP = 1 << 11
    L = 1 << 12
    ZL = 1 << 13
    MINUS = 1 << 14
    LS = 1 << 15
    # --- NS2_BTN_PRO_* : Pro 的第三字节 ---
    HOME = 1 << 16
    CAPTURE = 1 << 17
    # --- NS2_BTN3_* / NS2_BTN_U2_C : C 键（Joy-Con 2 右侧新增）---
    C = 1 << 18
    # --- SL / SR 分成左右两组，不能共用一个位---
    # Joy-Con L 的滑轨键与 Joy-Con R 的滑轨键是两个独立物理实体，
    # 共用一位会导致左右互相覆盖（单只 Joy-Con 使用时尤其明显）。
    SL_L = 1 << 19
    SR_L = 1 << 20
    SL_R = 1 << 21
    SR_R = 1 << 22


def has_sl(bit: "Ns2Bit") -> bool:
    """任意一侧的 SL 被按下。"""
    return bool(bit & (Ns2Bit.SL_L | Ns2Bit.SL_R))


def has_sr(bit: "Ns2Bit") -> bool:
    """任意一侧的 SR 被按下。"""
    return bool(bit & (Ns2Bit.SR_L | Ns2Bit.SR_R))


# --------------------------------------------------------------------------- #
# 报告字节 → 语义位
#
# 全部逐条对应 hid-nintendo.c:2896-2967 的定义 + 3180-3286 的映射表。
# --------------------------------------------------------------------------- #

# Pro 专用报告 0x09（NS2_REPORT_PRO）unified=False 的一套
_PRO_BYTES = (
    # NS2_BTNR_*  → raw_data[3]
    (3, 0x01, Ns2Bit.B),
    (3, 0x02, Ns2Bit.A),
    (3, 0x04, Ns2Bit.Y),
    (3, 0x08, Ns2Bit.X),
    (3, 0x10, Ns2Bit.R),
    (3, 0x20, Ns2Bit.ZR),
    (3, 0x40, Ns2Bit.PLUS),
    (3, 0x80, Ns2Bit.RS),
    # NS2_BTNL_*  → raw_data[4]
    (4, 0x01, Ns2Bit.DOWN),
    (4, 0x02, Ns2Bit.RIGHT),
    (4, 0x04, Ns2Bit.LEFT),
    (4, 0x08, Ns2Bit.UP),
    (4, 0x10, Ns2Bit.L),
    (4, 0x20, Ns2Bit.ZL),
    (4, 0x40, Ns2Bit.MINUS),
    (4, 0x80, Ns2Bit.LS),
    # NS2_BTN_PRO_* → raw_data[5]
    (5, 0x01, Ns2Bit.HOME),
    (5, 0x02, Ns2Bit.CAPTURE),
    # NS2_BTN_PRO_C = NS2_BTN3_C = BIT(4)
    (5, 0x10, Ns2Bit.C),
    # BIT(2)/BIT(3) 是 GR/GL —— 充电握把专属，手柄本体没有，不收
)

# 统一报告 0x05（NS2_REPORT_UNIFIED）的公共部分：raw_data[5..8]
# 注意 U1/U2/U3/U4 的物理位置在不同控制器类型下含义不同，
# 具体按键要靠下面的三套 per-type 表来解释。
_UNIFIED_U1 = (   # raw_data[5]
    (5, 0x01, "U1_Y"), (5, 0x02, "U1_X"), (5, 0x04, "U1_B"), (5, 0x08, "U1_A"),
    (5, 0x10, "U1_SR"), (5, 0x20, "U1_SL"), (5, 0x40, "U1_R"), (5, 0x80, "U1_ZR"),
)
_UNIFIED_U2 = (   # raw_data[6]
    (6, 0x01, "U2_MINUS"), (6, 0x02, "U2_PLUS"), (6, 0x04, "U2_RS"),
    (6, 0x08, "U2_LS"), (6, 0x10, "U2_HOME"), (6, 0x20, "U2_CAPTURE"),
    (6, 0x40, "U2_C"),
)
_UNIFIED_U3 = (   # raw_data[7]
    (7, 0x01, "U3_DOWN"), (7, 0x02, "U3_UP"), (7, 0x04, "U3_RIGHT"),
    (7, 0x08, "U3_LEFT"), (7, 0x10, "U3_SR"), (7, 0x20, "U3_SL"),
    (7, 0x40, "U3_L"), (7, 0x80, "U3_ZL"),
)
# U4 只有 GR(b0) / GL(b1) / HEADSET(b5)，三者都不是 Joy-Con 2 本体上的东西
# （GR/GL 要充电握把，HEADSET 要 Pro2 的耳机孔），所以整字节忽略。
_UNIFIED_U4: tuple = ()

# 统一报告下各类控制器的 U* → 语义位映射
# 来源：ns2_left_joycon_button_unified_mappings / ns2_right_... / ns2_procon_... / ns2_gccon_...
UNIFIED_MAPS: Dict[str, Dict[str, "Ns2Bit"]] = {
    "joyconL": {
        "U3_LEFT": Ns2Bit.LEFT, "U3_UP": Ns2Bit.UP,
        "U3_DOWN": Ns2Bit.DOWN, "U3_RIGHT": Ns2Bit.RIGHT,
        "U3_L": Ns2Bit.L, "U3_ZL": Ns2Bit.ZL,
        "U2_MINUS": Ns2Bit.MINUS, "U2_LS": Ns2Bit.LS,
        "U2_CAPTURE": Ns2Bit.CAPTURE,
        "U3_SL": Ns2Bit.SL_L, "U3_SR": Ns2Bit.SR_L,
    },
    "joyconR": {
        "U1_A": Ns2Bit.A, "U1_B": Ns2Bit.B,
        "U1_X": Ns2Bit.X, "U1_Y": Ns2Bit.Y,
        "U1_R": Ns2Bit.R, "U1_ZR": Ns2Bit.ZR,
        "U2_PLUS": Ns2Bit.PLUS, "U2_RS": Ns2Bit.RS,
        "U2_C": Ns2Bit.C, "U2_HOME": Ns2Bit.HOME,
        "U1_SL": Ns2Bit.SL_R, "U1_SR": Ns2Bit.SR_R,
    },
    "pro": {
        "U1_A": Ns2Bit.A, "U1_B": Ns2Bit.B,
        "U1_X": Ns2Bit.X, "U1_Y": Ns2Bit.Y,
        "U3_L": Ns2Bit.L, "U1_R": Ns2Bit.R,
        "U3_ZL": Ns2Bit.ZL, "U1_ZR": Ns2Bit.ZR,
        "U2_MINUS": Ns2Bit.MINUS, "U2_PLUS": Ns2Bit.PLUS,
        "U2_LS": Ns2Bit.LS, "U2_RS": Ns2Bit.RS,
        "U2_HOME": Ns2Bit.HOME, "U2_CAPTURE": Ns2Bit.CAPTURE,
        "U2_C": Ns2Bit.C,
        # 内核在 Pro 上把十字键走 HAT（raw_data[7] 的 U3_*）而不是 mappings 表，
        # 但本工具的输出去向是 Switch 1 的十字按键，所以照样折进语义位。
        "U3_UP": Ns2Bit.UP, "U3_DOWN": Ns2Bit.DOWN,
        "U3_LEFT": Ns2Bit.LEFT, "U3_RIGHT": Ns2Bit.RIGHT,
        # Pro 的两组滑轨键（一体式握把）
        "U1_SR": Ns2Bit.SR_R, "U1_SL": Ns2Bit.SL_R,
        "U3_SR": Ns2Bit.SR_L, "U3_SL": Ns2Bit.SL_L,
    },
    "gc": {
        "U1_A": Ns2Bit.A, "U1_B": Ns2Bit.B,
        "U1_X": Ns2Bit.X, "U1_Y": Ns2Bit.Y,
        "U3_L": Ns2Bit.L, "U1_R": Ns2Bit.R,
        "U3_ZL": Ns2Bit.ZL, "U1_ZR": Ns2Bit.ZR,
        "U2_MINUS": Ns2Bit.MINUS, "U2_PLUS": Ns2Bit.PLUS,
        "U2_HOME": Ns2Bit.HOME, "U2_CAPTURE": Ns2Bit.CAPTURE,
        "U2_C": Ns2Bit.C,
    },
}

# 单独一只 Joy-Con 的专用报告 0x07 / 0x08
# 来源：ns2_left_joycon_button_mappings / ns2_right_joycon_button_mappings
_JCL_BYTES = (
    # raw_data[3] = NS2_BTNL_*
    (3, 0x01, Ns2Bit.DOWN),
    (3, 0x02, Ns2Bit.RIGHT),
    (3, 0x04, Ns2Bit.LEFT),
    (3, 0x08, Ns2Bit.UP),
    (3, 0x10, Ns2Bit.L),
    (3, 0x20, Ns2Bit.ZL),
    (3, 0x40, Ns2Bit.MINUS),
    (3, 0x80, Ns2Bit.LS),
    # raw_data[4] = NS2_BTN_JCL_* + NS2_BTN3_*
    (4, 0x01, Ns2Bit.CAPTURE),          # NS2_BTN_JCL_CAPTURE = BIT(0)
    # BIT(2) = NS2_BTN_JCL_GL —— 充电握把专属，不收
    (4, 0x40, Ns2Bit.SR_L),             # NS2_BTN3_SR         = BIT(6)
    (4, 0x80, Ns2Bit.SL_L),             # NS2_BTN3_SL         = BIT(7)
)

_JCR_BYTES = (
    # raw_data[3] = NS2_BTNR_*
    (3, 0x01, Ns2Bit.B),
    (3, 0x02, Ns2Bit.A),
    (3, 0x04, Ns2Bit.Y),
    (3, 0x08, Ns2Bit.X),
    (3, 0x10, Ns2Bit.R),
    (3, 0x20, Ns2Bit.ZR),
    (3, 0x40, Ns2Bit.PLUS),
    (3, 0x80, Ns2Bit.RS),
    # raw_data[4] = NS2_BTN_JCR_* + NS2_BTN3_*
    (4, 0x01, Ns2Bit.HOME),             # NS2_BTN_JCR_HOME    = BIT(0)
    # BIT(2) = NS2_BTN_JCR_GR —— 充电握把专属，不收
    (4, 0x10, Ns2Bit.C),                # NS2_BTN3_C          = BIT(4)
    (4, 0x40, Ns2Bit.SR_R),             # NS2_BTN3_SR         = BIT(6)
    (4, 0x80, Ns2Bit.SL_R),             # NS2_BTN3_SL         = BIT(7)
)


# --------------------------------------------------------------------------- #
# 规范化状态
# --------------------------------------------------------------------------- #

@dataclass
class PadState:
    buttons: Ns2Bit = Ns2Bit(0)
    lx: int = STICK_CENTER
    ly: int = STICK_CENTER
    rx: int = STICK_CENTER
    ry: int = STICK_CENTER
    # IMU（原始值，Joy-Con 2 与 Joy-Con 1 同量级，直接透传）
    accel: tuple = (0, 0, 0)
    gyro: tuple = (0, 0, 0)
    # 遥测
    battery_volts: int = 3800
    charging: bool = False
    source_report: int = 0

    def pressed(self, bit: Ns2Bit) -> bool:
        return bool(self.buttons & bit)


def _unpack_stick12(buf: bytes, off: int) -> tuple:
    if len(buf) < off + 3:
        return STICK_CENTER, STICK_CENTER
    b0, b1, b2 = buf[off], buf[off + 1], buf[off + 2]
    x = b0 | ((b1 & 0x0F) << 8)
    y = (b1 >> 4) | (b2 << 4)
    return x, y


def _clamp12(v: int) -> int:
    return 0 if v < 0 else (0x0FFF if v > 0x0FFF else v)


def _pack_stick12(x: int, y: int) -> bytes:
    x = _clamp12(x)
    y = _clamp12(y)
    return bytes((
        x & 0xFF,
        ((x >> 8) & 0x0F) | ((y & 0x0F) << 4),
        (y >> 4) & 0xFF,
    ))


def _battery_byte(volts: int, charging: bool) -> int:
    """Pro1 报告 byte2：低 4 位电量档，bit4 充电，bit5 外接电源。"""
    if volts >= 4100:
        level = 8
    elif volts <= 3200:
        level = 0
    else:
        level = int((volts - 3200) / 100)
        level = max(0, min(8, level))
    return (level & 0x0F) | (0x10 if charging else 0) | (0x20 if charging else 0)
def _hat_value(buttons: Ns2Bit) -> int:
    """0x3F 简单报告的 hat 编码（switchbrew）：0=上 1=右上 2=右 3=右下
    4=下 5=左下 6=左 7=左上 8=中性。

    十字键在 0x3F 里走 hat，绝对不能塞进按钮位——描述符把 byte1..2 声明成
    16 个按钮，byte3 才是 hat，塞错位置主机读到的方向就是乱的。
    """
    up = bool(buttons & Ns2Bit.UP)
    down = bool(buttons & Ns2Bit.DOWN)
    left = bool(buttons & Ns2Bit.LEFT)
    right = bool(buttons & Ns2Bit.RIGHT)
    if up and right:
        return 1
    if down and right:
        return 3
    if down and left:
        return 5
    if up and left:
        return 7
    if up:
        return 0
    if right:
        return 2
    if down:
        return 4
    if left:
        return 6
    return 8


def _stick16(v12: int, center: int = 2048, travel: int = 2048) -> int:
    """12 位摇杆值(0..4095) -> 0x3F 的 16 位轴值(0..65535)。

    ★ center 必须是该摇杆的**真实物理中心**（见 SPI 0x603D 的 _stick_cal），
      不能用固定 2048。否则静止时会输出偏移值 → 表现为"中心偏移/漂移"。

    依据 HID 报告描述符（virtual/descriptors.py 的 JOYCON_REPORT_DESCRIPTOR）：
        Input size=16 count=4 logical=0..65535 usages=[X, Y, Rx, Ry]

    中心：12 位 2048 -> 16 位 32768（0x8000）
    满幅：12 位 0/4095 -> 16 位 0/65535

    这是 SDL ApplySimpleStickCalibration 与 Windows HID gamepad 驱动
    共同期望的格式（两者都按 0x8000 为中心归一化）。
    """
    v = int(v12)
    if v < 0:
        v = 0
    elif v > 4095:
        v = 4095
    # ★ 按**行程**归一化到满幅，不是按 12 位全范围。
    #   旧写法 (v-center)*16 隐含分母 2048，实际行程只有 1180 时
    #   推到极限也只得到 ±0.576 → **画不满**（用户实测圆度 2.5% 即此因）。
    #   travel 由调用方传入（= SPI 声明的行程），推到底正好 ±1.0。
    delta = (v - center) / float(travel) if travel else 0.0
    delta = -1.0 if delta < -1.0 else (1.0 if delta > 1.0 else delta)
    out = int(round(delta * 32768)) + 0x8000
    # +1.0 时算得 0x10000，超出 UShort，夹到 0xFFFF
    return 0 if out < 0 else (0xFFFF if out > 0xFFFF else out)


def _pack_stick16(v: int, negate: bool = False) -> bytes:
    # 12bit(0..4095) → 16bit 有符号（0x8000 居中）
    rel = (v - STICK_CENTER) / 1536.0      # ±1 满行程
    rel = max(-1.0, min(1.0, rel))
    val = int(round(rel * 32767))
    if negate:
        val = -val
    return int(val).to_bytes(2, "little", signed=True)


class JoyConEncoder:
    """Joy-Con 1（L=0x2006 / R=0x2007）编码器。

    USB 形态与蓝牙形态的 0x30 都是 48 字节负载 → 49 含 ID，无差异。
    """

    # ★ 2026-11-19：摇杆中心与行程统一改为标准值（照 viiper）
    #   vjoy_out.set_stick 已把 raw 重基准到 2048 中心，
    #   所以这里也必须用 2048 / 2047，保持一致。
    STICK_CENTER_XY = {"L": (2048, 2048), "R": (2048, 2048)}
    # 0x3F 走 _stick16，归一化=(v-center)/travel。
    # 行程改 2047（满量程），与 SPI 0x603D 声明一致，
    # 参考 viiper: "centre=2048, positive=2047, negative=2048"。
    STICK_TRAVEL = 2047

    def __init__(self, side: str, size: int = 49):
        self.side = side.upper()
        self.report_id = 0x30
        self.size = size
        self._counter = 0
        # 该侧真实物理中心，供 _stick16 使用
        self.stick_center = self.STICK_CENTER_XY.get(self.side, (2048, 2048))
        self.stick_travel = self.STICK_TRAVEL

    def encode(self, st: PadState, imu_enabled: bool = True) -> bytes:
        b = bytearray(self.size)
        b[0] = self.report_id
        b[1] = self._counter & 0xFF
        self._counter = (self._counter + 1) & 0xFF
        b[2] = _battery_byte(st.battery_volts, st.charging)
        ctx = st.buttons

        if self.side == "L":
            # ---- 位表照抄 SDL HandleCombinedControllerStateL ----
            #
            # 双手柄模式下 SDL 走 Combined 分支（不是 Mini），之前按 Mini
            # 的位表写，结果只有十字上和减号碰巧对得上，其余全错。
            #
            # rgucButtons[1] = b[4]:
            #   0x01 = BACK（减号 -）
            #   0x08 = LEFT_STICK 按下
            #   0x20 = SWITCH_SHARE（截图键）
            #
            # rgucButtons[2] = b[5]:
            #   0x01 = 十字下   0x02 = 十字上
            #   0x04 = 十字右   0x08 = 十字左
            #   0x10 = PADDLE2（SR）
            #   0x20 = PADDLE1（SL）
            #   0x40 = LEFT_SHOULDER（L）
            #   0x80 = LEFT_TRIGGER（ZL）
            if ctx & Ns2Bit.MINUS:
                b[4] |= 0x01      # BACK
            if ctx & Ns2Bit.LS:
                b[4] |= 0x08      # LEFT_STICK
            if ctx & Ns2Bit.CAPTURE:
                b[4] |= 0x20      # SHARE

            if ctx & Ns2Bit.DOWN:
                b[5] |= 0x01
            if ctx & Ns2Bit.UP:
                b[5] |= 0x02
            if ctx & Ns2Bit.RIGHT:
                b[5] |= 0x04
            if ctx & Ns2Bit.LEFT:
                b[5] |= 0x08
            if ctx & Ns2Bit.SR_L:
                b[5] |= 0x10      # PADDLE2
            if ctx & Ns2Bit.SL_L:
                b[5] |= 0x20      # PADDLE1
            if ctx & Ns2Bit.L:
                b[5] |= 0x40      # LEFT_SHOULDER
            if ctx & Ns2Bit.ZL:
                b[5] |= 0x80      # LEFT_TRIGGER
            b[6:9] = _pack_stick12(st.lx, st.ly)
            # ★ 2026-11-19 修复：另一侧（右）摇杆字段必须填**中性 2048**，
            #   原来留全 0 → raw 解包成 (0,0) = 满量程左上角。
            #   单只 Joy-Con 真机上报的是中性值，不是 0。
            #   SDL 若读该字段（配对被误判/换轴分支）会把角落值当真值，
            #   造成固定的大偏移、回中永远不在原点。
            b[9:12] = _pack_stick12(2048, 2048)
        else:
            # ---- 位表照抄 SDL HandleCombinedControllerStateR ----
            #
            # rgucButtons[0] = b[3]:
            #   0x01 = WEST(左)    0x02 = NORTH(上)
            #   0x04 = SOUTH(下)   0x08 = EAST(右)
            #   0x10 = PADDLE1(SL_R)  0x20 = PADDLE2(SR_R)
            #   0x40 = RIGHT_SHOULDER(R)
            #   0x80 = RIGHT_TRIGGER(ZR)
            #
            # 对应到 Joy-Con(R) 的物理键：
            #   Y 在左 -> WEST     X 在上 -> NORTH
            #   B 在下 -> SOUTH    A 在右 -> EAST
            if ctx & Ns2Bit.Y:
                b[3] |= 0x01      # WEST
            if ctx & Ns2Bit.X:
                b[3] |= 0x02      # NORTH
            if ctx & Ns2Bit.B:
                b[3] |= 0x04      # SOUTH
            if ctx & Ns2Bit.A:
                b[3] |= 0x08      # EAST
            if ctx & Ns2Bit.SR_R:
                b[3] |= 0x10
            if ctx & Ns2Bit.SL_R:
                b[3] |= 0x20
            if ctx & Ns2Bit.R:
                b[3] |= 0x40
            if ctx & Ns2Bit.ZR:
                b[3] |= 0x80
            if ctx & Ns2Bit.PLUS:
                b[4] |= 0x02
            if ctx & Ns2Bit.RS:
                b[4] |= 0x04
            if ctx & Ns2Bit.HOME:
                b[4] |= 0x10
            b[9:12] = _pack_stick12(st.rx, st.ry)
            # ★ 2026-11-19 修复：另一侧（左）摇杆字段填中性 2048，不留全 0。
            b[6:9] = _pack_stick12(2048, 2048)

        b[12] = 0x00
        if imu_enabled:
            # ---- 6 轴数据布局（官方文档 imu_sensor_notes.md）----
            #
            #   [13-14] accel_x  [15-16] accel_y  [17-18] accel_z
            #   [19-20] gyro_1   [21-22] gyro_2   [23-24] gyro_3
            #   每个样本 12 字节，共 3 个样本（间隔 5ms）
            #
            # 踩过的坑：之前顺序写成 az,ax,ay + gz,gx,gy，
            # 顺序错位会导致体感"全程乱转"。
            # 0x30 报文固定 3 组 IMU 样本（协议硬结构，SDL imuState[3]）。
            # SDL 把它们当作同一 15ms 报告周期内 3 个间隔 5ms 的采样
            # 依次积分 (sdl_switch.c:2731-2750)，3 组合起来正好覆盖 15ms。
            # 所以三组填**同一个真实值**是正确的：主机积分 3×5ms = 15ms，
            # 恰好等于真实时长，不是"算三遍"。
            # 若只让一组带值、另两组填 0，积分只剩 5ms -> 灵敏度掉到 1/3。
            # 我们只有 65Hz 一帧真实数据，没有 195Hz 历史，故复制当前帧。
            # 只缩放 gyro（被积分的量）；accel 保持真实重力值。
            # ═══ IMU 填充：3 组同值（照 Pro2 ProfessionalImuPipeline 的做法）═══
            #
            # Pro2 纯软件方案（ProfessionalImuPipeline.cs）默认：
            #   OutputSampleMode    = Average3Samples      → 输出取 3 组平均
            #   IntegrationSampleMode = PerSampleForIntegration → 积分逐样本
            #
            # 它每帧把**同一份物理样本**分发到 3 个 slot（因为我们每帧
            # 只从 BLE 拿到一帧 IMU，没有更细的历史），主机对 3 组做积分：
            #   interval = elapsed/3（SDL 自适应），积分 = w×(elapsed/3)×3
            #           = w×elapsed  ← 与报告周期无关，永远正确
            #
            # 这是 SDL 与 Pro2 共同的模型。不要只填 1 组（灵敏度掉 1/3），
            # 也不要把真值填到 slot[1]/[2] 而 slot[0]=0（SDL 的
            # bHasSensorData 看 slot[0].accel，会判为"无传感器数据"而跳过）。
            ax0, ay0, az0 = st.accel
            gx0, gy0, gz0 = st.gyro
            one = (ax0, ay0, az0, gx0, gy0, gz0)
            for i in range(3):
                ax, ay, az, g1, g2, g3 = one
                base = 13 + i * 12
                b[base + 0:base + 2] = int(ax).to_bytes(2, "little", signed=True)
                b[base + 2:base + 4] = int(ay).to_bytes(2, "little", signed=True)
                b[base + 4:base + 6] = int(az).to_bytes(2, "little", signed=True)
                b[base + 6:base + 8] = int(g1).to_bytes(2, "little", signed=True)
                b[base + 8:base + 10] = int(g2).to_bytes(2, "little", signed=True)
                b[base + 10:base + 12] = int(g3).to_bytes(2, "little", signed=True)
        return bytes(b)

    def encode_simple(self, st: PadState) -> bytes:
        """Joy-Con 的 0x3F 简单报告（12 字节）。

        权威来源 dekuNukem/bluetooth_hid_notes.md「INPUT 0x3F」+ SDL
        HandleMiniSimpleControllerStateL/R：

          byte0      0x3F
          byte1..2   按钮（左右两侧位定义不同，见下）
          byte3      hat（十字键/摇杆方向，0-7 + 8=中性）
          byte4..11  填充 `00 80 00 80 00 80 00 80`

        注意 Joy-Con 在 0x3F 里**没有模拟轴**——方向全靠 hat 表达，
        byte4..11 必须是固定的填充值。填真摇杆值会被主机当垃圾数据。
        所以这里把摇杆的大幅偏移折算进 hat，小偏移忽略（0x30 全模式才有精度）。
        """
        b = bytearray(12)
        b[0] = 0x3F
        ctx = st.buttons

        if self.side == "L":
            # SDL HandleMiniSimpleControllerStateL
            if ctx & Ns2Bit.DOWN:
                b[1] |= 0x01
            if ctx & Ns2Bit.UP:
                b[1] |= 0x02
            if ctx & Ns2Bit.LEFT:
                b[1] |= 0x04
            if ctx & Ns2Bit.RIGHT:
                b[1] |= 0x08
            if ctx & Ns2Bit.L:
                b[1] |= 0x10
            if ctx & Ns2Bit.ZL:
                b[1] |= 0x20
            if ctx & Ns2Bit.MINUS:
                b[1] |= 0x40
            if ctx & Ns2Bit.LS:
                b[1] |= 0x80
            if ctx & Ns2Bit.CAPTURE:
                b[2] |= 0x20
        else:
            # SDL HandleMiniSimpleControllerStateR
            if ctx & Ns2Bit.Y:
                b[1] |= 0x01
            if ctx & Ns2Bit.X:
                b[1] |= 0x02
            if ctx & Ns2Bit.B:
                b[1] |= 0x04
            if ctx & Ns2Bit.A:
                b[1] |= 0x08
            if ctx & Ns2Bit.R:
                b[1] |= 0x10
            if ctx & Ns2Bit.ZR:
                b[1] |= 0x20
            if ctx & Ns2Bit.PLUS:
                b[2] |= 0x02
            if ctx & Ns2Bit.RS:
                b[2] |= 0x08
            if ctx & Ns2Bit.HOME:
                b[2] |= 0x10

        # hat 只表达十字键。摇杆走下面的 16 位模拟轴，不塞进 hat。
        b[3] = _hat_value(ctx)

        # ── 摇杆：4 个 16 位轴（X, Y, Rx, Ry）───────────────
        # 依据 HID 报告描述符：
        #   Input size=16 count=4 logical=0..65535 usages=[X, Y, Rx, Ry]
        #
        # **这里原来是固定填 00 80 00 80 00 80 00 80（全中性），
        # 等于告诉主机"摇杆永远在中间"** —— 这是"画不满"的真正原因。
        # Windows HID gamepad 与 SDL ApplySimpleStickCalibration 都读这 4 个
        # 16 位轴并按 0x8000 为中心归一化。
        #
        # ═══ 轴分配（2026-11-18 修正）═══
        #
        # SDL 的 0x3F 结构体是（SDL_hidapi_switch.c:159-165）：
        #     Uint8 rgucButtons[2];
        #     Uint8 ucStickHat;
        #     Sint16 sJoystickLeft[2];   ← 第 1、2 轴
        #     Sint16 sJoystickRight[2];  ← 第 3、4 轴
        #
        # 而 SDL 的读取是（同文件 2386-2395）：
        #     sJoystickLeft[0]  → LEFTX      (b[4:6])
        #     sJoystickLeft[1]  → LEFTY      (b[6:8])
        #     sJoystickRight[0] → RIGHTX     (b[8:10])
        #     sJoystickRight[1] → RIGHTY     (b[10:12])
        #
        # ★ 旧实现把 4 个轴全按"每只 Joy-Con 只用主 X/Y"处理，
        #   第 3/4 轴固定填中性 → **右 Joy-Con 在 0x3F 下完全没有反应**
        #   （实测：测试网站右摇杆不动，Ryujinx 有反应）。
        #
        # 正确做法：按 side 填到对应的那一对轴，另一对保持中性。
        #   · 左手柄 → b[4:6]/b[6:8]  = lx/ly，第 3/4 轴中性
        #   · 右手柄 → b[8:10]/b[10:12] = rx/ry，第 1/2 轴中性
        #   Windows HID gamepad 与 SDL 都按这个结构读。
        # 中心必须用该侧的真实物理中心（与 SPI 0x603D 的 _stick_cal 一致），
        # 否则静止时输出偏移值 → 中心偏移/漂移。
        # ★ 2026-11-18 恢复：每只 Joy-Con 独立设备，都把主摇杆填到
        #   前两轴 X/Y（b[4:6]/b[6:8]），后两轴中性。
        #   c9d4244 曾错误地把右手柄填到后两轴 → WebHID 测试网站读不到 → 失灵。
        #   这是"网站完全正常"时的原始布局，只是 center/travel 改用实测值。
        cx, cy = self.stick_center
        tv = self.stick_travel
        if self.side == "L":
            ax, ay = st.lx, st.ly
        else:
            ax, ay = st.rx, st.ry

        b[4:6] = _stick16(ax, cx, tv).to_bytes(2, "little")   # X
        b[6:8] = _stick16(ay, cy, tv).to_bytes(2, "little")   # Y
        b[8:10] = (0x8000).to_bytes(2, "little")              # Z 轴：中性
        b[10:12] = (0x8000).to_bytes(2, "little")             # Rx 轴：中性
        return bytes(b)
