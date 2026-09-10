/*
 * Robot Eyes — 2x SPI TFT on Arduino Uno
 * ---------------------------------------
 * Draws one cartoon eye on each of two SPI TFT displays and moves the
 * pupils toward a target sent over serial by the Raspberry Pi 5.
 *
 * Serial protocol (115200 baud, ASCII lines):
 *   T <px> <py>   look toward point; px,py in 0..100 (50,50 = center)
 *   T -1 -1       no person in view; pupils return to center
 *   PING          reply "PONG" (link sanity check)
 *
 * Wiring (see eyes/wiring.md):
 *   SCK -> D13, MOSI -> D11        (shared bus)
 *   TFT #1 (LEFT):  CS=10, DC=9,  RST=8
 *   TFT #2 (RIGHT): CS=7,  DC=6,  RST=5
 *   VCC + LED -> 3.3V, GND -> GND
 *
 * Libraries: Adafruit GFX + Adafruit ST7735 (1.8") or Adafruit ILI9341 (2.4"/2.8")
 */

// ---- pick your display type once (or pass -DDISPLAY_TYPE=2 on the CLI) ----
#ifndef DISPLAY_TYPE
#define DISPLAY_TYPE 1   // 1 = ST7735 1.8", 2 = ILI9341 2.4"/2.8"
#endif
// ---- eye style ----
#define IRIS_R 30        // iris radius
#define PUPIL_R 14       // pupil radius
#define EYE_R 58         // eye (sclera) radius
#define GAZE_SPEED 0.18  // smoothing per loop (0..1, higher = snappier)

#if DISPLAY_TYPE == 1
#include <Adafruit_ST7735.h>
Adafruit_ST7735 tft1(10, 9, 8);   // cs, dc, rst
Adafruit_ST7735 tft2(7, 6, 5);
#else
#include <Adafruit_ILI9341.h>
Adafruit_ILI9341 tft1(10, 9, 8);
Adafruit_ILI9341 tft2(7, 6, 5);
#endif

// screen geometry
const int W = (DISPLAY_TYPE == 1) ? 160 : 320;
const int H = (DISPLAY_TYPE == 1) ? 128 : 240;
const int CX1 = W / 4;         // left eye center on screen #1
const int CY1 = H / 2;
const int CX2 = W - W / 4;     // right eye center on screen #2
const int CY2 = H / 2;

// current smoothed gaze in 0..100 space (50,50 = center)
float gx = 50.0, gy = 50.0;
// last target
int tx = 50, ty = 50;
bool targetSet = false;        // false when "T -1 -1"
float px1 = 0, py1 = 0;        // last drawn pupil offsets (for change test)
float px2 = 0, py2 = 0;

const uint16_t SKIN   = 0xDEDB;  // pale face tone (RGB565)
const uint16_t WHITE  = 0xFFFF;
const uint16_t IRIS   = 0x7DDF;  // light blue
const uint16_t PUPIL  = 0x0000;
const uint16_t OUTLN  = 0x52AA;  // dark gray eyeliner

void setup() {
  Serial.begin(115200);
#if DISPLAY_TYPE == 1
  tft1.initR(INITR_BLACKTAB);
  tft2.initR(INITR_BLACKTAB);
#else
  tft1.begin();
  tft2.begin();
#endif
  tft1.setRotation(0);
  tft2.setRotation(0);
  tft1.fillScreen(SKIN);
  tft2.fillScreen(SKIN);
  drawEye(tft1, CX1, CY1, 0, 0);
  drawEye(tft2, CX2, CY2, 0, 0);
  px1 = py1 = px2 = py2 = 0;
}

void loop() {
  handleSerial();

  // smooth gaze toward the target (50,50 when no person)
  float aimX = targetSet ? (float)tx : 50.0;
  float aimY = targetSet ? (float)ty : 50.0;
  gx += (aimX - gx) * GAZE_SPEED;
  gy += (aimY - gy) * GAZE_SPEED;

  // map gaze (0..100) to pupil offset in pixels
  float offX1 = (gx - 50.0) / 50.0 * (EYE_R - IRIS_R - 2);   // left eye
  float offY1 = (gy - 50.0) / 50.0 * (EYE_R - IRIS_R - 2);
  // right eye: slightly more converged for a natural look (0.85x of left)
  float offX2 = offX1 * 0.85f;
  float offY2 = offY1 * 0.85f;

  if (fabs(offX1 - px1) + fabs(offY1 - py1) > 1.0 ||
      fabs(offX2 - px2) + fabs(offY2 - py2) > 1.0) {
    // clear old eye region, redraw eye at new pupil position
    fillEyeArea(tft1, CX1, CY1);
    fillEyeArea(tft2, CX2, CY2);
    drawEye(tft1, CX1, CY1, offX1, offY1);
    drawEye(tft2, CX2, CY2, offX2, offY2);
    px1 = offX1; py1 = offY1;
    px2 = offX2; py2 = offY2;
  }

  delay(20);  // ~50 Hz input handling
}

void handleSerial() {
  static String line = "";
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      line.trim();
      if (line.length() > 0) {
        if (line.startsWith("PING")) {
          Serial.println("PONG");
        } else if (line.startsWith("T ")) {
          int sp = line.indexOf(' ', 2);
          if (sp > 0) {
            int a = line.substring(2, sp).toInt();
            int b = line.substring(sp + 1).toInt();
            if (a >= 0 && b >= 0) {
              tx = constrain(a, 0, 100);
              ty = constrain(b, 0, 100);
              targetSet = true;
            } else {
              targetSet = false;  // T -1 -1
            }
          }
        }
      }
      line = "";
    } else {
      line += c;
    }
  }
}

// ---- drawing ----
void drawEye(Adafruit_GFX &t, int cx, int cy, float ox, float oy) {
  t.fillCircle(cx, cy, EYE_R, WHITE);          // sclera
  t.drawCircle(cx, cy, EYE_R, OUTLN);          // eyeliner
  t.fillCircle(cx + (int)ox, cy + (int)oy, IRIS_R, IRIS);    // iris
  t.fillCircle(cx + (int)ox, cy + (int)oy, PUPIL_R, PUPIL);  // pupil
  // highlight so it looks alive
  t.fillCircle(cx + (int)ox - IRIS_R / 3, cy + (int)oy - IRIS_R / 3, 5, WHITE);
}

void fillEyeArea(Adafruit_GFX &t, int cx, int cy) {
  t.fillCircle(cx, cy, EYE_R + 2, SKIN);
}