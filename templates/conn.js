// Connection health banner + camera-ready state.
//
// One module owns "is the robot reachable" so the rest of the page can trust it:
//  - /ctrl + /json socket disconnects  -> banner "Reconnecting..." (socket.io
//    reconnects on its own; we only surface the state)
//  - /video_feed <img> error/stop      -> banner persists + video area gets the
//    retry affordance (no camera or stream dead)
//  - /camera_status polling            -> tells the video area whether the
//    capture thread actually has frames ("No camera - plug one in" vs "robot
//    unreachable")

(function () {
    'use strict';

    var banner = document.getElementById('conn_banner');
    if (!banner) return;                        // page without the banner

    var msgEl   = document.getElementById('conn_msg');
    var retryEl = document.getElementById('camera_retry_btn');
    var videoImg = document.querySelector('.video img');
    var camState = 'unknown';                   // unknown | ok | nocam | unreachable
    var cameraPollId = null;

    function setBanner(kind, text) {
        banner.classList.remove('conn_ok', 'conn_warn', 'conn_err', 'conn_hidden');
        if (kind === 'hidden') { banner.classList.add('conn_hidden'); return; }
        banner.classList.add(kind === 'ok' ? 'conn_ok' : kind === 'warn' ? 'conn_warn' : 'conn_err');
        if (msgEl) msgEl.textContent = text;
    }

    function showRetry(show) {
        if (retryEl) retryEl.style.display = show ? 'inline-block' : 'none';
    }

    function setVideoOverlay(text) {
        var v = document.getElementById('video_state');
        if (v) v.textContent = text;
        if (v) v.style.display = text ? 'block' : 'none';
    }

    // ---- camera / stream state (poll while the page is open) ----
    function pollCamera() {
        $.get('/camera_status')
            .done(function (d) {
                var reachable = true;
                camState = d.ready ? 'ok' : 'nocam';
                if (socketHealthy()) {
                    if (camState === 'ok') {
                        setBanner('hidden', '');
                        setVideoOverlay('');
                        showRetry(false);
                    } else {
                        setBanner('warn', 'Robot is up, but no camera is detected. Plug one in, then press Retry.');
                        setVideoOverlay('No camera detected - plug in a camera, then press Retry');
                        showRetry(true);
                    }
                }
                scheduleNext(3000);
            })
            .fail(function () {
                camState = 'unreachable';
                scheduleNext(5000);
            });
    }
    function scheduleNext(ms) { cameraPollId = setTimeout(pollCamera, ms); }

    // ---- socket health (socket.io auto-reconnects; we surface it) ----
    function socketHealthy() {
        return (typeof socket !== 'undefined') && socket && socket.connected;
    }
    function refreshConnBanner() {
        if (socketHealthy()) {
            if (camState === 'unknown') setBanner('warn', 'Connected - checking camera...');
            // camera poll upgrades/worsens the message
        } else {
            setBanner('err', 'Connection lost - reconnecting to the robot...');
            setVideoOverlay('Robot unreachable - check power and WiFi');
            showRetry(false);
        }
    }
    if (typeof socket !== 'undefined' && socket) {
        socket.on('disconnect', refreshConnBanner);
        socket.on('connect', refreshConnBanner);
        socket.on('reconnect', refreshConnBanner);
    }
    if (typeof socketJson !== 'undefined' && socketJson) {
        socketJson.on('disconnect', refreshConnBanner);
        socketJson.on('connect', refreshConnBanner);
    }

    // ---- video <img> death (stream 404s after a server restart, etc.) ----
    if (videoImg) {
        videoImg.addEventListener('error', function () {
            setVideoOverlay('Video stream interrupted - retrying...');
        });
    }

    // ---- Retry button: re-arm camera detection server-side, reload stream ----
    if (retryEl) {
        retryEl.addEventListener('click', function () {
            retryEl.disabled = true;
            setVideoOverlay('Retrying camera detection...');
            $.post('/retry_camera')
                .done(function () {
                    // give the capture thread a moment, then re-poll
                    setTimeout(function () {
                        retryEl.disabled = false;
                        camState = 'unknown';
                        if (videoImg) { var src = videoImg.src; videoImg.src = src; }
                    }, 1500);
                })
                .fail(function () {
                    retryEl.disabled = false;
                    setVideoOverlay('Retry failed - is the robot still up?');
                });
        });
    }

    setBanner('warn', 'Connecting to robot...');
    pollCamera();
})();
