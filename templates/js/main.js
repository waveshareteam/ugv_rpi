import { roarm_m2, roarm_m3 } from './roarm_solver.js';
import { MediaMTXWebRTCReader } from '../libs/webrtc_reader.js';
import { 
    socketAudio, 
    socketJson, 
    socketCtrl,
    fetchConfig,
    fetchUploadAudio,
    fetchGetAudioFiles,
    fetchPlayAudio,
    fetchStopAudio,
    fetchDeleteAudio,
    fetchSendCommand,
} from './api.js';
import { updatePhotoNames, updateVideoList } from './gallery.js';
import config from './config.js';
let roarm_type =null;
let gripper_type =null;
const view = document.getElementById("roarmView");
//config
function onConfigLoaded() {
  if (config.robot_name) {
    document.title = config.robot_name + " WEB CTRL";
  }
  const busServoSetup = document.getElementById("bus_servo_setup");
  if (busServoSetup) {
    if (config.module_type === 2) {
      busServoSetup.classList.remove("hidden");
    } else {
      busServoSetup.classList.add("hidden");
    }
  }
  if (config.module_type !== undefined && view) {
    view.classList.remove("hidden");
    if (config.module_type===1){
        if (config.gripper_type===0){
            roarm_type='roarm_m2'
        }else{
            roarm_type='roarm_m2_ga'
        }
    }else if (config.module_type===3){
        roarm_type='roarm_m3'
    }else if (config.module_type===0 || config.module_type===2){
        view.classList.add("hidden");
    }
    const roarmFrame = document.getElementById("roarmViewerFrame");
    if (roarmFrame && roarm_type) {
        roarmFrame.src = `http://${window.location.hostname}:3000/play/${roarm_type}/`;
    }
  }
  bindNoLongPressMenu();
  startRobotControl();
  const armBtns = document.getElementById("armControlButtons");
  if (armBtns) {
    if (config.module_type === 1 || config.module_type === 3) {
      armBtns.classList.remove("hidden");
    } else {
      armBtns.classList.add("hidden");
    }
  }
  setLeftStickVisible(config.module_type === 1 || config.module_type === 3);
}

function setLeftStickVisible(visible) {
    const leftBase = document.getElementById('ctrl_base_left');
    const leftBox = leftBase && leftBase.closest('.ctrl_base_box');
    if (leftBox) {
        leftBox.classList.toggle('hidden', !visible);
    }
}

fetch(fetchConfig)
  .then(response => response.text())
  .then(yamlText => {
    try {
        const yamlObject = jsyaml.load(yamlText);
        console.log(yamlObject);
        config.cmd_ros_movition_ctrl = yamlObject.cmd_config.cmd_ros_movition_ctrl;
        config.cmd_gimbal_steady = yamlObject.cmd_config.cmd_gimbal_steady;
        config.cmd_gimbal_ctrl = yamlObject.cmd_config.cmd_gimbal_ctrl;
        config.cmd_arm_ctrl = yamlObject.cmd_config.cmd_arm_ctrl;
        config.cmd_set_led_pwm = yamlObject.cmd_config.cmd_set_led_pwm;

        config.max_speed = yamlObject.args_config.max_speed;
        config.max_turn_speed = yamlObject.args_config.max_turn_speed;
        config.robot_name = yamlObject.base_config.robot_name;

        config.max_rate = yamlObject.args_config.max_rate;
        config.mid_rate = yamlObject.args_config.mid_rate;
        config.min_rate = yamlObject.args_config.min_rate;

        config.module_type = yamlObject.base_config.module_type;
        config.gripper_type = yamlObject.base_config.gripper_type;

        config.zoom = yamlObject.code.zoom;

        config.pic_cap = yamlObject.code.pic_cap;
        config.video = yamlObject.code.video;

        config.mc_lock = yamlObject.code.mc_lock;
        config.mc_unlo = yamlObject.code.mc_unlo;

        config.cv_none = yamlObject.code.cv_none;
        config.cv_moti = yamlObject.code.cv_moti;
        config.cv_face = yamlObject.code.cv_face;
        config.cv_objs = yamlObject.code.cv_objs;
        config.cv_color = yamlObject.code.cv_color;
        config.mp_hand = yamlObject.code.mp_hand;
        config.cv_auto = yamlObject.code.cv_auto;
        config.mp_face = yamlObject.code.mp_face;
        config.mp_pose = yamlObject.code.mp_pose;

        config.re_none = yamlObject.code.re_none;
        config.re_capt = yamlObject.code.re_capt;
        config.re_reco = yamlObject.code.re_reco;
        config.head_ct = yamlObject.code.head_ct;
        config.base_ct = yamlObject.code.base_ct;
        config.led_off = yamlObject.code.led_off;
        config.led_aut = yamlObject.code.led_aut;
        config.led_ton = yamlObject.code.led_ton;

        config.s_panid = yamlObject.code.s_panid;
        config.release = yamlObject.code.release;
        config.set_mid = yamlObject.code.set_mid;
        config.s_tilid = yamlObject.code.s_tilid;

        config.detect_type = yamlObject.fb.detect_type;
        config.led_mode = yamlObject.fb.led_mode;
        config.detect_react = yamlObject.fb.detect_react;
        config.picture_size = yamlObject.fb.picture_size;
        config.video_size = yamlObject.fb.video_size;
        config.cpu_load = yamlObject.fb.cpu_load;
        config.cpu_temp = yamlObject.fb.cpu_temp;
        config.ram_usage = yamlObject.fb.ram_usage;
        config.wifi_rssi = yamlObject.fb.wifi_rssi;
        config.base_voltage = yamlObject.fb.base_voltage;
        config.video_fps = yamlObject.fb.video_fps;
        config.cv_movtion_mode = yamlObject.fb.cv_movtion_mode;
        config.base_light = yamlObject.fb.base_light;
        config.pt_steady = yamlObject.fb.pt_steady;

        onConfigLoaded(); 
    } catch (e) {
        console.error('Error parsing YAML file:', e);
    }
})
.catch(error => {
    console.error('Error fetching YAML file:', error);
});

function bindNoLongPressMenu() {
    const preventMenu = (event) => {
        event.preventDefault();
    };
    document.querySelectorAll('.ctrl_base_box, .ctl9, .tilt, .slider_track').forEach((el) => {
        el.addEventListener('contextmenu', preventMenu);
    });
    document.querySelectorAll('.ctrl_base_box, .ctl9, .ctl9_base ul li').forEach((el) => {
        el.addEventListener('touchstart', preventMenu, { passive: false });
    });
    document.querySelectorAll('.tilt').forEach((el) => {
        el.addEventListener('touchmove', preventMenu, { passive: false });
    });
}

function startRobotControl() {

window.re_none = config.re_none;
window.re_capt = config.re_capt;
window.re_reco = config.re_reco;

window.detect_type = config.detect_type;
window.detect_react = config.detect_react;

window.cv_movtion_mode = config.cv_movtion_mode;
window.cv_none = config.cv_none;
window.cv_moti = config.cv_moti;
window.cv_face = config.cv_face;
window.cv_objs = config.cv_objs;
window.cv_color = config.cv_color;
window.cv_auto = config.cv_auto;

window.mp_hand = config.mp_hand;
window.mp_face = config.mp_face;
window.mp_pose = config.mp_pose;

window.led_mode = config.led_mode;
window.led_aut = config.led_aut;
window.led_ton = config.led_ton;
window.led_off = config.led_off;
window.base_light = config.base_light;

window.mc_lock = config.mc_lock;
window.mc_unlo = config.mc_unlo;

window.min_rate = config.min_rate;
window.mid_rate = config.mid_rate;
window.max_rate = config.max_rate;
window.head_ct = config.head_ct;

window.speedRateCtrl = speedRateCtrl;
window.captureAndUpdate = captureAndUpdate;
window.confirmSetPanID = confirmSetPanID;
window.confirmRelease = confirmRelease;
window.confirmMiddleSet = confirmMiddleSet;
window.confirmSetTiltID = confirmSetTiltID;
window.cmdSend = cmdSend;
window.toggleArmMode = toggleArmMode;
window.togglePressMode = togglePressMode;
window.lookAhead = lookAhead;
window.steadyCtrl = steadyCtrl;

//audio
let audioContext = null;
let audioStarted = false;
const queue = [];
let isPlaying = false;
const MAX_QUEUE_SIZE = 5;  

function initAudioContext() {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === 'suspended') {
        return audioContext.resume();
    }
    return Promise.resolve();
}

function convertPCMToFloat32(pcmBuffer) {
    const int16 = new Int16Array(pcmBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768;
    }
    return float32;
}

function playNext() {
    if (isPlaying) return; 
    if (!audioStarted || !audioContext || audioContext.state !== 'running') {
        setTimeout(playNext, 200);
        return;
    }
    if (queue.length === 0) {
        requestAnimationFrame(playNext);
        return;
    }

    isPlaying = true;

    const buffer = queue.shift();
    if (!buffer || buffer.byteLength === 0) {
        isPlaying = false;
        playNext();
        return;
    }

    try {
        const float32Samples = convertPCMToFloat32(buffer);
        const audioBuffer = audioContext.createBuffer(1, float32Samples.length, 16000);
        audioBuffer.getChannelData(0).set(float32Samples);

        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);
        source.start();

        source.onended = () => {
            isPlaying = false;
            playNext();
        };
    } catch (err) {
        console.error('Audio playback error:', err);
        isPlaying = false;
        playNext();
    }
}

