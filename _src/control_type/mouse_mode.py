# -*- coding: utf-8 -*-
"""输入模式核心引擎 —— WinJoyCon2-Plus 鼠标/陀螺仪鼠标/宏系统。

设计模式（每侧独立）：
  * gamepad       : 普通手柄（默认）
  * mouse         : 光学鼠标模式（手柄上报 mouse X/Y 控制光标）
  * gyro_mouse    : 陀螺仪鼠标模式（IMU 角速度积分控制光标，马力欧银河式）

组合键（右手柄 C 键 = GameChat 为前缀）：
  * C            : 所有侧回到 gamepad
  * C + L        : 左手柄 → mouse
  * C + ZL       : 左手柄 → gyro_mouse
  * C + R        : 右手柄 → mouse
  * C + ZR       : 右手柄 → gyro_mouse
  * C + SL/SR    : 触发宏系统（宏录制/开关在 GUI 完成）

自定义按键映射：每种模式一套 keymap（按钮语义 → 鼠标动作），
默认按既有行为，GUI 可改，带"还原默认"按钮。
宏：ZL/ZR 四个肩键可绑「任意单键」或「录制宏」，默认关闭。
"""
from __future__ import annotations

import configparser
import os

from app_paths import config_path  # noqa: E402

# ── 模式常量 ─────────────────────────────────────────────────────────────────
MODE_GAMEPAD = "gamepad"
MODE_MOUSE = "mouse"
MODE_GYRO = "gyro"
MODES = (MODE_GAMEPAD, MODE_MOUSE, MODE_GYRO)

# ── 鼠标动作枚举（keymap 的值）───────────────────────────────────────────────
ACT_NONE = ""
ACT_LEFT = "left"          # 鼠标左键
ACT_RIGHT = "right"        # 鼠标右键
ACT_MIDDLE = "middle"      # 鼠标中键
ACT_FWD = "forward"        # 侧键2 前进 (x2)
ACT_BACK = "back"          # 侧键1 后退 (x1)
ACT_SCROLL_UP = "scroll_up"
ACT_SCROLL_DOWN = "scroll_down"
ACT_DPI_UP = "dpi_up"      # 灵敏度升挡
ACT_DPI_DOWN = "dpi_down"  # 灵敏度降挡
ACT_CENTER = "center"      # 光标回屏幕中心（陀螺仪模式 LS/RS 摇杆按下）
ACTIONS = (ACT_NONE, ACT_LEFT, ACT_RIGHT, ACT_MIDDLE, ACT_FWD, ACT_BACK,
           ACT_SCROLL_UP, ACT_SCROLL_DOWN, ACT_DPI_UP, ACT_DPI_DOWN, ACT_CENTER)

# 可映射的按钮语义（左右手柄通用名，实际取各自 buttons 字典）
LEFT_BUTTONS = ("Up", "Down", "Left", "Right", "L", "ZL", "Minus", "LS",
                "Capture", "SLL", "SRL")
RIGHT_BUTTONS = ("Up", "Down", "Left", "Right", "R", "ZR", "Plus", "RS",
                 "Home", "GameChat", "SLR", "SRR")

# ── 默认 keymap（沿用既有行为）───────────────────────────────────────────────
# 每套 keymap: {按钮语义: 动作}。鼠标与陀螺仪鼠标共用同一套默认。
def default_keymap() -> dict:
    return {
        # 左右键
        "L": ACT_LEFT, "R": ACT_LEFT,
        "ZL": ACT_RIGHT, "ZR": ACT_RIGHT,
        # 中键
        "Capture": ACT_MIDDLE, "Home": ACT_MIDDLE,
        # 侧键前进/后退
        "Up": ACT_FWD, "Left": ACT_FWD,        # 左手柄十字上/左
        "Down": ACT_BACK, "Right": ACT_BACK,   # 左手柄十字下/右
        "X": ACT_FWD, "A": ACT_FWD,            # 右手柄 X/A
        "Y": ACT_BACK, "B": ACT_BACK,          # 右手柄 Y/B
        # 灵敏度挡位
        "Plus": ACT_DPI_UP, "Minus": ACT_DPI_DOWN,
        # 摇杆按下 = 光标回屏幕中心（陀螺仪模式尤其有用）
        "LS": ACT_CENTER, "RS": ACT_CENTER,
    }


