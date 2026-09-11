"""Lance — the UGV's local AI brain.

Wake word "hey Lance" starts a session; the spoken request is parsed by a
small local LLM (Ollama, models on the Pi) into a robot action, executed
through the OpencvFuncs object, and answered in a high-pitched minion-style
voice by the caller.

Everything robot-facing goes through the `robot` argument (an OpencvFuncs
instance) so this module stays testable with a stub and never imports the
app stack. Only the Python standard library is used on purpose.

Model sizing: qwen2.5:1.5b (Q4) runs in ~1.2GB RAM — fits the Pi 5's 4GB.
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("lance")

OLLAMA_URL = os.environ.get("LANCE_OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("LANCE_MODEL", "qwen2.5:1.5b")
OLLAMA_BIN = os.path.expanduser(os.environ.get("LANCE_OLLAMA_BIN", "~/ollama/bin/ollama"))
# Pi install: models live here (rootfs SD; the exfat NVMe proved unusable).
MODELS_DIR = os.environ.get("LANCE_MODELS_DIR", "/home/ws/ollama-models")

SYSTEM_PROMPT = """You are Lance, the voice-controlled brain of a 4-wheel UGV robot car.
The user speaks a command; reply with ONE JSON object only:
{"action": "...", "params": {...}, "say": "..."}

Available actions:
- drive     params: {"dir": "forward|backward|left|right", "seconds": 1..4, "speed": 0.1..0.6}
            Drive in that direction for `seconds` then stop automatically. Default seconds 2, speed 0.4.
- spin      params: {"dir": "left|right", "degrees": 45..360}  Turn in place.
- stop      params: {}  Stop immediately, all motors.
- lights    params: {"on": true|false}  Headlights on or off.
- picture   params: {}  Take a photo.
- video     params: {"rec": true|false}  Start or stop recording video.
- self_drive params: {"on": true|false}  start/stop the learning self-driver (LIDAR + camera learning, drives on its own and remembers the room)
- selfdrive params: {"on": true|false}  same as self_drive — enable or disable learning self-drive
- approach  params: {"object": "chair"}  Drive toward ONE named object the camera can see: "drive towards the chair", "go to the door", "head for the person", "approach the table". Turns self-drive on and steers at that object until it is about 0.6m away, then stops.
- map       params: {"action": "status|save|clear"}  Report / persist / wipe the learned surroundings (walls + objects).
- avoidance params: {"on": true|false}  LIDAR obstacle avoidance on or off.
- capable params: {"on": true|false}  enable or disable standalone self-driving mode (same as selfdrive)
- gimbal    params: {"dir": "up|down|left|right"}  Tilt/pan the camera head.
- detect    params: {}  LOOK through the camera and NAME the objects in front of the robot. Use for: "what do you see", "detect", "look at", "identify", "what's in front of you", "what is that". NEVER use gimbal for these.
- learn     params: {"name": "stapler"}  The user TEACHES you a new object they are showing you ("learn that this is a stapler", "this is called a mug", "what you're looking at is a banana"). Add it to your vocabulary so you can recognize it forever.
- status    params: {"what": "battery|lidar|all"}  Report robot state.
- chat      params: {}  For greetings, thanks, jokes, or anything with no robot action.

