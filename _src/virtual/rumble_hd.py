"""Joy-Con 1 震动块 → Joy-Con 2 HD 震动块（LRA）。

=============== 链路总览 ===============

  主机（游戏/模拟器）写 USB 中断 OUT 的 Output Report 0x01 / 0x10
    → `hid_function._handle_output_report` 拿到完整输出包
    → data[2:6] = 左块，data[6:10] = 右块（各 4 字节，JC1 原生编码）
    → `jc1_block_to_jc2()`  解振幅 → 编成 5 字节
    → `HdRumbleSender`      组 17 字节帧 → 写 Joy-Con 2 的 GATT 0x0012
                            （Output Report 0x01）

=============== 为什么不能"直接转发 4 字节" ===============

JC1 的震动块是 **4 字节**：2 字节高频段（频率码 + 振幅） + 2 字节低频段。
JC2 的 HD Rumble Data 是 **16 字节**，前 5 字节是一组
（高频频率 10 位 + 高频振幅 12 位 + 低频频率 10 位 + 低频振幅 10 位）。
两者编码不同、量纲不同 —— 直接透传 4 字节到 JC2 只会让它静音或乱震。

=============== 为什么只搬振幅、不搬频率 ===============

SDL 的 JC2 驱动（`SDL_hidapi_switch2.c`）自己也不搬频率：
`ctx->rumble_hi_freq` / `ctx->rumble_lo_freq` 在 `InitJoystick` 里被写成
常数 0x187 / 0x112，之后**再也不改**，`RumbleJoystick` 只更新两个振幅。
JC1 的频率码是"9 位指数码（81.75Hz~1252Hz）"，JC2 是"10 位另一种码"，
二者没有公开的换算关系；硬套线性比例只会把低频段推到听不见的位置。
所以本模块沿用 SDL 的做法：频率锁默认值，只把振幅忠实搬过去 ——
这是**已经过 SDL 实机验证**的唯一可靠映射。
"""
from __future__ import annotations

import logging
import threading
import time

# 必须挂到 logger_config 的 "Joy2Win" 上。
# 用 logging.getLogger(__name__) 得到 "virtual.rumble_hd"：
# 它没有 handler、也不 propagate 到 Joy2Win，
# 结果 [HD震动] 一行都进不了 logs/joy2win.log —— 诊断等于没做。
try:
    from logger_config import logger as log
except Exception:            # noqa: BLE001  —— 单测/独立运行时可降级
    log = logging.getLogger("Joy2Win")

# ---------------------------------------------------------------- 常量

# Joy-Con 1 震动块的"中性值"：无震动（[00 01 40 40]）
JC1_NEUTRAL = bytes((0x00, 0x01, 0x40, 0x40))

# Joy-Con 1 HF 振幅字节范围（dekuNukem/bluetooth_hid_notes.md）
JC1_HF_AMP_MIN = 0x00
JC1_HF_AMP_MAX = 0xC8          # 标称安全上限；真机 0xFE 但会伤 LRA
# Joy-Con 1 LF 振幅：低字节 0x40 = 0.0，0x72 = 1.0
JC1_LF_AMP_ZERO = 0x40
JC1_LF_AMP_MAX = 0x72

# SDL 的 JC2 振幅上限（SDL_hidapi_switch2.c: #define RUMBLE_MAX 29000）
# 源码注释："Rumble can get so strong that it might be dangerous to the
# controller... This is a game controller, not a massage device"
JC2_RUMBLE_MAX = 29000

# SDL 的 JC2 默认频率码（InitJoystick 里写死，之后不再变）
JC2_HF_FREQ = 0x187
JC2_LF_FREQ = 0x112

# Joy-Con 2 的 Output Report 0x01 落在 GATT handle 0x0012，
# 左右手柄是不同的 characteristic（s2r_bluetooth_interface.md:126-127）
UUID_RUMBLE_LEFT = "289326cb-a471-485d-a8f4-240c14f18241"
UUID_RUMBLE_RIGHT = "fa19b0fb-cd1f-46a7-84a1-bbb09e00c149"

# Output Report 0x01 在蓝牙下 report ID 恒为 0x00（s2r_hid_reports.md:228）
REPORT_ID_BT = 0x00
# 0x0(reportID) + 0x1..0x10(HD Rumble Data) = 17 字节最小完整帧
FRAME_LEN = 17

# 节流：SDL 的 RUMBLE_WRITE_FREQUENCY_MS = 5，Joy-Con 还要翻倍（=10ms）
# 即 100Hz。BLE 写是无应答写，太快会把 Windows BLE 栈顶住。
# 100Hz 是 2026-11-17 实测验证过的正确值 —— 之前误以为高频写会导致
# 摇杆跳变而降到 20Hz，那是错误假说：跳变真因是 hid_function 的子命令
# reply 摇杆字段全 0（已修，见 virtual/hid_function.py），与写频率无关。
MIN_INTERVAL_S = 0.010