# ── 灵敏度挡位 ───────────────────────────────────────────────────────────────
# 历史：原 1 挡(400/0.5x) → 2026-11-20 嫌低整体前移 → 2026-11-26 用户反馈
# 「每个挡位都太高」，故整体降一档回到 400 起，默认仍是第 2 挡（索引1）。
# 现在：1挡 400/0.5x、2挡 800/1.0x、3挡 1600/2.0x、4挡 3200/4.0x。
DPI_LEVELS = ((400, 0.5), (800, 1.0), (1600, 2.0), (3200, 4.0))
DPI_DEFAULT_INDEX = 1

# ── 每组 pair 默认配置 ───────────────────────────────────────────────────────
_DEFAULTS = {
    "mode_left": MODE_GAMEPAD,
    "mode_right": MODE_GAMEPAD,
    "mouse_dpi_index": DPI_DEFAULT_INDEX,
    "mouse_scroll": True,
    "mouse_scroll_rev": False,
    # 陀螺仪灵敏度倍率（相对鼠标的 scale）
    "gyro_scale": 1.0,
    "gyro_invert_x": False,
    "gyro_invert_y": False,
    # 宏系统默认关闭
    "macro_enabled": False,
}

_BOOL_KEYS = ("mouse_scroll", "mouse_scroll_rev",
              "gyro_invert_x", "gyro_invert_y", "macro_enabled")
_INT_KEYS = ("mouse_dpi_index",)
_FLOAT_KEYS = ("gyro_scale",)
_STR_KEYS = ("mode_left", "mode_right")

# 内存状态
_cfg = {}          # pair_id -> 配置 dict（含 keymap_* / macro_* 字符串）
_c_prev = {}       # C 键边沿
_combo_prev = {}   # 组合键边沿：pair -> 各修饰键上次状态
_dpi_prev = {}     # 加减键边沿
_active = {}       # 兼容用
_macro_rec = {}    # 宏录制运行时：pair -> {"recording", "current": [], "trigger"}


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _keyspec_str(d: dict) -> str:
    """把 keymap 编码成 'Btn:act,Btn:act' 字符串存 ini。"""
    return ",".join(f"{k}:{v}" for k, v in d.items() if v)


def _parse_keyspec(s: str) -> dict:
    out = {}
    if not s:
        return out
    for part in s.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            if v in ACTIONS:
                out[k] = v
    return out


