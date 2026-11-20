# -*- coding: utf-8 -*-
"""隐藏窗口的 subprocess 调用（Windows）。

═══════════════════════════════════════════════════════════════════════════
为什么需要这个模块
═══════════════════════════════════════════════════════════════════════════
PyInstaller `--windowed` 打包后没有控制台，但 `subprocess.run` 调用
`usbip.exe` 时会**弹出黑窗口**（每次一个新控制台）。

一键连接要 attach 左右两个虚拟设备，加上 detach/port 查询，
一次连接能闪 4~6 个黑窗口 —— 实测用户抱怨"每次连接都要闪好几次黑窗口"。

根因是那些调用点漏了 `creationflags=CREATE_NO_WINDOW`。

═══════════════════════════════════════════════════════════════════════════
用法
═══════════════════════════════════════════════════════════════════════════
所有 `subprocess.run(...)` 改成 `run_hidden(...)`，参数一致。
"""
from __future__ import annotations

import subprocess
import sys

# Windows: 不创建控制台窗口。
# 其它平台没有这个概念，取 0。
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def run_hidden(args, timeout: float = 30, **kwargs):
    """subprocess.run 的无黑窗口版本。

    与 subprocess.run 参数一致；`creationflags` 由本函数统一设置，
    调用方不要自己传（传了会被覆盖）。
    """
    kwargs.pop("creationflags", None)
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        **kwargs,
    )
