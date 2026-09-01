import sys
sys.stdout.reconfigure(line_buffering=True)
# import base_ctrl library
from controllers.base_ctrl import BaseController
from controllers.joy_ctrl import JoystickReader, JoyTeleop
from controllers import cv_ctrl, audio_ctrl, os_info

# Import necessary modules
from flask import Flask, render_template, Response, request, jsonify, redirect, url_for, send_from_directory, send_file
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

import threading
import yaml
import os
import json
import uuid
import asyncio
import time
import logging

# raspberry pi version check.
def is_raspberry_pi5():
    with open('/proc/cpuinfo', 'r') as file:
        for line in file:
            if 'Model' in line:
                if 'Raspberry Pi 5' in line:
                    return True
                else:
                    return False

if is_raspberry_pi5():
    base = BaseController('/dev/ttyAMA0', 115200)
else:
    base = BaseController('/dev/serial0', 115200)
    
threading.Thread(target=lambda: base.breath_light(15), daemon=True).start()

# config file.
curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/config.yaml', 'r') as yaml_file:
    f = yaml.safe_load(yaml_file)

base.base_oled(0, f["base_config"]["robot_name"])
base.base_oled(1, f"sbc_version: {f['base_config']['sbc_version']}")
base.base_oled(2, f"{f['base_config']['main_type']}{f['base_config']['module_type']}")
base.base_oled(3, "Starting...")

# Get system info
UPLOAD_FOLDER = thisPath + '/templates/media/sounds/others'
si = os_info.SystemInfo()

# Create a Flask app instance
app = Flask(__name__)
# log = logging.getLogger('werkzeug')
# log.disabled = True
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# Camera funcs
cvf = cv_ctrl.OpencvFuncs(thisPath, base)

cmd_actions = {
    f['code']['zoom']: lambda mode: cvf.scale_ctrl(mode),

    f['code']['pic_cap']: lambda mode: cvf.picture_capture(),
    f['code']['video']: lambda mode: cvf.video_record(mode),

    f['fb']['detect_type']: lambda mode: cvf.set_cv_mode(mode),

    f['fb']['detect_react']: lambda mode: cvf.set_detection_reaction(mode),

    f['fb']['cv_movtion_mode']: lambda mode: cvf.set_movtion_lock(mode),

    f['fb']['led_mode']: lambda mode: cvf.head_light_ctrl(mode),

    f['code']['release']: lambda mode: base.bus_servo_torque_lock(255, 0),
    f['code']['s_panid']: lambda mode: base.bus_servo_id_set(255, 2),
    f['code']['s_tilid']: lambda mode: base.bus_servo_id_set(255, 1),
    f['code']['set_mid']: lambda mode: base.bus_servo_mid_set(255),

    f['fb']['base_light']: lambda mode: base.lights_ctrl(mode, base.head_light_status),
    f['code']['base_ct']: lambda mode: base.base_lights_ctrl(),
}

cmd_feedback_actions = [f['fb']['detect_type'], f['fb']['detect_react'],
                        f['fb']['cv_movtion_mode'],f['fb']['led_mode'], 
                        f['fb']['base_light'],f['code']['base_ct']
                        ]

# cv info process
def process_cv_info(cmd):
    if cmd[f['fb']['detect_type']] != f['code']['cv_none']:
        print(cmd[f['fb']['detect_type']])
        pass

# Route to render the HTML template
@app.route('/')
def index():
    audio_ctrl.play_random_audio("connected", False)
    return render_template('index.html')

@app.route('/config')
def get_config():
    with open(thisPath + '/config.yaml', 'r') as file:
        yaml_content = file.read()
    return yaml_content

# get pictures and videos.
@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('templates', filename)

@app.route('/get_photo_names')
def get_photo_names():
    photo_files = sorted(os.listdir(thisPath + '/templates/media/pictures'), key=lambda x: os.path.getmtime(os.path.join(thisPath + '/templates/media/pictures', x)), reverse=True)
    return jsonify(photo_files)

