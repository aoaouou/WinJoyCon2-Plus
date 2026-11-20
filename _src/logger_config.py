"""
Logging configuration module for Joy2Win-vgamepad
"""
import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler


def _app_dir() -> str:
    """程序所在目录。

    PyInstaller onefile 下 sys.executable 指向 exe 本身，sys.frozen 为 True；
    源码运行时用 __file__ 的目录。
    **绝不能用相对路径或 os.getcwd()** —— 从 CMD/系统目录/计划任务启动时，
    工作目录可能是 C:\\WINDOWS\\system32，那里没有写权限，
    结果是启动即抛 PermissionError 直接崩溃（已实测踩过）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _make_file_handler(log_file: str, level: int, max_bytes: int,
                       backup: int) -> logging.Handler:
    """优先写到程序目录；无权限则退到 %TEMP%，绝不让日志拖垮启动。"""
    candidates = [log_file]
    if not os.path.isabs(log_file):
        candidates = [os.path.join(_app_dir(), log_file),
                      os.path.join(tempfile.gettempdir(), log_file)]
    last_err = None
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            h = RotatingFileHandler(path, maxBytes=max_bytes,
                                    backupCount=backup, encoding="utf-8")
            return h
        except (PermissionError, OSError) as exc:
            last_err = exc
    # 全部失败 -> 用 NullHandler，保证程序仍能启动
    sys.stderr.write(f"[logger] 无法创建日志文件，日志已禁用: {last_err}\n")
    return logging.NullHandler()


def setup_logger(name="Joy2Win", log_file="logs/joy2win.log", level=logging.INFO):
    """
    Setup and return a logger instance
    
    Args:
        name: Logger name
        log_file: Log file path
        level: Logging level
    
    Returns:
        Logger instance
    """
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger
    
    # Create formatters
    # Detailed formatter for file logs
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Simple formatter for console
    console_formatter = logging.Formatter(
        '%(levelname)s - %(message)s'
    )
    
    # File handler with rotation (10MB max, keep 5 backup files)
    file_handler = _make_file_handler(
        log_file, level, 10 * 1024 * 1024, 5)
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)  # Only show INFO and above in console
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Create default logger
logger = setup_logger()

# Convenience functions
def debug(msg, *args, **kwargs):
    logger.debug(msg, *args, **kwargs)

def info(msg, *args, **kwargs):
    logger.info(msg, *args, **kwargs)

def warning(msg, *args, **kwargs):
    logger.warning(msg, *args, **kwargs)

def error(msg, *args, **kwargs):
    logger.error(msg, *args, **kwargs)

def critical(msg, *args, **kwargs):
    logger.critical(msg, *args, **kwargs)

def exception(msg, *args, **kwargs):
    logger.exception(msg, *args, **kwargs)
