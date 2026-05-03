"""
Remote Access blueprint — V3.
Covers: ZeroTier, WireGuard, Cellular modem (MC8700), Network interfaces.
All read endpoints are open to viewer+; write/control endpoints require admin.
"""
import json as _json
import re
import subprocess

from flask import Blueprint, jsonify, request

from services.auth import require_role
from services import cellular as _cellular
from ugv_logger import get_logger

log = get_logger("remote")

remote_bp = Blueprint("remote", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd, timeout=10, sudo=False):
    """Run subprocess and return stdout string, or None on FileNotFoundError."""
    full = (["sudo"] + list(cmd)) if sudo else list(cmd)
    try:
        return subprocess.check_output(full, text=True, timeout=timeout,
                                       stderr=subprocess.STDOUT).strip()
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError as exc:
        return exc.output.strip()
    except subprocess.TimeoutExpired:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# ZeroTier
# ─────────────────────────────────────────────────────────────────────────────

def _zt_installed():
    return _run(["which", "zerotier-cli"]) is not None


def _zt_info():
    out = _run(["zerotier-cli", "info"], sudo=True)
    if not out:
        return None
    # "200 info <node_id> <version> ONLINE|OFFLINE"
    parts = out.split()
    if len(parts) < 4:
        return None
    return {
        "node_id": parts[2],
        "version": parts[3],
        "online":  "ONLINE" in out,
        "raw":     out,
    }


def _zt_networks():
    out = _run(["zerotier-cli", "listnetworks"], sudo=True) or ""
    networks = []
    for line in out.splitlines():
        if not line.startswith("200"):
            continue
        cols = line.split()
        # 200 listnetworks <id> <name> <mac> <status> <type> <dev> <ips>
        if len(cols) < 7:
            continue
        networks.append({
            "id":     cols[2],
            "name":   cols[3],
            "mac":    cols[4],
            "status": cols[5],
            "type":   cols[6],
            "dev":    cols[7] if len(cols) > 7 else "",
            "ips":    cols[8] if len(cols) > 8 else "",
        })
    return networks


@remote_bp.route("/api/remote/zerotier/status")
def zt_status():
    if not _zt_installed():
        return jsonify({"installed": False})
    info = _zt_info()
    if info is None:
        return jsonify({"installed": True, "running": False,
                        "error": "zerotier-one not running or permission denied"})
    return jsonify({
        "installed": True,
        "running":   True,
        "node_id":   info["node_id"],
        "version":   info["version"],
        "online":    info["online"],
        "networks":  _zt_networks(),
    })


@remote_bp.route("/api/remote/zerotier/join", methods=["POST"])
@require_role("admin")
def zt_join():
    nid = (request.get_json() or {}).get("network_id", "").strip()
    if not re.fullmatch(r"[0-9a-f]{16}", nid):
        return jsonify({"ok": False, "error": "network_id must be 16 hex chars"}), 400
    out = _run(["zerotier-cli", "join", nid], sudo=True)
    return jsonify({"ok": out is not None, "output": out})


@remote_bp.route("/api/remote/zerotier/leave", methods=["POST"])
@require_role("admin")
def zt_leave():
    nid = (request.get_json() or {}).get("network_id", "").strip()
    if not re.fullmatch(r"[0-9a-f]{16}", nid):
        return jsonify({"ok": False, "error": "network_id must be 16 hex chars"}), 400
    out = _run(["zerotier-cli", "leave", nid], sudo=True)
    return jsonify({"ok": out is not None, "output": out})


# ─────────────────────────────────────────────────────────────────────────────
# WireGuard
# ─────────────────────────────────────────────────────────────────────────────

def _wg_installed():
    return _run(["which", "wg"]) is not None


