# -*- coding: utf-8 -*-
"""摇杆的「滚轮」用法：把摇杆当作滚轮输出 -32767..32767。

鼠标模式用这条通道实现"摇杆滚轮"。历史实现（scroll_decoder）用旧中心：

    x_center = (3260 + 780) / 2 = 2020
    y_center = (3250 + 820) / 2 = 2035

但真机 12 位中位是 2048。用旧中心会在静止时产生：
    X: 2048 - 2020 = +28 LSB  → 归一化后恒为正 → 滚轮一直朝一个方向走
    Y: 2048 - 2035 = +13 LSB

本模块用真实中位 2048 与固定死区，保证"摇杆归中 = 滚轮不动"。
摇杆本身走原生透传（见 control_type），这里只管鼠标模式的滚轮。
"""
from __future__ import annotations

STICK_CENTER = 2048
STICK_MAX = 4095

# 滚轮输出的满量程。沿用原实现的 32767，避免改动下游鼠标逻辑。
SCROLL_MAX = 32767

# 滚轮死区：必须与摇杆死区一致，否则摇杆已经归中、滚轮还在走。
# 摇杆死区 5% × 2047 ≈ 102 LSB；这里用同样的归一化半径。
SCROLL_DEADZONE = 0.05


def scroll_from_raw(raw_x: int, raw_y: int) -> tuple[int, int]:
    """12 位原始摇杆值 -> 滚轮增量 (-32767..32767)。

    两轴独立处理（滚轮语义就是要分轴），不做圆度压缩 ——
    滚轮上下/左右是独立通道，压成圆会让斜推时两轴都变慢。
    """
    span = STICK_MAX - STICK_CENTER      # 2047
    dz = SCROLL_DEADZONE * span          # ≈ 102 LSB

    def one(raw: int) -> int:
        d = raw - STICK_CENTER
        if abs(d) <= dz:
            return 0
        # 死区外重新铺满，避免死区边缘跳变
        sign = 1 if d > 0 else -1
        mag = (abs(d) - dz) / (span - dz)
        mag = min(1.0, mag)
        return int(sign * mag * SCROLL_MAX)

    return one(raw_x), one(raw_y)
