/*
 * Robot Eyes — 2x SPI TFT on Arduino Uno
 * ---------------------------------------
 * Draws one cartoon eye on each of two SPI TFT displays and moves the
 * pupils toward a target sent over serial by the Raspberry Pi 5.
 *
 * Serial protocol (115200 baud, ASCII lines):
 *   T <px> <py>     look toward point; px,py in 0..100 (50,50 = center)
 *   T -1 -1         no person in view; pupils return to center
 *   PING            reply "PONG" (link sanity check)
 *   TYPE <l> <r>    set display controller per eye (1=ST7735, 2=ILI9341,
 *                   3=GC9A01A round), re-initialize and re-run the color test
 *   TAB <l> <r>     ST7735 init variant per eye (1=black 2=green 3=red 4=144)
 *   TEST            re-run the boot color test + redraw
 *
 * Boot: prints detected controller IDs + fill timings, then paints LEFT eye
 * RED and RIGHT eye GREEN for a few seconds (the color test), then switches
 * to eye mode. During tracking a "REPAINT" line is printed every 25 iris
 * moves so the repaint cost (and thus the achievable tracking rate) is
 * measurable over serial.
 *
 * ROUND-PANEL GEOMETRY (GC9A01A 240x240 round, the boards in use):
 *   All radii are computed from the panel size at init. On the round panel
 *   the sclera circle (r = 114) fills the visible round area — nothing is
 *   sized for the 128x160 rectangle anymore. The iris offset is clamped so
 *   the iris always stays inside the sclera circle.
 *
 * LEFT-EYE SPEED: the left eye has its own port (D4=SCLK, D3=MOSI) and is
 * driven by FastGc9a01 — a direct-PORTD bit-bang driver with the Adafruit
 * GC9A01A init sequence copied verbatim. That cuts a full 240x240 fill from
 * ~10 s (Adafruit software SPI) to ~0.4 s, and the incremental iris/pupil
 * repaint means a gaze move repaints only the iris region, so tracking stays
 * fluid. (Hardware MSPIM would be faster still but steals USART0 — the same
 * hardware that carries the gaze protocol — so it was rejected.)
 *
 * Wiring (see eyes/wiring.md) — NO shared signal wires:
 *   TFT #1 (LEFT eye)  own port: SCLK=D4, MOSI=D3, CS=10, DC=9,  RST=8
 *   TFT #2 (RIGHT eye) own port: SCK=D13, MOSI=D11, CS=7, DC=6,  RST=5
 *   MISO (D12) -> right eye MISO  OPTIONAL — needed only for auto-detect
 *   VCC + LED -> 3.3V, GND -> GND (power is common; signals are separate)
 *
 * Libraries: Adafruit GFX + Adafruit ST7735 + Adafruit ILI9341 + Adafruit GC9A01A
 */

// ---- default controller (3 = GC9A01A round 240x240, the boards in use) ----
#ifndef DEFAULT_TYPE
#define DEFAULT_TYPE 3   // 1 = ST7735 1.8", 2 = ILI9341 2.4", 3 = GC9A01A round 1.28" 240x240
#endif

#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <Adafruit_ILI9341.h>
#include <Adafruit_GC9A01A.h>
#include <SPI.h>
#include <math.h>

// ---- pins: LEFT eye on its own software-SPI port, RIGHT eye on hardware SPI ----
const int L_CS = 10, L_DC = 9, L_MOSI = 3, L_SCLK = 4, L_RST = 8;   // LEFT  eye (MOSI/SCLK are PD3/PD4)
const int R_CS = 7,  R_DC = 6, R_MOSI = 11, R_SCLK = 13, R_RST = 5; // RIGHT eye (hardware SPI 11/13)

// ---- colors (RGB565) ----
const uint16_t SKIN  = 0xDEDB;
const uint16_t WHITE = 0xFFFF;
const uint16_t IRIS  = 0x7DDF;
const uint16_t PUPIL = 0x0000;
const uint16_t OUTLN = 0x52AA;
const uint16_t RED   = 0xF800;
const uint16_t GREEN = 0x07E0;

