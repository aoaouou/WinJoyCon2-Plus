# -*- coding: utf-8 -*-
"""原生 Joy-Con 2 输出层（HIDMaestro 后端）。

架构
----
物理 JC2（蓝牙 BLE）→ 本项目控制器逻辑 → 本类 → TCP → HmBridge（C#，
管理员权限）→ HIDMaestro SDK → 虚拟原生 Joy-Con 2（VID 057E /
PID 2067 L · 2066 R，真机 100 字节 HID 描述符）。

与 VirtualJoyCon1 接口一致，controller_manager / control_type 一行不用改：
    set_buttons(left_bits, right_bits) / set_stick(side,x,y) /
    set_imu_raw(side, raw6) / update() / register_notification(cb) /
    ensure_side(left,right) / reset()

HIDMaestro 的两个关键事实（本机实测 + 上游源码）：
  · CreateController 要求管理员 token（machine-wide ownership claim）；
    所以桥接进程必须由 run_hidden(..., elevated=True) 提权启动。
  · UMDF2 后端虽然建出 HIDClass 节点，却不注册 HID 设备接口类
    （SetupAPI 枚举 25 个 HID 接口，0 个来自 UMDF2 设备）→ hidapi/SDL
    拿不到句柄。必须用 Usbip 后端（HidUsb 绑定 interface 0，正常注册接口）。
    实测：Canary / Steam 的 SDL3 都认出 `Nintendo Joy-Con 2 (L/R)` 并读到
    摇杆与按键数据。

震动
----
HmBridge 的 OutputDecoded 回调发 `OUT <side> <leftMotor> <rightMotor>`，
这里转成 JC2 的 HD 震动块喂给 rumble_hd 的 sender（GATT 0x0012），
保真 HD LRA，不退化成 XInput 预置样本。
"""
from __future__ import annotations

import logging
import pathlib
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

_ROOT = pathlib.Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from hidden_exec import run_hidden  # noqa: E402

log = logging.getLogger(__name__)

BRIDGE_PORT = 3250
_BRIDGE_EXE = "HmBridge.exe"
_PROFILES_DIR = "hidmaestro_profiles"

# ---- 真机握把 profile 的按钮位映射（静态推导，非直觉语义位）----
# HIDMaestro 自带 joycon-l-usb / joycon-r-usb 的 stateBlock 用 "#n" 把
# HMButton 第 n 位搬到 0x30 报告的特定位；SDL HandleCombinedControllerStateL/R
# 又按自己的位置名读这些位。两者合成的映射是"故意错位"的，必须照表填：
#
#   L 半（SDL 组合模式读出）：
#     MINUS「−」→ 1<<8    LS 按下 → 1<<10   CAPTURE → 1<<13
#     L1        → 1<<14   ZL      → 1<<15（模拟满拉）
#     SL_L      → 1<<4    SR_L    → 1<<5
#   R 半：
#     A(位置) → 1<<3   B(位置) → 1<<1   X(位置) → 1<<2   Y(位置) → 1<<0
#     PLUS「+」→ 1<<9   RS 按下 → 1<<11  HOME    → 1<<12
#     R1      → 1<<14   ZR      → 1<<15（模拟满拉）
#     SL_R    → 1<<4    SR_R    → 1<<5
#
# ★ 方向键不能用按钮掩码：DPAD_* 是 32 位以外的 sentinel（1<<34..37），
#   桥接用 uint.Parse 解析会溢出 → 整帧报废。方向键改由 Hat（HatDegrees）
#   传，见 update()。ZL/ZR 也不要带 1<<32/33（同样溢出）。
_HM_MINUS = 1 << 8
_HM_LS = 1 << 10
_HM_CAPTURE = 1 << 13
_HM_L1 = 1 << 14
_HM_R1 = 1 << 14
_HM_TRIGGER = 1 << 15
_HM_SL = 1 << 4
_HM_SR = 1 << 5
_HM_L_HOME = 1 << 12
# R 半 ABXY（位置名）；slot 标签 #3=Y 却产生位置 A，反之亦然
_HM_R_POS_A = 1 << 3   # SDL SOUTH（Xbox 布局显示 A）
_HM_R_POS_B = 1 << 1   # SDL EAST（显示 B）
_HM_R_POS_X = 1 << 2   # SDL WEST（显示 X）
_HM_R_POS_Y = 1 << 0   # SDL NORTH（显示 Y）
_HM_PLUS = 1 << 9
_HM_RS = 1 << 11
_HM_HOME = 1 << 12