@app.route('/delete_photo', methods=['POST'])
def delete_photo():
    filename = request.form.get('filename')
    try:
        os.remove(os.path.join(thisPath + '/templates/media/pictures', filename))
        return jsonify(success=True)
    except Exception as e:
        print(e)
        return jsonify(success=False)

@app.route('/videos/<path:filename>')
def videos(filename):
    return send_from_directory(thisPath + '/templates/media/videos', filename)

@app.route('/get_video_names')
def get_video_names():
    video_files = sorted(
        [filename for filename in os.listdir(thisPath + '/templates/media/videos/') if filename.endswith('.mp4')],
        key=lambda filename: os.path.getctime(os.path.join(thisPath + '/templates/media/videos/', filename)),
        reverse=True
    )
    return jsonify(video_files)

@app.route('/delete_video', methods=['POST'])
def delete_video():
    filename = request.form.get('filename')
    try:
        os.remove(os.path.join(thisPath + '/templates/media/videos', filename))
        return jsonify(success=True)
    except Exception as e:
        print(e)
        return jsonify(success=False)

# set product version
def set_version(input_main, input_module):
    base.base_json_ctrl({"T":900,"main":input_main,"module":input_module})
    if input_main == 1:
        cvf.info_update("RaspRover", (0,255,255), 0.36)
    elif input_main == 2:
        cvf.info_update("UGV Rover", (0,255,255), 0.36)
    elif input_main == 3:
        cvf.info_update("UGV Beast", (0,255,255), 0.36)
    if input_module == 0:
        cvf.info_update("No Module", (0,255,255), 0.36)
    elif input_module == 1:
        cvf.info_update("RoArm M2", (0,255,255), 0.36)
    elif input_module == 2:
        cvf.info_update("PT", (0,255,255), 0.36)
    elif input_module == 3:
        cvf.info_update("RoArm M3", (0,255,255), 0.36)