# ═══ 震动保持（2026-11-17，修「只有轻弹」）═══
#
# ★ 根因：JC1/JC2 的马达有看门狗，**不持续刷新就停**。
#   SDL 源码（SDL_hidapi_switch.c:57-58）原文：
#       // How often you have to refresh a long duration rumble
#       // to keep the motors running
#       #define RUMBLE_REFRESH_FREQUENCY_MS 50
#   并在 UpdateDevice 主循环里：
#       } else if (ctx->m_bRumbleActive &&
#                  now >= (ctx->m_ulRumbleSent + RUMBLE_REFRESH_FREQUENCY_MS)) {
#           SendPendingRumble(ctx);      // ← 每 50ms 重发，维持持续震动
#       }
#
#   旧实现只把主机写的 Output Report 转成一帧发出去。主机写一次、
#   我们发一帧 → 马达被驱动约 20ms 就因看门狗超时停掉
#   → 听感就是「轻弹一下」，无论游戏原本要震多久。
#
#   正确做法（照抄 SDL）：收到震动后把它记为"当前活动震动"，
#   在 worker 里每 REFRESH_S 重发一次，直到主机发来静音块或超时。
# ★ 2026-11-17 二次修正：改用 **JC2 驱动** 的 RUMBLE_INTERVAL=12ms，
#   不是 JC1 驱动的 RUMBLE_REFRESH_FREQUENCY_MS=50ms。
#   原因：目标是让 JC2 手柄震得像 **NS2 原生**。NS2 系统驱动 JC2 时
#   就是每 12ms 刷新一次（SDL_hidapi_switch2.c:36 RUMBLE_INTERVAL 12）。
#   12ms 的节奏比 50ms 细腻得多 —— 这正是用户说的"NS2 原生更细腻"。
#
# ★★ 2026-11-19 再修正：12ms → 36ms（= 12ms × 3 子帧）。
#   现在 build_frame 一包写 3 个相同子帧（照 Pro2 结构），
#   一包覆盖未来 36ms 的震动，所以每 36ms 写一次即可 ——
#   **实际震动刷新精度仍是 12ms，但 BLE 写入次数降到 1/3**。
#   这直接解决了「一开震动就把 BLE 时间槽占满 → 输入不跟手/判定断连」。
#   仍然远快于马达看门狗所需的 50ms，震动不会断。
REFRESH_S = 0.036


def _refresh_interval() -> float:
    """按当前模式取刷新间隔。

    basic（普通震动）：单子帧、无 HD 细腻度需求 → 用 SDL JC1 的 50ms 节奏，
        写完就让出 BLE，最大限度保输入流畅。
    hd（HD 震动）：3 子帧合并包 → 36ms（=12ms×3，等效仍 12ms 精度）。
    """
    return 0.050 if RUMBLE_MODE == "basic" else REFRESH_S


# 兼容旧代码：worker 里用 self._refresh() 取当前间隔

# 主机停写震动包后，继续维持这么久再停（吸收 USB 报告抖动）。
# SDL 的语义是"主机调用 RumbleJoystick 0,0 才停"，但我们的上游是
# 游戏写 Output Report，中间可能缺帧，留一点余量避免断续。
HOLD_S = 0.25

# ★ 2026-11-17 三次修正：静音也要"保持重发"，否则脉冲停顿不明显。
#
# 实测（tests/probe_pulse.py）：模拟震100ms/停100ms，
# 旧实现静音帧只占 8.2%（预期 50%），停顿被压缩一半。
#
# 根因：震动时 _active 有值，worker 按 REFRESH_S 持续重发保持；
#       但静音时 _active 清空，只发一帧静音就不再发了。
#       LRA 停驱动后是**缓慢衰减**的，只发一帧静音压不住余振，
#       马达还在振 → 停顿感消失。
#
# 修法：静音也当作一种"活动状态"保持重发 SILENCE_HOLD_S 毫秒，
#       确保 LRA 被明确制动。这样脉冲中间的停顿才清晰。
SILENCE_HOLD_S = 0.10       # 静音保持 100ms（覆盖典型脉冲间隔）
# ★ 2026-11-19：静音期间最多重发几帧制动。
#   原来在 SILENCE_HOLD_S(100ms) 内按 12ms 重发 = 约 8 帧，
#   而震动/静音每秒切换 2~6 次 → 光"制动帧"就 16~48 帧/秒白占 BLE。
#   LRA 一旦被明确制动就不需要持续刷，3 帧足够压住余振。
SILENCE_REFRESH_MAX = 3

# ═══ 震动模式开关（2026-11-19，用于 HD / 普通 对照实验）═══
#
# 用户要求：先改成"普通震动"，与 HD 震动做对照，确认问题是否来自 HD 链路。
#
#   "hd"    当前实现：NS2 原生频率 0x187/0x112 + 10位振幅 + 3 子帧合并包
#   "basic" 普通震动：固定单一频率、只搬振幅、单子帧
#           （等价于最朴素的震动，最省 BLE，但无 HD 细腻度）
#
# 改这一行即可切换；也可运行时用 set_mode("basic") 切换。
#
# ★ 2026-11-19 结论：卡顿的真正根因是 hid_function.pending_in 的阻塞策略
#   （已改为「缓存报告」路径，见那里的说明），与震动模式无关。
#   所以恢复 HD 震动；且 HD 用 3 子帧合并包 + 36ms 刷新，
#   BLE 写入量只有 basic(50ms 单子帧) 的约 1.4 倍，但远低于最初的
#   12ms 单子帧（那是 3 倍）。细腻度与带宽都保住了。
RUMBLE_MODE = "hd"