Rules:
- If the request names an object to travel to, the action is approach — never drive, which only moves for a couple of seconds.
- "say" is your short spoken reply — 1 sentence, friendly, minion-style enthusiasm.
- Pick exactly one action. If the command is ambiguous or unsafe, use "chat" and say what you need.
- Never invent actions. Never reply with anything but a JSON object.
"""


def _post(path, payload, timeout=120):
    req = urllib.request.Request(
        OLLAMA_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _get(path, timeout=3):
    req = urllib.request.Request(OLLAMA_URL + path)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def ollama_alive():
    try:
        _get("/api/tags", timeout=3)
        return True
    except Exception:
        return False


def ensure_ollama():
    """Start the user-level ollama serve if it is not already running."""
    if ollama_alive():
        return True
    if not os.path.exists(OLLAMA_BIN):
        log.error("ollama binary missing at %s", OLLAMA_BIN)
        return False
    env = dict(os.environ)
    if MODELS_DIR:
        env["OLLAMA_MODELS"] = MODELS_DIR
    env.setdefault("OLLAMA_HOST", "127.0.0.1:11434")
    try:
        subprocess.Popen(
            [OLLAMA_BIN, "serve"],
            stdout=open("/tmp/ollama_serve.log", "a"),
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    except Exception as e:
        log.error("failed to start ollama serve: %s", e)
        return False
    for _ in range(20):  # wait up to ~20s for the server to come up
        if ollama_alive():
            return True
        time.sleep(1)
    return False


def ask(text, timeout=180):
    """Run the model with JSON output forced; returns the parsed action dict."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 1024},
    }
    data = _post("/api/chat", payload, timeout=timeout)
    content = (data.get("message") or {}).get("content", "")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Model sometimes wraps the JSON in backticks or chatter — salvage it.
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("model returned non-JSON: %r" % content[:200])
        parsed = json.loads(content[start : end + 1])
    if not isinstance(parsed, dict) or "action" not in parsed:
        raise ValueError("model returned unexpected shape: %r" % parsed)
    return parsed


# ── action execution ────────────────────────────────────────────────────────

def _stop(robot):
    robot.send_base_command({"T": 1, "L": 0.0, "R": 0.0})
    sd = getattr(robot, "self_driver", None)
    if sd is not None:
        try:
            sd.clear_target()      # stopping also gives up whatever we chased
        except Exception:
            pass


def _drive(robot, params, say):
    d = (params.get("dir") or "forward").lower()
    secs = float(params.get("seconds", 2))
    speed = float(params.get("speed", 0.4))
    speed = max(0.1, min(0.6, speed))
    secs = max(0.5, min(4.0, secs))
    if d in ("forward", "fwd", "forwards"):
        l, r = speed, speed
        label = "forward"
    elif d in ("backward", "back", "backwards", "reverse"):
        l, r = -speed, -speed
        label = "backward"
    elif d in ("left", "turn left"):
        l, r = -speed, speed  # tank turn (Command Center convention)
        label = "left"
    elif d in ("right", "turn right"):
        l, r = speed, -speed
        label = "right"
    else:
        return f"I didn't understand which way to go."
    robot.send_base_command({"T": 1, "L": l, "R": r})
    threading.Timer(secs, _stop, args=(robot,)).start()
    return f"Driving {label} for {int(round(secs))} seconds."


def _spin(robot, params, say):
    d = (params.get("dir") or "right").lower()
    deg = float(params.get("degrees", 90))
    speed = 0.45
    if d in ("left", "counterclockwise"):
        l, r = -speed, speed
    else:
        l, r = speed, -speed
    robot.send_base_command({"T": 1, "L": l, "R": r})
    secs = max(0.4, min(3.0, deg / 90.0 * 0.7))
    threading.Timer(secs, _stop, args=(robot,)).start()
    return f"Spinning {d}."


def _lights(robot, params, say):
    on = bool(params.get("on"))
    robot.head_light_ctrl(2 if on else 0)
    return "Lights on!" if on else "Lights off."


def _status(robot, params, say):
    what = (params.get("what") or "all").lower()
    bits = []
    if what in ("battery", "all"):
        b = getattr(robot, "battery_level", None)
        bits.append(
            f"battery at {int(b)} percent" if isinstance(b, (int, float)) else "no battery reading yet"
        )
    if what in ("lidar", "all"):
        d = _nearest(robot)
        bits.append(f"nearest obstacle {d:.2f} meters" if d is not None else "lidar has no reading yet")
    if what in ("camera", "all") and "camera" in what:
        pass
    return " ".join(bits) if bits else "I've got nothing to report yet."


