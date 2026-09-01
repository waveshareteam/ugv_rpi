# Web UI

Browser control page for **ugv_rpi** (`app.py`). Open it from a phone or PC on the same network — no extra app.

Typical URL: `http://<robot-ip>:5000`

This is the Flask control page on **port 5000**. 

Install and first-time network setup: [README](../README.md).

---

## Open the page

| Network | What to type |
|---------|----------------|
| STA (robot joined your WiFi) | IP on the OLED **W** line, then `:5000` — e.g. `192.168.10.50:5000` |
| AP (hotspot `AccessPopup` / password `1234567890`) | `192.168.50.5:5000` |
| JupyterLab | same IP, port **8888** |
| AccessPopup web (WiFi helper) | same IP, port **8052** |

The OLED **F/J** line is a reminder: **F** = Flask web UI (`5000`), **J** = JupyterLab (`8888`).

Use a current desktop or mobile browser. Keep the tab in the foreground if you use a USB gamepad.

Before driving, set the chassis and module once in the command box (saved to `config.yaml`):

```text
s 22
```

| Digit | Meaning | Values |
|-------|---------|--------|
| First | Chassis | `1` RaspRover · `2` UGV Rover (also **WAVE ROVER**, **UGV02**) · `3` UGV Beast (also **UGV01**) |
| Second | Module | `0` none · `1` RoArm-M2 · `2` Camera PT · `3` RoArm-M3 |

Example: `s 22` = UGV Rover + pan-tilt. Wrong module type makes the on-screen sticks control the wrong thing. The first digit sets the speed profile and name in this app; pick the closest chassis if your product is WAVE ROVER / UGV01 / UGV02.

---

## First 5 minutes

1. Join the same WiFi as the robot (or the `AccessPopup` hotspot). Open `http://<IP>:5000`.
2. In **Enter Command**, send `s XY` for your chassis and module, then reload the page.
3. Wait for the camera. CPU / RAM / voltage ticking on the overlay means the backend is up. A black video for a while is normal; wait, then refresh if it stays black (sometimes one or two minutes on first open).
4. Drive with the **nine-way pad** under the video. Start on **Slow**.
5. Then use the right stick and the vertical slider for the pan-tilt or arm. Those sticks do **not** drive the chassis.

On a phone, avoid a long-press on the sticks or the nine-way pad (the OS “Copy” menu). The chassis **Slow / Middle / Fast** buttons do not change stick speed.

---

## Page layout

Left / video column:

- Live camera (WebRTC), with CPU / RAM / battery / RSSI / FPS / temperature / zoom / media size overlaid
- Tilt scale (numbers **90 … −30**) plus a separate vertical slider (**Y:** or **G:** under the bar)
- Two virtual sticks (right stick always; left stick only with a robot arm)
- Nine-way drive pad and **FUNC**
- Video toolbar (play, mute, fullscreen, PiP, record, capture, zoom)
- Audio drop zone and **Enter Command** box

Right column:

- Speed, gimbal steady, CV, lights
- Links to JupyterLab and AccessPopup
- Photo / video lists. **Setting Page** (bus-servo init) only on Camera PT (`s X2`)

---

## Drive the chassis

Three equivalent inputs — **one at a time** is enough:

1. **Nine-way pad** under the video — hold a direction; release to stop.
2. **Arrow keys** on a keyboard (page must not be focused in the command box).
3. **Gamepad D-pad** (see [Gamepad](#gamepad)).

Forward / back is `x`; left / right is in-place turn `z`. The analog sticks on the page do **not** drive the base — they move the pan-tilt or arm.

**Speed Ctrl:** **Slow** / **Middle** / **Fast** (about 30% / 66% / 100% of the configured max). That is chassis speed only. Start on Slow in a tight space.

Release keys or the pad to stop. If the robot keeps creeping, click the page once (so the command box is not focused) and tap an arrow then release, or refresh the tab.

---

## Camera, pan-tilt, and arm

What the sticks and slider do depends on the second digit of `s XY`.

**Sticks (pan-tilt and arm):** hold the stick off-center to move at a steady rate. Release to **keep** the current pose (it does not snap back). A small region around the center is a dead zone. Hold in that dead zone (or **Ahead**, or keyboard `0`) to look forward / home.

**Vertical slider** on the left of the video: drag the cyan bar. The **Y:** / **G:** label sits under the bar. The numbered scale next to it (**90, 60, 30, 0, −30**) is the tilt readout, not a second slider.

### Camera PT (`module_type` 2)

- **Right stick** — pan (X) and tilt (Y).
- **Vertical slider** — tilt, labeled **Y:**.
- **PT Steady/Ahead** — **ON** holds the camera level while the chassis pitches; **OFF** turns that off; **Ahead** recenters.

There is no left stick on a PT-only robot. The overlay buttons **Joint / Pose** and **Increase / Decrease** are **arm-only**; they stay hidden on a pan-tilt.

### Robot arm (`module_type` 1 or 3)

Two buttons on the video overlay (not shown on a pan-tilt):

| Button | Effect |
|--------|--------|
| **Joint** / **Pose** | Switches what the two sticks mean |
| **Increase** / **Decrease** | Sign for “press and hold center of a stick” (extra axis) |

| Mode | Left stick | Right stick | Hold center of left stick | Hold center of right stick |
|------|------------|-------------|---------------------------|----------------------------|
| **Pose** | End-effector X / Y | Pitch / roll | Z | Look-ahead / home pose |
| **Joint** | Base / shoulder | Roll / wrist | Elbow | Look-ahead / home pose |

The vertical slider is gripper opening (**G:**). **RoArm View** (iframe on the right) is a 3D preview, not a second controller. It needs the optional `roarm_web_app` service on port **3000** (`autorun.sh` can install it). If that service is not running, the preview is blank.

`s XY` does not choose the gripper model. `gripper_type` in `config.yaml` only switches the 3D preview: `0` → `roarm_m2`, any other value → `roarm_m2_ga` (M2 with gripper). Edit the yaml and reload the page.

**Ahead** (and stick-center hold, and `0`) sends the arm to a folded “look forward” pose and opens the gripper.

---

## Video toolbar

| Control | Action |
|---------|--------|
| Play / pause | Pause or resume the WebRTC player (does not stop the robot) |
| Speaker | Mute / unmute the **robot microphone** (PCM over Socket.IO). Starts muted. This is not the WebRTC video soundtrack |
| Fullscreen | Expand the video |
| PiP | Picture-in-picture |
| **Record** | Start / stop saving a clip |
| Capture (camera icon) | Still photo |
| Zoom | Cycle **1x → 2x → 4x** |
| **WebRTC** | Stream label (resolution items may be unused) |

Stills and clips show in **Photo Gallery** and **Video Files**, and on the full pages `html/photo.html` / `html/video.html`.

---

## Computer vision

These groups are **radio groups**, not toggles: click a mode to select it. Clicking the highlighted button again does **not** turn it off. Use **None** under **Simple Detection Type** (and **None** under **Simple Detection Reaction** if you need to stop capture/record-on-detect).

Use **one** detection type at a time. **Advance CV Funcs** and **MediaPipe Funcs** have no None in that row — go back to **Simple Detection Type → None** when you are done.

**Simple Detection Type**

| Button | What it does |
|--------|----------------|
| **None** | Idle |
| **Movtion** | Motion in the frame |
| **Faces** | OpenCV face detect |

**Simple Detection Reaction** — what happens when the selected detector fires:

| Button | What it does |
|--------|----------------|
| **None** | Overlay only |
| **Capture** | Take a photo |
| **Record** | Start recording |

**Advance CV Ctrl**

| Button | What it does |
|--------|----------------|
| **LOCK** | Vision may track in the picture; chassis does not follow |
| **UNLOCK** | Tracking can also move the base — clear space first |
| **AUTODRIVE** | Line following — the robot will drive on its own |

**Advance CV Funcs / MediaPipe Funcs:** **OBJECTS**, **COLOR**, **HAND GS**, **MP FACE**, **MP POSE**. These are heavier on the Pi.

If the chassis starts moving while you only wanted a box on the video, hit **LOCK** or **None**.

---

## Lights, audio, command box

**Head Light Ctrl:** **OFF** / **AUTO** / **ON**. **FUNC** on the drive pad (and gamepad **R2** on a PT robot) toggles the head lamp.

**Base Light Ctrl:** **BASE OFF** / **BASE ON**.

**Audio:** drop `.mp3` / `.wav` on **Drop audio files here!**. Play from the list; the pause control stops playback.

**Enter Command** + **Send** talks to the same command parser as the Jupyter tutorials. While this box is focused, keyboard driving is disabled.

Common commands:

```text
s 22
audio -s hello
audio -v 0.8
```

| Command | Role |
|---------|------|
| `s XY` | Chassis + module (see [Open the page](#open-the-page)) |
| `audio -s <text>` | Speak |
| `audio -v <0-1>` | Volume (`1` = max; values above `1` are clamped to max) |
| `base -c <json>` | Raw JSON to the ESP32 base (no spaces inside the JSON) |

More commands: JupyterLab notebooks **28** (custom CLI) and **29** (web command line):

- English: `tutorials/tutorial_en/28 Custom Command Line Functionality.ipynb`, `tutorials/tutorial_en/29 Web Command Line Application.ipynb`
- Chinese: `tutorials/tutorial_cn/28 自定义命令行功能.ipynb`, `tutorials/tutorial_cn/29 WEB 命令行应用.ipynb`

---

## Keyboard

Click empty space on the page first so the command box is not focused.

| Keys | Action |
|------|--------|
| `↑` `↓` `←` `→` | Drive (forward / back / turn). Release to stop |
| `S` | Invert the increment direction for the keys below |
| `0` | Look ahead / home pose |
| `L` | Head-light PWM (hold; `S` reverses) |
| `X` `Y` | Pan-tilt, or arm pose X/Y |
| `Z` `R` `P` | Arm pose Z / roll / pitch (arm only) |
| `1`–`5` | Arm joints: base, shoulder, elbow, wrist, roll |
| `G` | Gripper (slider follows) |

Arrow keys repeat while held. Do not type these while editing the command box.

---

## Gamepad

There are **two** independent gamepad paths. Use **one** at a time — both write chassis commands, so using both (or plugging two dongles, one in the Pi and one in the PC) can make the robot fight itself.

| Where the USB dongle is | What handles it | Needs the web page? |
|-------------------------|-----------------|---------------------|
| **Computer** that has the control page open | This page (browser Gamepad API) | Yes — keep the tab visible |
| **Raspberry Pi** | `joy_ctrl.py` inside `app.py` | No |

If the pad is in the Pi, this page will not see it. If it is in the PC, the Pi-side driver will not see it.

### Browser gamepad (dongle in the PC)

Leave that tab in the foreground (do not let the browser sleep the tab). Click the page once so it can read the Gamepad API.

Standard mapping (Xbox-style layout):

| Input | Action |
|-------|--------|
| D-pad | Drive (same as the nine-way pad). Analog left stick does **not** drive the base |
| **L1** / **L2** | Slower / faster speed step |
| **START** | Toggle record |
| **SELECT** / Back | Photo |
| Click **right stick** | Look ahead |
| **Y** / **X** | Head-light PWM up / down |

**Pan-tilt**

| Input | Action |
|-------|--------|
| Right stick | Pan / tilt |
| **R2** | Toggle head lamp (**FUNC**) |

**Arm**

| Input | Action |
|-------|--------|
| **R1** | Toggle Joint / Pose |
| Left stick | Pose X/Y or base/shoulder |
| Right stick | Pitch/roll or roll/wrist |
| Click left stick | Pose Z or elbow (**R2** held with that click reverses) |
| **A** / **B** | Gripper |

If nothing happens on this page: the dongle is probably in the **Pi** (use that path, or move it to the PC), or the tab is not focused.

### Onboard gamepad (dongle in the Raspberry Pi)

`app.py` starts `joy_ctrl.py` automatically. Drive, lights, pan-tilt, and arm work without the browser. Mapping is Xbox-style (pygame); unknown pads fall back to the Xbox 360 layout. This path does **not** follow the table above one-for-one (for example D-pad/hat vs analog).

Do not leave a pad in the Pi while also using the browser gamepad.

---

## Other pages

| Link | Use |
|------|-----|
| **JupyterLab** | Tutorials and a terminal (`:8888`) |
| **AccessPopup** | WiFi / AP helper (`:8052`) |
| **View Photo Gallery Page** / **View Video Files Page** | Browse and delete media |
| **Setting Page** | First-time bus-servo ID and middle position for the pan-tilt. Shown on the home page only when the module is Camera PT (`s X2`). Direct URL still opens a notice if the module is not PT. |

Follow the numbered steps on the Setting Page. If both servos were set to ID 2 by mistake, use **Set Tilt ID** and start over.

---

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| Page loads, no video | Wait; overlay numbers ticking means the app is up. Refresh if it stays black. Confirm `app.py` is running and MediaMTX is up (`http://<IP>:8889/cam/`) |
| Overlay stuck at 0 | Backend / Socket.IO not connected — restart the main program, then refresh |
| Sticks do not match the hardware | Send `s XY` for your chassis and module, then reload |
| No **Pose** / **Increase** on a pan-tilt | Expected — those buttons are arm-only |
| Keyboard does nothing | Click outside **Enter Command** |
| Gamepad does nothing | For **this page**: dongle in the **PC**, tab in the foreground, click the page once. A pad in the **Pi** is the onboard `joy_ctrl` path — the page will not see it |
| Robot jerks / two inputs at once | Unplug one gamepad path. Do not use a Pi-side pad and a browser pad together |
| Robot keeps driving | Release pad/keys; **None** on CV; **LOCK** if tracking was unlocked |
| Phone shows Copy / a menu on a stick | Short tap-and-drag only; do not long-press the stick or nine-way pad |
| Cannot open `:5000` | Same WiFi/hotspot as the robot; use the OLED **W** IP; AP default is `192.168.50.5` |
