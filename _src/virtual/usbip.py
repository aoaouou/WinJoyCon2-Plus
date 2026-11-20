"""最小可用的 USB/IP 服务端（RFC 无，参照 Linux tools/usb/usbip 的 wire format）。

只实现 Nintendo 手柄需要的路径：

    OP_REQ_DEVLIST  -> OP_REP_DEVLIST
    OP_REQ_IMPORT   -> OP_REP_IMPORT   （之后同一条 TCP 连接转为 URB 流）
    CMD_SUBMIT      -> RET_SUBMIT      （control / 中断 IN / 中断 OUT）
    CMD_UNLINK      -> RET_UNLINK

中断 IN 端点做了"挂起请求"处理：主机发来的 IN submit 不会被立刻回填，而是留到有新
输入报告时才答复——这与真实硬件的等时行为一致，也是 usbip-win2 能稳定跑 133Hz 的前提。

所有多字节字段网络序（大端），只有 setup 包里的字段按 USB 定义是小端。
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

log = logging.getLogger("jc2bridge.usbip")

USBIP_VERSION = 0x0111

OP_REQ_DEVLIST = 0x8005
OP_REP_DEVLIST = 0x0005
OP_REQ_IMPORT = 0x8003
OP_REP_IMPORT = 0x0003

CMD_SUBMIT = 0x00000001
CMD_UNLINK = 0x00000002
RET_SUBMIT = 0x00000003
RET_UNLINK = 0x00000004

DIR_OUT = 0x00000000
DIR_IN = 0x00000001

# USB 标准请求
REQ_GET_STATUS = 0x00
REQ_CLEAR_FEATURE = 0x01
REQ_SET_FEATURE = 0x03
REQ_SET_ADDRESS = 0x05
REQ_GET_DESCRIPTOR = 0x06
REQ_SET_DESCRIPTOR = 0x07
REQ_GET_CONFIGURATION = 0x08
REQ_SET_CONFIGURATION = 0x09
REQ_GET_INTERFACE = 0x0A
REQ_SET_INTERFACE = 0x0B

DESC_DEVICE = 0x01
DESC_CONFIGURATION = 0x02
DESC_STRING = 0x03
DESC_HID = 0x21
DESC_HID_REPORT = 0x22

# HID 类请求
HID_GET_REPORT = 0x01
HID_GET_IDLE = 0x02
HID_GET_PROTOCOL = 0x03
HID_SET_REPORT = 0x09
HID_SET_IDLE = 0x0A
HID_SET_PROTOCOL = 0x0B

RET_SUBMIT_HDR_SIZE = 0x30


# --------------------------------------------------------------------------- #
# URB 数据结构
# --------------------------------------------------------------------------- #

@dataclass
class Urb:
    seqnum: int
    devid: int
    direction: int
    ep: int
    length: int
    setup: bytes
    data: bytes
    flags: int = 0

    @property
    def is_control(self) -> bool:
        return self.ep == 0

    def setup_fields(self):
        bm, req, wv, wi, wl = struct.unpack("<BBHHH", self.setup[:8])
        return bm, req, wv, wi, wl


class UrbReply:
    """一个待回填的 URB：知道怎么写出 RET_SUBMIT。"""

    def __init__(self, sock: socket.socket, lock: threading.Lock, urb: Urb):
        self._sock = sock
        self._lock = lock
        self.urb = urb
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def complete(self, payload: bytes = b"", status: int = 0) -> bool:
        """回填。返回 False 表示这个 URB 已经被回填过（或连接已断）。"""
        with self._lock:
            if self._done:
                return False
            self._done = True
            hdr = struct.pack(
                ">IIIII", RET_SUBMIT, self.urb.seqnum, self.urb.devid,
                self.urb.direction, self.urb.ep,
            )
            tail = struct.pack(">IIIII", status & 0xFFFFFFFF, len(payload), 0, 0, 0)
            try:
                self._sock.sendall(hdr + tail + b"\x00" * 8 + payload)
            except OSError:
                return False
        return True

    def cancel(self) -> bool:
        return self.complete(b"", status=-104)  # -ECONNRESET


# --------------------------------------------------------------------------- #
# 设备接口
# --------------------------------------------------------------------------- #

class UsbFunction:
    """设备侧回调。上层只需要实现 handle_control / handle_in / handle_out。"""

    def control(self, urb: Urb) -> Optional[bytes]:
        """返回要回给主机的数据（IN 方向）；None 表示 STALL。"""
        return None

    def on_out(self, urb: Urb, data: bytes) -> None:
        """主机写了数据（控制 OUT 或中断 OUT）。"""

    # 中断 IN 端点：由 Server 调度
    def pending_in(self, ep: int) -> Optional[bytes]:
        """若已有可发送的报告则返回，None 表示继续挂起。"""
        return None

    def ep_max_report(self, ep: int) -> int:
        return 64


# --------------------------------------------------------------------------- #
# 服务端
# --------------------------------------------------------------------------- #

@dataclass
class ExportDevice:
    path: str
    busid: str
    busnum: int
    devnum: int
    speed: int
    vid: int
    pid: int
    bcd_device: int
    b_device_class: int
    b_device_sub_class: int
    b_device_protocol: int
    b_configuration_value: int
    b_num_configurations: int
    interfaces: List[tuple]      # [(class, subclass, protocol)]

    def pack_common(self) -> bytes:
        return (
            self.path.encode().ljust(256, b"\x00")[:256]
            + self.busid.encode().ljust(32, b"\x00")[:32]
            + struct.pack(
                ">II", self.busnum, self.devnum
            )
            + struct.pack(">I", self.speed)
            + struct.pack(">HHH", self.vid, self.pid, self.bcd_device)
            + bytes((
                self.b_device_class, self.b_device_sub_class,
                self.b_device_protocol, self.b_configuration_value,
                self.b_num_configurations, len(self.interfaces),
            ))
        )

    def pack_devlist(self) -> bytes:
        out = self.pack_common()
        for c, s, p in self.interfaces:
            out += bytes((c, s, p, 0))
        return out


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 3240
    busnum: int = 1
    devnum: int = 1


class UsbIpServer:
    def __init__(self, config: ServerConfig):
        self.config = config
        self._devices: Dict[str, tuple[ExportDevice, UsbFunction]] = {}
        self._devid_map: Dict[int, UsbFunction] = {}
        self._busid_devid: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._threads: List[threading.Thread] = []
        self._running = False
        self._pending_in: Dict[int, list] = {1: [], 2: []}   # ep -> [UrbReply]
        self._pending_lock = threading.Lock()

    # ---------------- 注册 ----------------

    def add_device(self, busid: str, dev: ExportDevice, func: UsbFunction) -> int:
        with self._lock:
            devid = len(self._devices) + 1
            self._devices[busid] = (dev, func)
            self._devid_map[devid] = func
            self._busid_devid[busid] = devid
        log.info("export %s (devid=%d) vid=%04X pid=%04X", busid, devid, dev.vid, dev.pid)
        return devid

    # ---------------- 生命周期 ----------------

    def start(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.config.host, self.config.port))
        s.listen(8)
        self._sock = s
        self._running = True
        t = threading.Thread(target=self._accept_loop, name="usbip-accept", daemon=True)
        t.start()
        self._threads.append(t)
        log.info("USB/IP listening on %s:%d", self.config.host, self.config.port)

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while self._running:
            try:
                conn, addr = self._sock.accept()
            except OSError:
                return
            log.info("client %s", addr)
            t = threading.Thread(
                target=self._handle_conn, args=(conn,), name="usbip-conn", daemon=True
            )
            t.start()

    # ---------------- 连接处理 ----------------

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            head = self._recv_exact(conn, 8)
            if head is None:
                return
            ver, code, status = struct.unpack(">HHI", head)
            if ver != USBIP_VERSION:
                log.warning("bad version %04X", ver)
                return
            if code == OP_REQ_DEVLIST:
                self._reply_devlist(conn)
            elif code == OP_REQ_IMPORT:
                busid = self._recv_exact(conn, 32)
                if busid is None:
                    return
                busid = busid.split(b"\x00")[0].decode(errors="replace")
                self._reply_import(conn, busid)
            else:
                log.warning("unknown op %04X", code)
        except OSError as exc:
            log.debug("conn error: %s", exc)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _recv_exact(conn: socket.socket, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _reply_devlist(self, conn: socket.socket) -> None:
        with self._lock:
            items = list(self._devices.values())
        body = struct.pack(">HHI", USBIP_VERSION, OP_REP_DEVLIST, 0)
        body += struct.pack(">I", len(items))
        for dev, _fn in items:
            body += dev.pack_devlist()
        conn.sendall(body)

    def _reply_import(self, conn: socket.socket, busid: str) -> None:
        with self._lock:
            entry = self._devices.get(busid)
        if entry is None:
            # 状态 1 = 无此设备
            conn.sendall(struct.pack(">HHII", USBIP_VERSION, OP_REP_IMPORT, 1, 0)[:8])
            log.warning("import %r: not exported", busid)
            return
        dev, _fn = entry
        conn.sendall(
            struct.pack(">HHI", USBIP_VERSION, OP_REP_IMPORT, 0) + dev.pack_common()
        )
        log.info("import %s ok", busid)
        self._urb_loop(conn, dev)

    # ---------------- URB 流 ----------------

    def _urb_loop(self, conn: socket.socket, dev: ExportDevice) -> None:
        with self._lock:
            func = None
            devid = 0
            for busid, (d, f) in self._devices.items():
                if d is dev:
                    func = f
                    devid = self._busid_devid.get(busid, 0)
                    break
        if func is None:
            return
        send_lock = threading.Lock()
        while self._running:
            head = self._recv_exact(conn, 20)
            if head is None:
                return
            command, seqnum, devid, direction, ep = struct.unpack(">IIIII", head)

            if command == CMD_SUBMIT:
                rest = self._recv_exact(conn, 28)
                if rest is None:
                    return
                flags, length, _sf, _np, _iv = struct.unpack(">IIIII", rest[:20])
                setup = rest[20:28]
                data = b""
                if direction == DIR_OUT and length:
                    data = self._recv_exact(conn, length) or b""
                self._dispatch_submit(
                    conn, send_lock, func, devid, seqnum, direction, ep,
                    length, setup, data, flags,
                )
            elif command == CMD_UNLINK:
                rest = self._recv_exact(conn, 28)
                if rest is None:
                    return
                target_seq = struct.unpack(">IIIII", rest[:20])[0]
                payload = struct.pack(">IIIII", RET_UNLINK, seqnum, devid, 0, 0) + b"\x00" * 24
                self._send(send_lock, conn, payload)
                self._cancel_pending(target_seq)
            else:
                log.warning("unknown urb cmd %08X", command)
                return

    def _send(self, lock, conn, payload: bytes) -> None:
        with lock:
            try:
                conn.sendall(payload)
            except OSError:
                pass

    def _cancel_pending(self, seqnum: int) -> None:
        with self._pending_lock:
            for ep, lst in self._pending_in.items():
                for reply in list(lst):
                    if reply.urb.seqnum == seqnum:
                        lst.remove(reply)
                        reply.cancel()
                        return

    def _dispatch_submit(
        self, conn, send_lock, func: UsbFunction, devid: int, seqnum: int,
        direction: int, ep: int, length: int, setup: bytes, data: bytes, flags: int,
    ) -> None:
        urb = Urb(seqnum=seqnum, devid=devid, direction=direction, ep=ep,
                  length=length, setup=setup, data=data, flags=flags)
        reply = UrbReply(conn, send_lock, urb)

        if ep == 0:
            resp = func.control(urb)
            if resp is None:
                reply.complete(b"", status=-32)   # -EPIPE (STALL)
            else:
                # 主机只接受 wLength 内的数据；actual_length 必须如实回报
                if length:
                    resp = resp[:length]
                reply.complete(resp)
            return

        if direction == DIR_OUT:
            func.on_out(urb, data)
            reply.complete(b"")
            return

        # 中断 IN：有数据立刻回，没有就挂起
        pending = func.pending_in(ep)
        if pending:
            reply.complete(pending)
            return
        with self._pending_lock:
            self._pending_in.setdefault(ep, []).append(reply)

    # ---------------- 输入推动 ----------------

    def kick_input(self, ep: int = 1) -> None:
        """有新报告时调用：把挂起的 IN 请求逐个回填。

        锁纪律：这里只在 _pending_lock 内做列表操作，绝不在持锁期间调用
        func.pending_in()（那会拿设备内部锁，与 _dispatch_submit 的
        "先取设备锁、再取 pending_lock" 形成反向顺序 -> 死锁）。
        """
        while True:
            with self._pending_lock:
                lst = self._pending_in.get(ep)
                if not lst:
                    return
                reply = lst[0]
                func = self._devid_map.get(reply.urb.devid)
                if func is None:
                    lst.pop(0)
                    stale = True
                else:
                    stale = False
                    lst.pop(0)
            if stale:
                reply.cancel()
                continue
            payload = func.pending_in(ep)   # 锁外调用
            if not payload:
                # 没东西可发：把请求放回原位，等下一次 kick
                with self._pending_lock:
                    cur = self._pending_in.setdefault(ep, [])
                    if reply not in cur:
                        cur.insert(0, reply)
                return
            reply.complete(payload)