def _ns2_to_hm_jc2(bits: int, side: str) -> int:
    """Ns2Bit → 独立 JC2 profile 的 HMButton 掩码（语义位，直觉映射）。

    switch2-joycon-left/right.json 的 extendedReport 用语义名（A/B/X/Y/
    DPAD_*/LeftBumper…），不是握把 profile 的错位 "#n"，所以这里按语义给。
    """
    from virtual.reports import Ns2Bit
    b = int(bits)
    hm = 0
    if b & Ns2Bit.A:
        hm |= 1 << 0
    if b & Ns2Bit.B:
        hm |= 1 << 1
    if b & Ns2Bit.X:
        hm |= 1 << 2
    if b & Ns2Bit.Y:
        hm |= 1 << 3
    if b & Ns2Bit.L:
        hm |= 1 << 4
    if b & Ns2Bit.R:
        hm |= 1 << 5
    if b & Ns2Bit.MINUS:
        hm |= 1 << 6
    if b & Ns2Bit.PLUS:
        hm |= 1 << 7
    if b & Ns2Bit.LS:
        hm |= 1 << 8
    if b & Ns2Bit.RS:
        hm |= 1 << 9
    if b & Ns2Bit.HOME:
        hm |= 1 << 10
    if b & Ns2Bit.CAPTURE:
        hm |= 1 << 12
    if b & Ns2Bit.UP:
        hm |= 1 << 3   # 见 profile extendedReport byte3 位序
    if b & Ns2Bit.DOWN:
        hm |= 1 << 0
    if b & Ns2Bit.LEFT:
        hm |= 1 << 2
    if b & Ns2Bit.RIGHT:
        hm |= 1 << 1
    return hm & 0xFFFFFFFF


def _ns2_to_hm(bits: int, side: str) -> int:
    """Ns2Bit → 真机握把 profile 的 32 位 HMButton 掩码（按推导表）。"""
    from virtual.reports import Ns2Bit
    b = int(bits)
    hm = 0
    if side == "L":
        if b & Ns2Bit.MINUS:
            hm |= _HM_MINUS
        if b & Ns2Bit.LS:
            hm |= _HM_LS
        if b & Ns2Bit.CAPTURE:
            hm |= _HM_CAPTURE
        if b & Ns2Bit.L:
            hm |= _HM_L1
        if b & Ns2Bit.ZL:
            hm |= _HM_TRIGGER
        if b & Ns2Bit.SL_L:
            hm |= _HM_SL
        if b & Ns2Bit.SR_L:
            hm |= _HM_SR
    else:
        # R 半 ABXY 用位置映射（SDL SOUTH/EAST/WEST/NORTH）
        if b & Ns2Bit.A:
            hm |= _HM_R_POS_A
        if b & Ns2Bit.B:
            hm |= _HM_R_POS_B
        if b & Ns2Bit.X:
            hm |= _HM_R_POS_X
        if b & Ns2Bit.Y:
            hm |= _HM_R_POS_Y
        if b & Ns2Bit.PLUS:
            hm |= _HM_PLUS
        if b & Ns2Bit.RS:
            hm |= _HM_RS
        if b & Ns2Bit.HOME:
            hm |= _HM_HOME
        if b & Ns2Bit.R:
            hm |= _HM_R1
        if b & Ns2Bit.ZR:
            hm |= _HM_TRIGGER
        if b & Ns2Bit.SL_R:
            hm |= _HM_SL
        if b & Ns2Bit.SR_R:
            hm |= _HM_SR
    # C 键在 Switch 2 实机触发语音聊天，PC 上保留系统级切换，不进手柄掩码
    return hm & 0xFFFFFFFF