// =============================================================================
// FastGc9a01 — GC9A01A 240x240 on direct-PORTD bit-bang SPI (left eye).
// Same init sequence as Adafruit_GC9A01A (copied verbatim), ~20x faster than
// the Adafruit software-SPI path because per-bit writes hit PORTD directly.
// =============================================================================
class FastGc9a01 {
public:
  static const int16_t W = 240, H = 240;

  FastGc9a01(int8_t cs, int8_t dc, int8_t rst) : _cs(cs), _dc(dc), _rst(rst) {}

  void begin() {
    pinMode(_cs, OUTPUT); pinMode(_dc, OUTPUT); pinMode(_rst, OUTPUT);
    pinMode(L_MOSI, OUTPUT); pinMode(L_SCLK, OUTPUT);
    digitalWrite(_cs, HIGH);
    digitalWrite(_rst, HIGH);
    delay(20);
    digitalWrite(_rst, LOW);
    delay(20);
    digitalWrite(_rst, HIGH);
    delay(120);

    // ---- Adafruit_GC9A01A init sequence (verbatim) ----
    static const uint8_t initcmd[] PROGMEM = {
      0xEF, 0,                                    // INREGEN2
      0xEB, 1, 0x14,
      0xFE, 0,                                    // INREGEN1
      0xEF, 0,
      0xEB, 1, 0x14,
      0x84, 1, 0x40,
      0x85, 1, 0xFF,
      0x86, 1, 0xFF,
      0x87, 1, 0xFF,
      0x88, 1, 0x0A,
      0x89, 1, 0x21,
      0x8A, 1, 0x00,
      0x8B, 1, 0x80,
      0x8C, 1, 0x01,
      0x8D, 1, 0x01,
      0x8E, 1, 0xFF,
      0x8F, 1, 0xFF,
      0xB6, 2, 0x00, 0x00,
      0x36, 1, 0x48,                              // MADCTL: MX | BGR
      0x3A, 1, 0x05,                              // COLMOD 16-bit
      0x90, 4, 0x08, 0x08, 0x08, 0x08,
      0xBD, 1, 0x06,
      0xBC, 1, 0x00,
      0xFF, 3, 0x60, 0x01, 0x04,
      0xC3, 1, 0x13,                              // POWER2
      0xC4, 1, 0x13,                              // POWER3
      0xC9, 1, 0x22,                              // POWER4
      0xBE, 1, 0x11,
      0xE1, 2, 0x10, 0x0E,
      0xDF, 3, 0x21, 0x0C, 0x02,
      0xF0, 6, 0x45, 0x09, 0x08, 0x08, 0x26, 0x2A, // GAMMA1
      0xF1, 6, 0x43, 0x70, 0x72, 0x36, 0x37, 0x6F, // GAMMA2
      0xF2, 6, 0x45, 0x09, 0x08, 0x08, 0x26, 0x2A, // GAMMA3
      0xF3, 6, 0x43, 0x70, 0x72, 0x36, 0x37, 0x6F, // GAMMA4
      0xED, 2, 0x1B, 0x0B,
      0xAE, 1, 0x77,
      0xCD, 1, 0x63,
      0xE8, 1, 0x34,                              // FRAMERATE
      0x62, 12, 0x18, 0x0D, 0x71, 0xED, 0x70, 0x70, 0x18, 0x0F, 0x71, 0xEF, 0x70, 0x70,
      0x63, 12, 0x18, 0x11, 0x71, 0xF1, 0x70, 0x70, 0x18, 0x13, 0x71, 0xF3, 0x70, 0x70,
      0x64, 7, 0x28, 0x29, 0xF1, 0x01, 0xF1, 0x00, 0x07,
      0x66, 10, 0x3C, 0x00, 0xCD, 0x67, 0x45, 0x45, 0x10, 0x00, 0x00, 0x00,
      0x67, 10, 0x00, 0x3C, 0x00, 0x00, 0x00, 0x01, 0x54, 0x10, 0x32, 0x98,
      0x74, 7, 0x10, 0x85, 0x80, 0x00, 0x00, 0x4E, 0x00,
      0x98, 2, 0x3E, 0x07,
      0x35, 0,                                    // TEON
      0x21, 0,                                    // INVON
      0x11, 0x80,                                 // SLPOUT (delay 150)
      0x29, 0x80,                                 // DISPON (delay 150)
      0x00                                        // end
    };
    uint8_t cmd, x, n;
    const uint8_t *a = initcmd;
    while ((cmd = pgm_read_byte(a++)) > 0) {
      x = pgm_read_byte(a++);
      n = x & 0x7F;
      writeCmd(cmd);
      for (uint8_t i = 0; i < n; i++) writeData(pgm_read_byte(a++));
      if (x & 0x80) delay(150);
    }
  }

