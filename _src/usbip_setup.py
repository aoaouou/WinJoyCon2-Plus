# -*- coding: utf-8 -*-
"""USB/IP 检测与一键安装 + KnownSides 左右记忆查询 —— WinJoyCon2-Plus 1.1。"""
from __future__ import annotations

import configparser
import os
import subprocess
import sys

from app_paths import app_path, config_path

USBIP_EXE = r"C:\Program Files\USBip\usbip.exe"
USBIP_LOCAL = "usbip.exe"   # 随项目附带的便携版（若有）

# 常见 usbip.exe 安装位置（参考 usbip-win2 v0.9.7.7 的定位逻辑）
_CANDIDATES = [
    r"C:\Program Files\USBip\usbip.exe",
    r"C:\Program Files\USBip\bin\usbip.exe",
    r"C:\Program Files (x86)\USBip\usbip.exe",
    r"C:\Program Files\usbip-win2\usbip.exe",
]


def is_usbip_installed() -> bool:
    """检测 USB/IP 是否可用：系统常见路径 / PATH / 项目随附。"""
    import shutil
    for p in _CANDIDATES:
        if os.path.exists(p):
            return True
    # PATH 里找
    if shutil.which("usbip.exe") or shutil.which("usbip"):
        return True
    # 用户级安装
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Programs", "USBip", "usbip.exe")
    if local and os.path.exists(local):
        return True
    # 项目随附便携版
    try:
        for rel in (USBIP_LOCAL, os.path.join("usbip-win2", "v0.9.7.7", "usbip.exe"),
                    os.path.join("usbip-win", USBIP_LOCAL)):
            p = app_path(rel)
            if p and os.path.exists(p):
                return True
    except Exception:
        pass
    return False


def get_usbip_exe() -> str:
    """返回可用的 usbip.exe 路径（优先系统，其次随附便携版）。"""
    if os.path.exists(USBIP_EXE):
        return USBIP_EXE
    try:
        p = app_path(USBIP_LOCAL)
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    return ""


def install_usbip() -> tuple[bool, str]:
    """一键安装 USB/IP：优先运行项目随附的 installer（需管理员）。

    返回 (是否成功启动安装, 说明)。真正的安装结果与提权由调用方/GUI 处理。
    """
    # 找随项目附带的安装包：install_usbip.ps1 / usbip installer exe
    for name in ("install_usbip.ps1", "usbip-install.exe", "install_usbip.bat"):
        try:
            p = app_path(name)
        except Exception:
            p = ""
        if p and os.path.exists(p):
            try:
                if name.endswith(".ps1"):
                    subprocess.Popen([
                        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", p], shell=False)
                else:
                    subprocess.Popen([p], shell=False)
                return True, f"已启动安装程序：{name}（如弹出 UAC 请允许）"
            except Exception as exc:
                return False, f"启动安装程序失败：{exc}"
    return False, "未找到随附的 USB/IP 安装包，请把安装包放在程序目录后重试。"


def get_known_sides() -> dict:
    """读取 config.ini [KnownSides]，返回 {'left': mac, 'right': mac}。"""
    out = {}
    try:
        parser = configparser.ConfigParser()
        path = config_path()
        if os.path.exists(path):
            parser.read(path, encoding="utf-8")
            if "KnownSides" in parser:
                for side in ("left", "right"):
                    out[side] = parser["KnownSides"].get(side, "").strip()
    except Exception:
        pass
    return out


def sides_calibrated() -> bool:
    """左右都已记录（非空）→ True，允许一键连接。"""
    ks = get_known_sides()
    return bool(ks.get("left")) and bool(ks.get("right"))


def reset_known_sides() -> tuple[bool, str]:
    """清空左右记忆（纯净测试/纠正用）：清 [KnownSides] 与首次须知标志。

    返回 (是否成功, 说明/错误)。不静默吞异常 —— GUI 要能把结果告诉用户。
    """
    try:
        parser = configparser.ConfigParser()
        path = config_path()
        if not os.path.exists(path):
            return False, f"配置文件不存在：{path}"
        parser.read(path, encoding="utf-8")
        removed = False
        if "KnownSides" in parser:
            parser.remove_section("KnownSides")
            removed = True
        if "General" not in parser:
            parser["General"] = {}
        parser["General"]["first_run_done"] = "0"
        with open(path, "w", encoding="utf-8") as f:
            parser.write(f)
        return True, f"已清空左右记忆（{'有记录被移除' if removed else '原本就没有记录'}）\n{path}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def first_run_done() -> bool:
    """首次启动须知是否已完成（[General] first_run_done=1）。"""
    try:
        parser = configparser.ConfigParser()
        path = config_path()
        if os.path.exists(path):
            parser.read(path, encoding="utf-8")
            if "General" in parser:
                return parser["General"].get("first_run_done", "0").strip() == "1"
    except Exception:
        pass
    return False


def mark_first_run_done():
    parser = configparser.ConfigParser()
    path = config_path()
    if os.path.exists(path):
        parser.read(path, encoding="utf-8")
    if "General" not in parser:
        parser["General"] = {}
    parser["General"]["first_run_done"] = "1"
    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)


# ── 国际化文案（供 GUI 使用）────────────────────────────────────────────
I18N = {
    "notice_title_zh": "首次使用须知 · WinJoyCon2-Plus 1.1",
    "notice_title_en": "First-run Notice · WinJoyCon2-Plus 1.1",
    "notice_zh": (
        "欢迎使用 WinJoyCon2-Plus！\n\n"
        "本程序把 Joy-Con 2 桥接为虚拟 Joy-Con 1，供模拟器/游戏使用。首次使用请注意：\n\n"
        "1. 需要 USB/IP 才能建立虚拟手柄。若未安装，请点「一键安装 USB/IP」并按提示完成。\n"
        "2. 新手柄第一次使用必须「分开连接」：先手动选左手柄、再选右手柄。"
        "程序会记住左右，之后即可用「一键连接」快速连上。\n"
        "3. 手柄需先按任意键唤醒，再长按 SYNC 键 3-5 秒进入配对模式。\n\n"
        "本项目为个人交互操作研究作品，与 Nintendo® 无关，仅供合法拥有的硬件使用。\n"
        "Joy-Con™、Nintendo Switch™ 为 Nintendo® 商标。"
    ),
    "notice_en": (
        "Welcome to WinJoyCon2-Plus!\n\n"
        "This app bridges Joy-Con 2 to virtual Joy-Con 1 for emulators/games. Notes for first use:\n\n"
        "1. USB/IP is required. If not installed, click \"Install USB/IP\" and follow the prompts.\n"
        "2. New controllers must be connected separately first: pick Left, then Right. "
        "The app remembers the sides, after which \"Connect Both\" is unlocked.\n"
        "3. Wake the controller with any button, then hold SYNC 3-5s to pair.\n\n"
        "This is a personal interoperability project, not affiliated with Nintendo. "
        "Use only with hardware you legally own."
    ),
    "install_btn_zh": "🔧 一键安装 USB/IP",
    "install_btn_en": "🔧 Install USB/IP",
    "usbip_ok_zh": "USB/IP 已就绪",
    "usbip_ok_en": "USB/IP ready",
    "usbip_missing_zh": "USB/IP 未检测到",
    "usbip_missing_en": "USB/IP not detected",
}
