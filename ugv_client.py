#!/usr/bin/env python3
"""
UGV Client — CLI for /api/ugv/* REST endpoints.

Basic commands:
  python ugv_client.py status
  python ugv_client.py move forward --speed 0.3 --duration 1.5
  python ugv_client.py stop
  python ugv_client.py lights --base 255 --head 0
  python ugv_client.py gimbal --x 30 --y 15
  python ugv_client.py gimbal center
  python ugv_client.py photo
  python ugv_client.py video start|stop
  python ugv_client.py cv face

Routine commands:
  python ugv_client.py patrol --duration 120 --scan-mode motion
  python ugv_client.py watch --cv-mode face --no-scan
  python ugv_client.py guard --scan-interval 30 --cv-mode motion
  python ugv_client.py search --target person
  python ugv_client.py routine stop
  python ugv_client.py routine status
  python ugv_client.py events --limit 20

ROS2 commands:
  python ugv_client.py ros2 status
  python ugv_client.py ros2 nav --x 1.0 --y 0.5 --yaw 0
  python ugv_client.py ros2 pub --topic /cmd_vel --type geometry_msgs/msg/Twist --data '{}'
  python ugv_client.py ros2 raw --cmd "ros2 node list" --confirm
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

DEFAULT_HOST = "http://localhost:5000"


def _req(method, host, path, payload=None):
    url  = host.rstrip("/") + path
    data = json.dumps(payload or {}).encode("utf-8") if method == "POST" else None
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"status": "error", "message": body, "code": e.code}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def post(host, path, payload=None):
    return _req("POST", host, path, payload)

def get(host, path):
    return _req("GET", host, path)

def out(result):
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="UGV Robot CLI")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"Flask server URL (default: {DEFAULT_HOST})")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ── Basic ─────────────────────────────────────────────────────────────────
    sub.add_parser("status",  help="Full system + robot status")
    sub.add_parser("stop",    help="Emergency stop (also stops routines)")

    pm = sub.add_parser("move", help="Move robot (auto-stops after duration)")
    pm.add_argument("direction",
                    choices=["forward","backward","left","right","spin_left","spin_right"])
    pm.add_argument("--speed",    type=float, default=0.3, help="0.0-0.8 (default 0.3)")
    pm.add_argument("--duration", type=float, default=1.0, help="0.1-5.0 s (default 1.0)")

    pl = sub.add_parser("lights", help="Control lights")
    pl.add_argument("--base", type=int, default=0, help="Base light 0-255")
    pl.add_argument("--head", type=int, default=0, help="Head light 0-255")

    pg = sub.add_parser("gimbal", help="Pan/tilt or 'center'")
    pg.add_argument("action", nargs="?", choices=["center"])
    pg.add_argument("--x",     type=float, default=0,   help="Pan -180..180")
    pg.add_argument("--y",     type=float, default=0,   help="Tilt -30..90")
    pg.add_argument("--speed", type=int,   default=200, help="1-1000")

    sub.add_parser("photo", help="Capture a photo")

    pv = sub.add_parser("video", help="Video recording")
    pv.add_argument("action", choices=["start","stop"])

    pc = sub.add_parser("cv", help="Set CV detection mode")
    pc.add_argument("mode",
                    choices=["none","motion","face","objects","color",
                             "autodrive","hand","mp_face","pose"])
    pc.add_argument("--confirm", action="store_true",
                    help="Required for autodrive")

    # ── Routines ──────────────────────────────────────────────────────────────
    pp = sub.add_parser("patrol", help="Start patrol routine")
    pp.add_argument("--duration",  type=float, default=120.0, help="Seconds (max 600)")
    pp.add_argument("--speed",     type=float, default=0.25,  help="0.1-0.5")
    pp.add_argument("--scan-mode", default="motion",
                    choices=["motion","face","objects","person","color"])
    pp.add_argument("--lights",  action="store_true", help="Turn on lights during patrol")
    pp.add_argument("--record",  action="store_true", help="Record video during patrol")

    pw = sub.add_parser("watch", help="Watch mode (immobile + CV)")
    pw.add_argument("--cv-mode", default="motion",
                    choices=["motion","face","objects","person","color","hand","pose"])
    pw.add_argument("--no-scan",       action="store_true", help="Disable gimbal scan")
    pw.add_argument("--scan-interval", type=float, default=20.0,
                    help="Seconds between gimbal sweeps")

    pgu = sub.add_parser("guard", help="Guard mode (long-running sentinel)")
    pgu.add_argument("--cv-mode",       default="motion")
    pgu.add_argument("--scan-interval", type=float, default=30.0)
    pgu.add_argument("--max-duration",  type=float, default=7200.0)
    pgu.add_argument("--record-on-detection", action="store_true")
    pgu.add_argument("--confirm", action="store_true",
                     help="Required to start guard mode")

    ps = sub.add_parser("search", help="Gimbal sweep searching for a target")
    ps.add_argument("--target", default="motion",
                    choices=["motion","face","objects","person","color","hand"])
    ps.add_argument("--no-photo", action="store_true", help="Don't take photo on find")

    pr = sub.add_parser("routine", help="Routine control")
    pr.add_argument("action", choices=["stop","status"])

    pe = sub.add_parser("events", help="Show CV/routine event log")
    pe.add_argument("--limit", type=int, default=20, help="Max events to show")

    # ── ROS2 ─────────────────────────────────────────────────────────────────
    pr2 = sub.add_parser("ros2", help="ROS2 integration commands")
    pr2_sub = pr2.add_subparsers(dest="ros2_cmd", required=True)

    pr2_sub.add_parser("status", help="ROS2 availability + nodes + topics")

    pnav = pr2_sub.add_parser("nav", help="Send Nav2 navigation goal")
    pnav.add_argument("--x",   type=float, default=0.0)
    pnav.add_argument("--y",   type=float, default=0.0)
    pnav.add_argument("--yaw", type=float, default=0.0,
                      help="Heading in radians (0=forward)")

    ppub = pr2_sub.add_parser("pub", help="Publish to a ROS2 topic (once)")
    ppub.add_argument("--topic", required=True)
    ppub.add_argument("--type",  required=True, dest="msg_type")
    ppub.add_argument("--data",  default="{}")

    psrv = pr2_sub.add_parser("srv", help="Call a ROS2 service")
    psrv.add_argument("--service", required=True)
    psrv.add_argument("--type",    required=True, dest="srv_type")
    psrv.add_argument("--data",    default="{}")

    praw = pr2_sub.add_parser("raw", help="Run arbitrary ros2 CLI command")
    praw.add_argument("--cmd",     required=True)
    praw.add_argument("--confirm", action="store_true", help="Required for raw commands")

    # ── Dispatch ──────────────────────────────────────────────────────────────
    args = p.parse_args()
    host = args.host

    if args.cmd == "status":
        out(get(host, "/api/ugv/status"))

    elif args.cmd == "stop":
        out(post(host, "/api/ugv/stop"))

    elif args.cmd == "move":
        out(post(host, "/api/ugv/move", {
            "direction": args.direction,
            "speed":     args.speed,
            "duration":  args.duration,
        }))

    elif args.cmd == "lights":
        out(post(host, "/api/ugv/lights", {"base": args.base, "head": args.head}))

    elif args.cmd == "gimbal":
        if args.action == "center":
            out(post(host, "/api/ugv/gimbal/center"))
        else:
            out(post(host, "/api/ugv/gimbal", {"x": args.x, "y": args.y, "speed": args.speed}))

    elif args.cmd == "photo":
        out(post(host, "/api/ugv/photo"))

    elif args.cmd == "video":
        path = "/api/ugv/video/start" if args.action == "start" else "/api/ugv/video/stop"
        out(post(host, path))

    elif args.cmd == "cv":
        payload = {"mode": args.mode}
        if args.mode == "autodrive":
            if not args.confirm:
                print("ERROR: autodrive requires --confirm flag")
                sys.exit(1)
            payload["confirm"] = True
        out(post(host, "/api/ugv/cv/mode", payload))

    elif args.cmd == "patrol":
        out(post(host, "/api/ugv/routine/patrol", {
            "duration":  args.duration,
            "speed":     args.speed,
            "scan_mode": args.scan_mode,
            "lights":    args.lights,
            "record":    args.record,
        }))

    elif args.cmd == "watch":
        out(post(host, "/api/ugv/routine/watch", {
            "cv_mode":      args.cv_mode,
            "scan_gimbal":  not args.no_scan,
            "scan_interval": args.scan_interval,
        }))

    elif args.cmd == "guard":
        if not args.confirm:
            print("ERROR: guard mode requires --confirm flag (long-running autonomous mode)")
            sys.exit(1)
        out(post(host, "/api/ugv/routine/guard", {
            "confirm":              True,
            "cv_mode":              args.cv_mode,
            "scan_interval":        args.scan_interval,
            "max_duration":         args.max_duration,
            "record_on_detection":  args.record_on_detection,
        }))

    elif args.cmd == "search":
        out(post(host, "/api/ugv/routine/search", {
            "target":     args.target,
            "take_photo": not args.no_photo,
        }))

    elif args.cmd == "routine":
        if args.action == "stop":
            out(post(host, "/api/ugv/routine/stop"))
        else:
            out(get(host, "/api/ugv/routine/status"))

    elif args.cmd == "events":
        out(get(host, f"/api/ugv/cv/events?limit={args.limit}"))

    elif args.cmd == "ros2":
        if args.ros2_cmd == "status":
            out(get(host, "/api/ugv/ros2/status"))

        elif args.ros2_cmd == "nav":
            out(post(host, "/api/ugv/ros2/command", {
                "cmd_type": "nav_goal",
                "x": args.x, "y": args.y, "yaw": args.yaw,
            }))

        elif args.ros2_cmd == "pub":
            out(post(host, "/api/ugv/ros2/command", {
                "cmd_type": "topic_pub",
                "topic":    args.topic,
                "type":     args.msg_type,
                "data":     args.data,
                "once":     True,
            }))

        elif args.ros2_cmd == "srv":
            out(post(host, "/api/ugv/ros2/command", {
                "cmd_type": "service_call",
                "service":  args.service,
                "type":     args.srv_type,
                "data":     args.data,
            }))

        elif args.ros2_cmd == "raw":
            if not args.confirm:
                print("ERROR: raw ROS2 commands require --confirm flag")
                sys.exit(1)
            out(post(host, "/api/ugv/ros2/command", {
                "cmd_type": "raw",
                "cmd":      args.cmd,
                "confirm":  True,
            }))


if __name__ == "__main__":
    main()
