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

## Self-drive subsystem structure (Sep 11 restructure)
The planner used to be one 630-line `self_drive.py` holding memory, detection
handling, pursuit and odometry. It is now six modules, each understandable
alone. Read this before changing anything in the chain:

| module | owns |
|---|---|
| `perception.py` | the robot-frame conventions — LIDAR `+180°` offset, camera bearing sign — plus pure scan helpers (`sector_min`, `turn_bias`, `arc_clearance`) and object-label matching |
| `robot_state.py` | reading live sensors: `LidarScan` (applies the angle fix **once**, at the boundary) and ESP32 wheel odometry |
| `spatial_memory.py` | the learned occupancy grid + object memory + `surroundings.json` (version 2; v1 maps were rotated 180° and are refused) |
| `detection_source.py` | which detections the planner sees: the live COCO stream plus a throttled `detect_world()` open-vocabulary top-up |
| `target_pursuit.py` | the target's state (`set`/`clear`/`observe`/`seen`/`halt`) and the pursuit rules (arrive, aim, veto, sweep) |
| `self_drive.py` | the thread lifecycle (`warm`/`enable`/`disable`/`pursue`), the tick, the heading choice + veto application, and the `status()` payload |

Rules that keep it that way:
- **Angles**: only `robot_state.LidarScan.read()` converts raw angles; everything
downstream (memory, planner, avoider helpers) works in the robot frame
(0 = forward, + = left). Never subtract `pi` anywhere else — that duplication is
what produced the 180°-inverted map and the inverted camera bearing.
- **Callers use transitions, not flag surgery**: `enable()` / `disable()` /
`pursue(name)` / `clear_target()` / `warm()`. `disable()` is pause + drop target
+ stop thread; the routes, the CLI, Lance and the boot path all call the same
methods, so "self-drive off" cannot drift between channels.
- **Memory is read through the planner's shortcuts** (`save_memory`,
`load_memory`, `clear_memory`) or `planner.memory` for reads.
- **Changing heading policy** (weights, veto, aim) lands in
`SelfDriver._choose_heading`; changing what a target *is* lands in
`target_pursuit.py`.

### The arrival stop, and the three rules it depends on
Three things had to agree before "drive to the chair" could end in a stop at
the chair. Each has exactly one home; change them there.

1. **The planner's `halt` outranks the avoider's forward motion** —
`LidarAvoider._decide` (app.py) checks `_planner_halted()` *before* the EVADE,
SLOW, post-evade-curve and CRUISE branches and reports the new `HOLD` state.
Only the `<250 mm` emergency reverse is exempt: it is the only way out of a
jam, and suppressing it would wedge the robot. Before this, `halt` was honored
in CRUISE alone, so the 450-700 mm band drove the robot on at 20-35% speed
*while the planner was saying stop*. `selfdrive_selftest.py` asserts the
ordering from app.py's syntax tree (it cannot be imported off the Pi).
2. **The arrival range is the object's own bearing** —
`target_pursuit.Target.observe(dets, scan)` measures the nearest LIDAR return
within `TARGET_CONE_DEG` (10°) of the detection's bearing, and treats *no
return* down that bearing as `OBJ_RANGE_MAX`. It deliberately does not fall
back to the forward cone: that cone measured whatever was nearest in front — on
this floor a wall 0.5 m away across +40°..+150° — so arrival used to fire at
the wall's distance and the robot stopped short. Collision avoidance is the
avoider's front cone, not this estimate.
3. **"drive to the X" is read, not guessed** — `lance.parse_pursuit_intent()`
routes verb + preposition + object straight to `_approach`, before the language
model is consulted. The model's own prompt advertises "drive towards the
chair" and it answered that phrase with a two-second forward drive, so the one
thing the user asked for was the one thing that did not happen. Extend the
verb/preposition lists there, not the prompt; anything the parser declines
still goes to the model. Not-objects (directions, measures) and clause breaks
("…the bin **and then** forward") are excluded on purpose.

4. **Arrival is sticky, and that lives in one place** —
`target_pursuit.PursuitPolicy.arrival_hold(target)` is the only arrival
question the planner asks. It returns True for the tick that first reaches the
object *and* for every tick after, including ones where the object has left the
camera view — which is exactly what happens once the robot is on top of it.
Deciding arrival from scratch each tick (`has_arrived`, removed) released halt
the moment the object left the frame, so the robot arrived, dropped `halt`, and
drove off again under the `looking for … — sweeping` path. It still releases
halt when the object is seen again beyond `arrive_m`, so a target that moves
away is re-approached rather than frozen forever. `Target.release_halt`
(unused) was deleted with it. Live proof: `arrived`, `halt=true`,
`avoidance_state=HOLD`, wheel odometry frozen for 20 s with `seen=false`.

Measured floor geometry at the last verification (robot stationary): straight
ahead open to 1439 mm; a wall 495-760 mm across +40°..+150°; ~1150 mm to the
right. That left wall is what held the old front-cone reading at ~580 mm, which
is also why the SLOW band was the state that mattered.

Note on `/send_command`: it is the **CLI**, not a JSON endpoint. A raw JSON POST
to it is silently dropped (`cmdline_ctrl` wants `command=base -c {"T":1,…}` in a
form field), which is how a previous pass concluded the chassis could not move.
With the correct form the wheels turn: a 4 s forward command moved the front cone
459 -> 179 mm and advanced the ESP32 odometry in the commanded direction.
