import asyncio, os, platform, time
from typing import Optional
from bleak import BleakClient, BleakScanner
from config import Config
from controller_command import (
    ControllerCommand,
    UUID_NOTIFY,
    UUID_CMD_RESPONSE,
    UUID_POWER_LEFT,
    UUID_POWER_RIGHT,
)
from controller_manager import get_controller_manager, ControllerMode
from logger_config import info, warning, error, debug
from controllers.battery import battery_percentage_from_voltage
from app_paths import app_path, config_path  # noqa: E402

# Check if the operating system is Windows
if(os.name != 'nt'):
    error("This application is only supported on Windows.")
    exit(1)

manufact = {
    "id": 0x0553,  # Nintendo Co., Ltd.
    "data-prefix": bytes([0x01, 0x00, 0x03, 0x7e, 0x05])
}

# Global state
_connected_devices = {}  # mac_address -> (client, side, pair_id)
_main_event_loop = None  # Reference to main event loop for callbacks
_notification_error_last = {}
_low_battery_counts = {}
_low_battery_alerted = set()


def log_notification_error(key: str, exc: Exception, interval: float = 5.0):
    """Log recurring BLE notification failures at a bounded rate."""
    now = time.monotonic()
    if now - _notification_error_last.get(key, 0) >= interval:
        _notification_error_last[key] = now
        warning(f"{key}: {type(exc).__name__}: {exc}")


def set_event_loop(loop):
    """Set the main event loop reference for use in callbacks"""
    global _main_event_loop
    _main_event_loop = loop


def get_event_loop():
    """Get the main event loop"""
    return _main_event_loop


def get_mac_from_device(device):
    """Extract MAC address from device"""
    return device.address.replace(":", "").replace("-", "").upper()


def get_power_report_uuid(side: str):
    if side == "Left":
        return UUID_POWER_LEFT
    if side == "Right":
        return UUID_POWER_RIGHT
    raise ValueError(f"Unknown Joy-Con side: {side}")


def get_player_led_value(pair_id: int):
    if not 0 <= pair_id < 4:
        raise ValueError(f"Invalid pair_id: {pair_id}")
    return format(1 << pair_id, 'x')


def handle_power_report(mac: str, data, side: str = "Joy-Con 2"):
    """Decode Joy-Con 2 report 0x07/0x08 power information."""
    if len(data) < 2:
        return
    power_info = data[1]
    external_power = bool(power_info & 0x01)
    is_charging = bool(power_info & 0x02)
    battery_units = (power_info >> 2) & 0x0F
    if battery_units > 9:
        debug(f"Ignoring invalid Joy-Con 2 battery level: {battery_units}")
        return
    battery_level = round(battery_units * 100 / 9)
    get_controller_manager().update_battery(
        mac,
        battery_level,
        is_charging=is_charging,
        external_power=external_power,
    )
    info(f"Joy-Con 2 {side} battery level: {battery_units}/9 ({battery_level}%)")


