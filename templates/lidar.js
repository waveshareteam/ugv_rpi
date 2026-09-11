// LIDAR radar panel + avoidance toggle
// Uses the endpoints that already exist in app.py:
//   GET  /lidar_points   -> {angles:[rad], distances:[mm], hw_connected, use_lidar}
//   GET  /lidar_status   -> {avoidance_active, avoidance_state, use_lidar, hw_connected, status_msg}
//   POST /lidar_avoidance (form: enable=true|false)
//
// The LD19 lidar angles carry a +180° hardware offset (see base_ctrl.parse_lidar_frame),
// which app.py's /lidar_points serves raw.  We normalise to 0° = forward here so the
// display matches how the robot drives.  0° = up on the canvas, angles grow clockwise.

(function () {
    'use strict';

    var canvas  = document.getElementById('lidar_canvas');
    if (!canvas) return;                       // page without the radar panel
    var ctx     = canvas.getContext('2d');
    var stateEl = document.getElementById('lidar_avoid_state');
    var btn     = document.getElementById('lidar_toggle_btn');

    var RANGE_MM   = 1200;     // display range (millimetres)
    var pollPoints = 500;      // ms between /lidar_points polls
    var pollStatus = 2000;     // ms between /lidar_status polls

    var lastScan = null;       // {angles, distances, hw, use}
    var avoidActive = false;
    var lidarEnabled = false;
    var hwConnected = false;

    function setStatusLine(msg, color) {
        if (stateEl) {
            stateEl.textContent = msg;
            stateEl.style.color = color || '#4FF5C0';
        }
    }

    function centre() {
        return {
            cx: canvas.width / 2,
            cy: canvas.height * 0.92,          // robot sits near the bottom
            maxR: Math.min(canvas.width / 2, canvas.height * 0.92) * 0.95
        };
    }

    function drawGrid() {
        var c = centre();
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // range rings (upper half only)
        ctx.strokeStyle = 'rgba(79, 245, 192, 0.25)';
        ctx.fillStyle   = 'rgba(79, 245, 192, 0.6)';
        ctx.lineWidth   = 1;
        ctx.font        = '12px monospace';
        for (var r = 1; r <= 3; r++) {
            var rr = (c.maxR * r) / 3;
            ctx.beginPath();
            ctx.arc(c.cx, c.cy, rr, Math.PI, 2 * Math.PI);
            ctx.stroke();
            ctx.fillText((RANGE_MM * r / 3 / 1000).toFixed(1) + 'm', c.cx + 4, c.cy - rr - 4);
        }

        // forward marker
        ctx.strokeStyle = 'rgba(79, 245, 192, 0.5)';
        ctx.beginPath();
        ctx.moveTo(c.cx, c.cy);
        ctx.lineTo(c.cx, c.cy - c.maxR);
        ctx.stroke();

        // robot icon
        ctx.fillStyle = '#4FF5C0';
        ctx.fillRect(c.cx - 10, c.cy - 8, 20, 16);
    }

    function drawScan() {
        drawGrid();
        if (!lastScan || !lastScan.angles || lastScan.angles.length === 0) return;

        var c = centre();
        var angles    = lastScan.angles;
        var distances = lastScan.distances;

        ctx.fillStyle = 'rgba(255, 90, 90, 0.9)';
        for (var i = 0; i < angles.length; i++) {
            var a = angles[i] - Math.PI;                  // remove +180° hardware offset
            a = Math.atan2(Math.sin(a), Math.cos(a));     // normalise to [-π, π]
            if (Math.abs(a) > Math.PI / 2) continue;      // only draw the forward half

            var d = distances[i];
            if (d <= 0 || d > RANGE_MM) continue;

            // 0° = forward = up; positive angle = robot-left = canvas-left
            var px = c.cx + (d / RANGE_MM) * c.maxR * Math.sin(a);
            var py = c.cy - (d / RANGE_MM) * c.maxR * Math.cos(a);
            ctx.fillRect(px - 1, py - 1, 2, 2);
        }
    }

    function updateStatusUI() {
        if (!btn) return;
        if (!lidarEnabled) {
            setStatusLine('LIDAR: disabled in config', '#FF9393');
            btn.textContent = 'Enable Avoidance';
            return;
        }
        if (!hwConnected) {
            setStatusLine('LIDAR: hardware not found', '#FF9393');
            btn.textContent = 'Enable Avoidance';
            return;
        }
        if (avoidActive) {
            setStatusLine('Avoidance: ACTIVE', '#4FF5C0');
            btn.textContent = 'Disable Avoidance';
        } else {
            setStatusLine('Avoidance: paused (manual)', '#f5bd5f');
            btn.textContent = 'Enable Avoidance';
        }
    }

    function pollPointsFn() {
        $.get('/lidar_points')
            .done(function (data) {
                lastScan    = data;
                hwConnected = !!data.hw_connected;
                lidarEnabled = !!data.use_lidar;
                drawScan();
            })
            .fail(function () {
                lastScan = null;
            });
    }

    function pollStatusFn() {
        $.get('/lidar_status')
            .done(function (data) {
                avoidActive  = !!data.avoidance_active;
                hwConnected  = !!data.hw_connected;
                lidarEnabled = !!data.use_lidar;
                updateStatusUI();
            })
            .fail(function () {
                setStatusLine('LIDAR: server unreachable', '#FF9393');
            });
    }

    if (btn) {
        btn.addEventListener('click', function () {
            var enable = !avoidActive;
            $.post('/lidar_avoidance', { enable: enable ? 'true' : 'false' })
                .done(function (resp) {
                    avoidActive = !!resp.avoidance_active;
                    updateStatusUI();
                })
                .fail(function () {
                    setStatusLine('LIDAR: toggle failed', '#FF9393');
                });
        });
    }

    updateStatusUI();
    pollPointsFn();
    pollStatusFn();
    setInterval(pollPointsFn, pollPoints);
    setInterval(pollStatusFn, pollStatus);
})();
