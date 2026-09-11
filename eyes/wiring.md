# Robot Eyes — wiring 2× TFT displays (Arduino Uno ← Raspberry Pi 5)

This guide wires **two SPI TFT displays** (one per "eye") to an **Arduino Uno**, and the Uno to the **Raspberry Pi 5** over USB serial. The Pi runs YOLO person detection and streams the detected person's screen position to the Uno, which moves the pupils toward them — that's what makes the eyes "look" at people.

> Open **`schematic.svg`** for the picture version of this table.

---

## 1. Parts

| Part | Notes |
|---|---|
| 2× SPI TFT display | Most common: **ST7735 1.8″** (128×160) or **ILI9341 2.4″/2.8″** (240×320). Any SPI TFT (ST7789, ILI9488, SSD1331…) works — same wiring, different Arduino library init. |
| 1× Arduino Uno | The Uno's ATmega16U2/CH340 gives the Pi a serial port over USB. |
| 1× Raspberry Pi 5 | Runs `pi_eyes.py` (already has `ultralytics` + `pyserial` installed). |
| 8× male–female jumper wires | For display → Uno signal wires. |
| 1× USB A→B cable | Pi 5 USB-A port → Uno USB-B port (power + serial). |
| (optional) 1× 8-channel level shifter | `TXS0108E` (or 2× `74AHCT125`). Recommended if your display board is strictly 3.3 V logic (see §4). |

### How to confirm which TFT you have (check your photos/boards)
- **1.8″ board, red PCB, 8-pin header, tiny 1.8″ screen** → ST7735.
- **2.4″/2.8″ board, often black PCB with a micro-SD slot, larger screen** → ILI9341.
- Read the white silkscreen near the pins: it will say `VCC GND CS RESET DC SDA SCK LED` (ST7735) or `VCC GND CS RESET DC MOSI SCK BLK` (ILI9341). **Base your wiring on your board's own silkscreen** — the schematic uses the standard labels.

---

## 2. Wiring — Arduino Uno → both TFTs

The two displays are **fully independent** — **no signal wires are shared**. The left eye runs on the Uno's hardware SPI (SCK=D13, MOSI=D11) with its own CS/DC/RST; the right eye runs on a second, software-driven SPI port (SCLK=D4, MOSI=D3) with its own CS/DC/RST. Each display gets five dedicated signal wires. Only power (VCC/LED) and GND are common (you can separate those too if you prefer).

| Signal | Uno pin | TFT #1 (LEFT eye) | TFT #2 (RIGHT eye) |
|---|---|---|---|
| Power (logic) | **3.3 V** | `VCC` | `VCC` |
| Power (backlight) | **3.3 V** | `LED` | `LED` |
| Ground | **GND** | `GND` | `GND` |
| Clock | **D4** | `SCK` / `SCL` | — |
| Data | **D3** | `SDA` / `MOSI` | — |
| Clock | **D13** | — | `SCK` / `SCL` |
| Data | **D11** | — | `SDA` / `MOSI` |
| Chip select | **D10** | `CS` | — |
| Chip select | **D7** | — | `CS` |
| Data/command | **D9** | `DC` | — |
| Data/command | **D6** | — | `DC` |
| Reset | **D8** | `RESET` | — |
| Reset | **D5** | — | `RESET` |

Notes:
- **No shared signal wires** — each display is on its own port, so you never have to tie SCK/MOSI together.
- The left eye runs the firmware's **fast direct-port bit-bang SPI** (mosi=D3, sclk=D4) — a full 240×240 fill takes ~0.4 s instead of ~10 s with the Adafruit software-SPI path, so the eyes track gaze smoothly. The right eye uses hardware SPI (SCK=D13, MOSI=D11).
- `MISO` (D12) is **not connected** — the TFTs don't need it for writing.
- **VCC → 3.3 V** is the safe rule. If your board has an **onboard 3.3 V regulator** (common on ILI9341 2.4″ boards, identifiable by the small regulator + jumper near the header), you may feed `VCC` from the Uno's **5 V** instead — check the board's datasheet/silkscreen first.
- Backlight: tying `LED` to 3.3 V = full brightness. To dim, move `LED` to **D3** (PWM) on the left eye and **D2** on the right instead.

