# -*- coding: utf-8 -*-
r"""退出时清理虚拟设备残留。

═══════════════════════════════════════════════════════════════════════════
为什么需要
═══════════════════════════════════════════════════════════════════════════
usbip 虚拟设备在「非正常退出」时（崩溃/强杀/os._exit）不会 detach，
Windows 设备树会留下幽灵节点（Status=Unknown）。实测曾累积 18 个：

    USB\\VID_057E&PID_2006\\...   Unknown
    HID\\VID_057E&PID_2006\\...   Unknown

后果：设备管理器混乱；测试工具可能连到旧节点，改代码看不出变化。

═══════════════════════════════════════════════════════════════════════════
实现说明
═══════════════════════════════════════════════════════════════════════════
用 PowerShell 的 Get-PnpDevice / pnputil，而不是 ctypes SetupAPI：
实测 ctypes 调用 SetupDiEnumDeviceInfo 对本机幽灵设备返回 0
（指针/结构体细节踩坑），PowerShell 则能正确枚举。

清理分两级：
① usbip detach —— 正常卸载，无需提权，能消掉绝大多数节点
② 幽灵设备移除 —— 需管理员，失败静默（不影响退出）
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from logger_config import info, warning

NINTENDO_PATTERN = "VID_057E"


def _run_ps(script: str, timeout: int = 20) -> str:
    """执行 PowerShell 片段，返回 stdout（失败返回空串）。"""
    try:
        from hidden_exec import run_hidden
        r = run_hidden(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=timeout,
        )
        return r.stdout or ""
    except Exception:
        return ""


def count_unknown() -> int:
    """统计 Status=Unknown 的 Nintendo 设备（真幽灵）。"""
    out = _run_ps(
        "Get-PnpDevice -ErrorAction SilentlyContinue | "
        f"Where-Object {{$_.InstanceId -match '{NINTENDO_PATTERN}' "
        "-and $_.Status -eq 'Unknown'} | "
        "Measure-Object | Select-Object -ExpandProperty Count"
    )
    out = out.strip()
    return int(out) if out.isdigit() else 0


def count_ghosts() -> int:
    """统计 Nintendo 相关设备节点数（含幽灵）。"""
    out = _run_ps(
        "Get-PnpDevice -ErrorAction SilentlyContinue | "
        f"Where-Object {{$_.InstanceId -match '{NINTENDO_PATTERN}'}} | "
        "Measure-Object | Select-Object -ExpandProperty Count"
    )
    out = out.strip()
    return int(out) if out.isdigit() else 0


def _is_admin() -> bool:
    out = _run_ps(
        "([Security.Principal.WindowsPrincipal]"
        "[Security.Principal.WindowsIdentity]::GetCurrent())"
        ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"
    )
    return out.strip().lower() == "true"


def remove_ghosts() -> int:
    """移除 Unknown 状态的 Nintendo 设备。需管理员。返回移除数。"""
    if not _is_admin():
        return 0

    script = (
        "$n=0; "
        "Get-PnpDevice -ErrorAction SilentlyContinue | "
        f"Where-Object {{$_.InstanceId -match '{NINTENDO_PATTERN}' -and "
        "$_.Status -eq 'Unknown'} | "
        "ForEach-Object { "
        "  pnputil /remove-device $_.InstanceId 2>$null | Out-Null; "
        "  if ($LASTEXITCODE -eq 0) { $n++ } "
        "}; "
        "Write-Output $n"
    )
    out = _run_ps(script, timeout=60)
    out = out.strip().splitlines()[-1] if out.strip() else "0"
    return int(out) if out.lstrip("-").isdigit() else 0


def remove_ghosts_elevated() -> int:
    """提权移除幽灵设备（会弹 UAC）。返回清理后剩余数量，失败返回 -1。

    非管理员无法 pnputil /remove-device，这是唯一可靠办法。
    """
    import os
    import tempfile

    before = count_ghosts()
    if before == 0:
        return 0

    script = (
        "Get-PnpDevice -ErrorAction SilentlyContinue | "
        f"Where-Object {{$_.InstanceId -match '{NINTENDO_PATTERN}' -and "
        "$_.Status -eq 'Unknown'} | "
        "ForEach-Object { pnputil /remove-device $_.InstanceId 2>$null | Out-Null }"
    )
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".ps1", text=True)
        os.close(fd)
        Path(path).write_text(script, encoding="utf-8-sig")
        from hidden_exec import run_hidden
        run_hidden(
            ["powershell", "-NoProfile", "-Command",
             f"Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
             f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','{path}'"],
            timeout=180,
        )
        return count_ghosts()
    except Exception:
        return -1
    finally:
        if path:
            try:
                os.remove(path)
            except Exception:
                pass


def cleanup_on_exit() -> None:
    """退出时调用。任何失败都不影响退出。"""
    # ★ HmBridge（原生 JC2 后端）是独立的管理员进程，必须先杀：
    #   它持有 HIDMaestro 的 device identity lease 和虚拟设备节点，
    #   不杀会以幽灵节点残留。放在最前，避免被后面的 return 跳过。
    try:
        from hidden_exec import run_hidden
        run_hidden(["taskkill", "/F", "/IM", "HmBridge.exe"], timeout=8)
    except Exception:
        pass

    try:
        # 先看有多少是 Unknown（真幽灵）——活跃设备不该动
        unknown = count_unknown()
        before = count_ghosts()
        if before == 0:
            return
        if unknown == 0:
            info(f"[清理] {before} 个设备节点均为活跃状态，跳过")
            return
        # ═══ 2026-11-17：改为**每次退出都清理**，不再设阈值 ═══
        #
        # 用户要求：幽灵设备每次退出程序后都要清理。
        #
        # 旧行为：非管理员且 unknown < 5 就跳过，理由是"避免每次弹 UAC"。
        # 实际后果：残留会累积（实测到 8 个），而且幽灵节点会让
        # Windows / GamepadTester 枚举到重复设备 —— 这本身就是
        # 排查"摇杆偏移"时的一个污染源（可能读到的是旧节点的数据）。
        #
        # 现在：只要有 Unknown 节点就清理，非管理员则提权。
        # 提权只覆盖 pnputil /remove-device，不重启任何服务。
        if _is_admin():
            m = remove_ghosts()
            if m:
                info(f"[清理] 已移除 {m} 个残留设备")
            else:
                info(f"[清理] 未发现可移除的残留设备")
        else:
            left = remove_ghosts_elevated()
            if left == 0:
                info(f"[清理] 已提权清理（原 {before} 个节点，剩余 0）")
            elif left > 0:
                warning(f"[清理] 提权后仍残留 {left} 个设备")
            else:
                # -1：用户拒绝了 UAC 或提权失败
                warning(f"[清理] 提权未完成，{unknown} 个幽灵节点仍残留"
                        f"（可手动以管理员运行一次以彻底清除）")
    except Exception as e:
        warning(f"[清理] 设备清理失败: {type(e).__name__}: {e}")