def get_config(pair_id: int) -> dict:
    if pair_id not in _cfg:
        cfg = dict(_DEFAULTS)
        # keymap 两套 + 4 个肩键绑定
        cfg["keymap_mouse"] = default_keymap()
        cfg["keymap_gyro"] = default_keymap()
        cfg["macro_bindings"] = {}     # 按钮语义 -> 宏名/单键描述
        cfg["macros"] = {}             # 宏名 -> 动作串（简单按键序列）
        try:
            parser = configparser.ConfigParser()
            path = config_path()
            if os.path.exists(path):
                parser.read(path, encoding="utf-8")
                sec_name = f"Pair_{pair_id}"
                if sec_name in parser:
                    sec = parser[sec_name]
                    for k in _BOOL_KEYS:
                        if k in sec:
                            cfg[k] = _truthy(sec.get(k))
                    for k in _INT_KEYS:
                        if k in sec:
                            try:
                                v = int(sec.get(k))
                                cfg[k] = min(len(DPI_LEVELS) - 1, max(0, v))
                            except (ValueError, TypeError):
                                pass
                    for k in _FLOAT_KEYS:
                        if k in sec:
                            try:
                                cfg[k] = float(sec.get(k))
                            except (ValueError, TypeError):
                                pass
                    for k in _STR_KEYS:
                        v = sec.get(k, "").strip().lower()
                        if v in MODES:
                            cfg[k] = v
                    km = sec.get("keymap_mouse", "").strip()
                    if km:
                        cfg["keymap_mouse"] = _parse_keyspec(km)
                    kg = sec.get("keymap_gyro", "").strip()
                    if kg:
                        cfg["keymap_gyro"] = _parse_keyspec(kg)
                    # 宏定义: name=act1|act2;name2=...
                    md = sec.get("macro_defs", "").strip()
                    if md:
                        for item in md.split(";"):
                            if "=" in item:
                                nm, acts = item.split("=", 1)
                                cfg["macros"][nm] = [a for a in acts.split("|") if a in ACTIONS]
                    # 宏绑定: key:name,key:name
                    mb = sec.get("macro_bindings", "").strip()
                    if mb:
                        for item in mb.split(","):
                            if ":" in item:
                                key, nm = item.split(":", 1)
                                cfg["macro_bindings"][key] = nm
        except Exception:                # noqa: BLE001
            pass
        _cfg[pair_id] = cfg
        _active[pair_id] = ("Right" if cfg["mode_right"] != MODE_GAMEPAD else
                            ("Left" if cfg["mode_left"] != MODE_GAMEPAD else None))
    return _cfg[pair_id]


def save_config(pair_id: int):
    cfg = get_config(pair_id)
    try:
        parser = configparser.ConfigParser()
        path = config_path()
        if os.path.exists(path):
            parser.read(path, encoding="utf-8")
        sec = f"Pair_{pair_id}"
        if sec not in parser:
            parser[sec] = {}
        for k in _BOOL_KEYS:
            parser[sec][k] = "1" if cfg[k] else "0"
        for k in _INT_KEYS:
            parser[sec][k] = str(cfg[k])
        for k in _FLOAT_KEYS:
            parser[sec][k] = str(cfg[k])
        for k in _STR_KEYS:
            parser[sec][k] = cfg[k]
        parser[sec]["keymap_mouse"] = _keyspec_str(cfg["keymap_mouse"])
        parser[sec]["keymap_gyro"] = _keyspec_str(cfg["keymap_gyro"])
        parser[sec]["macro_defs"] = ";".join(
            f"{nm}={'|'.join(acts)}" for nm, acts in cfg["macros"].items())
        parser[sec]["macro_bindings"] = ",".join(
            f"{k}:{v}" for k, v in cfg["macro_bindings"].items())
        with open(path, "w", encoding="utf-8") as fh:
            parser.write(fh)
    except Exception:                    # noqa: BLE001
        pass


# ── 模式查询/设置 ────────────────────────────────────────────────────────────
def get_mode(pair_id: int, side: str) -> str:
    cfg = get_config(pair_id)
    return cfg["mode_left" if side == "Left" else "mode_right"]


def set_mode(pair_id: int, side: str, mode: str, persist: bool = True):
    if mode not in MODES:
        return
    cfg = get_config(pair_id)
    cfg["mode_left" if side == "Left" else "mode_right"] = mode
    if mode != MODE_GAMEPAD:
        _active[pair_id] = side
    if persist:
        save_config(pair_id)


def is_in_pointer_mode(pair_id: int, side: str) -> bool:
    return get_mode(pair_id, side) in (MODE_MOUSE, MODE_GYRO)


def set_all_mode(mode: str, pair_count: int = 4, persist: bool = True):
    """托盘菜单用：把所有 pair 的左右手柄统一切到某模式。"""
    if mode not in MODES:
        return
    for pair_id in range(pair_count):
        cfg = get_config(pair_id)
        cfg["mode_left"] = mode
        cfg["mode_right"] = mode
        if persist:
            save_config(pair_id)


# 旧版键名 → 新版键名。JoyCon 上本来就叫 LS/RS，旧配置里存的 L3/R3 要迁移。
_RENAMED_KEYS = {"L3": "LS", "R3": "RS"}


