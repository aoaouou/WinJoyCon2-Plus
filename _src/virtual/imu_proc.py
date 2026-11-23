# -*- coding: utf-8 -*-
"""IMU：Joy-Con 2 -> Joy-Con 1 报告系。

═══════════════════════════════════════════════════════════════════
推导依据：两份 SDL 源码的轴定义逐条对照
═══════════════════════════════════════════════════════════════════

【JC2 原生】SDL_hidapi_switch2.c:1175-1180
    gyro_data[0] = +gx      gyro_data[1] = +gz      gyro_data[2] = -gy
    accel_data[0] = +ax     accel_data[1] = +az     accel_data[2] = -ay

【JC1 报告系】sdl_switch.c:2411-2427
    data[0] = -rep_gy       data[1] = +rep_gz       data[2] = -rep_gx
    data[0] = -rep_ay       data[1] = +rep_az       data[2] = -rep_ax
    右手额外: data[0] = -data[0];  data[1] = -data[1]

求解：让 JC1 的 data[] 等于 JC2 的 *_data[]
  data[0]: -rep_gy = +gx  =>  rep_gy = -gx
  data[1]: +rep_gz = +gz  =>  rep_gz = +gz
  data[2]: -rep_gx = -gy  =>  rep_gx = +gy

  => gyro report = (gy, -gx, gz)
     ★ 即交换 gx/gz 的语义位：gx 填到第 1 位并取负，gy 填到第 0 位
     这就是「前后倾 / 左右倾互换」的根源。

  accel 同理:
      rep_ay = -ax,  rep_az = +az,  rep_ax = +ay
  => accel report = (ay, -ax, az)

【右手 180°】
  JC1 对右手额外做 data[0]=-data[0]; data[1]=-data[1]，
  JC2 没有这一层。要让右手表现与左手一致，report 的第 0/1 位
  （即 accel 的 ay/ax 与 gyro 的 gy/-gx）需预先取负：
  => 右手 report 的 0、1 位再乘 -1
"""

INT16_MAX = 32767

# ═══ gyro 量纲换算（唯一一次，必要的物理单位转换）═══
#
# 依据：
#   · JC2/NS2 IMU 量纲 = 16.384 raw/dps
#     （Pro2 ProfessionalImuPipeline.cs 原文：
#      "Switch 2 Pro dynamic wired/wireless integration converges near the
#       16.384-count scale. The old 14.247 value belongs to Switch 1 IMUs."）
#   · JC1 由 SPI(0x6020) gyro scale=13371 声明 = 936/13371 = 14.285 raw/dps
#     （SDL SWITCH_GYRO_SCALE = 14.2842，两者一致）
#
# 主机按 SPI 的 14.285 解释我们填的值，所以必须把 JC2 的 16.384
# 换算到 14.285：系数 = 16.384 / 14.285 ≈ 1.1469
#
# 这不是补丁 —— 是把源设备量纲转换到目标设备声明量纲的必要换算。
JC2_GYRO_RAW_PER_DPS = 16.384      # JC2/NS2 IMU 量纲（Pro2 实证）
# JC1 SPI gyro scale = 13371，主机公式 dps = raw * 936 / (scale - offset)
#   → raw/dps = (scale - offset) / 936 = 13371 / 936 = 14.285
JC1_GYRO_RAW_PER_DPS = 13371.0 / 936.0   # = 14.2842，与 SDL 一致

GYRO_SCALE = JC2_GYRO_RAW_PER_DPS / JC1_GYRO_RAW_PER_DPS   # ≈ 1.1469


def _clamp(v):
    return -INT16_MAX if v < -INT16_MAX else (INT16_MAX if v > INT16_MAX else v)


# ── 模拟器兼容模式（热切换）──────────────────────────────────────────────
# "ryujinx"（默认）：缓存帧原样带 gyro。Ryujinx 按实际帧间隔积分，正常。
# "eden"：缓存帧 gyro 清零。Eden 按固定 dt 积分，避免重复帧多算。
# 运行时可随时切换，立即生效（get 每次读模块变量），并持久化到 config.ini。
_IMU_COMPAT_MODE = "ryujinx"


def get_imu_compat_mode() -> str:
    return _IMU_COMPAT_MODE


def set_imu_compat_mode(mode: str, persist: bool = True):
    global _IMU_COMPAT_MODE
    if mode not in ("ryujinx", "eden"):
        return
    _IMU_COMPAT_MODE = mode
    if persist:
        try:
            import configparser
            from app_paths import config_path
            import os
            p = config_path()
            cp = configparser.ConfigParser()
            if os.path.exists(p):
                cp.read(p, encoding="utf-8")
            if "Controller" not in cp:
                cp["Controller"] = {}
            cp["Controller"]["imu_compat_mode"] = mode
            with open(p, "w", encoding="utf-8") as f:
                cp.write(f)
        except Exception:
            pass


def load_imu_compat_mode():
    """启动时从 config.ini 读取模式（不写盘）。"""
    try:
        import configparser
        from app_paths import config_path
        import os
        p = config_path()
        cp = configparser.ConfigParser()
        if os.path.exists(p):
            cp.read(p, encoding="utf-8")
            m = cp.get("Controller", "imu_compat_mode", fallback="ryujinx").strip().lower()
            if m in ("ryujinx", "eden"):
                set_imu_compat_mode(m, persist=False)
    except Exception:
        pass


# ── 0x30 报告的 IMU 填充：3 组同值（协议标准）──────────────────────────────
# 真机与 SDL/Ryujinx 的标准模型：一帧 15ms 带 3 组采样（0/5/10ms），
# 主机按 5ms×3 积分 = 15ms，所以 3 组都填当前真值是正确做法。
# 真 JC1 在 Ryujinx 与 Eden 表现一致，说明两个模拟器的积分逻辑相同 ——
# Eden 异常的根因不是"3 组怎么填"，而是我们重复发送**缓存帧**时，
# 仍带着相同的 IMU 值，Eden 对它再次积分导致放大（见 hid_function 的修复）。


def imu(side, raw6):
    """(ax,ay,az,gx,gy,gz) JC2 原始值 -> JC1 报告 6 元组。"""
    ax, ay, az, gx, gy, gz = (int(v) for v in raw6)

    # 解出的 report 值
    ax_r = ay
    ay_r = -ax
    az_r = az
    gx_r = round(gy * GYRO_SCALE)
    gy_r = round(-gx * GYRO_SCALE)
    gz_r = round(gz * GYRO_SCALE)

    if side == "right":
        # 预补偿 JC1 对右手 data[0]/data[1] 的额外取负。
        # 穷举验证：符号 (1,-1,-1) 作用于 accel、gyro 各自后三位里的 y/z 位
        # 可让右手 SDL 输出与 JC2 原生逐分量相等（差=0）。
        ay_r = -ay_r
        az_r = -az_r
        gy_r = -gy_r
        gz_r = -gz_r

    return (_clamp(ax_r), _clamp(ay_r), _clamp(az_r),
            _clamp(gx_r), _clamp(gy_r), _clamp(gz_r))