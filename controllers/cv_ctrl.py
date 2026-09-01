import cv2
import signal
import imutils
import mediapipe as mp
import imageio
import threading
import datetime, time
import numpy as np
import math
import yaml, os, json, subprocess
from collections import deque
import textwrap
import re
from PIL import Image, ImageDraw, ImageFont
from .UltraFaceNcnn import UltraFaceNcnn
import signal
from enum import Enum
from math import isnan

# config file.
curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/../config.yaml', 'r') as yaml_file:
    f = yaml.safe_load(yaml_file)

log_file_path = os.path.join(thisPath,"Mediamtx", "mediamtx.log")

try:
    existing_pids = subprocess.check_output(
        ["pgrep", "-f", "mediamtx"], encoding="utf-8"
    ).splitlines()

    for pid_str in existing_pids:
        pid = int(pid_str)
        print(f"Killing existing mediamtx process: {pid}")
        os.kill(pid, signal.SIGTERM) 
except subprocess.CalledProcessError:
    pass
    
with open(log_file_path, "w") as log_file:
    mediamtx_command = [
        os.path.join(thisPath, "Mediamtx", "mediamtx"),
        os.path.join(thisPath, "Mediamtx", "mediamtx.yml"),
    ]
    mediamtx_process = subprocess.Popen(
        mediamtx_command,
        stdout=log_file,
        stderr=log_file
    )

def is_raspberry_pi5():
    with open('/proc/cpuinfo', 'r') as file:
        for line in file:
            if 'Model' in line:
                if 'Raspberry Pi 5' in line:
                    return True
                else:
                    return False

frame_width = f['video']['default_res_w']
frame_height = f['video']['default_res_h']

if is_raspberry_pi5():
   ffmpeg_command = [
        'ffmpeg',
        '-y',
        '-loglevel', 'quiet',    
        '-f', 'rawvideo',         
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',       
        '-s', f'{frame_width}x{frame_height}',           
        '-r', '30',                
        '-i', '-',                 
        '-c:v', 'libx264',         
        '-b:v', '300k',
        '-crf', '28',             
        '-pix_fmt', 'yuv420p',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-f', 'rtsp',              
        'rtsp://localhost:8554/cam'
    ]
else:
   ffmpeg_command = [
        'ffmpeg',
        '-y',
        '-loglevel', 'quiet',    
        '-f', 'rawvideo',         
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',       
        '-s', f'{frame_width}x{frame_height}',           
        '-r', '30',                
        '-i', '-',
        '-vf', 'format=yuv420p',                  
        '-c:v', 'h264_v4l2m2m',         
        '-b:v', '800k',
        '-pix_fmt', 'yuv420p',
        '-fflags', 'nobuffer',    
        '-f', 'rtsp',              
        'rtsp://localhost:8554/cam'
    ]

class TrackState(Enum):
    FOLLOW = 0
    SEARCH_SPIN = 1
    RECOVER = 2

def angle_diff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi

def robust_mean_remove_outliers(arr, mz_thresh=3.5, is_angle=False):
    if arr.size == 0:
        return 0.0
    med = np.median(arr)
    mad = np.median(np.abs(arr - med))
    if mad == 0:
        return float(np.mean(arr))
    mod_z = 0.6745 * (arr - med) / mad
    filtered = arr[np.abs(mod_z) <= mz_thresh]
    return float(np.mean(filtered)) if filtered.size > 0 else float(np.mean(arr))

class PID:
    def __init__(self, kp, ki, kd, output_limits, tolerance):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_time = None
        self.output_limits = output_limits
        self.tolerance = tolerance  

    def compute(self, setpoint, measurement):
        error = setpoint - measurement
        
        if abs(error) <= self.tolerance:
            self.integral = 0.0
            self.prev_error = 0.0
            self.prev_time = time.time()
            return 0.0

        now = time.time()
        dt = 0.0 if self.prev_time is None else now - self.prev_time

        self.integral += error * dt
        derivative = 0.0 if dt == 0 else (error - self.prev_error) / dt

        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        output = max(self.output_limits[0], min(self.output_limits[1], output))

        self.prev_error = error
        self.prev_time = now
        return output

font_path = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

def draw_chinese_text(img, text, position, font_size, color):
    img = cv2.resize(img, (frame_width, frame_height))
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    font = ImageFont.truetype(font_path, font_size)
    color_rgb = (color[2], color[1], color[0])
    draw.text(position, text, font=font, fill=color_rgb)
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

def contains_chinese(text):
    return bool(re.search('[\u4e00-\u9fff]', text))

