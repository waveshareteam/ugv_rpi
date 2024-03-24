import pygame
import os
import random
import threading
import time
import yaml
import pyttsx3

usb_connected = False

curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/config.yaml', 'r') as yaml_file:
    config = yaml.safe_load(yaml_file)

current_path = os.path.abspath(os.path.dirname(__file__))

try:
	pygame.mixer.init()
	pygame.mixer.music.set_volume(config['audio_config']['default_volume'])
	usb_connected = True
	print('audio usb connected')
except:
	usb_connected = False
	print('audio usb not connected')

play_audio_event = threading.Event()
min_time_bewteen_play = config['audio_config']['min_time_bewteen_play']

engine = pyttsx3.init()
engine.setProperty('rate', config['audio_config']['speed_rate'])


def play_audio(input_audio_file):
	if not usb_connected:
		return
	try:
		pygame.mixer.music.load(input_audio_file)
		pygame.mixer.music.play()
	except:
		play_audio_event.clear()
		return
	while pygame.mixer.music.get_busy():
		pass
	time.sleep(min_time_bewteen_play)
	play_audio_event.clear()


def play_random_audio(input_dirname, force_flag):
	if not usb_connected:
		return
	if play_audio_event.is_set() and not force_flag:
		return
	audio_files = [f for f in os.listdir(current_path + "/sounds/" + input_dirname) if f.endswith((".mp3", ".wav"))]
	audio_file = random.choice(audio_files)
	play_audio_event.set()
	audio_thread = threading.Thread(target=play_audio, args=(current_path + "/sounds/" + input_dirname + "/" + audio_file,))
	audio_thread.start()


def play_audio_thread(input_file):
	if not usb_connected:
		return
	if play_audio_event.is_set():
		return
	play_audio_event.set()
	audio_thread = threading.Thread(target=play_audio, args=(input_file,))
	audio_thread.start()


def play_file(audio_file):
	if not usb_connected:
		return
	audio_file = current_path + "/sounds/" + audio_file
	play_audio_thread(audio_file)


def get_mixer_status():
	if not usb_connected:
		return
	return pygame.mixer.music.get_busy()


def set_audio_volume(input_volume):
	if not usb_connected:
		return
	input_volume = float(input_volume)
	if input_volume > 1:
		input_volume = 1
	elif input_volume < 0:
		input_volume = 0
	pygame.mixer.music.set_volume(input_volume)


def set_min_time_between(input_time):
	if not usb_connected:
		return
	global min_time_bewteen_play
	min_time_bewteen_play = input_time


def play_speech(input_text):
	if not usb_connected:
		return
	engine.say(input_text)
	engine.runAndWait()
	play_audio_event.clear()


def play_speech_thread(input_text):
	if not usb_connected:
		return
	if play_audio_event.is_set():
		return
	play_audio_event.set()
	speech_thread = threading.Thread(target=play_speech, args=(input_text,))
	speech_thread.start()

def stop():
	if not usb_connected:
		return
	pygame.mixer.music.stop()
	play_audio_event.clear()


if __name__ == '__main__':
	# while True:
	# 	print(1)
	# 	engine.say("this is a test")
	# 	engine.runAndWait()
	# 	time.sleep(1)
	play_audio_thread("/home/ws/ugv_rpi/sounds/others/Boomopera_-_You_Rock_Full_Length.mp3")
	time.sleep(100)