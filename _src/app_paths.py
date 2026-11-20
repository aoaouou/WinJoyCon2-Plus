# -*- coding: utf-8 -*-
"""统一的路径解析：所有文件一律按**程序所在目录**定位。

为什么需要这个模块
------------------
之前 config.ini / joy2win.log / crash.log 全用相对路径，等于跟着"当前工作目录"走。
从这些位置启动时工作目录不是程序目录：
  CMD 在系统目录下启动、计划任务、
  快捷方式没设"起始位置"、被其他程序 ShellExecute 拉起……
于是会去写系统目录下的 config.ini —— 无权限 -> PermissionError ->
启动即弹框崩溃（已实测踩过两次）。

正确做法：一律基于 exe / 脚本所在目录解析，绝对不接受 cwd。
"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """程序所在目录（打包版 = exe 所在目录；源码版 = 脚本所在目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def app_path(name: str) -> str:
    """把文件名解析成程序目录下的绝对路径；绝对路径原样返回。"""
    if os.path.isabs(name):
        return name
    return os.path.join(app_dir(), name)


def config_path() -> str:
    """config.ini 的唯一位置：<程序目录>/config/config.ini。

    所有读写配置的代码都必须走这里，不要各自拼 "config.ini"。
    曾经因为配置移到 config/ 子目录但部分代码仍读根目录 config.ini，
    导致 [KnownSides] 读不到 -> 左右手柄随机分配、按键失灵。
    """
    return os.path.join(app_dir(), "config", "config.ini")