def _nearest(robot):
    try:
        rl = robot.base_ctrl.rl
        dists = rl.lidar_distances_show
        if dists:
            return min(d for d in dists if d and d > 0) / 1000.0
    except Exception:
        pass
    return None


def _auto_drive(robot, params, say):
    on = bool(params.get("on"))
    robot.execute_command("start_auto_drive" if on else "stop_auto_drive")
    return "Driving on my own, boss! I'll learn the room as I go." if on else "Auto drive stopped — map saved."

def _self_drive(robot, params, say):
    if bool(params.get("on")):
        robot.self_driver.enable()
        return "Self-drive on — I'm learning the room as I move."
    robot.self_driver.disable()
    return "Self-drive off — map saved."


def _approach(robot, params, say):
    """Drive toward one named object the camera can see."""
    name = (params.get("object") or params.get("name")
            or params.get("target") or "").strip()
    if not name:
        return "Which object should I drive toward, boss?"
    sd = getattr(robot, "self_driver", None)
    if sd is None or not hasattr(sd, "pursue"):
        return "My self-driving brain isn't ready yet, boss."
    if not sd.pursue(name):
        return "I couldn't start driving toward the %s." % name
    time.sleep(0.8)  # let the planner see one round of camera detections
    target = sd.status().get("target") or {}
    if target.get("seen"):
        bearing = target.get("bearing_deg") or 0.0
        side = "left" if bearing > 5 else ("right" if bearing < -5 else "centre")
        return ("Driving toward the %s — I can see it %s metres away, %s of me."
                % (name, target.get("range_m"), side))
    return ("I can't see a %s yet, so I'm sweeping to look for one — "
            "point me at it and I'll head over." % name)

def _selfdrive(robot, params, say):
    # alias for self_drive (some utterances say 'selfdrive on/off')
    return _self_drive(robot, params, say)

def _capable(robot, params, say):
    if bool(params.get("on")):
        robot.self_driver.enable()
        return "Capable mode on — I'll drive and learn on my own."
    robot.self_driver.disable()
    return "Capable mode off — map saved."


def _map(robot, params, say):
    """Report or persist the learned surroundings (walls + objects)."""
    action = (params.get("action") or "status").lower()
    sd = getattr(robot, "self_driver", None)
    if sd is None:
        return "I haven't started learning the room yet, boss."
    mem = sd.memory
    if action == "save":
        sd.save_memory()
        return (f"Saved my map of the room — {mem.busy_cells} obstacle cells, "
                f"{len(mem.objects)} objects remembered.")
    if action == "clear":
        mem.clear()
        return "Map cleared — I'll relearn the room as I drive."
    objs = ", ".join(sorted({o['name'] for o in mem.objects})[:8]) or "none yet"
    return (f"I've mapped {mem.busy_cells} obstacle cells and learned: {objs}. "
            "Drive around and I'll learn more.")


def _avoidance(robot, params, say):
    on = bool(params.get("on"))
    avoider = getattr(robot, "avoider", None)
    if avoider is None:
        return "I can't reach the avoidance controller."
    try:
        avoider.resume() if on else avoider.pause()
        return "Avoidance on." if on else "Avoidance off — be careful!"
    except Exception as e:
        log.error("avoidance toggle failed: %s", e)
        return "I couldn't toggle avoidance."


def _picture(robot, params, say):
    robot.picture_capture()
    return "Cheese! Photo taken."


def _video(robot, params, say):
    robot.video_record(bool(params.get("rec")))
    return "Recording started." if params.get("rec") else "Recording stopped."


def _gimbal(robot, params, say):
    d = (params.get("dir") or "up").lower()
    try:
        if d in ("up", "down"):
            robot.base_ctrl.gimbal_base_ctrl(0, 120 if d == "up" else -120, 40)
        else:
            robot.base_ctrl.gimbal_base_ctrl(120 if d == "right" else -120, 0, 40)
        return f"Looking {d}."
    except Exception as e:
        log.error("gimbal failed: %s", e)
        return "I couldn't move the camera."