const audioBtn = document.getElementById('audio-btn');
const audioIcon = document.getElementById('audio-icon');

function toggleAudio() {
    if (!audioContext) {
        initAudioContext().then(() => {
            audioStarted = true;
            audioIcon.src = '../assets/img/white/volume-up.svg';
            audioIcon.alt = 'volume-up';
            playNext();
        });
        return;
    }
    if (audioContext.state === 'suspended') {
        audioContext.resume().then(() => {
            audioStarted = true;
            audioIcon.src = '../assets/img/white/volume-up.svg';
            audioIcon.alt = 'volume-up';
            if (queue.length > 0) playNext();
        });
    } else if (audioContext.state === 'running') {
        audioContext.suspend().then(() => {
            audioStarted = false;
            audioIcon.src = '../assets/img/white/volume-mute.svg';
            audioIcon.alt = 'volume-mute';
        });
    }
}

if(audioBtn){
    audioBtn.addEventListener('click', toggleAudio);
}

socketAudio.on('audio', (chunk) => {
    if (!(chunk instanceof ArrayBuffer)) {
        console.warn('Received non-ArrayBuffer audio chunk');
        return;
    }

    if (queue.length >= MAX_QUEUE_SIZE) {
        queue.shift();
    }
    queue.push(chunk);
    if (queue.length === 1 && audioStarted && audioContext?.state === 'running') {
        playNext();
    }
});

// audio drag & play
updateAudioFileList();

var audioFilesElement = document.getElementById('audioFiles');

if(audioFilesElement){
    audioFilesElement.addEventListener('dragover', function (event) {
        event.preventDefault(); 
    });

    audioFilesElement.addEventListener('drop', function (event) {
        event.preventDefault(); 
        var files = event.dataTransfer.files;
        uploadFiles(files);
    });
}

var pauseBtn = document.getElementById('stopButton');

function updateAudioFileList() {
    fetch(fetchGetAudioFiles)
        .then(response => response.json())
        .then(files => {
            if (audioFilesElement) {
                audioFilesElement.innerHTML = '';
                if (files.length === 0) {
                    var dropDiv = document.createElement('div');
                    dropDiv.id = 'audioFilesDrag';
                    dropDiv.className = 'audio-drop';
                    dropDiv.textContent = 'Drop audio files here!';
                    audioFilesElement.appendChild(dropDiv);
                } else {
                    var ol = document.createElement('ol');
                    var counter = 1;
                    files.forEach(file => {
                        var listItem = document.createElement('li');

                        var spanPlay = document.createElement('span');
                        spanPlay.className = 'audioplay';

                        var spanFile = document.createElement('span');
                        spanFile.setAttribute('data-file-path', file);
                        spanFile.textContent = file;

                        var btnDelete = document.createElement('button');
                        btnDelete.className = 'delete-audio-btn'; 
                        btnDelete.title = 'delete audio file';

                        var delIcon = document.createElement('img');
                        delIcon.src = './assets/img/white/delete.svg';
                        delIcon.width = 16;
                        delIcon.height = 16;
                        delIcon.alt = 'delete';
                        btnDelete.appendChild(delIcon);

                        btnDelete.addEventListener('click', function(e) {
                            e.stopPropagation();  
                            var filePath = this.parentElement.querySelector('span[data-file-path]').getAttribute('data-file-path');
                            fetch(fetchDeleteAudio, {
                                method: 'POST',
                                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                                body: 'filename=' + encodeURIComponent(filePath)
                            })
                            .then(response => response.json())
                            .then(data => {
                                if (data.success) {
                                    updateAudioFileList();
                                } else {
                                    alert('delete failure');
                                }
                            })
                            .catch(err => console.error('delete error:', err));
                        });
                        listItem.appendChild(btnDelete);

                        listItem.textContent = counter + ' ';
                        counter++;

                        listItem.appendChild(spanPlay);
                        listItem.appendChild(spanFile);
                        listItem.appendChild(btnDelete);

                        listItem.addEventListener('click', function () {
                            var filePath = this.querySelector('span[data-file-path]').getAttribute('data-file-path');
                            fetch(fetchPlayAudio, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                                body: 'audio_file=' + encodeURIComponent(filePath)
                            });
                        });

                        ol.appendChild(listItem);
                    });
                    audioFilesElement.appendChild(ol);
                }
            }
        })
        .catch(error => console.error('Error:', error));
}

function uploadFiles(files) {
    for (var i = 0; i < files.length; i++) {
        var file = files[i];
        var formData = new FormData();
        formData.append('file', file);

        fetch(fetchUploadAudio, {
            method: 'POST',
            body: formData
        })
            .then(response => response.json())
            .then(data => {
                console.log('Success:', data);
                updateAudioFileList();
            })
            .catch((error) => {
                console.error('Error:', error);
            });
    }
}

if(pauseBtn){
    pauseBtn.addEventListener('click', function () {
        fetch(fetchStopAudio, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'command=' + 0
        })
            .then(response => response.json())
            .then(data => {
                console.log(data);
            })
            .catch(error => {
                console.error('Error:', error);
            });
    });
}

//video
const videoElement = document.getElementById('video');
const message = document.getElementById('message');
const wrapper = document.getElementById('video-wrapper');
const miniPlayer = document.getElementById('mini-player');

let placeholder = null;
let isMini = false;

function enterMiniPlayer() {
  if (isMini) return;
  isMini = true;

  miniPlayer.appendChild(videoElement);
  miniPlayer.style.display = 'block';

  videoElement.style.width = '100%';
  videoElement.style.height = '100%';
}

function exitMiniPlayer() {
  if (!isMini) return;
  isMini = false;

  wrapper.appendChild(videoElement);
  miniPlayer.style.display = 'none';

  if (placeholder) {
    placeholder.remove();
    placeholder = null;
  }

  videoElement.style.width = '100%';
  videoElement.style.height = '100%';
}

const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (!entry.isIntersecting) {
      enterMiniPlayer();
    } else {
      exitMiniPlayer();
    }
  });
}, { threshold: 0.05 });

if (wrapper) {
  observer.observe(wrapper);
}

const playPauseBtn = document.getElementById('playPause-btn');
const playPauseIcon = document.getElementById('playPause-icon');

const pipBtn = document.getElementById('pip-btn');
const pipIcon = document.getElementById('pip-icon');

const fullscreenBtn = document.getElementById('fullscreen-btn');

if(fullscreenBtn){
    fullscreenBtn.addEventListener('click', () => {
    if (!document.fullscreenElement) {
        if (videoElement.requestFullscreen) {
        videoElement.requestFullscreen();
        } else if (videoElement.webkitRequestFullscreen) { /* Safari */
        videoElement.webkitRequestFullscreen();
        } else if (videoElement.msRequestFullscreen) { /* IE11 */
        videoElement.msRequestFullscreen();
        }     
    } else {
        if (document.exitFullscreen) {
        document.exitFullscreen();
        } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
        } else if (document.msExitFullscreen) {
        document.msExitFullscreen();
        }   
    }
    });
}

let defaultControls = false;

if(playPauseBtn){
    playPauseBtn.addEventListener('click', () => {
    if (videoElement.paused) {
        videoElement.play();
        playPauseIcon.src = '../assets/img/white/pause_1.svg';
        playPauseIcon.alt = 'Pause';
        message.innerText = '';
    } else {
        videoElement.pause();
        playPauseIcon.src = '../assets/img/white/play-fill.svg';
        playPauseIcon.alt = 'Play';
        message.innerText = 'Stop Video Stream Update';
    }
    });
}

if(pipBtn){
    pipBtn.addEventListener('click', async () => {
    try {
        if (videoElement !== document.pictureInPictureElement) {
        await videoElement.requestPictureInPicture();
        pipIcon.src = '../assets/img/white/pip-fill.svg';
        pipIcon.alt = 'pip-fill';      
        } else {
        await document.exitPictureInPicture();
        pipIcon.src = '../assets/img/white/pip.svg';
        pipIcon.alt = 'pip';
        }

    } catch (err) {
        console.error('err:', err);
    }
    });
}

const setMessage = (str) => {
  if (str !== '') {
    videoElement.controls = false;
  } else {
    videoElement.controls = defaultControls;
  }
  message.innerText = str;
};

const parseBoolString = (str, defaultVal) => {
  str = (str || '');

  if (['1', 'yes', 'true'].includes(str.toLowerCase())) {
    return true;
  }
  if (['0', 'no', 'false'].includes(str.toLowerCase())) {
    return false;
  }
  return defaultVal;
};

const loadAttributesFromQuery = () => {
  const params = new URLSearchParams(window.location.search);
  videoElement.controls = parseBoolString(params.get('controls'), false);
  videoElement.muted = parseBoolString(params.get('muted'), true);
  videoElement.autoplay = parseBoolString(params.get('autoplay'), true);
  videoElement.playsInline = parseBoolString(params.get('playsinline'), true);
  defaultControls = videoElement.controls;
};

let stream_url = `http://${window.location.hostname}:8889/cam/`;

function tryPlayVideo() {
  if (!videoElement || !videoElement.srcObject) {
    return;
  }
  videoElement.muted = true;
  videoElement.playsInline = true;
  const playPromise = videoElement.play();
  if (playPromise && typeof playPromise.catch === 'function') {
    playPromise.catch(() => {
      const resume = () => {
        videoElement.play().catch(() => {});
        document.removeEventListener('touchend', resume);
        document.removeEventListener('click', resume);
      };
      document.addEventListener('touchend', resume, { once: true });
      document.addEventListener('click', resume, { once: true });
    });
  }
}

