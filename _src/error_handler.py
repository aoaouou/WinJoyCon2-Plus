"""
Error handling utilities for Joy2Win-vgamepad
"""
import os
import configparser
from logger_config import info, warning, error
from app_paths import app_path, config_path as _cfg_path  # noqa: E402

# ══════════════════════════════════════════════════════════════════════
# config.ini 的编码：统一为 UTF-8。
#
# 曾经的 bug（2026-11-15 修复）：
#   config.py 用 locale 默认编码（中文 Windows = GBK）读，
#   error_handler 用 UTF-8 读、且失败时**整份重写**配置文件。
#   两边不一致 → 打包版（PyInstaller 强制 UTF-8 模式）启动即失败
#   → 配置被覆盖成默认值 → 用户手改的 IMU 符号覆盖等全部丢失。
#
# 现在的约定：
#   1. 读写都用 _cfg_encoding() 解析出的同一个编码；
#   2. 修复时只**追加缺失的段/键**，绝不整份覆盖已有内容。
# ══════════════════════════════════════════════════════════════════════

CONFIG_ENCODINGS = ("utf-8-sig", "utf-8", "gbk")


def _cfg_encoding(path):
    """探测配置文件实际编码（BOM 优先，其次严格 UTF-8，最后 GBK）。"""
    if not os.path.exists(path):
        return "utf-8"
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in ("utf-8", "gbk"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def read_config_parser(path):
    """按探测到的编码解析配置，返回 ConfigParser（不存在的文件返回空）。"""
    parser = configparser.ConfigParser()
    if os.path.exists(path):
        parser.read(path, encoding=_cfg_encoding(path))
    return parser


def write_config_parser(parser, path):
    """原子写回（UTF-8），先写临时文件再替换，避免写一半损坏。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        parser.write(f)
    os.replace(tmp, path)


def validate_config_file(config_path=_cfg_path()):
    """
    Validate and repair config file if corrupted.

    修复策略：**只追加缺失的段与键**，已有值一律不动。
    """
    defaults = {
        "Controller": {
            "controller": "0", "led_player": "1",
            "save_mac_address": "0", "enable_dsu": "0", "mouse_mode": "0",
            "output_mode": "hidmaestro",
        },
        "Bluetooth": {"mac_address": ""},
    }

    try:
        if not os.path.exists(config_path):
            warning(f"Config file {config_path} not found, creating default config")
            parser = configparser.ConfigParser()
            for sec, kv in defaults.items():
                parser[sec] = kv
            write_config_parser(parser, config_path)
            info(f"Created default config file at {config_path}")
            return True

        parser = read_config_parser(config_path)

        added = []
        for sec, kv in defaults.items():
            if sec not in parser:
                parser[sec] = dict(kv)
                added.append(sec)
                continue
            for k, v in kv.items():
                if k not in parser[sec]:
                    parser[sec][k] = v
                    added.append(f"{sec}.{k}")

        if added:
            warning(f"Config missing entries {added}, appending (values kept)")
            write_config_parser(parser, config_path)
            info(f"Config repaired: appended {added}")
        else:
            info("Config file validated successfully")
        return True

    except Exception as e:
        error(f"Error validating config file: {e}")
        return False



async def connect_with_retry(connect_func, max_retries=3, retry_delay=2):
    """
    Connect with automatic retry mechanism
    
    Args:
        connect_func: Async function to connect
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
    
    Returns:
        Result of connect_func or None if all retries failed
    """
    import asyncio
    
    for attempt in range(1, max_retries + 1):
        try:
            info(f"Connection attempt {attempt}/{max_retries}")
            result = await connect_func()
            if result:
                info(f"Connection successful on attempt {attempt}")
                return result
        except Exception as e:
            error(f"Connection attempt {attempt} failed: {e}")
            
            if attempt < max_retries:
                warning(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                error(f"All {max_retries} connection attempts failed")
    
    return None


def handle_dsu_server_error(error_msg):
    """
    Handle DSU server errors gracefully
    
    Args:
        error_msg: Error message from DSU server
    
    Returns:
        str: User-friendly error message
    """
    error_patterns = {
        "Address already in use": "DSU 服务器端口已被占用，可能另一个实例正在运行",
        "Permission denied": "权限不足，无法启动 DSU 服务器",
        "Network is unreachable": "网络不可达，请检查网络连接",
    }
    
    for pattern, user_msg in error_patterns.items():
        if pattern in error_msg:
            error(f"DSU server error: {error_msg}")
            return user_msg
    
    error(f"DSU server error: {error_msg}")
    return f"DSU 服务器错误: {error_msg}"
