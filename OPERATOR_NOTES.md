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

## LIDAR D500 — RESOLVED to a wiring-quality issue (Sep 9, evening)
After the user re-plugged the sensor's USB adapter, the D500 now enumerates as its
own CP210x bridge (/dev/ttyUSB*, NOT ttyACM* — base_ctrl.py now prefers ttyUSB*).
Data DOES flow and the full pipeline works: revolutions parse, /lidar_points serves
real distances (0.28m close object, 1.6-1.7m walls), the radar fills in.
REMAINING DEFECT (hardware): the stream is ~98% corrupted — full revolutions land
only every ~2-12s instead of 10Hz, with only 12-24 valid points per scan (of ~400).
The wire carries high-entropy garbage at exactly 230400-line-utilization levels,
no valid frame headers for long stretches => classic half-seated ZH1.5T 4-pin
connector / mis-wired Tx-vs-PWM symptom. Re-seat the 4-pin cable firmly (or swap
it) and the radar should go dense and smooth instantly — no software change left
beyond what is already deployed.

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
