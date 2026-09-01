import pygame
import os
import random
import threading
import time
import yaml
import queue
import re
import subprocess

curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/../config.yaml', 'r') as yaml_file:
    config = yaml.safe_load(yaml_file)

current_path = os.path.abspath(os.path.dirname(__file__))

sink_device_name = "alsa_output.usb-Solid_State_System_Co._Ltd._USB_PnP_Audio_Device_000000000000-00.analog-stereo"
source_device_name = "alsa_input.usb-Solid_State_System_Co._Ltd._USB_PnP_Audio_Device_000000000000-00.analog-stereo"

CHUNK = 512
CHANNELS = 1
RATE = 16000
MIXER_WAIT_SEC = 45

audio_queue = queue.Queue()

usb_connected = False
play_audio_event = threading.Event()
min_time_bewteen_play = config['audio_config']['min_time_bewteen_play']
_volume = float(config['audio_config']['default_volume'])

_pulse_ready = threading.Event()
_mixer_ready = threading.Event()
_mixer_lock = threading.Lock()
_tts = None
_tts_lock = threading.Lock()
_engine = None
_engine_lock = threading.Lock()
_capture_lock = threading.Lock()
_capture_thread = None


def _pactl_has_device(kind, name):
    try:
        result = subprocess.run(
            ['pactl', 'list', 'short', kind],
            capture_output=True, text=True, timeout=5, check=False
        )
        return result.returncode == 0 and name in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f"pactl list {kind} failed: {e}")
        return False


def set_default_sink(sink_name, source_name):
    try:
        subprocess.run(
            ['pactl', 'set-default-sink', sink_name],
            check=True, timeout=5, capture_output=True
        )
        print(f"Default sink set to '{sink_name}' successfully.")
        subprocess.run(
            ['pactl', 'set-default-source', source_name],
            check=True, timeout=5, capture_output=True
        )
        print(f"Default source set to '{source_name}' successfully.")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f"Error: {e}")
        return False


def _init_mixer_backend():
    global usb_connected
    interval = 1.0
    attempt = 0
    while not _pulse_ready.is_set():
        attempt += 1
        try:
            sink_ok = _pactl_has_device('sinks', sink_device_name)
            source_ok = _pactl_has_device('sources', source_device_name)
            if sink_ok and source_ok and set_default_sink(sink_device_name, source_device_name):
                try:
                    with _mixer_lock:
                        if pygame.mixer.get_init() is None:
                            pygame.mixer.init()
                        pygame.mixer.music.set_volume(_volume)
                    usb_connected = True
                    _pulse_ready.set()
                    _mixer_ready.set()
                    print('audio usb connected')
                    return
                except Exception as e:
                    print(f"[audio mixer init] pygame mixer failed: {e}")
        except Exception as e:
            print(f"[audio mixer init] {e}")
        if attempt == 1 or attempt % 10 == 0:
            print(f'audio device not ready (attempt {attempt}), retrying...')
        time.sleep(interval)
        interval = min(interval * 1.5, 10.0)


def ensure_mixer(timeout=MIXER_WAIT_SEC):
    if _mixer_ready.is_set():
        return True
    if timeout is None or timeout <= 0:
        return _mixer_ready.is_set()
    return _mixer_ready.wait(timeout)


def ensure_tts():
    global _tts
    if _tts is not None:
        return _tts
    with _tts_lock:
        if _tts is not None:
            return _tts
        print('loading sherpa-onnx TTS model...')
        import sherpa_onnx
        model_dir = os.path.join(thisPath, "models", "sherpa-onnx-vits-zh-ll")
        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=os.path.join(model_dir, "model.onnx"),
                    lexicon=os.path.join(model_dir, "lexicon.txt"),
                    data_dir='',
                    dict_dir=os.path.join(model_dir, "dict"),
                    tokens=os.path.join(model_dir, "tokens.txt"),
                ),
                matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(),
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(),
                provider='cpu',
                debug=False,
                num_threads=2,
            ),
            rule_fsts=os.path.join(model_dir, "number.fst"),
            max_num_sentences=1,
        )
        _tts = sherpa_onnx.OfflineTts(tts_config)
        print('sherpa-onnx TTS model loaded')
        return _tts


def ensure_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        import pyttsx3
        _engine = pyttsx3.init()
        _engine.setProperty('rate', config['audio_config']['speed_rate'])
        print('pyttsx3 engine ready')
        return _engine


threading.Thread(target=_init_mixer_backend, daemon=True, name='audio-mixer-init').start()