function startWebrtc() {
  if (!videoElement) {
    return;
  }
  loadAttributesFromQuery();
  videoElement.playsInline = true;
  videoElement.setAttribute('playsinline', '');
  videoElement.setAttribute('webkit-playsinline', '');
  new MediaMTXWebRTCReader({
    url: new URL('whep', stream_url) + window.location.search,
    onError: (err) => {
      setMessage(err);
    },
    onTrack: (evt) => {
      setMessage('');
      videoElement.srcObject = evt.streams[0];
      tryPlayVideo();
    },
  });
}

if (document.readyState === 'complete') {
  startWebrtc();
} else {
  window.addEventListener('load', startWebrtc);
}

function captureAndUpdate() {
    cmdSend(config.pic_cap, 0);
    setTimeout(updatePhotoNames, 100);
}

//video pixel
var listItems = $("#video_pixel_btn_list").children("li");

if(listItems){
    listItems.on("click", function () {
        var innertext = $(this).text();
        $("#video_pixel_btn").text(innertext);
        $("#video_pixel_btn_list").css("display", "none");
        setTimeout(function () {
            $("#video_pixel_btn_list").removeAttr("style");
        }, 10);
    });
}

//record function
var isRecording = false;
var originalText = "Record";
var timerInterval;
var seconds = 0;
var minutes = 0;

function updateTimer() {
    seconds++;
    if (seconds === 60) {
        seconds = 0;
        minutes++;
    }
    var formattedTime = (minutes < 10 ? "0" : "") + minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
    $("#record-btn").text(formattedTime);
}

$(document).ready(function () {
    $("#record-btn").click(function () {
        if (!isRecording) {
            cmdSend(config.video, 1);
            $(this).css("color", "#FF8C8C");
            $(this).removeClass("video_btn_record");
            $(this).addClass("video_btn_stop");
            isRecording = true;
            $(this).text("00:00");
            timerInterval = setInterval(updateTimer, 1000);
        } else {
            cmdSend(config.video, 0);
            $(this).removeClass("video_btn_stop");
            $(this).addClass("video_btn_record");
            $(this).text(originalText);
            isRecording = false;
            clearInterval(timerInterval);
            seconds = 0;
            minutes = 0;
            $(this).css("color", "");
            updateVideoList();
        }
    });
});

//zoom
var zoomx = 1;

$("#zoom_btn").click(function () {
    var zoomNum = document.getElementById("zoom-num");
    switch (zoomx) {
        case 0: cmdSend(config.zoom, 1);
            zoomNum.innerHTML = "1x"
            break;
        case 1: cmdSend(config.zoom, 2);
            zoomNum.innerHTML = "2x"
            break;
        case 2: cmdSend(config.zoom, 4);
            zoomNum.innerHTML = "4x"
            break;
    }
    zoomx = (zoomx + 1) % 3;
});

//send button
const sendBtn = document.getElementById('sendButton');
const commandInput = document.getElementById('commandInput');

let isInputFocused = false;

if (sendBtn && commandInput) {
  sendBtn.addEventListener('click', () => {
    const command = commandInput.value;
    fetch(fetchSendCommand, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: 'command=' + encodeURIComponent(command)
    })
    .then(response => response.json())
    .then(data => {
      console.log('Command sent:', data);
    })
    .catch(error => {
      console.error('Error sending command:', error);
    });
  });

  commandInput.addEventListener('focus', () => {
    isInputFocused = true;
  });

  commandInput.addEventListener('blur', () => {
    isInputFocused = false;
  });
}

//jupyter
const jupyterBtn = document.getElementById('open_jupyter');
let jupyter_link = null;
if(jupyterBtn){
    jupyter_link = jupyterBtn.querySelector('a');
}

if (jupyter_link) {
  const { protocol, hostname } = window.location;
  jupyter_link.href = `${protocol}//${hostname}:8888`;
}

//accesspopup
const accesspopupBtn = document.getElementById('open_accesspopup');
let accesspopup_link = null;
if(accesspopupBtn){
    accesspopup_link = accesspopupBtn.querySelector('a');
}

if (accesspopup_link) {
  const { protocol, hostname } = window.location;
  accesspopup_link.href = `${protocol}//${hostname}:8052`;
}

//remove buttons class
function removeButtonsClass(buttons) {
    for (var i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove("ctl_btn_active");
    }
}

//remove all ico class
function removeAllIcoClass(ElName) {
    while (ElName.classList.length > 0) {
        ElName.classList.remove(ElName.classList.item(0));
    }
}

//socket
socketJson.emit('json', { 'T': 1, 'L': 0, 'R': 0 })

socketCtrl.emit('request_data');

var cv_heartbeat_stop_flag = false;
let armModeInitialized = false;

socketCtrl.on('update', function (data) {
    if (data[config.detect_type] == 0) return;

    try {
        const dtIco = document.getElementById("DT");
        const dTypeBtn = document.getElementById("d_type_btn");
        if (dtIco && dTypeBtn) {
            const DTbuttons = dTypeBtn.getElementsByTagName("button");
            removeAllIcoClass(dtIco);
            removeButtonsClass(DTbuttons);
        }

        const drIco = document.getElementById("DR");
        const DReactionBtn = document.getElementById("d_reaction_btn");
        if (drIco && DReactionBtn) {
            const DRbuttons = DReactionBtn.getElementsByTagName("button");
            removeButtonsClass(DRbuttons);
            if (data[config.detect_react] == config.re_none) {
                removeAllIcoClass(drIco);
                drIco.classList.add("feed_ico", "feed_ico_none");
                DRbuttons[0]?.classList.add("ctl_btn_active");
            } else if (data[config.detect_react] == config.re_capt) {
                removeAllIcoClass(drIco);
                drIco.classList.add("feed_ico", "feed_ico_capture");
                DRbuttons[1]?.classList.add("ctl_btn_active");
            } else if (data[config.detect_react] == config.re_reco) {
                removeAllIcoClass(drIco);
                drIco.classList.add("feed_ico", "feed_ico_record");
                DRbuttons[2]?.classList.add("ctl_btn_active");
            }
        }

        const cpu = document.getElementById("CPU");
        if (cpu) cpu.innerHTML = data[config.cpu_load] + "%";

        const ram = document.getElementById("RAM");
        if (ram) ram.innerHTML = data[config.ram_usage] + "%";

        const vin = document.getElementById("v_in");
        if (vin) vin.innerHTML = (data[config.base_voltage] / 100).toFixed(1);

        const element = document.getElementById("b_state");
        if (element) {
            element.classList.remove("baterry_state", "baterry_state1", "baterry_state2", "baterry_state3");
            const v = data[config.base_voltage] / 100;
            if (v >= 10.5) element.classList.add("baterry_state");
            else if (v >= 10) element.classList.add("baterry_state", "baterry_state3");
            else if (v >= 9.5) element.classList.add("baterry_state", "baterry_state2");
            else element.classList.add("baterry_state", "baterry_state1");
        }

        var steadyCtrlBtn = document.getElementById("steady_ctrl_btn");
        if (steadyCtrlBtn) {
            var steadybuttons = steadyCtrlBtn.getElementsByTagName("button");
            removeButtonsClass(steadybuttons);
            if (data[config.pt_steady] == 0) steadybuttons[0]?.classList.add("ctl_btn_active");
            else steadybuttons[1]?.classList.add("ctl_btn_active");
        }

        const lightMode = document.getElementById("MODE");
        const lightCtrlBtn = document.getElementById("light_ctrl_btn");
        if (lightMode && lightCtrlBtn) {
            const lbuttons = lightCtrlBtn.getElementsByTagName("button");
            removeButtonsClass(lbuttons);
            const ledModes = {
                0: { text: "OFF", index: 0 },
                1: { text: "AUTO", index: 1 },
                2: { text: "ON", index: 2 }
            };
            const mode = data[config.led_mode];
            if (ledModes.hasOwnProperty(mode)) {
                lightMode.innerHTML = ledModes[mode].text;
                lbuttons[ledModes[mode].index]?.classList.add("ctl_btn_active");
            }
        }

        const rssi = document.getElementById("rssi");
        if (rssi) rssi.innerHTML = data[config.wifi_rssi] + " dBm";

        const fps = document.getElementById("fps");
        if (fps) fps.innerHTML = data[config.video_fps].toFixed(1);

        const tem = document.getElementById("tem");
        if (tem) tem.innerHTML = data[config.cpu_temp].toFixed(1) + " ℃";

        const photoSize = document.getElementById("photos-size");
        if (photoSize) photoSize.innerHTML = data[config.picture_size] + " MB";

        const videoSize = document.getElementById("videos-size");
        if (videoSize) videoSize.innerHTML = data[config.video_size] + " MB";

        const baseBtn = document.getElementById("base_led_ctrl_btn");
        if (baseBtn) {
            const BButtons = baseBtn.getElementsByTagName("button");
            removeButtonsClass(BButtons);
            if (data[config.base_light] == 0) BButtons[0]?.classList.add("ctl_btn_active");
            else BButtons[1]?.classList.add("ctl_btn_active");
        }

        const advCBtn = document.getElementById("adv_cv_ctrl_btn");
        const advFBtn = document.getElementById("adv_cv_funcs_btn");
        const mpBtn = document.getElementById("mp_funcs_btn");
        const CButtons = advCBtn ? advCBtn.getElementsByTagName("button") : [];
        const FButtons = advFBtn ? advFBtn.getElementsByTagName("button") : [];
        const MPButtons = mpBtn ? mpBtn.getElementsByTagName("button") : [];

        removeButtonsClass(CButtons);
        removeButtonsClass(FButtons);
        removeButtonsClass(MPButtons);

        const DTbuttons = dTypeBtn ? dTypeBtn.getElementsByTagName("button") : [];

        const detectTypeMap = {
            [config.cv_none]: () => {
                dtIco?.classList.add("feed_ico", "feed_ico_none");
                DTbuttons[0]?.classList.add("ctl_btn_active");
            },
            [config.cv_moti]: () => {
                dtIco?.classList.add("feed_ico", "feed_ico_movtion");
                DTbuttons[1]?.classList.add("ctl_btn_active");
            },
            [config.cv_face]: () => {
                dtIco?.classList.add("feed_ico", "feed_ico_face");
                DTbuttons[2]?.classList.add("ctl_btn_active");
            },
            [config.cv_auto]: () => {
                CButtons[2]?.classList.add("ctl_btn_active");
            },
            [config.cv_objs]: () => {
                FButtons[0]?.classList.add("ctl_btn_active");
            },
            [config.cv_color]: () => {
                FButtons[1]?.classList.add("ctl_btn_active");
            },
            [config.mp_hand]: () => {
                FButtons[2]?.classList.add("ctl_btn_active");
            },
            [config.mp_face]: () => {
                MPButtons[0]?.classList.add("ctl_btn_active");
            },
            [config.mp_pose]: () => {
                MPButtons[1]?.classList.add("ctl_btn_active");
            }
        };

        const detectTypeHandler = detectTypeMap[data[config.detect_type]];
        if (detectTypeHandler) detectTypeHandler();

        if (data[config.detect_type] == config.cv_face|| data[config.detect_type] == config.cv_color || data[config.detect_type] == config.cv_auto|| data[config.detect_type] == config.mp_hand) {
            if (data[config.cv_movtion_mode] === true) {
                cv_heartbeat_stop_flag = false;
                CButtons[0]?.classList.add("ctl_btn_active");
            } else {
                cv_heartbeat_stop_flag = true;
                CButtons[1]?.classList.add("ctl_btn_active");
            }
        }

        if (!armModeInitialized) {
            toggleArmMode();
            armModeInitialized = true;
        }

    } catch (e) {
        console.log(e);
    }
});

