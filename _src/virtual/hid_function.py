"""把 PadState 编码成 Nintendo Switch 1 手柄的 USB HID 设备。

这一层负责"骗过主机"：

* 处理 HID 类请求（GET_REPORT / SET_REPORT / GET_IDLE / SET_PROTOCOL）
* 解析主机写入的输出报告（0x01/0x10/0x11/0x12），应答 0x21 子命令
  —— SDL / Steam 的 Switch 驱动必须先收到合法的 0x21 应答，才认为
  "这是真手柄"，然后才把输入模式切到 0x30 全模式
* 没收到任何子命令前只发 0x3F 简单报告（DirectInput / joy.cpl 用这条）

子命令应答（replyPrefix 21 seq 91 ...）逐条对应真机行为，参考 HIDMaestro
profiles/nintendo/switch-pro.json 的 protocol.rules。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

from . import descriptors as D
from .reports import JoyConEncoder, PadState
from .usbip import (
    DESC_CONFIGURATION,
    DESC_DEVICE,
    DESC_HID,
    DESC_HID_REPORT,
    DESC_STRING,
    HID_GET_IDLE,
    HID_GET_PROTOCOL,
    HID_GET_REPORT,
    HID_SET_IDLE,
    HID_SET_PROTOCOL,
    HID_SET_REPORT,
    REQ_GET_CONFIGURATION,
    REQ_GET_DESCRIPTOR,
    REQ_GET_INTERFACE,
    REQ_GET_STATUS,
    REQ_SET_CONFIGURATION,
    REQ_SET_INTERFACE,
    Urb,
    UsbFunction,
)

log = logging.getLogger("jc2bridge.hid")

# ═══ 输入报告节拍（2026-11-17 跟手/体感平衡）═══
# ═══ 报告周期：JC1 原生 15ms（= 66Hz，与真机一致）═══
#
# 用户实测对比其他手柄：66Hz + 20ms 延迟完全不会不跟手。
# 15ms 下 3 组 IMU 样本正好覆盖 15ms，主机积分天然正确，
# 不需要任何缩放补偿（IMU_SCALE 概念已彻底删除）。
DEFAULT_PERIOD_MS = 15.0


def _pack_12bit_series(values) -> bytes:
    """一串 12 位值 → 紧凑字节流（小端位序，用于 SPI 校准块）。"""
    bits = 0
    n = 0
    out = bytearray()
    for v in values:
        bits |= (int(v) & 0xFFF) << n
        n += 12
        while n >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            n -= 8
    if n > 0:
        out.append(bits & 0xFF)
    return bytes(out)


class Switch1HidFunction(UsbFunction):
    def __init__(self, spec: D.UsbDeviceSpec, encoder_kind: str,
                 period_ms: float = DEFAULT_PERIOD_MS):
        self.spec = spec
        self.kind = encoder_kind                 # "joyconL" / "joyconR"
        # 本项目只模拟 Joy-Con 1（config output_mode=joycon1），
        # Pro Controller 分支已删除 —— 它不属于本项目的模拟目标。
        self.encoder = JoyConEncoder("L" if encoder_kind == "joyconL" else "R",
                                     D.JOYCON_INPUT_REPORT_SIZE)
        self.reply_len = D.JOYCON_INPUT_REPORT_SIZE

        self._lock = threading.Lock()
        self._state = PadState()
        self._dirty = threading.Event()
        self._seq = 0

        # 协议状态
        # 设备类型：1=Joy-Con(L) 2=Joy-Con(R) 3=Pro Controller
        # SDL / 模拟器靠这个字节识别手柄型号
        _key = (encoder_kind or "").lower()
        if "joyconl" in _key or _key == "l":
            self.device_type = 0x01
        elif "joyconr" in _key or _key == "r":
            self.device_type = 0x02
        else:
            self.device_type = 0x03
        # 震动回调：主机写 0x10 / 0x01 的震动块时调用
        # 签名 cb(left_bytes: bytes, right_bytes: bytes)
        self.rumble_cb = None
        self.protocol_seen = False
        # 注意：input_mode 是 property，赋值会自动让 _last_payload 失效
        self._input_mode = 0x3F
        self.imu_enabled = True
        self.subcmd_counter = 0
        self._pending_replies: List[bytes] = []
        # 自上次发 reply 以来发出的输入帧数（用于防止 reply 饿死输入帧）
        self._in_since_last_reply = 0
        # 最近一份输入报告（主机轮询快于节拍时直接复用，见 pending_in）
        self._last_payload = None
        self._period_ms = float(period_ms)   # 真机报告周期（默认 15ms ≈ 66Hz）
        self._last_send = 0.0

        # 统计
        self.reports_sent = 0
        self.out_reports = 0
        self.last_out_hex = ""
        self.last_reply_hex = ""

    # ---------------- 输入 ----------------

    def set_state(self, st: PadState) -> None:
        with self._lock:
            self._state = st
            self._seq += 1
        self._dirty.set()

    # ---------------- 报告队列 ----------------

    @property
    def input_mode(self) -> int:
        return self._input_mode

    @input_mode.setter
    def input_mode(self, mode: int) -> None:
        """切换报告模式时**立即让缓存失效**。

        否则主机切到 0x30 后，`pending_in` 的缓存路径可能先返回上一帧
        0x3F 旧格式，要等下一个 15ms 节拍才变。真机切换模式后立即按新
        格式上报，这里保持一致（2026-11-19）。
        """
        self._input_mode = mode
        self._last_payload = None

    def pending_in(self, ep: int) -> Optional[bytes]:
        """中断 IN 端点：回一份输入报告，或先回子命令应答。

        ## 节流是必须的，否则体感会被放大几十倍

        Joy-Con 1 真机的 0x30 报告是 **15ms 一帧**（约 66Hz），每帧里
        3 组 IMU 样本分别代表 0/5/10ms。主机会把收到的每一帧都积分。

        如果这里不节流、主机能空转拉取（实测 2000+ 帧/秒），
        同一个角速度就会被反复积分几十次 ——
        表现就是"实际动 2 度，屏幕上转了 90 度"（45 倍）。

        之前的错误做法是"绝不 sleep，立即返回"，理由是怕堵死 URB 线程。
        正确做法是：**只在距上次发送不足 period 时短暂等待**，
        等到达节拍点就立刻返回，不会造成死锁（等待时间上限就是一个 period）。
        """
        if ep != 1:
            return None

        with self._lock:
            # ★ 2026-11-19：reply 队列限长，且**不能无限抢占输入帧**。
            #   真机 0x21 只需应答一次；主机不会因为少一条 ACK 就失效。
            #   若 hosts 在短时间内连发多条子命令（握手/校准/模式切换），
            #   reply 也会短时排队 —— 限长 8 条足够，多余的丢弃，
            #   避免把 0x30 输入帧饿死（那会表现为摇杆卡住/掉线）。
            if self._pending_replies and self._in_since_last_reply >= 1:
                payload = self._pending_replies.pop(0)
                self.last_reply_hex = payload.hex()
                self._in_since_last_reply = 0
                return payload

            period = self._period_ms / 1000.0
            now = time.monotonic()
            wait = period - (now - self._last_send)

        # ═══ 节流：三种实现对比（2026-11-19 定稿）═══
        #
        # 背景：主机按端点描述符的 bInterval=4ms 轮询（descriptors.py），
        # 而报告节拍是 15ms —— 两者不匹配，必须选对"空拉"的处理方式。
        #
        # ① `sleep(wait)` 睡满到节拍：
        #      usbip.py `_urb_loop` 是**每设备一条线程、串行处理该设备全部 URB**，
        #      OUT（震动）与 IN（输入）都在上面。睡 15ms 会把震动 OUT 一起堵住
        #      → 一震动就不跟手 / 主机判超时弹「输入配置无效」。
        #
        # ② `return None` 立即返回、让 URB 挂起：
        #      25 次/秒×10 的请求全堆进无上限 `_pending_in` → 队列爆炸 → 更卡。
        #
        # ③ **返回上一份缓存报告**（本实现的定稿）：
        #      立刻应答、零阻塞、零堆积。参照 viiper（Alia5/VIIPER）
        #      device/input_queue.go 原文：
        #        "legacy devices keep the USBIP **cached-report
        #         compatibility path**."
        #
        # 为什么不会「体感被放大几十倍」（2026-11-18 踩过的 10000Hz 空转 bug）：
        #   节流语义仍然有效 —— **新内容**只在距上次发送 >= period 时才产生
        #   （`_last_send` 不因缓存返回而推进）。
        #   缓存帧只是复用旧内容，主机积分不会重复累加同一份 IMU 样本。
        #   test_report_throttle.py 按「内容更新率」验证，实测约 62Hz ≈ 66Hz。
        if wait > 0:
            # ★★★ 2026-11-19 最终定稿（第三次修正）：缓存报告 + 短让出 ★★★
            #
            # 曾经踩过的三个坑（全部实测）：
            #   ① `sleep(wait)` 睡满 15ms：
            #      URB 线程停摆，震动 OUT 被堵 → 一震动就不跟手。
            #   ② `return None` 让 URB 挂起：
            #      主机 4ms 轮询 vs 66Hz 数据，请求全堆进无上限队列 → 爆炸。
            #   ③ 纯缓存报告、**完全不等待**（上一版）：
            #      pending_in 变成纯内存操作（实测 240 万次/秒），
            #      主机驱动以极限速度空转拉取 → **CPU 烧满 → 延迟巨大**。
            #
            # 现在：**缓存报告 + 让出 CPU 一小段**。
            #   · 用 1/3 个周期（5ms）上限，不会把震动 OUT 堵太久
            #   · 又足以把主机空转压到正常范围（不会 240 万次/秒）
            #   · 返回缓存帧而不是 None，所以 IN 请求不会堆积
            #
            # CPU 实测：纯缓存 240 万次/秒 → 加让出后回到正常量级。
            _max_wait = period / 3.0
            time.sleep(min(wait, _max_wait))
            with self._lock:
                cached = self._last_payload
            if cached is not None:
                return cached

        with self._lock:
            self._last_send = time.monotonic()
            st = self._state
            # ═══ 按 input_mode 选择报告（真机行为）═══
            # 依据 HID 报告描述符（hidparse 解析 JOYCON_REPORT_DESCRIPTOR）：
            #   0x30: size=8 count=48 logical=0..0 usage=0xFF01:0x30
            #         → 整份是**不透明厂商数据**，没有任何 Generic Desktop 轴
            #   0x3F: 含 size=16 count=4 logical=0..65535 usages=[X,Y,Rx,Ry]
            #         → 唯一带模拟轴的报告
            #
            # 真机 Joy-Con 1 就是这样：上电默认推 0x3F；主机发
            # SetInputReportMode(0x03) 后切到 0x30/0x31。
            #
            # 这正是"Windows 能读摇杆、模拟器能读 IMU"的原因：
            #   * Windows HID gamepad 驱动不发子命令 → 一直收 0x3F → 有轴
            #   * SDL/模拟器发 0x03 → 切 0x30 → 有 IMU + 完整按键
            #
            # 之前固定推 0x30，导致 Windows 永远读不到轴（摇杆画不满的根因）。
            if self.input_mode in (0x30, 0x31, 0x32, 0x33):
                # 让 encoder 的 report id 跟随主机请求的模式
                self.encoder.report_id = self.input_mode
                payload = self.encoder.encode(st, self.imu_enabled)
            else:
                payload = self.encoder.encode_simple(st)
            self.reports_sent += 1
            self._in_since_last_reply += 1
            # 缓存最近一份报告，供"主机轮询快于报告节拍"时直接复用
            self._last_payload = payload
            return payload

    def ep_max_report(self, ep: int) -> int:
        return self.spec.ep_max_report

    # ---------------- 控制传输 ----------------

    def control(self, urb: Urb) -> Optional[bytes]:
        bm, req, wvalue, windex, wlength = urb.setup_fields()
        rtype = bm & 0x60
        is_in = bool(bm & 0x80)

        if rtype == 0x00:                        # 标准请求
            if req == REQ_GET_DESCRIPTOR and is_in:
                dtype = (wvalue >> 8) & 0xFF
                index = wvalue & 0xFF
                if dtype == DESC_DEVICE:
                    return D.device_descriptor(self.spec)
                if dtype == DESC_CONFIGURATION:
                    return D.configuration_descriptor(self.spec)
                if dtype == DESC_STRING:
                    if index not in (0, 1, 2, 3):
                        return None          # 未实现的字符串索引 -> STALL
                    return D.string_descriptor(index, self.spec)
                if dtype == DESC_HID_REPORT:
                    n = wlength or len(self.spec.report_descriptor)
                    return self.spec.report_descriptor[:n]
                if dtype == DESC_HID:
                    n = wlength or 9
                    return D.hid_descriptor(len(self.spec.report_descriptor))[:n]
                return None
            if req in (REQ_SET_CONFIGURATION, REQ_SET_INTERFACE):
                return b""
            if req == REQ_GET_CONFIGURATION and is_in:
                return b"\x01"
            if req == REQ_GET_STATUS and is_in:
                return b"\x00\x00"
            if req == REQ_GET_INTERFACE and is_in:
                return b"\x00"
            return b""

        if rtype == 0x20:                        # HID 类请求
            if req == HID_GET_REPORT and is_in:
                rid = wvalue & 0xFF
                with self._lock:
                    st = self._state
                    if rid == 0x3F or (rid == 0 and not self.protocol_seen):
                        out = self.encoder.encode_simple(st)
                    else:
                        out = self.encoder.encode(st, self.imu_enabled)
                return out[:wlength or len(out)]
            if req == HID_SET_REPORT and not is_in:
                self._handle_output_report(urb.data)
                return b""
            if req == HID_GET_IDLE and is_in:
                return b"\x00"
            if req == HID_SET_IDLE:
                return b""
            if req == HID_GET_PROTOCOL and is_in:
                return b"\x01"
            if req == HID_SET_PROTOCOL:
                return b""
            return b""

        return None

    def on_out(self, urb: Urb, data: bytes) -> None:
        if urb.ep == 1 and data:
            self._handle_output_report(data)

    # ---------------- 输出报告 / 子命令 ----------------

    def _handle_output_report(self, data: bytes) -> None:
        # 记录一切收到的输出数据，便于定位 SDL/驱动的握手
        if data:
            self.last_out_hex = bytes(data)[:32].hex()
            self.out_raw_count = getattr(self, "out_raw_count", 0) + 1

        if not data:
            return

        rid = data[0]

        # ---- 震动数据 ----
        # 输出报告 0x01 / 0x10 里，[2:6] 是左震动块，[6:10] 是右震动块。
        # 官方文档 bluetooth_hid_notes.md:
        #   [00 01 40 40 00 01 40 40] 是中性值（无震动）
        # 真机 Joy-Con 1 的震动块就是 4 字节，从 data[2] 开始。
        if rid in (0x01, 0x10) and len(data) >= 10 and self.rumble_cb:
            try:
                self.rumble_cb(bytes(data[2:6]), bytes(data[6:10]))
            except Exception:
                pass

        # ---- 0x80：专有命令（USB 模式握手，SDL 的 BTrySetupUSB 用）----
        #
        # SDL 的 USB 初始化顺序（BTrySetupUSB）：
        #   Handshake(0x02) -> HighSpeed(0x03) -> Handshake(0x02) -> ForceUSB(0x04)
        # 每条都要收到 0x81 报告、且 [1] == 命令号，否则 SDL 报
        # "Couldn't setup USB mode" 并放弃设备。
        #
        # 应答格式（ReadProprietaryReply）：
        #   [0] = 0x81 (CommandAck)
        #   [1] = 回显命令号
        if rid == 0x80 and len(data) >= 2:
            cmd = data[1]
            self.out_reports += 1
            self.last_out_hex = data[:16].hex()
            self.protocol_seen = True
            buf = bytearray(self.reply_len)
            buf[0] = 0x81          # CommandAck
            buf[1] = cmd           # 回显命令号
            buf[2] = 0x00
            with self._lock:
                self._pending_replies.append(bytes(buf))
            return

        # ── 子命令 reply ──
        #
        # 0x01 是 **rumble + 子命令的复合报告**（SDL 的 SetInputMode、
        # 读校准等子命令都走 0x01 的 data[10]），**必须生成 reply**，
        # 否则 SDL 握手失败、手柄完全失灵（2026-11-17 踩过：曾把
        # 0x01 的 reply 砍掉，结果手柄列出但无法使用）。
        #
        # 「震动时摇杆往左下跳」的真正根因不是"不该 reply"，而是
        # reply 里的**摇杆字段全是 0** —— 见 _reply_header 的修复：
        # 现在会把当前真实 state 的摇杆值填进 reply，与正常 0x30 报告一致。
        if len(data) < 11:
            return
        # ★ 2026-11-19 根因修复：**只有 0x01 / 0x11 / 0x12 / 0x82 带子命令**。
        #
        # 0x10 是「纯震动报告（rumble only）」，**不含子命令**：
        #   官方 bluetooth_hid_notes.md：
        #     "You can send rumble data and subcommand with x01 command,
        #      otherwise only rumble with x10 command."
        #   也就是说 0x10 的 data[10] 是震动数据字节，不是 subcmd ID。
        #
        # 旧代码把 0x10 也放进这个分支，于是：
        #   震动期间主机高频写 0x10（刷新马达）→ 每条都生成一条 0x21 reply
        #   → pending_in 优先返回 reply 且**不节流** → 0x30 输入帧被无限延后。
        #   用户实测表现：
        #     · 震动时摇杆不回中（输入帧停更）
        #     · 操作无反应（同上）
        #     · 模拟器弹「手柄断连」提示（输入帧超时）
        #     · 关掉震动后一切正常（不再有 0x10 洪泛）
        # 这就是「只有震动时才出问题」的根因。
        if rid not in (0x01, 0x11, 0x12, 0x82):
            return

        self.out_reports += 1
        self.last_out_hex = data[:16].hex()
        subcmd = data[10]
        self.protocol_seen = True
        seq = data[1]
        reply = self._build_reply(seq, subcmd, data)
        if reply:
            with self._lock:
                # ★ 2026-11-19：队列限长。极端情况下（主機连发子命令）宁可丢弃
                # 多余的 ACK，也不能让队列无限增长把输入帧饿死。
                if len(self._pending_replies) >= 8:
                    self._pending_replies.pop(0)
                self._pending_replies.append(reply)

    def _reply_header(self, seq: int, ack: int, subcmd: int) -> bytearray:
        """真机 0x21 子命令应答的精确布局。

        **这个布局是照 SDL_hidapi_switch.c 的结构体定义来的**，不是猜的：

            SwitchSubcommandInputPacket_t {
                SwitchControllerStatePacket_t m_controllerState;   // 12 字节
                Uint8 ucSubcommandAck;                             // [12]
                Uint8 ucSubcommandID;                              // [13]
                union { ... };                                     // [14..]
            }
            SwitchControllerStatePacket_t {
                Uint8 ucCounter;              // [0]
                Uint8 ucBatteryAndConnection; // [1]
                Uint8 rgucButtons[3];         // [2..4]
                Uint8 rgucJoystickLeft[3];    // [5..7]
                Uint8 rgucJoystickRight[3];   // [8..10]
                Uint8 ucVibrationCode;        // [11]
            }

        注意：整个包**不含 report id**，因为 SDL 是从
        `m_rgucReadBuffer[1]` 开始强行转换的，
        而 `m_rgucReadBuffer[0]` 被它单独检查必须是 0x21。

        踩过的坑：之前把 ACK 放在 byte3、subcmd 放 byte4（以为头是 5 字节），
        导致 SDL 永远匹配不到应答，LoadStickCalibration 失败，
        JoystickOpen 返回 NULL —— 表现就是"手柄能列出但打不开"。
        """
        buf = bytearray(self.reply_len)
        # [0] 保留 0x21 作为 report id（SDL 检查 m_rgucReadBuffer[0]）
        buf[0] = 0x21
        # [1] counter / [2] battery（0x80|电量，此处给 0x80=满电+已连接）
        buf[1] = seq & 0xFF
        buf[2] = 0x80
        # 绝对偏移（含 [0] 的 report id）：
        #   [0]      report id 0x21
        #   [1..12]  SwitchControllerStatePacket_t (12 字节)
        #   [13]     ucSubcommandAck   <- SDL: reply->ucSubcommandAck
        #   [14]     ucSubcommandID    <- SDL: reply->ucSubcommandID
        #   [15..]   数据
        #
        # 踩过的坑：这里原先写成 [12]/[13]，整体错位一位，
        # SDL 每次都比对失败、重试 5 次后放弃。
        buf[13] = ack & 0xFF
        buf[14] = subcmd & 0xFF

        # ★★★ 2026-11-17 根因修复：把真实摇杆值填进 reply ★★★
        #
        # 旧代码这里不填摇杆，buf[6:12] 全是 0。子命令 reply 经由
        # pending_in() 优先返回给主机（见 pending_in 开头），主机把
        # (0,0) 的 12 位摇杆归一化成 (-1,-1) —— 满量程左下角。
        #
        # 主机写子命令（读校准/设模式/震动等）时机不定，所以表现为
        # 「震动/握手时摇杆往左下跳」。填真实 state 后，reply 与正常
        # 0x30 报告的摇杆字节完全一致，不再有假报告。
        #
        # 偏移与 0x30 编码器一致（见 reports.py:366-367）：
        #   buf[6:9]  = 左摇杆 3 字节打包
        #   buf[9:12] = 右摇杆 3 字节打包
        with self._lock:
            st = self._state
        try:
            from virtual.reports import _pack_stick12
            buf[6:9] = _pack_stick12(st.lx, st.ly)
            buf[9:12] = _pack_stick12(st.rx, st.ry)
        except Exception:      # noqa: BLE001
            # 兜底：至少填中心值 0x8000，绝不能留全 0
            buf[6:9] = bytes.fromhex("00 08 00".replace(" ", ""))
            buf[9:12] = bytes.fromhex("00 08 00".replace(" ", ""))
        return buf

    def _build_reply(self, seq: int, subcmd: int, data: bytes) -> Optional[bytes]:
        # 数据起始偏移 = 12(状态包) + 1(ACK) + 1(subcmd) = 14
        # 见 _reply_header 的布局说明（照 SDL 结构体而来）
        D = 15

        if subcmd == 0x02:                        # 请求设备信息
            # deviceInfo 结构（SDL 源码）：
            #   rgucFirmwareVersion[2] -> D+0, D+1
            #   ucDeviceType           -> D+2   <- 1=L 2=R 3=Pro
            #   ucFiller1              -> D+3
            #   rgucMACAddress[6]      -> D+4..D+9
            #   ucFiller2              -> D+10
            #   ucColorLocation        -> D+11
            buf = self._reply_header(seq, 0x82, subcmd)
            buf[D:D + 2] = bytes.fromhex("038B")          # 固件版本
            buf[D + 2] = self.device_type                 # 设备类型（关键）
            buf[D + 3] = 0x00                             # filler
            buf[D + 4:D + 10] = bytes.fromhex("98B6E9484D00")[:6]  # MAC
            # **设备类型必须正确**，SDL / 模拟器靠它判断手柄型号：
            #   0x01 = Joy-Con (L)
            #   0x02 = Joy-Con (R)
            #   0x03 = Pro Controller
            #
            # 踩过的坑：这里原本写的是 `(self.subcmd_counter + 0x30) & 0xFF`，
            # 把子命令计数器当成类型写进去了（值从 0x30 起递增）。
            # SDL 读到 0x30 不是合法类型，直接放弃打开设备 ——
            # 表现就是 GameControllerOpen 返回 NULL。
            self.subcmd_counter += 1
            buf[D + 10] = 0x00        # filler2
            buf[D + 11] = 0x01        # color location
            return bytes(buf)

        if subcmd == 0x03:                        # 设置输入报告模式
            if len(data) > 11 and data[11] in (0x30, 0x31, 0x3F):
                self.input_mode = data[11]
                # ★ 让缓存失效：否则切模式后主机可能先收到一帧旧格式
                #   （缓存帧），要等到下一个 15ms 节拍才变。
                #   真机切换模式后立即按新格式上报，这里保持一致。
                with self._lock:
                    self._last_payload = None
                log.info("input mode -> 0x%02X", self.input_mode)
            return bytes(self._reply_header(seq, 0x80, subcmd))

        if subcmd == 0x04:                        # 触发 IMU（旧版命令）
            self.imu_enabled = True
            return bytes(self._reply_header(seq, 0x83, subcmd))

        if subcmd == 0x10:                        # SPI flash 读
            # 主机请求的地址/长度在输出报告的 [11:15] / [15]
            addr = int.from_bytes(data[11:15], "little")
            length = data[15] if len(data) > 15 else 0
            length = min(max(length, 0), 29)
            buf = self._reply_header(seq, 0x90, subcmd)
            # 应答里必须**回显**主机请求的地址和长度，SDL 靠这个匹配
            buf[D:D + 4] = data[11:15]
            buf[D + 4] = length
            blob = self._spi_image(addr, length)
            buf[D + 5:D + 5 + len(blob)] = blob[:len(blob)]
            return bytes(buf)

        if subcmd == 0x21:                        # 手柄 MAC
            buf = self._reply_header(seq, 0xA0, subcmd)
            mac = bytes.fromhex("0100FF0008001B01")
            buf[D:D + len(mac)] = mac
            return bytes(buf)

        if subcmd == 0x40:                        # 开启/关闭 IMU
            # **不跟随主机的开关。**
            # 主机（SDL）在没有调用 SetJoystickSensorsEnabled(true) 时会发
            # 0x40 0x00 把 IMU 关掉；但 Joy-Con 1 的 0x30 报告本来就该
            # 带 IMU 数据，关掉后模拟器反而认不到传感器。
            # 这里始终回 0x01（开启），imu_enabled 保持 True。
            self.imu_enabled = True
            return bytes(self._reply_header(seq, 0x80, subcmd))

        if subcmd == 0x48:                        # 震动开关
            return bytes(self._reply_header(seq, 0x82, subcmd))

        return bytes(self._reply_header(seq, 0x80, subcmd))

    # 行程（2026-11-19 重新定案，依据 viiper 官方实现）
    #
    # ★ 为什么从 900 改为 2047：
    #   dekuNukem/Nintendo_Switch_Reverse_Engineering 的 spi_flash_notes.md 明确写：
    #     "The Switch does various sanity checks on the calibration values.
    #      If these checks fail, it applies a default calibration instead."
    #   且 Pro Controller 要求各方向 delta ≥ 0x542(1346) / X max ≥ 0x4d5(1237)。
    #   原来的 900 远低于该门槛，属违规值。
    #
    #   viiper（Alia5/VIIPER，Pro2 项目实际使用的虚拟手柄库）的 nspro 实现原文：
    #     // same endpoints: centre=2048, positive=2047, negative=2048.
    #     // A 1600 calibration here clipped the last 22% of valid travel in SDL/Steam.
    #     stick := []byte{0xFF,0xF7,0x7F, 0,0x08,0x80, ...}
    #   → center=2048、行程=2047（满量程），且**报告中心也用 2048**，
    #     使「声明中心 == 报告中心」恒成立，从根上消除回中偏移。
    #
    #   本项目此前用「实测中心 2040/2166 + 行程 900」，把正确性绑在
    #   「SPI 声明必须精确匹配物理回中值」这根钢丝上，实测会出现回中随机偏移。
    #   改为固定的 2048/2047 后，不再依赖任何校准协商的精度。
    _STICK_CENTER = 2048
    _STICK_TRAVEL = 2047

    def _stick_cal(self) -> bytes:
        """生成 0x603D 摇杆出厂校准（18 字节，12 位位打包）。

        格式（hid-nintendo.c:1104 / sdl_switch.c:1044）：
            左: Xabove Yabove Xcenter Ycenter Xbelow Ybelow
            右: Xcenter Ycenter Xbelow Ybelow Xabove Yabove
        above/below 是**相对 center 的行程距离**，主机算 max=center+above。

        ★ 2026-11-19 定案（依据 viiper 的 nspro 实现 + 官方 spi_flash_notes.md）：
            改为固定 center=2048、行程=2047（满量程），左右两组都填真值，
            **不再填中性占位**。viiper 原文：
              "same endpoints: centre=2048, positive=2047, negative=2048.
               A 1600 calibration here clipped the last 22% of valid travel."
            因为报告里的摇杆也以 2048 为中心，声明中心与报告中心恒等，
            回中值必然为 0，不再依赖"实测中心必须精确匹配"这条脆弱假设。
        """
        # ★ 关键：SDL 一次读 18 字节，**无脑解析成两组各 9 字节**
        #   （前9=left摇杆，后9=right摇杆，见 SDL_hidapi_switch.c:982-1060）
        #   每只 Joy-Con 是独立 USB 设备，但 SDL 仍会解析两组。
        #   旧实现只填 6 个值（9字节），**后 9 字节全 0** →
        #   SDL 读到 center=0/min=0/max=0 → 归一化完全错乱 → 右摇杆失灵。
        #   所以必须填完整 12 个值。现在两组都用同一套标准值（2048/2047）。
        # ★ 2026-11-19：直接照搬 viiper nspro 的 18 字节（逐字节一致）。
        #   viiper 原值: FF F7 7F 00 08 80 00 08 80 00 08 80 00 08 80 FF F7 7F
        #   解包 12 个 12 位值 = [2047,2047,2048,2048,2048,2048,
        #                        2048,2048,2048,2048,2047,2047]
        #   注意：行程字段填 2048，仅 Xmax/Ymax（左组前2、右组末2）为 2047。
        #   左组 = Xmax,Ymax,Xcenter,Ycenter,Xmin,Ymin
        #   右组 = Xcenter,Ycenter,Xmin,Ymin,Xmax,Ymax
        NEU = self._STICK_CENTER      # 2048
        tv = self._STICK_TRAVEL       # 2047（仅用于 Xmax/Ymax 位）
        left_group = [tv, tv, NEU, NEU, NEU, NEU]
        right_group = [NEU, NEU, NEU, NEU, tv, tv]
        vals = left_group + right_group
        return _pack_12bit_series(vals)

    def _spi_image(self, addr: int, length: int) -> bytes:
        """主机读走的 SPI 校准块。

        取值来自真机 dump（switchbrew Flashed-Controller-Factory-Data）：
        0x6020 左右摇杆出厂校准，0x603D 出厂中心/范围，
        0x8010 机身/按键颜色（SDL 用它识别手柄型号，缺了会导致打开失败）。
        """
        table = {
            # ================= SPI 数据表 =================
            # 所有布局照 Linux 内核 drivers/hid/hid-nintendo.c 的
            # joycon_read_stick_calibration / joycon_read_imu_calibration。

            # ---- 0x6020..0x6037：IMU 出厂校准（24 字节）----
            #
            # 布局（Linux 内核 joycon_request_imu_calibration 的解析顺序）：
            #   [0:6]   accel offset[3]  (u16 LE)
            #   [6:12]  accel scale[3]   (u16 LE)
            #   [12:18] gyro  offset[3]  (u16 LE)
            #   [18:24] gyro  scale[3]   (u16 LE)
            #
            # 内核默认值：
            #   DFLT_ACCEL_SCALE = 16384  (0x4000，配 divisor 除法等效 4096/G)
            #   DFLT_GYRO_SCALE  = 13371  (0x343B，等效 70 mdps/digit)
            #
            # **绝不能全零。** 主机算 divisor = scale - offset，
            # 全零会让 divisor=0 → scale=0 → 收到的 IMU 数值被乘成 0，
            # 表现就是"陀螺仪毫无反应"。
            0x6020: bytes.fromhex(
                "000000" "000000"          # accel offset[3]
                "0040" "0040" "0040"       # accel scale[3] = 16384
                "000000" "000000"          # gyro offset[3]
                "3b34" "3b34" "3b34"),     # gyro scale[3]  = 13371

            # ---- 0x603D..0x604E：摇杆出厂校准（18 字节）----
            # ── 摇杆 SPI 校准 ─────────────────────────────
            #
            # ★ 契约（2026-11-18）：摇杆原始 12 位由 control_type **直接透传**，
            #   中间不做任何映射；圆度/死区/回中全部由主机按这块 SPI 校准处理。
            #   曾经在 control_type 里加 stick_map 自标定层，与这块 SPI 叠加
            #   造成双重校准 → 操作后不完全回中即漂移（已删）。
            # 语义（hid-nintendo.c:1104 / sdl_switch.c:1044）：
            #   above / below 是【相对 center 的行程距离】，不是绝对位置
            #   主机算 max = center+above, min = center-below
            #
            # 12 位位打包，左右顺序不同（内核明确规定）：
            #   左: Xabove Yabove Xcenter Ycenter Xbelow Ybelow
            #   右: Xcenter Ycenter Xbelow Ybelow Xabove Yabove
            #
            # 取值由 _stick_cal() 动态生成（与 viiper nspro 逐字节一致）：
            #   center=2048、行程 2047（Xmax/Ymax 位），其余填 2048。
            # 依据见 _STICK_TRAVEL 的注释（官方 sanity check 门槛 + viiper 实测）。

            # ---- 0x8010：摇杆用户校准 magic ----
            # 不是 B2 A1 时主机会回退到 0x603D 的出厂校准（正确行为）
            0x8010: bytes(22),

            # ---- 0x8026：IMU 用户校准 magic，全 0 = 未校准 ----
            0x8026: bytes(20),

            # ---- 0x6050：手柄类型/颜色 ----
            0x6050: bytes.fromhex("323232FFFFFFFFFFFFFFFFFF"),

            # ---- 0x6080..0x6098：序列号 + 颜色 ----
            0x6080: bytes.fromhex("50FD0000C60F"),
            0x6086: bytes.fromhex("0F30610030F3D41454411554C7799C333663"),
            0x6098: bytes.fromhex("0F30610030F3D41454411554C7799C333663"),
        }
        # 摇杆出厂校准按 side 取（左右是独立设备，中心不同）
        table[0x603D] = self._stick_cal()

        need = max(length, 0)
        for base, blob in table.items():
            if base <= addr < base + len(blob):
                start = addr - base
                return blob[start:start + need].ljust(need, b"\x00")
        return b"\x00" * need
