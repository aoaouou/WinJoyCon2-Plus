from controllers.JoyconL import JoyConLeft
from controllers.JoyconR import JoyConRight

from controller_command import ControllerCommand, UUID_CMD

from config import Config
from pynput.mouse import Controller, Button
from logger_config import info, warning, error, debug
import control_type.mouse_mode as mm

def dbg(msg):
    try:
        debug(msg)
    except Exception:
        print(msg, flush=True)

from virtual.reports import Ns2Bit
from app_paths import app_path, config_path  # noqa: E402

# C 键 / SL / SR 的可选映射目标。
# 值直接用 Joy-Con 语义位（Ns2Bit），不经过 XInput。
C_KEY_TARGETS = [
    ("", "不映射"),
    ("A", Ns2Bit.A),
    ("B", Ns2Bit.B),
    ("X", Ns2Bit.X),
    ("Y", Ns2Bit.Y),
    ("L", Ns2Bit.L),
    ("R", Ns2Bit.R),
    ("ZL", Ns2Bit.ZL),
    ("ZR", Ns2Bit.ZR),
    ("MINUS", Ns2Bit.MINUS),
    ("PLUS", Ns2Bit.PLUS),
    ("LS", Ns2Bit.LS),
    ("RS", Ns2Bit.RS),
    ("HOME", Ns2Bit.HOME),
    ("CAPTURE", Ns2Bit.CAPTURE),
    ("UP", Ns2Bit.UP),
    ("DOWN", Ns2Bit.DOWN),
    ("LEFT", Ns2Bit.LEFT),
    ("RIGHT", Ns2Bit.RIGHT),
]
C_KEY_MAP = dict(C_KEY_TARGETS)
# 旧配置里 SL/SR 映射目标可能存的是 "L3"/"R3"（旧键名）。
# JoyCon 上本来叫 LS/RS，这里补上别名，老配置无需迁移即可继续匹配。
C_KEY_MAP["L3"] = Ns2Bit.LS
C_KEY_MAP["R3"] = Ns2Bit.RS


def get_default_controls():
    """默认映射表。

    结构保持不变（Left/Right 两个 dict），但**值改为 Joy-Con 语义位**，
    不再用 XUSD 按钮枚举。update() 里直接读 joyconL.buttons 的布尔值，
    这个表只用来承载 C 键 / SL / SR 的自定义映射结果。
    """
    return {
        "Left": {
            "ZL": Ns2Bit.ZL,
            "L": Ns2Bit.L,
            "LS": Ns2Bit.LS,
            "Up": Ns2Bit.UP,
            "Down": Ns2Bit.DOWN,
            "Left": Ns2Bit.LEFT,
            "Right": Ns2Bit.RIGHT,
            "Minus": Ns2Bit.MINUS,
            "Capture": Ns2Bit.CAPTURE,
            "SLL": Ns2Bit.SL_L,
            "SRL": Ns2Bit.SR_L,
        },
        "Right": {
            "ZR": Ns2Bit.ZR,
            "R": Ns2Bit.R,
            "RS": Ns2Bit.RS,
            "A": Ns2Bit.A,
            "B": Ns2Bit.B,
            "X": Ns2Bit.X,
            "Y": Ns2Bit.Y,
            "Plus": Ns2Bit.PLUS,
            "Home": Ns2Bit.HOME,
            "SLR": Ns2Bit.SL_R,
            "SRR": Ns2Bit.SR_R,
        }
    }


# Per-pair control mappings
pair_controls = {}


def get_pair_controls(pair_id: int):
    """Get or create control mapping for a pair, loading from config if available"""
    if pair_id not in pair_controls:
        # Start with default controls
        controls = get_default_controls()
        
        # Try to load SL/SR mappings from config for this pair
        try:
            import configparser
            import os
            
            parser = configparser.ConfigParser()
            if os.path.exists(config_path()):
                parser.read(config_path())
                
                section = f'Pair_{pair_id}'
                if section in parser:
                    # Load SL/SR mappings from config
                    sll = parser[section].get('sll_mapping', '')
                    srl = parser[section].get('srl_mapping', '')
                    slr = parser[section].get('slr_mapping', '')
                    srr = parser[section].get('srr_mapping', '')
                    
                    # Update mappings
                    controls["Left"]["SLL"] = C_KEY_MAP.get(sll) if sll else Ns2Bit.SL_L
                    controls["Left"]["SRL"] = C_KEY_MAP.get(srl) if srl else Ns2Bit.SR_L
                    controls["Right"]["SLR"] = C_KEY_MAP.get(slr) if slr else Ns2Bit.SL_R
                    controls["Right"]["SRR"] = C_KEY_MAP.get(srr) if srr else Ns2Bit.SR_R


        except Exception as e:
            pass  # Silent fail if config not found
        
        pair_controls[pair_id] = controls
    
    return pair_controls[pair_id]


