#!/usr/bin/env python3
"""
UGV Client - CLI to call the /api/ugv/* REST endpoints.
Usage examples:
  python ugv_client.py status
  python ugv_client.py move forward --speed 0.3 --duration 1.5
  python ugv_client.py stop
  python ugv_client.py lights --base 255 --head 0
  python ugv_client.py gimbal --x 30 --y 15
  python ugv_client.py gimbal center
  python ugv_client.py photo
  python ugv_client.py video start
  python ugv_client.py video stop
  python ugv_client.py cv face
  python ugv_client.py cv none
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

DEFAULT_HOST = "http://localhost:5000"


def post(host, path, payload=None):
    url = host.rstrip("/") + path
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"status": "error", "message": body, "code": e.code}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get(host, path):
    url = host.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "message": str(e)}


def print_result(result):
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="UGV Robot CLI Client")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"Flask server URL (default: {DEFAULT_HOST})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # status
    sub.add_parser("status", help="Get robot and system status")

    # stop
    sub.add_parser("stop", help="Emergency stop")

    # move
    p_move = sub.add_parser("move", help="Move robot")
    p_move.add_argument("direction",
                        choices=["forward", "backward", "left", "right",
                                 "spin_left", "spin_right"])
    p_move.add_argument("--speed", type=float, default=0.3,
                        help="Speed 0.0-0.8 (default 0.3)")
    p_move.add_argument("--duration", type=float, default=1.0,
                        help="Duration in seconds 0.1-5.0 (default 1.0)")

    # lights
    p_lights = sub.add_parser("lights", help="Control lights")
    p_lights.add_argument("--base", type=int, default=0,
                          help="Base light 0-255 (default 0=off)")
    p_lights.add_argument("--head", type=int, default=0,
                          help="Head light 0-255 (default 0=off)")

    # gimbal
    p_gimbal = sub.add_parser("gimbal", help="Pan/tilt gimbal or 'center'")
    p_gimbal.add_argument("action", nargs="?", default=None,
                          choices=["center"], help="'center' to reset gimbal")
    p_gimbal.add_argument("--x", type=float, default=0,
                          help="Pan angle -180..180 (default 0)")
    p_gimbal.add_argument("--y", type=float, default=0,
                          help="Tilt angle -30..90 (default 0)")
    p_gimbal.add_argument("--speed", type=int, default=200,
                          help="Speed 1-1000 (default 200)")

    # photo
    sub.add_parser("photo", help="Capture a photo")

    # video
    p_video = sub.add_parser("video", help="Video recording control")
    p_video.add_argument("action", choices=["start", "stop"])

    # cv
    p_cv = sub.add_parser("cv", help="Set CV detection mode")
    p_cv.add_argument("mode",
                      choices=["none", "motion", "face", "objects",
                               "color", "autodrive", "hand", "mp_face", "pose"])
    p_cv.add_argument("--confirm", action="store_true",
                      help="Required for autodrive mode")

    args = parser.parse_args()
    host = args.host

    if args.cmd == "status":
        print_result(get(host, "/api/ugv/status"))

    elif args.cmd == "stop":
        print_result(post(host, "/api/ugv/stop"))

    elif args.cmd == "move":
        print_result(post(host, "/api/ugv/move", {
            "direction": args.direction,
            "speed": args.speed,
            "duration": args.duration,
        }))

    elif args.cmd == "lights":
        print_result(post(host, "/api/ugv/lights", {
            "base": args.base,
            "head": args.head,
        }))

    elif args.cmd == "gimbal":
        if args.action == "center":
            print_result(post(host, "/api/ugv/gimbal/center"))
        else:
            print_result(post(host, "/api/ugv/gimbal", {
                "x": args.x,
                "y": args.y,
                "speed": args.speed,
            }))

    elif args.cmd == "photo":
        print_result(post(host, "/api/ugv/photo"))

    elif args.cmd == "video":
        path = "/api/ugv/video/start" if args.action == "start" else "/api/ugv/video/stop"
        print_result(post(host, path))

    elif args.cmd == "cv":
        payload = {"mode": args.mode}
        if args.mode == "autodrive":
            if not args.confirm:
                print("ERROR: autodrive requires --confirm flag (dangerous mode)")
                sys.exit(1)
            payload["confirm"] = True
        print_result(post(host, "/api/ugv/cv/mode", payload))


if __name__ == "__main__":
    main()
