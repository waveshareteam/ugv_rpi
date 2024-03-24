import os, psutil, time
import subprocess, re, netifaces
import threading

curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)

class SystemInfo(threading.Thread):
    """docstring for SystemInfo"""
    def __init__(self):
        self.this_path = None

        self.pictures_size = 0
        self.videos_size = 0
        self.cpu_load = 0
        self.cpu_temp = 0
        self.ram = 0
        self.wifi_rssi = 0

        self.net_interface = "wlan0"
        self.wlan_ip = None
        self.eth0_ip = None
        self.wifi_mode = None

        self.update_interval = 2

        super(SystemInfo, self).__init__()
        self.__flag = threading.Event()
        self.__flag.clear()

    def get_folder_size(self, folder_path):
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                total_size += os.path.getsize(file_path)
        # Convert total_size to MB
        size_in_mb = total_size / (1024 * 1024)
        return round(size_in_mb,2)

    def update_folder_size(self):
        self.pictures_size = self.get_folder_size(self.this_path + '/templates/pictures')
        self.videos_size = self.get_folder_size(self.this_path + '/templates/videos')

    def update_folder(self, input_path):
        self.this_path = input_path
        threading.Thread(target=self.update_folder_size, daemon=True).start()

    def get_cpu_temperature(self):
        try:
            temperature_str = os.popen('vcgencmd measure_temp').readline()
            temperature = float(temperature_str.replace("temp=", "").replace("'C\n", ""))
            return temperature
        except Exception as e:
            print("Error reading CPU temperature:", str(e))
            return None

    def get_ip_address(self, interface):
        try:
            interface_info = netifaces.ifaddresses(interface)

            ipv4_info = interface_info.get(netifaces.AF_INET, [{}])
            return ipv4_info[0].get('addr')
        except ValueError:
            print(f"Interface {interface} not found.")
            return None
        except IndexError:
            print(f"No IPv4 address assigned to {interface}.")
            return None

    def get_wifi_mode(self):
        try:
            result = subprocess.check_output(['/sbin/iwconfig', 'wlan0'], encoding='utf-8')
            if "Mode:Master" in result or "Mode:AP" in result:
                return "AP"
            if "Mode:Managed" in result:
                return "STA"
        except subprocess.CalledProcessError as e:
            print(f"Error checking Wi-Fi mode: {e}")
            return None
        return None

    def get_signal_strength(self, interface):
        try:
            output = subprocess.check_output(["/sbin/iwconfig", interface]).decode("utf-8")
            signal_strength = re.search(r"Signal level=(-\d+)", output)
            if signal_strength:
                return int(signal_strength.group(1))
            return 0
        except FileNotFoundError:
            print("iwconfig command not found. Please ensure it's installed and in your PATH.")
            return -1
        except subprocess.CalledProcessError as e:
            print(f"Error executing iwconfig: {e}")
            return -1
        except Exception as e:
            print(f"An error occurred: {e}")
            return -1

    def change_net_interface(self, new_interface):
        self.net_interface = new_interface

    def pause(self):
        self.__flag.clear()

    def resume(self):
        self.__flag.set()

    def run(self):
        self.eth0_ip = self.get_ip_address('eth0')
        self.wlan_ip = self.get_ip_address(self.net_interface)
        self.wifi_mode = self.get_wifi_mode()
        self.wifi_rssi = self.get_signal_strength(self.net_interface)
        self.cpu_temp = self.get_cpu_temperature()
        self.ram = psutil.virtual_memory().percent
        self.cpu_load = psutil.cpu_percent(interval = self.update_interval)
        while True:
            self.cpu_temp = self.get_cpu_temperature()
            time.sleep(0.5)
            self.ram = psutil.virtual_memory().percent
            time.sleep(0.5)
            self.wifi_rssi = self.get_signal_strength(self.net_interface)
            time.sleep(0.5)
            self.wifi_mode = self.get_wifi_mode()
            time.sleep(0.5)
            self.wlan_ip = self.get_ip_address(self.net_interface)
            time.sleep(0.5)
            self.eth0_ip = self.get_ip_address('eth0')
            time.sleep(0.5)
            self.cpu_load = psutil.cpu_percent(interval = self.update_interval)
            self.__flag.wait()


if __name__ == "__main__":
    si = SystemInfo()
    si.update_folder(thisPath)
    si.start()
    si.resume()
    while True:
        print([si.pictures_size, si.videos_size, si.cpu_load, si.cpu_temp,
            si.ram, si.wifi_rssi, si.wifi_mode])
        time.sleep(1)