def _detect(robot, params, say):
    """Look through the camera and describe what's in front of the robot."""
    try:
        if not hasattr(robot, 'detect_scene'):
            return "I don't have eyes yet, boss!"
        description = robot.detect_scene()
        return description
    except Exception as e:
        log.error("detect failed: %s", e)
        return "Something went wrong with my eyes."


def _learn(robot, params, say):
    """Self-learning: teach Lance a new object name so it can recognize it.
    If the user is currently self-driving, also announce it into the planner
    so the robot records this object as part of its surroundings."""
    name = (params.get("name") or "").strip()
    if not name:
        return "What should I learn? Tell me the object's name!"
    if not hasattr(robot, 'learn_object'):
        return "I can't learn new things yet, boss!"
    result = robot.learn_object(name)
    # If self-drive is active, log the new known object into the map too so the
    # robot treats it as a remembered obstacle even if the camera isn't looking now.
    sd = getattr(robot, 'self_driver', None)
    if sd is not None and sd.active:
        try:
            last = (getattr(robot, 'last_detections', None) or [{}])[0]
            box = last.get('box')
            if box:
                cx = (box[0] + box[2]) / 2.0
                # + = left in the planner's robot frame (same as self_drive).
                bearing = round((0.5 - cx / 640.0) * 60.0, 1)
                sd.memory.observe_object(name, bearing, 0.5, 1.0)
                sd.save_memory()
        except Exception:
            pass
    return result


ACTIONS = {
    "drive": _drive,
    "spin": _spin,
    "stop": lambda robot, p, s: (_stop(robot), "Stopped!")[1],
    "lights": _lights,
    "picture": _picture,
    "video": _video,
    "auto_drive": _auto_drive,
    "self_drive": _self_drive,
    "selfdrive": _selfdrive,
    "approach": _approach,
    "goto": _approach,
    "go_to": _approach,
    "drive_to": _approach,
    "capable": _capable,
    "avoidance": _avoidance,
    "map": _map,
    "gimbal": _gimbal,
    "detect": _detect,
    "learn": _learn,
    "status": _status,
}


_LOCK = threading.Lock()  # serialize voice-loop + Command Center chat requests


# ── "drive to the <object>" intent ───────────────────────────────────────────
# Read deterministically instead of asking the language model. The model's own
# prompt advertises "drive towards the chair" as the approach example and it
# still answered that exact phrase with a plain two-second forward drive, so
# the one thing the user asked for was the one thing that did not happen. A
# phrase written down as a pattern cannot be mis-routed, and it needs no model
# round trip.
_PURSUIT_VERBS = (r"(?:drive|go|head|move|navigate|steer|walk|travel|bring|"
                  r"park|roll|approach|visit)")
_PURSUIT_PREPS = (r"(?:towards|toward|over\s+to|up\s+to|next\s+to|beside|"
                  r"near|to|for|at|into|onto)")
_PURSUIT_TAIL = (r"\s+(?:the\s+|a\s+|an\s+|that\s+|this\s+|my\s+|your\s+|"
                 r"some\s+)?([a-z][a-z0-9 _-]{0,30})")
# "drive/go/head ... to X"
_PURSUIT_RE = re.compile(
    r"\b" + _PURSUIT_VERBS + r"\b[^.!?]{0,24}?\b" + _PURSUIT_PREPS + _PURSUIT_TAIL,
    re.IGNORECASE)
# "approach X" takes its object directly, with no preposition.
_PURSUIT_DIRECT_RE = re.compile(r"\b(?:approach|visit)\b" + _PURSUIT_TAIL,
                                re.IGNORECASE)

# A word that can follow "to" without being something worth driving at.
_NOT_AN_OBJECT = {
    "forward", "back", "backward", "backwards", "rear", "left", "right",
    "straight", "ahead", "up", "down", "home", "there", "here", "away",
    "around", "about", "side", "place", "spot", "somewhere", "anywhere",
    "nowhere", "it", "me", "you", "us", "them", "him", "her",
    "fast", "slow", "slowly", "quickly", "carefully",
}
# Stipped from the front of a phrase, rejected when it is all there is
# ("drive to the" names nothing).
_DETERMINERS = {"the", "a", "an", "that", "this", "my", "your", "our",
                "some"}
