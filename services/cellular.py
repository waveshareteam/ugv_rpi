"""
Cellular modem service — Sierra Wireless MC8700 (USB 1199:68a3).
Robust: gracefully handles missing tools (mmcli, qmicli).
"""
import glob
import json as _json
import re
import subprocess
from ugv_logger import get_logger

log = get_logger("cellular")

_TARGET_VENDOR  = "1199"
_TARGET_PRODUCT = "68a3"
_TARGET_NAME    = "Sierra Wireless MC8700"


def _run(cmd, timeout=8):
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout,
                                       stderr=subprocess.DEVNULL).strip()
    except FileNotFoundError:
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _lsusb_detect():
    out = _run(["lsusb"])
    if out is None:
        return {"detected": False, "error": "lsusb not available"}
    for line in out.splitlines():
        if _TARGET_VENDOR in line and _TARGET_PRODUCT in line:
            return {"detected": True, "usb_line": line.strip()}
    return {"detected": False}


def _tty_ports():
    return sorted(glob.glob("/dev/ttyUSB*"))


def _mmcli_status():
    """Query ModemManager. Returns dict with availability + modem details."""
    list_out = _run(["mmcli", "-L"])
    if list_out is None:
        return {"available": False, "error": "mmcli not installed"}

    match = re.search(r"/Modem/(\d+)", list_out)
    if not match:
        return {"available": True, "modem_found": False}

    mid = match.group(1)
    detail = _run(["mmcli", "-m", mid])
    if not detail:
        return {"available": True, "modem_found": True, "modem_id": mid}

    result = {"available": True, "modem_found": True, "modem_id": mid}
    patterns = [
        (r"operator name\s*\|\s*'([^']+)'",  "operator"),
        (r"signal quality\s*\|\s*'(\d+)'",   "signal_percent"),
        (r"access tech\s*\|\s*'([^']+)'",    "access_tech"),
        (r"state\s*\|\s*'([^']+)'",          "state"),
        (r"power state\s*\|\s*'([^']+)'",    "power_state"),
        (r"imei\s*\|\s*'([^']+)'",           "imei"),
        (r"sim\s*\|\s*([^\n]+)",             "sim_path"),
    ]
    for pattern, key in patterns:
        m = re.search(pattern, detail, re.IGNORECASE)
        if m:
            result[key] = m.group(1).strip()
    return result


def _interface_ip(ifaces=("wwan0", "ppp0", "usb0")):
    """Try to find an IP on known modem interfaces."""
    for iface in ifaces:
        out = _run(["ip", "-j", "addr", "show", iface])
        if not out:
            continue
        try:
            data = _json.loads(out)
            for entry in data:
                for addr in entry.get("addr_info", []):
                    if addr.get("family") == "inet":
                        return {"interface": iface, "ip": addr["local"]}
        except Exception:
            pass
    return None


def get_cellular_status():
    """Full cellular modem status. Never raises."""
    try:
        usb   = _lsusb_detect()
        tty   = _tty_ports()
        mm    = _mmcli_status()
        ip    = _interface_ip()
        return {
            "modem_detected": usb["detected"],
            "usb_info":       usb.get("usb_line"),
            "tty_ports":      tty,
            "modemmanager":   mm,
            "interface_ip":   ip,
            "target_device":  _TARGET_NAME,
        }
    except Exception as exc:
        log.warning("cellular status error: %s", exc)
        return {"modem_detected": False, "error": str(exc)}