class OpencvFuncs():
    """docstring for OpencvFuncs"""
    def __init__(self, project_path, base_ctrl):
        self.base_ctrl = base_ctrl      
        self.ffmpeg_process = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE)
        self.cv_event = threading.Event()
        self.cv_event.clear()
        self.cv_mode = f['code']['cv_none']
        self.detection_reaction_mode = f['code']['re_none']
        
        self.this_path = thisPath
        self.photo_path = self.this_path + '/../templates/media/pictures/'
        self.video_path = self.this_path + '/../templates/media/videos/'
        self.frame_scale = 1
        self.picture_capture_flag = False
        self.set_video_record_flag = False
        self.video_record_status_flag = False
        self.writer = None
        self.overlay = None
        self.scale_rate = 1

        # cv ctrl info
        self.cv_light_mode = 0
        self.video_fps = 0
        self.fps_start_time = time.time()
        self.fps_count = 0
        self.cv_movtion_lock = True
        self.base_width = 640
        self.base_height = 480
        self.cv_w_scale = frame_width/self.base_width
        self.cv_h_scale = frame_height/self.base_height

        # reaction
        self.last_frame_capture_time = datetime.datetime.now()
        self.last_movtion_captured = datetime.datetime.now()

        # movtion detection
        self.avg = None

        # face detection & tracking
        self.face_detector = UltraFaceNcnn(thisPath + '/models/ultraface-ncnn/RFB-320.param',thisPath + '/models/ultraface-ncnn/RFB-320.bin', input_size=(320,240), threshold=0.7, nms_threshold=0.3)

        # color detection
        self.track_base = f['cv']['track_base']
        color_name = f['cv']['default_color']

        self.color_list = f['cv']['color_list']
        self.color_lower = np.array(self.color_list[color_name]['lower'], dtype=np.uint8)
        self.color_upper = np.array(self.color_list[color_name]['upper'], dtype=np.uint8)

        self.ball_diameter = 0.038
        self.target_distance = 0.2
        self.target_yaw = 0.0

        self.x_distance_pid = PID(kp=1.25, ki=0.0, kd=0.05, output_limits=(-0.3, 0.3), tolerance=0.05)
        self.angle_pid = PID(kp=2.0, ki=0.00, kd=0.0, output_limits=(-1.5708, 1.5708), tolerance=0.1)

        self.distance_buffer = deque(maxlen=10)
        self.color_ball_yaw_buffer = deque(maxlen=10)
        self.cam_k = np.array([
                        [289.11451,   0.     , 347.23664],
                        [  0.     , 289.75319, 235.67429],
                        [  0.     ,   0.     ,   1.     ]
                    ], dtype=np.float64)

        self.pt_x = 0.0  
        self.pt_y = 0.0 
        self.pt_x_pid = PID(kp=0.9, ki=0.0, kd=0.1, output_limits=(-math.pi/4, math.pi/4), tolerance=0.02)
        self.pt_y_pid = PID(kp=0.7, ki=0.0, kd=0.05, output_limits=(-math.pi/4, math.pi/4), tolerance=0.02)

        self.pan_angle = 0
        self.tilt_angle = 0

        # cv_dnn_objects
        self.net = cv2.dnn.readNetFromCaffe(thisPath + '/models/deploy.prototxt', thisPath + '/models/mobilenet_iter_73000.caffemodel')
        self.class_names = ["background", "aeroplane", "bicycle", "bird", "boat",
                            "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
                            "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
                            "sofa", "train", "tvmonitor"]

        # mediapipe
        self.mpDraw = mp.solutions.drawing_utils

        # mediapipe detect hand
        self.mpHands = mp.solutions.hands
        self.hands = self.mpHands.Hands(max_num_hands=1)
        self.max_distance = 1
        self.gs_pic_interval = 6
        self.gs_pic_last_time = time.time()

        # findline autodrive
        self.state = TrackState.FOLLOW

        self.yaw = None
        self.kp = 3.0
        self.kd = 0.05
        self.last_error = 0.0
        self.line_track_speed = 0.2
        self.yaw_buffer = deque(maxlen=10)
        
        self.line_lower = np.array(f['cv']['line_lower'], dtype=np.uint8)
        self.line_upper = np.array(f['cv']['line_upper'], dtype=np.uint8)
        module_type = f['base_config']['module_type']
        if module_type==0 or module_type==2:
            self.roi = [
                (250, 300, 40, 600, 0.1),
                (300, 400, 40, 600, 0.3),
                (400, 480, 40, 600, 0.6),
            ]
        elif module_type==1 or module_type==3:
            self.roi = [
            (150, 200, 40, 600, 0.2),
            (200, 250, 40, 600, 0.3),
            (250, 300, 40, 600, 0.5)
        ]
        # --- SEARCH_SPIN ---
        self.search_start_time = 0.0
        self.scan_dir = -1                          
        self.scan_yaw_base = 0.5           
        self.scan_yaw_max = 3.1416
        self.max_scan_time = 10.0            
        
        # --- RECOVER ---
        self.recover_start_time = 0.0
        self.recover_time = 0.4              

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
        self.info_scale = 9/16
        self.info_bg_color = (0, 0, 0)
        self.info_show_time = 10
        self.recv_line_max = 26

        # mission funcs
        self.mission_flag = False

        # osd settings
        self.add_osd = f['base_config']['add_osd']
        # camera type detection
        self.init_camera(f)

    def init_camera(self, f):
        self.usb_camera_connected = self.usb_camera_detection()
        self.csi_camera_connected = False
        self.oak_camera_connected = False

        if self.usb_camera_connected:
            try:
                # self.camera = cv2.VideoCapture(0)
                self.camera = cv2.VideoCapture(0, cv2.CAP_V4L2)
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH,  frame_width)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
                self.camera.set(
                    cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(*'MJPG')
                )
                print("USB camera initialized.")
                return True
            except:
                self.usb_camera_connected = False

        if not self.usb_camera_connected:
            print("Trying to init CSI camera...")
            try:
                from picamera2 import Picamera2
                from picamera2.encoders import H264Encoder, Encoder
                from picamera2.outputs import FfmpegOutput    

                self.encoder = H264Encoder(1000000)
                self.picam2 = Picamera2()
                self.picam2.configure(
                    self.picam2.create_video_configuration(
                        main={
                            "format": 'XRGB8888',
                            "size": (frame_width, frame_height)
                        }
                    )
                )
                self.picam2.start()
                self.csi_camera_connected = True
                print("CSI camera initialized.")
                return True

            except Exception as e:
                print(f"CSI camera init failed: {e}")
                self.csi_camera_connected = False

        if not self.usb_camera_connected and not self.csi_camera_connected:
            print("Trying to init OAK camera...")
            try:
                import depthai as dai

                self.pipeline = dai.Pipeline()
                self.camRgb = self.pipeline.createColorCamera()

                self.camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
                self.camRgb.setInterleaved(False)
                self.camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
                self.camRgb.setPreviewSize(frame_width, frame_height)
                self.camRgb.setPreviewKeepAspectRatio(False)

                self.xout = self.pipeline.createXLinkOut()
                self.xout.setStreamName("preview")
                self.camRgb.preview.link(self.xout.input)

                self.device = dai.Device(self.pipeline)
                self.output_queue = self.device.getOutputQueue(name="preview", maxSize=8, blocking=False)

                self.oak_camera_connected = True
                print("OAK camera initialized.")
                return True

            except Exception as e:
                print(f"OAK camera init failed: {e}")
                self.oak_camera_connected = False

        print("No available camera found.")
        return False

    def frame_process(self):
        while True:
            try:
                if self.usb_camera_connected:
                    success, input_frame = self.camera.read()
                    if not success or input_frame is None:
                        self.camera.release()
                        time.sleep(1)
                        self.camera = cv2.VideoCapture(0, cv2.CAP_V4L2)
                        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH,  frame_width)
                        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
                        self.camera.set(
                            cv2.CAP_PROP_FOURCC,
                            cv2.VideoWriter_fourcc(*'MJPG')
                        )

                elif self.csi_camera_connected:
                    input_frame = self.picam2.capture_array()
                elif self.oak_camera_connected:
                    input_frame = self.output_queue.get().getCvFrame()
                else:
                    input_frame = 255 * np.ones((frame_height, frame_width, 3), dtype=np.uint8)
                    cv2.putText(input_frame, f"camera read failed... \nusb - csi - oak", 
                                (round(0.05*frame_width), round(0.1*frame_width + 5 * 13)), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.369*self.cv_h_scale, (0, 0, 0),int(self.cv_h_scale))
            except Exception as e:
                print(f"[cv_ctrl.frame_process] error: {e}")
                input_frame = 255 * np.ones((frame_height, frame_width, 3), dtype=np.uint8)
                cv2.putText(input_frame, f"camera read failed... \n{e}", 
                            (round(0.05*frame_width), round(0.1*frame_width + 5 * 13)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.369*self.cv_h_scale, (0, 0, 0),int(self.cv_h_scale))
        
            # opencv funcs
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
                cv2.rectangle(self.overlay, (round((self.info_scale-0.005)*frame_width), round((0.33)*frame_height)), 
                                        (round(0.98*frame_width), round((0.78)*frame_height)), self.info_bg_color, -1)
                cv2.addWeighted(self.overlay, 0.5, input_frame, 0.5, 0, input_frame)

                # info_deque.appendleft(time.time())

                for i in range(0, len(self.info_deque)):
                    text = str(self.info_deque[i]['text'])
                    size = self.info_deque[i]['size']
                    color = self.info_deque[i]['color'] 
                    base_x = round(self.info_scale * frame_width)
                    base_y = round(0.75 * frame_height - i * 20*self.cv_h_scale)
                    if contains_chinese(text):
                        input_frame = draw_chinese_text(input_frame, text, 
                                    (base_x, base_y - 10), 
                                    int(35*size*self.cv_h_scale), color)
                    else:
                        cv2.putText(input_frame, text, 
                                (base_x, base_y), 
                                cv2.FONT_HERSHEY_SIMPLEX, size*self.cv_h_scale, color,int(self.cv_h_scale))  
                    
            if self.show_base_info_flag:
                for i in range(0, len(self.recv_deque)):
                    cv2.putText(input_frame, str(self.recv_deque[i]), 
                            (round(0.05*frame_width), round(0.1*frame_width + i * 13)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.369*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))

            # render osd
            input_frame = self.osd_render(input_frame)

            # capture frame
            if self.picture_capture_flag:
                current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                photo_filename = f'{self.photo_path}photo_{current_time}.jpg'
                try:
                    cv2.imwrite(photo_filename, input_frame)
                    self.picture_capture_flag = False
                    print(photo_filename)
                except:
                    pass

            # record video
            if not self.set_video_record_flag and not self.video_record_status_flag:
                pass
            elif self.set_video_record_flag and not self.video_record_status_flag:
                current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                video_filename = f'{self.video_path}video_{current_time}.mp4'
                self.writer = imageio.get_writer(video_filename, fps=30)
                self.video_record_status_flag = True
            elif self.set_video_record_flag and self.video_record_status_flag:
                cv2.circle(input_frame, (15, 15), int(5*self.cv_h_scale), (64, 64, 255), -1)
                self.writer.append_data(np.array(cv2.cvtColor(input_frame, cv2.COLOR_BGRA2RGB)))
            elif not self.set_video_record_flag and self.video_record_status_flag:
                self.video_record_status_flag = False
                self.writer.close()

            # frame scale
            if self.scale_rate == 1:
                pass
            else:
                img_height, img_width = input_frame.shape[:2]
                new_width = int(img_width * self.scale_rate)
                new_height = int(img_height * self.scale_rate)
                resized_frame = cv2.resize(input_frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)

                if self.scale_rate > 1:
                    x_center = new_width // 2
                    y_center = new_height // 2
                    x_start = x_center - img_width // 2
                    y_start = y_center - img_height // 2
                    input_frame = resized_frame[y_start:y_start+img_height, x_start:x_start+img_width]
                else:
                    input_frame = np.zeros((img_height, img_width, 3), dtype=input_frame.dtype)
                    x_offset = (img_width - new_width) // 2
                    y_offset = (img_height - new_height) // 2
                    input_frame[y_offset:y_offset+new_height, x_offset:x_offset+new_width] = resized_frame

            # encode frame
            try:
                self.ffmpeg_process.stdin.write(input_frame.tobytes())
                self.ffmpeg_process.stdin.flush()
            except:
                pass

            time.sleep(1/30)
            # get fps
            self.fps_count += 1
            if time.time() - self.fps_start_time >= 2:
                self.video_fps = self.fps_count/2
                self.fps_count = 0
                self.fps_start_time = time.time()
                
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
        # cv2.putText(overlay_buffer, 'OSD_TEST', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))

        # render lidar data
        lidar_points = []
        for lidar_angle, lidar_distance in zip(self.base_ctrl.rl.lidar_angles_show, self.base_ctrl.rl.lidar_distances_show):
            lidar_x = int(lidar_distance * np.cos(lidar_angle) * 0.05) + 320
            lidar_y = int(lidar_distance * np.sin(lidar_angle) * 0.05) + 240
            lidar_points.append((lidar_x, lidar_y))

        for lidar_point in lidar_points:
            cv2.circle(osd_frame, lidar_point, int(3*self.cv_h_scale), (255, 0, 0), -1)

        # render sensor data
        sensor_index = 0
        for sensor_line in self.base_ctrl.rl.sensor_data:
            # sensor_line = sensor_line[:-2]
            cv2.putText(osd_frame, sensor_line,
                        (int(100*self.cv_w_scale), int((50 + sensor_index * 20*self.cv_h_scale))), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255,255,255),int(self.cv_h_scale))
            sensor_index = sensor_index + 1


        return osd_frame

    def picture_capture(self):
        self.picture_capture_flag = True

    def video_record(self, input_cmd):
        if input_cmd==1:
            self.set_video_record_flag = True
        else:
            self.set_video_record_flag = False

    def scale_ctrl(self, input_rate):
        if input_rate < 1:
            self.scale_rate = 1
        else:
            self.scale_rate = input_rate

    def set_cv_mode(self, input_mode):
        self.cv_mode = input_mode
        if self.cv_mode == f['code']['cv_none']:
            self.set_video_record_flag = False

    def set_detection_reaction(self, input_reaction):
        self.detection_reaction_mode = input_reaction
        if self.detection_reaction_mode == f['code']['re_none']:
            self.set_video_record_flag = False

    def cv_detect_movition(self, img):
        overlay_buffer = np.zeros_like(img)
        height, width = img.shape[:2]
        img = cv2.resize(img, (self.base_width, self.base_height))

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
        for c in cnts:
            # if the contour is too small, ignore it
            if cv2.contourArea(c) < 2000:
                continue
            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            (mov_x, mov_y, mov_w, mov_h) = cv2.boundingRect(c)
            mov_x = int(mov_x * self.cv_w_scale)
            mov_y = int(mov_y * self.cv_h_scale)
            mov_w = int(mov_w * self.cv_w_scale)
            mov_h = int(mov_h * self.cv_h_scale)
            cv2.rectangle(overlay_buffer, (mov_x, mov_y), (mov_x + mov_w, mov_y + mov_h), (128, 255, 0),int(self.cv_h_scale))
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

    def set_track_base(self, track_base):
        if track_base in ['ugv', 'pt']:
            self.track_base = track_base
        else:
            self.track_base = 'ugv'

    def cv_detect_faces(self, img):
        overlay_buffer = np.zeros_like(img)
        height, width = img.shape[:2]
        img = cv2.resize(img, (self.base_width, self.base_height))
        faces = self.face_detector.detect(img)

        center_x, center_y = width // 2, height // 2

        max_area = 0
        max_face_center = (0, 0)

        if len(faces):
            if self.cv_light_mode == 1:
                if self.base_ctrl.head_light_status == 0:
                    self.base_ctrl.head_light_status = 255
                    self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, self.base_ctrl.head_light_status)

            for face in faces:
                face.x1 = int(face.x1 * self.cv_w_scale)
                face.y1 = int(face.y1 * self.cv_h_scale)
                face.x2 = int(face.x2 * self.cv_w_scale)
                face.y2 = int(face.y2 * self.cv_h_scale)
                cv2.rectangle(overlay_buffer,(int(face.x1),int(face.y1)),(int(face.x2),int(face.y2)),(64,128,255),1)
                face_area = (face.x2-face.x1) * (face.y2-face.y1)
                if face_area > max_area:
                    max_area = face_area
                    max_face_center = ((face.x1 + face.x2) / 2, (face.y1 + face.y2) /2)

            if not self.cv_movtion_lock:
                error_x = 0.1*(max_face_center[0] - center_x) / center_x
                error_y = 0.1*(max_face_center[1] - center_y) / center_y

                delta_x = self.pt_x_pid.compute(0.0, error_x)
                delta_y = self.pt_y_pid.compute(0.0, error_y)

                self.pt_x += delta_x
                self.pt_y += delta_y

                self.pt_x = max(-3.14, min(3.14, self.pt_x))
                self.pt_y = max(-0.523, min(1.57, self.pt_y))

                self.pan_angle = -(180 * self.pt_x) / 3.14
                self.tilt_angle = (180 * self.pt_y) / 3.14

                self.base_ctrl.base_json_ctrl({"T": f['cmd_config']['cmd_gimbal_ctrl'],"X": self.pan_angle,"Y": self.tilt_angle,"SPD": 0,"ACC":128})
                cv2.putText(overlay_buffer, f'X: {self.pan_angle:.2f} Y: {self.tilt_angle:.2f}',(int(80*self.cv_h_scale), int(90*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
                
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

        cv2.putText(overlay_buffer, 'NUMBER: {}'.format(len(faces)), (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), 
                                                            cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
        self.overlay = overlay_buffer

    def cv_detect_objects(self, img):
        overlay_buffer = np.zeros_like(img)
        cv2.putText(overlay_buffer, 'CV_OBJS', (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))

        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        (h, w) = img.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 0.007843, (300, 300), 127.5)
        self.net.setInput(blob)
        detections = self.net.forward()

        for i in range(0, detections.shape[2]):
            confidence = detections[0, 0, i, 2]

            if confidence > 0.2:
                idx = int(detections[0, 0, i, 1])
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (startX, startY, endX, endY) = box.astype("int")

                label = "{}: {:.2f}%".format(self.class_names[idx], confidence * 100)
                cv2.rectangle(overlay_buffer, (startX, startY), (endX, endY), (0, 255, 0),int(self.cv_h_scale))
                y = startY - 15 if startY - 15 > 15 else startY + 15
                cv2.putText(overlay_buffer, label, (startX, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (0, 255, 0),int(self.cv_h_scale))

        self.overlay = overlay_buffer

    def cv_detect_color(self, img):
        overlay_buffer = np.zeros_like(img)
        height, width = img.shape[:2]
        img = cv2.resize(img, (self.base_width, self.base_height))
        cx, cy, w = None, None, None
        input_speed_x = 0
        input_turning = 0
        center_x, center_y = self.base_width // 2, self.base_height // 2
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        mask = cv2.inRange(lab, self.color_lower, self.color_upper)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            c = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(c)
            if area > 100:  
                ((x, y), radius) = cv2.minEnclosingCircle(c)
                circularity = area / (math.pi * radius * radius)
                if 0.5 < circularity < 1.3:  
                    cx, cy, w = int(x), int(y), int(radius*2)
                    cv2.circle(overlay_buffer, (int(cx* self.cv_w_scale), int(cy * self.cv_h_scale)), int(radius*self.cv_h_scale), (0, 255, 0),int(self.cv_h_scale))
                    cv2.circle(overlay_buffer, (int(cx* self.cv_w_scale), int(cy * self.cv_h_scale)), int(3*self.cv_h_scale), (255, 0, 0), -1)
                    # print(f'Tracking ball at ({cx* self.cv_w_scale}, {cy * self.cv_h_scale}), area={area:.1f}, circularity={circularity:.2f}')

        if cx is not None:
            if self.track_base =='ugv':
                distance_m = (self.ball_diameter * self.cam_k[0,0]) / w
                self.distance_buffer.append(distance_m)
                distance_avg = robust_mean_remove_outliers(np.array(self.distance_buffer))

                error_x = cx - center_x
                current_yaw = np.arctan2(error_x, self.cam_k[0,0])
                self.color_ball_yaw_buffer.append(current_yaw)
                yaw_avg = robust_mean_remove_outliers(np.array(self.color_ball_yaw_buffer), is_angle=True)

                input_speed_x = -self.x_distance_pid.compute(self.target_distance, distance_avg)
                yaw_ctrl = self.angle_pid.compute(self.target_yaw, yaw_avg)
                yaw_err = abs(yaw_avg)
                distance_err = abs(distance_avg - self.target_distance)
                input_turning = yaw_ctrl

            if self.track_base =='pt':
                error_x = 0.1*(cx - center_x) / center_x
                error_y = 0.1*(cy - center_y) / center_y

                delta_x = self.pt_x_pid.compute(0.0, error_x)
                delta_y = self.pt_y_pid.compute(0.0, error_y)

                self.pt_x += delta_x
                self.pt_y += delta_y

                self.pt_x = max(-3.14, min(3.14, self.pt_x))
                self.pt_y = max(-0.523, min(1.57, self.pt_y))

                self.pan_angle = -(180 * self.pt_x) / 3.14
                self.tilt_angle = (180 * self.pt_y) / 3.14

        if not self.cv_movtion_lock:
            if self.track_base =='ugv':
                self.base_ctrl.base_json_ctrl({"T": f['cmd_config']['cmd_ros_movition_ctrl'],"X": input_speed_x,"Z": input_turning})
                cv2.putText(overlay_buffer, f'X: {input_speed_x:.2f} Z: {input_turning:.2f}',(int(80*self.cv_h_scale), int(100*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
            if self.track_base =='pt':
                self.base_ctrl.base_json_ctrl({"T": f['cmd_config']['cmd_gimbal_ctrl'],"X": self.pan_angle,"Y": self.tilt_angle,"SPD": 0,"ACC":128})
                cv2.putText(overlay_buffer, f'X: {self.pan_angle:.2f} Y: {self.tilt_angle:.2f}',(int(80*self.cv_h_scale), int(100*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
                
        cv2.putText(overlay_buffer, ' UPPER: {}'.format(self.color_upper), (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 128, 128),int(self.cv_h_scale))
        cv2.putText(overlay_buffer, ' LOWER: {}'.format(self.color_lower), (int(80*self.cv_h_scale), int(80*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 128, 128),int(self.cv_h_scale))
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
        overlay_buffer = np.zeros_like(img)
        height, width = img.shape[:2]
        img = cv2.resize(img, (self.base_width, self.base_height))

        center_x, center_y = width // 2, height // 2

        imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.hands.process(imgRGB)

        get_pwm = 0

        if results.multi_hand_landmarks:
            for handLms in results.multi_hand_landmarks:
                xs = []
                ys = []
                landmark_points = []
                # draw joints
                for id, lm in enumerate(handLms.landmark):
                    cx = int(lm.x * width)
                    cy = int(lm.y * height)
                    xs.append(cx)
                    ys.append(cy)
                    landmark_points.append((cx, cy))
                    cv2.circle(overlay_buffer, (cx, cy), int(5*self.cv_h_scale), (0, 0, 255), -1)

                # draw lines
                # self.mpDraw.draw_landmarks(overlay_buffer, handLms, self.mpHands.HAND_CONNECTIONS)

                target_pos = handLms.landmark[self.mpHands.HandLandmark.INDEX_FINGER_TIP]

                min_x, max_x = int(min(xs)), int(max(xs))
                min_y, max_y = int(min(ys)), int(max(ys))

                track_cx = int((min_x + max_x) / 2)
                track_cy = int((min_y + max_y) / 2)

                cv2.rectangle(overlay_buffer, (min_x, min_y), (max_x, max_y), (0, 255, 0),int(self.cv_h_scale))
                cv2.circle(overlay_buffer, (track_cx,track_cy), int(8*self.cv_h_scale), (0, 255, 0), -1)
                
                for connection in self.mpHands.HAND_CONNECTIONS:
                    start_idx = connection[0]
                    end_idx = connection[1]

                    x1, y1 = landmark_points[start_idx]
                    x2, y2 = landmark_points[end_idx]

                    cv2.line(overlay_buffer, (x1, y1), (x2, y2), (255,255,255), int(self.cv_h_scale))

                # print(f"x:{target_pos.x} y:{target_pos.y}")
                if not self.cv_movtion_lock:
                    error_x = 0.1*(track_cx - center_x) / center_x
                    error_y = 0.1*(track_cy - center_y) / center_y

                    delta_x = self.pt_x_pid.compute(0.0, error_x)
                    delta_y = self.pt_y_pid.compute(0.0, error_y)

                    self.pt_x += delta_x
                    self.pt_y += delta_y
                    self.pt_x = max(-3.14, min(3.14, self.pt_x))
                    self.pt_y = max(-0.523, min(1.57, self.pt_y))

                    self.pan_angle = -(180 * self.pt_x) / 3.14
                    self.tilt_angle = (180 * self.pt_y) / 3.14

                    self.base_ctrl.base_json_ctrl({"T": f['cmd_config']['cmd_gimbal_ctrl'],"X": self.pan_angle,"Y": self.tilt_angle,"SPD": 0,"ACC":128})
                    cv2.putText(overlay_buffer, f'X: {self.pan_angle:.2f} Y: {self.tilt_angle:.2f}',(int(80*self.cv_h_scale), int(60*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
                
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
                if self.cv_movtion_lock and middle_finger_gs > 20 and pinky_finger_gs > 90:
                    cv2.putText(overlay_buffer, ' GS: LED Ctrl', (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 128, 128),int(self.cv_h_scale))
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
                elif self.cv_movtion_lock and middle_finger_gs < 10 and pinky_finger_gs > 90 and index_finger_gs < 10:
                    cv2.putText(overlay_buffer, ' GS: Take Pic', (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 128, 128),int(self.cv_h_scale))
                    if time.time() - self.gs_pic_last_time > self.gs_pic_interval:
                        self.base_ctrl.lights_ctrl(255, 255)
                        time.sleep(0.01)
                        self.picture_capture()
                        self.base_ctrl.lights_ctrl(0, 0)
                        self.gs_pic_last_time = time.time()

                # Not Found
                elif self.cv_movtion_lock:
                    cv2.putText(overlay_buffer, ' GS: Not Defined', (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 128, 128),int(self.cv_h_scale))
                    self.base_ctrl.lights_ctrl(0, 0)

        self.overlay = overlay_buffer

    def cv_auto_drive(self, img):
        overlay_buffer = np.zeros_like(img)
        height, width = img.shape[:2]
        img = cv2.resize(img, (self.base_width, self.base_height))

        cx = width // 2

        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)

        weight_sum = 0
        cx_sum = 0
        has_line = False

        input_speed = 0.0
        input_turning = 0.0

        for (y1, y2, x1, x2, wt) in self.roi:
            crop = lab[y1:y2, x1:x2]
            mask = cv2.inRange(crop, self.line_lower, self.line_upper)
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue

            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) < 50:
                continue

            c = c.astype(np.float32)

            c[:, :, 0] += x1
            c[:, :, 1] += y1

            c[:, :, 0] *= self.cv_w_scale
            c[:, :, 1] *= self.cv_h_scale

            c = c.astype(np.int32)

            cv2.drawContours(overlay_buffer, [c], -1, (0,0,255), int(2*self.cv_h_scale))

            (x, y), _, _ = cv2.minAreaRect(c)
            cx_sum += x * wt
            weight_sum += wt
            has_line = True

        if self.state == TrackState.FOLLOW:
            if has_line and weight_sum > 0:

                x = cx_sum / weight_sum
                err = (x - cx) / cx

                self.yaw_buffer.append(err)
                err_f = robust_mean_remove_outliers(np.array(self.yaw_buffer))

                d = err_f - self.last_error
                self.last_error = err_f

                z = self.kp * err_f + self.kd * d

                input_speed = self.line_track_speed
                input_turning = -z

            else:
                self.state = TrackState.SEARCH_SPIN
                self.search_start_time = time.time()
                self.scan_dir = 1 if self.last_error > 0 else -1

                input_speed = 0.0
                input_turning = 0.0

        elif self.state == TrackState.SEARCH_SPIN:
            if has_line and weight_sum > 0:
                self.state = TrackState.RECOVER
                self.recover_start_time = time.time()
                self.last_error = 0.0
                self.yaw_buffer.clear()
                # print("Line found → RECOVER")
                input_speed = 0.0
                input_turning = 0.0

            dt = time.time() - self.search_start_time
            yaw = max(self.scan_yaw_max * (1 - dt / self.max_scan_time), self.scan_yaw_base)
            input_speed = 0.0
            input_turning = self.scan_dir * yaw

        elif self.state == TrackState.RECOVER:
            dt = time.time() - self.recover_start_time

            if has_line:
                if weight_sum > 0:
                    x = cx_sum / weight_sum
                else:
                    x = self.base_width // 2

                err = (x - cx) / cx
                z = 0.5 * self.kp * err

                input_speed = 0.0
                input_turning = -z

                if dt > self.recover_time:
                    self.state = TrackState.FOLLOW
                    self.last_error = 0.0
                    self.yaw_buffer.clear()

            else:
                self.state = TrackState.SEARCH_SPIN
                self.search_start_time = time.time()
                self.scan_dir = 1 if self.last_error > 0 else -1
                input_speed = 0.0
                input_turning = self.scan_dir * self.scan_yaw_base

        if not self.cv_movtion_lock:
            self.base_ctrl.base_json_ctrl({
                "T": f['cmd_config']['cmd_ros_movition_ctrl'],
                "X": input_speed,
                "Z": input_turning,
            })

        cv2.putText(overlay_buffer, f'State: {self.state.name}', (int(80*self.cv_h_scale), int(60*self.cv_h_scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
        cv2.putText(overlay_buffer, f'X: {input_speed:.2f}  Z: {input_turning:.2f}',
                    (int(80*self.cv_h_scale), int(90*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
        self.overlay = overlay_buffer

    def mediaPipe_faces(self, img):
        overlay_buffer = np.zeros_like(img)
        height, width = img.shape[:2]
        img = cv2.resize(img, (self.base_width, self.base_height))

        image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.face_detection.process(image)

        cv2.putText(overlay_buffer, 'MediaPipe Faces', (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
        if results.detections:
            for detection in results.detections:
                # self.mpDraw.draw_detection(overlay_buffer, detection)
                bbox = detection.location_data.relative_bounding_box

                xmin = int(bbox.xmin * width)
                ymin = int(bbox.ymin * height)
                w = int(bbox.width * width)
                h = int(bbox.height * height)

                cv2.rectangle(overlay_buffer,(xmin, ymin),(xmin + w, ymin + h),(0,255,0),int(self.cv_h_scale))

                for keypoint in detection.location_data.relative_keypoints:

                    x = int(keypoint.x * width)
                    y = int(keypoint.y * height)

                    cv2.circle(overlay_buffer, (x, y), 4, (0,0,255), -1)
        self.overlay = overlay_buffer

    def mediaPipe_pose(self, img):
        overlay_buffer = np.zeros_like(img)
        height, width = img.shape[:2]
        img = cv2.resize(img, (self.base_width, self.base_height))

        image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.pose.process(image)

        cv2.putText(overlay_buffer, 'MediaPipe Pose', (int(80*self.cv_h_scale), int(60*self.cv_h_scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.7*self.cv_h_scale, (255, 255, 255),int(self.cv_h_scale))
        if results.pose_landmarks:
            # self.mpDraw.draw_landmarks(overlay_buffer, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)
            landmark_points = []

            for lm in results.pose_landmarks.landmark:

                cx = int(lm.x * width)
                cy = int(lm.y * height)

                landmark_points.append((cx, cy))

                cv2.circle(overlay_buffer, (cx, cy), 4, (0,0,255), -1)

            for connection in self.mp_pose.POSE_CONNECTIONS:
                start_idx = connection[0]
                end_idx = connection[1]

                x1, y1 = landmark_points[start_idx]
                x2, y2 = landmark_points[end_idx]

                cv2.line(overlay_buffer, (x1,y1), (x2,y2), (255,255,255), int(self.cv_h_scale))
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
        # print(self.show_base_info_flag)

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
            f['code']['cv_color']: self.cv_detect_color,
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

    def head_light_ctrl(self, input_mode):
        cv_light_mode_list = {
            f['code']['led_off']: 0,
            f['code']['led_aut']: 1,
            f['code']['led_ton']: 2,
            f['code']['head_ct']: 3,
        }
        try:
            mode = cv_light_mode_list.get(int(input_mode))
        except (TypeError, ValueError):
            return
        if mode is None:
            return

        if mode == 0:
            self.cv_light_mode = 0
            self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 0)
        elif mode == 1:
            self.cv_light_mode = 1
        elif mode == 2:
            self.cv_light_mode = 2
            self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 255)
        elif mode == 3:
            if self.cv_light_mode == 1:
                return
            if self.base_ctrl.head_light_status == 0:
                self.cv_light_mode = 2
                self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 255)
            else:
                self.cv_light_mode = 0
                self.base_ctrl.lights_ctrl(self.base_ctrl.base_light_status, 0)

    def set_movtion_lock(self, input_cmd):
        if input_cmd == f['code']['mc_unlo']:
            self.cv_movtion_lock = False
        else:
            self.cv_movtion_lock = True

    def change_target_color(self, lc, uc):
        self.color_lower = np.array([lc[0], lc[1], lc[2]])
        self.color_upper = np.array([uc[0], uc[1], uc[2]])

    def selet_target_color(self, color_name):
        color = self.color_list.get(color_name)

        if color:
            self.color_lower = np.array(color['lower'], dtype=np.uint8)
            self.color_upper = np.array(color['upper'], dtype=np.uint8)
            print(f"[CV] Switch target color -> {color_name}")
        else:
            print(f"[CV] Color '{color_name}' not found in config")

    def change_line_color(self, lc, uc):
        self.line_lower = np.array([lc[0], lc[1], lc[2]])
        self.line_upper = np.array([uc[0], uc[1], uc[2]])

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
   