// setting page
function confirmSetPanID() {
    if (confirm("Make sure that you have already DISCONNECT the wire of the Tilt Servo")) {
        cmdSend(config.s_panid, 0);
    }
}

function confirmRelease() {
    if (confirm("You will unlock the torque lock, then you can manually adjust the angle of the two servos.")) {
        cmdSend(config.release, 0);
    }
}

function confirmMiddleSet() {
    if (confirm("Set the current position as the middle position.")) {
        cmdSend(config.set_mid, 0);
    }
}

function confirmSetTiltID() {
    if (confirm("If you didn't disconnect the Tilt Servo in step 1, then both servo IDs will be set to 2 after you click the [Set Pan ID] button. Only in this case, you need to click [Set Tilt ID] to restore both servo IDs to 1, then repeat the entire setup process!")) {
        cmdSend(config.s_tilid, 0);
    }
}

function cmdFill(rawInfo, fillInfo) {
    document.getElementById(rawInfo).value = document.getElementById(fillInfo).innerHTML;
}

function jsonSendFb() {
    var xhttp = new XMLHttpRequest();
    xhttp.onreadystatechange = function () {
        if (this.readyState == 4 && this.status == 200) {
            document.getElementById("fbInfo").innerHTML =
                this.responseText;
        }
    };
    xhttp.open("GET", "jsfb", true);
    xhttp.send();
}

function jsonSend() {
    var xhttp = new XMLHttpRequest();
    xhttp.open("GET", "js?json=" + document.getElementById('jsonData').value, true);
    xhttp.send();
    jsonSendFb();
}

let lastTimeCmdSend = Date.now();;
let lastArgsCmdSend;

function cmdSend(inputCmd, inputMode) {
    const now = Date.now();
    if(typeof(lastArgsCmdSend)==undefined) return;
    if (!lastArgsCmdSend || inputCmd != lastArgsCmdSend || now - lastTimeCmdSend >= 10) {
        var jsonData = {
            "cmd": inputCmd,
            "mode": inputMode,
        };
        socketCtrl.send(JSON.stringify(jsonData));
        lastArgsCmdSend = inputCmd;
        lastTimeCmdSend = now;
    }
}

const cmdQueueMap = {};  
const cmdTimers = {};    
const SEND_INTERVAL = 20; 

function cmdJsonCmd(jsonData) {
    const t = jsonData.T;
    if (t == null) return;

    cmdQueueMap[t] = jsonData;

    if (!cmdTimers[t]) {
        cmdTimers[t] = setInterval(() => {
            if (cmdQueueMap[t]) {
                console.log(cmdQueueMap[t])
                socketJson.emit('json', cmdQueueMap[t]);
                delete cmdQueueMap[t];  
            }
        }, SEND_INTERVAL);
    }
}

let armMode = 'joint';
let pressMode = 'increase';

let leftJoystick = null;
let rightJoystick = null;

const armModeToggleEl = document.getElementById('arm_mode_toggle');
const armButtons = document.getElementById("armControlButtons");

function toggleArmMode() {
    if (leftJoystick) {
        leftJoystick.destroy();
        leftJoystick = null;
    }
    if (rightJoystick) {
        rightJoystick.destroy();
        rightJoystick = null;
    }
    if (config.module_type === 1 || config.module_type === 3) {
        armButtons.classList.remove("hidden");
        setLeftStickVisible(true);
    } else {
        armButtons.classList.add("hidden");
        setLeftStickVisible(false);
    }
    const sliderWrap = document.querySelector('.slider_wrap');
    if (slider && sliderText) {
        if(config.module_type === 2){
            sliderText.textContent  = "Y:";
            slider.min = -0.7854;
            slider.max = 1.5708;
            sliderWrap?.classList.remove("hidden");
            rightJoystick = createJoystick('joystick_right', 'x', 'y', 'ahead_on');
            syncCustomSlider();
        }else if(config.module_type === 1 || config.module_type === 3 ){
            sliderText.textContent  = "G:";
            slider.min = 0;
            slider.max = 1.5708;
            sliderWrap?.classList.remove("hidden");
            if (armMode === 'joint') {
                armMode = 'pose';
                leftJoystick = createJoystick('joystick_left', 'x', 'y', 'z');
                rightJoystick = createJoystick('joystick_right', 'p', 'r', 'ahead_on');
            } else {
                armMode = 'joint';
                leftJoystick = createJoystick('joystick_left', 'base', 'shoulder', 'elbow');
                rightJoystick = createJoystick('joystick_right', 'roll', 'wrist', 'ahead_on');
            }
            syncCustomSlider();
        }else if(config.module_type === 0 ){
            sliderWrap?.classList.add("hidden");
        }
    }    

    if (armModeToggleEl) {
        armModeToggleEl.textContent = capitalize(armMode);
    }
}

function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function togglePressMode() {
    if (pressMode === 'increase') {
        pressMode = 'decrease';
    } else {
        pressMode = 'increase';
    }

    document.getElementById('press_mode_toggle').textContent = capitalize(pressMode);
}

let ledPwmState = { io4: 0, io5: 0 };
let ptPoseState = { x: 0, y: 0 };
let armPoseState = { x: 168.7, y: 0, z: -6.7, r: 0, p: 0 };
let armJointState = { base: 0, shoulder: 0, elbow: 2.618, wrist: 0, roll: 0, hand: 3.1416 };
let armlastJointState = { base: 0, shoulder: 0, elbow: 2.618, wrist: 0, roll: 0, hand: 3.1416 };
let rosBaseSpeedState = { x: 0, z: 0 };

ledPwmState = createStateManager(ledPwmState, ledPwmCtrl);
armJointState = createStateManager(armJointState, armJointCtrl);
armPoseState = createStateManager(armPoseState, armPoseCtrl);
ptPoseState = createStateManager(ptPoseState, ptPoseCtrl);
rosBaseSpeedState = createSpeedStateManager(rosBaseSpeedState, rosBaseSpeedCtrl);

function createSpeedStateManager(initialState, onChange) {
  const speedProps = new Set(['x', 'z']);

  const handler = {
    set(target, prop, value) {
      const isSpeedProp = speedProps.has(prop);
      const changed = target[prop] !== value;

      const isZeroSpeed =
        isSpeedProp && value === 0 &&
        target.x === 0 &&
        target.z === 0 ;

      if (changed || (isSpeedProp && !isZeroSpeed)) {
        target[prop] = value;

        if (onChange && !handler._suspend) {
          onChange({ ...target });
        }
      }

      return true;
    }
  };

  handler._suspend = true;
  const proxy = new Proxy(initialState, handler);
  proxy._raw = initialState;

  setTimeout(() => handler._suspend = false, 0);

  return proxy;
}