def update_sl_sr_mappings_for_pair(pair_id: int, sll: str, srl: str, slr: str, srr: str):
    """Update SL/SR button mappings for a specific pair"""
    try:
        controls = get_pair_controls(pair_id)
        controls["Left"]["SLL"] = C_KEY_MAP.get(sll) if sll else Ns2Bit.SL_L
        controls["Left"]["SRL"] = C_KEY_MAP.get(srl) if srl else Ns2Bit.SR_L
        controls["Right"]["SLR"] = C_KEY_MAP.get(slr) if slr else Ns2Bit.SL_R
        controls["Right"]["SRR"] = C_KEY_MAP.get(srr) if srr else Ns2Bit.SR_R
    except Exception as e:
        pass  # Silent fail


import threading
import time
import asyncio


# Per-pair Joy-Con instances (keyed by pair_id)
# Each pair gets its own JoyConLeft/JoyConRight to avoid cross-pair data corruption
_pair_joycons = {}  # pair_id -> {"Left": JoyConLeft, "Right": JoyConRight}


def _get_pair_joycons(pair_id: int):
    """Get or create Joy-Con instances for a specific pair"""
    if pair_id not in _pair_joycons:
        _pair_joycons[pair_id] = {
            "Left": JoyConLeft(),
            "Right": JoyConRight(),
        }
    return _pair_joycons[pair_id]


def reset_joycon_instances(pair_id: int = None):
    """Reset Joy-Con controller instances for a pair (called when reconnecting).

    If pair_id is None, resets all pairs (legacy behavior).
    """
    if pair_id is not None:
        if pair_id in _pair_joycons:
            _pair_joycons[pair_id] = {
                "Left": JoyConLeft(),
                "Right": JoyConRight(),
            }
    else:
        _pair_joycons.clear()


def reset_pair_joycons(pair_id: int):
    """Reset a specific pair's Joy-Con instances (called on disconnect)."""
    if pair_id in _pair_joycons:
        del _pair_joycons[pair_id]

# Store clients for vibration, keyed by pair_id -> {side: client}
vibration_clients = {}
# Track the exact gamepad object that owns each registered callback. A pair's
# virtual gamepad is recreated after a full disconnect, so pair_id alone is
# not sufficient for reconnect handling.
_vibration_registered_gamepads = {}
# Store event loop for thread-safe callback
_event_loop = None
# Per-pair vibration setting
_pair_vibration_enabled = {}

def set_vibration_enabled(enabled, pair_id: int = 0):
    """Set whether vibration feedback is enabled for one pair."""
    _pair_vibration_enabled[pair_id] = enabled

# Vibration callback function
#
# ⚠ 2026-11-16 已废除此路径的预置样本发送。
#
# 旧实现发 `0A 91 01 02 ... 01` = command 0x0A subcmd 0x02「播放预置样本 #1」。
# 官方文档（s2r_commands.md:678）对该样本的描述是：
#     `0x1 | Low frequency buzz, ~1s`
# 即每次都在播放一段**约 1 秒的低频嗡鸣**。
# 而本回调每秒被调用 200+ 次 → 每秒重放 200 次「1 秒嗡鸣」
# → LRA 持续过驱、停不下来 → 摇杆 ADC 被物理带偏（方向恒定居中于某角）。
# 这是「震动导致摇杆偏移」的真正物理根因。
#
# 震动现在只走 HD 通道：hid_function → rumble_cb → rumble_hd →
# GATT 0x0012。振幅逐帧精确映射，没有"1 秒样本"语义，不会过驱。
# 本函数保留成空壳仅为兼容既有调用点（send_vibration / GUI 开关）。
# 震动只走 HD 通道：hid_function → rumble_cb → rumble_hd → GATT 0x0012。
#
# 2026-11-17 最终定案：曾以为是"持续写 GATT 抢占 BLE"导致摇杆跳变，
# 做了多轮降频/去重/傻震对照都无效。真正根因是 hid_function 把震动
# Output Report 0x01/0x10 误判为子命令、伪造了一个摇杆字段全 0 的
# 输入报告（见 virtual/hid_function.py 的修复与注释）。
# 与本文件无关 —— 这里保持空实现，震动完全由 HD 通道负责。
async def send_vibration_to_client(client, large_motor, small_motor):
    """已停用：震动由 HD 通道（GATT 0x0012）负责，见 rumble_hd.py。"""
    return

async def send_vibration(pair_id, large_motor, small_motor):
    """已停用：HD 通道负责真正的震动输出。保留签名以免回调链断裂。"""
    return

def vibration_callback(pair_id, client, target, large_motor, small_motor, led_number, user_data):
    """Callback for gamepad vibration feedback from vgamepad"""
    if not _pair_vibration_enabled.get(pair_id, True):
        return

    global _event_loop
    if _event_loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(send_vibration(pair_id, large_motor, small_motor), _event_loop)
        except Exception as e:
            pass  # Silent fail