async def capture_power_level(client, side: str, mac: str, timeout: float = 1.5):
    """Capture one native 0-9 battery report before selecting report 0x05.

    Keeping report 0x07/0x08 subscribed after sensor initialisation can stop the
    main button/IMU stream on real controllers. A short pre-initialisation
    subscription obtains the controller's own state-of-charge value and is
    removed before report 0x05 is enabled.
    """
    received = asyncio.Event()

    def power_handler(sender, data):
        try:
            handle_power_report(mac, data, side)
            received.set()
        except Exception as exc:
            debug(f"Failed to decode {side} power report: {exc}")

    uuid = get_power_report_uuid(side)
    started = False
    try:
        await client.start_notify(uuid, power_handler)
        started = True
        await asyncio.wait_for(received.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        debug(f"Timed out waiting for {side} native battery report")
        return False
    except Exception as exc:
        debug(f"Unable to capture {side} native battery report: {exc}")
        return False
    finally:
        if started:
            try:
                await client.stop_notify(uuid)
            except Exception as exc:
                debug(f"Unable to stop {side} battery report: {exc}")


async def cleanup_failed_connection(client, side: str, mac: str, pair_id=None):
    """Release resources left by a failed or partial BLE initialisation."""
    _connected_devices.pop(mac, None)
    _low_battery_counts.pop(mac, None)
    _low_battery_alerted.discard(mac)
    try:
        if client.is_connected:
            notify_uuids = [UUID_NOTIFY, UUID_CMD_RESPONSE]
            try:
                notify_uuids.append(get_power_report_uuid(side))
            except ValueError:
                pass
            for uuid in notify_uuids:
                try:
                    await client.stop_notify(uuid)
                except Exception:
                    pass
            await client.disconnect()
    except Exception as exc:
        debug(f"Cleanup disconnect failed for {mac}: {exc}")

    manager = get_controller_manager()
    if pair_id is None:
        mapped_pair = manager.get_pair_by_mac(mac)
        pair_id = mapped_pair.pair_id if mapped_pair else None
    await manager.remove_joycon(mac)

    if pair_id is not None:
        pair = manager.get_pair(pair_id)
        pair_empty = pair is None or not pair.is_active()
        try:
            from control_type.duo_joycon import cleanup_disconnected_joycon, unregister_vibration
            unregister_vibration(side, pair_id)
            cleanup_disconnected_joycon(pair_id, side, pair_empty)
            from control_type.single_joycon import reset_pair_state
            reset_pair_state(pair_id)
        except Exception as exc:
            debug(f"State cleanup failed for pair {pair_id}: {exc}")


def detect_side_from_name(name: str) -> str:
    """Detect Joy-Con side from device name"""
    if not name:
        return "Unknown"
    
    name_upper = name.upper()
    
    # Check for explicit left/right indicators
    if "(L)" in name_upper or "LEFT" in name_upper or name_upper.endswith(" L"):
        return "Left"
    elif "(R)" in name_upper or "RIGHT" in name_upper or name_upper.endswith(" R"):
        return "Right"
    
    # Fallback: check for standalone L/R with better pattern matching
    # Check if name contains " L " or " R " (with spaces)
    if " L " in name or name.startswith("L ") or name.endswith(" L"):
        return "Left"
    elif " R " in name or name.startswith("R ") or name.endswith(" R"):
        return "Right"
    
    # Check for Joy-Con specific patterns
    if "Joy" in name:
        # Joy-Con typically has (L) or (R) in the name
        # If we see "L)" or "R)" without the opening paren, it's likely a formatting issue
        if name_upper.find("L)") != -1:
            return "Left"
        elif name_upper.find("R)") != -1:
            return "Right"
    
    return "Unknown"


async def connect_joycon(device, side: str, mac: str, pair_id: Optional[int] = None, mode: str = "both"):
    """Connect to a Joy-Con and assign it to a pair
    
    Args:
        device: BLE device
        side: "Left" or "Right"
        mac: MAC address
        pair_id: Optional preferred pair ID (0-based)
        mode: "left", "right", or "both"
    """
    global _connected_devices

    manager = get_controller_manager()
    assigned_pair_id = None
    connection_loop = asyncio.get_running_loop()

    def disconnected_callback(disconnected_client):
        if connection_loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(
            cleanup_failed_connection(
                disconnected_client, side, mac, assigned_pair_id
            ),
            connection_loop,
        )
    
    # Try to connect
    # device 可能是 None（快速探测路径只给了 MAC），此时按地址连。
    target = device if device is not None else mac
    client = BleakClient(
        target,
        timeout=5.0,        # 2026-11-21：8→5s。JC2 配对窗口只有 10s，握手要快，
                            # 失败也要快，才能在这 10s 内完成重试
        disconnected_callback=disconnected_callback,
    )
    try:
        dev_name = getattr(device, "name", None) or mac

        # ── 连接重试 ──
        # 实测：Windows BLE 栈偶发"第一次 connect 失败、第二次成功"，
        # 尤其在一键连接两只手柄并发时。原实现一次失败就放弃，
        # 表现就是"只连上一个，另一个连不上，必须重启程序"。
        #
        # 退避重试：0.4s → 0.9s → 1.8s（给协议栈释放上一个句柄的时间）
        info(f"Attempting to connect to {mac} ({dev_name})...")
        last_exc = None
        for attempt in range(1, 4):
            try:
                await client.connect()
                if client.is_connected:
                    break
                last_exc = RuntimeError("connect 返回但未连接")
            except Exception as exc:
                last_exc = exc
            if attempt < 3:
                delay = 0.4 * (2 ** (attempt - 1))
                debug(f"{mac} 第 {attempt} 次连接失败（{last_exc}），"
                      f"{delay:.1f}s 后重试")
                # 失败后必须关掉旧 client，否则句柄不释放，下次必失败
                try:
                    await client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(delay)

        if not client.is_connected:
            warning(f"Failed to connect to {mac} after 3 attempts: {last_exc}")
            return False
        
        info(f"Successfully connected to {mac}")
        
        # Assign to a pair (use preferred pair if specified)
        pair_id_result = await manager.assign_joycon(client, side, mac, preferred_pair=pair_id)
        if pair_id_result is None:
            warning(f"No available slot for {side} Joy-Con {mac}")
            await client.disconnect()
            return False
        assigned_pair_id = pair_id_result
        
        pair = manager.get_pair(pair_id_result)
        info(f"Connected {side} Joy-Con {mac} to Pair {pair_id_result + 1} (Mode: {pair.get_mode_display()})")
        
        # Store connection info
        _connected_devices[mac] = (client, side, pair_id_result)

        # 记住这只手柄属于左/右（供下次一键连接快速识别 + 解锁判断）
        # 每次连接成功都写，确保用户手动选侧的结果被持久化
        if side in ("Left", "Right") and mac:
            record_known_side(side, mac)

        # Initialize the controller
        # For "both" mode, always use duo mode even if only one Joy-Con is connected
        if mode == "both":
            await handle_duo_joycons(client, side, pair_id_result, mac)
        elif pair.mode == ControllerMode.BOTH:
            await handle_duo_joycons(client, side, pair_id_result, mac)
        elif pair.mode == ControllerMode.LEFT_ONLY:
            await handle_single_joycon(client, side, pair_id_result, mac)
        elif pair.mode == ControllerMode.RIGHT_ONLY:
            await handle_single_joycon(client, side, pair_id_result, mac)
        
        info(f"Initialization complete for {mac}")
        return True
        
    except asyncio.TimeoutError:
        warning(f"Connection timeout for {mac} - device may not be in pairing mode")
        await cleanup_failed_connection(client, side, mac, assigned_pair_id)
        return False
    except Exception as e:
        error(f"Error connecting to {mac}: {type(e).__name__}: {e}")
        await cleanup_failed_connection(client, side, mac, assigned_pair_id)
        return False


async def handle_duo_joycons(client, side: str, pair_id: int, mac: str):
    """Handle duo Joy-Con mode for a specific pair
    
    Args:
        client: BLE client
        side: "Left" or "Right"
        pair_id: Pair ID (0-based)
        mac: MAC address
    """
    from control_type.duo_joycon import notify_duo_joycons

    async def notification_handler(sender, data):
        try:
            # Check if client is still connected before processing
            if not client.is_connected:
                return
            # Directly await the notification handler
            await notify_duo_joycons(client, side, data, pair_id)
        except Exception as e:
            log_notification_error(f"Duo notification pair={pair_id} side={side}", e)
    
    def response_handler(sender, data):
        try:
            if client.is_connected:
                ControllerCommand().receive_response(client, data)
        except Exception as e:
            log_notification_error(f"Duo command response pair={pair_id} side={side}", e)
    
    response_notify_started = False
    try:
        await client.start_notify(UUID_CMD_RESPONSE, response_handler)
        response_notify_started = True
        await capture_power_level(client, side, mac)
        await initSendControllerCmd(client, "Joy-Con", pair_id)
        
    finally:
        if response_notify_started:
            try:
                await client.stop_notify(UUID_CMD_RESPONSE)
            except Exception as e:
                debug(f"Failed to stop command notifications for {mac}: {e}")
    
    await client.start_notify(UUID_NOTIFY, notification_handler)


async def handle_single_joycon(client, side: str, pair_id: int, mac: str):
    """Handle single Joy-Con mode for a specific pair"""
    # Reset pair state to clear old joycon instance
    from control_type.single_joycon import reset_pair_state
    reset_pair_state(pair_id)
    
    from control_type.single_joycon import notify_single_joycons

    async def notification_handler(sender, data):
        try:
            # Check if client is still connected before processing
            if not client.is_connected:
                return
            # Directly await the notification handler
            await notify_single_joycons(client, side, data, pair_id)
        except Exception as e:
            log_notification_error(f"Single notification pair={pair_id} side={side}", e)
    
    def response_handler(sender, data):
        try:
            if client.is_connected:
                ControllerCommand().receive_response(client, data)
        except Exception as e:
            log_notification_error(f"Single command response pair={pair_id} side={side}", e)
    
    response_notify_started = False
    try:
        await client.start_notify(UUID_CMD_RESPONSE, response_handler)
        response_notify_started = True
        await capture_power_level(client, side, mac)
        await initSendControllerCmd(client, "Joy-Con", pair_id)
    finally:
        if response_notify_started:
            try:
                await client.stop_notify(UUID_CMD_RESPONSE)
            except Exception as e:
                debug(f"Failed to stop command notifications for {mac}: {e}")
    
    await client.start_notify(UUID_NOTIFY, notification_handler)


async def initSendControllerCmd(client, controllerName: str, pair_id: int):
    """Send initialization commands to controller"""
    controllerCommand = ControllerCommand()
    current_config = Config().getConfig()

    async def send_required(command_type, args=None):
        if not await controllerCommand.send_command(client, command_type, args):
            raise RuntimeError(f"Controller command failed: {command_type}")
    
    if current_config.get('save_mac_address', False):
        mac_address = current_config.get('mac_address', b'\xFF' * 6)
        mac_addr1 = mac_address
        mac_addr2 = ((mac_address[0] - 1) & 0xFF).to_bytes(1, 'big') + mac_address[1:]
        
        await send_required("JOY2_SAVE_MC_ADDR_STEP1",
                            {"mac-addr1": mac_addr1.hex(), "mac-addr2": mac_addr2.hex()})
        await send_required("JOY2_SAVE_MC_ADDR_STEP2")
        await send_required("JOY2_SAVE_MC_ADDR_STEP3")
        await send_required("JOY2_SAVE_MC_ADDR_STEP4")
        info(f"MAC address saved successfully.")
    
    # ═══ 震动功能位必须在发任何震动包之前打开 ═══
    # 这两条是「不震」的解药：feature bit 5 = Rumble。
    # 用 send_command 而非 send_required —— 老固件可能不支持整条命令，
    # 拿不到应答不能让整个连接流程失败。
    # 参考 SDL_hidapi_switch2.c 的 init_sequence（0x0c subcmd 02 / 04，掩码 0x27）
    await controllerCommand.send_command(client, "JOY2_SET_FEATURE_MASK")
    await controllerCommand.send_command(client, "JOY2_ENABLE_FEATURES")

    await send_required("JOY2_CONNECTED_VIBRATION")
    
    # Set LED to show pair number (1-4)
    led_value = get_player_led_value(pair_id)
    await send_required("JOY2_SET_PLAYER_LED", {"led_player": led_value})

    await send_required("JOY2_INIT_SENSOR_DATA")
    await send_required("JOY2_START_SENSOR_DATA")

    # Query battery through the command-response channel. This is reliable on
    # hardware where report 0x07/0x08 is notify-only, and unlike subscribing to
    # that alternate report it does not interrupt the main button/IMU stream.
    if await controllerCommand.send_command(client, "JOY2_GET_BATTERY_VOLTAGE"):
        response = controllerCommand.lastResponse
        if response and len(response) >= 10:
            voltage_mv = int.from_bytes(response[8:10], "little")
            battery_level = battery_percentage_from_voltage(voltage_mv)
            if battery_level is not None:
                mac = client.address.replace(":", "").replace("-", "").upper()
                manager = get_controller_manager()
                pair = manager.get_pair_by_mac(mac)
                joycon_info = None
                if pair:
                    if pair.left.mac_address == mac:
                        joycon_info = pair.left
                    elif pair.right.mac_address == mac:
                        joycon_info = pair.right
                # The native 0-9 state-of-charge report is authoritative.
                # Only use voltage estimation when that report was unavailable.
                if joycon_info is None or joycon_info.battery_level is None:
                    manager.update_battery(mac, battery_level)
                    info(f"Joy-Con 2 battery fallback: {voltage_mv} mV (~{battery_level}%)")
                else:
                    info(f"Joy-Con 2 battery voltage: {voltage_mv} mV")
            else:
                warning(f"Ignoring invalid Joy-Con 2 battery voltage: {voltage_mv} mV")

    # Request high-throughput BLE connection parameters on Windows 11 (build >= 22000)
    # to increase sensor data frequency. Copied from switch2_input_viewer.py by ndeadly.
    if platform.system() == 'Windows':
        version = platform.version()
        try:
            build_number = int(version.rsplit('.', 1)[-1])
        except (TypeError, ValueError):
            warning(f"Unable to determine Windows build from {version!r}; skipping BLE throughput tuning")
            return
        if build_number >= 22000:
            from bleak.backends.winrt.client import BleakClientWinRT
            from winrt.windows.devices.bluetooth import BluetoothLEPreferredConnectionParameters
            backend = client._backend
            if isinstance(backend, BleakClientWinRT):
                backend._requester.request_preferred_connection_parameters(BluetoothLEPreferredConnectionParameters.throughput_optimized)


async def disconnect_all():
    """Disconnect all connected devices"""
    global _connected_devices
    
    info("Disconnecting all controllers...")
    manager = get_controller_manager()
    for mac, (client, side, pair_id) in list(_connected_devices.items()):
        try:
            if client.is_connected:
                try:
                    await client.stop_notify(get_power_report_uuid(side))
                except:
                    pass
                await client.disconnect()
            info(f"Disconnected {mac}")
        except Exception as e:
            error(f"Error disconnecting {mac}: {e}")
        await manager.remove_joycon(mac)
        pair = manager.get_pair(pair_id)
        try:
            from control_type.duo_joycon import cleanup_disconnected_joycon, unregister_vibration
            unregister_vibration(side, pair_id)
            cleanup_disconnected_joycon(pair_id, side, pair is None or not pair.is_active())
            from control_type.single_joycon import reset_pair_state
            reset_pair_state(pair_id)
        except Exception as exc:
            debug(f"State cleanup failed for pair {pair_id}: {exc}")
    
    _connected_devices.clear()
    
    # Clear any assignments that were not present in the connection registry.
    for mac in list(manager._mac_to_pair.keys()):
        await manager.remove_joycon(mac)


async def scan_for_joycons(include_connected: bool = False):
    """Scan for Joy-Cons - same as original Joy2Win project.

    include_connected=True（分开连接/纠正左右用）：不过滤已连接手柄，
    否则用户连过之后就再也扫不到，无法重新选侧。
    """
    device_controller = None
    
    def scan_callback(device, advertisement_data):
        nonlocal device_controller
        data = advertisement_data.manufacturer_data.get(manufact["id"])
        if not data:
            return
        
        if data.startswith(manufact["data-prefix"]):
            if not device_controller:
                mac = get_mac_from_device(device)
                # Skip if already connected —— 分开连接模式例外
                if mac in _connected_devices and not include_connected:
                    return
                info(f"Controller with address: {device.address} found.")
                device_controller = device
    
    scanner = BleakScanner(scan_callback)
    await scanner.start()
    
    # Keep scanning until a device is found (no timeout)
    while True:
        if device_controller:
            break
        await asyncio.sleep(0.5)
    
    await scanner.stop()
    return device_controller


def record_known_side(side: str, mac: str) -> None:
    """记住某个 MAC 属于哪一侧，写进 config.ini 的 [KnownSides]。"""
    try:
        import configparser
        import os
        parser = configparser.ConfigParser()
        if os.path.exists(config_path()):
            parser.read(config_path(), encoding="utf-8")
        if "KnownSides" not in parser:
            parser["KnownSides"] = {}
        parser["KnownSides"][side.lower()] = mac
        with open(config_path(), "w", encoding="utf-8") as fh:
            parser.write(fh)
    except Exception:
        pass


async def _probe_known_macs(timeout: float = 4.0):
    """快速探测：直接按已知 MAC 连接，验证手柄是否在线。

    比扫描快得多 —— Joy-Con 的 BLE 广播间隔长，扫描经常要等 10+ 秒
    才能收到第一包；而按 MAC 直连是主动寻呼，通常 1~3 秒就有结果。

    返回 {side: mac} 里能连上的那些。
    """
    import configparser
    import os
    from bleak import BleakClient

    if not os.path.exists(config_path()):
        return {}
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    if "KnownSides" not in parser:
        return {}

    from bleak import BleakScanner

    async def _try(side, mac):
        """探活。

        ⚠ 关键优化（2026-11-16）：**不做完整 connect+disconnect 探活**。

        原实现为了"确认在线"先连一次再断开，然后 connect_device 又连一次
        —— 等于每只手柄连两遍，每次连接白白多花 2~4 秒，而且断开后
        Windows BLE 栈需要时间释放句柄，紧接着的第二次连接经常失败，
        表现就是"只连上一个"。

        现在只做**轻量可达性检查**：用 BleakScanner 的 advertisement
        或直接返回 MAC 让 connect_device 去连（真连失败它会自己重试）。
        """
        try:
            # 直接返回 MAC：connect_device 有 3 次退避重试，
            # 真不在线会失败并清理，没必要在这里先连一遍。
            return side, mac
        except Exception:
            return side, None

    tasks = []
    for side in ("Left", "Right"):
        mac = parser["KnownSides"].get(side.lower(), "")
        if mac:
            tasks.append(_try(side, mac))
    if not tasks:
        return {}

    res = await asyncio.gather(*tasks, return_exceptions=True)
    out = {}
    for r in res:
        if isinstance(r, tuple) and r[1]:
            out[r[0]] = r[1]
    return out


async def scan_both_joycons(timeout: float = 45.0, on_progress=None):
    """扫描并收集**两只** Joy-Con，返回 (left_device, right_device)。

    设计目标：一键连接两只手柄。

    判定左右的方式（按可靠性排序）：
      1. 广播名里带 (L)/(R)
      2. 广播厂商数据里的设备类型字节
      3. Joy-Con 2 的 MAC 顺序（同一对里 L 的地址通常更小）

    每找到一只就回调 on_progress，让 GUI 能实时显示进度。
    """
    import time as _t

    found = {}      # side -> device
    seen = set()

    def _side_from_name(name: str):
        if not name:
            return None
        u = name.upper()
        if "(L)" in u or "LEFT" in u or u.endswith(" L"):
            return "Left"
        if "(R)" in u or "RIGHT" in u or u.endswith(" R"):
            return "Right"
        return None

    def _side_from_mac(mac: str):
        """按 MAC 判定左右。

        **优先用学习到的对照表**（config.ini 的 [KnownSides] 节）。
        MAC 是硬判据，比广播名可靠 —— Joy-Con 2 的广播名经常是空的
        （实测 name=None），以前靠名字判会全部落到兜底逻辑，
        导致左右随机分配、连反。

        没学过的 MAC 返回 None，交给调用方按到达顺序兜底。
        """
        try:
            from config import Config
            import configparser
            import os
            parser = configparser.ConfigParser()
            if os.path.exists(config_path()):
                parser.read(config_path(), encoding="utf-8")
            if "KnownSides" not in parser:
                return None
            m = mac.replace(":", "").upper()
            for side in ("Left", "Right"):
                v = parser["KnownSides"].get(side.lower(), "")
                if v and str(v).replace(":", "").upper() == m:
                    return side
        except Exception:
            pass
        return None


    candidates = []

    def scan_callback(device, advertisement_data):
        data = advertisement_data.manufacturer_data.get(manufact["id"])
        if not data or not data.startswith(manufact["data-prefix"]):
            return
        mac = get_mac_from_device(device)
        if mac in _connected_devices or mac in seen:
            return
        seen.add(mac)
        # 判定顺序：广播名 -> MAC 对照表
        # **MAC 对照表必须在这里调用**，否则 KnownSides 形同虚设，
        # 所有候选的 side 都是 None，只能等超时后兜底分配（实测要等 18 秒）。
        side = _side_from_name(device.name or "") or _side_from_mac(mac)
        candidates.append({"device": device, "mac": mac,
                           "name": device.name or "", "side": side})
        info(f"[扫描] 发现 {mac} name={device.name!r} side={side}")

    scanner = BleakScanner(scan_callback)
    await scanner.start()

    deadline = _t.monotonic() + timeout
    try:
        while _t.monotonic() < deadline:
            # 先按名字分配
            for c in list(candidates):
                if c["side"] and c["side"] not in found:
                    found[c["side"]] = c
                    candidates.remove(c)
                    if on_progress:
                        on_progress(c["side"], c["mac"])

            if len(found) >= 2:
                break

            # 兜底：有候选但分不出左右时，**立刻**按到达顺序分配，
            # 不再等 18 秒。只要候选数够填满空位就分配。
            free_sides = [s for s in ("Left", "Right") if s not in found]
            if candidates and len(candidates) >= len(free_sides):
                for c in list(candidates):
                    free = [s for s in ("Left", "Right") if s not in found]
                    if not free:
                        break
                    c["side"] = free[0]
                    found[c["side"]] = c
                    candidates.remove(c)
                    if on_progress:
                        on_progress(c["side"], c["mac"])
                if len(found) >= 2:
                    break

            await asyncio.sleep(0.1)
    finally:
        await scanner.stop()

    return found.get("Left"), found.get("Right")


async def scan_for_joycons_with_side():
    """Scan for Joy-Cons and try to detect side even when name is None"""
    device_controller = None
    detected_side = "Unknown"
    
    def scan_callback(device, advertisement_data):
        nonlocal device_controller, detected_side
        data = advertisement_data.manufacturer_data.get(manufact["id"])
        if not data:
            return
        
        if data.startswith(manufact["data-prefix"]):
            if not device_controller:
                mac = get_mac_from_device(device)
                # Skip if already connected
                if mac in _connected_devices:
                    return
                
                info(f"Controller with address: {device.address} found.")
                device_controller = device
                
                # Try to detect side from device name
                device_name = device.name if device.name else ""
                if device_name:
                    detected_side = detect_side_from_name(device_name)
                    info(f"Detected side from name '{device_name}': {detected_side}")
                else:
                    # If name is None, try to detect from MAC address pattern
                    # Some Joy-Cons have different MAC patterns for L/R
                    # Or check advertisement data for clues
                    info("Device name is None, checking other characteristics...")
                    # For now, we'll rely on user to specify side in GUI
    
    scanner = BleakScanner(scan_callback)
    await scanner.start()
    
    # Keep scanning until a device is found (no timeout)
    while True:
        if device_controller:
            break
        await asyncio.sleep(0.5)
    
    await scanner.stop()
    return device_controller, detected_side


async def connect_device(device_info: dict) -> bool:
    """Connect to a specific device"""
    device = device_info.get('device')
    side = device_info.get('side', 'Unknown')
    mac = device_info.get('mac', '')
    pair_id = device_info.get('pair_id')  # Get preferred pair_id from device_info
    mode = device_info.get('mode', 'both')  # Get connection mode
    
    # 允许只有 MAC：快速探测路径只会给出 mac，此时直接用地址连，
    # 不再依赖 device 对象（BleakClient 支持按地址连接）。
    if not device and not mac:
        return False

    return await connect_joycon(device, side, mac, pair_id=pair_id, mode=mode)


async def disconnect_pair_by_id(pair_id: int):
    """Disconnect a specific pair by ID"""
    manager = get_controller_manager()
    pair = manager.get_pair(pair_id)

    if not pair:
        return

    from control_type.duo_joycon import cleanup_disconnected_joycon, unregister_vibration
    from control_type.single_joycon import reset_pair_state

    # Disconnect left
    if pair.left and pair.left.mac_address:
        mac = pair.left.mac_address
        if mac in _connected_devices:
            client, _, _ = _connected_devices[mac]
            try:
                # Stop notifications before disconnecting
                if client.is_connected:
                    try:
                        await client.stop_notify(UUID_NOTIFY)
                    except:
                        pass
                    try:
                        await client.stop_notify(UUID_CMD_RESPONSE)
                    except:
                        pass
                    try:
                        await client.stop_notify(get_power_report_uuid("Left"))
                    except:
                        pass
                    await client.disconnect()
            except:
                pass
            _connected_devices.pop(mac, None)
        await manager.remove_joycon(mac)
        cleanup_disconnected_joycon(pair_id, "Left", not pair.is_active())
        reset_pair_state(pair_id)
        unregister_vibration("Left", pair_id)

    # Disconnect right
    if pair.right and pair.right.mac_address:
        mac = pair.right.mac_address
        if mac in _connected_devices:
            client, _, _ = _connected_devices[mac]
            try:
                # Stop notifications before disconnecting
                if client.is_connected:
                    try:
                        await client.stop_notify(UUID_NOTIFY)
                    except:
                        pass
                    try:
                        await client.stop_notify(UUID_CMD_RESPONSE)
                    except:
                        pass
                    try:
                        await client.stop_notify(get_power_report_uuid("Right"))
                    except:
                        pass
                    await client.disconnect()
            except:
                pass
            _connected_devices.pop(mac, None)
        await manager.remove_joycon(mac)
        cleanup_disconnected_joycon(pair_id, "Right", not pair.is_active())
        reset_pair_state(pair_id)
        unregister_vibration("Right", pair_id)



async def main():
    """Main entry point - CLI mode (manual connection only)"""
    info("=" * 50)
    info("Joy2Win - Multi Controller Support")
    info("Supports up to 4 pairs (8 Joy-Cons)")
    info("=" * 50)
    info("Note: Use GUI mode for better experience (python gui.py)")
    info("=" * 50)

    try:

        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)

    except (KeyboardInterrupt, asyncio.CancelledError):
        info("Interrupting...")
    finally:
        await disconnect_all()
        info("All controllers disconnected.")