def get_keymap(pair_id: int, mode: str) -> dict:
    """取该模式的按键映射。

    ★ 用默认 keymap 做**增量补全**：老版本保存的配置里没有后来新增的
      键（如 LS/RS 回中心），若不补全，这些功能对老配置永久失效。
      用户显式设过 ""（不映射）的键保留原值，不被默认覆盖。
    ★ 同时把旧键名 L3/R3 迁移成 LS/RS（JoyCon 的实际叫法）。
    """
    cfg = get_config(pair_id)
    key = "keymap_gyro" if mode == MODE_GYRO else "keymap_mouse"
    saved = cfg.get(key) or {}
    merged = default_keymap()
    for k, v in saved.items():
        k = _RENAMED_KEYS.get(k, k)      # 旧配置里的 L3/R3 → LS/RS
        merged[k] = v                    # 用户自定义优先（含显式 "" 表示不映射）
    return merged


def set_keymap(pair_id: int, mode: str, keymap: dict, persist: bool = True):
    cfg = get_config(pair_id)
    cfg["keymap_gyro" if mode == MODE_GYRO else "keymap_mouse"] = dict(keymap)
    if persist:
        save_config(pair_id)


def reset_keymap(pair_id: int, mode: str = None, persist: bool = True):
    """还原默认按键映射。mode=None 还原两套。"""
    cfg = get_config(pair_id)
    if mode in (None, MODE_MOUSE):
        cfg["keymap_mouse"] = default_keymap()
    if mode in (None, MODE_GYRO):
        cfg["keymap_gyro"] = default_keymap()
    if persist:
        save_config(pair_id)


def set_option(pair_id: int, key: str, value, persist: bool = True):
    cfg = get_config(pair_id)
    if key in ("mode_left", "mode_right"):
        set_mode(pair_id, "Left" if key == "mode_left" else "Right",
                 value if value in MODES else MODE_GAMEPAD, persist=persist)
        return
    if key not in cfg:
        return
    if key in _BOOL_KEYS:
        cfg[key] = bool(value)
    elif key in _INT_KEYS:
        cfg[key] = int(value)
    elif key in _FLOAT_KEYS:
        cfg[key] = float(value)
    if persist:
        save_config(pair_id)


def get_option(pair_id: int, key: str):
    return get_config(pair_id).get(key)


# ── C 键组合键状态机 ─────────────────────────────────────────────────────────
# 用户实测：自然操作是「先按住 C，再按修饰键」，所以组合键必须在
# **修饰键按下沿** 判定（此刻 C 已按住），而不是 C 按下沿。
# 单独按 C 复位改为「长按 C 2 秒」，避免误触发、也避免和组合键冲突。
import time as _time

C_HOLD_RESET_SEC = 2.0     # 长按 C 多久回手柄
_MOD_KEYS = ("l", "zl", "r", "zr", "sll", "srl", "slr", "srr",
             "gl", "gr")


