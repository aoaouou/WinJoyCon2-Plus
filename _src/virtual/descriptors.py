"""USB 描述符：Nintendo Switch 1 手柄（Pro Controller 1 / Joy-Con L,R / Charging Grip）。

描述符字节来自真实硬件抓包：
* Pro Controller 1 的 203 字节 USB 描述符（HIDMaestro profiles/nintendo/switch-pro.json
  的 nativeDescriptor，来源 DJm00n/ControllersInfo）
* Joy-Con / Pro Controller 的 170 字节蓝牙 HID 报告描述符（switchbrew Joy-Con.txt，
  经 HIDMaestro joycon-l.json 交叉核对）

USB 上 Joy-Con 1 本体并不存在（只有 Charging Grip 0x200E 走 USB），因此本工具把
Joy-Con L/R 也按它们的 VID/PID 用 USB 暴露，报告描述符沿用蓝牙那份，保证按
VID/PID 判定的程序（Steam / SDL / 游戏）能认出来。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


USB_VENDOR_NINTENDO = 0x057E

PID_JOYCON_L = 0x2006
PID_JOYCON_R = 0x2007
PID_JOYCON_GRIP = 0x200E


REPORT_ID_SIMPLE = 0x3F   # 12 字节简单报告（joy.cpl / DirectInput 走这条）
REPORT_ID_FULL = 0x30     # 48 字节全模式报告
REPORT_ID_MCU = 0x31      # 49 字节（含 3 组 IMU）；一般不主动发
REPORT_ID_OUTPUT = 0x01   # 输出报告（震动 + 子命令）
REPORT_ID_RUMBLE_ONLY = 0x10
REPORT_ID_NFC_IR = 0x11
REPORT_ID_RUMBLE_2 = 0x12


# --------------------------------------------------------------------------- #
# 报告描述符
# --------------------------------------------------------------------------- #

JOYCON_REPORT_DESCRIPTOR = bytes.fromhex(
    "05010905a1010601ff"
    "85210921750895308102"
    "85300930750895308102"
    "8531093175089669018102"
    "8532093275089669018102"
    "8533093375089669018102"
    "853f05091901291015002501750195108102"
    "0501093915002507750495018142"
    "0509750495018101"
    "0501093009310933093416000027ffff0000751095048102"
    "0601ff85010901750895309102"
    "85100910750895309102"
    "85110911750895309102"
    "85120912750895309102"
    "c0"
)

# 中断端点支持的最大报告尺寸（含 report id）
#
# Pro Controller 的 USB 描述符把 0x21/0x30/0x81 都声明成 63 字节负载
# → 含 ID 共 64 字节。这是 USB 形态与蓝牙形态的真实差异：蓝牙上 0x30 是
# 49 字节，USB 上是 64 字节。发 49 字节会被 hidclass 直接丢弃（实测读到 0 份）。
#
# Joy-Con 的蓝牙描述符里 0x30 是 48 字节负载 → 含 ID 共 49 字节，与编码一致。
JOYCON_EP_MAX_REPORT = 64   # USB 报告 64 字节（SDL 按此长度读包）
# USB 模式下必须 64 字节。SDL 的 k_unSwitchUSBPacketLength = 64，
# 按 64 读包；只给 49 会让它读到不完整的包，握手中的子命令应答对不上，
# 表现就是 "Couldn't load stick calibration" / JoystickOpen 返回 NULL。
# （蓝牙模式才是 49 = k_unSwitchBluetoothPacketLength）
JOYCON_INPUT_REPORT_SIZE = 64


# --------------------------------------------------------------------------- #
# 设备定义
# --------------------------------------------------------------------------- #

@dataclass
class UsbDeviceSpec:
    """一个可被 usbip 导出的虚拟 Nintendo 手柄。"""

    key: str                       # 内部标识
    product: str                   # USB 产品字符串
    manufacturer: str              # 厂商字符串
    vid: int
    vd_pid: int
    serial: str
    report_descriptor: bytes
    ep_max_report: int
    bcd_device: int = 0x0000
    # FIDO/WINUSB 不需要；Nintendo 手柄是纯 HID，走系统 hidusb
    b_device_class: int = 0x00
    b_device_sub_class: int = 0x00
    b_device_protocol: int = 0x00
    # usbip 的 speed 编码：1=Low(1.5M) 2=Full(12M) 3=High(480M)。
    # Switch 1 手柄是全速设备，必须是 2；写 1 会让主机当成低速设备，
    # 中断端点包长被限到 8 字节，报告流直接作废。
    speed: int = 2
    extra_strings: List[str] = field(default_factory=list)

    @property
    def pid(self) -> int:
        return self.vd_pid


def _mk(key, product, pid, report_descriptor, ep_max_report, serial):
    return UsbDeviceSpec(
        key=key,
        product=product,
        manufacturer="Nintendo Co., Ltd.",
        vid=USB_VENDOR_NINTENDO,
        vd_pid=pid,
        serial=serial,
        report_descriptor=report_descriptor,
        ep_max_report=ep_max_report,
    )


DEVICE_JOYCON_L = _mk(
    "joyconL", "Joy-Con (L)", PID_JOYCON_L,
    JOYCON_REPORT_DESCRIPTOR, JOYCON_EP_MAX_REPORT, "000000000002",
)

DEVICE_JOYCON_R = _mk(
    "joyconR", "Joy-Con (R)", PID_JOYCON_R,
    JOYCON_REPORT_DESCRIPTOR, JOYCON_EP_MAX_REPORT, "000000000003",
)

DEVICE_GRIP = _mk(
    "grip", "Joy-Con Charging Grip", PID_JOYCON_GRIP,
    JOYCON_REPORT_DESCRIPTOR, JOYCON_EP_MAX_REPORT, "000000000004",
)

DEVICES = {
    d.key: d for d in (DEVICE_JOYCON_L, DEVICE_JOYCON_R, DEVICE_GRIP)
}


# --------------------------------------------------------------------------- #
# USB 标准描述符的字节组装
# --------------------------------------------------------------------------- #

def _le16(v: int) -> bytes:
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


def device_descriptor(spec: UsbDeviceSpec) -> bytes:
    """18 字节设备描述符。"""
    return bytes((
        18, 0x01,
    )) + _le16(0x0200) + bytes((
        spec.b_device_class, spec.b_device_sub_class, spec.b_device_protocol,
        0x40,                              # bMaxPacketSize0 = 64
    )) + _le16(spec.vid) + _le16(spec.pid) + _le16(spec.bcd_device) + bytes((
        1,                                 # iManufacturer
        2,                                 # iProduct
        3,                                 # iSerialNumber
        1,                                 # bNumConfigurations
    ))


def hid_descriptor(w_report_desc_len: int) -> bytes:
    # bcdHID 1.11, country 0, 1 个下级描述符
    return bytes((9, 0x21)) + _le16(0x0111) + bytes((0, 1, 0x22)) + _le16(w_report_desc_len)


def configuration_descriptor(spec: UsbDeviceSpec) -> bytes:
    """配置 + 接口 + HID + 2 个端点。

    布局：4 字节 EP1 IN（中断，报告）+ 4 字节 EP1 OUT（中断，输出报告/震动）。
    """
    hid = hid_descriptor(len(spec.report_descriptor))
    ep_in = bytes((7, 0x05, 0x81, 0x03)) + _le16(spec.ep_max_report) + bytes((4,))
    ep_out = bytes((7, 0x05, 0x01, 0x03)) + _le16(64) + bytes((4,))
    # 9 配置头 + 9 接口 + len(hid) + 7 + 7 端点
    total = 9 + 9 + len(hid) + len(ep_in) + len(ep_out)
    return (
        bytes((9, 0x02)) + _le16(total)
        + bytes((1, 1, 0, 0xC0, 50))
        + bytes((9, 0x04, 0, 0, 2, 0x03, 0x00, 0x00, 0))
        + hid
        + ep_in
        + ep_out
    )


def string_descriptor(index: int, spec: UsbDeviceSpec) -> bytes:
    if index == 0:
        # LANGID 表：0x0409 = en-US
        return bytes((4, 0x03)) + _le16(0x0409)
    table = {
        1: spec.manufacturer,
        2: spec.product,
        3: spec.serial,
    }
    text = table.get(index, "")
    encoded = text.encode("utf-16-le")
    return bytes((2 + len(encoded), 0x03)) + encoded