# main cmdline for robot ctrl
def cmdline_ctrl(args_string):
    if not args_string:
        return
    args = args_string.split()
    # base -c {"T":1,"L":0.5,"R":0.5}
    if args[0] == 'base':
        if args[1] == '-c' or args[1] == '--cmd':
            base.base_json_ctrl(json.loads(args[2]))
        elif args[1] == '-r' or args[1] == '--recv':
            if args[2] == 'on':
                cvf.show_recv_info(True)
            else:
                cvf.show_recv_info(False)

    elif args[0] == 'audio':
        if args[1] == '-s' or args[1] == '--say':
            audio_ctrl.play_speech_thread(' '.join(args[2:]))
        elif args[1] == '-v' or args[1] == '--volume':
            audio_ctrl.set_audio_volume(args[2])
        elif args[1] == '-p' or args[1] == '--play_file':
            audio_ctrl.play_file(args[2])

    elif args[0] == 'send':
        if args[1] == '-a' or args[1] == '--add':
            if args[2] == '-b' or args[2] == '--broadcast':
                base.base_json_ctrl({"T":303,"mac":"FF:FF:FF:FF:FF:FF"})
            else:
                base.base_json_ctrl({"T":303,"mac":args[2]})
        elif args[1] == '-rm' or args[1] == '--remove':
            if args[2] == '-b' or args[2] == '--broadcast':
                base.base_json_ctrl({"T":304,"mac":"FF:FF:FF:FF:FF:FF"})
            else:
                base.base_json_ctrl({"T":304,"mac":args[2]})
        elif args[1] == '-b' or args[1] == '--broadcast':
            base.base_json_ctrl({"T":306,"mac":"FF:FF:FF:FF:FF:FF","dev":0,"b":0,"s":0,"e":0,"h":0,"cmd":3,"megs":' '.join(args[2:])})
        elif args[1] == '-g' or args[1] == '--group':
            base.base_json_ctrl({"T":305,"dev":0,"b":0,"s":0,"e":0,"h":0,"cmd":3,"megs":' '.join(args[2:])})
        else:
            base.base_json_ctrl({"T":306,"mac":args[1],"dev":0,"b":0,"s":0,"e":0,"h":0,"cmd":3,"megs":' '.join(args[2:])})

    elif args[0] == 'cv':
        if args[1] == '-r' or args[1] == '--range':
            try:
                lower_trimmed = args[2].strip("[]")
                lower_nums = [int(lower_num) for lower_num in lower_trimmed.split(",")]
                if all(0 <= num <= 255 for num in lower_nums):
                    pass
                else:
                    return
            except:
                return
            try:
                upper_trimmed = args[3].strip("[]")
                upper_nums = [int(upper_num) for upper_num in upper_trimmed.split(",")]
                if all(0 <= num <= 255 for num in upper_nums):
                    pass
                else:
                    return
            except:
                return
            cvf.change_target_color(lower_nums, upper_nums)
        elif args[1] == '-s' or args[1] == '--select':
            cvf.selet_target_color(args[2])

    elif args[0] == 'line':
        if args[1] == '-r' or args[1] == '--range':
            try:
                lower_trimmed = args[2].strip("[]")
                lower_nums = [int(lower_num) for lower_num in lower_trimmed.split(",")]
                if all(0 <= num <= 255 for num in lower_nums):
                    pass
                else:
                    return
            except:
                return
            try:
                upper_trimmed = args[3].strip("[]")
                upper_nums = [int(upper_num) for upper_num in upper_trimmed.split(",")]
                if all(0 <= num <= 255 for num in upper_nums):
                    pass
                else:
                    return
            except:
                return
            cvf.change_line_color(lower_nums, upper_nums)

    elif args[0] == 'track':
        if args[1] == '-b' or args[1] == '--base':
            cvf.set_track_base(args[2])
            f['base_config']['robot_name'] = args[2]
            with open(thisPath + '/config.yaml', "w") as yaml_file:
                yaml.dump(f, yaml_file)

    elif args[0] == 'timelapse':
        if args[1] == '-s' or args[1] == '--start':
            if len(args) != 6:
                return
            try:
                move_speed = float(args[2])
                move_time  = float(args[3])
                t_interval = float(args[4])
                loop_times = int(args[5])
            except:
                return
            cvf.timelapse(move_speed, move_time, t_interval, loop_times)
        elif args[1] == '-e' or args[1] == '--end' or args[1] == '--stop':
            cvf.mission_stop()

    # s 20
    elif args[0] == 's':
        main_type = int(args[1][0])
        module_type = int(args[1][1])
        if main_type == 1:
            f['base_config']['robot_name'] = "RaspRover"
            f['args_config']['max_speed'] = 0.65
            f['args_config']['slow_speed'] = 0.3
        elif main_type == 2:
            f['base_config']['robot_name'] = "UGV Rover"
            f['args_config']['max_speed'] = 1.3
            f['args_config']['slow_speed'] = 0.2
        elif main_type == 3:
            f['base_config']['robot_name'] = "UGV Beast"
            f['args_config']['max_speed'] = 1.0
            f['args_config']['slow_speed'] = 0.2
        f['base_config']['main_type'] = main_type
        f['base_config']['module_type'] = module_type
        with open(thisPath + '/config.yaml', "w") as yaml_file:
            yaml.dump(f, yaml_file)
        set_version(main_type, module_type)

    elif args[0] == 'test':
        cvf.update_base_data({"T":1003,"mac":1111,"megs":"helllo aaaaaaaa"})

@app.route('/send_command', methods=['POST'])
def handle_command():
    command = request.form['command']
    print("Received command:", command)
    cvf.info_update("CMD: " + command, (0,255,255), 0.36)
    try:
        cmdline_ctrl(command)
    except Exception as e:
        print(f"[app.handle_command] error: {e}")
    return jsonify({"status": "success", "message": "Command received"})

@app.route('/get_audio_files', methods=['GET'])
def get_audio_files():
    files = [f for f in os.listdir(UPLOAD_FOLDER) if os.path.isfile(os.path.join(UPLOAD_FOLDER, f)) and (f.endswith('.mp3') or f.endswith('.wav'))]
    return jsonify(files)

@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'})
    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(UPLOAD_FOLDER, filename))
        return jsonify({'success': 'File uploaded successfully'})