def _wg_parse_dump():
    """
    Parse `wg show all dump`.
    Returns dict: {interface_name: {public_key, listen_port, peers: [...]}}
    Private keys are NEVER returned.
    """
    out = _run(["wg", "show", "all", "dump"])
    if out is None:
        return None  # not installed
    interfaces = {}
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) == 5:
            # Interface line: iface  private_key  public_key  listen_port  fwmark
            iface = cols[0]
            interfaces[iface] = {
                "public_key":   cols[2],
                "listen_port":  cols[3],
                "peers":        [],
            }
        elif len(cols) == 9:
            # Peer line: iface  pub  psk  endpoint  allowed  handshake  rx  tx  keepalive
            iface = cols[0]
            if iface not in interfaces:
                interfaces[iface] = {"public_key": "", "listen_port": "", "peers": []}
            try:
                rx = int(cols[6])
                tx = int(cols[7])
            except ValueError:
                rx = tx = 0
            interfaces[iface]["peers"].append({
                "public_key":       cols[1],
                "endpoint":         cols[3],
                "allowed_ips":      cols[4],
                "latest_handshake": cols[5],
                "transfer_rx_b":    rx,
                "transfer_tx_b":    tx,
            })
    return interfaces


def _wg_quick(action, iface="wg0"):
    out = _run(["wg-quick", action, iface], sudo=True, timeout=20)
    return out is not None, out or ""


@remote_bp.route("/api/remote/wireguard/status")
def wg_status():
    if not _wg_installed():
        return jsonify({"installed": False})
    data = _wg_parse_dump()
    if data is None:
        return jsonify({"installed": False})
    return jsonify({"installed": True, "interfaces": data})


@remote_bp.route("/api/remote/wireguard/up", methods=["POST"])
@require_role("admin")
def wg_up():
    iface = (request.get_json() or {}).get("interface", "wg0")
    ok, msg = _wg_quick("up", iface)
    return jsonify({"ok": ok, "message": msg})


@remote_bp.route("/api/remote/wireguard/down", methods=["POST"])
@require_role("admin")
def wg_down():
    iface = (request.get_json() or {}).get("interface", "wg0")
    ok, msg = _wg_quick("down", iface)
    return jsonify({"ok": ok, "message": msg})


@remote_bp.route("/api/remote/wireguard/restart", methods=["POST"])
@require_role("admin")
def wg_restart():
    iface = (request.get_json() or {}).get("interface", "wg0")
    _wg_quick("down", iface)
    ok, msg = _wg_quick("up", iface)
    return jsonify({"ok": ok, "message": msg})


# ─────────────────────────────────────────────────────────────────────────────
# Cellular (Sierra Wireless MC8700)
# ─────────────────────────────────────────────────────────────────────────────

@remote_bp.route("/api/remote/cellular/status")
def cellular_status():
    return jsonify(_cellular.get_cellular_status())


@remote_bp.route("/api/remote/cellular/refresh", methods=["POST"])
def cellular_refresh():
    return jsonify(_cellular.get_cellular_status())


# ─────────────────────────────────────────────────────────────────────────────
# Network interfaces
# ─────────────────────────────────────────────────────────────────────────────

_INTERESTING = re.compile(r"^(eth\d|wlan\d|zt\w+|wg\w+|wwan\d|ppp\d|usb\d|lo)$")


def _get_interfaces():
    out = _run(["ip", "-j", "addr"])
    if not out:
        return []
    try:
        data = _json.loads(out)
    except Exception:
        return []

    ifaces = []
    for entry in data:
        name = entry.get("ifname", "")
        addrs = [
            a["local"]
            for a in entry.get("addr_info", [])
            if a.get("family") in ("inet", "inet6")
        ]
        ifaces.append({
            "name":  name,
            "mac":   entry.get("address"),
            "state": entry.get("operstate", "UNKNOWN"),
            "ips":   addrs,
            "mtu":   entry.get("mtu"),
            "flags": entry.get("flags", []),
        })
    return ifaces


def _get_default_route():
    out = _run(["ip", "route", "show", "default"])
    if not out:
        return None
    # "default via 192.168.1.1 dev eth0 ..."
    m = re.search(r"default via (\S+) dev (\S+)", out)
    if m:
        return {"gateway": m.group(1), "dev": m.group(2)}
    return None


@remote_bp.route("/api/remote/interfaces")
def net_interfaces():
    return jsonify({
        "interfaces":    _get_interfaces(),
        "default_route": _get_default_route(),
    })