# "drive to 2 metres" is a distance and a time, not an object.
_MEASURE_WORDS = {
    "second", "seconds", "sec", "secs", "minute", "minutes", "metre",
    "metres", "meter", "meters", "centimetre", "centimetres", "foot",
    "feet", "inch", "inches", "bit", "while", "moment", "half",
}
# The object phrase ends at the first of these: "drive to the bin and then
# forward" is a request about a bin, not about "bin and then".
_CLAUSE_BREAKS = {
    "and", "then", "but", "or", "after", "before", "while", "next",
    "for", "to", "at", "in", "on", "near", "beside", "with", "from",
    "when", "if",
}
_TRAILING_FILLER = {
    "please", "now", "thanks", "thank", "you", "boss", "ok", "okay",
    "mate", "buddy", "quickly", "slowly", "carefully",
}


def parse_pursuit_intent(text):
    """Name the object a 'drive to X' request is asking for, else None.

    None for everything that is not a request to travel to a named object, so
    all the other phrasings still go to the language model.
    """
    match = _PURSUIT_RE.search(text or "") or _PURSUIT_DIRECT_RE.search(text or "")
    if not match:
        return None
    words = [w for w in re.split(r"[^a-z0-9]+", match.group(1).lower()) if w]
    for i, word in enumerate(words):
        if word in _CLAUSE_BREAKS:
            words = words[:i]
            break
    while words and words[-1] in _TRAILING_FILLER:
        words.pop()
    if len(words) > 1 and words[0] in _DETERMINERS:
        words = words[1:]           # "the 3rd chair" -> "3rd chair"
    if not words or words[0] in _NOT_AN_OBJECT \
            or words[0] in _DETERMINERS or words[0] in _MEASURE_WORDS:
        return None
    if any(w in _MEASURE_WORDS for w in words):
        return None
    return " ".join(words[:3])


def handle(text, robot):
    """Serialize Lance requests (voice loop and the chat UI share the robot)."""
    with _LOCK:
        return _handle(text, robot)


def _handle(text, robot):
    """Full cycle: ensure Ollama, parse `text` into an action, execute it.

    Returns the spoken reply string (the caller voices it).
    """
    # A request to travel to a named object is handled here rather than by the
    # model (see parse_pursuit_intent), which also makes it work while Ollama
    # is still waking up.
    object_name = parse_pursuit_intent(text)
    if object_name is not None and getattr(robot, "self_driver", None) is not None:
        log.info("lance: pursuit intent %r -> approach", object_name)
        try:
            return _approach(robot, {"object": object_name}, "")
        except Exception as e:      # same handling as any other action
            log.error("lance pursuit intent %r failed: %s", object_name, e)
            _stop(robot)
            return "Something went wrong driving to that."
    if not ensure_ollama():
        return "My brain isn't loaded. Try again in a minute."
    try:
        parsed = ask(text)
    except Exception as e:
        log.error("lance parse failed: %s", e)
        return "Sorry, I couldn't understand that. Try again?"
    action = (parsed.get("action") or "chat").lower()
    params = parsed.get("params") or {}
    say = (parsed.get("say") or "").strip()
    log.info("lance: action=%s params=%s say=%s", action, params, say)
    fn = ACTIONS.get(action)
    if fn is None:  # chat / unknown — just voice the model's reply
        return say or "Hi boss!"
    try:
        executed = fn(robot, params, say)
    except Exception as e:
        log.error("lance action %s failed: %s", action, e)
        _stop(robot)
        return f"Something went wrong doing that. {say}".strip()
    # Prefer the executed confirmation; the model's "say" wins for status/chat.
    if action in ("status",):
        return executed
    return executed