/**
 * ugv_hud.js — UGV HUD enhancements
 * Loaded AFTER main.js. Adds: toasts, fullscreen, tabs,
 * autonomous mode controls, ZeroTier panel, event log,
 * HUD mode indicator, SVG angle gauges, speed bar.
 *
 * Exposes on window: ugvToast(msg, type, ms), ugvStop()
 */

(function () {
  "use strict";

  /* ─── Config ──────────────────────────────────────────────────── */
  const API   = "";          // empty = same origin
  const POLL_ROUTINE_MS = 2500;
  const POLL_EVENTS_MS  = 8000;
  const POLL_ZT_MS      = 15000;

  /* ─── Toast system ────────────────────────────────────────────── */
  const TOAST_ICONS = { ok:"✅", warn:"⚠️", error:"❌", info:"ℹ️" };

  window.ugvToast = function (msg, type = "ok", duration = 3500) {
    const wrap = document.getElementById("ugv-toasts");
    if (!wrap) return;
    const t = document.createElement("div");
    t.className = `ugv-toast t-${type}`;
    t.innerHTML =
      `<span class="ugv-toast-icon">${TOAST_ICONS[type] || "•"}</span>` +
      `<span class="ugv-toast-msg">${msg}</span>`;
    wrap.prepend(t);
    setTimeout(() => {
      t.classList.add("toast-out");
      setTimeout(() => t.remove(), 400);
    }, duration);
  };

  /* ─── Fullscreen ──────────────────────────────────────────────── */
  window.toggleFullscreen = function () {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      document.getElementById("fullscreen-btn").textContent = "⊡";
    } else {
      document.exitFullscreen();
      document.getElementById("fullscreen-btn").textContent = "⛶";
    }
  };
  document.addEventListener("fullscreenchange", () => {
    const btn = document.getElementById("fullscreen-btn");
    if (btn) btn.textContent = document.fullscreenElement ? "⊡" : "⛶";
  });

  /* ─── Tab switching ───────────────────────────────────────────── */
  window.ugvSwitchTab = function (name) {
    document.querySelectorAll(".ugv-tab-btn").forEach(b => {
      b.classList.toggle("ugv-tab-active", b.dataset.tab === name);
    });
    document.querySelectorAll(".ugv-tab-panel").forEach(p => {
      p.classList.toggle("ugv-tab-show", p.id === "ugv-tab-" + name);
    });
    if (name === "events")  refreshEvents();
    if (name === "network") refreshZeroTier();
  };

  /* ─── HUD mode indicator ──────────────────────────────────────── */
  const MODE_CLASS = {
    idle:     "mode-manual",
    running:  "mode-auto",
    sentinel: "mode-sentinel",
    follow:   "mode-follow",
  };

  function setHudMode(label, cssClass) {
    const el = document.getElementById("ugv-mode-hud");
    if (!el) return;
    el.textContent = label;
    el.className   = cssClass || "mode-manual";
  }

  /* ─── SVG circular gauge helper ───────────────────────────────── */
  function buildGauge(containerId, minVal, maxVal, label) {
    const C = document.getElementById(containerId);
    if (!C) return null;
    const R = 16, CX = 20, CY = 20, SIZE = 40;
    const CIRC = 2 * Math.PI * R;
    C.innerHTML =
      `<div class="hud-gauge-label">${label}</div>` +
      `<svg class="hud-gauge-svg" width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}">` +
        `<circle class="gauge-track" cx="${CX}" cy="${CY}" r="${R}" />` +
        `<circle class="gauge-fill"  cx="${CX}" cy="${CY}" r="${R}"` +
          ` stroke-dasharray="${CIRC}" stroke-dashoffset="${CIRC}"` +
          ` transform="rotate(-90 ${CX} ${CY})" id="${containerId}-arc"/>` +
      `</svg>` +
      `<div class="hud-gauge-val" id="${containerId}-val">0</div>`;
    return {
      update(val) {
        const norm   = Math.max(0, Math.min(1, (val - minVal) / (maxVal - minVal)));
        const offset = CIRC * (1 - norm);
        const arc    = document.getElementById(containerId + "-arc");
        const valEl  = document.getElementById(containerId + "-val");
        if (arc)   { arc.style.strokeDashoffset = offset;
                     arc.className = "gauge-fill" +
                       (norm > 0.85 ? " crit" : norm > 0.65 ? " warn" : ""); }
        if (valEl) valEl.textContent = Math.round(val) + "°";
      }
    };
  }

  /* ─── Speed bar ───────────────────────────────────────────────── */
  function updateSpeedBar(pct) {
    const fill = document.getElementById("hud-speed-fill");
    if (!fill) return;
    fill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    fill.style.background =
      pct > 75 ? "var(--hud-red)" : pct > 45 ? "var(--hud-orange)" : "var(--hud-green)";
  }

  /* ─── Emergency stop ──────────────────────────────────────────── */
  window.ugvStop = function () {
    fetch(API + "/api/ugv/stop", { method: "POST" })
      .then(r => r.json())
      .then(() => { ugvToast("⛔ Emergency stop sent", "warn", 3000); pollRoutine(); })
      .catch(() => ugvToast("Stop request failed", "error"));
  };

  /* ─── Routine API helpers ─────────────────────────────────────── */
  function apiPost(path, body) {
    return fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(r => r.json());
  }

  function startRoutine(path, body, label) {
    apiPost(path, body)
      .then(d => {
        if (d.status === "ok") {
          ugvToast(`${label} started`, "ok");
          pollRoutine();
        } else if (d.status === "requires_confirm") {
          ugvToast("Confirm required — check console", "warn");
        } else {
          ugvToast(d.message || "Error", "error");
        }
      })
      .catch(() => ugvToast("API unreachable", "error"));
  }

  /* ─── Routine status polling ──────────────────────────────────── */
  let _routineTimer = null;
  const _ROUTINE_LABELS = {
    patrol:   "🚶 PATROL",
    guard:    "🛡 GUARD",
    watch:    "👁 WATCH",
    search:   "🔍 SEARCH",
    sentinel: "🔴 SENTINEL",
    follow:   "🎯 FOLLOW",
    idle:     "IDLE",
  };

  function pollRoutine() {
    fetch(API + "/api/ugv/routine/status")
      .then(r => r.json())
      .then(d => {
        const running = d.running;
        const state   = (d.params && d.params.mode) || d.state || "idle";
        const dot     = document.getElementById("routine-status-dot");
        const name    = document.getElementById("routine-status-name");
        const stopBtn = document.getElementById("routine-stop-btn");

        if (dot)    dot.className   = running ? "active" : "";
        if (name)   name.textContent = running
          ? (_ROUTINE_LABELS[state] || state.toUpperCase())
          : "IDLE";
        if (stopBtn) stopBtn.classList.toggle("visible", running);

        // HUD mode badge
        const label = _ROUTINE_LABELS[state] || state.toUpperCase();
        if (running) {
          const cls = state === "sentinel" ? "mode-sentinel"
                    : state === "follow"   ? "mode-follow"
                    : "mode-auto";
          setHudMode(label.replace(/[^\w ]/g, "").trim(), cls);
        } else {
          setHudMode("MANUAL", "mode-manual");
        }
        // V2 topbar badge
        v2UpdateRoutineBadge(running, label.replace(/[^\w ]/g, "").trim());
      })
      .catch(() => {});
  }

  function startRoutinePolling() {
    pollRoutine();
    if (_routineTimer) clearInterval(_routineTimer);
    _routineTimer = setInterval(pollRoutine, POLL_ROUTINE_MS);
  }

  /* ─── Event log ───────────────────────────────────────────────── */
  const WARN_EV = ["abort", "error", "low_battery", "overheating", "emergency"];
  const ERR_EV  = ["error", "emergency_stop"];

  function refreshEvents() {
    fetch(API + "/api/ugv/cv/events?limit=40")
      .then(r => r.json())
      .then(d => {
        const ul = document.getElementById("ugv-event-log");
        if (!ul) return;
        const events = (d.events || []).slice().reverse();
        ul.innerHTML = events.map(e => {
          const time    = (e.ts || "").split("T")[1] || "";
          const type    = e.type || "";
          const detail  = e.details ? JSON.stringify(e.details).replace(/[{}'"]/g,"") : "";
          const isWarn  = WARN_EV.some(w => type.includes(w));
          const isErr   = ERR_EV.some(w => type.includes(w));
          const cls     = isErr ? "ev-err" : isWarn ? "ev-warn" : "";
          return `<li><span class="ev-time">${time}</span>` +
                 `<span class="ev-type ${cls}">${type}</span>` +
                 `<span class="ev-detail">${detail}</span></li>`;
        }).join("");
      })
      .catch(() => {});
  }

  /* ─── ZeroTier panel ──────────────────────────────────────────── */
  function refreshZeroTier() {
    const dot    = document.getElementById("zt-dot");
    const nodeEl = document.getElementById("zt-node-id");
    const verEl  = document.getElementById("zt-version");
    const listEl = document.getElementById("zt-networks-list");
    if (!dot) return;

    fetch(API + "/zt/status")
      .then(r => r.json())
      .then(d => {
        if (!d.ok) {
          dot.className = "offline";
          if (nodeEl) nodeEl.textContent = d.error || "Offline";
          if (listEl) listEl.innerHTML = "<li style='color:#666;font-size:11px'>ZeroTier not running</li>";
          return;
        }
        dot.className = "online";
        const info = d.info || {};
        if (nodeEl) nodeEl.textContent = info.node_id || "—";
        if (verEl)  verEl.textContent  = `v${info.version || "?"}  ${info.status || ""}`;

        const nets = d.networks || [];
        if (listEl) {
          if (!nets.length) {
            listEl.innerHTML = "<li style='color:#666;font-size:11px'>No networks joined</li>";
          } else {
            listEl.innerHTML = nets.map(n => {
              const ok  = (n.status || "").toUpperCase() === "OK" ||
                          (n.status || "").includes("ACCESS");
              const cls = ok ? "zt-net-ok" : "zt-net-err";
              return `<li>` +
                `<span class="zt-net-id">${n.id || n.nwid}</span>` +
                `<span class="zt-net-name">${n.name || ""}</span>` +
                `<span class="${cls}">${n.status}</span>` +
                `<button class="zt-btn danger" style="padding:2px 6px;font-size:10px" ` +
                  `onclick="ztLeave('${n.id||n.nwid}')">Leave</button>` +
              `</li>`;
            }).join("");
          }
        }
      })
      .catch(() => { if (dot) dot.className = "offline"; });
  }

  window.ztJoin = function () {
    const input = document.getElementById("zt-join-input");
    const nid = (input && input.value || "").trim();
    if (!nid) { ugvToast("Enter a network ID", "warn"); return; }
    apiPost("/zt/join", { network_id: nid })
      .then(d => {
        ugvToast(d.ok ? `Joined ${nid}` : (d.error || "Join failed"),
                 d.ok ? "ok" : "error");
        if (d.ok) { if (input) input.value = ""; setTimeout(refreshZeroTier, 2000); }
      })
      .catch(() => ugvToast("API error", "error"));
  };

  window.ztLeave = function (nid) {
    if (!confirm(`Leave ZeroTier network ${nid}?`)) return;
    apiPost("/zt/leave", { network_id: nid })
      .then(d => {
        ugvToast(d.ok ? `Left ${nid}` : (d.error || "Leave failed"),
                 d.ok ? "warn" : "error");
        if (d.ok) setTimeout(refreshZeroTier, 2000);
      })
      .catch(() => ugvToast("API error", "error"));
  };

  /* ─── Mode button handlers (called from HTML) ─────────────────── */
  window.ugvPatrol = function () {
    const dur = parseInt(document.getElementById("patrol-duration")?.value || "120");
    startRoutine("/api/ugv/routine/patrol",
      { duration: dur, speed: 0.25, scan_mode: "motion", lights: false },
      "🚶 Patrol");
  };

  window.ugvWatch = function (mode) {
    startRoutine("/api/ugv/routine/watch",
      { cv_mode: mode || "motion", scan_gimbal: true, scan_interval: 20 },
      "👁 Watch");
  };

  window.ugvSearch = function (target) {
    startRoutine("/api/ugv/routine/search",
      { target: target || "motion", take_photo: true },
      "🔍 Search");
  };

  window.ugvSentinel = function () {
    if (!confirm("Start SENTINEL mode?\nRobot will auto-record on detection. Confirm?")) return;
    startRoutine("/api/ugv/routine/sentinel",
      { cv_mode: "motion", scan_interval: 10, record_on_detect: true, confirm: true },
      "🔴 Sentinel");
  };

  window.ugvFollow = function () {
    if (!confirm("Start FOLLOW mode?\nRobot base will rotate to follow detected person. Confirm?")) return;
    startRoutine("/api/ugv/routine/follow",
      { cv_mode: "mp_pose", base_follow: true, confirm: true },
      "🎯 Follow");
  };

  window.ugvStopRoutine = function () {
    fetch(API + "/api/ugv/routine/stop", { method: "POST" })
      .then(() => { ugvToast("Routine stopped", "warn"); setTimeout(pollRoutine, 500); })
      .catch(() => ugvToast("Stop error", "error"));
  };

  /* ─── Gauge instances ─────────────────────────────────────────── */
  let panGauge = null, tiltGauge = null;

  /* ─── Hook into existing socket updates ──────────────────────── */
  // We patch in after main.js sets up socket.on('update')
  function hookSocketUpdate() {
    if (typeof socket === "undefined") {
      setTimeout(hookSocketUpdate, 500);
      return;
    }
    socket.on("update", function (data) {
      // pan / tilt gauges
      if (data[109] !== undefined && panGauge)  panGauge.update(data[109]);
      if (data[110] !== undefined && tiltGauge) tiltGauge.update(data[110]);

      // speed bar — use base_voltage as proxy; use custom speed_rate if exposed
      if (typeof speed_rate !== "undefined" && typeof max_rate !== "undefined") {
        updateSpeedBar(Math.round((speed_rate / max_rate) * 100));
      }
    });
  }

  /* ─── Intercept existing button clicks for toasts ─────────────── */
  function addToastHooks() {
    // Record button
    const recBtn = document.getElementById("record-btn");
    if (recBtn) {
      recBtn.addEventListener("click", function () {
        // isRecording is defined in main.js — check after click
        setTimeout(() => {
          if (typeof isRecording !== "undefined") {
            ugvToast(isRecording ? "🔴 Recording started" : "⏹ Recording stopped",
                     isRecording ? "ok" : "warn", 2500);
          }
        }, 100);
      });
    }

    // Observation: delegate to cmdSend wrapper
    const _orig = window.cmdSend;
    window.cmdSend = function (a, b, c) {
      if (typeof led_ton !== "undefined" && a === led_ton) ugvToast("💡 Head light ON", "info", 2000);
      if (typeof led_off !== "undefined" && a === led_off) ugvToast("💡 Head light OFF", "info", 2000);
      if (typeof base_on !== "undefined" && a === base_on) ugvToast("💡 Base light ON", "info", 2000);
      if (typeof base_of !== "undefined" && a === base_of) ugvToast("💡 Base light OFF","info", 2000);
      if (typeof cv_moti !== "undefined" && a === cv_moti) ugvToast("👁 Motion detection ON", "info", 2000);
      if (typeof cv_face !== "undefined" && a === cv_face) ugvToast("👤 Face detection ON", "info", 2000);
      if (typeof cv_none !== "undefined" && a === cv_none) ugvToast("Detection OFF", "info", 2000);
      if (typeof cv_auto !== "undefined" && a === cv_auto) ugvToast("🤖 Autodrive activated", "warn", 3000);
      return _orig && _orig(a, b, c);
    };
  }

  /* ─── V2 Theme system ────────────────────────────────────────────── */
  const THEMES = ["dark", "cyberpunk", "military", "terminal"];

  window.v2SetTheme = function (name) {
    if (!THEMES.includes(name)) return;

    // Swap CSS link
    const link = document.getElementById("v2-theme-css");
    if (link) link.href = `/themes/${name}.css`;

    // Swap body class
    document.body.className = document.body.className
      .replace(/\btheme-\S+/g, "").trim();
    document.body.classList.add("theme-" + name);

    // Update active button
    document.querySelectorAll(".v2-theme-btn").forEach(b => {
      b.classList.toggle("v2-theme-active", b.dataset.theme === name);
    });

    // Persist locally + to backend
    localStorage.setItem("ugv-theme", name);
    fetch("/api/v2/theme", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).catch(() => {});
    ugvToast(`Theme: ${name.toUpperCase()}`, "info", 1800);
  };

  function v2InitTheme() {
    const saved = localStorage.getItem("ugv-theme") || "dark";
    v2SetTheme(saved);
  }

  /* ─── V2 User info ────────────────────────────────────────────── */
  function v2LoadUser() {
    fetch("/auth/me")
      .then(r => r.json())
      .then(d => {
        const info     = document.getElementById("v2-user-info");
        const adminLnk = document.getElementById("v2-admin-link");
        const logoutLnk= document.getElementById("v2-logout-link");
        if (d.authenticated) {
          if (info)     info.textContent = `${d.username} (${d.role})`;
          if (logoutLnk) logoutLnk.style.display = "inline";
          if (adminLnk && d.role === "admin") adminLnk.style.display = "inline";
        }
      })
      .catch(() => {});
  }

  /* ─── V2 Routine badge in topbar ─────────────────────────────── */
  function v2UpdateRoutineBadge(running, label) {
    const badge = document.getElementById("v2-routine-badge");
    if (!badge) return;
    if (running) {
      badge.textContent  = `● ${label}`;
      badge.className    = "v2-badge v2-badge-running";
    } else {
      badge.textContent  = "● IDLE";
      badge.className    = "v2-badge v2-badge-idle";
    }
  }

  /* ─── Init ────────────────────────────────────────────────────── */
  function init() {
    // Gauges (containers injected into HUD in index.html)
    panGauge  = buildGauge("hud-pan-gauge",  -180, 180, "PAN");
    tiltGauge = buildGauge("hud-tilt-gauge",  -30,  90, "TILT");

    hookSocketUpdate();
    addToastHooks();

    // V2 init
    v2InitTheme();
    v2LoadUser();

    startRoutinePolling();

    // Open Controls tab by default
    ugvSwitchTab("controls");

    // Auto-poll ZeroTier status less frequently
    setInterval(refreshZeroTier, POLL_ZT_MS);
    setInterval(pollRoutine, POLL_ROUTINE_MS);
    setInterval(() => {
      const activeTab = document.querySelector(".ugv-tab-btn.ugv-tab-active");
      if (activeTab && activeTab.dataset.tab === "events") refreshEvents();
    }, POLL_EVENTS_MS);
  }

  // Wait for DOM + main.js to finish their init
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    setTimeout(init, 200);
  }
})();