@app.route('/play_audio', methods=['POST'])
def play_audio():
    audio_file = request.form['audio_file']
    print(thisPath + '/templates/media/sounds/others/' + audio_file)
    audio_ctrl.play_audio_thread(thisPath + '/templates/media/sounds/others/' + audio_file)
    return jsonify({'success': 'Audio is playing'})

@app.route('/stop_audio', methods=['POST'])
def audio_stop():
    audio_ctrl.stop()
    return jsonify({'success': 'Audio stop'})

@app.route('/delete_audio', methods=['POST'])
def delete_audio():
    filename = request.form.get('filename')
    try:
        os.remove(os.path.join(thisPath + '/templates/media/sounds/others/', filename))
        return jsonify(success=True)
    except Exception as e:
        print(e)
        return jsonify(success=False)

@app.route('/settings/<path:filename>')
def serve_static_settings(filename):
    return send_from_directory('templates', filename)

def audio_send_thread():
    while True:
        try:
            data = audio_ctrl.audio_queue.get()
            socketio.emit('audio', data, namespace='/audio')
            audio_ctrl.audio_queue.task_done()
        except Exception as e:
            print("[Audio Send Error]", e)

@socketio.on('connect', namespace='/audio')
def on_audio_connect():
    print('Client connected to /audio')
    audio_ctrl.start_audio_capture()

# Web socket
@socketio.on('json', namespace='/json')
def handle_socket_json(json):
    try:
        base.base_json_ctrl(json)
    except Exception as e:
        print("Error handling JSON data:", e)
        return

# info update single
def update_data_websocket_single():
    # {'T':1001,'L':0,'R':0,'r':0,'p':0,'v': 11,'pan':0,'tilt':0}
    try:
        socket_data = {
            f['fb']['picture_size']:si.pictures_size,
            f['fb']['video_size']:  si.videos_size,
            f['fb']['cpu_load']:    si.cpu_load,
            f['fb']['cpu_temp']:    si.cpu_temp,
            f['fb']['ram_usage']:   si.ram,
            f['fb']['wifi_rssi']:   si.wifi_rssi,

            f['fb']['led_mode']:    cvf.cv_light_mode,
            f['fb']['detect_type']: cvf.cv_mode,
            f['fb']['detect_react']:cvf.detection_reaction_mode,
            f['fb']['pan_angle']:   cvf.pan_angle,
            f['fb']['tilt_angle']:  cvf.tilt_angle,
            f['fb']['base_voltage']: base.base_voltage_status,
            f['fb']['video_fps']:   cvf.video_fps,
            f['fb']['cv_movtion_mode']: cvf.cv_movtion_lock,
            f['fb']['pt_steady']:  base.pt_steady_status,
            f['fb']['base_light']:  base.base_light_status
        }
        socketio.emit('update', socket_data, namespace='/ctrl')
    except Exception as e:
        print("An [app.update_data_websocket_single] error occurred:", e)

# info feedback
def update_data_loop():
    base.base_oled(2, "F/J:5000/8888")
    
    last_eth0 = None
    last_wlan = None
    start_time = time.time()

    while True:
        update_data_websocket_single()

        eth0 = si.eth0_ip
        wlan = si.wlan_ip

        if eth0 != last_eth0:
            if eth0:
                base.base_oled(0, f"E:{eth0}")
            else:
                base.base_oled(0, "E: No Ethernet")
            last_eth0 = eth0

        if wlan != last_wlan:
            if wlan:
                base.base_oled(1, f"W:{wlan}")
            else:
                base.base_oled(1, f"W: NO {si.net_interface}")
            last_wlan = wlan

        elapsed_time = time.time() - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        base.base_oled(3, f"{si.wifi_mode} {hours:02d}:{minutes:02d}:{seconds:02d} {si.wifi_rssi}dBm")

        time.sleep(1)  

