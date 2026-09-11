import cv2
import imutils
import mediapipe as mp
import imageio
import threading
import numpy as np
import math
import time
import random
import yaml
import serial
import torch
import os
import json
import subprocess
import datetime
import pygame
from gtts import gTTS
import speech_recognition as sr  # Import the speech recognition library
from threading import Thread
from collections import deque
import azure.cognitiveservices.speech as speechsdk
import textwrap
import logging
from sklearn.linear_model import LinearRegression
import pyttsx3
from datetime import datetime  # Ensure this is imported correctly
# Libraries for CSI camera
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, Encoder
from picamera2.outputs import FfmpegOutput
import sys

# libraries for oak camera (upstream OAK-D support; optional dependency)
try:
    import depthai as dai
except ImportError:
    dai = None

# config file.
curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/config.yaml', 'r') as yaml_file:
    f = yaml.safe_load(yaml_file)

# Seed vocabulary for Lance's open-vocabulary vision (YOLO-World). The COCO-80
# classes plus a broad list of common household/office objects. Lance self-learns
# beyond this: learn_object() appends to known_objects.json which persists across
# restarts. Names are matched by CLIP text embeddings, so synonyms work too.
DEFAULT_KNOWN_OBJECTS = [
    # --- COCO-80 ---
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
    # --- kitchen ---
    "coffee mug", "glass", "plate", "pan", "pot", "kettle", "frying pan",
    "spatula", "cutting board", "blender", "coffee maker", "water bottle",
    "thermos", "lunch box", "cereal box", "bread", "bagel", "muffin", "cheese",
    "yogurt", "eggs", "milk carton", "butter", "jam", "peanut butter", "cereal",
    "pasta", "rice", "soup", "salad", "fries", "burger", "taco", "sushi",
    "cookie", "brownie", "pie", "ice cream", "popcorn", "chips", "pretzel",
    "crackers", "nuts", "candy", "chocolate bar", "salt shaker", "pepper shaker",
    "sugar bowl", "honey", "syrup", "ketchup", "mustard", "mayonnaise", "vinegar",
    "olive oil", "spices", "napkin", "paper towel", "aluminum foil", "plastic wrap",
    "trash can", "recycling bin", "dishwasher", "stove", "grill", "barbecue",
    "mug", "sponge", "dish rack", "sink faucet",
    # --- office ---
    "stapler", "pen", "pencil", "crayon", "marker", "highlighter", "ruler",
    "eraser", "tape", "sticky note", "notebook", "paper", "folder", "envelope",
    "calculator", "printer", "scanner", "desk", "whiteboard", "projector",
    "webcam", "headphones", "earbuds", "speaker", "microphone", "usb drive",
    "hard drive", "charger", "power strip", "extension cord", "battery",
    "game controller", "tablet", "smartwatch", "tripod", "drone", "remote control",
    "camera", "flashlight",
    # --- furniture / home ---
    "sofa", "loveseat", "recliner", "armchair", "ottoman", "coffee table",
    "end table", "nightstand", "dresser", "wardrobe", "bookshelf", "bookcase",
    "shelf", "cabinet", "drawer", "stool", "mattress", "pillow", "blanket",
    "comforter", "sheet", "rug", "carpet", "curtain", "blinds", "mirror",
    "picture frame", "painting", "poster", "alarm clock", "wall clock", "candle",
    "lamp", "floor lamp", "ceiling fan", "chandelier", "plant", "flower pot",
    "flower", "globe", "aquarium", "fish tank",
    # --- tools ---
    "hammer", "nail", "screw", "screwdriver", "wrench", "pliers", "drill",
    "saw", "axe", "shovel", "rake", "lawn mower", "ladder", "tape measure",
    "level", "utility knife", "duct tape", "rope", "chain", "padlock", "key",
    "keychain", "safety goggles", "work gloves", "hard hat", "tool box",
    "workbench", "paintbrush", "paint roller", "watering can", "garden hose",
    "wheelbarrow", "headlamp",
    # --- toys ---
    "doll", "action figure", "toy car", "toy train", "lego", "building blocks",
    "puzzle", "board game", "chess set", "playing cards", "dice", "stuffed animal",
    "rubber duck", "balloon", "bubbles", "yo-yo", "play-doh", "video game",
    "game console", "rattle", "pacifier", "baby bottle", "stroller", "crib",
    "high chair",
    # --- sports / outdoor ---
    "soccer ball", "basketball", "football", "volleyball", "baseball",
    "tennis ball", "golf ball", "golf club", "hockey stick", "hockey puck",
    "ping pong paddle", "pool cue", "dart", "dartboard", "bowling ball",
    "fishing rod", "fishing reel", "sled", "ice skates", "roller skates",
    "scooter", "unicycle", "helmet", "knee pads", "whistle", "stopwatch",
    "hula hoop", "jump rope", "trampoline", "swing", "slide", "sandbox",
    "camping tent", "sleeping bag", "campfire", "fire pit", "picnic basket",
    "cooler", "hiking boots", "duffel bag", "passport", "wallet", "money",
    # --- clothing / accessories ---
    "shirt", "t-shirt", "polo shirt", "dress shirt", "blouse", "sweater",
    "hoodie", "cardigan", "jacket", "coat", "trench coat", "parka", "raincoat",
    "vest", "blazer", "suit", "bow tie", "scarf", "gloves", "mittens", "hat",
    "cap", "beanie", "beret", "cowboy hat", "sun hat", "earmuffs", "face mask",
    "headband", "hair clip", "comb", "brush", "razor", "toothpaste", "dental floss",
    "mouthwash", "tissue", "toilet paper", "hand sanitizer", "soap", "shampoo",
    "conditioner", "lotion", "sunscreen", "lip balm", "lipstick", "mascara",
    "nail polish", "perfume", "cologne", "deodorant", "towel",
    # --- electronics ---
    "smartphone", "desktop computer", "monitor", "screen", "television", "router",
    "modem", "external hard drive", "sd card", "sim card", "headset", "dslr camera",
    "camcorder", "action camera", "vr headset", "fitness tracker", "e-reader",
    "kindle", "soundbar", "subwoofer", "turntable", "record player", "vinyl record",
    "cd", "dvd", "power bank", "solar panel", "light bulb", "led bulb", "night light",
    "laser pointer", "tv remote", "smart speaker", "smart bulb", "security camera",
    "baby monitor", "walkie talkie",
    # --- fruit / veg / drink extras ---
    "grapes", "strawberries", "blueberries", "watermelon", "pineapple", "mango",
    "peach", "pear", "lemon", "lime", "tomato", "potato", "onion", "garlic",
    "cucumber", "bell pepper", "avocado", "corn", "lettuce", "spinach", "mushroom",
    "pumpkin", "sweet potato", "zucchini", "eggplant", "canned food", "jar", "can",
    "soda can", "juice box", "coffee", "tea", "smoothie", "beer bottle",
    "wine bottle", "soda bottle", "coconut", "cherries", "melon", "chili pepper",
    "pickle", "olive",
]

# Confidence bar for open-vocabulary detection. YOLO-World scores run cooler than
# closed-set COCO, but 0.15 over-reports (e.g. "sim card" for a phone); 0.30 keeps
# real objects while cutting most of the noise.
WORLD_DETECT_CONF = 0.30

# Near-duplicate vocabulary entries: when both fire on the same object, report
# them under one canonical name (e.g. "monitor" + "screen" -> "monitor").
SYNONYM_GROUPS = {
    "monitor": ["screen", "display"],
    "tv": ["television"],
    "laptop": ["notebook"],
    "cell phone": ["smartphone", "mobile phone", "iphone"],
    "mug": ["coffee mug", "coffee cup"],
    "couch": ["sofa", "loveseat"],
    "bookshelf": ["bookcase"],
    "plant": ["potted plant", "houseplant"],
    "remote": ["remote control", "tv remote"],
    "bottle": ["water bottle"],
    "pan": ["frying pan", "skillet"],
    "headphones": ["headset", "earbuds", "earphones"],
    "clock": ["wall clock"],
    "speaker": ["smart speaker"],
}
_SYNONYM_ALIAS_MAP = {alias: canon for canon, aliases in SYNONYM_GROUPS.items() for alias in aliases}

_IRREGULAR_PLURALS = {
    "person": "people", "mouse": "mice", "child": "children", "foot": "feet",
    "tooth": "teeth", "man": "men", "woman": "women", "goose": "geese",
    "die": "dice", "cactus": "cacti", "knife": "knives", "leaf": "leaves",
    "shelf": "shelves", "half": "halves", "life": "lives", "loaf": "loaves",
    "tomato": "tomatoes", "potato": "potatoes",
}

# Nouns already plural (never add an s):
_PLURAL_ONLY = {"goggles", "scissors", "pants", "glasses", "sunglasses",
                 "trousers", "pliers", "jeans", "shorts", "binoculars",
                 "headphones", "earbuds"}


def _pluralize(word):
    """Pluralize a count noun: 'juice box' -> 'juice boxes', 'berry' -> 'berries'."""
    w = word.strip().lower()
    if w in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[w]
    if w in _PLURAL_ONLY:
        return w
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return w[:-1] + "ies"
    if w.endswith("fe"):
        return w[:-2] + "ves"
    if w.endswith("f"):
        return w[:-1] + "ves"
    return w + "s"


def _article(word):
    """'a' vs 'an' for a singular noun ('an egg', 'a laptop')."""
    return "an" if word.strip().lower()[:1] in "aeiou" else "a"


