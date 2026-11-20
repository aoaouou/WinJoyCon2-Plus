"""打包残留清理（走回收站，不永久删）。

约定第 5 条：一律 SHFileOperationW + FOF_ALLOWUNDO。
"""
import ctypes
import os
import sys
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"D:\Games\Nintendo\tool\Joycon2\_src"

FO_DELETE = 3
FOF_ALLOWUNDO = 0x40
FOF_NOCONFIRMATION = 0x10
FOF_SILENT = 0x4


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def to_recycle(path):
    if not os.path.exists(path):
        return None
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = path + "\0\0"
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))


targets = []
for name in ("Switch1Pad.spec", "build", "dist"):
    targets.append(os.path.join(BASE, name))

# 所有 __pycache__
for root, dirs, _files in os.walk(BASE):
    if "__pycache__" in dirs:
        targets.append(os.path.join(root, "__pycache__"))

for t in targets:
    rc = to_recycle(t)
    if rc is None:
        print(f"  skip (不存在) {t}")
    else:
        print(f"  rc={rc}  {t}")
