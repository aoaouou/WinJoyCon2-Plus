import configparser
import os
import sys
from app_paths import app_path, config_path as _cfg_path  # noqa: E402


def app_dir() -> str:
    """程序所在目录。

    **绝不能用相对路径或 getcwd()** —— 从 CMD / 系统目录 / 计划任务 /
    快捷方式启动时工作目录可能是 C:\\WINDOWS\\system32，
    那里没有写权限，读写配置会 PermissionError 直接弹框退出（已实测踩过）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resolve_path(path: str) -> str:
    """相对路径一律按程序目录解析，绝对路径原样返回。"""
    if os.path.isabs(path):
        return path
    return os.path.join(app_dir(), path)


class Config:
    _instance = None
    _defaults = {
        "controller": 0,
        "led_player": "0001",
        "save_mac_address": False,
        "enable_dsu": False,
        "mouse_mode": 0,
        "mac_address": b'\xFF' * 6,  # Always bytes to avoid type mismatch
        "sll_mapping": "",      # SL Left mapping (empty = unmapped)
        "srl_mapping": "",      # SR Left mapping (empty = unmapped)
        "slr_mapping": "",      # SL Right mapping (empty = unmapped)
        "srr_mapping": "",      # SR Right mapping (empty = unmapped)
        "gl_mapping": "",       # 充电握把 GL (grip) mapping (empty = unmapped)
        "gr_mapping": "",       # 充电握把 GR (grip) mapping (empty = unmapped)
    }

    def __new__(cls, config_path=_cfg_path()):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config_path = resolve_path(config_path)
            cls._instance._init_defaults()
            cls._instance.load_config()
        return cls._instance

    def _init_defaults(self):
        for key, value in self._defaults.items():
            setattr(self, key, value)

    def load_config(self):
        config_parser = configparser.ConfigParser()
        if not os.path.exists(self._config_path):
            print(f"{self._config_path} not found. Using default values.")
            return

        # 编码必须显式指定：不指定时 configparser 用 locale 默认编码
        # （中文 Windows = GBK），而打包版 PyInstaller 会强制 UTF-8 模式，
        # 两边不一致会让同一份配置在源码运行与 exe 运行下解析结果不同。
        # 用与 error_handler 相同的探测逻辑，读侧与写侧保持同一约定。
        from error_handler import _cfg_encoding
        config_parser.read(self._config_path, encoding=_cfg_encoding(self._config_path))
        
        # Check for Controller section (case-insensitive)
        controller_section = None
        for section_name in ['Controller', 'controller']:
            if section_name in config_parser:
                controller_section = config_parser[section_name]
                break
        
        if controller_section:
            try:
                self.controller = int(controller_section.get('controller', self.controller))
            except ValueError:
                print(f"Invalid 'controller' value in {self._config_path}. Using default: {self.controller}")
            self.led_player = str(controller_section.get('led_player', self.led_player))
            save_mac_val = controller_section.get('save_mac_address', '0')
            self.save_mac_address = save_mac_val.lower() in ['1', 'true', 'yes']
            enable_dsu_val = controller_section.get('enable_dsu', '0')
            self.enable_dsu = enable_dsu_val.lower() in ['1', 'true', 'yes']
            try:
                self.mouse_mode = int(controller_section.get('mouse_mode', self.mouse_mode if self.mouse_mode in [0, 1, 2] else 0))
                if self.mouse_mode not in [0, 1, 2]:
                    self.mouse_mode = 0
            except ValueError:
                print(f"Invalid 'mouse_mode' value in {self._config_path}. Using default: 0")
                self.mouse_mode = 0
            # SL/SR button mappings
            self.sll_mapping = controller_section.get('sll_mapping', self.sll_mapping)
            self.srl_mapping = controller_section.get('srl_mapping', self.srl_mapping)
            self.slr_mapping = controller_section.get('slr_mapping', self.slr_mapping)
            self.srr_mapping = controller_section.get('srr_mapping', self.srr_mapping)
            # 充电握把背键 GL/GR mappings (empty = unmapped)
            self.gl_mapping = controller_section.get('gl_mapping', self.gl_mapping)
            self.gr_mapping = controller_section.get('gr_mapping', self.gr_mapping)
        else:
            print(f"Section 'Controller' not found in {self._config_path}. Using default values.")
            self._init_defaults()
            return
        
        if "Bluetooth" in config_parser or "bluetooth" in config_parser:
            section = config_parser["Bluetooth"] if "Bluetooth" in config_parser else config_parser["bluetooth"]
            configMacAddress = section.get("mac_address", self.mac_address)
            if not configMacAddress:
                self.mac_address = self._defaults["mac_address"]
            elif(len(configMacAddress) == 12 and all(c in "0123456789ABCDEF" for c in configMacAddress.upper())): # Valid MAC address format like AABBCCDDEEFF
                self.mac_address = bytes.fromhex(configMacAddress)[::-1] # Convert mac to little-endian format
            else:
                print(f"Invalid MAC address in {self._config_path}. Using default: {self.mac_address}")
                self.mac_address = self._defaults["mac_address"]
        else:
            print(f"Section 'Bluetooth' not found in {self._config_path}. disabling save_mac_address.")
            self.save_mac_address = False

    def getConfig(self):
        return {
            "controller": self.controller,
            "led_player": self.led_player,
            "save_mac_address": self.save_mac_address,
            "enable_dsu": self.enable_dsu,
            "mouse_mode": self.mouse_mode,
            "mac_address": self.mac_address,
            "sll_mapping": self.sll_mapping,
            "srl_mapping": self.srl_mapping,
            "slr_mapping": self.slr_mapping,
            "srr_mapping": self.srr_mapping,
            "gl_mapping": self.gl_mapping,
            "gr_mapping": self.gr_mapping,
        }


# ── 左右记忆 / 首次须知（原 usbip_setup.py，USB/IP 删除后迁来）──────────
def get_known_sides() -> dict:
    """读取 config.ini [KnownSides] → {'left': mac, 'right': mac}。"""
    out = {}
    try:
        cp = configparser.ConfigParser()
        p = _cfg_path()
        if os.path.exists(p):
            cp.read(p, encoding="utf-8")
            if "KnownSides" in cp:
                for side in ("left", "right"):
                    out[side] = cp["KnownSides"].get(side, "").strip()
    except Exception:
        pass
    return out


def sides_calibrated() -> bool:
    """左右都已记忆 → 允许一键连接。"""
    ks = get_known_sides()
    return bool(ks.get("left")) and bool(ks.get("right"))


def reset_known_sides() -> tuple:
    """清空左右记忆与首次须知标志（纠正用）。返回 (成功, 说明)。"""
    try:
        cp = configparser.ConfigParser()
        p = _cfg_path()
        if not os.path.exists(p):
            return False, f"配置文件不存在：{p}"
        cp.read(p, encoding="utf-8")
        removed = "KnownSides" in cp
        if removed:
            cp.remove_section("KnownSides")
        if "General" not in cp:
            cp["General"] = {}
        cp["General"]["first_run_done"] = "0"
        with open(p, "w", encoding="utf-8") as f:
            cp.write(f)
        return True, f"已清空左右记忆（{'有记录被移除' if removed else '原本就没有记录'}）\n{p}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def first_run_done() -> bool:
    try:
        cp = configparser.ConfigParser()
        p = _cfg_path()
        if os.path.exists(p):
            cp.read(p, encoding="utf-8")
            if "General" in cp:
                return cp["General"].get("first_run_done", "0").strip() == "1"
    except Exception:
        pass
    return False


def mark_first_run_done():
    cp = configparser.ConfigParser()
    p = _cfg_path()
    if os.path.exists(p):
        cp.read(p, encoding="utf-8")
    if "General" not in cp:
        cp["General"] = {}
    cp["General"]["first_run_done"] = "1"
    with open(p, "w", encoding="utf-8") as f:
        cp.write(f)