function createStateManager(initialState, onChange) {
  const handler = {
    set(target, prop, value) {
      if (target[prop] !== value) {
        target[prop] = value;
        if (onChange && !handler._suspend) {
          onChange({ ...target });
        }
      }
      return true;
    }
  };

  handler._suspend = true; 
  const proxy = new Proxy(initialState, handler);
  proxy._raw = initialState;

  setTimeout(() => handler._suspend = false, 0);

  return proxy;
}

function format(value, digits = 5) {
    return parseFloat(value.toFixed(digits));
}

function radToDeg(radian) {
    return radian * 180 / Math.PI;
}

function updateSliderBackground(slider) {
    const val = (slider.value - slider.min) / (slider.max - slider.min) * 100;
    slider.style.background = `linear-gradient(to right, #4FF5C0 0%, #4FF5C0 ${val}%, #ddd ${val}%, #ddd 100%)`;
}

document.querySelectorAll('input[type=range].custom-slider').forEach(slider => {
  updateSliderBackground(slider);
  slider.addEventListener('input', () => updateSliderBackground(slider));
});

(function ensureCustomSliderDom() {
    const el = document.getElementById('slider');
    if (!el) {
        return;
    }
    const wrap = el.parentElement;
    if (wrap) {
        wrap.classList.add('slider_wrap');
    }
    if (!document.getElementById('slider_track')) {
        const track = document.createElement('span');
        track.id = 'slider_track';
        track.className = 'slider_track';
        const fill = document.createElement('span');
        fill.id = 'slider_fill';
        fill.className = 'slider_fill';
        const thumb = document.createElement('span');
        thumb.id = 'slider_thumb';
        thumb.className = 'slider_thumb';
        track.append(fill, thumb);
        el.insertAdjacentElement('afterend', track);
    }
    const scale = document.getElementById('tilt_scale');
    const scaleDiv = document.getElementById('tilt_scalediv');
    if (wrap && scale && scaleDiv && wrap !== scaleDiv.previousElementSibling) {
        scale.insertBefore(wrap, scaleDiv);
    }
})();

const slider = document.getElementById('slider');
const sliderText = document.getElementById('slider_text');
const sliderTrack = document.getElementById('slider_track');
const sliderFill = document.getElementById('slider_fill');
const sliderThumb = document.getElementById('slider_thumb');

function syncCustomSlider() {
    if (!slider || !sliderFill || !sliderThumb) {
        return;
    }
    const min = parseFloat(slider.min);
    const max = parseFloat(slider.max);
    const val = parseFloat(slider.value);
    const ratio = max === min ? 0 : (val - min) / (max - min);
    const pct = Math.max(0, Math.min(1, ratio)) * 100;
    sliderFill.style.height = pct + '%';
    sliderThumb.style.top = (100 - pct) + '%';
}

function applySliderFromClientY(clientY) {
    if (!slider || !sliderTrack) {
        return;
    }
    const rect = sliderTrack.getBoundingClientRect();
    const ratio = 1 - ((clientY - rect.top) / Math.max(rect.height, 1));
    const min = parseFloat(slider.min);
    const max = parseFloat(slider.max);
    slider.value = min + Math.max(0, Math.min(1, ratio)) * (max - min);
    slider.dispatchEvent(new Event('input', { bubbles: true }));
    syncCustomSlider();
}

if (slider && sliderText) {
  slider.addEventListener('input', (e) => {
    if(config.module_type === 1 || config.module_type === 3){
        armJointState.hand = format(3.1416 - e.target.value);
    }else if(config.module_type === 2){
        ptPoseState.y = radToDeg(e.target.value);
    }
    syncCustomSlider();
  });
}

if (sliderTrack) {
    let sliderDragging = false;
    const pointerY = (event) => (event.touches && event.touches[0] ? event.touches[0].clientY : event.clientY);

    const onSliderStart = (event) => {
        sliderDragging = true;
        document.body.style.overflow = 'hidden';
        event.preventDefault();
        applySliderFromClientY(pointerY(event));
    };
    const onSliderMove = (event) => {
        if (!sliderDragging) {
            return;
        }
        event.preventDefault();
        applySliderFromClientY(pointerY(event));
    };
    const onSliderEnd = () => {
        if (!sliderDragging) {
            return;
        }
        sliderDragging = false;
        document.body.style.overflow = '';
    };

    sliderTrack.addEventListener('touchstart', onSliderStart, { passive: false, capture: true });
    sliderTrack.addEventListener('mousedown', onSliderStart);
    document.addEventListener('touchmove', onSliderMove, { passive: false, capture: true });
    document.addEventListener('mousemove', onSliderMove);
    document.addEventListener('touchend', onSliderEnd);
    document.addEventListener('touchcancel', onSliderEnd);
    document.addEventListener('mouseup', onSliderEnd);
    syncCustomSlider();
}

function updatePanTiltUI(panRad, tiltRad) {
    const panDeg = panRad.toFixed(2);
    document.getElementById("Pan").innerHTML = panDeg;
    document.getElementById("pan_scale").style.transform = `rotate(${-panDeg}deg)`;

    const tiltDeg = tiltRad.toFixed(2);
    const tiltNum = document.getElementById("Tilt");
    tiltNum.innerHTML = tiltDeg;

    const pointer = document.getElementById('tilt_scale_pointer');
    const tiltScaleOut = document.getElementById('tilt_scale');
    const tiltScalediv = document.getElementById('tilt_scalediv');
    if (!pointer || !tiltScaleOut || !tiltScalediv || !tiltNum) {
        return;
    }

    const tiltRoot = pointer.parentElement;
    const tiltScaleHeight = tiltScaleOut.getBoundingClientRect().height;
    const tiltNumHeight = tiltNum.getBoundingClientRect().height;
    const tiltBox = tiltRoot.getBoundingClientRect();
    const scaleBox = tiltScalediv.getBoundingClientRect();
    const translateX = scaleBox.right - tiltBox.left;
    const pointerMoveY = tiltScaleHeight / 135;
    const translateY = pointerMoveY * (90 - tiltDeg) - tiltNumHeight / 2;

    pointer.style.transform = `translate(${translateX}px, ${translateY}px)`;
}

requestAnimationFrame(() => {
    const panEl = document.getElementById("Pan");
    const tiltEl = document.getElementById("Tilt");
    const pan = parseFloat(panEl && panEl.textContent) || 0;
    const tilt = parseFloat(tiltEl && tiltEl.textContent) || 0;
    updatePanTiltUI(pan, tilt);
});

const STICK_DEADZONE_PX = 10;
const STICK_CENTER_HOLD_MS = 100;
const STICK_DT_MAX_S = 0.05;
const STICK_PT_DEG_PER_S = 50;
const STICK_JOINT_RAD_PER_S = 0.3;
const STICK_POSE_POS_PER_S = 50;
const STICK_POSE_RP_RAD_PER_S = 0.2;

