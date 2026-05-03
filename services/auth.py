"""
UGV Auth Service — SQLite + Werkzeug PBKDF2 + Flask sessions.

Roles (ascending permission):
  viewer   → read-only (status, video feed)
  operator → robot control (move, lights, CV, routines)
  admin    → everything + user management + settings

Auth is DISABLED by default (settings.json auth.enabled=false).
When disabled, all routes are accessible without login — V1 behaviour preserved.

API routes support both session cookie and Bearer token.
"""

import sqlite3
import secrets
import os
from functools import wraps
from datetime import datetime

from flask import session, request, jsonify, redirect, url_for, Blueprint, render_template, flash
from werkzeug.security import generate_password_hash, check_password_hash

from ugv_logger import get_logger

log = get_logger("auth")

# ── DB path (created next to this file's project root) ───────────────────────
_HERE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_HERE, "config", "ugv_users.db")

# ── Role hierarchy ────────────────────────────────────────────────────────────
ROLES = {"viewer": 1, "operator": 2, "admin": 3}

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ── Database helpers ──────────────────────────────────────────────────────────

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and default admin user if DB does not exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT    NOT NULL UNIQUE,
                password    TEXT    NOT NULL,
                role        TEXT    NOT NULL DEFAULT 'viewer',
                api_token   TEXT    UNIQUE,
                created_at  TEXT    NOT NULL,
                last_login  TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS login_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT,
                success    INTEGER,
                ip         TEXT,
                ts         TEXT
            )
        """)
        # Create default admin if no users exist
        row = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if row == 0:
            _create_user_internal(c, "admin", "ugv_admin", "admin")
            log.warning("Default admin created — username:admin password:ugv_admin — CHANGE IMMEDIATELY")
    log.info("Auth DB ready at %s", DB_PATH)


def _create_user_internal(conn, username, password, role):
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO users (username, password, role, api_token, created_at) VALUES (?,?,?,?,?)",
        (username, generate_password_hash(password), role, token,
         datetime.utcnow().isoformat())
    )


# ── Public user API ───────────────────────────────────────────────────────────

def create_user(username: str, password: str, role: str = "viewer") -> dict:
    if role not in ROLES:
        return {"ok": False, "error": f"Invalid role. Valid: {list(ROLES)}"}
    try:
        with _conn() as c:
            _create_user_internal(c, username, password, role)
        log.info("User created: %s (%s)", username, role)
        return {"ok": True, "username": username, "role": role}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Username already exists"}


def update_password(username: str, new_password: str) -> dict:
    with _conn() as c:
        rows = c.execute(
            "UPDATE users SET password=? WHERE username=?",
            (generate_password_hash(new_password), username)
        ).rowcount
    if rows:
        log.info("Password updated for %s", username)
        return {"ok": True}
    return {"ok": False, "error": "User not found"}


def delete_user(username: str) -> dict:
    if username == "admin":
        return {"ok": False, "error": "Cannot delete the admin account"}
    with _conn() as c:
        rows = c.execute("DELETE FROM users WHERE username=?", (username,)).rowcount
    return {"ok": True} if rows else {"ok": False, "error": "User not found"}


def list_users() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, username, role, created_at, last_login FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def verify_credentials(username: str, password: str):
    """Return user dict or None."""
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if row and check_password_hash(row["password"], password):
        return dict(row)
    return None


def verify_token(token: str):
    """Return user dict or None for Bearer token auth."""
    if not token:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE api_token=?", (token,)).fetchone()
    return dict(row) if row else None


def get_current_user():
    """Return user from session, or from Bearer token, or None."""
    if "user" in session:
        return session["user"]
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return verify_token(token)


def rotate_token(username: str) -> dict:
    new_token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute("UPDATE users SET api_token=? WHERE username=?", (new_token, username))
    return {"ok": True, "token": new_token}


def _log_login(username, success, ip):
    with _conn() as c:
        c.execute(
            "INSERT INTO login_log (username, success, ip, ts) VALUES (?,?,?,?)",
            (username, int(success), ip, datetime.utcnow().isoformat())
        )
    if success:
        with _conn() as c:
            c.execute("UPDATE users SET last_login=? WHERE username=?",
                      (datetime.utcnow().isoformat(), username))


# ── Decorators ────────────────────────────────────────────────────────────────

def _settings_auth_enabled():
    """Import lazily to avoid circular imports."""
    try:
        from services.settings import get as _get
        return _get("auth.enabled", False)
    except Exception:
        return False


def require_login(f):
    """Redirect to login if auth enabled and user not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _settings_auth_enabled():
            return f(*args, **kwargs)
        user = get_current_user()
        if not user:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "login": "/auth/login"}), 401
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def require_role(minimum_role: str):
    """Allow access only if user has at least minimum_role."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not _settings_auth_enabled():
                return f(*args, **kwargs)
            user = get_current_user()
            if not user:
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for("auth.login", next=request.path))
            user_level = ROLES.get(user.get("role", "viewer"), 0)
            need_level = ROLES.get(minimum_role, 99)
            if user_level < need_level:
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"error": "Forbidden", "required": minimum_role}), 403
                return render_template("403.html"), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Auth Blueprint routes ─────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip       = request.remote_addr
        user     = verify_credentials(username, password)
        _log_login(username, bool(user), ip)

        if user:
            session.permanent = True
            session["user"] = {
                "id":       user["id"],
                "username": user["username"],
                "role":     user["role"],
            }
            log.info("Login OK: %s (%s) from %s", username, user["role"], ip)
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)

        log.warning("Login FAILED: %s from %s", username, ip)
        flash("Invalid credentials", "error")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    username = session.get("user", {}).get("username", "?")
    session.clear()
    log.info("Logout: %s", username)
    return redirect(url_for("auth.login"))


@auth_bp.route("/me")
def me():
    user = get_current_user()
    if not user:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "username": user.get("username"),
        "role":     user.get("role"),
    })


@auth_bp.route("/token/rotate", methods=["POST"])
@require_login
def rotate_my_token():
    user = get_current_user()
    return jsonify(rotate_token(user["username"]))
