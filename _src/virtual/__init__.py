"""输入侧工具 —— 把 Switch 2 的 Joy-Con 2 输入转成语义状态。

输出层统一走 hidmaestro_out.py（HIDMaestro 独立 JoyCon1），旧的 USB/IP
输出层（vjoy_out / usbip / bridge / hid_function / descriptors）已彻底删除。

保留的组成：
    reports      报告解析 / 编码（Joy-Con 2 -> PadState -> 按键位）
    jc2_frame    Joy-Con 2 BLE 帧解析
    imu_proc     传感器量纲/轴向换算（imu_semantic 供 HIDMaestro 用）
    rumble_hd    HD 震动块编码（发给真手柄）
    scroll       滚轮
    hidmaestro_out  HIDMaestro 输出层
"""
from .reports import PadState, Ns2Bit, JoyConEncoder

__all__ = [
    "PadState", "Ns2Bit", "JoyConEncoder",
]

__version__ = "0.1.0"