  // ---- one byte, MSB first, SPI mode 0, direct PORTD (MOSI=PD3, SCLK=PD4) ----
  inline void write8(uint8_t b) {
    for (uint8_t m = 0x80; m; m >>= 1) {
      if (b & m) PORTD |= (1 << 3); else PORTD &= ~(1 << 3);
      PORTD |= (1 << 4);
      PORTD &= ~(1 << 4);
    }
  }

  inline void write16(uint16_t v) { write8(v >> 8); write8(v & 0xFF); }

  void writeCmd(uint8_t c) {
    digitalWrite(_dc, LOW);
    write8(c);
    digitalWrite(_dc, HIGH);
  }

  void writeData(uint8_t b) {
    digitalWrite(_dc, HIGH);
    write8(b);
  }

  void setAddrWindow(int16_t x, int16_t y, int16_t w, int16_t h) {
    digitalWrite(_cs, LOW);
    writeCmd(0x2A);           // CASET
    write16(x); write16(x + w - 1);
    writeCmd(0x2B);           // RASET
    write16(y); write16(y + h - 1);
    writeCmd(0x2C);           // RAMWR
  }

  void pushPixels(uint32_t n, uint16_t c) {
    uint8_t hi = c >> 8, lo = c & 0xFF;
    for (uint32_t i = 0; i < n; i++) { write8(hi); write8(lo); }
  }

  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) {
    if (w <= 0 || h <= 0) return;
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x >= W || y >= H) return;
    if (x + w > W) w = W - x;
    if (y + h > H) h = H - y;
    if (w <= 0 || h <= 0) return;
    setAddrWindow(x, y, w, h);
    pushPixels((uint32_t)w * h, c);
    digitalWrite(_cs, HIGH);
  }

  void fillScreen(uint16_t c) { fillRect(0, 0, W, H, c); }

  void fillCircle(int16_t x0, int16_t y0, int16_t r, uint16_t c) {
    if (r < 0) return;
    for (int16_t dy = -r; dy <= r; dy++) {
      int16_t dx = (int16_t)sqrt((long)r * r - (long)dy * dy);
      fillRect(x0 - dx, y0 + dy, dx * 2 + 1, 1, c);
    }
  }

  void drawPixel(int16_t x, int16_t y, uint16_t c) { fillRect(x, y, 1, 1, c); }

  void drawCircle(int16_t x0, int16_t y0, int16_t r, uint16_t c) {
    int16_t f = 1 - r, ddF_x = 1, ddF_y = -2 * r, x = 0, y = r;
    drawPixel(x0, y0 + r, c); drawPixel(x0, y0 - r, c);
    drawPixel(x0 + r, y0, c); drawPixel(x0 - r, y0, c);
    while (x < y) {
      if (f >= 0) { y--; ddF_y += 2; f += ddF_y; }
      x++; ddF_x += 2; f += ddF_x;
      drawPixel(x0 + x, y0 + y, c); drawPixel(x0 - x, y0 + y, c);
      drawPixel(x0 + x, y0 - y, c); drawPixel(x0 - x, y0 - y, c);
      drawPixel(x0 + y, y0 + x, c); drawPixel(x0 - y, y0 + x, c);
      drawPixel(x0 + y, y0 - x, c); drawPixel(x0 - y, y0 - x, c);
    }
  }

private:
  int8_t _cs, _dc, _rst;
};

