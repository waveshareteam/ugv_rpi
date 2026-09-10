#!/usr/bin/env python3
"""Robot Eyes bridge (Raspberry Pi 5 side).

Grabs the USB camera, runs YOLOv8n person detection, and streams the
person's frame position to the Arduino Uno over serial at ~20 Hz so the
two TFT eyes look toward them.

Protocol (115200 baud, ASCII):
    T <px> <py>   px,py in 0..100, (50,50) = frame center
    T -1 -1       no person in view
    PING          Uno replies PONG

Usage:
    python pi_eyes.py --port /dev/ttyACM0
"""
import argparse
import sys
import time

import cv2
import serial
from ultralytics import YOLO

PERSON_CLASS = 0  # YOLO COCO index for "person"


def main() -> int:
    ap = argparse.ArgumentParser(description="Stream person position to the eye-display Arduino.")
    ap.add_argument("--port", default="/dev/ttyACM0", help="Uno serial port (also try /dev/ttyUSB0)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    ap.add_argument("--conf", type=float, default=0.35, help="YOLO confidence threshold")
    ap.add_argument("--dry-run", action="store_true",
                    help="No serial device needed: log the T commands that would be sent")
    ap.add_argument("--verbose", action="store_true",
                    help="Print every command even when writing to the serial port")
    ap.add_argument("--model", default="yolov8n.pt", help="YOLO weights (auto-downloads if missing)")
    args = ap.parse_args()

    ser = None
    if args.dry_run:
        print("DRY-RUN: no serial device used — logging the gaze stream instead.")
    else:
        try:
            ser = serial.Serial(args.port, args.baud, timeout=0.2)
        except serial.SerialException as e:
            print(f"ERROR: cannot open {args.port}: {e}")
            print("Run: ls /dev/ttyACM* /dev/ttyUSB*  (or dmesg | tail) to find the Uno's port,")
            print("      or use --dry-run to verify detection without the Uno.")
            return 1
        ser.reset_input_buffer()

        # sanity check: the Uno replies PONG to PING
        ser.write(b"PING\n")
        deadline = time.time() + 2
        reply = b""
        while time.time() < deadline:
            chunk = ser.read(64)
            if chunk:
                reply += chunk
                if b"PONG" in reply:
                    break
        print(f"Uno alive: {'PONG' if b'PONG' in reply else 'NO REPLY — check wiring/USB'}")

    def send(line: bytes):
        if ser is not None:
            ser.write(line)
            if args.verbose:
                print(f"[sent] {line.decode().rstrip()}")
        else:
            print(f"[would send] {line.decode().rstrip()}")

    # bare filename not in cwd? also try the repo root (where the weights live)
    model_path = args.model
    if not os.path.exists(model_path) and os.path.sep not in model_path:
        parent = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, model_path)
        if os.path.exists(parent):
            model_path = parent
    model = YOLO(model_path)
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"ERROR: cannot open camera index {args.camera}")
        return 1

    dest = args.port if ser is not None else "LOG (dry-run)"
    print(f"Tracking people on camera {args.camera} -> {dest}  (Ctrl+C to stop)")
    try:
        frame_no = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            h, w = frame.shape[:2]

            # largest person in frame wins
            best = None  # (area, cx, cy)
            results = model(frame, verbose=False, conf=args.conf)
            for r in results:
                for box in r.boxes:
                    if int(box.cls[0]) != PERSON_CLASS:
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    area = (x2 - x1) * (y2 - y1)
                    if best is None or area > best[0]:
                        best = (area, (x1 + x2) // 2, (y1 + y2) // 2)

            if best:
                cx, cy = best[1], best[2]
                px, py = int(cx * 100 / w), int(cy * 100 / h)
                send(f"T {px} {py}\n".encode())
            else:
                send(b"T -1 -1\n")

            frame_no += 1
            time.sleep(0.05)  # ~20 Hz
    except KeyboardInterrupt:
        print("\nStopped — pupils return to center.")
        if ser is not None:
            ser.write(b"T -1 -1\n")
    finally:
        cap.release()
        if ser is not None:
            ser.close()
    return 0


if __name__ == "__main__":
    import os
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    sys.exit(main())