def _make_vibration_callback(pair_id):
    """Create a vgamepad-compatible vibration callback that captures pair_id via closure"""
    def callback(client, target, large_motor, small_motor, led_number, user_data):
        vibration_callback(pair_id, client, target, large_motor, small_motor, led_number, user_data)
    return callback

def register_vibration(client, side, pair_id: int = 0):
    """Register/update a client for vibration on a specific pair.

    Always updates the client reference (so reconnected Joy-Cons get
    their new client stored). Only registers the gamepad callback once
    per pair (vgamepad.register_notification).
    """
    if pair_id not in vibration_clients:
        vibration_clients[pair_id] = {}
    previous_client = vibration_clients[pair_id].get(side)
    vibration_clients[pair_id][side] = client
    if previous_client is not client:
        info(f"[VIBRATION] client updated: pair_id={pair_id} side={side}")

    # Register once per actual gamepad object. A reconnect can create a new
    # VX360Gamepad for the same pair_id and needs a fresh callback.
    from controller_manager import get_controller_manager
    manager = get_controller_manager()
    pair = manager.get_pair(pair_id)
    if pair and pair.gamepad:
        if _vibration_registered_gamepads.get(pair_id) is not pair.gamepad:
            try:
                pair.gamepad.register_notification(_make_vibration_callback(pair_id))
                _vibration_registered_gamepads[pair_id] = pair.gamepad
                info(f"[VIBRATION] callback registered on gamepad for pair_id={pair_id}")
            except Exception as e:
                error(f"[VIBRATION] register_notification failed: {e}")
    else:
        warning(f"[VIBRATION] cannot register: pair={pair is not None}, gamepad={pair.gamepad if pair else 'N/A'}")


def unregister_vibration(side: str, pair_id: int = 0):
    """Remove a client from vibration tracking (called on disconnect)."""
    try:
        from virtual.rumble_hd import detach_client
        detach_client("left" if side == "Left" else "right")
    except Exception:       # noqa: BLE001
        pass
    if pair_id in vibration_clients and side in vibration_clients[pair_id]:
        del vibration_clients[pair_id][side]
        info(f"[VIBRATION] unregistered side={side} from pair_id={pair_id}")
        # If both sides are gone, clean up the pair entry entirely
        if not vibration_clients[pair_id]:
            del vibration_clients[pair_id]
            _vibration_registered_gamepads.pop(pair_id, None)


# Per-pair update locks to serialize gamepad access from Left/Right notifications
_pair_update_locks = {}


def _get_pair_update_lock(pair_id: int):
    """Get or create an asyncio lock for serializing update() calls per pair."""
    if pair_id not in _pair_update_locks:
        _pair_update_locks[pair_id] = asyncio.Lock()
    return _pair_update_locks[pair_id]


# Per-pair state for duo mode
pair_state = {}
# Lock to protect pair_state dict fields from concurrent read-modify-write
# between mouse_loop (thread) and update() (event loop)
_pair_state_lock = threading.RLock()
_mouse_loop_thread = None
_mouse_loop_start_lock = threading.Lock()
_mouse_wakeup = threading.Event()

# Per-pair mouse enabled state (set from GUI)
pair_mouse_enabled = {}


def get_pair_state(pair_id: int):
    """Get or create state for a pair"""
    with _pair_state_lock:
        if pair_id not in pair_state:
            pair_state[pair_id] = {
                'targetX': 0,
                'targetY': 0,
                'previousMouseX': 0,
                'previousMouseY': 0,
                'leftPressed': False,
                'rightPressed': False,
                'middlePressed': False,   # 鼠标中键按下态（边沿）
                'forwardPressed': False,  # 侧键2 前进
                'backPressed': False,     # 侧键1 后退
                'wheelAcc': 0.0,          # 滚轮力度累积器（模拟量连续滚动）
                'joyconMouseMode': None,
                'firstCall': False,
                # 左右两侧各自独立的鼠标状态（Windows 原生叠加多鼠标）
                'sides': {
                    "Left": _new_side_mouse_state(),
                    "Right": _new_side_mouse_state(),
                },
            }
        return pair_state[pair_id]


def _new_side_mouse_state():
    """单侧手柄的鼠标运行时状态（按键按下态 / 光标基准 / 滚轮累积）。"""
    return {
        'prevX': 0,
        'prevY': 0,
        'baseline': False,        # 是否已建立光标基准（防进入瞬间跳变）
        'leftPressed': False,
        'rightPressed': False,
        'middlePressed': False,
        'forwardPressed': False,
        'backPressed': False,
        'wheelAcc': 0.0,
        'actPrev': {},            # keymap 点按动作边沿检测 {按钮: 上次按下}
    }