---

## 3. Wiring — Arduino Uno ↔ Raspberry Pi 5

| From | To | Purpose |
|---|---|---|
| Pi 5 **USB-A** port | Uno **USB-B** port | Serial link + power |

- The Uno enumerates as `/dev/ttyACM0` (16U2) or `/dev/ttyUSB0` (CH340 clones) at **115200 baud**.
- The Pi 5 USB-A port supplies ~600 mA — enough for the Uno + both TFTs' logic, but **both backlights at full brightness can draw close to that**. If the eyes flicker or the Uno browns out under load, power the Uno from a powered USB hub or a 5 V/2 A supply via its DC jack (never feed the Uno's 5V pin while USB is plugged in).

---

## 4. Level shifting (the one real gotcha)

The Uno's outputs are **5 V**; TFT controller chips (ST7735, ILI9341) are rated **3.3 V logic**. The boards usually survive direct 5 V in practice, but it's out of spec.

- **Recommended:** put an **8-channel level shifter** (TXS0108E) between the Uno and the TFTs on the 8 signal lines: SCK, MOSI, CS1, CS2, DC1, DC2, RST1, RST2. HV side = Uno 5 V, LV side = 3.3 V (tied to the same 3.3 V that feeds VCC).
- **"It just works" shortcut (common with ST7735 1.8″ boards):** wire direct as in §2. Many boards clamp fine at 5 V. If a display glitches or gets warm, add the shifter.
- If you choose the shifter, it goes inline on the signal wires only — power and GND stay direct.

---

## 5. Software — what goes where