function createJoystick(containerId, axisX, axisY, clickCenter = null) {
    let stickVector = { x: 0, y: 0 };
    let stickDistance = 0;
    let isPressed = false;
    let pressStartTime = 0;
    let clickCenterAccumulatorTimer = null;
    let holdRafId = null;
    let lastHoldTime = 0;
    let holding = false;

    const zoneIds = {
        joystick_left: 'ctrl_base_left',
        joystick_right: 'ctrl_base_right',
    };
    const container = document.getElementById(zoneIds[containerId] || containerId);
    if (!container) {
        console.warn(`Joystick container not found: ${containerId}`);
        return null;
    }

    const size = Math.round(container.getBoundingClientRect().width) || 80;
    const joystick = nipplejs.create({
        zone: container,
        mode: 'static',
        position: { left: '50%', top: '50%' },
        color: 'rgba(79, 245, 192, 1)',
        size: size,
        restOpacity: 0.5
    });

    function stickModeConfig() {
        if (config.module_type === 2) {
            return {
                stateObject: ptPoseState,
                transformVector: (v) => [v.x, v.y],
                rate: STICK_PT_DEG_PER_S,
                clickCenterOptions: clickCenter ? { callback: lookAhead } : null,
            };
        }
        if (config.module_type === 1 || config.module_type === 3) {
            if (armMode === 'joint') {
                return {
                    stateObject: armJointState,
                    transformVector: (v) => [-v.x, v.y],
                    rate: STICK_JOINT_RAD_PER_S,
                    clickCenterOptions: clickCenter ? {
                        factorPerSecond: 0.1,
                        stateObject: armJointState,
                        callback: lookAhead,
                    } : null,
                };
            }
            if (armMode === 'pose') {
                return {
                    stateObject: armPoseState,
                    transformVector: (v) => [v.y, -v.x],
                    rate: STICK_POSE_POS_PER_S,
                    clickCenterOptions: clickCenter ? {
                        factorPerSecond: 50,
                        stateObject: armPoseState,
                        callback: lookAhead,
                    } : null,
                };
            }
        }
        return null;
    }

    function applyOuterRate(dt, mode) {
        const [vx, vy] = mode.transformVector(stickVector);
        if (axisX === 'p' || axisY === 'r') {
            mode.stateObject[axisX] += vx * STICK_POSE_RP_RAD_PER_S * dt;
            mode.stateObject[axisY] += -vy * STICK_POSE_RP_RAD_PER_S * dt;
        } else if (axisX === 'roll') {
            mode.stateObject[axisX] += -vx * STICK_JOINT_RAD_PER_S * dt;
            mode.stateObject[axisY] += vy * STICK_JOINT_RAD_PER_S * dt;
        } else {
            mode.stateObject[axisX] += vx * mode.rate * dt;
            mode.stateObject[axisY] += vy * mode.rate * dt;
        }
    }

    function applyCenterHold(mode) {
        const clickCenterOptions = mode.clickCenterOptions;
        if (!clickCenterOptions) {
            return;
        }
        if (isPressed) {
            return;
        }
        if (pressStartTime === 0) {
            pressStartTime = Date.now();
            return;
        }
        if (Date.now() - pressStartTime < STICK_CENTER_HOLD_MS) {
            return;
        }
        isPressed = true;
        if (clickCenterAccumulatorTimer) {
            return;
        }
        clickCenterAccumulatorTimer = setInterval(() => {
            const now = Date.now();
            const dt = Math.min((now - pressStartTime) / 1000, STICK_DT_MAX_S);
            pressStartTime = now;
            const direction = (pressMode === 'increase') ? 1 : -1;
            if (clickCenter === 'ahead_on') {
                clickCenterOptions.callback();
            } else {
                clickCenterOptions.stateObject[clickCenter] += direction * clickCenterOptions.factorPerSecond * dt;
            }
        }, 30);
    }

    function applyStick(dt) {
        const mode = stickModeConfig();
        if (!mode) {
            return;
        }
        if (stickDistance < STICK_DEADZONE_PX) {
            applyCenterHold(mode);
            return;
        }
        stopPressing();
        applyOuterRate(dt, mode);
    }

    function holdLoop(nowMs) {
        if (!holding) {
            return;
        }
        const now = nowMs / 1000;
        let dt = lastHoldTime ? (now - lastHoldTime) : 0;
        lastHoldTime = now;
        if (dt > STICK_DT_MAX_S) {
            dt = STICK_DT_MAX_S;
        }
        if (dt > 0) {
            applyStick(dt);
        }
        holdRafId = requestAnimationFrame(holdLoop);
    }

    function startHoldLoop() {
        if (holding) {
            return;
        }
        holding = true;
        lastHoldTime = 0;
        holdRafId = requestAnimationFrame(holdLoop);
    }

    function stopHoldLoop() {
        holding = false;
        if (holdRafId) {
            cancelAnimationFrame(holdRafId);
            holdRafId = null;
        }
        lastHoldTime = 0;
        stickVector = { x: 0, y: 0 };
        stickDistance = 0;
        stopPressing();
    }

    function stopPressing() {
        isPressed = false;
        pressStartTime = 0;
        if (clickCenterAccumulatorTimer) {
            clearInterval(clickCenterAccumulatorTimer);
            clickCenterAccumulatorTimer = null;
        }
    }

    joystick.on('start', () => {
        stickVector = { x: 0, y: 0 };
        stickDistance = 0;
        stopPressing();
        startHoldLoop();
    });

    joystick.on('move', (evt, data) => {
        if (!data || !data.vector) {
            return;
        }
        stickVector = { x: data.vector.x, y: data.vector.y };
        stickDistance = data.distance;
    });

    joystick.on('end', () => {
        stopHoldLoop();
    });

    const origDestroy = joystick.destroy.bind(joystick);
    joystick.destroy = function () {
        stopHoldLoop();
        origDestroy();
    };

    return joystick;
}

function lookAhead() {   
    if (config.module_type === 1 || config.module_type === 3) {
        armJointState.base = 0;
        armJointState.shoulder = 0;
        armJointState.elbow = 2.618;
        armJointState.wrist = 0;
        armJointState.roll = 0;
        armJointState.hand = 3.1416;
        if (slider) {
            slider.value = 3.1416 - armJointState.hand;
            syncCustomSlider();
        }
    }else if (config.module_type === 2 ) {
        ptPoseState.x = 0;
        ptPoseState.y = 0;
        if (slider) {
            slider.value = 0;
            syncCustomSlider();
        }
    }
}

let updatingJoint = false;

function armJointCtrl() {
    if (updatingJoint) return;

    const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

    const limits = {
        base: [-Math.PI, Math.PI],
        shoulder: [-Math.PI / 2, Math.PI / 2],
        elbow: [-Math.PI / 6, Math.PI],
        wrist: [-Math.PI / 2, Math.PI / 2],
        roll: [-Math.PI, Math.PI],
        hand: [Math.PI / 2, Math.PI]
    };

    const clampedState = {};
    for (let joint in limits) {
        if (armJointState.hasOwnProperty(joint)) {
            const [minVal, maxVal] = limits[joint];
            clampedState[joint] = clamp(armJointState[joint], minVal, maxVal);
        }
    }

    const isInvalid = Object.values(clampedState).some(v => isNaN(v));
    const jointToSend = isInvalid ? armlastJointState : clampedState;

    if (!isInvalid) {
        updatingJoint = true;
        for (let joint in jointToSend) {
            armJointState[joint] = jointToSend[joint];  
        }
        armlastJointState = { ...jointToSend };
        updatingJoint = false;
    } else {
        console.warn("Invalid joint value detected, reverting to last valid joint state.");
        return;
    }

    const poseRaw = armPoseState._raw;
    if (config.module_type === 1) {
        cmdJsonCmd({
            T: config.cmd_arm_ctrl,
            base: format(jointToSend.base),
            shoulder: format(jointToSend.shoulder),
            elbow: format(jointToSend.elbow),
            hand: format(jointToSend.hand),
            spd: 0,
            acc: 30
        });
        [poseRaw.x, poseRaw.y, poseRaw.z] = roarm_m2.computePosbyJointRad(
            jointToSend.base,
            jointToSend.shoulder,
            jointToSend.elbow,
            jointToSend.hand
        );
    }else if (config.module_type === 3) {
        cmdJsonCmd({
            T: config.cmd_arm_ctrl,
            base: format(jointToSend.base),
            shoulder: format(jointToSend.shoulder),
            elbow: format(jointToSend.elbow),
            wrist: format(jointToSend.wrist),
            roll: format(jointToSend.roll),
            hand: format(jointToSend.hand),
            spd: 0,
            acc: 30
        });
        [poseRaw.x, poseRaw.y, poseRaw.z, poseRaw.r, poseRaw.p] = roarm_m3.computePosbyJointRad(
            jointToSend.base,
            jointToSend.shoulder,
            jointToSend.elbow,
            jointToSend.wrist,
            jointToSend.roll,
            jointToSend.hand
        );       
    }

    updatePanTiltUI(
        radToDeg(jointToSend.base),
        180 - radToDeg(jointToSend.hand)
    );
}

let updatingPose = false;

function armPoseCtrl() {
    if (updatingPose) return;
    updatingPose = true;

    if (config.module_type === 1) {
        roarm_m2.setEEMode(0);

        let jointAngles = roarm_m2.computeJointRadbyPos(
            armPoseState.x,
            armPoseState.y,
            armPoseState.z,
            armJointState.hand
        );

        if (!roarm_m2.getNanIK()) {
            armJointState.base = format(jointAngles[0]);
            armJointState.shoulder = format(jointAngles[1]);
            armJointState.elbow = format(jointAngles[2]);
            armJointState.hand = format(armJointState.hand);

            armlastJointState = {
                base: jointAngles[0],
                shoulder: jointAngles[1],
                elbow: jointAngles[2],
                hand: jointAngles[5] !== undefined ? jointAngles[5] : armJointState.hand,
            };

        } else {
            console.warn("Invalid IK solution. Reverting to last joint state.");
            armJointState.base = format(armlastJointState.base);
            armJointState.shoulder = format(armlastJointState.shoulder);
            armJointState.elbow = format(armlastJointState.elbow);
            armJointState.hand = format(armJointState.hand);
        }
    } else if (config.module_type === 3) {
        let jointAngles = roarm_m3.computeJointRadbyPos(
            armPoseState.x,
            armPoseState.y,
            armPoseState.z,
            armPoseState.r,
            armPoseState.p,
            armJointState.hand
        );
        if (!roarm_m3.getNanIK()) {
            armJointState.base = format(jointAngles[0]);
            armJointState.shoulder = format(jointAngles[1]);
            armJointState.elbow = format(jointAngles[2]);
            armJointState.wrist = format(jointAngles[3]);
            armJointState.roll = format(jointAngles[4]);
            armJointState.hand = format(armJointState.hand);

            armlastJointState = {
                base: jointAngles[0],
                shoulder: jointAngles[1],
                elbow: jointAngles[2],
                wrist: jointAngles[3],
                roll: jointAngles[4],
                hand: jointAngles[5] !== undefined ? jointAngles[5] : armJointState.hand,
            };

        } else {
            console.warn("Invalid IK solution. Reverting to last joint state.");
            armJointState.base = format(armlastJointState.base);
            armJointState.shoulder = format(armlastJointState.shoulder);
            armJointState.elbow = format(armlastJointState.elbow);
            armJointState.wrist = format(armlastJointState.wrist);
            armJointState.roll = format(armlastJointState.roll);            
            armJointState.hand = format(armJointState.hand);
        }
    }

    updatingPose = false;
}

let updatingPt = false;