# 连续帧**字节完全相同**才跳过（游戏静止时主机仍反复写同一帧）。
# 不做"振幅近似去重"——那会把渐变的细腻震动抹平成阶跃，手感变差。
DEDUP_ENABLE = True


# ---------------------------------------------------------------- 解码

def decode_jc1_block(blk: bytes) -> tuple:
    """JC1 4 字节震动块 → (hf_freq9, hf_amp8, lf_freq7, lf_amp9)。

    位域依据 dekuNukem/Nintendo_Switch_Reverse_Engineering
    `bluetooth_hid_notes.md` 的 "Rumble data" 表：

      | 字节 | 掩码     | 含义                                        |
      | 0    | 全       | HF 频率码低 8 位                            |
      | 1    | bit0     | HF 频率码第 9 位                            |
      | 1    | bit1..7  | HF 振幅（步长 0x02，0x00..0xC8）            |
      | 2    | bit0..6  | LF 频率码（0x01..0x7F）                     |
      | 2    | bit7     | LF 振幅"中间档"标志                         |
      | 3    | 全       | LF 振幅低 8 位（0x40..0x72）                |

    返回值里的 lf_amp9 保留了 bit8 的中间档标志，换算见 `jc1_lf_amp16()`。
    """
    if len(blk) < 4:
        return (0, 0, 0, 0)
    b0, b1, b2, b3 = blk[0], blk[1], blk[2], blk[3]
    hf_freq = ((b1 & 0x01) << 8) | b0          # 9 位，0x004..0x1FC
    hf_amp = b1 & 0xFE                          # 8 位，步长 2
    lf_freq = b2 & 0x7F                         # 7 位，0x01..0x7F
    lf_amp = ((b2 & 0x80) << 1) | b3            # 9 位，含中间档标志
    return (hf_freq, hf_amp, lf_freq, lf_amp)


def is_neutral(blk: bytes) -> bool:
    """是否中性块（= 不震）。

    中性值是 `00 01 40 40`。但**不能只判等于中性**：
    主机停震时经常写成"振幅为 0、频率码不同"的块，语义上同样是静音。
    """
    if len(blk) < 4:
        return True
    _hf_freq, hf_amp, _lf_freq, lf_amp = decode_jc1_block(blk)
    return hf_amp == 0 and (lf_amp & 0xFF) <= JC1_LF_AMP_ZERO


# SDL 的 JC1 HF 振幅表（sdl_switch.c: EncodeRumbleHighAmplitude 的 hfa[101][2]）
# 这是**唯一权威**的 0..65535 → 0x00..0xC8 映射，不能自己造指数近似：
# 表在 index 0→1 处跳到 514，之后按 1.19 倍递进，到 8192 附近又换段。
# 指数公式给 0x10 → 724，真表是 2192（差 3 倍），听感完全不同。
_HFA_KEYS = (
    0, 514, 775, 921, 1096, 1303, 1550, 1843, 2192, 2606,
    3100, 3686, 4383, 5213, 6199, 7372, 7698, 8039, 8395, 8767,
    9155, 9560, 9984, 10426, 10887, 11369, 11873, 12398, 12947, 13520,
    14119, 14744, 15067, 15397, 15734, 16079, 16431, 16790, 17158, 17534,
    17918, 18310, 18711, 19121, 19540, 19967, 20405, 20851, 21308, 21775,
    22251, 22739, 23236, 23745, 24265, 24797, 25340, 25894, 26462, 27041,
    27633, 28238, 28856, 29488, 30134, 30794, 31468, 32157, 32861, 33581,
    34316, 35068, 35836, 36620, 37422, 38242, 39079, 39935, 40809, 41703,
    42616, 43549, 44503, 45477, 46473, 47491, 48531, 49593, 50679, 51789,
    52923, 54082, 55266, 56476, 57713, 58977, 60268, 61588, 62936, 64315,
    65535,
)


