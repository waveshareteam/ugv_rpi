import serial  
import json
import queue
import threading
import yaml
import os
import time
import glob
import numpy as np

curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/config.yaml', 'r') as yaml_file:
    f = yaml.safe_load(yaml_file)

class ReadLine:
	def __init__(self, s):
		self.buf = bytearray()
		self.s = s

		self.sensor_data = []
		self.sensor_list = []
		try:
			self.sensor_data_ser = serial.Serial(glob.glob('/dev/ttyUSB*')[0], 115200)
			print("/dev/ttyUSB* connected succeed")
		except:
			self.sensor_data_ser = None
		self.sensor_data_max_len = 51

		self.open_lidar_serial()
		self.ANGLE_PER_FRAME = 12
		self.HEADER = 0x54
		self.lidar_angles = []
		self.lidar_distances = []
		self.lidar_angles_show = []
		self.lidar_distances_show = []
		self.lidar_scan_time = 0.0
		self.last_start_angle = 0
		# 1-degree occupancy bins: (distance_mm, timestamp).  /lidar_points
		# serves these (last 3 s) so the radar shows a dense, smoothed picture
		# built from several revolutions instead of one sparse partial scan.
		self.lidar_bins = [(0.0, 0.0) for _ in range(360)]
		# Rolling read buffer + bookkeeping for the non-blocking scanner.
		self._lbuf = bytearray()
		self._last_rx = 0.0
		# Wire-health counters: bytes arriving vs valid frames parsed.  Rates
		# are computed over a 2 s sliding window; the UI uses them to tell
		# "sensor silent" from "wire alive but garbage" from "streaming".
		self._rate_stamp = time.time()
		self._rate_bytes = 0
		self._rate_frames = 0
		self.rx_bps = 0.0
		self.frames_per_s = 0.0

	def _pick_lidar_port(self):
		"""The D500 kit's adapter is a CP210x bridge on /dev/ttyUSB*; older
		UART-wired kits stream through the ESP32 base board on /dev/ttyACM*.
		Prefer the USB bridge, fall back to the base board."""
		usb = sorted(glob.glob('/dev/ttyUSB*'))
		acm = sorted(glob.glob('/dev/ttyACM*'))
		return usb[0] if usb else (acm[0] if acm else None)

	def open_lidar_serial(self):
		"""(Re)open the lidar serial port on the best available device.
		De-asserts DTR/RTS: CP210x adapters can route those lines to the
		sensor's reset/PWM, and pyserial asserts them on open by default,
		which can hold the STL-19P in a dead state."""
		port = self._pick_lidar_port()
		if port is None:
			print("[lidar] no serial device for lidar")
			self.lidar_ser = None
			return
		try:
			if self.lidar_ser is not None:
				try:
					self.lidar_ser.close()
				except Exception:
					pass
				self.lidar_ser = None
			s = serial.Serial(port, 230400, timeout=1, dsrdtr=False, rtscts=False)
			try:
				s.dtr = False
				s.rts = False
			except Exception:
				pass
			self.lidar_ser = s
			self.last_start_angle = 0
			self._lbuf.clear()
			print(f"lidar serial connected succeed on {port}")
		except Exception as e:
			print(f"[lidar] open failed {port}: {e}")
			self.lidar_ser = None

	def kick_lidar(self):
		"""Pulse the serial DTR line to reset a sensor MCU that has gone
		silent-but-busy (STL-19P on CP210x adapters where DTR = reset).
		Safe when DTR is not wired: it just idles the line."""
		print("[lidar] kicking sensor: DTR pulse")
		try:
			port = self._pick_lidar_port()
			if self.lidar_ser is not None:
				try:
					self.lidar_ser.close()
				except Exception:
					pass
				self.lidar_ser = None
			if port:
				s = serial.Serial(port, 230400, timeout=0.2, dsrdtr=False, rtscts=False)
				try:
					s.dtr = True
					time.sleep(0.25)
					s.dtr = False
				except Exception:
					pass
				s.close()
			time.sleep(1.0)   # give the sensor a moment to boot
		except Exception as e:
			print(f"[lidar] kick failed: {e}")
		self.open_lidar_serial()

	def readline(self):
		i = self.buf.find(b"\n")
		if i >= 0:
			r = self.buf[:i+1]
			self.buf = self.buf[i+1:]
			return r
		while True:
			i = max(1, min(512, self.s.in_waiting))
			data = self.s.read(i)
			i = data.find(b"\n")
			if i >= 0:
				r = self.buf + data[:i+1]
				self.buf[0:] = data[i+1:]
				return r
			else:
				self.buf.extend(data)

	def clear_buffer(self):
		self.s.reset_input_buffer()

	def read_sensor_data(self):
		if self.sensor_data_ser == None:
			return

		try:
			buffer_clear = False
			while self.sensor_data_ser.in_waiting > 0:
				buffer_clear = True
				sensor_readline = self.sensor_data_ser.readline()
				if len(sensor_readline) <= self.sensor_data_max_len:
					self.sensor_list.append(sensor_readline.decode('utf-8')[:-2])
				else:
					self.sensor_list.append(sensor_readline.decode('utf-8')[:self.sensor_data_max_len])
					self.sensor_list.append(sensor_readline.decode('utf-8')[self.sensor_data_max_len:-2])
			if buffer_clear:
				self.sensor_data = self.sensor_list.copy()
				self.sensor_list.clear()
				self.sensor_data_ser.reset_input_buffer()
		except Exception as e:
			print(f"[base_ctrl.read_sensor_data] error: {e}")

	def parse_lidar_frame(self, data):
		# header = data[0]
		# verlen = data[1]
		# speed  = data[3] << 8 | data[2]
		start_angle = (data[5] << 8 | data[4]) * 0.01
		# print(start)
		# end_angle = (data[43] << 8 | data[42]) * 0.01
		for i in range(0, self.ANGLE_PER_FRAME):
			offset = 6 + i * 3
			distance = data[offset+1] << 8 | data[offset]
			confidence = data[offset+2]
			# lidar_angles.append(np.radians(start_angle + i * 0.167))
			self.lidar_angles.append(np.radians(start_angle + i * 0.83333 + 180))
			# lidar_angles.append(np.radians(start_angle + end_angle))
			self.lidar_distances.append(distance)
		# end_angle = (data[43] << 8 | data[42]) * 0.01
		# timestamp = data[45] << 8 | data[44]
		# crc = data[46]
		return start_angle

	def lidar_data_recv(self):
		"""Pump the lidar stream for up to ~100 ms and publish whatever is new.

		The wire from this kit is marginal, so bytes frequently arrive corrupted;
		the old reader blocked until a perfect 360-degree wrap and could spin for
		many seconds on garbage (radar "randomly" stops and never restarts).  This
		scanner instead:
		  - scans a rolling buffer for 0x54 0x2C frame headers (self-resyncing),
		  - validates each frame (FSYNC + angle ordering + plausibility) and
		    drops corrupt ones,
		  - stamps every parsed point into 1-degree occupancy bins,
		  - publishes the last partial scan after 2.5 s without a clean wrap so
		    the UI keeps moving on a degraded wire.
		Returns quickly; call in a loop from the reader thread.
		"""
		if self.lidar_ser is None:
			return
		try:
			t_now = time.time()
			# Rate window first, so a disconnected port still decays to zero
			# (the reader loop calls this every ~10 ms regardless).
			if t_now - self._rate_stamp >= 2.0:
				dt = t_now - self._rate_stamp
				self.rx_bps = self._rate_bytes / dt
				self.frames_per_s = self._rate_frames / dt
				self._rate_bytes = 0
				self._rate_frames = 0
				self._rate_stamp = t_now
			# Pull whatever arrived recently into the rolling buffer.
			if self.lidar_ser.in_waiting > 0:
				chunk = self.lidar_ser.read(min(self.lidar_ser.in_waiting, 8192))
				self._lbuf.extend(chunk)
				self._rate_bytes += len(chunk)
				if len(self._lbuf) > 65536:
					del self._lbuf[:16384]
				self._last_rx = t_now
			elif t_now - self._last_rx > 2.0 and self._lbuf:
				# Port went silent mid-frame: drop partial bytes so the next
				# real packet is not mis-aligned by stale leading garbage.
				self._lbuf.clear()

			# Harvest every complete valid frame currently in the buffer.
			consume = 0
			while True:
				i = self._lbuf.find(b'\x54\x2C', consume)
				if i < 0 or len(self._lbuf) - i < 47:
					break
				frame = bytes(self._lbuf[i:i+47])
				if not self._frame_valid(frame):
					consume = i + 1          # false header - resync one byte on
					continue
				start_angle = self.parse_lidar_frame(list(frame))
				self._stamp_bins(frame)
				self._rate_frames += 1
				consume = i + 47
				# Wrap detected: start angle went backwards -> full revolution.
				if self.last_start_angle > start_angle:
					self.lidar_angles_show = self.lidar_angles.copy()
					self.lidar_distances_show = self.lidar_distances.copy()
					self.lidar_scan_time = t_now
					self.lidar_angles.clear()
					self.lidar_distances.clear()
				self.last_start_angle = start_angle
			if consume:
				del self._lbuf[:consume]

			# Degraded wire: no clean wrap for 2.5 s -> publish what we have so
			# the radar keeps updating instead of freezing on stale data.
			if self.lidar_angles and t_now - self.lidar_scan_time > 2.5:
				self.lidar_angles_show = self.lidar_angles.copy()
				self.lidar_distances_show = self.lidar_distances.copy()
				self.lidar_scan_time = t_now
				self.lidar_angles.clear()
				self.lidar_distances.clear()
		except Exception as e:
			print(f"[base_ctrl.lidar_data_recv] error: {e}")
			try:
				self.lidar_ser.close()
			except Exception:
				pass
			self.lidar_ser = None   # reader loop in app.py reconnects

	def _frame_valid(self, f):
		"""Sanity-check one 47-byte STL-19P packet; rejects wire-corrupted frames."""
		if f[0] != 0x54 or f[1] != 0x2C:
			return False
		start_angle = (f[5] << 8 | f[4]) * 0.01
		end_angle = (f[43] << 8 | f[42]) * 0.01
		if start_angle > 360.0 or end_angle > 360.0:
			return False
		# End must not lag start by more than the packet's angular span
		# (12 points x <=0.72 deg nominal, allow generous slop for speed change).
		if (end_angle - start_angle) % 360.0 > 14.4:
			return False
		# Sample count in verlen low nibble must be 12 for this format.
		if (f[1] & 0x0F) != 12:
			return False
		return True

	def _stamp_bins(self, f):
		"""Write each of the packet's 12 samples into the 1-degree occupancy bins."""
		start_angle = (f[5] << 8 | f[4]) * 0.01
		now = time.time()
		for k in range(12):
			off = 6 + k * 3
			dist = f[off] | (f[off + 1] << 8)
			if dist == 0:
				continue
			ang = int((start_angle + k * 0.83333 + 180.0) % 360)
			old_d, old_t = self.lidar_bins[ang]
			if now - old_t > 3.0 or dist < old_d or old_d == 0.0:
				# Fresh cell, or closer reading wins (obstacle safety).
				self.lidar_bins[ang] = (float(dist), now)