function ptPoseCtrl() {
    if (updatingPt) return;

    const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

    const limits = {
        x: [-180, 180],
        y: [-30, 90],
    };

    const clampedState = {};
    for (let axis in limits) {
        if (Object.prototype.hasOwnProperty.call(ptPoseState, axis)) {
            const [minVal, maxVal] = limits[axis];
            clampedState[axis] = clamp(ptPoseState[axis], minVal, maxVal);
        }
    }

    const isInvalid = Object.values(clampedState).some(v => isNaN(v));
    if (isInvalid) {
        console.warn("Invalid pose value detected, reverting to last valid pose state.");
        return;
    }

    updatingPt = true;

    for (let axis in clampedState) {
        ptPoseState[axis] = clampedState[axis];
    }

    if (steady_mode) {
        steadyCtrl(1);
        updatePanTiltUI(0, clampedState.y);
    } else {
        cmdJsonCmd({
            T: config.cmd_gimbal_ctrl,
            X: clampedState.x,
            Y: clampedState.y,
            SPD: 0,
            ACC: 128
        });
        updatePanTiltUI(clampedState.x, clampedState.y);
    }

    updatingPt = false;
}

var steady_mode = false;

function steadyCtrl(inputCmd) {
    var steadyCtrlBtn = document.getElementById("steady_ctrl_btn");
    var steadybuttons = steadyCtrlBtn.getElementsByTagName("button");
    removeButtonsClass(steadybuttons);
    if (inputCmd == 0) {
        steadybuttons[0].classList.add("ctl_btn_active");
        steady_mode = false;
        cmdJsonCmd({ "T": config.cmd_gimbal_steady, "s": 0, "y": ptPoseState.y });
    } else if (inputCmd == 1) {
        steadybuttons[1].classList.add("ctl_btn_active");
        steady_mode = true;
        cmdJsonCmd({ "T": config.cmd_gimbal_steady, "s": 1, "y": ptPoseState.y });
    }
}

let updatingRosSpeed = false;
let speed_rate = 0.3;

function speedRateCtrl(inputRate) {
    speed_rate = inputRate;
    var spdCtrlBtn = document.getElementById("speed_ctrl_btn");
    var spdbuttons = spdCtrlBtn.getElementsByTagName("button");
    removeButtonsClass(spdbuttons);
    if (speed_rate == 0.30) {
        spdbuttons[0].classList.add("ctl_btn_active");
    } else if (speed_rate== 0.66) {
        spdbuttons[1].classList.add("ctl_btn_active");
    } else if (speed_rate == 1.0) {
        spdbuttons[2].classList.add("ctl_btn_active");
    }
}

function rosBaseSpeedCtrl() {
    if (updatingRosSpeed) return;

    const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

    const limits = {
        x: [-1.5, 1.5],
        z: [-3.1416, 3.1416],
    };

    const clampedState = {};
    for (let axis in limits) {
        if (Object.prototype.hasOwnProperty.call(rosBaseSpeedState, axis)) {
            const [minVal, maxVal] = limits[axis];
            clampedState[axis] = clamp(rosBaseSpeedState[axis], minVal, maxVal);
        }
    }

    const isInvalid = Object.values(clampedState).some(v => isNaN(v));
    if (isInvalid) {
        console.warn("Invalid speed value detected, skipping command.");
        return;
    }

    updatingRosSpeed = true;

    for (let axis in clampedState) {
        rosBaseSpeedState[axis] = clampedState[axis];
    }

    cmdJsonCmd({
        T: config.cmd_ros_movition_ctrl,
        X: clampedState.x,
        Z: clampedState.z,
    });

    updatingRosSpeed = false;
    heartbeat_send_flag = true;
}

let moveTimer = null;

document.querySelectorAll(
    '.ctl9_base_btn, .ctl9_base_btn2, .ctl9_base_btn4, .ctl9_base_btn6, .ctl9_base_btn8'
).forEach(btn => {

    const sendCmd = () => {
        const x_dir = parseFloat(btn.dataset.x || 0);
        const z_dir = parseFloat(btn.dataset.z || 0);

        rosBaseSpeedState.x = x_dir * config.max_speed * speed_rate;
        rosBaseSpeedState.z = z_dir * config.max_turn_speed * speed_rate;
    
        heartbeat_send_flag = true;
    };

    const onDown = () => {
        if (moveTimer) return; 
        sendCmd();           
        moveTimer = setInterval(sendCmd, 50); 
    };

    const onUp = () => {
        clearInterval(moveTimer);
        moveTimer = null;

        rosBaseSpeedState.x = 0.0;
        rosBaseSpeedState.z = 0.0;

        console.log('stop', rosBaseSpeedState);
    };

    btn.addEventListener('mousedown', onDown);
    btn.addEventListener('touchstart', onDown);

    btn.addEventListener('mouseup', onUp);
    btn.addEventListener('mouseleave', onUp); 
    btn.addEventListener('touchend', onUp);
    btn.addEventListener('touchcancel', onUp);
});

var heartbeat_send_flag = true;

function heartbeat_send() {
    if (socketJson.connected && heartbeat_send_flag && !cv_heartbeat_stop_flag) {
        cmdJsonCmd({ 'T': config.cmd_ros_movition_ctrl, 'X': 0, 'Z': 0 });
    }
}

setInterval(heartbeat_send, 2000);

let updatingLed = false;

function ledPwmCtrl() {
    if (updatingLed) return;

    const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

    const limits = {
        io4: [0, 255],
        io5: [0, 255],
    };

    const clampedState = {};
    for (let axis in limits) {
        if (Object.prototype.hasOwnProperty.call(ledPwmState, axis)) {
            const [minVal, maxVal] = limits[axis];
            clampedState[axis] = clamp(ledPwmState[axis], minVal, maxVal);
        }
    }

    const isInvalid = Object.values(clampedState).some(v => isNaN(v));
    if (isInvalid) {
        console.warn("Invalid pwm value detected, reverting to last valid pwm state.");
        return;
    }

    updatingLed = true;

    for (let axis in clampedState) {
        ledPwmState[axis] = clampedState[axis];
    }

    cmdJsonCmd({
        T: config.cmd_set_led_pwm,
        IO4: clampedState.io4,
        IO5: clampedState.io4
    });
    
    updatingLed = false;
}

// keyboard ctrl 
const keyMap = {
    37: 'left',      // ←
    38: 'up',        // ↑
    39: 'right',     // →
    40: 'down',      // ↓
    83: 's',         // swith 
    48: 'ahead_on',  //0
    49: 'base',      //1
    50: 'shoulder',  //2
    51: 'elbow',     //3
    52: 'wrist',     //4
    53: 'roll',      //5
    82: 'r',
    80: 'p',
    71: 'g',
    88: 'x',
    89: 'y',
    90: 'z',
    67: 'c',
    70: 'f',
    76: 'l',
    72: 'h',
    77: 'm',
    79: 'o',
    84: 't',
    85: 'u'
};

const keyState = {};
for (const code in keyMap) {
    keyState[keyMap[code]] = 0;
}

let directionReversed = false;
const repeatInterval = 100;
const keyTimers = {};

function keyboardCtrl() {
    const direction = directionReversed ? -1 : 1;

    const left = keyState.left;
    const right = keyState.right;
    const up = keyState.up;
    const down = keyState.down;

    if (up && !down) {
        rosBaseSpeedState.x = speed_rate * config.max_speed;
    } else if (!up && down) {
        rosBaseSpeedState.x = -speed_rate * config.max_speed;
    } else {
        rosBaseSpeedState.x = 0;
    }

    if (left && !right) {
        rosBaseSpeedState.z = speed_rate * config.max_turn_speed;
    } else if (!left && right) {
        rosBaseSpeedState.z = -speed_rate * config.max_turn_speed;
    } else {
        rosBaseSpeedState.z = 0;
    }
    
    if (keyState.s) directionReversed = !directionReversed;

    if (keyState.l) {
        ledPwmState.io4 += 5 * direction;
    }

    const moveXYZ = keyState.x || keyState.y || keyState.z || keyState.r || keyState.p;
    if (moveXYZ) {
        if (config.module_type === 2) {
            if (keyState.x) ptPoseState.x += 5 * direction;
            if (keyState.y) ptPoseState.y += 5 * direction;
        } else if (config.module_type === 1 || config.module_type === 3) {
            if (keyState.x) armPoseState.x += 5 * direction;
            if (keyState.y) armPoseState.y += 5 * direction;
            if (keyState.z) armPoseState.z += 5 * direction;
            if (keyState.r) armPoseState.r += -0.02 * direction;
            if (keyState.p) armPoseState.p += 0.02 * direction;
        }
    }

    const moveJoint = keyState.base || keyState.shoulder || keyState.elbow || keyState.wrist || keyState.roll;
    if (moveJoint) {
        if (keyState.base)     armJointState.base     += 0.03 * direction;
        if (keyState.shoulder) armJointState.shoulder += 0.03 * direction;
        if (keyState.elbow)    armJointState.elbow    += 0.03 * direction;
        if (keyState.wrist)    armJointState.wrist    += 0.03 * direction;
        if (keyState.roll)     armJointState.roll     += -0.03 * direction;
    }

    if (keyState.g) {
        armJointState.hand -= 0.01 * direction;
        document.getElementById('slider').value = 3.1416 - armJointState.hand;
        syncCustomSlider();
    }

    if (keyState.ahead_on) lookAhead();
}

document.onkeydown = function (event) {
    if (isInputFocused) return;

    const key = keyMap[event.keyCode];
    if (!key) return;

    if (['left', 'right', 'up', 'down'].includes(key)) {
        event.preventDefault();
    }

    if (keyState[key] === 0) {
        keyState[key] = 1;
        keyboardCtrl();

        const repeatableKeys = ['l', 'x', 'y', 'z', 'r', 'p', 'g', 'base', 'shoulder', 'elbow', 'wrist', 'roll', 'up', 'down', 'left', 'right'];
        if (repeatableKeys.includes(key) && !keyTimers[key]) {
            keyTimers[key] = setInterval(() => {
                keyboardCtrl();
            }, repeatInterval);
        }
    }
};