def jc1_hf_amp16(hf_amp: int) -> float:
    """JC1 HF 振幅字节 → 0..65535 的归一化振幅（SDL 原表直查）。

    code 0x00..0xC8 步长 2，共 101 档，index = code // 2。
    """
    code = max(JC1_HF_AMP_MIN, min(JC1_HF_AMP_MAX, int(hf_amp) & 0xFE))
    return float(_HFA_KEYS[code // 2])


def jc1_hf_amp16_to_code(amp16: float) -> int:
    """反函数：0..65535 → JC1 HF code（自测与日志用）。"""
    amp = max(0.0, min(65535.0, float(amp16)))
    idx = 0
    for i, k in enumerate(_HFA_KEYS):
        if amp <= k:
            idx = i
            break
    else:
        idx = len(_HFA_KEYS) - 1
    return idx * 2


def jc1_lf_amp16(lf_amp9: int) -> float:
    """JC1 LF 振幅（9 位，含中间档标志） → 0..65535 的归一化振幅。

    LF 表（SDL 的 `lfa[101][2]`）低字节从 0x40(0.0) 到 0x72(1.0)，
    共 50 步；bit8 置位表示"取两档之间的中间值"（再增加 51 个中间档）。
    所以整张表是 101 档：整数档 + 中间档交替排列。
    """
    v = int(lf_amp9) & 0x1FF
    low = v & 0xFF
    mid = bool(v & 0x100)
    if low <= JC1_LF_AMP_ZERO and not mid:
        return 0.0
    step = (low - JC1_LF_AMP_ZERO) * 2 + (1 if mid else 0)   # 0..100
    step = max(0, min(100, step))
    return 65535.0 * step / 100.0


# ---------------------------------------------------------------- 编码

def encode_jc2(hf_amp16: float, lf_amp16: float,
               hf_freq: int = JC2_HF_FREQ, lf_freq: int = JC2_LF_FREQ) -> bytes:
    """(hf_amp, lf_amp) → Joy-Con 2 的 5 字节震动编码。

    逐位照抄 `SDL_hidapi_switch2.c` 的 `EncodeHDRumble()`：

        rumble[0] = hf_freq & 0xFF
        rumble[1] = ((hf_amp >> 4) & 0xFC) | ((hf_freq >> 8) & 0x03)
        rumble[2] = (hf_amp >> 12) | (lf_freq << 4)
        rumble[3] = (lf_amp & 0xC0) | ((lf_freq >> 4) & 0x3F)
        rumble[4] = lf_amp >> 8

    并照抄它的**限幅**：`amp * RUMBLE_MAX / 65535`，RUMBLE_MAX = 29000。
    注意振幅是**跨字节**的（HF 占 rumble[1] 高 6 位 + rumble[2] 低 4 位，
    共 10 位；LF 占 rumble[3] 高 2 位 + rumble[4] 全 8 位），
    单独看某一个字节会在 bit12 处回绕 —— 这是编码本来的位分布，不是 bug。
    """
    hf = int(round(max(0.0, min(65535.0, hf_amp16)) * JC2_RUMBLE_MAX / 65535.0))
    lf = int(round(max(0.0, min(65535.0, lf_amp16)) * JC2_RUMBLE_MAX / 65535.0))
    hf_freq &= 0x3FF
    lf_freq &= 0x3FF

    return bytes((
        hf_freq & 0xFF,
        ((hf >> 4) & 0xFC) | ((hf_freq >> 8) & 0x03),
        ((hf >> 12) & 0xFF) | ((lf_freq << 4) & 0xF0),
        (lf & 0xC0) | ((lf_freq >> 4) & 0x3F),
        (lf >> 8) & 0xFF,
    ))


def decode_jc2(rumble5: bytes) -> tuple:
    """5 字节编码 → (hf_amp, lf_amp)，只用于自测与日志。"""
    if len(rumble5) < 5:
        return (0, 0)
    hf = ((rumble5[1] & 0xFC) << 4) | ((rumble5[2] & 0x0F) << 12)
    lf = (rumble5[3] & 0xC0) | (rumble5[4] << 8)
    return (hf, lf)


def jc1_block_to_jc2(blk: bytes):
    """JC1 4 字节块 → JC2 5 字节（**只搬振幅，频率用 JC2 原生高频**）。

    ★★★ 2026-11-17 定案：频率**不能**从 JC1 搬过来，方向是错的 ★★★

    依据（SDL 官方两个驱动的对比）：
      · SDL_hidapi_switch.c (JC1)  写死 k_usHighFreq=0x74 / k_ucLowFreq=0x3D
      · SDL_hidapi_switch2.c (JC2) 写死 rumble_hi_freq=0x187 / lo_freq=0x112

    0x187=391 是 **10 位**频率码，超出 JC1 的 8 位范围 —— 两套频率域
    **量纲不同，直接换算会把高频降成低频**。上一版用 jc1_freq 把
    0x187 搬到 0x74，结果震动变得比 NS2 原生低频、粗糙，就是这个问题。

    正确做法（照抄 SDL，也是 NS2 原生）：**频率锁 JC2 原生高频值，
    只把振幅忠实搬过去**。细腻度来自：
      ① 高频载频 0x187（NS2 原生，比 JC1 的 0x74 高一截）
      ② 12ms 刷新节奏（NS2 原生 RUMBLE_INTERVAL）
      ③ 振幅的完整 10 位映射（四种震动靠这个区分）

    返回 None 表示"不震"。
    """
    if len(blk) < 4:
        return None
    _hf_freq, hf_amp, _lf_freq, lf_amp = decode_jc1_block(blk)

    hf16 = jc1_hf_amp16(hf_amp)
    lf16 = jc1_lf_amp16(lf_amp)
    if hf16 <= 0 and lf16 <= 0:
        return None

    if RUMBLE_MODE == "basic":
        # 普通震动：不再区分 HF/LF 两路，把两者取最大后作为单一振幅，
        # 固定用 NS2 低频载频（0x112，更接近传统 ERM 的"嗡嗡"感）。
        amp = max(hf16, lf16)
        return encode_jc2(0.0, amp, hf_freq=JC2_LF_FREQ, lf_freq=JC2_LF_FREQ)

    # 频率用 JC2 原生高频（SDL 写死值 = NS2 原生），不搬 JC1 的低频
    return encode_jc2(hf16, lf16,
                      hf_freq=JC2_HF_FREQ, lf_freq=JC2_LF_FREQ)


def neutral_jc2() -> bytes:
    """JC2 的静音帧（振幅全 0，频率取默认值）。"""
    return encode_jc2(0.0, 0.0)


# ---------------------------------------------------------------- 组帧

_seq = 0
_seq_lock = threading.Lock()


def build_frame(rumble5: bytes) -> bytes:
    """5 字节编码 → 17 字节 BLE Output Report 0x01（含 **3 个子帧**）。

    ★★ 2026-11-19 关键改动：照 Pro2 的子帧结构，一包写满 3 个子帧。

    依据（XinHeLianSheng-Pro2-Bridge / Pro2NativeRumbleEncoder.cs）：
        每个电机块 = 1 字节头(0x5n) + 3 个子帧 × 5 字节
        每子帧 40 位 = HF频率(10) | HF振幅(10) | LF频率(10) | LF振幅(10)
    Pro2 一包 33 字节同时装左右两个电机块 × 3 子帧，
    所以**一次 BLE 写就覆盖 3 个时间片**。

    我们的左右手柄走**各自的 GATT 特征 UUID**（289326cb… / fa19b0fb…），
    不能像 Pro2 那样合并两侧；但可以把**本侧**从 1 个子帧扩到 3 个：
        [0]       report ID 0x00
        [1]       0x50 | seq
        [2:7]     子帧 0
        [7:12]    子帧 1
        [12:17]   子帧 2
    三个子帧填同一份震动内容（当前震动状态在未来 3 个时间片内保持不变）。

    效果：相同震动时长，BLE 写入次数降到约 1/3
    → 不再占满 BLE 时间槽 → 输入 notify 不再被饿死。
    """
    global _seq
    with _seq_lock:
        s = _seq & 0x0F
        _seq = (_seq + 1) & 0x0F
    b = bytearray(FRAME_LEN)
    b[0] = REPORT_ID_BT
    b[1] = 0x50 | s
    sub = bytes(rumble5[:5]).ljust(5, b"\x00")
    if RUMBLE_MODE == "basic":
        # 普通震动：只写 1 个子帧，其余留 0（最朴素的 Output 0x01）
        b[2:7] = sub
        return bytes(b)
    b[2:7] = sub
    b[7:12] = sub
    b[12:17] = sub
    return bytes(b)


def set_mode(mode: str) -> None:
    """运行时切换震动模式："hd" / "basic"（对照实验用）。"""
    global RUMBLE_MODE
    RUMBLE_MODE = "basic" if str(mode).lower() == "basic" else "hd"
    log.info("[HD震动] 模式切换为 %s", RUMBLE_MODE)


# ---------------------------------------------------------------- 发送器

def _default_writer(client, uuid, data, loop) -> None:
    """生产路径：把写交给 BLE 事件循环，阻塞等结果。

    ★★ 2026-11-19 关键修复（震动与操作无法共存的真正根因）★★

    链路事实（已核对 bedrock 源码与 main.py）：
      · BLE notify 回调（notification_handler → notify_duo_joycons → update()
        → gamepad.update() → _push()）**跑在 bleak 的 asyncio 事件循环里**；
      · 本函数的 write 也提交到**同一个事件循环**。
    于是震动写入与 notify 处理在同一条循环上串行排队：
      震动写得越勤，notify 回调就被排得越后 →
        输入回报延迟（不跟手）→ 久了主机判定超时（弹出「输入配置无效」）。

    原实现用 `fut.result(timeout=1.5)` **无限期阻塞 worker 线程等写完**，
    一旦某次写卡住（BLE 重传/协议栈抖动），worker 就停在那里，
    而 loop 里排队的写入任务越积越多 —— 把 notify 彻底压死。

    修法：给等待设**硬上限**。超时即放弃这一帧（震动是可丢的，
    输入不可丢），worker 立刻回到可服务状态，loop 不再积压。
    """
    import asyncio
    try:
        fut = asyncio.run_coroutine_threadsafe(
            client.write_gatt_char(uuid, data, response=False), loop)
        # 上限取一个报告周期的量级：超时宁可丢这一帧震动，
        # 也不能让 worker 长时间占着，把 notify 挤死。
        fut.result(timeout=0.05)
    except Exception:
        # 超时/已断开/取消：丢弃本帧。调用方会统计到 errors。
        raise



class HdRumbleSender:
    """把 JC1 震动块流式转发到一只 Joy-Con 2。

    设计要点（全部来自踩坑）：

    1. **独立线程**：蓝牙写偶尔阻塞 20ms+，绝不能在
       `_handle_output_report`（USB/IP 的 OUT 线程）里做，
       否则会把 IN 报告一起卡住 —— 表现是"一震就掉帧 / 摇杆卡顿"。
    2. **只保留最新一帧**：震动是"当前状态"语义，不是队列语义。
       积压会让震动延后几百毫秒，听起来像回音。
    3. **节流 + 去重**：见 MIN_INTERVAL_S / DEDUP_ENABLE。
    4. **震动保持**：收到震动后按 REFRESH_S 持续重发（SDL 同款机制），
       保持 HOLD_S 后转静音 —— 这是「持续震动 vs 轻弹一下」的关键。
       否则主机掉线/暂停时手柄会一直震。
    5. **自动降级**：HD 通道（GATT 0x0012）连续失败就回落到
       旧的 command 0x0A 通道，保证"至少还能震"。
    """

    STALE_WARN_AFTER = 6    # 连续失败这么多次时提示一次
    # 注：原 STALE_S（超时静音）已由模块级 HOLD_S + REFRESH_S 取代 ——
    # 现在是「到期前持续重发、到期后静音」，不再是「一超时就静音」。
    # ⚠ 2026-11-17：legacy 预置样本通道已彻底删除（照抄 Pro2 Bridge ——
    #   它的 switch2_gatt_send_rumble_stub 对预置样本直接返回
    #   ESP_ERR_NOT_SUPPORTED：「legacy rumble stub is unused」）。
    #
    #   该通道发的是 command 0x0A subcmd 0x02「播放预置样本 #1」，
    #   官方描述 `Low frequency buzz, ~1s`。回调每秒 200+ 次
    #   → 每秒重放 200 次「1 秒嗡鸣」→ LRA 持续过驱
    #   → 摇杆 ADC 被物理带偏。删掉后震动只有 HD 一条路。

    def __init__(self, side: str):
        """side: "left" / "right"（决定用哪个 GATT characteristic）。"""
        self.side = side
        self._uuid = UUID_RUMBLE_LEFT if side == "left" else UUID_RUMBLE_RIGHT
        self._client = None
        self._evloop = None
        self._pending = None
        self._last_sent = b""
        self._last_time = 0.0
        self._last_rx = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._mode = "hd"           # "hd" | "legacy"
        self._hd_fail = 0
        # 写执行器：签名 writer(client, uuid, data, loop) -> None，抛异常即失败。
        # 生产走事件循环；测试可替换成同步直调（避免 monkeypatch 全局）。
        self._writer = _default_writer
        self.enabled = True
        self.sent = 0
        self.dropped = 0
        self.errors = 0
        self._logged_first = False
        # 震动保持（见 REFRESH_S/HOLD_S 说明）
        self._active = b""          # 当前应持续重发的震动块（静音也存这里）
        self._hold_until = 0.0      # 保持到什么时候
        self._active_is_silence = False   # _active 是静音帧（需保持制动）
        self._silence_refresh_left = 0    # 静音期间还允许重发几帧

    # ---------------- 生命周期 ----------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="hd-rumble-" + self.side)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            try:
                t.join(timeout=1.0)
            except RuntimeError:
                pass
        self._thread = None

    def attach(self, client, loop) -> None:
        """绑定 BLE client 与它所属的事件循环（重连后必须重新调用）。

        只在 client 真正变化时才重置失败计数 —— 每帧都调会让
        "降级状态"被反复清零，HD 通道永远也降不下去。
        """
        with self._lock:
            changed = client is not self._client
            self._client = client
            self._evloop = loop
            if changed:
                self._hd_fail = 0
                self._mode = "hd"
                self._last_sent = b""

    def detach(self) -> None:
        with self._lock:
            self._client = None
            self._evloop = None

    # ---------------- 入口 ----------------

    def feed_block(self, blk: bytes) -> None:
        """喂一个 JC1 4 字节块（无阻塞，可在任意线程调用）。"""
        if not self.enabled or len(blk) < 4:
            return
        rumble5 = jc1_block_to_jc2(blk)
        if rumble5 is None:
            rumble5 = neutral_jc2()

        with self._lock:
            if self._pending is not None:
                self.dropped += 1
            self._pending = rumble5
            self._last_rx = time.monotonic()
            # ★ 记录"当前活动震动"，worker 会按 REFRESH_S 持续重发它。
            # 非静音块 → 记为持续震动；静音块 → 立即结束保持。
            if rumble5 == neutral_jc2():
                # ★ 静音也保持重发（制动 LRA），不是发一帧就停。
                #   2026-11-19：保持窗口从 100ms 缩到 SILENCE_HOLD_S，
                #   且 worker 里限制重发次数（见 _silence_refresh_left），
                #   避免静音期间仍以 83Hz 白占 BLE 时间槽。
                self._active = neutral_jc2()
                self._active_is_silence = True
                self._hold_until = time.monotonic() + SILENCE_HOLD_S
                self._silence_refresh_left = SILENCE_REFRESH_MAX
            else:
                self._active = rumble5
                self._active_is_silence = False
                self._hold_until = time.monotonic() + HOLD_S
                self._silence_refresh_left = 0
        self.start()

    def silence(self) -> None:
        """立即排一个静音帧并等它发出去（断开 / 退出时用）。"""
        if not self._last_sent or self._last_sent == neutral_jc2():
            return
        with self._lock:
            self._pending = neutral_jc2()
            self._last_rx = time.monotonic()
        self.start()
        time.sleep(MIN_INTERVAL_S * 3)

    # ---------------- 内部 ----------------

    def _worker(self) -> None:
        """发送线程体。

        名字不能叫 `_loop` —— 实例属性 self._loop 存的是
        BLE 事件循环，与同名方法互撞会把线程 target 变成
        None/object，Thread 启动即抛 TypeError 且静默死掉，
        表现就是「震动完全没有」。
        """
        while not self._stop.is_set():
            payload = None

            with self._lock:
                now = time.monotonic()
                if self._pending is not None:
                    payload = self._pending
                    self._pending = None
                elif self._active and now < self._hold_until:
                    # ★ 活动保持：按 REFRESH_S 重发 _active。
                    #   震动 → 维持马达运转（SDL 同款机制）
                    #   静音 → 只发有限几帧制动（SILENCE_REFRESH_MAX），
                    #          不持续刷，避免白占 BLE 时间槽
                    if now - self._last_time >= _refresh_interval():
                        if (not self._active_is_silence) or self._silence_refresh_left > 0:
                            payload = self._active
                            if self._active_is_silence:
                                self._silence_refresh_left -= 1
                        elif self._active_is_silence and self._silence_refresh_left <= 0:
                            # 制动帧已发够 → 结束保持，不再占用
                            self._active = b""
                            self._active_is_silence = False
                elif (self._active and now >= self._hold_until):
                    # 保持期结束
                    if self._active_is_silence:
                        # 静音保持已到期 → 清理，不再补发（避免死循环）
                        self._active = b""
                        self._active_is_silence = False
                    else:
                        # 震动保持到期（主机停写且没发静音块）→ 补一帧静音
                        self._active = b""
                        payload = neutral_jc2()

                if payload is not None:
                    # 去重只针对"非刷新帧"：主机连续写相同块时跳过，
                    # 但保持重发必须真的发出去（否则马达又停）。
                    is_refresh = (payload is self._active)
                    if (not is_refresh) and DEDUP_ENABLE and payload == self._last_sent:
                        payload = None
                    elif not is_refresh and now - self._last_time < MIN_INTERVAL_S:
                        self._pending = payload     # 太快，下轮再发
                        payload = None

            if payload is None:
                time.sleep(0.002)
                continue

            try:
                self._emit(payload)
                with self._lock:
                    self._last_sent = payload
                    self._last_time = time.monotonic()
                self.sent += 1
                self._diag_log(payload)
            except Exception as exc:      # noqa: BLE001
                self.errors += 1
                if self._mode == "hd":
                    self._hd_fail += 1
                    # 不再降级到预置样本通道（已删除）。持续失败就持续报，
                    # 让用户能看见「HD 写不进去」，而不是悄悄退化成嗡鸣。
                    if self._hd_fail == self.STALE_WARN_AFTER:
                        log.warning("[HD震动] %s HD 通道连续失败 %d 次，"
                                    "检查 GATT 0x0012 是否可写",
                                    self.side, self._hd_fail)
                if self.errors <= 5:
                    log.warning("[HD震动] %s 发送失败: %s: %s",
                                self.side, type(exc).__name__, exc)
                time.sleep(0.02)

    def _diag_log(self, rumble5: bytes) -> None:
        """首帧 / 起震 / 停震 / 每 200 帧 各打一行。

        震动 100Hz，全打会撑爆日志并阻塞事件循环（上一轮踩过）。
        但"起震/停震"是运维必须能看见的事件 —— 用它能直接判断
        「这次震动有没有真的送到手柄」，比每帧日志有用得多。
        """
        hf, lf = decode_jc2(rumble5)
        active = rumble5 != neutral_jc2()

        if not self._logged_first:
            self._logged_first = True
            log.info("[HD震动] %s 首帧已发出 mode=%s hf=%d lf=%d",
                     self.side, self._mode, hf, lf)
            self._logged_active = active
            return

        # 起震 / 停震的边沿
        if active != getattr(self, "_logged_active", False):
            self._logged_active = active
            if active:
                log.info("[HD震动] %s 起震 hf=%d lf=%d", self.side, hf, lf)
            else:
                log.info("[HD震动] %s 停震（累计 %d 帧 / 丢弃 %d / 失败 %d）",
                         self.side, self.sent, self.dropped, self.errors)
            return

        if self.sent % 200 == 0:
            log.info("[HD震动] %s 累计 %d 帧（丢弃 %d / 失败 %d）",
                     self.side, self.sent, self.dropped, self.errors)

    def _emit(self, rumble5: bytes) -> None:
        with self._lock:
            client = self._client
            loop = self._evloop
        if client is None or loop is None:
            return

        uuid = self._uuid
        data = build_frame(rumble5)

        self._writer(client, uuid, data, loop)
        self._hd_fail = 0            # 成功即清零



# ---------------------------------------------------------------- 单例注册表
#
# 谁持有 sender？
#   * vjoy_out（USB/IP 输出层）要**喂**块 —— 它在 _handle_output_report 路径上
#   * duo_joycon / single_joycon 要**绑定** client+loop —— 只有它知道 BLE 连接
# 两边都不能各存一份（会产生两个线程、两份节流状态），所以放模块级单例。

_SENDERS = {}
_SENDERS_LOCK = threading.Lock()


def get_sender(side: str) -> "HdRumbleSender":
    """取（或惰性创建）某一侧的发送器。side: "left" / "right"。"""
    side = "left" if side == "left" else "right"
    with _SENDERS_LOCK:
        s = _SENDERS.get(side)
        if s is None:
            s = HdRumbleSender(side)
            _SENDERS[side] = s
        return s


def attach_client(side: str, client, loop) -> None:
    """BLE 连上后调用一次。"""
    get_sender(side).attach(client, loop)


def detach_client(side: str) -> None:
    """BLE 断开时调用：先静音再解绑。"""
    s = _SENDERS.get(side)
    if s is not None:
        try:
            s.silence()
        except Exception:       # noqa: BLE001
            pass
        s.detach()


def set_enabled(enabled: bool) -> None:
    """GUI 的"启用震动反馈"开关接到这里。"""
    enabled = bool(enabled)
    with _SENDERS_LOCK:
        senders = list(_SENDERS.values())
    for s in senders:
        s.enabled = enabled
        if not enabled:
            try:
                s.silence()
            except Exception:   # noqa: BLE001
                pass


def stats() -> dict:
    """诊断用：每侧发送统计。"""
    with _SENDERS_LOCK:
        return {k: {"sent": v.sent, "dropped": v.dropped,
                    "errors": v.errors, "mode": v._mode}
                for k, v in _SENDERS.items()}


# ---------------------------------------------------------------- 自测

def _self_test() -> None:
    """纯函数自测，不依赖硬件。`python -m virtual.rumble_hd` 可直接跑。"""
    # 1) 中性块必须解成 0
    assert is_neutral(JC1_NEUTRAL), "中性块被判成在震"
    assert encode_jc2(0.0, 0.0) == neutral_jc2()

    # 2) 满幅 HF
    full_hf = bytes((0x74, 0xC8, 0x40, 0x40))     # freq=0x074, amp=0xC8
    hf, amp, _lf_freq, _lf_amp = decode_jc1_block(full_hf)
    assert hf == 0x074, hex(hf)
    assert amp == 0xC8, hex(amp)
    assert jc1_hf_amp16(0xC8) == 65535.0
    assert jc1_hf_amp16(0x02) == 514.0

    # 3) 满幅 LF
    full_lf = bytes((0x74, 0x00, 0x72, 0x72))
    _a, _b, _c, lfa = decode_jc1_block(full_lf)
    assert lfa == 0x072, hex(lfa)
    assert jc1_lf_amp16(0x072) == 65535.0
    assert jc1_lf_amp16(0x040) == 0.0

    # 4) 编码与 SDL 的极值对齐（29000 = 0x7148，丢掉低 4 位 → 0x7140）
    assert decode_jc2(encode_jc2(65535.0, 65535.0)) == (0x7140, 0x7140)

    # 5) 组帧
    f = build_frame(neutral_jc2())
    assert len(f) == FRAME_LEN
    assert f[0] == 0x00 and (f[1] & 0xF0) == 0x50

    # 6) 单调性：振幅越大，编码里的振幅字段越大（跨字节拼接后比较）
    prev = -1
    for code in range(0x00, 0xCA, 0x02):
        cur = decode_jc2(encode_jc2(jc1_hf_amp16(code), 0.0))[0]
        assert cur >= prev, (hex(code), cur, prev)
        prev = cur

    prev = -1
    for step in range(0, 101):
        cur = decode_jc2(encode_jc2(0.0, 65535.0 * step / 100.0))[1]
        assert cur >= prev, (step, cur, prev)
        prev = cur

    # 7) HF 必须与 SDL 原表逐项一致（不能自己算指数近似）
    #    抽样对照 sdl_switch.c 的 hfa[]：
    assert jc1_hf_amp16(0x02) == 514
    assert jc1_hf_amp16(0x10) == 2192
    assert jc1_hf_amp16(0x20) == 7698
    assert jc1_hf_amp16(0x40) == 15067
    assert jc1_hf_amp16(0x80) == 30134
    assert jc1_hf_amp16(0xC8) == 65535
    #    反函数自洽
    for code in range(0x00, 0xCA, 0x02):
        assert jc1_hf_amp16_to_code(jc1_hf_amp16(code)) == code, hex(code)

    # 8) 端到端：一个真实强度的块
    blk = bytes((0x74, 0x40, 0x3D, 0x50))
    out = jc1_block_to_jc2(blk)
    assert out is not None and len(out) == 5
    hf_amp, lf_amp = decode_jc2(out)
    assert hf_amp > 0 and lf_amp > 0, (hf_amp, lf_amp)

    # 9) 全零块 → 静音
    assert jc1_block_to_jc2(bytes(4)) == neutral_jc2()

    print("[rumble_hd] self-test OK")


if __name__ == "__main__":
    _self_test()
