"""虚拟 Joy-Con 1 输出层。

接口与 `vgamepad.VX360Gamepad` 完全一致，Joy2Win 的调用代码一行不用改：
    update() / reset() / press_button(n) / release_button(n)
    left_joystick(x,y) / right_joystick(x,y) / left_trigger(v) / right_trigger(v)
    register_notification(cb)

按键值的来源
------------
Joy2Win 的 `controls` 表里，值来自 `vgamepad.XUSB_BUTTON` 枚举，
实测量值（vgamepad 0.1.0）：

    A=0x1000  B=0x2000  X=0x4000  Y=0x8000
    LEFT_SHOULDER=0x0100   RIGHT_SHOULDER=0x0200
    BACK=0x0020   START=0x0010
    LEFT_THUMB=0x0040   RIGHT_THUMB=0x0080
    DPAD_UP=0x0001  DOWN=0x0002  LEFT=0x0004  RIGHT=0x0008
    GUIDE=0x0400

之前用"按钮编号 1/2/3..."去映射，跟真实枚举值完全对不上，
结果所有按键都被丢弃 —— 表现就是"按键完全没反应"。
"""
from __future__ import annotations

import logging
import pathlib
import sys
import threading
import time

_ROOT = pathlib.Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

from virtual.imu_proc import imu  # noqa: E402

# ---- XUSB 按钮位（与 vgamepad.XUSB_BUTTON 同值，实测取得）----
PAD_DPAD_UP = 0x0001
PAD_DPAD_DOWN = 0x0002
PAD_DPAD_LEFT = 0x0004
PAD_DPAD_RIGHT = 0x0008
PAD_START = 0x0010
PAD_BACK = 0x0020
PAD_LEFT_THUMB = 0x0040
PAD_RIGHT_THUMB = 0x0080
PAD_LEFT_SHOULDER = 0x0100
PAD_RIGHT_SHOULDER = 0x0200
PAD_GUIDE = 0x0400
PAD_A = 0x1000
PAD_B = 0x2000
PAD_X = 0x4000
PAD_Y = 0x8000

# 扳机用两个不冲突的私有标记位
PAD_LT = 0x01000000
PAD_RT = 0x02000000
# SL / SR / Capture 在 XInput 里没有原生对应键，
# 但 Joy-Con 1 有这三个物理键，必须能传过去。
# 用高位私有标记，避免和真实 XUSB 位冲突。
PAD_SL_L = 0x04000000
PAD_SR_L = 0x08000000
PAD_SL_R = 0x10000000
PAD_SR_R = 0x20000000
PAD_CAPTURE = 0x40000000