def base_data_loop():
    sensor_interval = 1
    sensor_read_time = time.time()
    while True:
        cvf.update_base_data(base.feedback_data())
        if f['base_config']['module_type'] != 2:
            base.base_json_ctrl({"T":105})   
            data = base.feedback_data()
            if data !=None and data["T"] ==1051:
                socketio.emit('arm_state_update', data, namespace='/arm_state_update')
        # get sensor data
        if base.extra_sensor:
            if time.time() - sensor_read_time > sensor_interval:
                base.rl.read_sensor_data()
                sensor_read_time = time.time()
        
        # get lidar data
        if base.use_lidar:
            base.rl.lidar_data_recv()
        
        time.sleep(0.025)

@socketio.on('connect', namespace='/arm_state_update')
def connect_arm():
    print("Client connected to /arm_state_update")

@socketio.on('message', namespace='/ctrl')
def handle_socket_cmd(message):
    try:
        json_data = json.loads(message)
        print("Received JSON data:", json_data)
    except json.JSONDecodeError:
        print("Error decoding JSON.[app.handle_socket_cmd]")
        return
    cmd = float(json_data.get("cmd", 0))
    mode = float(json_data.get("mode", 0))
    if cmd in cmd_actions:
        cmd_actions[cmd](mode)
    else:
        pass
    if cmd in cmd_feedback_actions:
        threading.Thread(target=update_data_websocket_single, daemon=True).start()

class JoyCtrlThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.js_reader = JoystickReader()
        self.js_reader.start()
        
        self.joy_ctrl = JoyTeleop(self.js_reader, base.ser.port)
        self.running = True

    def run(self):
        while self.running:
            if self.js_reader.Joy_active:
                self.joy_ctrl.handle_events()
            time.sleep(0.05)

    def stop(self):
        self.running = False
        pygame.quit()

# commandline on boot
def cmd_on_boot():
    cmd_list = [
        'base -c {"T":142,"cmd":50}',   # set feedback interval
        'base -c {"T":131,"cmd":1}',    # serial feedback flow on
        'base -c {"T":143,"cmd":0}',    # serial echo off
        'base -c {"T":4,"cmd":0}',      # select the module - 0:None 1:RoArm-M2-S 2:Gimbal
        'base -c {"T":300,"mode":0,"mac":"EF:EF:EF:EF:EF:EF"}',  # the base won't be ctrl by esp-now broadcast cmd, but it can still recv broadcast megs.
        'send -a -b'    # add broadcast mac addr to peer
    ]
    for i in range(0, len(cmd_list)):
        cmdline_ctrl(cmd_list[i])
        cvf.info_update(cmd_list[i], (0,255,255), 0.36)
    set_version(f['base_config']['main_type'], f['base_config']['module_type'])

def run_flask():
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

# Run the Flask app
if __name__ == "__main__":
    # lights on
    base.lights_ctrl(255, 255)

    # play a audio file in /templates/media/sounds/robot_started/
    audio_ctrl.play_random_audio("robot_started", False)

    # update the size of videos and pictures
    si.update_folder(thisPath)

    # feedback loop starts
    si.start()
    si.resume()
    data_update_thread = threading.Thread(target=update_data_loop, daemon=True)
    data_update_thread.start()

    # base data update
    base_update_thread = threading.Thread(target=base_data_loop, daemon=True)
    base_update_thread.start()

    # cam update
    cam_thread = threading.Thread(target=cvf.frame_process, daemon=True)
    cam_thread.start()

    # lights off
    base.lights_ctrl(0, 0)
    cmd_on_boot()

    # joy_ctrl 
    joy_thread = JoyCtrlThread()
    joy_thread.start()

    # pt/arm looks forward
    if f['base_config']['module_type'] == 1:
        base.base_json_ctrl({"T":102,"base": 0,"shoulder": 0,"elbow": 2.618,"hand": 3.1415,"spd": 0,"acc": 30})
    elif f['base_config']['module_type'] == 3:
        base.base_json_ctrl({"T":102,"base": 0,"shoulder": 0,"elbow": 2.618,"wrist": 0,"roll": 0,"hand": 3.1415,"spd": 0,"acc": 30})
    elif f['base_config']['module_type'] == 2:
        base.gimbal_ctrl(0, 0, 200, 10)

    # run the main web app
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    audio_send_thread = threading.Thread(target=audio_send_thread, daemon=True)
    audio_send_thread.start()