def set_mouse_enabled(pair_id: int, enabled: bool):
    """兼容旧调用：同时开关左右手柄的鼠标模式。"""
    pair_mouse_enabled[pair_id] = enabled
    for side in ("Left", "Right"):
        mm.set_mode(pair_id, side, mm.MODE_MOUSE if enabled else mm.MODE_GAMEPAD,
                    persist=False)


def is_mouse_enabled(pair_id: int) -> bool:
    """兼容查询：任一侧处于指针模式即视为启用。"""
    return (mm.is_in_pointer_mode(pair_id, "Left") or
            mm.is_in_pointer_mode(pair_id, "Right"))


def mouse_loop():
    """Global mouse loop - handles all pairs"""
    while True:
        movements = []
        with _pair_state_lock:
            for state in pair_state.values():
                # Truncate towards zero and always consume a non-zero remainder.
                # ``//`` made tiny positive moves disappear and biased negative
                # moves, which made pointer control feel delayed and uneven.
                stepX = int(state['targetX'] / 6)
                stepY = int(state['targetY'] / 6)
                if stepX == 0 and state['targetX']:
                    stepX = 1 if state['targetX'] > 0 else -1
                if stepY == 0 and state['targetY']:
                    stepY = 1 if state['targetY'] > 0 else -1
                if stepX != 0 or stepY != 0:
                    state['targetX'] -= stepX
                    state['targetY'] -= stepY
                else:
                    continue
                movements.append((stepX, stepY))
        # pynput can block; do not hold the state lock while calling it.
        if movements:
            for stepX, stepY in movements:
                mouse.move(stepX, stepY)
            time.sleep(0.006)
        else:
            _mouse_wakeup.wait()
            _mouse_wakeup.clear()


mouse = Controller()


def _screen_size():
    """取**当前主屏**的像素尺寸（自适应任意分辨率/缩放）。

    ★ 必须动态取，不能硬编码：用户屏幕可能是 2560x1600 / 1920x1080 / 4K。
    ★ 不能用 pynput Controller.size —— 该对象没有 size 属性（实测
      AttributeError），旧实现的异常被 except 吞掉，导致"回中心"静默失效。

    取值优先级（先准后稳）：
      1) Qt 的 primaryScreen —— 本程序是 Qt 应用，Qt 自己已处理 DPI 缩放，
         拿到的一定是逻辑像素坐标系，与 pynput 的 position 一致。
      2) Win32 GetSystemMetrics + SetProcessDPIAware —— 无 Qt 时回退。
      3) 1920x1080 兜底（只为避免除零，不让功能崩）。
    """
    # ① Qt：GUI 应用最可靠，且与 pynput 坐标系一致
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            scr = app.primaryScreen()
            if scr is not None:
                g = scr.geometry()
                if g.width() > 0 and g.height() > 0:
                    return int(g.width()), int(g.height())
    except Exception:
        pass

    # ② Win32（打开 DPI 感知后才是物理像素）
    try:
        import ctypes
        u = ctypes.windll.user32
        try:
            u.SetProcessDPIAware()
        except Exception:
            pass
        w = int(u.GetSystemMetrics(0))   # SM_CXSCREEN
        h = int(u.GetSystemMetrics(1))   # SM_CYSCREEN
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass

    # ③ 兜底
    return 1920, 1080


