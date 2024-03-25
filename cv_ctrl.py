import cv2
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

# libraries for csi camera
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, Encoder
from picamera2.outputs import FfmpegOutput

# config file.
curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/config.yaml', 'r') as yaml_file:
    f = yaml.safe_load(yaml_file)


class OpencvFuncs():
    """docstring for OpencvFuncs"""
    def __init__(self, project_path, base_ctrl):
        self.base_ctrl = base_ctrl
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
        self.cv_movtion_lock = True
        self.aimed_error = f['cv']['aimed_error']
        self.track_spd_rate = f['cv']['track_spd_rate']
        self.track_acc_rate = f['cv']['track_acc_rate']
        self.CMD_GIMBAL = f['cmd_config']['cmd_gimbal_ctrl']
        self.sampling_rad = f['cv']['sampling_rad']

        # reaction
        self.last_frame_capture_time = datetime.datetime.now()
        self.last_movtion_captured = datetime.datetime.now()

        # movtion detection
        self.avg = None

        # face detection & tracking
        self.faceCascade = cv2.CascadeClassifier(thisPath + '/models/haarcascade_frontalface_default.xml')
        self.min_radius = f['cv']['min_radius']
        self.track_faces_iterate = f['cv']['track_faces_iterate']

        # color detection
        self.points = deque(maxlen=32)
        self.color_list = {
                        'red':  [np.array([  0,200, 170]), np.array([ 10, 255, 255])],
                        'green':[np.array([ 50, 130, 130]), np.array([ 78, 255, 255])],
                        'blue': [np.array([ 90,160, 150]), np.array([105, 255, 255])]
                        }
        if f['cv']['default_color'] in self.color_list:
            self.color_lower = self.color_list[f['cv']['default_color']][0]
            self.color_upper = self.color_list[f['cv']['default_color']][1]
        else:
            self.color_lower = np.array(f['cv']['color_lower'])
            self.color_upper = np.array(f['cv']['color_upper'])
        self.track_color_iterate = f['cv']['track_color_iterate']

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
        self.sampling_line_1 = 0.6
        self.sampling_line_2 = 0.9
        self.slope_impact = 1.5
        self.base_impact = 0.005
        self.speed_impact = 0.5
        self.line_track_speed = 0.3
        self.slope_on_speed = 0.1
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

        # mission funcs
        self.mission_flag = False

        # osd settings
        self.add_osd = f['base_config']['add_osd']

        # camera type detection
        self.usb_camera_connected = self.usb_camera_detection()

        # usb camera init
        if self.usb_camera_connected:
            self.camera = cv2.VideoCapture(0)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, f['video']['default_res_w'])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, f['video']['default_res_h'])

        # csi camera init
        if not self.usb_camera_connected:
            print("init csi camera.")
            self.encoder = H264Encoder(1000000)
            self.picam2 = Picamera2()
            self.picam2.configure(self.picam2.create_video_configuration(main={"format": 'XRGB8888', "size": (f['video']['default_res_w'], f['video']['default_res_h'])}))
            self.picam2.start()



    def frame_process(self):
        try:
            if self.usb_camera_connected:
                success, input_frame = self.camera.read()
                if not success:
                    self.camera.release()
                    time.sleep(1)
                    self.camera = cv2.VideoCapture(0)
            else:
                input_frame = self.picam2.capture_array()
        except Exception as e:
            print(f"[cv_ctrl.frame_process] error: {e}")
            input_frame = 255 * np.ones((480, 640, 3), dtype=np.uint8)
            cv2.putText(input_frame, f"camera read failed... \n{e}", 
                        (round(0.05*640), round(0.1*640 + 5 * 13)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.369, (0, 0, 0), 1)
            ret, buffer = cv2.imencode('.jpg', input_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.video_quality])
            input_frame = buffer.tobytes()
            return input_frame

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
            cv2.circle(input_frame, (15, 15), 5, (64, 64, 255), -1)
            self.writer.append_data(np.array(cv2.cvtColor(input_frame, cv2.COLOR_BGRA2RGB)))
        elif not self.set_video_record_flag and self.video_record_status_flag:
            self.video_record_status_flag = False
            self.writer.close()

        # frame scale
        if self.scale_rate == 1:
            pass
        else:
            img_height, img_width = input_frame.shape[:2]
            img_width_d2  = img_width/2
            img_height_d2 = img_height/2
            x_start = int(img_width_d2 - (img_width_d2//self.scale_rate))
            x_end   = int(img_width_d2 + (img_width_d2//self.scale_rate))
            y_start = int(img_height_d2 - (img_height_d2//self.scale_rate))
            y_end   = int(img_height_d2 + (img_height_d2//self.scale_rate))
            input_frame = input_frame[y_start:y_end, x_start:x_end]

        # encode frame
        try:
            ret, buffer = cv2.imencode('.jpg', input_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.video_quality])
            input_frame = buffer.tobytes()
        except:
            pass

        # get fps
        self.fps_count += 1
        if time.time() - self.fps_start_time >= 2:
            self.video_fps = self.fps_count/2
            self.fps_count = 0
            self.fps_start_time = time.time()

        # output frame
        return input_frame



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
        cv2.putText(overlay_buffer, 'CV_OBJS', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

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
                cv2.rectangle(overlay_buffer, (startX, startY), (endX, endY), (0, 255, 0), 2)
                y = startY - 15 if startY - 15 > 15 else startY + 15
                cv2.putText(overlay_buffer, label, (startX, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        self.overlay = overlay_buffer

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

    def cv_auto_drive(self, img):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # get a sampling
        height, width = img.shape[:2]
        center_x, center_y = width // 2, height // 2
        mask_sampling = np.zeros((height, width), dtype=np.uint8)
        cv2.circle(mask_sampling, (center_x, center_y), int(self.sampling_rad/4), (255), thickness=-1)
        masked_hsv = cv2.bitwise_and(hsv, hsv, mask=mask_sampling)
        masked_hsv_pixels = masked_hsv[mask_sampling == 255]
        lower_hsv = np.min(masked_hsv_pixels, axis=0)
        upper_hsv = np.max(masked_hsv_pixels, axis=0)

        # select the line color & get the mask
        # img = cv2.GaussianBlur(img, (11, 11), 0)
        line_mask = cv2.inRange(hsv, self.line_lower, self.line_upper)
        line_mask = cv2.erode(line_mask, None, iterations=2)
        line_mask = cv2.dilate(line_mask, None, iterations=2)

        sampling_h1 = int(height * self.sampling_line_1)
        sampling_h2 = int(height * self.sampling_line_2)

        get_sampling_1 = line_mask[sampling_h1]
        get_sampling_2 = line_mask[sampling_h2]

        sampling_width_1 = np.sum(get_sampling_1 == 255)
        sampling_width_2 = np.sum(get_sampling_2 == 255)

        if sampling_width_1:
            sam_1 = True
        else:
            sam_1 = False
        if sampling_width_2:
            sam_2 = True
        else:
            sam_2 = False

        line_index_1 = np.where(get_sampling_1 == 255)
        line_index_2 = np.where(get_sampling_2 == 255)

        if sam_1:
            sampling_1_left  = line_index_1[0][0]
            sampling_1_right = line_index_1[0][sampling_width_1 - 1]
            sampling_1_center= int((sampling_1_left + sampling_1_right) / 2)
        if sam_2:
            sampling_2_left  = line_index_2[0][0]
            sampling_2_right = line_index_2[0][sampling_width_2 - 1]
            sampling_2_center= int((sampling_2_left + sampling_2_right) / 2)

        line_slope = 0
        input_speed = 0
        input_turning = 0
        if sam_1 and sam_2:
            line_slope = (sampling_1_center - sampling_2_center) / abs(sampling_h1 - sampling_h2)
            impact_by_slope = self.slope_on_speed * abs(line_slope)
            # if impact_by_slope > input_speed:
            #     impact_by_slope = input_speed
            input_speed = self.line_track_speed - impact_by_slope
            # print(f'im_by_slope:{impact_by_slope}   input_speed:{input_speed}')
            input_turning = -(line_slope * self.slope_impact + (sampling_2_center - center_x) * self.base_impact) #+ (speed_impact * input_speed)
        elif not sam_1 and sam_2:
            input_speed = 0
            input_turning = (sampling_2_center - center_x) * self.base_impact
        elif sam_1 and not sam_2:
            input_speed = (self.line_track_speed / 3)
            input_turning = 0
        else:
            input_speed = - (self.line_track_speed / 3)
            input_turning = 0

        # input_turning = - line_slope * slope_impact
        # try:
        #     input_turning = -(sampling_2_center - center_x) * base_impact
        # except:
        #     pass
        if not self.cv_movtion_lock:
            self.base_ctrl.base_json_ctrl({"T":13,"X":input_speed,"Z":input_turning})

        overlay_buffer = np.zeros_like(img)
        overlay_buffer = cv2.cvtColor(line_mask, cv2.COLOR_GRAY2BGR)

        cv2.putText(overlay_buffer, 'Line Following', (100, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.circle(overlay_buffer, (center_x, center_y), int(self.sampling_rad/4), (64, 255, 64), 1)

        cv2.putText(overlay_buffer, ' SAM_H1: {}'.format(self.sampling_line_1), (center_x-150, sampling_h1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
        cv2.putText(overlay_buffer, ' SAM_H2: {}'.format(self.sampling_line_2), (center_x-150, sampling_h2-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)

        cv2.putText(overlay_buffer, f'X: {input_speed:.2f}, Z: {input_turning:.2f}', (center_x+50, center_y+0), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.putText(overlay_buffer, ' UPPER: {}'.format(upper_hsv), (center_x+50, center_y+40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(overlay_buffer, ' LOWER: {}'.format(lower_hsv), (center_x+50, center_y+60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.putText(overlay_buffer, ' UPPER: {}'.format(self.line_upper), (center_x+50, center_y+100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
        cv2.putText(overlay_buffer, ' LOWER: {}'.format(self.line_lower), (center_x+50, center_y+120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
        cv2.putText(overlay_buffer, f' SLOPE: {line_slope:.2f}', (center_x+50, center_y+140), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
        cv2.putText(overlay_buffer, f' SAM_1 SAM_2 SLOPE_IM BASE_IM SPD_IM LT_SPD SLOPE_SPD', (center_x-250, center_y-70), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)
        cv2.putText(overlay_buffer, f' {self.sampling_line_1:.2f}   {self.sampling_line_2:.2f}   {self.slope_impact:.2f}      {self.base_impact:.4f}  {self.speed_impact:.2f}    {self.line_track_speed:.2f}    {self.slope_on_speed:.2f}', (center_x-250, center_y-50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 128), 1)

        cv2.line(overlay_buffer, (0, sampling_h1), (width, sampling_h1), (255, 0, 0), 2)
        cv2.line(overlay_buffer, (0, sampling_h2), (width, sampling_h2), (255, 0, 0), 2)

        if sam_1:
            cv2.line(overlay_buffer, (sampling_1_left, sampling_h1+20), (sampling_1_left, sampling_h1-20), (0, 255, 0), 2)
            cv2.line(overlay_buffer, (sampling_1_right, sampling_h1+20), (sampling_1_right, sampling_h1-20), (0, 255, 0), 2)
        if sam_2:
            cv2.line(overlay_buffer, (sampling_2_left, sampling_h2+20), (sampling_2_left, sampling_h2-20), (0, 255, 0), 2)
            cv2.line(overlay_buffer, (sampling_2_right, sampling_h2+20), (sampling_2_right, sampling_h2-20), (0, 255, 0), 2)
        if sam_1 and sam_2:
            cv2.line(overlay_buffer, (sampling_1_center, sampling_h1), (sampling_2_center, sampling_h2), (255, 0, 0), 2)

        self.overlay = overlay_buffer

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