def feed_combo(pair_id: int, c: bool, l: bool, zl: bool, r: bool, zr: bool,
               sll: bool, srl: bool, slr: bool, srr: bool,
               gl: bool, gr: bool) -> str:
    """喂入 C 键及修饰键当前状态，返回本次触发的动作描述。

    规则：
      * C 按住期间，任一修饰键出现「按下沿」→ 触发对应组合键（**切换开关**：
        目标侧已是该模式则回手柄，否则进入该模式）。
      * 单独长按 C ≥2 秒 → 全部回手柄（reset，兜底）。
      * 单纯短按 C 不触发任何事。
    """
    now = _time.monotonic()
    prev = _combo_prev.setdefault(
        pair_id, {"c": False, "c_down_at": 0.0,
                  **{k: False for k in _MOD_KEYS}})

    cur = {"l": l, "zl": zl, "r": r, "zr": zr,
           "sll": sll, "srl": srl, "slr": slr, "srr": srr,
           "gl": gl, "gr": gr}

    # C 按下沿：记录时刻
    if c and not prev["c"]:
        prev["c_down_at"] = now
    # C 松开：清除长按计时
    if not c:
        prev["c_down_at"] = 0.0

    action = ""
    if c:
        # 1) 修饰键按下沿（C 已按住）→ 组合键
        for k in ("sll", "srl", "slr", "srr", "gl", "gr",
                  "l", "zl", "r", "zr"):
            if cur[k] and not prev[k]:
                mapping = {
                    "sll": "macro_sll", "srl": "macro_srl",
                    "slr": "macro_slr", "srr": "macro_srr",
                    # 充电握把背键只触发宏，不参与模式切换（不进 side_target）
                    "gl": "macro_gl", "gr": "macro_gr",
                    "l": "left_mouse", "zl": "left_gyro",
                    "r": "right_mouse", "zr": "right_gyro",
                }
                act = mapping[k]
                # 组合键变成「切换开关」：再次触发同一组合 → 回手柄模式
                side_target = {
                    "left_mouse": ("Left", MODE_MOUSE),
                    "left_gyro": ("Left", MODE_GYRO),
                    "right_mouse": ("Right", MODE_MOUSE),
                    "right_gyro": ("Right", MODE_GYRO),
                }.get(act)
                if side_target:
                    side, target_mode = side_target
                    if get_mode(pair_id, side) == target_mode:
                        set_mode(pair_id, side, MODE_GAMEPAD)
                        act += "_off"       # 便于日志/测试识别"关闭"
                    else:
                        set_mode(pair_id, side, target_mode)
                action = act
                break
        # 2) 长按 C 复位（且本帧没有触发组合键）
        if not action and prev["c_down_at"] and (now - prev["c_down_at"]) >= C_HOLD_RESET_SEC:
            set_mode(pair_id, "Left", MODE_GAMEPAD, persist=False)
            set_mode(pair_id, "Right", MODE_GAMEPAD)
            prev["c_down_at"] = 0.0     # 只触发一次
            action = "reset"

    # 更新所有键的边沿状态
    prev["c"] = bool(c)
    for k in _MOD_KEYS:
        prev[k] = bool(cur[k])
    return action


def reset_combo(pair_id: int):
    _combo_prev.pop(pair_id, None)


# 组合键本次触发所"消费"的修饰键（按钮语义名）——这些键在本帧不再触发鼠标动作，
# 避免 C+L 进鼠标模式时 L（默认=鼠标左键）误点一下。
_consumed = {}


def mark_consumed(pair_id: int, action: str):
    """组合键触发后调用：记下被消费的修饰键，供本帧 keymap 分发跳过。"""
    m = {
        "left_mouse": "L", "left_mouse_off": "L",
        "left_gyro": "ZL", "left_gyro_off": "ZL",
        "right_mouse": "R", "right_mouse_off": "R",
        "right_gyro": "ZR", "right_gyro_off": "ZR",
    }
    key = m.get(action)
    if key:
        _consumed[pair_id] = key


def is_consumed(pair_id: int, button_name: str) -> bool:
    return _consumed.get(pair_id) == button_name


def clear_consumed(pair_id: int):
    _consumed.pop(pair_id, None)


# 兼容旧接口（部分调用点/测试可能用）
def feed_c_key(pair_id: int, pressed: bool) -> bool:
    prev = _c_prev.get(pair_id, False)
    _c_prev[pair_id] = pressed
    if pressed and not prev:
        return True
    return False


def reset_c_key(pair_id: int):
    _c_prev[pair_id] = False


# ── 灵敏度挡位 ───────────────────────────────────────────────────────────────
def get_dpi_index(pair_id: int) -> int:
    return int(get_config(pair_id)["mouse_dpi_index"])


def get_dpi_scale(pair_id: int) -> float:
    return DPI_LEVELS[get_dpi_index(pair_id)][1]


def get_dpi_label(pair_id: int) -> str:
    idx = get_dpi_index(pair_id)
    dpi, scale = DPI_LEVELS[idx]
    return f"{idx + 1} 挡 · {dpi} DPI · {scale:g}x"