def _center_cursor():
    """把光标移到主屏幕中心（陀螺仪长时间累计漂移后一键归位）。"""
    try:
        w, h = _screen_size()
        mouse.position = (w // 2, h // 2)
    except Exception:
        pass


def _trigger_macro(pair_id: int, trigger_key: str = None):
    """回放该 pair 指定 SL/SR 键绑定的宏。trigger_key 如 'slr'/'sll'。"""
    cfg = mm.get_config(pair_id)
    binding = cfg.get("macro_bindings", {})
    macros = cfg.get("macros", {})
    name = None
    if trigger_key:
        # 精确匹配 + 大小写不敏感
        for k in (trigger_key, trigger_key.upper()):
            if k in binding:
                name = binding[k]
                break
    if name is None and macros:
        name = next(iter(macros))
    if name is None:
        return
    steps = macros.get(name, [])
    _action_click = {
        mm.ACT_LEFT: Button.left, mm.ACT_RIGHT: Button.right,
        mm.ACT_MIDDLE: Button.middle, mm.ACT_FWD: Button.x2,
        mm.ACT_BACK: Button.x1,
    }
    for act in steps:
        try:
            if act in _action_click:
                mouse.click(_action_click[act])
            elif act in (mm.ACT_SCROLL_UP, mm.ACT_SCROLL_DOWN):
                mouse.scroll(0, 1 if act == mm.ACT_SCROLL_UP else -1)
        except Exception:
            pass


def cleanup_disconnected_joycon(pair_id: int, side: str, pair_empty: bool = False):
    """Clear cached input/mouse state after a Joy-Con disconnects."""
    if pair_empty:
        _pair_joycons.pop(pair_id, None)
    elif pair_id in _pair_joycons and side in ("Left", "Right"):
        _pair_joycons[pair_id][side] = JoyConLeft() if side == "Left" else JoyConRight()

    with _pair_state_lock:
        state = pair_state.get(pair_id)
        if state is not None:
            for _side in ("Left", "Right"):
                ss = state.get('sides', {}).get(_side)
                if ss is None:
                    continue
                for _btn, _attr in ((Button.left, 'leftPressed'),
                                    (Button.right, 'rightPressed'),
                                    (Button.middle, 'middlePressed'),
                                    (Button.x2, 'forwardPressed'),
                                    (Button.x1, 'backPressed')):
                    if ss.get(_attr):
                        try:
                            mouse.release(_btn)
                        except Exception:
                            pass
                    ss[_attr] = False
                ss['baseline'] = False
                ss['wheelAcc'] = 0.0
            state['targetX'] = 0
            state['targetY'] = 0
            if pair_empty or state['joyconMouseMode'] == side:
                state['joyconMouseMode'] = None
            if pair_empty:
                pair_state.pop(pair_id, None)

    # C 键边沿状态也要清，避免断连残留按下态
    mm.reset_c_key(pair_id)
    if pair_empty:
        mm.reset_pair(pair_id)

    if pair_empty:
        _pair_update_locks.pop(pair_id, None)


def _push_motion(gamepad, side: str, joycon) -> None:
    """把 Joy-Con 2 的体感送进输出层。

    **用原始 int16，不做任何换算或轴重排。**

    原因：Joy2Win 的 JoyconL.py 里对 IMU 做了轴重排
        accelerometer: X=-ax, Y=-az, Z=ay
        gyroscope:     X=gx,  Y=-gz,  Z=gy
    那是给 DSU / Xbox 输出用的坐标约定。Joy-Con 1 的 0x30 报告
    要的是**传感器原始轴序**，套用那套重排会让体感方向全错。

    实测数据（左手柄静止放在桌上，原始 raw）：
        accel=(649, 2112, 3418)  gyro=(98, 103, -6)
    Z 轴约 3418 ≈ 0.83G，说明手柄平放时重力确实主要在 Z 轴，
    符合 Joy-Con 的传感器坐标系。直接透传即可。
    """
    if not hasattr(gamepad, "set_imu_raw"):
        return
    raw = getattr(joycon, "imu_raw", None)

    # 诊断：每 200 帧记一次实际值，确认数据是否真的到了这一层
    _d = globals().setdefault("_imu_dbg", {})
    _d[side] = _d.get(side, 0) + 1
    if _d[side] % 200 == 1:
        info(f"[IMU] {side} 帧#{_d[side]} raw={raw}")

    if raw is None:
        return
    try:
        gamepad.set_imu_raw(side, raw)
    except Exception:
        pass


async def update(pair_id: int = 0):
    # Serialize per-pair updates so Left and Right notifications don't
    # interleave gamepad writes across an await boundary.
    async with _get_pair_update_lock(pair_id):
        from controller_manager import get_controller_manager
        manager = get_controller_manager()
        pair = manager.get_pair(pair_id)
        if not pair or not pair.gamepad:
            return

        gamepad = pair.gamepad
        state = get_pair_state(pair_id)
        controls = get_pair_controls(pair_id)

        # Get per-pair Joy-Con instances
        pair_joycons = _get_pair_joycons(pair_id)
        joyconLeft = pair_joycons["Left"]
        joyconRight = pair_joycons["Right"]

        # ── 组合键模式切换（C 为前缀）──
        # C+L / C+ZL / C+R / C+ZR 切对应侧模式；单 C 全回手柄；C+SL/SR 触发宏。
        rb = joyconRight.buttons
        lb = joyconLeft.buttons
        combo_action = mm.feed_combo(
            pair_id,
            c=bool(rb.get("GameChat")),
            l=bool(lb.get("L")), zl=bool(lb.get("ZL")),
            r=bool(rb.get("R")), zr=bool(rb.get("ZR")),
            sll=bool(lb.get("SLL")), srl=bool(lb.get("SRL")),
            slr=bool(rb.get("SLR")), srr=bool(rb.get("SRR")),
        )
        if combo_action:
            mm.mark_consumed(pair_id, combo_action)   # 本帧该修饰键不触发鼠标动作
        if combo_action.startswith("macro_") and mm.is_macro_enabled(pair_id):
            _trigger_macro(pair_id, combo_action[6:])   # 去掉 'macro_' 前缀
        # 修饰键松开后清除"已消费"标记，下次正常按下可触发鼠标动作
        _ck = mm._consumed.get(pair_id)
        if _ck:
            _still = {"L": lb.get("L"), "ZL": lb.get("ZL"),
                      "R": rb.get("R"), "ZR": rb.get("ZR")}.get(_ck)
            if not _still:
                mm.clear_consumed(pair_id)

        # 宏录制中：把本帧新按下的按钮记成鼠标动作序列
        rec = mm._macro_rec.get(pair_id)
        if rec and rec.get("recording"):
            _act_map = {mm.ACT_LEFT: mm.ACT_LEFT, mm.ACT_RIGHT: mm.ACT_RIGHT}
            _SYSTEM_KEYS = {"GameChat", "Plus", "Minus"}   # 固定功能键不入宏
            for _bname, _pressed in list(lb.items()) + list(rb.items()):
                if not _pressed or _bname in _SYSTEM_KEYS:
                    continue
                _prev = rec.setdefault("keyPrev", {})
                if _prev.get(_bname):
                    continue
                _prev[_bname] = True
                # 记录按钮语义作为一步（回放时按 ACT 解释，未映射则忽略）
                for _mode in (mm.MODE_MOUSE, mm.MODE_GYRO):
                    _a = mm.get_keymap(pair_id, _mode).get(_bname)
                    if _a:
                        mm.record_macro_step(pair_id, _a)
                        break
            for _bname, _pressed in list(lb.items()) + list(rb.items()):
                if not _pressed:
                    rec.get("keyPrev", {}).pop(_bname, None)

        mode_left = mm.get_mode(pair_id, "Left")
        mode_right = mm.get_mode(pair_id, "Right")
        left_on = mm.is_in_pointer_mode(pair_id, "Left")
        right_on = mm.is_in_pointer_mode(pair_id, "Right")

        # 供下方"哪些手柄不投手柄按键/摇杆/体感"判断用
        previous_mouse_mode = state['joyconMouseMode']
        state['joyconMouseMode'] = ("both" if left_on and right_on else
                                    "Left" if left_on else
                                    "Right" if right_on else None)

        # 某侧退出指针模式时，清掉该侧按键态 + 基准，避免卡键/再开时跳变
        for _side, _on in (("Left", left_on), ("Right", right_on)):
            ss = state['sides'][_side]
            if not _on and (ss['leftPressed'] or ss['rightPressed'] or ss['middlePressed']
                            or ss['forwardPressed'] or ss['backPressed'] or ss['baseline']):
                with _pair_state_lock:
                    for _btn, _attr in ((Button.left, 'leftPressed'),
                                        (Button.right, 'rightPressed'),
                                        (Button.middle, 'middlePressed'),
                                        (Button.x2, 'forwardPressed'),
                                        (Button.x1, 'backPressed')):
                        if ss[_attr]:
                            try:
                                mouse.release(_btn)
                            except Exception:
                                pass
                        ss[_attr] = False
                    ss['baseline'] = False
                    ss['wheelAcc'] = 0.0

        global _mouse_loop_thread
        if left_on or right_on:
            with _mouse_loop_start_lock:
                if _mouse_loop_thread is None or not _mouse_loop_thread.is_alive():
                    _mouse_loop_thread = threading.Thread(target=mouse_loop, daemon=True)
                    _mouse_loop_thread.start()

        # ================= 按键 / 摇杆 / 体感 直投 =================
        #
        # 这里**不再经过 XInput 那一套**（press_button / left_joystick /
        # left_trigger 等）。那套是给虚拟 Xbox 手柄用的中间层：
        #   XUSB 位 -> VirtualJoyCon1 再翻译成 Joy-Con 位
        # 多一层翻译就多一层出错机会，而且语义本身对不上
        # （Joy-Con 没有"扳机模拟量"、没有"ABXY 四色"那套）。
        #
        # 现在直接用 Joy-Con 原生接口：输出层接收
        #   set_buttons(Ns2Bit) / set_stick(side, x, y) / set_motion(...)
        # 位定义与 Joy-Con 1 的 0x30 报告一一对应，没有二次翻译。

        n = Ns2Bit
        left_bits = n(0)
        right_bits = n(0)

        # ---- 左手柄 ----
        if state.get('joyconMouseMode') != "Left":
            b = joyconLeft.buttons
            if b.get("Up"):      left_bits |= n.UP
            if b.get("Down"):    left_bits |= n.DOWN
            if b.get("Left"):    left_bits |= n.LEFT
            if b.get("Right"):   left_bits |= n.RIGHT
            if b.get("L"):       left_bits |= n.L
            if b.get("ZL"):      left_bits |= n.ZL
            if b.get("Minus"):   left_bits |= n.MINUS
            if b.get("LS"):      left_bits |= n.LS
            if b.get("Capture"): left_bits |= n.CAPTURE
            if b.get("SLL"):     left_bits |= n.SL_L
            if b.get("SRL"):     left_bits |= n.SR_L

        # ---- 右手柄 ----
        if state.get('joyconMouseMode') != "Right":
            b = joyconRight.buttons
            if b.get("A"):       right_bits |= n.A
            if b.get("B"):       right_bits |= n.B
            if b.get("X"):       right_bits |= n.X
            if b.get("Y"):       right_bits |= n.Y
            if b.get("R"):       right_bits |= n.R
            if b.get("ZR"):      right_bits |= n.ZR
            if b.get("Plus"):    right_bits |= n.PLUS
            if b.get("RS"):      right_bits |= n.RS
            if b.get("Home"):    right_bits |= n.HOME
            if b.get("SLR"):     right_bits |= n.SL_R
            if b.get("SRR"):     right_bits |= n.SR_R
            # C 键（GameChat）已专职切换鼠标/手柄模式，不再映射为手柄按键。

        if hasattr(gamepad, "set_buttons"):
            gamepad.set_buttons(left_bits, right_bits)

        # ---- 摇杆：直接给 Joy2Win 的 0..32768 原始值 ----
        # Joy2Win 的 joystick_decoder 输出 0..32768，中位 16384，
        # 与 Joy-Con 1 的 12 位摇杆（0..4095，中位 2048）是同一套线性关系，
        # 转换放在输出层做，这里不做任何换算。
        # ---- 摇杆 ----
        # 输入是 JC2 原始 12 位，直接透传给虚拟设备。
        if hasattr(gamepad, "set_stick"):
            # ★ 2026-11-18：直接透传原始 12 位，**不做任何映射**。
            #
            # 之前这里调 stick_map.map_stick() 做「自标定 + 死区 + 拉伸」，
            # 但虚拟设备已经通过 SPI（0x603D）告诉主机 center=2048/行程1400，
            # 主机会自己做校准。两边叠加 = 双重处理 → 漂移。
            #
            # 这正是用户观察到的现象：NS2 实机同样的 raw 数据毫无问题，
            # 说明漂移是链路里这一层多余处理造成的，不是硬件。
            #
            # set_stick 的契约本来就是透传（见 vjoy_out.set_stick 文档）：
            #   "JC2 原始 12 位直接透传，圆度/死区/回中由主机按 SPI 校准处理"
            left_in_mouse = state['joyconMouseMode'] == "Left"
            right_in_mouse = state['joyconMouseMode'] == "Right"

            if not left_in_mouse:
                gamepad.set_stick("left",
                                  joyconLeft.analog_stick["X"],
                                  joyconLeft.analog_stick["Y"])
            if not right_in_mouse:
                gamepad.set_stick("right",
                                  joyconRight.analog_stick["X"],
                                  joyconRight.analog_stick["Y"])

        # ---- 体感 ----
        if state['joyconMouseMode'] != "Left":
            _push_motion(gamepad, "left", joyconLeft)
        if state['joyconMouseMode'] != "Right":
            _push_motion(gamepad, "right", joyconRight)

        gamepad.update()

        # ── 灵敏度挡位：加减键专用，永远只调 DPI（不可自定义/不可录宏）──
        both_in_pointer = left_on and right_on
        plus_pressed = bool(right_on and rb.get("Plus"))
        minus_pressed = bool(left_on and lb.get("Minus"))
        mm.feed_dpi_keys(pair_id, plus_pressed, minus_pressed, both_in_pointer)

        # ── 指针动作：左右两侧独立处理，由 keymap 驱动，事件叠加给系统 ──
        cfg = mm.get_config(pair_id)
        scale = mm.get_dpi_scale(pair_id)
        for _side, _joycon, _on, _mode in (
                ("Left", joyconLeft, left_on, mode_left),
                ("Right", joyconRight, right_on, mode_right)):
            if not _on:
                continue
            ss = state['sides'][_side]
            keymap = mm.get_keymap(pair_id, _mode)
            btn = _joycon.buttons

            # 光标位移：mouse 模式用光学传感器 X/Y；gyro 模式用 IMU 角速度
            with _pair_state_lock:
                if _mode == mm.MODE_GYRO:
                    dx, dy = mm.gyro_cursor_delta(_side, getattr(_joycon, "imu_raw", None), pair_id)
                    state['targetX'] += dx
                    state['targetY'] += dy
                    if dx or dy:
                        _mouse_wakeup.set()
                else:
                    if not ss['baseline']:
                        ss['prevX'] = _joycon.mouse["X"]
                        ss['prevY'] = _joycon.mouse["Y"]
                        ss['baseline'] = True
                        deltaX = deltaY = 0
                    else:
                        deltaX = (_joycon.mouse["X"] - ss['prevX'] + 32768) % 65536 - 32768
                        deltaY = (_joycon.mouse["Y"] - ss['prevY'] + 32768) % 65536 - 32768
                        ss['prevX'] = _joycon.mouse["X"]
                        ss['prevY'] = _joycon.mouse["Y"]
                    state['targetX'] += deltaX * scale
                    state['targetY'] += deltaY * scale
                    if deltaX or deltaY:
                        _mouse_wakeup.set()

            # 按 keymap 分发左右键
            want_left = False
            want_right = False
            for _bname, _act in keymap.items():
                if not btn.get(_bname):
                    continue
                if mm.is_consumed(pair_id, _bname):   # 组合键刚用的修饰键，本帧跳过
                    continue
                if _act == mm.ACT_LEFT:
                    want_left = True
                elif _act == mm.ACT_RIGHT:
                    want_right = True

            if _mode == mm.MODE_GYRO:
                # 陀螺仪模式：光标持续微动，press-hold 会被系统判成拖拽 →
                # 改用按下沿 click() 瞬时点击，彻底避免误拖拽
                _edge_lr = ss.setdefault('lrEdge', {})
                for _act, _btn, _was_key in ((mm.ACT_LEFT, Button.left, 'l'),
                                             (mm.ACT_RIGHT, Button.right, 'r')):
                    want = want_left if _act == mm.ACT_LEFT else want_right
                    if want and not _edge_lr.get(_was_key, False):
                        try:
                            mouse.click(_btn)
                        except Exception:
                            pass
                    _edge_lr[_was_key] = want
                ss['leftPressed'] = False
                ss['rightPressed'] = False
            else:
                # 光学鼠标模式：保留真实 press-hold 语义
                if want_left and not ss['leftPressed']:
                    mouse.press(Button.left)
                elif not want_left and ss['leftPressed']:
                    mouse.release(Button.left)
                ss['leftPressed'] = want_left
                if want_right and not ss['rightPressed']:
                    mouse.press(Button.right)
                elif not want_right and ss['rightPressed']:
                    mouse.release(Button.right)
                ss['rightPressed'] = want_right

            # 点按型：按下沿触发（中键/侧键/挡位/滚动）
            _click_map = {mm.ACT_MIDDLE: Button.middle, mm.ACT_FWD: Button.x2,
                          mm.ACT_BACK: Button.x1}
            _edge_prev = ss.setdefault('actPrev', {})
            for _bname, _act in keymap.items():
                now = bool(btn.get(_bname))
                was = bool(_edge_prev.get(_bname, False))
                _edge_prev[_bname] = now
                if mm.is_consumed(pair_id, _bname):   # 组合键修饰键本帧跳过
                    continue
                if not (now and not was):
                    continue
                if _act in _click_map:
                    try:
                        mouse.click(_click_map[_act])
                    except Exception:
                        pass
                elif _act in (mm.ACT_DPI_UP, mm.ACT_DPI_DOWN):
                    pass   # 加减键固定调 DPI，由上方 feed_dpi_keys 统一处理
                elif _act == mm.ACT_SCROLL_UP:
                    try:
                        mouse.scroll(0, 1)
                    except Exception:
                        pass
                elif _act == mm.ACT_SCROLL_DOWN:
                    try:
                        mouse.scroll(0, -1)
                    except Exception:
                        pass
                elif _act == mm.ACT_CENTER:
                    _center_cursor()

            # 滚轮：两种指针模式都用摇杆力度连续滚动（陀螺仪模式拇指仍在摇杆上）
            if cfg["mouse_scroll"]:
                raw = getattr(_joycon, "stick_raw", (2048, 2048))
                delta = mm.wheel_delta(_side, raw[0], raw[1],
                                       reverse=cfg["mouse_scroll_rev"])
                steps, ss['wheelAcc'] = mm.accumulate_wheel(ss['wheelAcc'], delta)
                if steps:
                    try:
                        mouse.scroll(0, steps)
                    except Exception:
                        pass


async def notify_duo_joycons(client, side, data, pair_id: int = 0):
    global _event_loop
    if _event_loop is None:
        _event_loop = asyncio.get_running_loop()

    # Sensor notifications arrive many times per second. Only touch vibration
    # registration when the BLE client object actually changes.
    if vibration_clients.get(pair_id, {}).get(side) is not client:
        register_vibration(client, side, pair_id)
        # HD 震动通道绑定：GATT 0x0012 需要 client 和它的事件循环
        try:
            from virtual.rumble_hd import attach_client
            attach_client("left" if side == "Left" else "right",
                          client, _event_loop)
        except Exception:       # noqa: BLE001
            pass

    # Get per-pair Joy-Con instances
    pair_joycons = _get_pair_joycons(pair_id)

    if side == "Left":
        await pair_joycons["Left"].update(data)
        await update(pair_id)
    elif side == "Right":
        await pair_joycons["Right"].update(data)
        await update(pair_id)
    else:
        warning("Unknown controller side.")

    return client