document.onkeyup = function (event) {
    if (isInputFocused) return;
    const key = keyMap[event.keyCode];
    if (!key) return;

    if (keyState[key] === 1) {
        keyState[key] = 0;
        keyboardCtrl();
    }

    if (keyTimers[key]) {
        clearInterval(keyTimers[key]);
        delete keyTimers[key];
    }
};

// gamepad ctrl functions
var gp_x = 0.00;
var gp_z = 0.00;
var last_gp_x = 0.00;
var last_gp_z = 0.00;

var last_gp_rt2 = false;

var startPressed = false;
var last_gp_picture = false;

let last_btn_l1 = false;
let last_btn_l2 = false;
let last_btn_r1 = false;
let last_btn_r2 = false;
const speed_levels = [min_rate, mid_rate, max_rate];
let speed_index = 0;
let lastSwitchTime_l1 = 0;
let lastSwitchTime_l2 = 0;
let lastSwitchTime_r1 = 0;
let lastSwitchTime_r2 = 0;
const switchCooldown = 300;

window.addEventListener("gamepadconnected", function (e) {
    console.log("gamepad connected:" + e.gamepad.index);
    heartbeat_send_flag = false;
});


window.addEventListener("gamepaddisconnected", function (e) {
    console.log("gamepad disconnected:" + e.gamepad.index);
    heartbeat_send_flag = true;
});

function logButtons(gamepad) {
    gamepad.buttons.forEach((button, index) => {
        console.log(`button ${index}: ${button.pressed ? 'pressed' : 'released'}`);
    });
}

function logAxes(gamepad) {
    gamepad.axes.forEach((axis, index) => {
        console.log(`axis ${index}: ${axis}`);

    });
}

const mapping = {
    "A": 0,
    "B": 1,
    "X": 2,
    "Y": 3,
    "L1": 4,
    "R1": 5,
    "L2": 6, 
    "R2": 7,
    "SELECT": 8,
    "START": 9,
    "LEFT_STICK": 10,
    "RIGHT_STICK": 11,
    "DPAD_UP": 12,
    "DPAD_DOWN": 13,
    "DPAD_LEFT": 14,
    "DPAD_RIGHT": 15,
    "HOME": 16,

    "LEFT_STICK_X": 0,
    "LEFT_STICK_Y": 1,
    "RIGHT_STICK_X": 2,
    "RIGHT_STICK_Y": 3,
};

function gamepadCtrl() {
    const threshold = 0.01;
    const pose_sensitivity = 1;
    const joint_sensitivity = 0.01;
    var gamepads = navigator.getGamepads ? navigator.getGamepads() : [];

    for (var i = 0; i < gamepads.length; i++) {
        var gp = gamepads[i];
        if (gp) {
            //   logButtons(gp);
            //   logAxes(gp);   
            speed_rate = speed_levels[speed_index];
            const l1Pressed = gp.buttons[mapping["L1"]].pressed;
            const now_l1 = Date.now();
            if ( l1Pressed && !last_btn_l1 && (now_l1 - lastSwitchTime_l1 > switchCooldown)) {
                speed_index = Math.max(0, speed_index - 1);
                speed_rate = speed_levels[speed_index];
                speedRateCtrl(speed_rate);
                lastSwitchTime_l1 = now_l1;
            }
            last_btn_l1 = l1Pressed;

            const l2Pressed = gp.buttons[mapping["L2"]].pressed;
            const now_l2 = Date.now();
            if (l2Pressed && !last_btn_l2 && (now_l2 - lastSwitchTime_l2 > switchCooldown)) {
                speed_index = Math.min(speed_levels.length - 1, speed_index + 1);
                speed_rate = speed_levels[speed_index];
                speedRateCtrl(speed_rate);
                lastSwitchTime_l2 = now_l2;
            }
            last_btn_l2 = l2Pressed;

            gp_x = 0;
            if (gp.buttons[mapping["DPAD_UP"]].pressed) gp_x = config.max_speed * speed_rate;
            if (gp.buttons[mapping["DPAD_DOWN"]].pressed) gp_x = -config.max_speed * speed_rate;
            
            gp_z = 0;   
            if (gp.buttons[mapping["DPAD_LEFT"]].pressed) gp_z = config.max_turn_speed * speed_rate;
            if (gp.buttons[mapping["DPAD_RIGHT"]].pressed) gp_z = -config.max_turn_speed * speed_rate;

            if (Math.abs(gp_x) < threshold) {
                gp_x = 0;
            }
            if (Math.abs(gp_z) < threshold) {
                gp_z = 0;
            }

            rosBaseSpeedState.x = gp_x;
            rosBaseSpeedState.z = gp_z;

            if (gp.buttons[mapping["START"]].pressed && !startPressed) {
                startPressed = true;
                $("#record-btn").trigger("click");
            }
            if (!gp.buttons[mapping["START"]].pressed) {
                startPressed = false;
            }

            if (last_gp_picture != gp.buttons[mapping["SELECT"]].pressed) {
                if (gp.buttons[mapping["SELECT"]].pressed) {
                    captureAndUpdate();
                }
                last_gp_picture = gp.buttons[mapping["SELECT"]].pressed;
            }

            if (gp.buttons[mapping["RIGHT_STICK"]].pressed) {
                lookAhead();
            }

            let deltaLed = 0;
            if (gp.buttons[mapping["Y"]].pressed) {
                deltaLed = 1;
            } else if (gp.buttons[mapping["X"]].pressed) {
                deltaLed = -1;
            } else {
                deltaLed = 0;
            }
            ledPwmState.io4 += deltaLed;

            if (config.module_type === 2) {
                const r2Pressed = gp.buttons[mapping["R2"]].pressed;
                if (r2Pressed && !last_gp_rt2) {
                    cmdSend(config.led_mode, config.head_ct);
                }
                last_gp_rt2 = r2Pressed;
                const gp_pt_speed = 1;

                var change_x = gp.axes[mapping["RIGHT_STICK_X"]];
                var change_y = gp.axes[mapping["RIGHT_STICK_Y"]];

                if (Math.abs(change_x) > threshold || Math.abs(change_y) > threshold) {
                    ptPoseState.x = ptPoseState.x + change_x * gp_pt_speed;
                    ptPoseState.y = ptPoseState.y - change_y * gp_pt_speed;  
                }
            } else if (config.module_type === 1 || config.module_type === 3) {
                const change_joystick_left_x = gp.axes[mapping["LEFT_STICK_X"]];    
                const change_joystick_left_y = gp.axes[mapping["LEFT_STICK_Y"]];

                let change_joystick_left_click = 0;
                if (gp.buttons[mapping["LEFT_STICK"]].pressed && gp.buttons[mapping["R2"]].pressed) {
                    change_joystick_left_click = -1;
                } else if (gp.buttons[mapping["LEFT_STICK"]].pressed) {
                    change_joystick_left_click = 1;
                }

                const change_joystick_right_x = gp.axes[mapping["RIGHT_STICK_X"]];
                const change_joystick_right_y = -gp.axes[mapping["RIGHT_STICK_Y"]];

                const r1Pressed = gp.buttons[mapping["R1"]].pressed;
                const now_r1 = Date.now();
                if (r1Pressed && !last_btn_r1 && (now_r1 - lastSwitchTime_r1 > switchCooldown)) {
                    toggleArmMode();
                    lastSwitchTime_r1 = now_r1;
                }

                if (armMode === 'pose') {
                    armPoseState.z += change_joystick_left_click * pose_sensitivity;
                    if (Math.abs(change_joystick_left_x) > threshold || Math.abs(change_joystick_left_y) > threshold || Math.abs(change_joystick_right_x) > threshold || Math.abs(change_joystick_right_y) > threshold) {
                        armPoseState.x -= change_joystick_left_y * pose_sensitivity;
                        armPoseState.y -= change_joystick_left_x * pose_sensitivity;
                        armPoseState.r += change_joystick_right_x * joint_sensitivity;
                        armPoseState.p += change_joystick_right_y * joint_sensitivity;
                    }
                } else if(armMode === 'joint'){
                    armJointState.elbow -= change_joystick_left_click * joint_sensitivity;
                    if (Math.abs(change_joystick_left_x) > threshold || Math.abs(change_joystick_left_y) > threshold || Math.abs(change_joystick_right_x) > threshold || Math.abs(change_joystick_right_y) > threshold) {
                        armJointState.base -= change_joystick_left_x * joint_sensitivity;
                        armJointState.shoulder -= change_joystick_left_y * joint_sensitivity;
                        armJointState.roll += change_joystick_right_x * joint_sensitivity;
                        armJointState.wrist += change_joystick_right_y * joint_sensitivity;
                    }
                }

                last_btn_r1 = r1Pressed;

                let deltaHand = 0;
                if (gp.buttons[mapping["A"]].pressed) {
                    deltaHand = 0.005;
                } else if (gp.buttons[mapping["B"]].pressed) {
                    deltaHand = -0.005;
                } else {
                    deltaHand = 0;
                }
                armJointState.hand += deltaHand;
            }

        }
    }
    window.requestAnimationFrame(gamepadCtrl);
}

window.requestAnimationFrame(gamepadCtrl);

}