### Arduino Uno — `eyes_tft/eyes_tft.ino`
1. Open `eyes_tft/eyes_tft.ino` in the Arduino IDE (it's in its own folder, as Arduino requires).
2. Install libraries: **Adafruit GFX**, plus **Adafruit ST7735** (1.8″), **Adafruit ILI9341** (2.4″/2.8″) and **Adafruit GC9A01A** (round 1.28″ 240×240).
3. Set `DEFAULT_TYPE` at the top to match your boards (`1`=ST7735, `2`=ILI9341, `3`=GC9A01A round — the default) and confirm the pin constants match §2.
4. Upload. Each screen shows one big cartoon eye (sclera + colored iris + pupil).

### Raspberry Pi 5 — `pi_eyes.py`
```bash
cd ~/ugv_rpi/eyes
source ~/ugv_rpi/ugv-env/bin/activate
python pi_eyes.py --port /dev/ttyACM0
```
It grabs the robot's USB camera, runs YOLOv8n (`person` class, conf 0.35), and streams the person's position to the Uno at ~20 Hz.

### Serial protocol (Pi → Uno, ASCII lines, 115200 baud)
| Command | Meaning |
|---|---|
| `T <px> <py>` | Look toward point; `px`,`py` in **0–100** (50,50 = frame center). Both pupils converge on it. |
| `T -1 -1` | No person in view — pupils return to center. |
| `PING` | Uno replies `PONG` — wiring/link sanity check. |
| `TYPE <l> <r>` | Set each eye's controller at runtime: `1` = ST7735, `2` = ILI9341, `3` = GC9A01A round (e.g. `TYPE 3 3`). Re-initializes both displays and re-runs the color test. No re-flash needed. |

### Boot behavior (this is your main diagnostic)
When the Uno powers up (or resets) it prints the pin map and controller IDs over serial, then **paints LEFT eye RED and RIGHT eye GREEN for 4 seconds** — the color test — then switches to eye mode. What you see during those 4 seconds tells us exactly what's wrong:

| You see | Meaning | Fix |
|---|---|---|
| Left RED, right GREEN | Wiring + both inits correct | nothing — eyes follow |
| One solid color, other blank/garbage | That eye's wiring or controller type is wrong | re-check that eye's 5 wires; try `TYPE` for that eye |
| Neither shows color | Power problem (VCC/GND/LED/backlight) or wrong controller on both | check power first, then `TYPE 3 3` (GC9A01A) vs `TYPE 2 2` / `TYPE 1 1` |
| Scrolling lines/garbage | Controller mismatch (ST7735 init on ILI9341 panel or vice-versa), or CS/DC swapped | try the other `TYPE`; swap CS↔DC if needed |

---

## 6. Bring-up test sequence (with the color test)

1. Upload `eyes_tft/eyes_tft.ino`.
2. Watch the screens during boot: **LEFT should flash RED, RIGHT should flash GREEN** for ~4 s, then both show one cartoon eye filling the round panel (white sclera circle edge-to-edge, colored iris + dark pupil + highlight).
3. If the colors are wrong/blank/garbage, use the table above, and switch controller types from the Pi **without re-flashing**:
   ```bash
   echo 'TYPE 3 3' > /dev/ttyACM0   # GC9A01A round — or TYPE 1 1 / TYPE 2 2; one build handles any mix
   ```
4. `PING` should print `PONG` on the Pi. With this firmware the boot fills take milliseconds-to-sub-second (the Uno prints `FILL L: …ms R: …ms`), and during tracking it prints `REPAINT n=25 avg=…ms` every 25 iris moves so you can see the repaint cost on the serial line.

1. **Power only:** plug the Uno into the Pi. Both TFTs should light up (backlight on) and the Arduino sketch draws the two eyes.
2. **Serial check:** run `python pi_eyes.py --port /dev/ttyACM0` — the script sends `PING` first and prints `Uno alive: PONG`.
3. **Manual gaze test:** from the Pi, `echo "T 90 50" > /dev/ttyACM0` → both pupils drift right. `echo "T -1 -1"` → center.
4. **Full system:** stand in front of the camera and wave — the eyes should track you left/right/up/down as you move across the frame.
5. If a display stays blank: swap its `CS`/`DC`/`RST` wires with the other display's to isolate a bad pin vs. a bad display; re-check that `SCK`→`SCK` and `MOSI`→`SDA` (a reversed SDA/SCK is the #1 wiring mistake).

---

## 7. The most common wiring mistake (read this if you used the old table)

An earlier version of this guide shared one SPI bus (SCK→D13, MOSI→D11 for **both** displays). That is **wrong for the current firmware**. The left eye must be on **its own port**:

- LEFT eye: `SCL/SCK → D4`, `SDA/MOSI → D3`
- RIGHT eye: `SCK → D13`, `SDA/MOSI → D11`

If you wired **both** displays' clock to D13 and data to D11, the left eye will be blank or show garbage — move its two wires from D13→D4 and D11→D3. Do **not** tie both displays' SCK or MOSI together.

## 8. How the eye movement works (data flow)

```
Pi 5 camera → YOLOv8n "person" box → center (cx,cy)
            → px = cx*100/frame_w, py = cy*100/frame_h
            → serial "T <px> <py>" (or "T -1 -1" when lost)
Arduino Uno → parses line → smooths gaze → maps px,py to pupil offset
            → redraws both TFTs (iris+pupil move toward the target)
```

The eye firmware is in `eyes_tft/eyes_tft.ino`; the Pi side is `pi_eyes.py`. The current firmware's boot banner is the fastest way to report back: screenshot the serial output (`PING`, probe IDs, per-eye `init:` lines) and tell me which colors each screen showed in the test phase.

### Quick fault-finding checklist (run these in order)
1. **Backlight** — is the white LED behind the screen on? If not, check the `LED` pin is powered (3.3 V) and its wire isn't swapped with another pin. A lit backlight with no image = init/wiring problem; a dark screen = power problem.
2. **VCC + GND** — measure 3.3 V between `VCC` and `GND` at each display's header.
3. **Color test** — reboot the Uno and note each screen's color during the 4 s test (RED = left, GREEN = right).
4. **Controller type** — try `TYPE 1 1` then `TYPE 2 2` and repeat the color test; one of them should light up solid if the wiring is right.
5. **Per-eye wiring** — left eye: D4(clock) D3(data) D10(CS) D9(DC) D8(RST). Right eye: D13(clock) D11(data) D7(CS) D6(DC) D5(RST). A blank eye usually means its CS/DC/RST wires are on the wrong Uno pins.
6. **Optional:** wire the right eye's MISO pin to **D12** — the firmware then auto-detects ST7735 vs ILI9341 and prints the panel ID at boot.