// =============================================================================
// Panel abstraction — the eye renderer draws through this so both eyes share
// one code path: LEFT = FastGc9a01 (fast bit-bang), RIGHT = Adafruit GFX (hw SPI).
// =============================================================================
struct Panel {
  int16_t W, H;
  virtual void fillScreen(uint16_t c) = 0;
  virtual void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) = 0;
  virtual void fillCircle(int16_t x, int16_t y, int16_t r, uint16_t c) = 0;
  virtual void drawCircle(int16_t x, int16_t y, int16_t r, uint16_t c) = 0;
  virtual ~Panel() {}
};

class FastPanel : public Panel {
public:
  FastPanel(FastGc9a01 *d) : _d(d) { W = d->W; H = d->H; }
  void fillScreen(uint16_t c) override { _d->fillScreen(c); }
  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) override { _d->fillRect(x, y, w, h, c); }
  void fillCircle(int16_t x, int16_t y, int16_t r, uint16_t c) override { _d->fillCircle(x, y, r, c); }
  void drawCircle(int16_t x, int16_t y, int16_t r, uint16_t c) override { _d->drawCircle(x, y, r, c); }
private:
  FastGc9a01 *_d;
};

class GfPanel : public Panel {
public:
  GfPanel(Adafruit_GFX *g) : _g(g) { W = g->width(); H = g->height(); }
  void fillScreen(uint16_t c) override { _g->fillScreen(c); }
  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) override { _g->fillRect(x, y, w, h, c); }
  void fillCircle(int16_t x, int16_t y, int16_t r, uint16_t c) override { _g->fillCircle(x, y, r, c); }
  void drawCircle(int16_t x, int16_t y, int16_t r, uint16_t c) override { _g->drawCircle(x, y, r, c); }
private:
  Adafruit_GFX *_g;
};

// ---- display objects ----
FastGc9a01       fastL(L_CS, L_DC, L_RST);                    // LEFT  eye, GC9A01A, fast bit-bang
Adafruit_ST7735  stL(L_CS, L_DC, L_MOSI, L_SCLK, L_RST);      // LEFT  eye, ST7735,  software SPI
Adafruit_ST7735  stR(R_CS, R_DC, R_RST);                      // RIGHT eye, ST7735,  hardware SPI
Adafruit_ILI9341 ilL(L_CS, L_DC, L_MOSI, L_SCLK, L_RST);      // LEFT  eye, ILI9341, software SPI
Adafruit_ILI9341 ilR(R_CS, R_DC, R_RST);                      // RIGHT eye, ILI9341, hardware SPI
Adafruit_GC9A01A gcR(R_CS, R_DC, R_RST);                      // RIGHT eye, GC9A01A, hardware SPI

GfPanel  gfStL(&stL), gfStR(&stR), gfIlL(&ilL), gfIlR(&ilR), gfGcR(&gcR);
FastPanel fpL(&fastL);

Panel *eye[2] = {nullptr, nullptr};   // active panel per eye (0=left, 1=right)
int eyeType[2] = {DEFAULT_TYPE, DEFAULT_TYPE};
int tabType[2] = {1, 1};              // ST7735 init variant per eye (only used when type==1)

int W[2], H[2], CX[2], CY[2];         // per-eye panel geometry
int EYE_R[2], IRIS_R[2], PUPIL_R[2], HL_R[2];   // per-eye radii (round-panel aware)

// ---- gaze state ----
#define GAZE_SPEED 0.25
#define TEST_MS 4000
float gx = 50.0, gy = 50.0;
int tx = 50, ty = 50;
bool targetSet = false;
float px[2] = {0, 0}, py[2] = {0, 0};  // last-drawn iris offset per eye

// ---- repaint timing report (every N moves, so tracking rate is measurable) ----
unsigned long repaintAccum = 0;
unsigned long lastRepaintTime = 0;
int repaintCount = 0;

const char *typeName(int t) {
  if (t == 2) return "ILI9341";
  if (t == 3) return "GC9A01A-round";
  return "ST7735";
}