class VirtualJoyCon1:
    """一只或多只虚拟 Joy-Con 1（USB/IP）。"""

    def __init__(self, side: str = "both"):
        self.side = side.lower()
        self._lock = threading.Lock()
        self._buttons: set[int] = set()
        # 摇杆初始值为 XInput 中位 0（-32768..32767 区间的中心）。
        # 注意：这里存的不是 Joy-Con 的 12 位值，转换在 _push 里做。
        self._lx = self._ly = self._rx = self._ry = 0
        self._bridge = None
        self._slots: dict[str, dict] = {}
        # ★ 必须先初始化：__init__ 末尾会调 _ensure()，而 ensure_side()
        #   开头读 self._server，缺这个属性会 AttributeError，
        #   表现就是"第二只手柄连不上"（2026-11-17 实测）。
        self._server = None
        self._ready = False
        self._pushed = 0
        self._failed = 0
        self._vibration_cb = None
        # 体感（Joy-Con 1 原始量纲）：accel 单位 1/4096 G，gyro 单位 0.06103 dps
        self._bits_l = 0
        self._bits_r = 0
        self._stick_l = (2048, 2048)   # 12 位中位
        self._stick_r = (2048, 2048)
        self._imuraw_l = None    # (ax,ay,az,gx,gy,gz) 报告值
        self._imuraw_r = None

        # 构造时就把虚拟设备建出来。之前只在 update() 里懒加载，
        # 导致外部拿 _slots 时永远是空的（手柄没数据进来就不会建）。
        self._ensure()
        self._logged_buttons: set[int] = set()

    # ---------------- 与 vgamepad 同名 ----------------

    def press_button(self, button) -> None:
        b = int(button)
        with self._lock:
            self._buttons.add(b)
        if b not in self._logged_buttons:
            self._logged_buttons.add(b)
            log.info("按钮按下值 0x%04X", b)
            print(f"[Joy-Con 1] 按下 0x{b:04X}", flush=True)
        self.update()

    def release_button(self, button) -> None:
        b = int(button)
        with self._lock:
            self._buttons.discard(b)
        self.update()

    # ================= Joy-Con 原生接口 =================
    # 直接接收语义位和原始摇杆值，不做 XInput 翻译。

    def set_buttons(self, left_bits=None, right_bits=None) -> None:
        """直接写入语义按键位（Ns2Bit 的组合）。"""
        with self._lock:
            if left_bits is not None:
                self._bits_l = left_bits
            if right_bits is not None:
                self._bits_r = right_bits


    def set_imu_raw(self, side: str, raw6: tuple) -> None:
        """写入一帧 IMU：经 imu() 映射后缓存。"""
        sample = imu(side, raw6)
        with self._lock:
            if side == "left":
                self._imuraw_l = sample
            else:
                self._imuraw_r = sample

    # 中央死区（LSB）：围绕**标准中心 2048**（与 SPI 0x603D 声明一致）。
    #
    # ★ 2026-11-19 关键改动：死区吸附目标从"实测中心 2040/2166"改为**固定 2048**。
    #
    #   原因：SPI 现在声明 center=2048（照 viiper 的 nspro 实现），
    #   若报告里回中值仍是 2040/2166，两者差 8~182 LSB → SDL 归一化后
    #   就是固定的非零轴值 = 永久回中偏移。
    #   让报告中心与声明中心都为 2048，才是 viiper 之所以永不偏移的根本原因。
    #
    #   死区宽度沿用实测结论：JC2 右摇杆静止后物理回中会偏离中心 50~52 LSB
    #   （60 秒/2500 帧 raw trace），取 96 可覆盖该偏差 + 波动。
    STICK_DEADBAND = 96

    # JC2 手柄的**物理**回中基准（用于把 raw 换算到标准中心 2048）
    # 左 (2040,2166) / 右 (1987,1984)，来自 47 次标定样本中位数。
    _PHYS_CENTER = {"L": (2040, 2166), "R": (1987, 1984)}
    _STD_CENTER = 2048

    # ★ 2026-11-19 新增：物理行程 → 满量程 2047 的拉伸比例基准
    #
    # 问题：SPI 现在声明行程 2047（为满足官方 sanity check 门槛 ≥1237），
    #   但 JC2 硬件各方向真实行程只有约 970~1224 LSB
    #   （实测 L: X +1209/-984, Y +1133/-1224；R: X +1003/-1216, Y +1142/-1155）。
    #   若不补偿，推满只有 970/2047 ≈ 47% 行程 —— 就是"行程非常小、到不了边界"。
    #
    # 修法：在重基准之后，把偏离量按 2047/物理行程 放大，使推满正好落到满量程。
    #   取 900（略小于实测最小行程 984/1003）：保证**全部 8 个方向推满都能饱和到边界**
    #   （离线验算：phys=930 时 8/8 饱和；取 900 留余量，兼容手柄个体差异与老化）。
    #   行程更大的方向会被 4095 边界夹住，即轻微饱和，这正是要的效果。
    #
    # 注意：此项只影响行程，不影响回中（回中偏离为 0，放大后仍为 0）。
    _PHYS_TRAVEL = 900

    def set_stick(self, side: str, x: int, y: int) -> None:
        """写入摇杆值 —— JC2 原始 12 位 → 重基准 2048 + 死区 + 行程拉伸。

        ★ 2026-11-19 定案（照 viiper 语义 + 本机实测行程补偿）：
          1. 先减物理中心、再加标准中心 → 回中值落在 2048，
             与 SPI 声明的 center=2048 严格一致；
          2. 死区把中心附近抖动夹成精确 2048 → SDL 归一化后精确为 0；
          3. 超出死区的偏离量按 2047/_PHYS_TRAVEL 放大 → 推满到达边界。
        """
        from virtual.reports import JoyConEncoder
        key = "L" if side == "left" else "R"
        px, py = self._PHYS_CENTER[key]
        std = self._STD_CENTER
        x, y = int(x), int(y)
        # 1) 重基准：物理中心 -> 标准中心 2048
        x = x - px + std
        y = y - py + std

        # 2) 死区 + 3) 行程拉伸（对超出死区的偏离量线性放大）
        dz = self.STICK_DEADBAND
        full = 2047              # 满量程（与 SPI 声明一致）
        phys = self._PHYS_TRAVEL
        scale = full / float(phys) if phys else 1.0

        def remap(v: int) -> int:
            d = v - std
            if abs(d) <= dz:
                return std
            # 死区外：先扣掉死区宽度，再放大，偏移死区边界不跳变
            sign = 1 if d > 0 else -1
            mag = (abs(d) - dz) * scale + dz
            out = std + sign * mag
            return int(round(out))

        x, y = remap(x), remap(y)

        with self._lock:
            v = (max(0, min(4095, x)), max(0, min(4095, y)))
            if side == "left":
                self._stick_l = v
            else:
                self._stick_r = v

    def left_joystick(self, x: int, y: int) -> None:
        with self._lock:
            self._lx, self._ly = int(x), int(y)
        self.update()

    def right_joystick(self, x: int, y: int) -> None:
        with self._lock:
            self._rx, self._ry = int(x), int(y)
        self.update()

    def left_trigger(self, value: int) -> None:
        with self._lock:
            if int(value) > 127:
                self._buttons.add(PAD_LT)
            else:
                self._buttons.discard(PAD_LT)
        self.update()

    def right_trigger(self, value: int) -> None:
        with self._lock:
            if int(value) > 127:
                self._buttons.add(PAD_RT)
            else:
                self._buttons.discard(PAD_RT)
        self.update()

    def reset(self) -> None:
        with self._lock:
            self._buttons.clear()
            self._lx = self._ly = self._rx = self._ry = 0
        self.update()

    def register_notification(self, callback) -> None:
        self._vibration_cb = callback

    def unregister_notification(self) -> None:
        self._vibration_cb = None

    # ---------------- 震动：HD 直投 + 旧 XInput 兼容 ----------------

    def _make_rumble_cb(self, side: str):
        """构造 hid.rumble_cb。

        签名：cb(left_block: bytes, right_block: bytes)，每侧 4 字节。

        ═══ 这是 HD 震动问题的核心修复 ═══

        旧实现做的是：把 blk[1] 当 small、blk[3] 当 large，
        直接夹到 0..255 后当 XInput 的强弱传下去。
        两个致命信息损失：

        1. **二值化**：blk[1] 是"频率码 bit0 + 振幅 bit1..7"混在一起的字节，
           blk[3] 是低频振幅低 8 位（0x40 = 0，0x72 = 满）。直接把字节值
           当强度传下去，结果是"要么不震、要么满幅"，中间力度全丢。
        2. **走错通道**：XInput 那套（large/small motor）在 Joy-Con 上
           被映射成 command 0x0A 的预置样本，只能"嗡一声"，
           无法还原 HD 强弱。JC2 真正的 HD 通道是 GATT 0x0012 的
           Output Report 0x01（16 字节 Packed rumble data）。

        现在：原始 4 字节块**原样**喂给 HdRumbleSender，
        由它解振幅 → 编成 JC2 的 10 位编码 → 写 GATT 0x0012。
        **旧 XInput / 预置样本路径已彻底删除**（照抄 Pro2 Bridge：
        预置样本 stub 直接返回 NOT_SUPPORTED）。
        """
        def _cb(lb, rb):
            blk = bytes(lb if side == "left" else rb)
            if len(blk) < 4:
                return
            # ① HD 通道：保真（唯一的震动路径）
            try:
                from virtual.rumble_hd import get_sender
                get_sender(side).feed_block(blk[:4])
            except Exception:               # noqa: BLE001
                pass
            # ② 旧 XInput / 预置样本通道：**已删除**（2026-11-17）。
            #
            # 照抄 XinHeLianSheng-Pro2-Bridge 的做法：它的
            # `switch2_gatt_send_rumble_stub` 对预置样本路径直接
            #     return ESP_ERR_NOT_SUPPORTED;
            # 并计数 rumble_preset_ignored ——
            # 「legacy rumble stub is unused; rumble is handled by the HD stream path」。
            #
            # 本项目的旧路径发的是 command 0x0A subcmd 0x02「播放预置样本 #1」，
            # 官方描述 `Low frequency buzz, ~1s`。回调每秒 200+ 次
            # → 每秒重放 200 次「1 秒嗡鸣」→ LRA 持续过驱
            # → 摇杆 ADC 被物理带偏。这是「震动导致摇杆偏移」的物理根因。
            # 而且那段计算每帧都在做、结果喂给一个空实现，纯浪费。
            #
            # 现在：震动只有 HD 一条路（GATT 0x0012，振幅逐帧映射）。

        return _cb

    def ensure_side(self, left: bool, right: bool) -> None:
        """按需补齐缺失的一侧，**不拆已连上的那侧**。

        ⚠ 2026-11-16 修复（真机 bug）：
          原实现是 `_teardown()` 再 `_ensure()` —— 整个拆掉重建。
          两只手柄连接时，第二只触发重建，**左手柄的虚拟设备被拆掉**，
          重建时 usbip 端口(3240) 常因句柄未释放而失败，
          表现就是「只连上一个，另一个连不上，必须重启程序」。

          现在：已经 attach 的侧完全不动，只 start 新侧。
          usbip 支持在同一 server 上追加设备，不需要重启 server。
        """
        want = []
        if left:
            want.append("left")
        if right:
            want.append("right")
        if not want:
            return
        if set(want) <= set(self._slots.keys()):
            return                      # 需要的侧都已存在，什么都不做

        if self._server is None:
            # 还没有 server：一次性建全（首次连接路径）
            self.side = "both" if len(want) == 2 else want[0]
            self._ready = False
            self._ensure()
            return

        # 已有 server：只补缺失侧，已连的侧不动
        missing = [w for w in want if w not in self._slots]
        self.side = "both" if len(want) == 2 else want[0]
        self._add_sides(missing)

    def update(self) -> None:
        if not self._ensure():
            return
        try:
            self._push()
        except Exception as exc:  # noqa: BLE001
            self._failed += 1
            if self._failed <= 5:
                log.warning("推送失败 %s: %s", type(exc).__name__, exc)

    # ---------------- 内部 ----------------

    def _teardown(self) -> None:
        try:
            from virtual.bridge import find_usbip
            exe = find_usbip()
            if exe:
                import subprocess
                for info in self._slots.values():
                    for args in ([exe, "detach", "--busid", info["busid"]],
                                 [exe, "detach", "-b", info["busid"]]):
                        try:
                            from hidden_exec import run_hidden
                            run_hidden(args, timeout=8)
                        except Exception:  # noqa: BLE001
                            pass
        except Exception:  # noqa: BLE001
            pass
        srv = getattr(self, "_server", None)
        if srv is not None:
            try:
                srv.stop()
            except Exception:  # noqa: BLE001
                pass
        self._slots.clear()
        self._server = None
        import time as _t
        _t.sleep(1.0)

    @staticmethod
    def _alloc_busid(server) -> str:
        """分配一个未被占用的 busid（"1-1" / "1-2" / ...）。

        ═══ 为什么要这个函数 ═══
        原实现有两条建设备路径，编号规则不一致：
          * _ensure   按 targets 顺序 enumerate(start=1)
          * _add_sides 按侧写死 left=1 / right=2
        只先连右手时 right 占住 "1-1"；后来追加左手算出也是 "1-1"，
        撞上已存在 → `continue` 跳过 → **左手虚拟设备永远建不出来**。
        表现：左手柄 BLE 连得上、能震（震动走 BLE GATT 不经过 usbip），
        但 Windows 里根本没有 PID_2006 设备。

        现在统一从空闲索引取，两条路径不会撞。
        """
        used = set()
        devices = getattr(server, "_devices", {}) or {}
        for busid in devices:
            try:
                used.add(int(str(busid).split("-")[-1]))
            except (ValueError, IndexError):
                continue
        n = 1
        while n in used:
            n += 1
        return f"1-{n}"

    def _add_sides(self, sides) -> None:
        """在**已有的** server 上追加设备，不动已 attach 的侧。

        这是 ensure_side 增量路径的实现：
        首次连左手柄建立 left；再连右手柄时只追加 right，
        left 的 server/busid/attach 全部保持原样。
        """
        if not sides or self._server is None:
            return
        try:
            from virtual import descriptors as D
            from virtual.hid_function import Switch1HidFunction, DEFAULT_PERIOD_MS
            from virtual.usbip import ExportDevice
            from hidden_exec import run_hidden
            from virtual.bridge import find_usbip

            server = self._server
            exe = find_usbip()

            for s_ in sides:
                key = "joyconL" if s_ == "left" else "joyconR"
                spec = D.DEVICES[key]
                # busid 从空闲索引取，绝不复用已占用的编号。
                # 旧实现写死 left=1-1 / right=1-2，与 _ensure 的
                # enumerate(start=1) 撞车 —— 见 _alloc_busid 的说明。
                busid = self._alloc_busid(server)
                idx = int(busid.split("-")[-1])

                hid = Switch1HidFunction(spec, key, period_ms=DEFAULT_PERIOD_MS)
                dev = ExportDevice(
                    path=f"/sys/devices/virtual/usbip/{busid}",
                    busid=busid,
                    busnum=1,
                    devnum=idx,
                    speed=spec.speed,
                    vid=spec.vid,
                    pid=spec.pid,
                    bcd_device=spec.bcd_device,
                    b_device_class=spec.b_device_class,
                    b_device_sub_class=spec.b_device_sub_class,
                    b_device_protocol=spec.b_device_protocol,
                    b_configuration_value=1,
                    b_num_configurations=1,
                    interfaces=[(0x03, 0x00, 0x00)],
                )

                # 震动回调：HD 直投 + 旧 XInput 兼容（见 _make_rumble_cb）
                hid.rumble_cb = self._make_rumble_cb(s_)

                server.add_device(busid, dev, hid)
                self._slots[s_] = {"hid": hid, "busid": busid, "spec": spec}

                if exe:
                    try:
                        r = run_hidden(
                            [exe, "attach", "-r", "127.0.0.1",
                             "-b", busid], timeout=30)
                        out = (r.stdout or "") + (r.stderr or "")
                        if "success" in out.lower() or r.returncode == 0:
                            log.info("追加侧 %s attach 成功 (%s)", s_, busid)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as exc:  # noqa: BLE001
            log.warning("追加侧失败 %s: %s", sides, exc)

    def _ensure(self) -> bool:
        if self._ready:
            return True
        try:
            from virtual import descriptors as D
            from virtual.hid_function import Switch1HidFunction, DEFAULT_PERIOD_MS
            from virtual.usbip import (
                ExportDevice,
                ServerConfig,
                UsbIpServer,
            )
            targets = []
            if self.side in ("left", "both"):
                targets.append(("left", "joyconL"))
            if self.side in ("right", "both"):
                targets.append(("right", "joyconR"))

            server = UsbIpServer(ServerConfig(host="127.0.0.1", port=3240,
                                             busnum=1, devnum=1))
            for s, key in targets:
                spec = D.DEVICES[key]
                hid = Switch1HidFunction(spec, key, period_ms=DEFAULT_PERIOD_MS)
                # 与 _add_sides 共用分配器：顺次得到 1-1 / 1-2，
                # 但不会与追加路径撞号（那才是左手失灵的根因）。
                busid = self._alloc_busid(server)
                idx = int(busid.split("-")[-1])
                dev = ExportDevice(
                    path=f"/sys/devices/virtual/usbip/{busid}",
                    busid=busid,
                    busnum=1,
                    devnum=idx,
                    speed=spec.speed,
                    vid=spec.vid,
                    pid=spec.pid,
                    bcd_device=spec.bcd_device,
                    b_device_class=spec.b_device_class,
                    b_device_sub_class=spec.b_device_sub_class,
                    b_device_protocol=spec.b_device_protocol,
                    b_configuration_value=1,
                    b_num_configurations=1,
                    interfaces=[(0x03, 0x00, 0x00)],
                )
                server.add_device(busid, dev, hid)
                self._slots[s] = {"hid": hid, "busid": busid, "spec": spec}

                # 震动回调：HD 直投 + 旧 XInput 兼容（见 _make_rumble_cb）
                #
                # **回调签名**：hid.rumble_cb 的签名是 cb(left_block, right_block)，
                # 每侧 4 字节，由 hid_function._handle_output_report 同步调用。
                # 旧实现把它错当 vgamepad 的 6 参数回调，
                # 每次调用都抛 TypeError 被 except 吞掉 —— 表现就是"震动完全没有"。
                hid.rumble_cb = self._make_rumble_cb(s)

            server.start()
            self._server = server

            from virtual.bridge import find_usbip
            exe = find_usbip()
            attached = 0
            if exe:
                import subprocess
                for s, info in self._slots.items():
                    try:
                        from hidden_exec import run_hidden
                        r = run_hidden(
                            [exe, "attach", "-r", "127.0.0.1",
                             "-b", info["busid"]], timeout=30)
                        out = (r.stdout or "") + (r.stderr or "")
                        if "success" in out.lower() or r.returncode == 0:
                            attached += 1
                    except Exception:  # noqa: BLE001
                        pass

            self._ready = True
            # **启动独立推送线程**
            #
            # 为什么必须有它：
            # 中断 IN 请求会挂起在服务端的 _pending_in 队列里，
            # 等 kick_input 回填。而 kick_input 只在手柄有数据时才被调用。
            # SDL / 驱动在"打开设备"阶段就会发 IN 请求 —— 这时手柄可能
            # 静止无数据，于是一直等不到报告，打开失败。
            #
            # 这个线程按固定频率无条件推送，保证任何时候都有报告可读。
            self._stop_push = False
            self._push_thread = threading.Thread(
                target=self._auto_push, daemon=True,
                name="joycon1-push")
            self._push_thread.start()

            msg = (f"[Joy-Con 1] 虚拟设备就绪：{len(self._slots)} 只，"
                   f"attach {attached} 只")
            log.info(msg)
            print(msg, flush=True)
            return True
        except Exception as exc:  # noqa: BLE001
            msg = f"[Joy-Con 1] 启动失败: {type(exc).__name__}: {exc}"
            log.error(msg)
            print(msg, flush=True)
            return False

    def _auto_push(self) -> None:
        """固定频率无条件推送，保证主机任何时候都能读到报告。

        SDL / 模拟器打开设备时会发中断 IN 请求；若服务端手里没数据，
        请求就挂起、打开超时。这个线程解决这个问题。

        ★ 2026-11-19：间隔回到 33ms。
          `hid.pending_in` 现在采用**缓存报告**路径（主机问得快就直接回上一帧），
          不再需要本线程高频回填；33ms 只用于保证"永远有报告可读"。
          过高频率（曾试 5ms）会频繁重写 _state 并抢 GIL，反而造成卡顿。
        """
        interval = 1.0 / 30.0
        while not getattr(self, "_stop_push", True):
            try:
                if self._slots:
                    self._push()
            except Exception:
                pass
            time.sleep(interval)

    def _push(self) -> None:
        """把当前状态推给虚拟设备。

        只用**原生字段**（_bits_l/_bits_r/_stick_l/_stick_r/_accel/_gyro），
        不再有任何 XInput 位翻译。
        """
        from virtual.reports import Ns2Bit, PadState

        with self._lock:
            left_bits = Ns2Bit(self._bits_l)
            right_bits = Ns2Bit(self._bits_r)
            sl, sr = self._stick_l, self._stick_r

        def to12(v: int) -> int:
            """摇杆值 -> 12 位（仅边界保护，不改数值）。

            原始值直接透传，任何换算都应避免（历史上二次映射出过多次错）。
            """
            return 0 if v < 0 else (4095 if v > 4095 else int(v))

        for key, bits, stick in (
            ("left", left_bits, sl),
            ("right", right_bits, sr),
        ):
            info = self._slots.get(key)
            if info is None:
                continue

            st = PadState()
            st.buttons = bits
            sx, sy = to12(stick[0]), to12(stick[1])
            if key == "left":
                st.lx, st.ly = sx, sy
            else:
                st.rx, st.ry = sx, sy
            # IMU 只有一条通路：set_imu_raw -> imu_proc -> _imuraw_*。
            raw = self._imuraw_l if key == "left" else self._imuraw_r
            if raw is not None:
                st.accel = raw[0:3]
                st.gyro = raw[3:6]
            else:
                # 尚无数据 / 手柄断开：发静止帧（重力沿按钮法线，gyro 全 0）。
                st.accel = (0, 0, 4096)
                st.gyro = (0, 0, 0)

            info["hid"].set_state(st)
            devid = self._server._busid_devid.get(info["busid"])
            if devid is not None:
                self._server.kick_input(devid)

        self._pushed += 1
