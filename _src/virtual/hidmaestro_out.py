# -*- coding: utf-8 -*-
"""独立 Joy-Con 1 输出层（HIDMaestro 后端）。

架构
----
物理 JC2（蓝牙 BLE）→ 本项目控制器逻辑 → 本类 → TCP → HmBridge（C#，
管理员权限）→ HIDMaestro SDK → 两只虚拟独立 Joy-Con 1（VID 057E /
PID 2006 L · 2007 R，真机 HID 描述符）。平台自动组合成一对，全平台兼容。

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

# ---- 真机 JoyCon1 profile 的按钮位映射（静态推导 + 实测校准）----
# HIDMaestro 自带 joycon-l / joycon-r 的 stateBlock 用 "#n" 把
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
# R 半 ABXY → HMButton 位。
# ★ 用户 2026-11-26 真机实测：上一版 A↔B、X↔Y 互换。按用户反馈交换回来。
#   A→bit0  B→bit2  X→bit1  Y→bit3
# 依据：joycon-r.json stateBlock byte2 = ["#3","#1","#2","#0",...]，
# 经真机验证这四位分别对应手柄物理 A/B/X/Y 的正确位置。
_HM_R_POS_A = 1 << 0
_HM_R_POS_B = 1 << 2
_HM_R_POS_X = 1 << 1
_HM_R_POS_Y = 1 << 3
_HM_PLUS = 1 << 9
_HM_RS = 1 << 11
_HM_HOME = 1 << 12


def _ns2_to_hm(bits: int, side: str) -> int:
    """Ns2Bit → 独立 JoyCon1 profile 的 32 位 HMButton 掩码。

    真机 profile 的 stateBlock 用 "#n" 把 HMButton 位搬到 0x30 报告特定位，
    SDL HandleCombinedControllerStateL/R 又按自己位置名读——合成映射是
    "故意错位"的，位表见下方常量注释（已按实测校准 ABXY）。
    """
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
    """两只虚拟独立 Joy-Con 1（PID 2006/2007，HIDMaestro 后端）。

    平台自动把左右两只组合成一对，全平台兼容。按键/HD震动/陀螺仪按旧
    USB/IP 方案的实现，走 profile 的 0x30/0x3F 报告。
    """

    def __init__(self, side: str = "both", profile_set: str = None):
        # profile_set 保留形参只为兼容旧调用，已无意义（唯一形态=jc1）。
        self.side = side.lower()
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
        self._ever_started = False
        self._next_retry_at = 0.0
        self._failed = 0
        self._ensure()

    # ---------- 生命周期 ----------

    def _bridge_paths(self):
        """返回 (bridge exe, profiles dir)。

        ★ 打包版（onefile）必须把桥接文件复制到 _MEI 之外的固定目录再启动：
          桥接是提权进程，主程序退出时 PyInstaller bootloader 会删 _MEI 临时
          目录；若桥接还在里面运行，exe/dll 被占用 -> 删不掉 ->
          「Failed to remove temporary directory: C:\\...\\_MEIxxxxxx」弹窗。
          放到 exe 同目录的 bridge_runtime/，_MEI 就不再被占用。
        """
        meipass = getattr(sys, "_MEIPASS", None)
        base = pathlib.Path(meipass or str(_ROOT.parent))
        # 源码运行：exe 在 hidmaestro_bridge/bin/；打包后：在 _MEIPASS/hidmaestro_bridge/
        exe = base / "hidmaestro_bridge" / "bin" / _BRIDGE_EXE
        if not exe.exists():
            exe = base / "hidmaestro_bridge" / _BRIDGE_EXE
        # profiles 唯一来源：_src/hidmaestro_profiles（打包后在 _MEIPASS/hidmaestro_bridge/）
        profiles = base / _PROFILES_DIR
        if not profiles.exists():
            profiles = base / "hidmaestro_bridge" / _PROFILES_DIR

        if meipass:
            # 打包模式：暂存到 exe 同目录的 bridge_runtime/
            import shutil
            from app_paths import app_dir
            runtime = pathlib.Path(app_dir()) / "bridge_runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            for name in (_BRIDGE_EXE, "HmBridge.dll", "HmBridge.deps.json",
                         "HmBridge.runtimeconfig.json", "HIDMaestro.Core.dll"):
                src = exe.parent / name
                if src.exists():
                    dst = runtime / name
                    # 只在缺失或变化时复制（避免每次启动写盘；版本变化靠大小+时间）
                    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                        shutil.copy2(str(src), str(dst))
            dst_profiles = runtime / "profiles"
            dst_profiles.mkdir(parents=True, exist_ok=True)
            if profiles.exists():
                # ★ 每次按内容同步：缺口/变化就覆盖，并删除目标里已废弃的
                #   profile（如旧的 joycon-l-usb / switch2-*）。否则旧缓存
                #   目录会一直存在，桥接找不到新的 joycon-l/r → INIT 失败。
                import filecmp
                src_names = set()
                for src in profiles.iterdir():
                    if not src.is_file():
                        continue
                    src_names.add(src.name)
                    dst = dst_profiles / src.name
                    if not dst.exists() or not filecmp.cmp(str(src), str(dst), shallow=False):
                        shutil.copy2(str(src), str(dst))
                for stale in dst_profiles.iterdir():
                    if stale.is_file() and stale.name not in src_names:
                        stale.unlink()
            return str(runtime / _BRIDGE_EXE), str(dst_profiles)

        return str(exe), str(profiles)

    def _fail(self) -> None:
        """初始化失败：首次永久放弃（避免反复弹 UAC）；重建时 5s 后重试。"""
        if not getattr(self, "_ever_started", False):
            self._init_failed = True
        else:
            self._init_failed = False
            self._next_retry_at = time.time() + 5.0

    def _ensure(self) -> bool:
        if self._started:
            return True
        if getattr(self, "_init_failed", False):
            return False  # 失败只尝试一次，避免每帧提权重试
        # 重建节流：链路断开后至少隔 2 秒再重建，防每帧提权。
        import time as _t
        if _t.time() < getattr(self, "_next_retry_at", 0.0):
            return False
        exe, profiles = self._bridge_paths()
        if not pathlib.Path(exe).exists():
            log.error("HmBridge.exe 不存在: %s", exe)
            self._fail()
            return False

        # 杀旧实例（可能占用 identity key）。没有残留时 taskkill 会立刻返回，
        # 所以不再固定 sleep(1)，改为按需短等。
        had_old = False
        try:
            from hidden_exec import run_hidden
            r = run_hidden(["tasklist", "/FI", f"IMAGENAME eq {_BRIDGE_EXE}"],
                           timeout=5)
            had_old = _BRIDGE_EXE.lower() in (r.stdout or "").lower()
            if had_old:
                run_hidden(["taskkill", "/F", "/IM", _BRIDGE_EXE], timeout=8)
        except Exception:
            pass
        if had_old:
            time.sleep(0.4)

        # 提权启动（CreateController 要管理员 token）。
        # run_hidden 是阻塞的 subprocess.run，这里要用 PowerShell 的
        # Start-Process -Verb RunAs 拉起独立的管理员进程。
        try:
            ps = (
                "Start-Process -FilePath '" + exe + "' "
                "-ArgumentList @('" + profiles + "') "
                "-Verb RunAs -WindowStyle Hidden"
            )
            self._proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            log.error("启动 HmBridge 失败: %s", exc)
            self._fail()
            return False
        # 不再盲等 6 秒：轮询端口，一开就继续（典型 1.5~3s）。
        deadline = time.time() + 20.0
        sock = None
        while time.time() < deadline:
            try:
                sock = socket.create_connection(("127.0.0.1", BRIDGE_PORT), timeout=0.3)
                break
            except OSError:
                time.sleep(0.15)
        if sock is None:
            log.error("HmBridge 端口未就绪（%s:%s）", BRIDGE_PORT, "127.0.0.1")
            self._fail()
            return False

        # 连接并 INIT
        try:
            s = sock
            s.settimeout(0.3)
            self._sock = s
            self._send("HELLO")
            self._read_reply(1)
            self._send("INIT")
            ok = self._wait_ok(15)
            if not ok:
                log.error("HmBridge INIT 失败")
                self._close()
                self._fail()
                return False
            self._send("SUB")
            self._read_reply(0.5)
        except Exception as exc:
            log.error("连接 HmBridge 失败: %s", exc)
            self._close()
            self._fail()
            return False

        self._started = True
        self._ever_started = True
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
        # ★ 用旧 USB/IP 方案**已验证**的 imu()：输出报告顺序的 wire raw
        #   （量纲 GYRO_SCALE + 轴向都经实机验证，reports.py 里明确记录了
        #   "写成 az,ax,ay 会导致体感全程乱转"）。桥接再按 profile 的
        #   错位映射 + negate 反解成属性值，使报告字节与旧方案逐字节相同。
        sample = imu(side, raw6)
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
                bl = _ns2_to_hm(self._bits_l, "L")
                br = _ns2_to_hm(self._bits_r, "R")
                lx, ly = self._stick_l
                rx, ry = self._stick_r
                imu_l, imu_r = self._imu_l, self._imu_r
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
        # 链路断了（桥接被杀 / 端口关闭）：标记为未启动，让下一次
        # update() 自动走 _ensure() 重建，避免"静默失效"（表现为
        # 手柄一直断连重连但程序没报错）。
        if not self._stop:
            log.warning("HmBridge 链路断开，2s 后自动重建")
            self._started = False
            self._init_failed = False
            self._next_retry_at = time.time() + 2.0
            try:
                if self._sock:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _handle_line(self, line: str):
        if not line:
            return
        if line.startswith("RUMBLE "):
            # RUMBLE <side> <left4hex> <right4hex>
            # 桥接只把真机的原始 4 字节震动块送来，解码交给已验证的
            # rumble_hd.feed_block（内部走 jc1_block_to_jc2：
            #  SDL 权威振幅表 + 中性判定 + 频率锁 JC2 原生）。
            p = line.split()
            if len(p) >= 4:
                try:
                    lblock = bytes.fromhex(p[2])
                    rblock = bytes.fromhex(p[3])
                except ValueError:
                    return
                self._on_jc1_blocks(p[1], lblock, rblock)
        elif line.startswith("RAW "):
            p = line.split()
            if len(p) >= 3:
                try:
                    self._on_jc1_blocks(p[1], bytes.fromhex(p[2])[:4], b"")
                except ValueError:
                    pass

    def _on_jc1_blocks(self, side: str, left: bytes, right: bytes):
        """把真机 JC1 的 4 字节震动块喂给 HdRumbleSender（原样，不自己解）。

        本侧 JOY-CON 用 `side` 决定喂哪个 sender；块本身用真机左右两块里
        对应的一块（左半设备用 left，右半设备用 right；两块在
        joystick-rumble 下通常相同）。
        """
        blk = left if side == "L" else right
        if len(blk) < 4:
            blk = left if len(left) >= 4 else right
        if len(blk) < 4:
            return
        try:
            from virtual.rumble_hd import get_sender
            get_sender("left" if side == "L" else "right").feed_block(blk[:4])
        except Exception:
            pass

    # 兼容旧入口（外部若还调 _on_rumble）
    def _on_rumble(self, side: str, left: float, right: float):
        return

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
        # 让桥接自己正常退出（QUIT -> Environment.Exit(0)），等它释放
        # exe/dll 句柄。相比 taskkill，这样不会因"非提权杀不掉提权进程"
        # 而留下残留占用文件。
        try:
            self._send("QUIT")
            self._read_reply(0.6)
        except Exception:
            pass
        self._close()
        # 兜底：非提权 taskkill（能杀则杀，杀不掉也无妨——桥接已在
        # bridge_runtime/ 而非 _MEI，不占用 PyInstaller 临时目录）。
        try:
            run_hidden(["taskkill", "/F", "/IM", _BRIDGE_EXE], timeout=8)
        except Exception:
            pass
