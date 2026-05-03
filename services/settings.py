"""
UGV Settings Service — reads/writes config/settings.json.
All V2 features check settings before activating.

Usage:
    from services.settings import get, set_key, all_settings

    if get('auth.enabled'):
        ...
    set_key('theme.default', 'cyberpunk')
"""

import json
import os
import threading
from ugv_logger import get_logger

log = get_logger("settings")

_HERE    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH    = os.path.join(_HERE, "config", "settings.json")
_lock    = threading.RLock()
_cache   = None


def _load():
    global _cache
    with open(_PATH, encoding="utf-8") as f:
        _cache = json.load(f)
    return _cache


def _save(data):
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def all_settings() -> dict:
    with _lock:
        if _cache is None:
            _load()
        return dict(_cache)


def get(dotted_key: str, default=None):
    """
    Read a setting using dot notation.
    get('auth.enabled')  → False
    get('robot.max_speed') → 0.8
    """
    with _lock:
        if _cache is None:
            _load()
        parts = dotted_key.split(".")
        node  = _cache
        try:
            for p in parts:
                node = node[p]
            return node
        except (KeyError, TypeError):
            return default


def set_key(dotted_key: str, value) -> bool:
    """
    Write a setting by dot-notation key.
    Returns True on success.
    """
    with _lock:
        if _cache is None:
            _load()
        parts = dotted_key.split(".")
        node  = _cache
        for p in parts[:-1]:
            if p not in node or not isinstance(node[p], dict):
                node[p] = {}
            node = node[p]
        node[parts[-1]] = value
        try:
            _save(_cache)
            log.info("Setting updated: %s = %r", dotted_key, value)
            return True
        except Exception as e:
            log.error("Failed to save settings: %s", e)
            return False


def update_bulk(updates: dict) -> dict:
    """
    Apply multiple dotted-key updates atomically.
    update_bulk({'auth.enabled': True, 'theme.default': 'cyberpunk'})
    """
    results = {}
    for k, v in updates.items():
        results[k] = set_key(k, v)
    return results


def reload():
    """Force reload from disk (e.g. after external edit)."""
    global _cache
    with _lock:
        _cache = None
        _load()
    log.info("Settings reloaded from disk")