def _iou(a, b):
    """Intersection-over-union of two [x1, y1, x2, y2] boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    a_area = (a[2] - a[0]) * (a[3] - a[1])
    b_area = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (a_area + b_area - inter)


# Configure logging
logging.basicConfig(filename='Log.txt', 
                    level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

logging.basicConfig(filename='log_commands.txt', level=logging.INFO, format='%(asctime)s - %(message)s')

# NOTE: the old OpenAI API key was removed — Lance uses the local Ollama model.
logging.basicConfig(level=logging.INFO)

# Ensure this is outside the class definition
if __name__ == "__main__":
    # Instantiate the OpencvFuncs class and start listening for wake word
    opencv_funcs = OpencvFuncs(project_path="/home/ws/ugv_rpi", base_ctrl="base_controller")
    opencv_funcs.start_listening()

class OpencvFuncs():
    """docstring for OpencvFuncs"""
    def __init__(self, project_path, base_ctrl, lidar_port="/dev/ttyAMA0", baud_rate=115200, max_distance=0.5):
        # Any other initializations
        self.speech_config = speechsdk.SpeechConfig(subscription="702d957143704526a6687ac6cde18194", region="eastus2")
        self.speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"  # Choose a voice you like
        #auto response systems
        self.wake_word = "hey lance"  # Wake word for activation
        self.wake_aliases = ("hey lance", "hi lucy", "hello lance", "hey lucy")
        self.command_log_file = 'log_commands.txt'

        self.listening = False  # Flag for wake word detection status
        # Initialize a lock for the microphone
        self.mic_lock = threading.Lock()
        # Add initialization for listening and toggle-related attributes
        self.listening_active = False  # Tracks if listening mode is active
        self.listening_thread = None   # Store the listening thread
        self.speech_lock = threading.Lock()  # Prevents overlapping accesses to the microphone
        self.project_path = project_path
        self.base_ctrl = base_ctrl
        self.prev_error = 0
        self.integral_error = 0
        self.line_memory = deque(maxlen=100)  # Store recent line positions and features
        self.model = LinearRegression()  # Linear model to predict line position adjustments

        # Gesture and person detection initializations
        self.gesture_enabled = True
        self.person_detected = False
        self.robot_moving = True
        self.speaking = False

        self.cv_event = threading.Event()
        self.cv_event.clear()
        self.cv_mode = f['code']['cv_none']
        self.detection_reaction_mode = f['code']['re_none']

        self.this_path = project_path
        self.photo_path = self.this_path + '/templates/pictures/'
        self.video_path = self.this_path + '/templates/videos/'
        self.frame_scale = 1
        self.picture_capture_flag = False
        self.set_video_record_flag = False
        self.video_record_status_flag = False
        self.writer = None
        self.overlay = None
        self.scale_rate = 1
        self.video_quality = f['video']['default_quality']

        # cv ctrl info
        self.cv_light_mode = 0
        self.pan_angle = 0
        self.tilt_angle = 0
        self.video_fps = 0
        self.fps_start_time = time.time()
        self.fps_count = 0
        self.cv_movtion_lock = False  # Corrected default value
        self.aimed_error = f['cv']['aimed_error']
        self.track_spd_rate = f['cv']['track_spd_rate']
        self.track_acc_rate = f['cv']['track_acc_rate']
        self.CMD_GIMBAL = f['cmd_config']['cmd_gimbal_ctrl']
        self.sampling_rad = f['cv']['sampling_rad']

        # reaction
        self.last_frame_capture_time = datetime.now()  # Correct usage
        self.last_movtion_captured = datetime.now()  # Correct usage

        # movtion detection
        self.avg = None
        self.cv_motion_lock = False  # Initialize cv_motion_lock
        self.integral = 0.0
        self.lidar_distance = float('inf')
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty('volume', 10.0)  # Set volume to maximum (1.0 is the max)
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.detected_people = 0
        self.lidar_distance_left = 0
        self.lidar_distance_right = 0
        self.last_announcement_time = 0.0
        self.announcement_cooldown = 15  # Cooldown of 10 seconds between announcements
        self.battery_level = None  # Last battery % reported by the base controller
        self.speaking = False  # Flag to check if robot is already speaking

        # face detection & tracking
        self.faceCascade = cv2.CascadeClassifier(self.this_path + '/models/haarcascade_frontalface_default.xml')
        self.min_radius = f['cv']['min_radius']
        self.track_faces_iterate = f['cv']['track_faces_iterate']

        # color detection
        self.points = deque(maxlen=32)
        self.color_list = {
            'red': [np.array([0, 200, 170]), np.array([10, 255, 255])],
            'green': [np.array([50, 130, 130]), np.array([78, 255, 255])],
            'blue': [np.array([90, 160, 150]), np.array([105, 255, 255])]
        }
        if f['cv']['default_color'] in self.color_list:
            self.color_lower = self.color_list[f['cv']['default_color']][0]
            self.color_upper = self.color_list[f['cv']['default_color']][1]
        else:
            self.color_lower = np.array(f['cv']['color_lower'])
            self.color_upper = np.array(f['cv']['color_upper'])
        self.track_color_iterate = f['cv']['track_color_iterate']

        # Load the pre-trained model (already initialized)
        self.net = cv2.dnn.readNetFromCaffe(
            self.this_path + '/models/deploy.prototxt', 
            self.this_path + '/models/mobilenet_iter_73000.caffemodel'
        )
        
        # List of class names the model can detect
        self.class_names = ["background", "aeroplane", "bicycle", "bird", "boat",
                            "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
                            "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
                            "sofa", "train", "tvmonitor"]

        # YOLOv8 model for broader object detection (80 COCO classes)
        self.yolo_model = None
        self.last_detections = []  # Latest detection results for Lance to access
        self.last_frame_for_detect = None  # Latest frame for on-demand detection
        try:
            from ultralytics import YOLO
            self.yolo_model = YOLO('yolov8n.pt')  # nano model — fast on Pi
            logging.info("YOLOv8 loaded successfully")
        except Exception as e:
            logging.warning("YOLOv8 not available, falling back to MobileNet: %s", e)

        # Open-vocabulary learning (YOLO-World): knows COCO + every object Lance
        # has been taught. Self-learns: learn_object() adds names to the persistent
        # known_objects.json vocabulary and re-embeds only the new name.
        self.known_objects_path = os.path.join(thisPath, 'known_objects.json')
        self.world_embeddings_path = os.path.join(thisPath, 'world_embeddings.pkl')
        self.known_objects, self.object_facts = self._load_known_objects()
        self.world_model = None  # lazy-loaded YOLO-World (heavy; background warmup)
        self.world_ready = False
        self._world_lock = threading.Lock()
        self._world_warmup_started = False
        self._start_world_warmup()

        # mediapipe
        self.mpDraw = mp.solutions.drawing_utils

        # MediaPipe setup for hands
        self.mpHands = mp.solutions.hands
        self.hands = self.mpHands.Hands(max_num_hands=1)
        self.mpDraw = mp.solutions.drawing_utils

        # findline autodrive
        self.sampling_line_1 = 0.6
        self.sampling_line_2 = 0.6
        self.slope_impact = 1.5
        self.base_impact = 0.005
        self.speed_impact = 0.6
        self.line_track_speed = 0.5  # Unified definition
        self.slope_on_speed = 0.4
        self.line_lower = np.array([25, 150, 70])
        self.line_upper = np.array([42, 255, 255])

        # mediapipe detect faces
        self.mp_face_detection = mp.solutions.face_detection
        self.face_detection = self.mp_face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)

        # mediapipe detect pose
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(static_image_mode=False, 
                                      model_complexity=1, 
                                      smooth_landmarks=True, 
                                      min_detection_confidence=0.5, 
                                      min_tracking_confidence=0.5)

        # base data
        self.show_base_info_flag = False
        self.recv_deque = deque(maxlen=20)

        # info update
        self.show_info_flag = True
        self.info_update_time = time.time()
        self.info_deque = deque(maxlen=10)
        self.info_scale = 270 / 480
        self.info_bg_color = (0, 0, 0)
        self.info_show_time = 10
        self.recv_line_max = 26

        # LIDAR Initialization
        self.lidar_port = lidar_port
        self.baud_rate = baud_rate
        self.max_distance = max_distance
        self.lidar_data = []
        self.lidar_lock = threading.Lock()
        self.steering_history = []  # To smooth out steering changes

        # mission funcs
        self.mission_flag = False

        # osd settings
        self.add_osd = f['base_config']['add_osd']

        # Camera type detection and initialization
        self.usb_camera_connected = self.usb_camera_detection()
        # Lidar/odometry data comes from base_ctrl (rl.lidar_* and base_data).
        # Never open /dev/ttyAMA0 here - that is the ESP32 link, and a second
        # handle corrupts base_ctrl's serial stream (drive stops responding).
        self.lidar_serial = None
        self.csi_camera_connected = False
        self.oak_camera_connected = False

        # Initialize USB camera if connected
        if self.usb_camera_connected:
            try:
                self.camera = cv2.VideoCapture(0)
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, f['video']['default_res_w'])
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, f['video']['default_res_h'])
                if not self.camera.isOpened():
                    logging.error("USB camera failed to initialize.")
            except Exception as e:
                logging.error(f"Error initializing USB camera: {e}")
                self.camera = None  # Handle failure to initialize
        else:
            self.camera = None  # No USB camera connected

        # Initialize CSI camera if no USB camera
        if not self.usb_camera_connected:
            try:
                logging.info("Initializing CSI camera.")
                self.encoder = H264Encoder(1000000)
                self.picam2 = Picamera2()
                self.picam2.configure(self.picam2.create_video_configuration(main={"format": 'XRGB8888', "size": (f['video']['default_res_w'], f['video']['default_res_h'])}))
                self.picam2.start()
                self.csi_camera_connected = True
            except Exception as e:
                logging.error(f"Error initializing CSI camera: {e}")
                self.picam2 = None  # Handle failure to initialize CSI camera
                self.csi_camera_connected = False

        # Ensure there is always a fallback when accessing the camera
        if not self.camera and not hasattr(self, 'picam2'):
            logging.error("No camera initialized.")

        # OAK camera init: USB -> CSI -> OAK-D fallback chain (upstream)
        if not self.usb_camera_connected and not self.csi_camera_connected:
            try:
                self.pipeline = dai.Pipeline()
                self.camRgb = self.pipeline.createColorCamera()
                self.camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
                self.camRgb.setInterleaved(False)
                self.camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_720_P)
                self.xout = self.pipeline.createXLinkOut()
                self.xout.setStreamName("video")
                self.camRgb.video.link(self.xout.input)
                self.device = dai.Device(self.pipeline)
                self.output_queue = self.device.getOutputQueue(name="video", maxSize=8, blocking=False)
                self.oak_camera_connected = True
            except Exception as e:
                logging.error(f"OAK camera init failed: {e}")
                self.oak_camera_connected = False

    def info_scale(self):
        # Implementation for info_scale
        pass

    def info_update(self):
        # Your implementation here
        print("Info updated!")

    def frame_process(self):
        try:
            if self.usb_camera_connected:
                success, input_frame = self.camera.read()
                if not success:
                    self.camera.release()
                    time.sleep(1)
                    self.camera = cv2.VideoCapture(0)
            elif self.csi_camera_connected:
                input_frame = self.picam2.capture_array()
            elif self.oak_camera_connected:
                input_frame = self.output_queue.get().getCvFrame()
                input_frame = cv2.resize(input_frame, (640, 480))
            else:
                input_frame = 255 * np.ones((480, 640, 3), dtype=np.uint8)
                cv2.putText(input_frame, f"camera read failed... \nusb - csi - oak", 
                            (round(0.05*640), round(0.1*640 + 5 * 13)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.369, (0, 0, 0), 1)
                ret, buffer = cv2.imencode('.jpg', input_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.video_quality])
                input_frame = buffer.tobytes()
                time.sleep(1)
                return input_frame
        except Exception as e:
            print(f"[cv_ctrl.frame_process] error: {e}")
            input_frame = 255 * np.ones((480, 640, 3), dtype=np.uint8)
            cv2.putText(input_frame, f"camera read failed... \n{e}", 
                        (round(0.05*640), round(0.1*640 + 5 * 13)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.369, (0, 0, 0), 1)
            ret, buffer = cv2.imencode('.jpg', input_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.video_quality])
            input_frame = buffer.tobytes()
            return input_frame

        # Store latest raw frame for on-demand detection (detect_scene)
        self._latest_raw_frame = input_frame
    
        # Reset overlay at the beginning of each frame
        self.overlay = np.zeros_like(input_frame)
    
        # Call specific overlay functions only when required
        if self.cv_mode != f['code']['cv_none']:
            if not self.cv_event.is_set():
                self.cv_event.set()
                self.opencv_threading(input_frame)
            try:
                mask = self.overlay.astype(bool)
                input_frame[mask] = self.overlay[mask]
                cv2.addWeighted(self.overlay, 1, input_frame, 1, 0, input_frame)
            except Exception as e:
                    print("An error occurred:", e)
        elif self.show_info_flag:
            if time.time() - self.info_update_time > self.info_show_time:
                self.show_info_flag = False
            self.overlay = input_frame.copy()
            cv2.rectangle(self.overlay,  (round((self.info_scale-0.005)*640), round((0.33)*480)), 
                                    (round(0.98*640), round((0.78)*480)), 
                                    self.info_bg_color, -1)
            cv2.addWeighted(self.overlay, 0.5, input_frame, 0.5, 0, input_frame)
    
            # info_deque.appendleft(time.time())
            for i in range(0, len(self.info_deque)):
                cv2.putText(input_frame, str(self.info_deque[i]['text']), 
                            (round(self.info_scale*640), round(self.info_scale*640 - i * 20)), 
                            cv2.FONT_HERSHEY_SIMPLEX, self.info_deque[i]['size'], self.info_deque[i]['color'], 1)
    
        if self.show_base_info_flag:
            for i in range(0, len(self.recv_deque)):
                cv2.putText(input_frame, str(self.recv_deque[i]), 
                        (round(0.05*640), round(0.1*640 + i * 13)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.369, (255, 255, 255), 1)
    
        # Call osd_render separately to handle overlay stability
        input_frame = self.osd_render(input_frame)
    
        # Reset overlay before starting new overlay processes
        self.overlay = np.zeros_like(input_frame)
    
        # Encode frame to avoid issues
        try:
            ret, buffer = cv2.imencode('.jpg', input_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.video_quality])
            input_frame = buffer.tobytes()
        except Exception as e:
            print(f"Encoding error: {e}")
    
        return input_frame
        
    def update_overlay(self, img):
        """Updates the overlay with the yellow line detection and other info."""
        try:
            # Detect yellow line and overlay a circle at its center
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            yellow_mask = cv2.inRange(hsv, self.line_lower, self.line_upper)
            
            contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                cx, cy = x + w // 2, y + h // 2
                cv2.circle(img, (cx, cy), 5, (0, 255, 255), -1)
            
            # Use the updated frame as the overlay
            self.overlay = img
        except Exception as e:
            print(f"Overlay update error: {e}")
            
    def log_command_output(self, command, response=None):
        """
        Logs each command and its response.
        """
        logging.info(f"Command sent: {command}")
        if response:
            logging.info(f"Response: {response}")
            
    def log_command_to_file(self, command):
        """
        Logs each command to a specific file for tracking.
        """
        with open(self.command_log_file, 'a') as log_file:
            log_file.write(f"Sending command: {command}\n")
            
    def usb_camera_detection(self):
        lsusb_output = subprocess.check_output(["lsusb"]).decode("utf-8")
        if "Camera" in lsusb_output:
            print("USB Camera connected")
            return True
        else:
            print("USB Camera not connected")
            return False

    def osd_render(self, osd_frame):
        if not self.add_osd:
            return osd_frame
        
        # add your osd info here
        # cv2.putText(overlay_buffer, 'OSD_TEST', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        # render lidar data
        lidar_points = []
        for lidar_angle, lidar_distance in zip(self.base_ctrl.rl.lidar_angles_show, self.base_ctrl.rl.lidar_distances_show):
            lidar_x = int(lidar_distance * np.cos(lidar_angle) * 0.05) + 320
            lidar_y = int(lidar_distance * np.sin(lidar_angle) * 0.05) + 240
            lidar_points.append((lidar_x, lidar_y))

        for lidar_point in lidar_points:
            cv2.circle(osd_frame, lidar_point, 3, (255, 0, 0), -1)

        # render sensor data
        sensor_index = 0
        for sensor_line in self.base_ctrl.rl.sensor_data:
            # sensor_line = sensor_line[:-2]
            cv2.putText(osd_frame, sensor_line,
                        (100, 50 + sensor_index * 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
            sensor_index = sensor_index + 1
        return osd_frame

    def picture_capture(self):
        self.picture_capture_flag = True

    def video_record(self, input_cmd):
        if input_cmd:
            self.set_video_record_flag = True
        else:
            self.set_video_record_flag = False

    def scale_ctrl(self, input_rate):
        if input_rate < 1:
            self.scale_rate = 1
        else:
            self.scale_rate = input_rate

    def set_video_quality(self, input_quality):
        if input_quality < 1:
            self.video_quality = 1
        elif input_quality > 100:
            self.video_quality = 100
        else:
            self.video_quality = int(input_quality)

    def set_cv_mode(self, input_mode):
        self.cv_mode = input_mode
        if self.cv_mode == f['code']['cv_none']:
            self.set_video_record_flag = False

    def set_detection_reaction(self, input_reaction):
        self.detection_reaction_mode = input_reaction
        if self.detection_reaction_mode == f['code']['re_none']:
            self.set_video_record_flag = False

    def cv_detect_movition(self, img):
        timestamp = datetime.datetime.now()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self.avg is None:
            self.avg = gray.copy().astype("float")
            return
        try:
            cv2.accumulateWeighted(gray, self.avg, 0.5)
        except:
            return
        frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(self.avg))

        # threshold the delta image, dilate the thresholded image to fill
        # in holes, then find contours on thresholded image
        thresh = cv2.threshold(frameDelta, 5, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)
        # loop over the contours
        overlay_buffer = np.zeros_like(img)
        for c in cnts:
            # if the contour is too small, ignore it
            if cv2.contourArea(c) < 2000:
                continue
            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            (mov_x, mov_y, mov_w, mov_h) = cv2.boundingRect(c)
            cv2.rectangle(overlay_buffer, (mov_x, mov_y), (mov_x + mov_w, mov_y + mov_h), (128, 255, 0), 1)
            self.last_movtion_captured = timestamp

            if(timestamp - self.last_frame_capture_time).seconds >= 1:
                if self.detection_reaction_mode == f['code']['re_none']:
                    pass
                elif self.detection_reaction_mode == f['code']['re_capt']: 
                    self.picture_capture()
                elif self.detection_reaction_mode == f['code']['re_reco']:
                    self.video_record(True)
                self.last_frame_capture_time = datetime.datetime.now()
            
        if (timestamp - self.last_movtion_captured).seconds >= 1.5:
            if self.detection_reaction_mode == f['code']['re_reco']:
                if(timestamp - self.last_frame_capture_time).seconds >= 5:
                    self.video_record(False)

        self.overlay = overlay_buffer

    def gimbal_track(self, fx, fy, gx, gy, iterate):
        global gimbal_x, gimbal_y
        distance = math.sqrt((fx - gx) ** 2 + (gy - fy) ** 2)
        self.pan_angle += (gx - fx) * iterate
        self.tilt_angle += (fy - gy) * iterate
        if self.pan_angle > 180:
            self.pan_angle = 180
        elif self.pan_angle < -180:
            self.pan_angle = -180
        if self.tilt_angle > 90:
            self.tilt_angle = 90
        elif self.tilt_angle < -30:
            self.tilt_angle = -30
        gimbal_spd = int(distance * self.track_spd_rate)
        gimbal_acc = int(distance * self.track_acc_rate)
        if gimbal_acc < 1:
            gimbal_acc = 1
        if gimbal_spd < 1:
            gimbal_spd = 1
        self.base_ctrl.base_json_ctrl({"T":self.CMD_GIMBAL,"X":self.pan_angle,"Y":self.tilt_angle,"SPD":gimbal_spd,"ACC":gimbal_acc})
        return distance

    def cv_detect_faces(self, img):
        gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self.faceCascade.detectMultiScale(
                gray_img,     
                scaleFactor=1.2,
                minNeighbors=5,     
                minSize=(20, 20)
            )
        overlay_buffer = np.zeros_like(img)

        height, width = img.shape[:2]
        center_x, center_y = width // 2, height // 2

        max_area = 0
        max_face_center = (0, 0)

        if len(faces):
            if self.cv_light_mode == 1:
                if self.base_ctrl.head_light_status == 0:
                    self.base_ctrl.head_light_status = 255
                    self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, self.base_ctrl.head_light_status)

            for (x,y,w,h) in faces:
                cv2.rectangle(overlay_buffer,(x,y),(x+w,y+h),(64,128,255),1)
                face_area = w * h
                if face_area > max_area:
                    max_area = face_area
                    max_face_center = (x + w // 2, y + h // 2)

            if not self.cv_movtion_lock:
                self.gimbal_track(center_x, center_y, max_face_center[0], max_face_center[1], self.track_faces_iterate)

            if(datetime.datetime.now() - self.last_frame_capture_time).seconds >= 3:
                if self.detection_reaction_mode == f['code']['re_none']:
                    pass
                elif self.detection_reaction_mode == f['code']['re_capt']:
                    self.picture_capture()
                elif self.detection_reaction_mode == f['code']['re_reco']:
                    self.video_record(True)
                self.last_frame_capture_time = datetime.datetime.now()
        else:
            if self.cv_light_mode == 1:
                if self.base_ctrl.head_light_status != 0:
                    self.base_ctrl.head_light_status = 0
                    self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, self.base_ctrl.head_light_status)

            if self.detection_reaction_mode == f['code']['re_reco']:
                if(datetime.datetime.now() - self.last_frame_capture_time).seconds >= 5:
                    self.video_record(False)

        cv2.putText(overlay_buffer, 'NUMBER: {}'.format(len(faces)), (center_x+50, center_y+40), 
                                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, 'ITERATE: {}'.format(self.track_faces_iterate), (center_x+50, center_y+60), 
                                                         cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' SPD_R: {}'.format(self.track_spd_rate), (center_x+50, center_y+80), 
                                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' ACC_R: {}'.format(self.track_acc_rate), (center_x+50, center_y+100), 
                                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        self.overlay = overlay_buffer

    def cv_detect_objects(self, img):
        overlay_buffer = np.zeros_like(img)

        # Prefer YOLOv8 when available — 80 COCO classes, much better accuracy
        if self.yolo_model is not None:
            try:
                results = self.yolo_model(img, verbose=False, conf=0.25)
                objects = []
                confidences = []
                boxes = []
                for r in results:
                    for box in r.boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        name = self.yolo_model.names.get(cls_id, f"class_{cls_id}")
                        x1, y1, x2, y2 = map(int, box.xyxy[0])

                        # Color code: green for people, cyan for vehicles, yellow for animals, white for others
                        if name == 'person':
                            color = (0, 200, 0)
                        elif name in ('car', 'truck', 'bus', 'motorcycle', 'bicycle'):
                            color = (255, 200, 0)
                        elif name in ('dog', 'cat', 'bird', 'horse', 'sheep', 'cow', 'bear'):
                            color = (0, 255, 255)
                        else:
                            color = (200, 200, 200)

                        cv2.rectangle(overlay_buffer, (x1, y1), (x2, y2), color, 2)
                        label = f"{name} {conf:.0%}"
                        y = y1 - 10 if y1 - 10 > 15 else y1 + 15
                        cv2.putText(overlay_buffer, label, (x1, y),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                        objects.append(name)
                        confidences.append(conf)
                        boxes.append((x1, y1, x2, y2))

                # Store latest detections for Lance voice queries
                self.last_detections = [
                    {'name': n, 'confidence': c, 'box': b}
                    for n, c, b in zip(objects, confidences, boxes)
                ]
                # Summary line at top
                if objects:
                    from collections import Counter
                    counts = Counter(objects)
                    summary = ", ".join(f"{v} {k}" + ("s" if v > 1 else "") for k, v in counts.most_common(5))
                    cv2.putText(overlay_buffer, summary, (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
                else:
                    cv2.putText(overlay_buffer, "No objects detected", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (120, 120, 120), 1)

                self.overlay = overlay_buffer
                return objects, confidences, boxes
            except Exception as e:
                logging.warning("YOLOv8 detection failed, falling back: %s", e)

        # Fallback: old MobileNet Caffe model
        cv2.putText(overlay_buffer, 'Person Detect', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        (h, w) = img_rgb.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(img_rgb, (300, 300)), 0.007843, (300, 300), 127.5)
        self.net.setInput(blob)
        detections = self.net.forward()

        objects = []
        confidences = []
        boxes = []

        for i in range(0, detections.shape[2]):
            confidence = detections[0, 0, i, 2]

            if confidence > 0.2:
                idx = int(detections[0, 0, i, 1])
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (startX, startY, endX, endY) = box.astype("int")

                label = "{}: {:.2f}%".format(self.class_names[idx], confidence * 100)
                cv2.rectangle(overlay_buffer, (startX, startY), (endX, endY), (0, 255, 0), 2)

                y = startY - 15 if startY - 15 > 15 else startY + 15
                cv2.putText(overlay_buffer, label, (startX, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                objects.append(self.class_names[idx])
                confidences.append(confidence)
                boxes.append((startX, startY, endX, endY))

        self.last_detections = [
            {'name': n, 'confidence': c, 'box': b}
            for n, c, b in zip(objects, confidences, boxes)
        ]
        self.overlay = overlay_buffer
        return objects, confidences, boxes


    def cv_detect_color(self, img):
        global head_light_pwm
        blurred = cv2.GaussianBlur(img, (11, 11), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        mask = cv2.inRange(hsv, self.color_lower, self.color_upper)
        mask = cv2.erode(mask, None, iterations=5)
        mask = cv2.dilate(mask, None, iterations=5)

        cnts = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)
        center = None

        overlay_buffer = np.zeros_like(img)

        height, width = img.shape[:2]
        center_x, center_y = width // 2, height // 2

        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.circle(mask, (center_x, center_y), self.sampling_rad, (255), thickness=-1)

        masked_hsv = cv2.bitwise_and(hsv, hsv, mask=mask)
        masked_hsv_pixels = masked_hsv[mask == 255]
        lower_hsv = np.min(masked_hsv_pixels, axis=0)
        upper_hsv = np.max(masked_hsv_pixels, axis=0)

        cv2.putText(overlay_buffer, ' UPPER: {}'.format(upper_hsv), (center_x+50, center_y+40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' LOWER: {}'.format(lower_hsv), (center_x+50, center_y+60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.putText(overlay_buffer, ' UPPER: {}'.format(self.color_upper), (center_x+50, center_y+100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
        cv2.putText(overlay_buffer, ' LOWER: {}'.format(self.color_lower), (center_x+50, center_y+120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
        cv2.putText(overlay_buffer, 'ITERATE: {}'.format(self.track_color_iterate), (center_x+50, center_y+140), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' SPD_R: {}'.format(self.track_spd_rate), (center_x+50, center_y+160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' ACC_R: {}'.format(self.track_acc_rate), (center_x+50, center_y+180), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        cv2.circle(overlay_buffer, (center_x, center_y), self.sampling_rad, (64, 255, 64), 1)

        # only proceed if at least one contour was found
        if len(cnts) > 0:
            # find the largest contour in the mask, then use
            # it to compute the minimum enclosing circle and
            # centroid
            c = max(cnts, key=cv2.contourArea)
            ((x, y), radius) = cv2.minEnclosingCircle(c)
            M = cv2.moments(c)
            center = (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))

            # only proceed if the radius meets a minimum size
            if radius > self.min_radius:
                if not self.cv_movtion_lock:
                    distance = self.gimbal_track(center_x, center_y, center[0], center[1], self.track_color_iterate)
                    if distance < self.aimed_error:
                        head_light_pwm = 10
                        self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, head_light_pwm)
                    else:
                        head_light_pwm = 0
                        self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, head_light_pwm)
                    cv2.putText(overlay_buffer, 'DIF: {}'.format(distance), (center_x+50, center_y+20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                # draw the circle and centroid on the frame,
                # then update the list of tracked points
                cv2.circle(overlay_buffer, (int(x), int(y)), int(radius),
                    (128, 255, 255), 1)
                cv2.circle(overlay_buffer, center, 3, (128, 255, 255), -1)
                cv2.line(overlay_buffer, center, (center_x, center_y), (0, 0, 255), 1)
                cv2.putText(overlay_buffer, 'RAD: {}'.format(radius), (center_x+50, center_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                self.points.appendleft(center)
            else:
                head_light_pwm = 0
                self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, head_light_pwm)
                self.points.appendleft(None)

            for i in range(1, len(self.points)):
                if self.points[i-1] is None or self.points[i] is None:
                    continue
                cv2.line(overlay_buffer, self.points[i - 1], self.points[i], (255, 255, 128), 1)

        self.overlay = np.zeros_like(img)
        self.overlay = overlay_buffer

    def calculate_distance(self, lm1, lm2):
        return ((lm1.x - lm2.x) ** 2 + (lm1.y - lm2.y) ** 2) ** 0.5

    def calculate_angle(self, A1, A2, B1, B2):
        vector_A = (A2.x - A1.x, A2.y - A1.y)
        vector_B = (B2.x - B1.x, B2.y - B1.y)

        dot_product = vector_A[0] * vector_B[0] + vector_A[1] * vector_B[1]

        magnitude_A = math.sqrt(vector_A[0]**2 + vector_A[1]**2)
        magnitude_B = math.sqrt(vector_B[0]**2 + vector_B[1]**2)

        angle = math.acos(dot_product / (magnitude_A * magnitude_B))

        angle_deg = math.degrees(angle)

        return angle_deg

    def map_value(self, value, original_min, original_max, new_min, new_max):
        if original_max == 0:
            return 0
        return (value - original_min) / (original_max - original_min) * (new_max - new_min) + new_min

    def mp_detect_hand(self, img):
        height, width = img.shape[:2]
        center_x, center_y = width // 2, height // 2

        imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.hands.process(imgRGB)

        overlay_buffer = np.zeros_like(imgRGB)
        get_pwm = 0

        if results.multi_hand_landmarks:
            for handLms in results.multi_hand_landmarks:
                # draw joints
                for id, lm in enumerate(handLms.landmark):
                    h, w, c = imgRGB.shape
                    cx, cy = int(lm.x * w), int(lm.y * h)
                    cv2.circle(overlay_buffer, (cx, cy), 5, (255, 0, 0), -1)

                # draw lines
                self.mpDraw.draw_landmarks(overlay_buffer, handLms, self.mpHands.HAND_CONNECTIONS)

                target_pos = handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_TIP]
                # print(f"x:{target_pos.x} y:{target_pos.y}")
                if not self.cv_movtion_lock:
                    distance = self.gimbal_track(center_x, center_y, width*target_pos.x, height*target_pos.y, self.track_faces_iterate)

                # check hand gs
                pinky_finger_gs = self.calculate_angle(
                                            handLms.landmark[self.mpHands.HandLandmark.WRIST],
                                            handLms.landmark[self.mpHands.HandLandmark.PINKY_MCP],
                                            handLms.landmark[self.mpHands.HandLandmark.PINKY_MCP],
                                            handLms.landmark[self.mpHands.HandLandmark.PINKY_TIP])

                index_finger_gs = self.calculate_angle(
                                            handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_MCP],
                                            handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_PIP],
                                            handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_PIP],
                                            handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_TIP])

                middle_finger_gs = self.calculate_angle(
                                            handLms.landmark[self.mpHands.HandLandmark.MIDDLE_FINGER_MCP],
                                            handLms.landmark[self.mpHands.HandLandmark.MIDDLE_FINGER_PIP],
                                            handLms.landmark[self.mpHands.HandLandmark.MIDDLE_FINGER_PIP],
                                            handLms.landmark[self.mpHands.HandLandmark.MIDDLE_FINGER_TIP])

                # LED Ctrl
                if middle_finger_gs > 20 and pinky_finger_gs > 90:
                    cv2.putText(overlay_buffer, ' GS: LED Ctrl', (center_x+50, center_y+100), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
                    tips_distance = self.calculate_distance(handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_TIP],
                        handLms.landmark[self.mpHands.HandLandmark.THUMB_TIP])

                    if index_finger_gs < 3:
                        self.max_distance = tips_distance
                    # print(index_finger_gs)

                    get_pwm = int(self.map_value(tips_distance, 0.01, self.max_distance, 0, 128))
                    self.base_ctrl.lights_ctrl(get_pwm, get_pwm)

                    # try:
                    #     print(f"dis:{tips_distance} max:{self.max_distance} pwm:{get_pwm}")
                    # except Exception as e:
                    #     print(e)

                # Take Pic
                elif middle_finger_gs < 10 and pinky_finger_gs > 90 and index_finger_gs < 10:
                    cv2.putText(overlay_buffer, ' GS: Take Pic', (center_x+50, center_y+100), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
                    if time.time() - self.gs_pic_last_time > self.gs_pic_interval:
                        self.base_ctrl.lights_ctrl(255, 255)
                        time.sleep(0.01)
                        self.picture_capture()
                        self.base_ctrl.lights_ctrl(0, 0)
                        self.gs_pic_last_time = time.time()

                # Not Found
                else:
                    cv2.putText(overlay_buffer, ' GS: Not Defined', (center_x+50, center_y+100), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
                    self.base_ctrl.lights_ctrl(0, 0)

        cv2.putText(overlay_buffer, 'ITERATE: {}'.format(self.track_faces_iterate), (center_x+50, center_y+140), 
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' SPD_R: {}'.format(self.track_spd_rate), (center_x+50, center_y+160), 
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' ACC_R: {}'.format(self.track_acc_rate), (center_x+50, center_y+180), 
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        self.overlay = overlay_buffer
            # UsageCall the method
    
    def toggle_gesture_control(self, enable):
        self.gesture_enabled = enable
        logging.info(f"Gesture control {'enabled' if enable else 'disabled'}.")

        # Method to continuously listen for wake word
    # In the listen_for_wake_word method
    def listen_for_wake_word(self):
        print("Listening for wake word...")
        while True:
            with self.mic_lock:  # Acquire the lock
                try:
                    with self.microphone as source:
                        # Adjust recognizer for ambient noise levels
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        audio = self.recognizer.listen(source, timeout=5)
                    
                    # Attempt to recognize the wake word
                    speech_text = self.recognizer.recognize_google(audio).lower()
                    if self.wake_word in speech_text:
                        print(f"Wake word '{self.wake_word}' detected.")
                        self.speaking = True  # Block other actions while speaking
                        self.respond_to_greeting()
                except sr.UnknownValueError:
                    print("Could not understand the audio")
                except Exception as e:
                    print(f"Error listening for wake word: {e}")
                finally:
                    self.speaking = False  # Ensure this resets after each session

    def detect_gestures(self, img):
        """Detect hand gestures to control the robot."""
        if not self.gesture_enabled:
            return img

        imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.hands.process(imgRGB)
        overlay_buffer = np.zeros_like(img)

        if results.multi_hand_landmarks:
            for handLms in results.multi_hand_landmarks:
                self.mpDraw.draw_landmarks(overlay_buffer, handLms, mp.solutions.hands.HAND_CONNECTIONS)

                # Extract landmarks for gestures
                wrist = handLms.landmark[self.mpHands.HandLandmark.WRIST]
                index_tip = handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_TIP]
                middle_tip = handLms.landmark[self.mpHands.HandLandmark.MIDDLE_FINGER_TIP]
                thumb_tip = handLms.landmark[self.mpHands.HandLandmark.THUMB_TIP]

                # Stop gesture: hand raised
                if index_tip.y < wrist.y and middle_tip.y < wrist.y:
                    self.gesture_stop = True
                    self.follow_mode = False
                    self.stop_robot()
                    cv2.putText(overlay_buffer, "STOP", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

                # Follow gesture: hand forward or downward
                elif wrist.y < index_tip.y < wrist.y + 0.2 and thumb_tip.y > wrist.y:
                    self.follow_mode = True
                    self.gesture_stop = False
                    self.start_follow_mode()
                    cv2.putText(overlay_buffer, "FOLLOW", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                # Resume gesture: hand lowered to resume motion
                elif wrist.y < index_tip.y and not self.gesture_stop:
                    self.follow_mode = False
                    self.resume_robot()
                    cv2.putText(overlay_buffer, "RESUME", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)

        img = cv2.addWeighted(img, 1, overlay_buffer, 1, 0)
        return img
        
    def learn_from_line(self):
        if len(self.line_memory) < 10:  # Ensure enough data points for training
            return None
        
        # Prepare data for learning
        line_positions = np.array([data['line_center_x'] for data in self.line_memory]).reshape(-1, 1)
        turn_angles = np.array([data['turning_angle'] for data in self.line_memory])
        
        # Train the model to predict turning angle based on line center position
        self.model.fit(line_positions, turn_angles)

    def predict_turning(self, line_center_x):
        # Predict turning angle using the learned model
        return self.model.predict(np.array([[line_center_x]]))[0] if len(self.line_memory) >= 10 else None

    def stop_robot(self):
        # Send command to stop the robot
        print("Stopping the robot.")

    def start_follow_mode(self):
        # Send command to start following
        print("Starting follow mode.")

    def resume_robot(self):
        # Send command to resume motion
        print("Resuming robot motion.")
    def cv_process(self, frame):
        """
        Enhanced cv_process to include gesture detection.
        """
        super().cv_process(frame)  # Call any base class processing
        self.detect_gestures(frame)  # Call the gesture detection method
        
    def draw_lidar_box(self, img, lidar_data):
        height, width = img.shape[:2]
        box_width = 200
        box_height = 150
        box_x = width - box_width - 10
        box_y = (height // 2) - (box_height // 2)
        
        cv2.rectangle(img, (box_x, box_y), (box_x + box_width, box_y + box_height), (0, 255, 0), 2)
        cv2.rectangle(img, (box_x + 1, box_y + 1), (box_x + box_width - 1, box_y + box_height - 1), (0, 0, 0), -1)

        font = cv2.FONT_HERSHEY_SIMPLEX
        line_height = 20
        max_lines = min(len(lidar_data), 5)
        for i in range(max_lines):
            text = f"Dist {i + 1}: {lidar_data[i]:.2f}m"
            cv2.putText(img, text, (box_x + 10, box_y + 30 + (i * line_height)), font, 0.5, (255, 255, 255), 1)

        return img

    def read_lidar(self):
        """Sample wheel odometry from base_ctrl's parsed ESP32 feedback
        (odl/odr in base_data). Never opens /dev/ttyAMA0 directly - a second
        handle corrupts base_ctrl's serial stream."""
        try:
            bd = self.base_ctrl.base_data
            if bd:
                odl = bd.get("odl")
                odr = bd.get("odr")
                if odl is not None and odr is not None:
                    self.lidar_data.append((odl, odr))
                    if len(self.lidar_data) > 100:
                        self.lidar_data.pop(0)
        except Exception as e:
            logging.info(f"Error reading LIDAR data: {e}")

    def toggle_listening(self):
        """Toggle listening state on/off."""
        if not self.listening_active:
            self.listening_active = True
            logging.info("Activating listening mode.")
            self.listening_thread = threading.Thread(target=self.listen_and_respond)
            self.listening_thread.start()
        else:
            self.listening_active = False
            logging.info("Deactivating listening mode.")

    def listen_and_respond(self):
        """Continuously listens for the wake word if listening is active."""
        logging.info("Lucy listening for the wake word.")
        while self.listening_active:
            with self.speech_lock:  # Lock microphone access
                try:
                    with self.microphone as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        audio = self.recognizer.listen(source, timeout=5)
                    # Check for wake word
                    speech_text = self.recognizer.recognize_google(audio).lower()
                    logging.info(f"Detected: '{speech_text}'")
                    if any(w in speech_text for w in self.wake_aliases):
                        logging.info(f"Wake word detected in '{speech_text}'.")
                        self.initiate_interaction()
                except sr.UnknownValueError:
                    logging.warning("Could not understand the audio")
                except sr.RequestError as e:
                    logging.error(f"Speech recognition error: {e}")
                except Exception as e:
                    logging.error(f"Error listening for wake word: {e}")
                    
    def initiate_interaction(self):
        """Initiates the interaction sequence after wake word detection."""
        logging.info("Starting interaction sequence.")
        # Toggle lights on and greet the user
        self.toggle_lights(True)
        self.speak_minion("Bello boss! I'm Lance. What can I do for you?")
        
        # Listen for a follow-up question or command
        self.listen_for_question()
        self.toggle_lights(False)  # Turn off lights after interaction
        
    def feedback_data(self, raw_data):
        """
        Processes incoming data and parses JSON with added error handling.
        """
        try:
            # Remove any control characters or extraneous whitespace
            cleaned_data = raw_data.strip()
            
            # Parse JSON and handle any parsing errors
            data = json.loads(cleaned_data)
            logging.info(f"Parsed feedback data: {data}")
            
            # Proceed with processing parsed data
            self.process_feedback_data(data)
        
        except json.JSONDecodeError as e:
            # Log the full raw data to diagnose JSON issues
            logging.error(f"[base_ctrl.feedback_data] JSON decode error: {e} - Raw data: {raw_data}")
        except Exception as e:
            logging.error(f"[base_ctrl.feedback_data] Unexpected error: {e} - Raw data: {raw_data}")
            
    def process_feedback_data(self, data):
        """
        Processes parsed JSON feedback data from the base controller.
        """
        try:
            # Check for status updates
            if "status" in data:
                status = data["status"]
                logging.info(f"Status update received: {status}")
                # Take actions based on status, e.g., start/stop robot or adjust speed
                if status == "ready":
                    self.robot_ready = True
                elif status == "busy":
                    self.robot_ready = False
    
            # Check for error messages
            if "error" in data:
                error_message = data["error"]
                logging.error(f"Error from base controller: {error_message}")
                # You might add custom handling for certain error codes here
    
            # Check for sensor data updates
            if "sensor_data" in data:
                sensor_data = data["sensor_data"]
                self.update_sensors(sensor_data)
                logging.info(f"Sensor data updated: {sensor_data}")
    
            # Handle any command feedback
            if "command_feedback" in data:
                command_feedback = data["command_feedback"]
                logging.info(f"Command feedback received: {command_feedback}")
                # Act on feedback, such as adjusting parameters if feedback indicates so
    
            # Example: Check for specific JSON fields and act on them
            if "battery_level" in data:
                battery_level = data["battery_level"]
                self.battery_level = battery_level
                logging.info(f"Battery level: {battery_level}%")
                if battery_level < 20:
                    self.warn_low_battery()
    
            # Add additional processing as needed
    
        except Exception as e:
            logging.error(f"[process_feedback_data] Unexpected error while processing data: {e}")

    def cv_auto_drive(self, img):
        img = cv2.resize(img, (640, 480))
        height, width = img.shape[:2]
        center_x = width // 2
    
        # Detect the yellow line
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        yellow_lower = np.array([20, 100, 100])
        yellow_upper = np.array([30, 255, 255])
        line_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)
        line_mask = cv2.erode(line_mask, None, iterations=2)
        line_mask = cv2.dilate(line_mask, None, iterations=2)
    
        # Set the ROI to a lower portion of the frame
        roi_height_start = int(height * 0.75)
        roi = line_mask[roi_height_start:height, :]
    
        # Find contours in the ROI for line tracking
        contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        weighted_sum_x = 0
        total_weight = 0
        line_detected = False
        detection_ball_position = (center_x, int(height * 0.9))  # Default position at the center bottom of the overlay
    
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            contour_center_x = x + (w // 2)
            contour_area = cv2.contourArea(contour)
    
            # Calculate weighted center for line position
            weighted_sum_x += contour_center_x * contour_area
            total_weight += contour_area
    
        if total_weight > 0:
            line_center_x = weighted_sum_x / total_weight
            error = center_x - line_center_x
            line_detected = True
            detection_ball_position = (int(line_center_x), int(height * 0.9))
    
            # Add the detected line data to memory
            turning_angle = (0.025 * error)
            self.line_memory.append({
                'line_center_x': line_center_x,
                'turning_angle': turning_angle,
                'width': w,
                'height': h
            })
    
            # Train model periodically
            if len(self.line_memory) >= 10:
                self.learn_from_line()
    
            # Predict turning angle from learned model
            predicted_turning = self.predict_turning(line_center_x)
            turning = predicted_turning if predicted_turning is not None else turning_angle
        else:
            error = 0
            line_detected = False
            turning = 15  # Default turning angle when line is lost
    
        # Draw the detection ball on the overlay
        overlay = img.copy()
        ball_color = (0, 255, 0) if line_detected else (0, 0, 255)
        cv2.circle(overlay, detection_ball_position, 10, ball_color, -1)
        img = cv2.addWeighted(overlay, 0.5, img, 0.5, 0)
    
        # Detect objects in the frame, specifically looking for persons
        stop_robot = False
        objects, confidences, boxes = self.cv_detect_objects(img)

        # Safety stop for REAL close people only. YOLO at 0.25 conf
        # false-positives on chairs, doors, posters at any distance, which
        # froze auto-drive a few feet in and it never continued. Require a
        # large box (someone genuinely close to the robot) AND decent
        # confidence AND 3 consecutive frames of evidence before stopping.
        img_h = img.shape[0]
        close_person = False
        for obj_class, conf, box in zip(objects, confidences, boxes):
            x_min, y_min, x_max, y_max = box
            if obj_class == "person" and conf >= 0.35 and (y_max - y_min) >= img_h * 0.18:
                close_person = True
                # Draw bounding box for the detected person
                cv2.rectangle(img, (x_min, y_min), (x_max, y_max), (0, 0, 255), 2)
                cv2.putText(img, "Person Detected", (x_min, y_min - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        if close_person:
            self.person_frames = getattr(self, "person_frames", 0) + 1
        else:
            self.person_frames = 0
        if self.person_frames >= 3:
            stop_robot = True
            threading.Thread(target=self.announce_person_detected).start()  # Announce detection if needed
    
        # Set speed based on line and person detection
        final_speed = self.line_track_speed * 0.6 if line_detected else self.line_track_speed * 0.4
        if stop_robot:
            final_speed = 0  # Stop the robot if a person is detected
    
        # ROS control command for four-wheel drive
        command = {"T": 13, "X": final_speed, "Z": turning, "ALL_WHEELS": True}
        self.send_base_command(command)
    
        # Update previous error for PID
        self.prev_error = error


    def toggle_listening(self):
        """Toggle listening state on/off."""
        self.listening_active = not self.listening_active
        if self.listening_active:
            print("Listening mode activated.")
        else:
            print("Listening mode deactivated.")

    def update_sensors(self, sensor_data):
        # Process and store sensor data; e.g., LIDAR, proximity, etc.
        self.sensors = sensor_data  # Store or process data as needed
        logging.info(f"Updated sensor data: {sensor_data}")
    
    def warn_low_battery(self):
        # Actions to take when battery is low
        logging.warning("Battery level is low! Consider charging soon.")
        self.send_base_command({"T": 13, "X": 0, "Z": 0})  # Stop robot if low on battery
           
    def play_speech(self, text):
        if self.speaking:
            print("Audio already playing; unable to start a new one.")
            return
        self.speaking = True
        self.tts_engine.say(text)
        try:
            self.tts_engine.runAndWait()
        except RuntimeError:
            print("Audio playback error.")
        finally:
            self.speaking = False

    # Additional Updates for Improvements
    def announce_person_detected(self):
        current_time = time.time()
        if self.speaking or (current_time - self.last_announcement_time) < self.announcement_cooldown:
            return
        self.speaking = True
        threading.Thread(target=self._make_announcement).start()
    
    def _make_announcement(self):
        try:
            # Stop the robot before interaction
            self.robot_moving = False
            self.send_base_command({"T": 13, "X": 0, "Z": 0})
    
            # Create a speech synthesizer
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config)
    
            # Synthesize the greeting
            synthesizer.speak_text_async("Hi, how can I be of service?").get()
            self.last_announcement_time = time.time()
    
            # Start interaction after greeting
            self.listen_for_question()
    
        finally:
            # Allow the robot to move again after interaction
            self.robot_moving = True
            self.speaking = False    # Existing listen_for_question method
    def listen_for_question(self):
        with self.microphone as source:
            self.speak_minion("Listening boss.")
            audio = self.recognizer.listen(source, timeout=5)
            try:
                question = self.recognizer.recognize_google(audio).lower()
                print(f"Recognized question: {question}")
                response = self.lance_handle(question)
                self.speak_minion(response)
            except sr.UnknownValueError:
                self.speak_minion("Sorry, I didn't catch that boss.")
            except Exception as e:
                logging.error(f"Error in listen_for_question: {e}")
                self.speak_minion("Oops boss, something went wrong.")

    MINION_PHRASES = ["Bello!", "Papoy!", "Bee-do-bee-do-bee-do!", "Ta-ta!", "Banana!", "Underwear!"]

    def _synth_rest(self, ssml):
        """Synthesize SSML via the Azure TTS REST endpoint (robust: the Speech SDK's
        WebSocket layer fails to open on this box after a reboot, while plain HTTPS
        works). Returns the WAV bytes."""
        import urllib.request
        url = f"https://{self.speech_config.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        req = urllib.request.Request(url, data=ssml.encode("utf-8"), method="POST")
        req.add_header("Ocp-Apim-Subscription-Key", self.speech_config.subscription_key)
        req.add_header("Content-Type", "application/ssml+xml")
        req.add_header("X-Microsoft-OutputFormat", "riff-24khz-16bit-mono-pcm")
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()

    def _play_wav(self, wav_bytes):
        """Play WAV bytes through the system default sink (currently the BT speaker)."""
        import subprocess, tempfile, os
        fd, path = tempfile.mkstemp(suffix=".wav", dir="/tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav_bytes)
            subprocess.run(["/usr/bin/paplay", path], timeout=40, check=False)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def speak_minion(self, text):
        """Speak `text` in a high-pitched fast 'minion' voice (Azure SSML), falling
        back to the local pyttsx3 engine if synthesis fails."""
        if self.speaking:
            print("Audio already playing; skipping speech.")
            return
        self.speaking = True
        try:
            phrase = random.choice(self.MINION_PHRASES)
            ssml = (
                '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
                f'<voice name="en-US-JennyNeural"><prosody pitch="+40%" rate="+28%">'
                f"{phrase} {text}"
                '</prosody></voice></speak>'
            )
            # Primary: REST synthesis -> paplay (reliable; SDK WebSocket is broken on this box)
            try:
                wav = self._synth_rest(ssml)
                if wav and wav[:4] == b"RIFF":
                    self._play_wav(wav)
                    return
                logging.warning("REST TTS returned no audio; trying SDK")
            except Exception as e:
                logging.warning(f"REST TTS error: {e}; trying SDK")
            # Fallback 1: Azure Speech SDK (plays to the default device itself)
            try:
                synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config)
                result = synthesizer.speak_ssml_async(ssml).get()
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    return
                logging.warning(f"Azure SDK TTS failed ({result.reason}); falling back to pyttsx3")
            except Exception as e:
                logging.warning(f"Azure SDK TTS error: {e}; falling back to pyttsx3")
            # Fallback 2: local pyttsx3 engine
            self.play_speech(text)
        finally:
            self.speaking = False

    def lance_handle(self, question):
        """Route a spoken request through the local Lance brain (Ollama)."""
        try:
            import lance
            return lance.handle(question, self)
        except Exception as e:
            logging.error(f"lance_handle failed: {e}")
            return "Sorry boss, my brain is having a moment."

    # ------------------------------------------------------------------
    # Open-vocabulary vision: self-learning + internet knowledge
    # ------------------------------------------------------------------

    def _load_known_objects(self):
        """Load the persistent object vocabulary + facts, seeding it if missing."""
        facts = {}
        if os.path.exists(self.known_objects_path):
            try:
                with open(self.known_objects_path, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                objs = [str(x).strip().lower() for x in data.get('objects', []) if str(x).strip()]
                facts = data.get('facts') or {}
                if objs:
                    return objs, facts
            except Exception as e:
                logging.warning("known_objects.json unreadable: %s", e)
        objs = list(dict.fromkeys(DEFAULT_KNOWN_OBJECTS))
        self._save_known_objects(objs, facts)
        return objs, facts

    def _save_known_objects(self, objs=None, facts=None):
        try:
            with open(self.known_objects_path, 'w', encoding='utf-8') as fp:
                json.dump({'objects': objs if objs is not None else self.known_objects,
                           'facts': facts if facts is not None else self.object_facts},
                          fp, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.warning("failed to save known_objects.json: %s", e)

    def _start_world_warmup(self):
        """Load YOLO-World in the background so it's ready when asked. Safe to fail."""
        if self._world_warmup_started:
            return
        self._world_warmup_started = True
        try:
            threading.Thread(target=self._ensure_world_model, args=(True,), daemon=True).start()
        except Exception as e:
            logging.warning("world warmup thread failed to start: %s", e)

    def _ensure_world_model(self, block=True):
        """Load YOLO-World and set its vocabulary from known_objects.json.

        Embeddings are cached to world_embeddings.pkl, so only unseen names get
        re-embedded (CLIP text encoder is internet-trained: it already knows the
        visual meaning of thousands of object words). Returns True when ready.
        """
        with self._world_lock:
            if self.world_model is not None and self.world_ready:
                return True
            try:
                if self.world_model is None:
                    from ultralytics import YOLO
                    self.world_model = YOLO('yolov8s-worldv2.pt')  # open-vocabulary
                wm = self.world_model.model  # nn WorldModel
                cache = {}
                if os.path.exists(self.world_embeddings_path):
                    try:
                        cache = torch.load(self.world_embeddings_path, map_location='cpu', weights_only=True)
                    except Exception as e:
                        logging.warning("embedding cache unreadable: %s", e)
                names = self.known_objects
                missing = [n for n in names if n not in cache]
                if missing:
                    feats = wm.get_text_pe(missing, batch=80)  # builds/caches the CLIP encoder
                    for n, f in zip(missing, feats[0]):
                        cache[n] = f.detach().cpu().float()
                    try:
                        torch.save(cache, self.world_embeddings_path)
                    except Exception as e:
                        logging.warning("embedding cache save failed: %s", e)
                vecs = torch.stack([cache[n].float() for n in names])  # (n, d)
                wm.txt_feats = vecs.unsqueeze(0)  # (1, n, d) — same path set_classes uses
                wm.model[-1].nc = len(names)
                self.world_model.model.names = {i: n for i, n in enumerate(names)}
                self.world_model.predictor = None  # force predictor to re-read names
                self.world_ready = True
                logging.info("YOLO-World ready: %d known objects (internet-trained vocabulary)", len(names))
                return True
            except Exception as e:
                logging.warning("YOLO-World load failed (vision falls back to YOLOv8 COCO): %s", e)
                self.world_ready = False
                return False

    def _reembed_new(self, new_names):
        """Embed only the newly learned names and append to the existing text features.
        Caller must hold self._world_lock and world_ready must be True."""
        wm = self.world_model.model
        cache = {}
        if os.path.exists(self.world_embeddings_path):
            try:
                cache = torch.load(self.world_embeddings_path, map_location='cpu', weights_only=True)
            except Exception:
                cache = {}
        missing = [n for n in new_names if n not in cache]
        if missing:
            feats = wm.get_text_pe(missing, batch=80)
            for n, f in zip(missing, feats[0]):
                cache[n] = f.detach().cpu().float()
            try:
                torch.save(cache, self.world_embeddings_path)
            except Exception:
                pass
        new_vecs = torch.stack([cache[n].float() for n in new_names])  # (m, d)
        wm.txt_feats = torch.cat([wm.txt_feats, new_vecs.unsqueeze(0)], dim=1)
        wm.model[-1].nc = len(self.known_objects)
        self.world_model.model.names = {i: n for i, n in enumerate(self.known_objects)}
        self.world_model.predictor = None  # force predictor to re-read names

    def _fetch_fact(self, name, max_chars=110):
        """Look up what `name` is on Wikipedia (free public API, no key).
        Returns a short spoken fact or '' on failure. Result is cached in
        known_objects.json so it survives restarts and needs no repeat lookups."""
        if name in self.object_facts:
            return self.object_facts[name]
        import urllib.parse
        import urllib.request
        try:
            slug = urllib.parse.quote(name.replace(' ', '_'))
            req = urllib.request.Request(
                'https://en.wikipedia.org/api/rest_v1/page/summary/' + slug,
                headers={'User-Agent': 'UGV-Lance/1.0 (educational home robot)'},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            extract = (data.get('extract') or '').strip()
            if extract:
                extract = extract[:max_chars].rsplit(' ', 1)[0] + '.'
                self.object_facts[name] = extract
                self._save_known_objects()
                return extract
        except Exception as e:
            logging.info("wiki lookup failed for %s: %s", name, e)
        return ''

    def learn_object(self, name):
        """Self-learning: add an object to Lance's permanent vocabulary.

        Once learned, YOLO-World can recognize it immediately (its CLIP text
        encoder understands the word from internet-scale training). The name is
        persisted to known_objects.json and a Wikipedia fact is fetched so Lance
        can also say something true about the object. Returns the spoken reply.
        """
        name = ' '.join(str(name or '').strip().lower().split())
        if not name:
            return "Tell me what object to learn!"
        with self._world_lock:
            if name in self.known_objects:
                already = True
            else:
                already = False
                self.known_objects.append(name)
                self._save_known_objects()
            if self.world_ready and not already:
                try:
                    self._reembed_new([name])
                except Exception as e:
                    logging.warning("incremental embed failed for %s: %s", name, e)
        if already:
            return "I already know " + name + " — I'll keep an eye out for it."
        fact = self._fetch_fact(name)
        if fact:
            return "Learned! A " + name + " — " + fact + " I'll recognize it from now on."
        return "Learned! From now on I'll recognize a " + name + "."

    def _merge_synonym_boxes(self, found):
        """Map detected names to canonical forms and merge overlapping boxes.

        found: list of (name, conf, [x1,y1,x2,y2]). Returns the same list with
        synonyms collapsed (monitor + screen on the same object -> one monitor)
        and, per canonical class, overlapping boxes merged (keep highest conf).
        """
        groups = {}
        for name, conf, box in found:
            groups.setdefault(_SYNONYM_ALIAS_MAP.get(name, name), []).append((name, conf, box))
        merged = []
        for canon, dets in groups.items():
            dets.sort(key=lambda d: d[1], reverse=True)
            kept = []
            for det in dets:
                if all(_iou(det[2], k[2]) < 0.35 for k in kept):
                    kept.append(det)
            merged.extend((canon, conf, box) for _, conf, box in kept)
        return merged

    def _build_scene_summary(self, found):
        """Turn raw detections into a spoken summary: synonyms deduped, overlapping
        boxes merged, counts pluralized ('2 juice boxes'). Returns (top_name, text)."""
        merged = self._merge_synonym_boxes(found)
        if not merged:
            return None, "I don't see anything I recognize right now."
        from collections import Counter
        counts = Counter(name for name, _, _ in merged)
        parts = []
        for name, count in counts.most_common(10):
            if count == 1:
                # plural-only nouns ('scissors') take no article
                parts.append(name if name in _PLURAL_ONLY else f"{_article(name)} {name}")
            else:
                parts.append(f"{count} {_pluralize(name)}")
        return counts.most_common(1)[0][0], ", ".join(parts)

    def detect_world(self):
        """Structured open-vocabulary detections from the newest frame.

        detect_scene() answers Lance in sentences; this returns the same
        YOLO-World pass as data — [{'name','confidence','box'}] — so the
        self-drive planner can pursue an object that only the open-vocabulary
        model knows (the frame loop's last_detections come from the closed-set
        COCO model, which has no 'refrigerator'/'whiteboard' class at all).
        """
        frame = getattr(self, '_latest_raw_frame', None)
        if frame is None or self.world_model is None \
                or not getattr(self, 'world_ready', False):
            return []
        try:
            results = self.world_model(frame, verbose=False, conf=WORLD_DETECT_CONF)
            dets = []
            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    raw = self.world_model.names.get(cls_id, '')
                    name = _SYNONYM_ALIAS_MAP.get(raw, raw)
                    if not name:
                        continue
                    dets.append({'name': name,
                                 'confidence': float(box.conf[0]),
                                 'box': list(map(int, box.xyxy[0]))})
            return dets
        except Exception as e:
            logging.error("detect_world error: %s", e)
            return []

    def detect_scene(self):
        """Use the latest captured frame to run open-vocabulary detection.
        Returns a human-readable summary string of what's in front of the camera.
        """
        frame = getattr(self, '_latest_raw_frame', None)
        if frame is None:
            return "I can't see anything right now — the camera isn't responding."

        # Open-vocabulary YOLO-World: COCO-80 + every learned/taught object.
        # Confidence bar is WORLD_DETECT_CONF (0.30) — high enough to cut noise
        # ("sim card" for a phone), low enough to keep real objects.
        if self.world_model is not None and getattr(self, 'world_ready', False):
            try:
                results = self.world_model(frame, verbose=False, conf=WORLD_DETECT_CONF)
                found = []
                for r in results:
                    for box in r.boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        name = self.world_model.names.get(cls_id, f"class_{cls_id}")
                        found.append((name, conf, list(map(int, box.xyxy[0]))))

                self.last_detections = [
                    {'name': _SYNONYM_ALIAS_MAP.get(n, n), 'confidence': c, 'box': b}
                    for n, c, b in found
                ]

                top_name, summary = self._build_scene_summary(found)
                if top_name is None:
                    return summary
                # Attach a cached internet fact about the main object, if we have one
                fact = ''
                if top_name in self.object_facts:
                    fact = ' ' + self.object_facts[top_name]
                return f"I can see: {summary}.{fact}"

            except Exception as e:
                logging.error("world detect error, falling back: %s", e)

        # Run YOLOv8 COCO detection if available (closed-set fallback)
        if self.yolo_model is not None:
            try:
                results = self.yolo_model(frame, verbose=False, conf=0.3)
                found = []
                for r in results:
                    for box in r.boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        name = self.yolo_model.names.get(cls_id, f"class_{cls_id}")
                        found.append((name, conf, list(map(int, box.xyxy[0]))))

                # Also store for later reference (names canonicalized)
                self.last_detections = [
                    {'name': _SYNONYM_ALIAS_MAP.get(n, n), 'confidence': c, 'box': b}
                    for n, c, b in found
                ]

                top_name, summary = self._build_scene_summary(found)
                if top_name is None:
                    return "I don't see anything recognizable in front of the camera."
                return f"I can see: {summary}."

            except Exception as e:
                logging.error("detect_scene YOLO error: %s", e)
                return "My vision had a hiccup. Try again in a second."

        # Fallback: MobileNet (20 classes)
        try:
            objects, confidences, boxes = self.cv_detect_objects(frame)
            if not objects:
                return "I don't see anything recognizable."
            from collections import Counter
            counts = Counter(objects)
            parts = []
            for name, count in counts.most_common(5):
                parts.append(f"{count} {name}" if count > 1 else f"a {name}")
            return f"I can see: {', '.join(parts)}."
        except Exception as e:
            return "My vision isn't working right now."
    
    def execute_command(self, command):
        logging.info(f"Executing command: {command}")
        if command == "start_auto_drive":
            logging.info("Starting auto drive...")
            self.robot_moving = True
            self.cv_auto_drive_active = True  # Flag to track auto-drive status

            # "Auto-drive" is LIDAR cruise: let the avoider drive forward and
            # avoid obstacles. Do NOT pause() it here — pausing killed the lidar
            # cruise (the watchdog can't re-enable it because
            # _last_manual_cmd_time starts at 0 at boot) and the camera
            # line-follow that took over creeps at ~6 cm/s with no line then
            # freezes on the first close object = "drives forward then stops".
            avoider = getattr(self, "avoider", None)
            if avoider is not None and f['base_config']['use_lidar']:
                avoider.resume()
                sd = getattr(self, "self_driver", None)
                if sd is not None:
                    sd.resume()   # planner learns surroundings + steers cruise
            else:
                # No LIDAR: fall back to camera line-follow.
                self.set_cv_mode(f['code']['cv_auto'])

            # Optionally, provide feedback to the user
            self.speak_minion("Auto-drive started boss!")

        elif command == "stop_auto_drive":
            logging.info("Stopping auto drive...")
            self.robot_moving = False
            self.cv_auto_drive_active = False  # Disable auto-drive flag
            self.set_cv_mode(f['code']['cv_none'])  # Reset mode to default

            # Hand the wheels back / halt so the ESP32 doesn't keep the last
            # avoider speed latched (that latch made the robot keep rolling
            # after "stop").
            avoider = getattr(self, "avoider", None)
            if avoider is not None:
                avoider.pause(halt=True)
            sd = getattr(self, "self_driver", None)
            if sd is not None:
                sd.pause()   # persist the learned surroundings

            # Provide feedback to the user
            self.speak_minion("Auto-drive stopped.")

    # Start the wake word detection in a separate thread
    def start_listening(self):
        Thread(target=self.listen_for_wake_word, daemon=True).start()
    
    # Ensure no movement during interaction
    def handle_interaction(self):
        self.robot_moving = False
        self.listen_for_question()
        self.robot_moving = True
        
    def send_base_command(self, command):
        """
        Send a command to the base controller and log it to both file and log system.
        """
        try:
            # Log command to file
            self.log_command_to_file(command)

            # Send the command and get the response
            response = self.base_ctrl.base_json_ctrl(command)

            # Log response for debugging
            logging.info(f"Raw response: {response}")
            if response:
                try:
                    response_data = json.loads(response)
                    logging.info(f"Parsed response data: {response_data}")
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON decode error: {e} with response: {response}")
            else:
                logging.warning("Received empty response from base controller.")
        except Exception as e:
            logging.warning(f"Error sending command to base controller: {e}")    ### Environment Learning and Memory Buffer:
        # Greet user and handle interaction after wake word
    def respond_to_greeting(self):
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config)
        
        # Greet the user
        synthesizer.speak_text_async("Hi, how can I be of service?").get()
        self.last_announcement_time = time.time()

        # Start interaction for a question
        self.listen_for_question()

        # Resume robot activities after interaction
        self.speaking = False

    
    def learn_environment(self):
        # Capture current environment data, e.g., from LIDAR, and store it in memory
        surrounding_data = {
            'lidar': self.lidar_data,
            'position': self.get_current_position(),
            # Add other relevant sensor data here
        }
        with open("environment_memory.json", "a") as f:
            json.dump(surrounding_data, f)
            logging.info(surrounding_data)
            f.write("\n")

    def lidar_detect_human(self):
        object_close = False

        if self.lidar_data:
            min_distance_left = min([data[0] for data in self.lidar_data])
            min_distance_right = min([data[1] for data in self.lidar_data])

            self.lidar_distance_left = min_distance_left / 1000.0
            self.lidar_distance_right = min_distance_right / 1000.0

            if self.lidar_distance_left < 1.0 or self.lidar_distance_right < 1.0:
                object_close = True

        return object_close
        
    def send_base_command(self, command):
        """
        Send a command to the base controller and log the output.
        """
        try:
            # Log the command being sent
            self.log_command_output(command)
            
            # Send the command
            response = self.base_ctrl.base_json_ctrl(command)

            # Log the raw response if available
            logging.info(f"Raw response: {response}")
            if response:
                # Attempt to parse the response as JSON
                try:
                    response_data = json.loads(response)
                    logging.info(f"Parsed response data: {response_data}")
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON decode error: {e} with response: {response}")
            else:
                logging.warning("Received empty response from base controller.")
        except Exception as e:
            logging.warning(f"Error sending command to base controller: {e}")
    # Example for other command methods
    def execute_command(self, command):
        """
        Executes specific robot commands (e.g., start/stop self-drive) and logs them.
        """
        logging.info(f"Executing command: {command}")
        if command == "start_auto_drive":
            logging.info("Starting self-drive...")
            self.robot_moving = True
            self.cv_auto_drive_active = True
            # Start the learning self-driver so the robot learns its surroundings
            # (LIDAR grid + camera objects) and uses them to pick safe headings.
            self.self_driver = getattr(self, "self_driver", None)
            if self.self_driver is not None:
                self.self_driver.start()
                self.self_driver.resume()
            sd = getattr(self, "self_driver", None)
            if sd is not None and f['base_config']['use_lidar']:
                sd.resume()   # planner learns surroundings + steers cruise
            else:
                # No LIDAR: fall back to camera line-follow.
                self.set_cv_mode(f['code']['cv_auto'])
            self.log_command_output({"action": "start_self_drive"})

        elif command == "stop_auto_drive":
            logging.info("Stopping self-drive...")
            self.robot_moving = False
            self.cv_auto_drive_active = False
            self.set_cv_mode(f['code']['cv_none'])
            # Halt so the ESP32 doesn't keep the last avoider speed latched.
            avoider = getattr(self, "avoider", None)
            if avoider is not None:
                avoider.pause(halt=True)
            sd = getattr(self, "self_driver", None)
            if sd is not None:
                sd.pause()   # persist the learned surroundings
            self.log_command_output({"action": "stop_self_drive"})

    # Add log_command_output calls to other methods as needed

    def mediaPipe_faces(self, img):
        image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.face_detection.process(image)

        overlay_buffer = np.zeros_like(image)
        cv2.putText(overlay_buffer, 'MediaPipe Faces', (100, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if results.detections:
            for detection in results.detections:
                self.mpDraw.draw_detection(overlay_buffer, detection)
        self.overlay = overlay_buffer

    def mediaPipe_pose(self, img):
        image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.pose.process(image)

        overlay_buffer = np.zeros_like(image)
        cv2.putText(overlay_buffer, 'MediaPipe Pose', (100, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if results.pose_landmarks:
            self.mpDraw.draw_landmarks(overlay_buffer, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)
        self.overlay = overlay_buffer

    def info_update(self, megs, color, size):
        if megs == -1:
            self.info_update_time = time.time()
            self.show_info_flag = True
            return
        wrapped_lines = textwrap.wrap(megs, self.recv_line_max)
        for line in wrapped_lines:
            self.info_deque.appendleft({'text':line,'color':color,'size':size})
        self.info_update_time = time.time()
        self.show_info_flag = True

    def commandline_ctrl(self, args_str):
        return

    def show_recv_info(self, input_cmd):
        if input_cmd == True:
            self.show_base_info_flag = True
        else:
            self.show_base_info_flag = False
        print(self.show_base_info_flag)

    def format_json_numbers(self, obj):
        if isinstance(obj, dict):
            return {k: self.format_json_numbers(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.format_json_numbers(elem) for elem in obj]
        elif isinstance(obj, float):
            return round(obj, 2)
        return obj

    def update_base_data(self, input_data):
        if not input_data:
            return
        try:
            # Battery: the ESP32 broadcasts pack voltage as "v" (3S LiPo:
            # 12.6 V full, 9.9 V empty).  Store as a 0-100 percentage.
            v = input_data.get("v")
            if isinstance(v, (int, float)) and v > 0:
                pct = int((v - 9.9) / (12.6 - 9.9) * 100)
                self.battery_level = max(0, min(100, pct))
            if self.show_base_info_flag:
                self.recv_deque.appendleft(json.dumps(self.format_json_numbers(input_data)))
            if input_data['T'] == 1003:
                self.info_deque.appendleft({'text':json.dumps(input_data['mac']),'color':(16,64,255),'size':0.5})
                wrapped_lines = textwrap.wrap(json.dumps(input_data['megs']), self.recv_line_max)
                for line in wrapped_lines:
                    self.info_deque.appendleft({'text':line,'color':(255,255,255),'size':0.5})
                self.info_update_time = time.time()
                self.show_info_flag = True
        except Exception as e:
            print(f"[cv_ctrl.update_base_data] error: {e}")




    def cv_process(self, frame):
        cv_mode_list = {
            f['code']['cv_moti']: self.cv_detect_movition,
            f['code']['cv_face']: self.cv_detect_faces,
            f['code']['cv_objs']: self.cv_detect_objects,
            f['code']['cv_clor']: self.cv_detect_color,
            f['code']['mp_hand']: self.mp_detect_hand,
            f['code']['cv_auto']: self.cv_auto_drive,
            f['code']['mp_face']: self.mediaPipe_faces,
            f['code']['mp_pose']: self.mediaPipe_pose
        }
        try:
            cv_mode_list[self.cv_mode](frame)
        except Exception as e:
            print(f'[cv_ctrl.cv_process] error: {e}')
        self.cv_event.clear()

    def opencv_threading(self, input_img):
        cv_thread = threading.Thread(target=self.cv_process, args=(input_img,), daemon=True)
        cv_thread.start()

    def toggle_lights(self, on):
        """Head lights on/off (used by the voice interaction path)."""
        self.head_light_ctrl(2 if on else 0)

    def head_light_ctrl(self, input_mode):
        self.cv_light_mode = input_mode
        if input_mode == 0:
            self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 0)
            self.cv_light_mode = input_mode
        elif input_mode == 2:
            self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 255)
            self.cv_light_mode = input_mode
        elif input_mode == 3:
            if self.cv_light_mode == 1:
                return
            elif self.base_ctrl.head_light_status == 0:
                self.cv_light_mode = 2
                self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 255)
            elif self.base_ctrl.head_light_status != 0:
                self.cv_light_mode = 0
                self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 0)

    def set_movtion_lock(self, input_cmd):
        if not input_cmd:
            self.cv_movtion_lock = False
            self.pan_angle = 0
            self.tilt_angle = 0
        else:
            self.cv_movtion_lock = True




    def change_target_color(self, lc, uc):
        self.color_lower = np.array([lc[0], lc[1], lc[2]])
        self.color_upper = np.array([uc[0], uc[1], uc[2]])

    def selet_target_color(self, color_name):
        if color_name in self.color_list:
            self.color_lower = self.color_list[color_name][0]
            self.color_upper = self.color_list[color_name][1]

    def change_line_color(self, lc, uc):
        self.line_lower = np.array([lc[0], lc[1], lc[2]])
        self.line_upper = np.array([uc[0], uc[1], uc[2]])

    def set_line_track_args(self, sam_pos_1, sam_pos_2, slope_im, base_im, spd_im, lt_spd, slope_spd):
        self.sampling_line_1 = sam_pos_1
        if sam_pos_2 < sam_pos_1:
            sam_pos_2 = sam_pos_1 + 0.1
        self.sampling_line_2 = sam_pos_2
        self.slope_impact = slope_im
        self.base_impact = base_im
        self.speed_impact = spd_im
        self.line_track_speed = lt_spd
        self.slope_on_speed = slope_spd

    def set_pt_track_args(self, args_1, args_2):
        if args_1 == '-c' or args_1 == '--color_iterate':
            self.track_color_iterate = float(args_2)
        elif args_1 == '-f' or args_1 == '--faces_iterate':
            self.track_faces_iterate = float(args_2)
        elif args_1 == '-s' or args_1 == '--speed':
            self.track_spd_rate = float(args_2)
        elif args_1 == '-a' or args_1 == '--acc':
            self.track_acc_rate = float(args_2)

    def timelapse(self, input_speed, input_time, input_interval, input_loop_times):
        self.mission_flag = True
        for i in range(0, input_loop_times):
            if not self.mission_flag:
                self.mission_flag = False
                break
            self.base_ctrl.base_json_ctrl({"T":1,"L":input_speed,"R":input_speed})
            time.sleep(input_time)
            self.base_ctrl.base_json_ctrl({"T":1,"L":0,"R":0})
            time.sleep(input_interval/2)
            self.base_ctrl.lights_ctrl(255, 255)
            time.sleep(0.01)
            self.picture_capture()
            self.base_ctrl.lights_ctrl(0, 0)
            time.sleep(input_interval/2)
            if not self.mission_flag:
                self.mission_flag = False
                break

    def mission_stop(self):
        self.mission_flag = False