def feed_dpi_keys(pair_id: int, plus_pressed: bool, minus_pressed: bool,
                  both_in_pointer: bool) -> int:
    """加减键切挡。双柄都在指针模式：+升/−降到顶停；单柄：都升循环。"""
    prev = _dpi_prev.setdefault(pair_id, {"plus": False, "minus": False})
    plus_edge = bool(plus_pressed) and not prev["plus"]
    minus_edge = bool(minus_pressed) and not prev["minus"]
    prev["plus"] = bool(plus_pressed)
    prev["minus"] = bool(minus_pressed)
    idx = get_dpi_index(pair_id)
    if both_in_pointer:
        if plus_edge:
            idx = min(len(DPI_LEVELS) - 1, idx + 1)
        elif minus_edge:
            idx = max(0, idx - 1)
    else:
        if plus_edge or minus_edge:
            idx = (idx + 1) % len(DPI_LEVELS)
    if idx != get_dpi_index(pair_id):
        get_config(pair_id)["mouse_dpi_index"] = idx
        save_config(pair_id)
    return idx


def apply_dpi_action(pair_id: int, action: str, both_in_pointer: bool):
    """由 keymap 的 dpi_up/dpi_down 动作直接切挡（边沿已在调用方判定）。"""
    idx = get_dpi_index(pair_id)
    if action == ACT_DPI_UP:
        if both_in_pointer:
            idx = min(len(DPI_LEVELS) - 1, idx + 1)   # 双柄到顶停住
        else:
            idx = (idx + 1) % len(DPI_LEVELS)          # 单柄循环
    elif action == ACT_DPI_DOWN:
        if both_in_pointer:
            idx = max(0, idx - 1)                      # 双柄到底停住
        else:
            idx = (idx + 1) % len(DPI_LEVELS)          # 单柄也升（原规则）
    if idx != get_dpi_index(pair_id):
        get_config(pair_id)["mouse_dpi_index"] = idx
        save_config(pair_id)
    return idx


def reset_dpi_keys(pair_id: int):
    _dpi_prev.pop(pair_id, None)


# ── 滚轮：力度曲线 + 亚格平滑 ────────────────────────────────────────────────
STICK_CENTER = 2048
WHEEL_DEADZONE = 120
WHEEL_TRAVEL = 900
WHEEL_SPEED = 0.35
WHEEL_CURVE = 2.0
MIN_SCROLL = 8.0 / 120.0


def wheel_delta(side: str, raw_x: int, raw_y: int, reverse: bool = False) -> float:
    dx = int(raw_x) - STICK_CENTER
    dy = int(raw_y) - STICK_CENTER
    y_up = dy
    x_up = -dx if side == "Left" else dx
    signed, mag = (x_up, abs(dx)) if abs(dx) >= abs(dy) else (y_up, abs(dy))
    if mag <= WHEEL_DEADZONE:
        return 0.0
    norm = min(1.0, (mag - WHEEL_DEADZONE) / (WHEEL_TRAVEL - WHEEL_DEADZONE))
    norm = norm ** WHEEL_CURVE
    val = (1 if signed > 0 else -1) * norm
    return -val if reverse else val


def wheel_direction(side, raw_x, raw_y, reverse=False) -> int:
    d = wheel_delta(side, raw_x, raw_y, reverse)
    return 1 if d > 0 else (-1 if d < 0 else 0)


def accumulate_wheel(acc: float, delta: float) -> tuple[float, float]:
    if delta == 0:
        return 0.0, acc
    if (acc > 0 and delta < 0) or (acc < 0 and delta > 0):
        acc = 0.0
    acc += delta * WHEEL_SPEED
    if abs(acc) < MIN_SCROLL:
        return 0.0, acc
    out, acc = acc, 0.0
    return out, acc


