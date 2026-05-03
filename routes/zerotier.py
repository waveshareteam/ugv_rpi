"""
ZeroTier management Blueprint.
Routes:
  GET  /zt/status       — daemon info + network list
  GET  /zt/networks     — networks detail
  POST /zt/join         — join network  {"network_id": "..."}
  POST /zt/leave        — leave network {"network_id": "..."}
"""

import subprocess
import json
from flask import Blueprint, jsonify, request
from ugv_logger import get_logger

log = get_logger("zerotier")
zt_bp = Blueprint("zerotier", __name__)

_TIMEOUT = 6


def _run(*cmd):
    try:
        r = subprocess.run(
            ["sudo", "zerotier-cli"] + list(cmd),
            capture_output=True, text=True, timeout=_TIMEOUT
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, "", "zerotier-cli not found — is ZeroTier installed?"
    except subprocess.TimeoutExpired:
        return -2, "", "zerotier-cli timed out"
    except Exception as e:
        return -3, "", str(e)


def _parse_info(line):
    """Parse '200 info <id> <version> <status>'."""
    parts = line.split()
    if len(parts) >= 5 and parts[0] == "200":
        return {"node_id": parts[2], "version": parts[3], "status": parts[4]}
    return {"raw": line}


def _parse_networks(text):
    """Parse listnetworks output — try JSON first, fall back to text."""
    if not text or text.startswith("Error"):
        return []
    text = text.strip()
    if text.startswith("["):
        try:
            return json.loads(text)
        except Exception:
            pass
    networks = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0] == "200":
            networks.append({
                "id":     parts[2],
                "name":   parts[3],
                "status": parts[5],
                "type":   parts[6] if len(parts) > 6 else "PRIVATE",
            })
    return networks


@zt_bp.route("/zt/status")
def zt_status():
    code, out, err = _run("info")
    if code != 0:
        log.warning("ZeroTier info failed: %s", err)
        return jsonify({"ok": False, "error": err or "ZeroTier not running"}), 503

    info = _parse_info(out)

    code2, nout, _ = _run("listnetworks")
    networks = _parse_networks(nout) if code2 == 0 else []

    log.info("ZeroTier status: %s, %d network(s)", info.get("status"), len(networks))
    return jsonify({"ok": True, "info": info, "networks": networks})


@zt_bp.route("/zt/networks")
def zt_networks():
    code, out, err = _run("listnetworks")
    if code != 0:
        return jsonify({"ok": False, "error": err}), 503
    return jsonify({"ok": True, "networks": _parse_networks(out)})


@zt_bp.route("/zt/join", methods=["POST"])
def zt_join():
    data = request.get_json() or {}
    nid = data.get("network_id", "").strip()
    if not nid or len(nid) != 16:
        return jsonify({"ok": False, "error": "Invalid network_id (must be 16 hex chars)"}), 400

    code, out, err = _run("join", nid)
    if code != 0:
        log.error("ZeroTier join %s failed: %s", nid, err)
        return jsonify({"ok": False, "error": err}), 500

    log.info("Joined ZeroTier network %s", nid)
    return jsonify({"ok": True, "message": f"Join request sent for {nid}", "output": out})


@zt_bp.route("/zt/leave", methods=["POST"])
def zt_leave():
    data = request.get_json() or {}
    nid = data.get("network_id", "").strip()
    if not nid:
        return jsonify({"ok": False, "error": "network_id required"}), 400

    code, out, err = _run("leave", nid)
    if code != 0:
        log.error("ZeroTier leave %s failed: %s", nid, err)
        return jsonify({"ok": False, "error": err}), 500

    log.info("Left ZeroTier network %s", nid)
    return jsonify({"ok": True, "message": f"Left network {nid}", "output": out})