// ---- init one eye with a given controller type (and ST7735 tab) ----
void initEye(int i, int type) {
  eyeType[i] = type;
  if (i == 0) {  // LEFT eye — type 3 uses the fast bit-bang driver
    if (type == 3)      { eye[0] = &fpL;  fastL.begin(); }
    else if (type == 2) { eye[0] = &gfIlL; ilL.begin(); }
    else {
      eye[0] = &gfStL;
      switch (tabType[0]) {
        case 2: stL.initR(INITR_GREENTAB); break;
        case 3: stL.initR(INITR_REDTAB); break;
        case 4: stL.initR(INITR_144GREENTAB); break;
        default: stL.initR(INITR_BLACKTAB);
      }
    }
  } else {       // RIGHT eye — hardware SPI Adafruit for all types
    if (type == 3)      { eye[1] = &gfGcR; gcR.begin(); }
    else if (type == 2) { eye[1] = &gfIlR; ilR.begin(); }
    else {
      eye[1] = &gfStR;
      switch (tabType[1]) {
        case 2: stR.initR(INITR_GREENTAB); break;
        case 3: stR.initR(INITR_REDTAB); break;
        case 4: stR.initR(INITR_144GREENTAB); break;
        default: stR.initR(INITR_BLACKTAB);
      }
    }
  }

  W[i] = eye[i]->W;
  H[i] = eye[i]->H;
  CX[i] = W[i] / 2;
  CY[i] = H[i] / 2;

  // Round-panel-aware geometry: the sclera circle is sized to fill the panel's
  // inscribed circle (on 240x240 that's r=114, i.e. a 228px eye in a 240px
  // round panel). Iris/pupil/highlight scale off it.
  int m = min(W[i], H[i]);
  EYE_R[i]  = m / 2 - 6;                    // 114 on GC9A01A, 58 on ST7735 128x160
  IRIS_R[i] = EYE_R[i] * 38 / 100;          //  43 on GC9A01A
  PUPIL_R[i] = IRIS_R[i] * 40 / 100;        //  17
  HL_R[i]   = max(3, IRIS_R[i] / 8);        //   5

  Serial.print(F("EYE"));
  Serial.print(i + 1);
  Serial.print(F(" init: "));
  Serial.print(typeName(type));
  Serial.print(F("  "));
  Serial.print(W[i]);
  Serial.print('x');
  Serial.print(H[i]);
  Serial.print(F("  sclera r="));
  Serial.print(EYE_R[i]);
  Serial.print(F(" iris r="));
  Serial.println(IRIS_R[i]);
}

// ---- auto-detect the RIGHT eye's controller by reading its ID over SPI ----
// Works only if the right eye's MISO pin is wired to Uno D12. Left eye is
// software SPI (no MISO) so it always uses the configured/default type.
void detectRightEye() {
  SPI.begin();
  pinMode(R_CS, OUTPUT); pinMode(R_DC, OUTPUT); pinMode(R_RST, OUTPUT);
  digitalWrite(R_RST, HIGH);
  delay(50);
  digitalWrite(R_CS, HIGH);

  // ILI9341: command 0xD3 "Read ID4" -> dummy bytes then 0x93 0x41
  uint8_t ili[8];
  digitalWrite(R_CS, LOW);
  digitalWrite(R_DC, LOW);
  SPI.transfer(0xD3);
  digitalWrite(R_DC, HIGH);
  for (uint8_t i = 0; i < 8; i++) ili[i] = SPI.transfer(0x00);
  digitalWrite(R_CS, HIGH);

  // ST7735: command 0x04 "Read ID" -> single byte 0x80..0x85
  uint8_t st = 0;
  digitalWrite(R_CS, LOW);
  digitalWrite(R_DC, LOW);
  SPI.transfer(0x04);
  digitalWrite(R_DC, HIGH);
  st = SPI.transfer(0x00);
  digitalWrite(R_CS, HIGH);

  Serial.print(F("EYE2 PROBE ILI9341: "));
  for (uint8_t i = 0; i < 8; i++) { Serial.print(ili[i], HEX); Serial.write(' '); }
  Serial.println();
  Serial.print(F("EYE2 PROBE ST7735 : 0x"));
  Serial.println(st, HEX);

  bool iliOK = false;
  for (uint8_t i = 0; i < 7; i++) if (ili[i] == 0x93 && ili[i + 1] == 0x41) iliOK = true;
  if (iliOK) {
    eyeType[1] = 2;
    Serial.println(F("EYE2 AUTO-DETECT: ILI9341"));
  } else if ((st & 0xF0) == 0x80) {
    eyeType[1] = 1;
    Serial.println(F("EYE2 AUTO-DETECT: ST7735"));
  } else {
    Serial.println(F("EYE2 AUTO-DETECT: failed — wire MISO (D12) to the right eye to enable"));
    Serial.println(F("  -> using default; override with: TYPE <l> <r>"));
  }
}

