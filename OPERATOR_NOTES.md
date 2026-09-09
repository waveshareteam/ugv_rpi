# UGV Rover web UI — operator notes (Sep 2026)

## What is verified working (browser-driven against the live robot)
- Page load: telemetry live (CPU/RAM/voltage/RSSI/temp), zero console errors, all statics 200.
- D-pad: all 9 pads emit `T:1 {L,R}` frames with correct differential semantics
  (fwd `0.5/0.5`, spin `0.5/-0.5`, back `-0.5/-0.5`, release `0/0`), verified on the
  wire through the real socket.io connection.
- WASD: same drive path; keydown drives, keyup returns to `0/0`.
- Joystick: drags the gimbal (Pan/Tilt numbers move; gimbal frames sent).
- Robot-side safety clamp proven: an over-max `4.5/-4.5` emitted from the browser is
  clamped server-side to `0.5/-0.5` (verified in the previous pass via the deployed
  handler harness; the log line is `[drive] clamped ...` in ugv.log).
- LIDAR radar: live polling of /lidar_points + /lidar_status with the enable/disable
  toggle.
- Cameras (Sep 9): BOTH USB cameras verified producing frames — Microsoft LifeCam
  Studio (video2/3, used by the app, streams real JPEG via /video_feed) and Realtek
  "USB Camera" (video0/1, spare — captured a 614400-byte raw frame via v4l2-ctl).
  Only one camera is used by app.py at a time (first found, here video2).

## LIDAR D500 — RESOLVED: wrong baud, not hardware (Sep 9, late)
The D500 (STL-19P core) connected directly through its CP2102 adapter emits its
native stream at **921600 baud** — NOT the 230400 the vendor code (and every
earlier diagnosis) assumed. Reading a 921600 stream at 230400 yields exactly the
"saturated high-entropy garbage with zero 54 2C headers" signature that was
misdiagnosed as a half-seated ZH1.5T cable for most of the session.

Proof chain: multi-baud sweep on /dev/ttyUSB1 showed 639 `54 2C` headers in
30KB only at 921600; offline validation: 499/500 CRC8-valid 47-byte frames,
motor 3551 RPM, real distances 0-2098mm. The cable was fine all along.

FIX (base_ctrl.py): `_pick_lidar_baud(port)` returns 921600 for /dev/ttyUSB*
(direct CP2102 adapter) and 230400 for /dev/ttyACM* (ESP32 base-board relay).
DTR/RTS are asserted on open (the adapter drives the sensor's motor PWM via DTR;
asserted = motor runs at full speed; a floating PWM pin = internal 10Hz control).
Also: the ultrasonic `sensor_data_ser` no longer grabs the lidar's ttyUSB port.

VERIFIED LIVE: streaming true, ~1800 frames/s, full revolutions every ~0.1s,
/lidar_points serves 360/360 1-degree bins, WPF Radar tab reads "streaming
(1800 frames/s)", 356 pts, nearest 0.43m, avoidance ACTIVE and reacting.

KEY LESSON: never conclude hardware without sweeping the baud. Undersampling a
921600 stream at 230400 looks like saturated noise at the *right-looking* data
rate — the exact trap this session fell into.

## Operational gotchas learned the hard way
1. **WiFi flakiness is environmental.** The robot dropped off the network twice in one
   session (~1 min, then ~6+ min), with RSSI already reading `-32 dBm → unstable`
   beforehand. If the UI suddenly dead-ends, ping the robot before debugging software.
   The browser page will silently sit on a dead socket — that is the next UX gap to fix
   (reconnect banner + `socket.on('disconnect')` handling).
2. **Server prints are block-buffered under the cron autorun.** `print()` diagnostics
   (including the `[drive] clamped` receipt line) can sit unflushed in ugv.log. The
   deployed app.py now reconfigures stdout/stderr to line-buffered at startup, so the
   log is trustworthy for live debugging. Launching with `python -u` also works.
3. **Deploying**: back up first (`~/ugv_rpi/backup_20260908/` holds pass-1 and pass-2
   copies), scp app.py / templates, then restart:
   `kill $(pgrep -f 'ugv-env/bin/python /home/ws/ugv_rpi/app.py')` and relaunch via
   `setsid ... python -u app.py >> ~/ugv.log 2>&1 &` (or just reboot the robot —
   cron relaunches it via autorun.sh).

## Known-not-fixed (hardware or deferred)
- No camera detected (USB/CSI): video area shows the placeholder; feed returns
  "No camera detected" frames. Hardware.
- LIDAR serial opens but streams no data: hardware/power.
- cv_ctrl.py still contains a dead duplicate `execute_command` (second shadows first).

## PENDING DEPLOY (Sep 2026, latest pass)
The robot's WiFi degraded mid-session (66% packet loss; SSH cannot complete), so the
following files are **verified locally but not yet on the robot**:
- `app.py` — stdout/stderr line-buffering fix (log lines land instantly)
- `templates/index.html` — connection banner + video-state overlay + Retry button +
  button acknowledge states
- `templates/conn.js` — NEW: connection-health banner + camera-ready polling module
  (behavior-verified in a local browser harness; see below)

To finish the deploy when the link stabilizes, from the project root run:
    bash deploy.sh
It backs up current files to `~/ugv_rpi/backup_20260908/*.pass4`, uploads the three
files over one connection, and stops the app process (cron/autorun or a reboot then
relaunches it). It needs `/tmp/ap.sh` (the SSH askpass helper) to exist.

conn.js behavior verified in-browser (all transitions): no-camera → amber banner +
Retry visible; socket drop → red "reconnecting" + overlay; camera ready → banner
hidden; Retry → POST /retry_camera, button disables, stream re-polled.
