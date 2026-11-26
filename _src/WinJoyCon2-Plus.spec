# -*- mode: python ; coding: utf-8 -*-
"""WinJoyCon2-Plus v1.3（HIDMaestro 原生 Joy-Con 2 后端）打包配置。

把 HmBridge（C# 桥接 + HIDMaestro.Core.dll + JC2 profiles）打进单文件。
运行时 hidmaestro_out._bridge_paths() 会在 _MEIPASS 下找到它们。
"""

import os as _os

_hb = 'hidmaestro_bridge/bin'
_dll = _os.path.join(_hb, 'HIDMaestro.Core.dll')
_exe = _os.path.join(_hb, 'HmBridge.exe')
_profiles = 'hidmaestro_profiles'

_binaries = []
_datas = []
# .NET 独立运行需要 exe + dll + runtimeconfig + deps 四件套
for _name in ('HmBridge.exe', 'HmBridge.dll', 'HmBridge.runtimeconfig.json',
              'HmBridge.deps.json', 'HIDMaestro.Core.dll'):
    _p = _os.path.join(_hb, _name)
    if _os.path.exists(_p):
        _binaries.append((_p, 'hidmaestro_bridge'))
if _os.path.isdir(_profiles):
    _datas.append((_profiles, 'hidmaestro_bridge/hidmaestro_profiles'))

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=[
        'theme', 'i18n', 'config', 'virtual',
        'virtual.reports', 'virtual.hidmaestro_out', 'virtual.imu_proc',
        'virtual.scroll', 'virtual.rumble_hd', 'virtual.jc2_frame',
        'device_cleanup', 'hidden_exec',
        'control_type', 'control_type.duo_joycon', 'control_type.single_joycon',
        'control_type.mouse_mode', 'controllers', 'controllers.JoyconL',
        'controllers.JoyconR', 'error_handler',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WinJoyCon2-Plus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['HmBridge.exe', 'HIDMaestro.Core.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['logo_256.ico'],
)
