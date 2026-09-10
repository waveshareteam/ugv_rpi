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

Both displays share the Uno's SPI bus (**SCK + MOSI** are common). Each display gets its **own CS, DC, and RESET** pin so the Uno can talk to them one at a time. Power (VCC/LED) and GND are common.

| Signal | Uno pin | TFT #1 (LEFT eye) | TFT #2 (RIGHT eye) |
|---|---|---|---|
| Power (logic) | **3.3 V** | `VCC` | `VCC` |
| Power (backlight) | **3.3 V** | `LED` | `LED` |
| Ground | **GND** | `GND` | `GND` |
| SPI clock | **D13 (SCK)** | `SCK` / `SCL` | `SCK` / `SCL` |
| SPI data | **D11 (MOSI)** | `SDA` / `MOSI` | `SDA` / `MOSI` |
| Chip select | **D10** | `CS` | — |
| Chip select | **D7** | — | `CS` |
| Data/command | **D9** | `DC` | — |
| Data/command | **D6** | — | `DC` |
| Reset | **D8** | `RESET` | — |
| Reset | **D5** | — | `RESET` |

Notes:
- `MISO` (D12) is **not connected** — the TFTs don't need it for writing.
- **VCC → 3.3 V** is the safe rule. If your board has an **onboard 3.3 V regulator** (common on ILI9341 2.4″ boards, identifiable by the small regulator + jumper near the header), you may feed `VCC` from the Uno's **5 V** instead — check the board's datasheet/silkscreen first.
- Backlight: tying `LED` to 3.3 V = full brightness. To dim, move `LED` to **D3** (PWM) on both displays instead.

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
2. Install libraries: **Adafruit GFX**, plus **Adafruit ST7735** (1.8″) or **Adafruit ILI9341** (2.4″/2.8″).
3. Set `DISPLAY_TYPE` at the top to match your boards, and confirm the pin constants match §2.
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

---

## 6. Bring-up test sequence

1. **Power only:** plug the Uno into the Pi. Both TFTs should light up (backlight on) and the Arduino sketch draws the two eyes.
2. **Serial check:** run `python pi_eyes.py --port /dev/ttyACM0` — the script sends `PING` first and prints `Uno alive: PONG`.
3. **Manual gaze test:** from the Pi, `echo "T 90 50" > /dev/ttyACM0` → both pupils drift right. `echo "T -1 -1"` → center.
4. **Full system:** stand in front of the camera and wave — the eyes should track you left/right/up/down as you move across the frame.
5. If a display stays blank: swap its `CS`/`DC`/`RST` wires with the other display's to isolate a bad pin vs. a bad display; re-check that `SCK`→`SCK` and `MOSI`→`SDA` (a reversed SDA/SCK is the #1 wiring mistake).

---

## 7. How the eye movement works (data flow)

```
Pi 5 camera → YOLOv8n "person" box → center (cx,cy)
            → px = cx*100/frame_w, py = cy*100/frame_h
            → serial "T <px> <py>" (or "T -1 -1" when lost)
Arduino Uno → parses line → smooths gaze → maps px,py to pupil offset
            → redraws both TFTs (iris+pupil move toward the target)
```

The eye firmware is in `eyes_tft.ino`; the Pi side is `pi_eyes.py`. If your Uno already has its own eye firmware, keep it — just make it accept the `T <px> <py>` / `PING` protocol above so the Pi can drive it.