class BaseController:

	def __init__(self, uart_dev_set, buad_set):
		self.ser = serial.Serial(uart_dev_set, buad_set, timeout=1)
		self.rl = ReadLine(self.ser)
		self.command_queue = queue.Queue()
		self.command_thread = threading.Thread(target=self.process_commands, daemon=True)
		self.command_thread.start()

		self.base_light_status = 0
		self.head_light_status = 0

		self.data_buffer = None
		self.base_data = None

		self.use_lidar = f['base_config']['use_lidar']
		self.extra_sensor = f['base_config']['extra_sensor']
		

	def feedback_data(self):
		try:
			while self.rl.s.in_waiting > 0:
				self.data_buffer = json.loads(self.rl.readline().decode('utf-8'))
				if 'T' in self.data_buffer:
					self.base_data = self.data_buffer
					self.data_buffer = None
					if self.base_data["T"] == 1003:
						print(self.base_data)
						return self.base_data
			self.rl.clear_buffer()
			self.data_buffer = json.loads(self.rl.readline().decode('utf-8'))
			self.base_data = self.data_buffer
			return self.base_data
		except Exception as e:
			self.rl.clear_buffer()
			print(f"[base_ctrl.feedback_data] error: {e}")


	def on_data_received(self):
		self.ser.reset_input_buffer()
		data_read = json.loads(self.rl.readline().decode('utf-8'))
		return data_read


	def send_command(self, data):
		self.command_queue.put(data)


	def process_commands(self):
		while True:
			data = self.command_queue.get()
			self.ser.write((json.dumps(data) + '\n').encode("utf-8"))


	def base_json_ctrl(self, input_json):
		self.send_command(input_json)


	def gimbal_emergency_stop(self):
		data = {"T":0}
		self.send_command(data)


	def base_speed_ctrl(self, input_left, input_right):
		data = {"T":1,"L":input_left,"R":input_right}
		self.send_command(data)


	def gimbal_ctrl(self, input_x, input_y, input_speed, input_acceleration):
		data = {"T":133,"X":input_x,"Y":input_y,"SPD":input_speed,"ACC":input_acceleration}
		self.send_command(data)


	def gimbal_base_ctrl(self, input_x, input_y, input_speed):
		data = {"T":141,"X":input_x,"Y":input_y,"SPD":input_speed}
		self.send_command(data)


	def base_oled(self, input_line, input_text):
		data = {"T":3,"lineNum":input_line,"Text":input_text}
		self.send_command(data)


	def base_default_oled(self):
		data = {"T":-3}
		self.send_command(data)


	def bus_servo_id_set(self, old_id, new_id):
		# data = {"T":54,"old":old_id,"new":new_id}
		data = {"T":f['cmd_config']['cmd_set_servo_id'],"raw":old_id,"new":new_id}
		self.send_command(data)


	def bus_servo_torque_lock(self, input_id, input_status):
		# data = {"T":55,"id":input_id,"status":input_status}
		data = {"T":f['cmd_config']['cmd_servo_torque'],"id":input_id,"cmd":input_status}
		self.send_command(data)


	def bus_servo_mid_set(self, input_id):
		# data = {"T":58,"id":input_id}
		data = {"T":f['cmd_config']['cmd_set_servo_mid'],"id":input_id}
		self.send_command(data)


	def lights_ctrl(self, pwmA, pwmB):
		data = {"T":132,"IO4":pwmA,"IO5":pwmB}
		self.send_command(data)
		self.base_light_status = pwmA
		self.head_light_status = pwmB


	def base_lights_ctrl(self):
		if self.base_light_status != 0:
			self.base_light_status = 0
		else:
			self.base_light_status = 255
		self.lights_ctrl(self.base_light_status, self.head_light_status)

	def gimbal_dev_close(self):
		self.ser.close()

	def breath_light(self, input_time):
		breath_start_time = time.time()
		while time.time() - breath_start_time < input_time:
			for i in range(0, 128, 10):
				self.lights_ctrl(i, 128-i)
				time.sleep(0.1)
			for i in range(0, 128, 10):
				self.lights_ctrl(128-i, i)
				time.sleep(0.1)
		self.lights_ctrl(0, 0)


if __name__ == '__main__':
	import time

	gimbal = GimbalController('/dev/serial0', 115200)
	gimbal.gimbal_lights_ctrl(255, 0)

	while True:
		try:
			gimbal.gimbal_ctrl(-90, 0, 0, 0)
			time.sleep(2)
			gimbal.gimbal_ctrl(90, 60, 0, 0)
			time.sleep(2)
		except:
			pass

	gimbal.gimbal_dev_close()