// ---- color test: left RED, right GREEN; fill timings prove the fast path ----
void colorTest() {
  unsigned long t0 = millis();
  eye[0]->fillScreen(RED);
  unsigned long t1 = millis();
  eye[1]->fillScreen(GREEN);
  unsigned long t2 = millis();
  Serial.print(F("FILL L: "));
  Serial.print(t1 - t0);
  Serial.print(F("ms  R: "));
  Serial.print(t2 - t1);
  Serial.println(F("ms  (was ~10s on the left eye with Adafruit soft-SPI)"));
  Serial.println(F("TEST: LEFT=RED  RIGHT=GREEN  (4s)"));
  Serial.println(F("  LEFT looks BLUE instead of RED  -> BGR panel, run: TAB 3 3"));
  Serial.println(F("  screens stay white/garbage      -> wrong controller, run: TYPE 3 3 (GC9A01A)"));
  Serial.println(F("  rerun anytime with: TEST"));
  unsigned long start = millis();
  while (millis() - start < TEST_MS) {
    handleSerial();  // keep the link responsive during the test
    delay(10);
  }
}

// ---- full scene: sclera fills the round visible area + eyeliner + iris ----
void drawScene() {
  for (int i = 0; i < 2; i++) drawEye(i, 0, 0);
  px[0] = py[0] = px[1] = py[1] = 0;
}

void drawEye(int i, float ox, float oy) {
  eye[i]->fillScreen(SKIN);                       // background (corners hidden on round panel)
  eye[i]->fillCircle(CX[i], CY[i], EYE_R[i], WHITE);   // sclera fills the visible circle
  eye[i]->drawCircle(CX[i], CY[i], EYE_R[i], OUTLN);   // eyeliner rim
  drawIris(i, ox, oy);
}

void drawIris(int i, float ox, float oy) {
  int ix = CX[i] + (int)ox, iy = CY[i] + (int)oy;
  eye[i]->fillCircle(ix, iy, IRIS_R[i], IRIS);
  eye[i]->fillCircle(ix, iy, PUPIL_R[i], PUPIL);
  eye[i]->fillCircle(ix - HL_R[i], iy - HL_R[i], HL_R[i], WHITE);   // highlight
}

void eraseIris(int i, float ox, float oy) {
  eye[i]->fillCircle(CX[i] + (int)ox, CY[i] + (int)oy, IRIS_R[i] + 1, WHITE);  // patch back to sclera
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println(F("EYES FW v5 — round GC9A01A geometry + fast left-eye SPI"));
  Serial.println(F("PINS LEFT : CS=10 DC=9 MOSI=3 SCLK=4 RST=8 (fast bit-bang)"));
  Serial.println(F("PINS RIGHT: CS=7  DC=6 MOSI=11 SCK=13 RST=5 (hw SPI)"));

  detectRightEye();          // may set eyeType[1]; left stays default unless TYPE cmd
  initEye(0, eyeType[0]);
  initEye(1, eyeType[1]);

  colorTest();               // LEFT=RED RIGHT=GREEN (fill timings printed)
  drawScene();
  lastRepaintTime = millis();
  Serial.println(F("EYES READY — send PING / T <px> <py> / T -1 -1 / TYPE <l> <r>"));
}