def audio_capture_thread():
    import pyaudio
    _pulse_ready.wait()
    while True:
        p = None
        stream = None
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=CHANNELS, rate=RATE,
                            input=True, frames_per_buffer=CHUNK)
            while True:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_queue.put(data, timeout=0.05)
                except queue.Full:
                    pass
        except Exception as e:
            print(f"[Audio Capture Error]: {e}")
            time.sleep(2)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass


def start_audio_capture():
    global _capture_thread
    with _capture_lock:
        if _capture_thread is not None and _capture_thread.is_alive():
            return
        _capture_thread = threading.Thread(
            target=audio_capture_thread, daemon=True, name='audio-capture'
        )
        _capture_thread.start()


def play_audio(input_audio_file):
    if not ensure_mixer():
        print('audio usb not ready, skip play')
        play_audio_event.clear()
        return
    if not os.path.isfile(input_audio_file):
        print(f'[play_audio] file not found: {input_audio_file}')
        play_audio_event.clear()
        return
    try:
        pygame.mixer.music.set_volume(_volume)
        pygame.mixer.music.load(input_audio_file)
        pygame.mixer.music.play()
        print(f'[play_audio] pygame {input_audio_file}')
    except Exception as e:
        print(f'[play_audio] pygame load/play failed: {e}')
        play_audio_event.clear()
        return
    while pygame.mixer.music.get_busy():
        time.sleep(0.05)
    time.sleep(min_time_bewteen_play)
    play_audio_event.clear()


def play_random_audio(input_dirname, force_flag):
    if play_audio_event.is_set() and not force_flag:
        return
    audio_files = [f for f in os.listdir(current_path + "/../templates/media/sounds/" + input_dirname) if f.endswith((".mp3", ".wav"))]
    audio_file = random.choice(audio_files)
    play_audio_event.set()
    audio_thread = threading.Thread(target=play_audio, args=(current_path + "/../templates/media/sounds/" + input_dirname + "/" + audio_file,))
    audio_thread.start()


def play_audio_thread(input_file):
    if play_audio_event.is_set():
        stop()
    play_audio_event.set()
    audio_thread = threading.Thread(target=play_audio, args=(input_file,))
    audio_thread.start()


def play_file(audio_file):
    audio_file = current_path + "/../templates/media/sounds/" + audio_file
    play_audio_thread(audio_file)


def get_mixer_status():
    if not _mixer_ready.is_set():
        return
    return pygame.mixer.music.get_busy()


def set_audio_volume(input_volume):
    global _volume
    input_volume = float(input_volume)
    if input_volume > 1:
        input_volume = 1
    elif input_volume < 0:
        input_volume = 0
    _volume = input_volume
    if _mixer_ready.is_set():
        pygame.mixer.music.set_volume(input_volume)


def set_min_time_between(input_time):
    global min_time_bewteen_play
    min_time_bewteen_play = input_time


def contains_chinese(text):
    return bool(re.search('[\u4e00-\u9fff]', text))


def play_speech(input_text):
    filename = 'audio-say.wav'

    try:
        if contains_chinese(input_text):
            import numpy as np
            import soundfile as sf
            tts = ensure_tts()
            if tts is None:
                return
            audio = tts.generate(input_text, sid=4, speed=1.0)
            scale = 4
            samples = np.array(audio.samples) * scale
            samples = np.clip(samples, -1.0, 1.0)

            sf.write(
                filename,
                samples,
                samplerate=audio.sample_rate,
                subtype="PCM_16",
            )

            for _ in range(10):
                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    break
                time.sleep(0.1)

            play_audio(filename)
        else:
            if not ensure_mixer():
                print('audio usb not ready, skip speech')
                return
            engine = ensure_engine()
            if engine is None:
                return
            engine.say(input_text)
            engine.runAndWait()

    except Exception as e:
        print(f"[play failure] {e}")
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception as e:
                print(f"[delete file failure] {e}")
        play_audio_event.clear()


def play_speech_thread(input_text):
    if play_audio_event.is_set():
        return
    play_audio_event.set()
    speech_thread = threading.Thread(target=play_speech, args=(input_text,))
    speech_thread.start()


def stop():
    if pygame.mixer.get_init():
        pygame.mixer.music.stop()
    play_audio_event.clear()


if __name__ == '__main__':
    play_audio_thread("/home/ws/ugv_rpi/templates/media/sounds/others/Boomopera_-_You_Rock_Full_Length.mp3")
    time.sleep(100)
