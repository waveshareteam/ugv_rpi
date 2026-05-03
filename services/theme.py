"""
UGV Theme Service.
Themes live in templates/themes/<name>.css and set CSS custom properties.
User preference is persisted via the settings service (per-session via cookies on client).
"""

import os
from ugv_logger import get_logger

log = get_logger("theme")

VALID_THEMES = {"dark", "cyberpunk", "military", "terminal", "nexus"}
DEFAULT_THEME = "nexus"

_HERE        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_THEMES_DIR  = os.path.join(_HERE, "templates", "themes")


def is_valid(name: str) -> bool:
    return name in VALID_THEMES


def list_themes() -> list:
    return sorted(VALID_THEMES)


def theme_url(name: str) -> str:
    """Return the URL path to load from Flask (served via /<filename> route)."""
    return f"/themes/{name}.css"