void loop() {
  handleSerial();

  float aimX = targetSet ? (float)tx : 50.0;
  float aimY = targetSet ? (float)ty : 50.0;
  gx += (aimX - gx) * GAZE_SPEED;
  gy += (aimY - gy) * GAZE_SPEED;

  // Map the smoothed aim (0..100 square) onto a UNIT vector, so the iris
  // center travels inside a circle of radius maxOff — a per-axis clamp alone
  // would push the iris outside the sclera at diagonal gazes.
  float vx = (gx - 50.0) / 50.0;
  float vy = (gy - 50.0) / 50.0;
  float mag = sqrt(vx * vx + vy * vy);
  if (mag > 1.0) { vx /= mag; vy /= mag; }

  float off[2] = {0, 0}, offY[2] = {0, 0};
  for (int i = 0; i < 2; i++) {
    float conv = (i == 1) ? 0.85f : 1.0f;        // right eye slightly more converged
    float maxOff = EYE_R[i] - IRIS_R[i] - 2;     // iris stays inside the sclera circle
    off[i]  = vx * maxOff * conv;
    offY[i] = vy * maxOff * conv;
  }

  bool moved = false;
  for (int i = 0; i < 2; i++) {
    if (fabs(off[i] - px[i]) + fabs(offY[i] - py[i]) > 1.0) {
      eraseIris(i, px[i], py[i]);                // clear old iris (incremental repaint)
      drawIris(i, off[i], offY[i]);              // draw new iris + pupil + highlight
      px[i] = off[i]; py[i] = offY[i];
      moved = true;
    }
  }

  if (moved) {
    unsigned long now = millis();
    unsigned long gap = now - lastRepaintTime;
    lastRepaintTime = now;
    if (gap < 1000) {                // ignore idle gaps: report the active repaint cost
      repaintAccum += gap;
      repaintCount++;
      if (repaintCount >= 25) {      // report the measured repaint cost
        Serial.print(F("REPAINT n=25 avg="));
        Serial.print(repaintAccum / 25);
        Serial.println(F("ms"));
        repaintAccum = 0;
        repaintCount = 0;
      }
    }
  }

  delay(20);
}

void handleSerial() {
  static String line = "";
  static unsigned long lastChar = 0;
  while (Serial.available()) {
    char c = Serial.read();
    lastChar = millis();
    if (c == '\n') {
      line.trim();
      if (line.length() > 0) {
        if (line.startsWith("PING")) {
          Serial.println("PONG");
        } else if (line.startsWith("TEST")) {
          colorTest();
          drawScene();
          Serial.println(F("TEST DONE"));
        } else if (line.startsWith("TAB ")) {
          int sp = line.indexOf(' ', 4);
          if (sp > 0) {
            int l = line.substring(4, sp).toInt();
            int r = line.substring(sp + 1).toInt();
            if (l >= 1 && l <= 4 && r >= 1 && r <= 4) {
              tabType[0] = l; tabType[1] = r;
              Serial.print(F("TAB OK: LEFT=")); Serial.print(l); Serial.print(F(" RIGHT=")); Serial.println(r);
              initEye(0, eyeType[0]);
              initEye(1, eyeType[1]);
              colorTest();
              drawScene();
              Serial.println(F("REINIT DONE"));
            } else {
              Serial.println(F("TAB: 1=black 2=green 3=red(BGR) 4=144green, e.g. TAB 3 3"));
            }
          }
        } else if (line.startsWith("TYPE ")) {
          int sp = line.indexOf(' ', 5);
          if (sp > 0) {
            int l = line.substring(5, sp).toInt();
            int r = line.substring(sp + 1).toInt();
            if (l >= 1 && l <= 3 && r >= 1 && r <= 3) {
              Serial.print(F("TYPE OK: LEFT="));
              Serial.print(typeName(l));
              Serial.print(F(" RIGHT="));
              Serial.println(typeName(r));
              initEye(0, l);
              initEye(1, r);
              colorTest();
              drawScene();
              Serial.println(F("REINIT DONE"));
            } else {
              Serial.println(F("TYPE: 1=ST7735 2=ILI9341 3=GC9A01A-round, e.g. TYPE 3 3"));
            }
          }
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
  // defensive: a partial line that never got its \n (e.g. bytes lost during a
  // long fill) is discarded after 200 ms so the parser can't wedge
  if (line.length() > 0 && millis() - lastChar > 200) line = "";
}