"""
UGV structured logger — rotating file + coloured console.
Usage:
    from ugv_logger import get_logger
    log = get_logger('mymodule')
    log.info("Robot started")
    log.warning("Low battery: %.1f V", voltage)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

_LOGDIR   = os.path.join(os.path.dirname(__file__), "logs")
_LOGFILE  = os.path.join(_LOGDIR, "ugv.log")
_FMT      = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
_DATEFMT  = "%Y-%m-%d %H:%M:%S"
_MAX_SIZE = 5 * 1024 * 1024   # 5 MB
_BACKUPS  = 3

_COLORS = {
    "DEBUG":    "\033[36m",    # cyan
    "INFO":     "\033[32m",    # green
    "WARNING":  "\033[33m",    # yellow
    "ERROR":    "\033[31m",    # red
    "CRITICAL": "\033[35m",    # magenta
    "RESET":    "\033[0m",
}


class _ColorFormatter(logging.Formatter):
    def format(self, record):
        color = _COLORS.get(record.levelname, _COLORS["RESET"])
        record.levelname = f"{color}{record.levelname}{_COLORS['RESET']}"
        return super().format(record)


_root_configured = False


def _configure_root():
    global _root_configured
    if _root_configured:
        return

    os.makedirs(_LOGDIR, exist_ok=True)

    root = logging.getLogger("ugv")
    root.setLevel(logging.DEBUG)

    # Rotating file — full debug
    fh = RotatingFileHandler(_LOGFILE, maxBytes=_MAX_SIZE,
                              backupCount=_BACKUPS, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    root.addHandler(fh)

    # Console — INFO and above with colour
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(_ColorFormatter(_FMT, datefmt=_DATEFMT))
    root.addHandler(ch)

    root.propagate = False
    _root_configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(f"ugv.{name}")
