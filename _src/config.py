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
        # 输出模式：
        #   hidmaestro = 原生 Joy-Con 2（057E:2067 L / 2066 R，HIDMaestro）—— 默认
        #   grip       = 充电握把形态（057E:200E，Switch 1 握把 0x30 协议）：
        #                SDL 里组合/分开都正常，功能按 Switch 1 协议
        #   joycon1    = 虚拟 Joy-Con 1（057E:2006 / 2007，USB/IP）—— 旧路径，保留
        #   xgip       = 虚拟 Xbox 360（原版行为）
        "output_mode": "hidmaestro",
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
            # 输出模式：xgip（原版 Xbox360）/ joycon1（虚拟 Joy-Con 1）
            self.output_mode = str(
                controller_section.get('output_mode', self.output_mode)).strip().lower()
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
            "output_mode": self.output_mode,
        }
