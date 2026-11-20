"""桥接层：Joy-Con 2 (BLE)  ->  虚拟 Switch 1 手柄 (USB/IP)。"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

from . import descriptors as D
from .hid_function import Switch1HidFunction
from .reports import PadState
from .usbip import ExportDevice, ServerConfig, UsbIpServer

log = logging.getLogger("jc2bridge.bridge")

USBIP_CANDIDATES = [
    r"C:\Program Files\USBip\usbip.exe",
    r"C:\Program Files (x86)\USBip\usbip.exe",
    r"C:\Program Files\usbip-win2\usbip.exe",
    r"C:\Windows\System32\usbip.exe",
]

SERIAL_SUFFIX = {"joyconL": "02", "joyconR": "03", "grip": "04"}


def find_usbip() -> Optional[str]:
    env = os.environ.get("JC2_USBIP")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("usbip") or shutil.which("usbip.exe")
    if found:
        return found
    for path in USBIP_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


@dataclass
class BridgeOptions:
    target: str = "joyconL"        # joyconL / joyconR（本项目只模拟 Joy-Con 1）
    address: Optional[str] = None  # Joy-Con 2 的 BLE MAC，空则扫描
    port: int = 3240
    busid: str = "1-1"
    full_init: bool = True
    attach: bool = True
    host_bind: str = "127.0.0.1"
    period_ms: float = 0.0         # 0=用 DEFAULT_PERIOD_MS(8ms)；真机虽15ms但实测太慢


class Bridge:
    def __init__(self, opts: BridgeOptions):
        self.opts = opts
        self.spec = D.DEVICES[opts.target]
        from virtual.hid_function import DEFAULT_PERIOD_MS as _DP
        self.hid = Switch1HidFunction(self.spec, opts.target,
                                      period_ms=(_DP if opts.period_ms <= 0 else opts.period_ms))
        self.server = UsbIpServer(ServerConfig(
            host=opts.host_bind, port=opts.port, busnum=1, devnum=1,
        ))
        self.source: object = None
        self._stop = asyncio.Event()
        self._attached = False
        self._last_state = PadState()
        self._push_count = 0
        self._t0 = time.monotonic()

    # ---------------- USB 侧 ----------------

    def start_usb(self) -> None:
        busid = self.opts.busid
        dev = ExportDevice(
            path=f"/sys/devices/virtual/usbip/{busid}",
            busid=busid,
            busnum=1,
            devnum=1,
            speed=self.spec.speed,
            vid=self.spec.vid,
            pid=self.spec.pid,
            bcd_device=self.spec.bcd_device,
            b_device_class=self.spec.b_device_class,
            b_device_sub_class=self.spec.b_device_sub_class,
            b_device_protocol=self.spec.b_device_protocol,
            b_configuration_value=1,
            b_num_configurations=1,
            interfaces=[(0x03, 0x00, 0x00)],
        )
        self.server.add_device(busid, dev, self.hid)
        self.server.start()

    def attach(self) -> bool:
        if not self.opts.attach:
            log.info("跳过 usbip attach（--no-attach）")
            return False
        exe = find_usbip()
        if exe is None:
            log.error("找不到 usbip.exe，请安装 usbip-win2 或设置 JC2_USBIP")
            return False
        cmd = [exe, "attach", "-r", self.opts.host_bind, "-b", self.opts.busid]
        log.info("exec: %s", " ".join(cmd))
        try:
            from hidden_exec import run_hidden
            res = run_hidden(cmd, timeout=30)
        except Exception as exc:  # noqa: BLE001
            log.error("usbip attach 失败: %s", exc)
            return False
        out = (res.stdout or "") + (res.stderr or "")
        for line in out.strip().splitlines():
            log.info("usbip: %s", line)
        ok = "success" in out.lower() or res.returncode == 0
        self._attached = ok
        return ok

    def detach(self) -> None:
        if not self._attached:
            return
        exe = find_usbip()
        if not exe:
            return
        try:
            from hidden_exec import run_hidden
            run_hidden([exe, "detach", "-p", "0"], timeout=15)
        except Exception:  # noqa: BLE001
            pass
        self._attached = False

    # ---------------- 输入 ----------------

    def _on_state(self, st: PadState) -> None:
        self._last_state = st
        self.hid.set_state(st)
        self.server.kick_input(1)
        self._push_count += 1

    def _on_raw(self, raw: bytes) -> None:
        log.debug("raw %s", raw[:12].hex())

    # ---------------- 主流程 ----------------

    def _controller_kind(self) -> str:
        """把输出目标名翻成统一报告解析用的控制器类型。

        本项目只模拟 Joy-Con 1（L/R），没有 Pro Controller 分支。
        """
        return self.opts.target

    async def run(self) -> None:
        addr = self.opts.address
        if not addr:
            log.info("扫描 BLE 设备（10 秒）...")
            hits = await scan(10.0)
            for h in hits[:12]:
                log.info("  %s", h.describe())
            # Joy-Con 2 广告名通常为空，先挑已配对的地址
            cands = [h for h in hits if h.name and "joy" in h.name.lower()]
            if not cands:
                cands = [h for h in hits if h.rssi > -80]
            if not cands:
                raise RuntimeError("没扫到可用的手柄，请按住 Joy-Con 2 侧键唤醒后重试")
            addr = cands[0].address
            log.info("选用 %s", addr)

        self.source = JoyCon2Source(
            addr, on_state=self._on_state, on_raw=self._on_raw,
            use_full_init=self.opts.full_init,
            controller=self._controller_kind(),
        )
        await self.source.connect()
        log.info("Joy-Con 2 已连接：%s", addr)

        self.start_usb()
        if self.opts.attach:
            if not self.attach():
                log.warning("usbip attach 未成功；设备仍在本机 usbip 服务端就绪，可手动 attach")

        await self._status_loop()

    async def _status_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(2.0)
            if self.source and not self.source.connected:
                log.warning("手柄断连，重连中 ...")
                try:
                    await self.source.connect()
                    log.info("重连成功")
                except Exception as exc:  # noqa: BLE001
                    log.warning("重连失败: %s", exc)
            dt = time.monotonic() - self._t0
            rate = self._push_count / dt if dt else 0
            log.info(
                "输入 %.1f Hz | USB 报告 %d | out %d | mode=0x%02X protocol=%s",
                rate, self.hid.reports_sent, self.hid.out_reports,
                self.hid.input_mode, self.hid.protocol_seen,
            )

    def stop(self) -> None:
        self._stop.set()
        self.server.stop()
        self.detach()