def _ns2_hat_degrees(bits: int, side: str):
    """方向键 → Hat 角度（0=N 顺时针）。无方向返回 None。

    DPAD_* 走 sentinel，只能经 HMGamepadState.HatDegrees 写入；桥接协议
    STATE 第 7 参数传这个角度。
    """
    from virtual.reports import Ns2Bit
    b = int(bits)
    up = bool(b & Ns2Bit.UP)
    down = bool(b & Ns2Bit.DOWN)
    left = bool(b & Ns2Bit.LEFT)
    right = bool(b & Ns2Bit.RIGHT)
    if up and right:
        return 45.0
    if right and down:
        return 135.0
    if down and left:
        return 225.0
    if left and up:
        return 315.0
    if up:
        return 0.0
    if right:
        return 90.0
    if down:
        return 180.0
    if left:
        return 270.0
    return None


class HidMaestroJoyCon2:
    """两只虚拟原生 Joy-Con 2（HIDMaestro 后端）。"""

    def __init__(self, side: str = "both", profile_set: str = None):
        self.side = side.lower()
        # profile_set：grip（充电握把 200E，功能全）/ jc2（独立 JC2 2067/2066）
        # 未显式指定时从 config 的 output_mode 决定。
        if profile_set is None:
            try:
                from config import Config
                m = str(Config().getConfig().get("output_mode", "hidmaestro")).strip().lower()
                profile_set = "jc2" if m in ("hidmaestro", "jc2", "jc2native") else "grip"
            except Exception:
                profile_set = "grip"
        self.profile_set = "jc2" if str(profile_set).lower() in ("jc2", "hidmaestro", "jc2native") else "grip"
        self._lock = threading.Lock()
        self._bits_l = 0
        self._bits_r = 0
        self._stick_l = (2048, 2048)
        self._stick_r = (2048, 2048)
        self._imu_l = (0.0,) * 6
        self._imu_r = (0.0,) * 6
        self._vibration_cb: Optional[Callable] = None
        self._sock: Optional[socket.socket] = None
        self._rbuf = bytearray()
        self._read_thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._started = False
        self._stop = False
        self._failed = 0
        self._ensure()

    # ---------- 生命周期 ----------

    def _bridge_paths(self):
        # 打包后资源在 _MEIPASS/hidmaestro_bridge；源码运行时 _ROOT 是
        # _src/virtual/，桥接在它的上一级 _src/hidmaestro_bridge/。
        base = pathlib.Path(getattr(sys, "_MEIPASS", None) or str(_ROOT.parent))
        # 源码运行：exe 在 hidmaestro_bridge/bin/；打包后：在 _MEIPASS/hidmaestro_bridge/
        exe = base / "hidmaestro_bridge" / "bin" / _BRIDGE_EXE
        if not exe.exists():
            exe = base / "hidmaestro_bridge" / _BRIDGE_EXE
        # profiles 唯一来源：_src/hidmaestro_profiles（打包后在 _MEIPASS/hidmaestro_bridge/）
        profiles = base / _PROFILES_DIR
        if not profiles.exists():
            profiles = base / "hidmaestro_bridge" / _PROFILES_DIR
        return str(exe), str(profiles)

    def _ensure(self) -> bool:
        if self._started:
            return True
        if getattr(self, "_init_failed", False):
            return False  # 失败只尝试一次，避免每帧提权重试
        exe, profiles = self._bridge_paths()
        if not pathlib.Path(exe).exists():
            log.error("HmBridge.exe 不存在: %s", exe)
            self._init_failed = True
            return False

        # 杀掉旧实例（可能占用 identity key）
        try:
            run_hidden(["taskkill", "/F", "/IM", _BRIDGE_EXE], timeout=8)
        except Exception:
            pass
        time.sleep(1)

        # 提权启动（CreateController 要管理员 token）。
        # run_hidden 是阻塞的 subprocess.run，这里要用 PowerShell 的
        # Start-Process -Verb RunAs 拉起独立的管理员进程。
        try:
            ps = (
                "Start-Process -FilePath '" + exe + "' "
                "-ArgumentList @('" + profiles + "','" + self.profile_set + "') "
                "-Verb RunAs -WindowStyle Hidden"
            )
            self._proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            log.error("启动 HmBridge 失败: %s", exc)
            self._init_failed = True
            return False
        time.sleep(6)

        # 连接并 INIT
        try:
            s = socket.create_connection(("127.0.0.1", BRIDGE_PORT), timeout=10)
            s.settimeout(0.3)
            self._sock = s
            self._send("HELLO")
            self._read_reply(2)
            self._send("INIT")
            ok = self._wait_ok(12)
            if not ok:
                log.error("HmBridge INIT 失败")
                self._close()
                self._init_failed = True
                return False
            self._send("SUB")
            self._read_reply(1)
        except Exception as exc:
            log.error("连接 HmBridge 失败: %s", exc)
            self._close()
            self._init_failed = True
            return False

        self._started = True
        self._stop = False
        self._read_thread = threading.Thread(target=self._reader, daemon=True)
        self._read_thread.start()
        log.info("HIDMaestro Joy-Con 2 已就绪（L+R）")
        return True

    def ensure_side(self, left: bool, right: bool) -> None:
        # 两只设备始终一起建（桥接 INIT 一次建 L+R），无需增量
        self._ensure()

    def reset(self) -> None:
        with self._lock:
            self._bits_l = self._bits_r = 0
            self._stick_l = self._stick_r = (2048, 2048)
            self._imu_l = self._imu_r = (0.0,) * 6
        self.update()

    def register_notification(self, callback) -> None:
        self._vibration_cb = callback

    def unregister_notification(self) -> None:
        self._vibration_cb = None

    # ---------- 输入写入 ----------

    def set_buttons(self, left_bits=None, right_bits=None) -> None:
        with self._lock:
            if left_bits is not None:
                self._bits_l = int(left_bits)
            if right_bits is not None:
                self._bits_r = int(right_bits)

    # 与 vjoy_out 一致的摇杆标定常数（物理中心 / 死区 / 行程）
    STICK_DEADBAND = 96
    _PHYS_CENTER = {"L": (2040, 2166), "R": (1987, 1984)}
    _STD_CENTER = 2048
    _PHYS_TRAVEL = 900

    def set_stick(self, side: str, x: int, y: int) -> None:
        """JC2 原始 12 位 → 重基准 2048 + 死区 + 行程拉伸（与 joycon1 路径一致）。"""
        key = "L" if side == "left" else "R"
        px, py = self._PHYS_CENTER[key]
        std = self._STD_CENTER
        x, y = int(x) - px + std, int(y) - py + std
        dz = self.STICK_DEADBAND
        scale = 2047 / float(self._PHYS_TRAVEL)

        def remap(v):
            d = v - std
            if abs(d) <= dz:
                return std
            sign = 1 if d > 0 else -1
            return int(round(std + sign * ((abs(d) - dz) * scale + dz)))

        v = (max(0, min(4095, remap(x))), max(0, min(4095, remap(y))))
        with self._lock:
            if side == "left":
                self._stick_l = v
            else:
                self._stick_r = v

    def set_imu_raw(self, side: str, raw6: tuple) -> None:
        from virtual.imu_proc import imu
        sample = imu(side, raw6)
        # sample 是 6 个 float（g / dps），直接送给 SDK 的 AccelGX..GyroDpsZ
        with self._lock:
            if side == "left":
                self._imu_l = tuple(float(v) for v in sample)
            else:
                self._imu_r = tuple(float(v) for v in sample)

    def left_joystick(self, x, y):
        with self._lock:
            self._stick_l = (max(0, min(4095, x)), max(0, min(4095, y)))
        self.update()

    def right_joystick(self, x, y):
        with self._lock:
            self._stick_r = (max(0, min(4095, x)), max(0, min(4095, y)))
        self.update()

    def left_trigger(self, value):
        pass  # 扳机在 0x05 报告里由按钮位表达，见 _ns2_to_hm

    def right_trigger(self, value):
        pass

    # 兼容老上层可能调用的 XInput 同名方法
    def press_button(self, button) -> None:
        pass

    def release_button(self, button) -> None:
        pass

    def update(self) -> None:
        if not self._ensure():
            return
        try:
            with self._lock:
                if self.profile_set == "jc2":
                    # 独立 JC2：语义位映射，方向键在按钮位里（profile 用语义名）
                    bl = _ns2_to_hm_jc2(self._bits_l, "L")
                    br = _ns2_to_hm_jc2(self._bits_r, "R")
                else:
                    # 握把：错位位映射，方向键走 hat
                    bl = _ns2_to_hm(self._bits_l, "L")
                    br = _ns2_to_hm(self._bits_r, "R")
                lx, ly = self._stick_l
                rx, ry = self._stick_r
                imu_l, imu_r = self._imu_l, self._imu_r
            hl = hr = "-1"
            if self.profile_set != "jc2":
                hat_l = _ns2_hat_degrees(self._bits_l, "L")
                hat_r = _ns2_hat_degrees(self._bits_r, "R")
                hl = "-1" if hat_l is None else f"{hat_l:.1f}"
                hr = "-1" if hat_r is None else f"{hat_r:.1f}"
            self._send(f"STATE L {bl} {lx} {ly} {rx} {ry} {hl}")
            self._send(f"STATE R {br} {lx} {ly} {rx} {ry} {hr}")
            self._send("IMU L " + " ".join(f"{v:.4f}" for v in imu_l))
            self._send("IMU R " + " ".join(f"{v:.4f}" for v in imu_r))
        except Exception as exc:
            self._failed += 1
            if self._failed <= 5:
                log.warning("推送失败 %s: %s", type(exc).__name__, exc)

    # ---------- TCP ----------

    def _send(self, line: str) -> None:
        if not self._sock:
            raise RuntimeError("bridge not connected")
        with self._lock:
            self._sock.sendall((line + "\n").encode("utf-8"))

    def _read_reply(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    return
                self._rbuf.extend(chunk)
                while b"\n" in self._rbuf:
                    line, _, self._rbuf = self._rbuf.partition(b"\n")
                    self._handle_line(line.decode("utf-8", errors="replace").strip())
            except socket.timeout:
                pass

    def _wait_ok(self, seconds: float) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    return False
                self._rbuf.extend(chunk)
                while b"\n" in self._rbuf:
                    line, _, self._rbuf = self._rbuf.partition(b"\n")
                    txt = line.decode("utf-8", errors="replace").strip()
                    if txt == "OK":
                        return True
                    if txt.startswith("ERR"):
                        log.error("HmBridge: %s", txt)
                        return False
            except socket.timeout:
                pass
        return False

    def _reader(self):
        while not self._stop and self._sock:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                self._rbuf.extend(chunk)
                while b"\n" in self._rbuf:
                    line, _, self._rbuf = self._rbuf.partition(b"\n")
                    self._handle_line(line.decode("utf-8", errors="replace").strip())
            except socket.timeout:
                continue
            except Exception:
                break

    def _handle_line(self, line: str):
        if not line:
            return
        if line.startswith("OUT "):
            # OUT <side> <leftMotor> <rightMotor>
            p = line.split()
            if len(p) >= 4:
                self._on_rumble(p[1], float(p[2]), float(p[3]))
        elif line.startswith("RAW "):
            # RAW <side> <hex>  （原始 output report 兜底）
            p = line.split()
            if len(p) >= 3:
                self._on_raw_rumble(p[1], bytes.fromhex(p[2]))

    def _on_rumble(self, side: str, left: float, right: float):
        """HIDMaestro 解码出的震动 → JC2 HD 震动块。"""
        if left <= 0.001 and right <= 0.001:
            return
        # HIDMaestro 的 0..1 振幅 → HD LRA 块（与 rumble_hd 的 feed_block 同格式）
        # 高频块 blk[1]=0x80|amp_hi(6bit)，低频块 blk[3]=amp_lo(7bit)+0x40
        la = max(0, min(127, int(left * 127)))
        ra = max(0, min(127, int(right * 127)))
        blk = bytes([0x00, 0x80 | la, 0x00, 0x40 | ra, 0x00])
        self._feed_hd(side, blk)

    def _on_raw_rumble(self, side: str, data: bytes):
        self._feed_hd(side, data[:4])

    @staticmethod
    def _feed_hd(side: str, blk: bytes):
        try:
            from virtual.rumble_hd import get_sender
            get_sender("left" if side == "L" else "right").feed_block(blk[:4])
        except Exception:
            pass

    def _close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    def close(self) -> None:
        self._stop = True
        try:
            self._send("QUIT")
        except Exception:
            pass
        self._close()
        try:
            run_hidden(["taskkill", "/F", "/IM", _BRIDGE_EXE], timeout=8)
        except Exception:
            pass
