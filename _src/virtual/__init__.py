"""jc2bridge —— 把 Switch 2 的 Joy-Con 2 / Pro Controller 2 模拟成 Switch 1 手柄。

组成：
    ble_source   读 Joy-Con 2 的 BLE 输入（GATT notify）
    reports      报告解析 / 编码（Joy-Con 2 -> PadState -> Pro1 / JoyCon1）
    descriptors  USB 描述符（真实硬件字节）
    usbip        最小 usbip 服务端（把虚拟 USB 设备挂到系统）
    hid_function HID 类请求 + 子命令应答
    bridge       两者粘合，含 usbip attach 与状态输出
"""
from .reports import PadState, Ns2Bit, JoyConEncoder
from .descriptors import DEVICES, DEVICE_JOYCON_L, DEVICE_JOYCON_R
from .usbip import ServerConfig, UsbIpServer, ExportDevice
from .hid_function import Switch1HidFunction

__all__ = [
    "PadState", "Ns2Bit", "JoyConEncoder",
    "DEVICES", "DEVICE_JOYCON_L", "DEVICE_JOYCON_R",
    "ServerConfig", "UsbIpServer", "ExportDevice", "Switch1HidFunction",
    "JoyCon2Source", "scan",
]

__version__ = "0.1.0"
