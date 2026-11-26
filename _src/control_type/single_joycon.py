from controllers.JoyconL import JoyConLeft
from controllers.JoyconR import JoyConRight

from controller_command import ControllerCommand, UUID_CMD
from controller_manager import get_controller_manager

from config import Config
from pynput.mouse import Controller, Button
import control_type.mouse_mode as mm

import threading
import time
import asyncio
import copy
from app_paths import app_path, config_path  # noqa: E402
from virtual.reports import Ns2Bit  # noqa: E402

# Xbox button name to vgamepad mapping
# 已改用 Joy-Con 原生语义位，此表仅保留兼容；充电握把背键别名走这里。
XBOX_BUTTON_MAP = {
    "gll": Ns2Bit.GL_L,
    "grl": Ns2Bit.GR_L,
    "glr": Ns2Bit.GL_R,
    "grr": Ns2Bit.GR_R,
}


def get_default_controls():
    """Get default control mapping for single Joy-Con"""
    return {
        "Left": {
            "0": {  # Vertical
                "ZL": "LEFT_TRIGGER",
                "L": None,  # Add L button mapping
                "LS": None,
                "Up": None,
                "Down": None,
                "Left": None,
                "Right": None,
                "Minus": None,
                "SLL": None,
                "SRL": None,
                "GLL": None,
                "GRL": None,
                "Capture": None,
            },
        },
        "Right": {
            "0": {  # Vertical
                "ZR": "RIGHT_TRIGGER",
                "R": None,  # Add R button mapping
                "RS": None,
                "A": None,
                "B": None,
                "X": None,
                "Y": None,
                "Plus": None,
                "SRR": None,
                "SLR": None,
                "GLR": None,
                "GRR": None,
                "Home": None,
            },
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
                    gll = parser[section].get('gll_mapping', '')
                    grl = parser[section].get('grl_mapping', '')
                    glr = parser[section].get('glr_mapping', '')
                    grr = parser[section].get('grr_mapping', '')
                    
                    # Update SL/SR mappings
                    controls["Left"]["0"]["SLL"] = XBOX_BUTTON_MAP.get(sll, None)
                    controls["Left"]["0"]["SRL"] = XBOX_BUTTON_MAP.get(srl, None)
                    controls["Right"]["0"]["SLR"] = XBOX_BUTTON_MAP.get(slr, None)
                    controls["Right"]["0"]["SRR"] = XBOX_BUTTON_MAP.get(srr, None)
                    # 充电握把 GL/GR mappings（空串 = 未映射）
                    controls["Left"]["0"]["GLL"] = XBOX_BUTTON_MAP.get(gll, None)
                    controls["Left"]["0"]["GRL"] = XBOX_BUTTON_MAP.get(grl, None)
                    controls["Right"]["0"]["GLR"] = XBOX_BUTTON_MAP.get(glr, None)
                    controls["Right"]["0"]["GRR"] = XBOX_BUTTON_MAP.get(grr, None)
                            
        except Exception as e:
            pass
                
        pair_controls[pair_id] = controls
    
    return pair_controls[pair_id]


def update_sl_sr_mappings_for_pair(pair_id: int, sll: str, srl: str, slr: str, srr: str):
    """Update SL/SR button mappings for a specific pair"""
    try:
        controls = get_pair_controls(pair_id)
        controls["Left"]["0"]["SLL"] = XBOX_BUTTON_MAP.get(sll, None)
        controls["Left"]["0"]["SRL"] = XBOX_BUTTON_MAP.get(srl, None)
        controls["Right"]["0"]["SLR"] = XBOX_BUTTON_MAP.get(slr, None)
        controls["Right"]["0"]["SRR"] = XBOX_BUTTON_MAP.get(srr, None)
    except Exception as e:
        pass


def update_gl_gr_mappings_for_pair(pair_id: int, gll: str, grl: str, glr: str, grr: str):
    """Update 充电握把 GL/GR button mappings for a specific pair"""
    try:
        controls = get_pair_controls(pair_id)
        controls["Left"]["0"]["GLL"] = XBOX_BUTTON_MAP.get(gll, None)
        controls["Left"]["0"]["GRL"] = XBOX_BUTTON_MAP.get(grl, None)
        controls["Right"]["0"]["GLR"] = XBOX_BUTTON_MAP.get(glr, None)
        controls["Right"]["0"]["GRR"] = XBOX_BUTTON_MAP.get(grr, None)
    except Exception as e:
        pass


# Per-pair state
pair_state = {}
_pair_state_lock = threading.RLock()
_mouse_threads = {}
_mouse_events = {}

# Per-pair mouse enabled state (set from GUI)
pair_mouse_enabled = {}


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


def get_pair_state(pair_id: int):
    """Get or create state for a pair"""
    with _pair_state_lock:
        if pair_id not in pair_state:
            pair_state[pair_id] = _new_pair_state()
        return pair_state[pair_id]


def _new_pair_state():
    return {
        'joycon': None,
        'side': None,
        'mouse': Controller(),
        'targetX': 0,
        'targetY': 0,
        'previousMouseX': 0,
        'previousMouseY': 0,
        'leftPressed': False,
        'rightPressed': False,
        'middlePressed': False,
        'forwardPressed': False,
        'backPressed': False,
        'wheelAcc': 0.0,
        'mouse_mode_active': False,
        'lastTime': time.time(),
    }


def reset_pair_state(pair_id: int):
    """Reset state for a pair (called when reconnecting)"""
    with _pair_state_lock:
        if pair_id in pair_state:
            old_state = pair_state[pair_id]
            for _btn, _attr in ((Button.left, 'leftPressed'),
                                (Button.right, 'rightPressed'),
                                (Button.middle, 'middlePressed'),
                                (Button.x2, 'forwardPressed'),
                                (Button.x1, 'backPressed')):
                if old_state.get(_attr):
                    try:
                        old_state['mouse'].release(_btn)
                    except Exception:
                        pass
            pair_state[pair_id] = _new_pair_state()
            _mouse_events.setdefault(pair_id, threading.Event()).set()
            mm.reset_pair(pair_id)


# Per-pair vibration setting
_pair_vibration_enabled = {}


def set_vibration_enabled(enabled, pair_id: int = 0):
    """Set whether vibration feedback is enabled for one pair."""
    _pair_vibration_enabled[pair_id] = enabled


async def send_vibration_to_client(client, large_motor, small_motor):
    """已停用：震动由 HD 通道（GATT 0x0012）负责，见 rumble_hd.py。

    旧实现发 command 0x0A subcmd 0x02「播放预置样本 #1」，
    官方描述为 `Low frequency buzz, ~1s`。回调每秒 200+ 次 →
    每秒重放 200 次 1 秒嗡鸣 → LRA 过驱 → 摇杆 ADC 被物理带偏。
    这是「震动导致摇杆偏移」的物理根因，已彻底移除。
    """
    return

# Reuse the BLE notification loop instead of maintaining another permanent
# event-loop thread solely for vibration writes.
_event_loop = None
_vibration_registered_gamepads = {}

def vibration_callback(client, target, large_motor, small_motor, led_number, user_data):
    """Callback for gamepad vibration feedback from vgamepad"""
    pair_id = user_data if user_data is not None else 0
    if not _pair_vibration_enabled.get(pair_id, True):
        return
    
    manager = get_controller_manager()
    pair = manager.get_pair(pair_id)
    if not pair:
        return
    
    # In single Joy-Con mode, check which Joy-Con is connected
    target_client = None
    if pair.left.is_connected and pair.left.client:
        target_client = pair.left.client
    elif pair.right.is_connected and pair.right.client:
        target_client = pair.right.client
    
    if target_client and _event_loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(
                send_vibration_to_client(target_client, large_motor, small_motor),
                _event_loop
            )
        except Exception as e:
            pass  # Silent fail


def register_vibration(pair_id: int):
    """Register vibration callback for a pair"""
    manager = get_controller_manager()
    pair = manager.get_pair(pair_id)
    if (pair and pair.gamepad
            and _vibration_registered_gamepads.get(pair_id) is not pair.gamepad):
        pair.gamepad.register_notification(lambda client, target, large_motor, small_motor, led_number, user_data: vibration_callback(client, target, large_motor, small_motor, led_number, pair_id))
        _vibration_registered_gamepads[pair_id] = pair.gamepad


def mouse_loop(pair_id: int):
    """Mouse movement loop for a pair"""
    with _pair_state_lock:
        wakeup = _mouse_events.setdefault(pair_id, threading.Event())
    while True:
        # Re-fetch state every iteration so reconnect/reset does not leave this
        # thread operating on an orphaned dictionary.
        with _pair_state_lock:
            state = get_pair_state(pair_id)
            stepX = int(state['targetX'] / 6)
            stepY = int(state['targetY'] / 6)
            if stepX == 0 and state['targetX']:
                stepX = 1 if state['targetX'] > 0 else -1
            if stepY == 0 and state['targetY']:
                stepY = 1 if state['targetY'] > 0 else -1
            if stepX != 0 or stepY != 0:
                state['targetX'] -= stepX
                state['targetY'] -= stepY
                mouse_controller = state['mouse']
            else:
                mouse_controller = None
        if mouse_controller is not None:
            mouse_controller.move(stepX, stepY)
            time.sleep(0.006)
        else:
            wakeup.wait()
            wakeup.clear()


async def update(joycon, side, isInMouse, pair_id: int):
    """Update gamepad state for a specific pair"""
    state = get_pair_state(pair_id)
    controls = get_pair_controls(pair_id)
    manager = get_controller_manager()
    pair = manager.get_pair(pair_id)

    if not pair:
        return

    gamepad = pair.gamepad
    
    # ================= Joy-Con 原生直投（不走 XInput）=================
    # 单手柄模式下同样用语义位 + 原始摇杆值，与 duo_joycon 一致。
    from virtual.reports import Ns2Bit as n

    bits = n(0)
    b = joycon.buttons
    if not isInMouse:
        if b.get("Up"):       bits |= n.UP
        if b.get("Down"):     bits |= n.DOWN
        if b.get("Left"):     bits |= n.LEFT
        if b.get("Right"):    bits |= n.RIGHT
        if b.get("L"):        bits |= n.L
        if b.get("ZL"):       bits |= n.ZL
        if b.get("Minus"):    bits |= n.MINUS
        if b.get("LS"):       bits |= n.LS
        if b.get("Capture"):  bits |= n.CAPTURE
        if b.get("SLL"):      bits |= n.SL_L
        if b.get("SRL"):      bits |= n.SR_L
        if b.get("GLL"):      bits |= n.GL_L
        if b.get("GRL"):      bits |= n.GR_L
        if b.get("A"):        bits |= n.A
        if b.get("B"):        bits |= n.B
        if b.get("X"):        bits |= n.X
        if b.get("Y"):        bits |= n.Y
        if b.get("R"):        bits |= n.R
        if b.get("ZR"):       bits |= n.ZR
        if b.get("Plus"):     bits |= n.PLUS
        if b.get("RS"):       bits |= n.RS
        if b.get("Home"):     bits |= n.HOME
        if b.get("SLR"):      bits |= n.SL_R
        if b.get("SRR"):      bits |= n.SR_R
        if b.get("GLR"):      bits |= n.GL_R
        if b.get("GRR"):      bits |= n.GR_R

    if hasattr(gamepad, "set_buttons"):
        if side == "Left":
            gamepad.set_buttons(bits, None)
        else:
            gamepad.set_buttons(None, bits)

    # ---- 摇杆：原始 12 位直接透传（不做映射，由主机按 SPI 校准处理）----
    # 2026-11-18：与 duo_joycon 同样修掉双重校准（自标定 + 主机 SPI 校准叠加 → 漂移）
    if not isInMouse and hasattr(gamepad, "set_stick"):
        side_key = "left" if side == "Left" else "right"
        gamepad.set_stick(side_key,
                          joycon.analog_stick["X"],
                          joycon.analog_stick["Y"])

    # ---- 体感 ----
    if hasattr(gamepad, "set_imu_raw"):
        raw = getattr(joycon, "imu_raw", None)
        if raw is not None:
            gamepad.set_imu_raw("left" if side == "Left" else "right", raw)

    if hasattr(gamepad, "update"):
        gamepad.update()


async def controller_traitement(joycon, side, data, pair_id: int):
    """Process controller data for single Joy-Con mode"""
    state = get_pair_state(pair_id)


    await joycon.update(data)

    # ── 单手柄模式：三态（手柄/鼠标/陀螺仪鼠标），C 组合键仅右手柄可触发 ──
    if side == "Right":
        b = joycon.buttons
        action = mm.feed_combo(
            pair_id, c=bool(b.get("GameChat")),
            l=bool(b.get("L")), zl=bool(b.get("ZL")),
            r=bool(b.get("R")), zr=bool(b.get("ZR")),
            sll=bool(b.get("SLL")), srl=bool(b.get("SRL")),
            slr=bool(b.get("SLR")), srr=bool(b.get("SRR")),
            gll=bool(b.get("GLL")), grl=bool(b.get("GRL")),
            glr=bool(b.get("GLR")), grr=bool(b.get("GRR")))
        if action:
            mm.mark_consumed(pair_id, action)
        if action.startswith("macro_") and mm.is_macro_enabled(pair_id):
            try:
                from control_type.duo_joycon import _trigger_macro
                _trigger_macro(pair_id, action[6:])
            except Exception:
                pass
        _ck = mm._consumed.get(pair_id)
        if _ck and not b.get(_ck, False):
            mm.clear_consumed(pair_id)
    pointer_mode = mm.get_mode(pair_id, side)
    mouse_active = mm.is_in_pointer_mode(pair_id, side)

    if mouse_active:
        with _pair_state_lock:
            mouse_thread = _mouse_threads.get(pair_id)
            if mouse_thread is None or not mouse_thread.is_alive():
                mouse_thread = threading.Thread(target=mouse_loop, args=(pair_id,), daemon=True)
                _mouse_threads[pair_id] = mouse_thread
                mouse_thread.start()

    await update(joycon, side, mouse_active, pair_id)

    if mouse_active:
        cfg = mm.get_config(pair_id)
        keymap = mm.get_keymap(pair_id, pointer_mode)
        btn = joycon.buttons
        # 加减键固定调 DPI，不可自定义/不可录宏
        mm.feed_dpi_keys(pair_id, bool(btn.get("Plus")), bool(btn.get("Minus")),
                         both_in_pointer=False)
        scale = mm.get_dpi_scale(pair_id)
        with _pair_state_lock:
            if not state['mouse_mode_active']:
                state['previousMouseX'] = joycon.mouse['X']
                state['previousMouseY'] = joycon.mouse['Y']
                state['targetX'] = 0
                state['targetY'] = 0
                state['mouse_mode_active'] = True
                deltaX = deltaY = 0
            else:
                deltaX = (joycon.mouse["X"] - state['previousMouseX'] + 32768) % 65536 - 32768
                deltaY = (joycon.mouse["Y"] - state['previousMouseY'] + 32768) % 65536 - 32768
                state['previousMouseX'] = joycon.mouse["X"]
                state['previousMouseY'] = joycon.mouse["Y"]
            if pointer_mode == mm.MODE_GYRO:
                gdx, gdy = mm.gyro_cursor_delta(side, getattr(joycon, "imu_raw", None), pair_id)
                state['targetX'] += gdx
                state['targetY'] += gdy
                if gdx or gdy:
                    _mouse_events.setdefault(pair_id, threading.Event()).set()
            else:
                state['targetX'] += deltaX * scale
                state['targetY'] += deltaY * scale
                if deltaX or deltaY:
                    _mouse_events.setdefault(pair_id, threading.Event()).set()

        # keymap 驱动左右键（跳过组合键刚用的修饰键）
        want_left = any(btn.get(b) and a == mm.ACT_LEFT and not mm.is_consumed(pair_id, b)
                        for b, a in keymap.items())
        want_right = any(btn.get(b) and a == mm.ACT_RIGHT and not mm.is_consumed(pair_id, b)
                         for b, a in keymap.items())
        if pointer_mode == mm.MODE_GYRO:
            # 陀螺仪模式：光标持续微动，press-hold 易被判成拖拽 → 按下沿瞬时 click
            _edge_lr = state.setdefault('lrEdge', {})
            for _act, _btn, _k in ((mm.ACT_LEFT, Button.left, 'l'),
                                   (mm.ACT_RIGHT, Button.right, 'r')):
                want = want_left if _act == mm.ACT_LEFT else want_right
                if want and not _edge_lr.get(_k, False):
                    try:
                        state['mouse'].click(_btn)
                    except Exception:
                        pass
                _edge_lr[_k] = want
            state['leftPressed'] = False
            state['rightPressed'] = False
        else:
            if want_left and not state['leftPressed']:
                state['mouse'].press(Button.left)
            elif not want_left and state['leftPressed']:
                state['mouse'].release(Button.left)
            state['leftPressed'] = want_left
            if want_right and not state['rightPressed']:
                state['mouse'].press(Button.right)
            elif not want_right and state['rightPressed']:
                state['mouse'].release(Button.right)
            state['rightPressed'] = want_right

        # 点按型：按下沿
        _click_map = {mm.ACT_MIDDLE: Button.middle, mm.ACT_FWD: Button.x2,
                      mm.ACT_BACK: Button.x1}
        _edge = state.setdefault('actPrev', {})
        for _b, _a in keymap.items():
            now, was = bool(btn.get(_b)), bool(_edge.get(_b, False))
            _edge[_b] = now
            if mm.is_consumed(pair_id, _b):
                continue
            if not (now and not was):
                continue
            if _a in _click_map:
                try:
                    state['mouse'].click(_click_map[_a])
                except Exception:
                    pass
            elif _a in (mm.ACT_DPI_UP, mm.ACT_DPI_DOWN):
                pass   # 加减键固定调 DPI
            elif _a == mm.ACT_SCROLL_UP:
                state['mouse'].scroll(0, 1)
            elif _a == mm.ACT_SCROLL_DOWN:
                state['mouse'].scroll(0, -1)
            elif _a == mm.ACT_CENTER:
                # 回屏幕中心。尺寸必须动态取（自适应任意分辨率/缩放）：
                #   ① Qt primaryScreen（GUI 应用最准，与 pynput 坐标系一致）
                #   ② Win32 GetSystemMetrics + DPI 感知
                #   ③ 1920x1080 兜底
                # 不能用 pynput Controller.size —— 该对象没有该属性。
                try:
                    w = h = 0
                    try:
                        from PyQt5.QtWidgets import QApplication
                        _app = QApplication.instance()
                        if _app is not None and _app.primaryScreen() is not None:
                            _g = _app.primaryScreen().geometry()
                            w, h = int(_g.width()), int(_g.height())
                    except Exception:
                        w = h = 0
                    if w <= 0 or h <= 0:
                        import ctypes
                        _u = ctypes.windll.user32
                        try:
                            _u.SetProcessDPIAware()
                        except Exception:
                            pass
                        w = int(_u.GetSystemMetrics(0))
                        h = int(_u.GetSystemMetrics(1))
                    if w > 0 and h > 0:
                        state['mouse'].position = (w // 2, h // 2)
                except Exception:
                    pass

        # 滚轮：两种指针模式都用摇杆力度连续滚动
        if cfg["mouse_scroll"]:
            raw = getattr(joycon, "stick_raw", (2048, 2048))
            delta = mm.wheel_delta(side, raw[0], raw[1],
                                   reverse=cfg["mouse_scroll_rev"])
            steps, state['wheelAcc'] = mm.accumulate_wheel(state['wheelAcc'], delta)
            if steps:
                try:
                    state['mouse'].scroll(0, steps)
                except Exception:
                    pass
    else:
        with _pair_state_lock:
            for _btn, _attr in ((Button.left, 'leftPressed'),
                                (Button.right, 'rightPressed'),
                                (Button.middle, 'middlePressed'),
                                (Button.x2, 'forwardPressed'),
                                (Button.x1, 'backPressed')):
                if state.get(_attr):
                    try:
                        state['mouse'].release(_btn)
                    except Exception:
                        pass
                state[_attr] = False
            state['wheelAcc'] = 0.0
            state['targetX'] = 0
            state['targetY'] = 0
            state['mouse_mode_active'] = False

    # Latency calculation
    currentTime = time.time()
    elapsedTime = (currentTime - state['lastTime']) * 1000
    state['lastTime'] = currentTime


async def notify_single_joycons(client, side, data, pair_id: int):
    """Handle notifications for single Joy-Con mode"""
    global _event_loop
    if _event_loop is None or _event_loop.is_closed():
        _event_loop = asyncio.get_running_loop()
    state = get_pair_state(pair_id)
    manager = get_controller_manager()
    pair = manager.get_pair(pair_id)
    if pair:
        pass  # 保留后续 joycon 初始化前的判空语义

    # Initialize joycon object if needed
    if state['joycon'] is None:
        if side == "Left":
            state['joycon'] = JoyConLeft()
        else:
            state['joycon'] = JoyConRight()
        state['side'] = side
        register_vibration(pair_id)
        # HD 震动通道绑定（单手柄模式同样需要）
        try:
            from virtual.rumble_hd import attach_client
            attach_client("left" if side == "Left" else "right",
                          client, _event_loop)
        except Exception:       # noqa: BLE001
            pass

    mac = client.address.replace(":", "").replace("-", "").upper()

    # 重连会换 client 对象，HD 通道必须跟着换绑（attach 内部去重，开销可忽略）
    try:
        from virtual.rumble_hd import attach_client
        attach_client("left" if side == "Left" else "right", client, _event_loop)
    except Exception:       # noqa: BLE001
        pass

    await controller_traitement(state['joycon'], side, data, pair_id)

    # Only publish a verified battery value. Unknown must not become 0%.
    if state['joycon'].battery_level is not None:
        manager.update_battery(mac, int(state['joycon'].battery_level))

    return client