# ── 陀螺仪鼠标：角速度 → 光标增量（超级马力欧银河 NS 版逻辑）────────────────
# 银河式核心：手柄侧放桌面，绕「竖直轴」转 = 光标水平移动；
# 绕「水平横轴」俯仰 = 光标垂直移动。是角速度积分，但增益必须很温和，
# 否则 109Hz 下每帧累加会瞬间飞出屏幕（上一版 GYRO_GAIN=2.5 就属这种爆炸）。
GYRO_DEADZONE_DPS = 6.0     # dps 死区，防静止漂移
GYRO_GAIN = 0.18            # dps → 像素/帧（2026-11-20 用户反馈 0.12 偏低，提到 0.18）
GYRO_LSB_TO_DPS = 0.06103   # ±2000dps/32767


def gyro_cursor_delta(side: str, imu_raw, pair_id: int) -> tuple[float, float]:
    """IMU 原始 6 轴 → 光标 (dx, dy) 像素增量（银河式）。

    imu_raw = (ax,ay,az,gx,gy,gz)。
    银河逻辑（右手柄侧放、按键朝上，绕桌面法线=垂直轴转）：
      - gz（绕传感器 Z / 桌面法线的 yaw）→ 光标水平
      - gx（绕手柄长轴的 pitch）         → 光标垂直
    上一版错用 gy 当水平轴（那是俯仰相关的轴），方向逻辑不对。
    左右手：镜像取反；再叠加用户 GUI 的 X/Y 反转与 scale。
    """
    if not imu_raw or len(imu_raw) < 6:
        return 0.0, 0.0
    gx, gy, gz = imu_raw[3], imu_raw[4], imu_raw[5]
    cfg = get_config(pair_id)
    scale = get_dpi_scale(pair_id) * float(cfg["gyro_scale"])

    yaw_dps = gz * GYRO_LSB_TO_DPS     # 绕垂直轴 → 水平
    pitch_dps = gx * GYRO_LSB_TO_DPS   # 绕长轴 → 垂直
    if abs(yaw_dps) < GYRO_DEADZONE_DPS:
        yaw_dps = 0.0
    if abs(pitch_dps) < GYRO_DEADZONE_DPS:
        pitch_dps = 0.0

    # ★★★ 2026-11-20 最终定案：两只手柄方向**完全一致**，不做左右镜像 ★★★
    # 依据：JC2 双手柄 IMU 坐标系一致（实测，见 n-mwhdgkgdkxcl）——不像 JC1
    # 右手装反。此前反复加 side 镜像正是"一直改不好"的根源。
    # 从用户历次实测反馈反推，正确映射为：水平取反、垂直不取反（左右手相同）。
    h = -yaw_dps * GYRO_GAIN * scale
    v = -pitch_dps * GYRO_GAIN * scale
    if cfg["gyro_invert_x"]:
        h = -h
    if cfg["gyro_invert_y"]:
        v = -v
    return h, v


# ── 宏系统（运行时，不持久化）────────────────────────────────────────────────
def start_macro_record(pair_id: int, trigger: str):
    _macro_rec[pair_id] = {"recording": True, "current": [], "trigger": trigger}


def record_macro_step(pair_id: int, action: str):
    rec = _macro_rec.get(pair_id)
    if rec and rec.get("recording"):
        rec["current"].append(action)


def stop_macro_record(pair_id: int, name: str = None, persist: bool = True):
    rec = _macro_rec.get(pair_id)
    if not rec or not rec.get("recording"):
        return None
    rec["recording"] = False
    cfg = get_config(pair_id)
    name = name or rec.get("trigger") or "macro1"
    cfg["macros"][name] = list(rec["current"])
    cfg["macro_bindings"][rec.get("trigger")] = name
    if persist:
        save_config(pair_id)
    return name


def is_macro_enabled(pair_id: int) -> bool:
    return bool(get_config(pair_id)["macro_enabled"])


def reset_pair(pair_id: int):
    for d in (_c_prev, _combo_prev, _dpi_prev, _macro_rec, _consumed):
        d.pop(pair_id, None)
    _active.pop(pair_id, None)
    _cfg.pop(pair_id, None)
