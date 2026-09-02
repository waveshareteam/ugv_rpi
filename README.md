![GitHub top language](https://img.shields.io/github/languages/top/waveshareteam/ugv_rpi)
![GitHub language count](https://img.shields.io/github/languages/count/waveshareteam/ugv_rpi)
![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/waveshareteam/ugv_rpi)
![GitHub repo size](https://img.shields.io/github/repo-size/waveshareteam/ugv_rpi)
![GitHub](https://img.shields.io/github/license/waveshareteam/ugv_rpi)
![GitHub last commit (branch)](https://img.shields.io/github/last-commit/waveshareteam/ugv_rpi/refactor%2Fdebian12-2025.10.01-py3.11)


# Waveshare UGV Robots
This is a Raspberry Pi example for the [Waveshare](https://www.waveshare.com/) UGV robots: **WAVE ROVER**, **UGV Rover**, **UGV Beast**, **RaspRover**, **UGV01**, **UGV02**.  

![](./images/UGV-Rover-details-23.jpg)

## Basic Description
The Waveshare UGV robots utilize both an upper computer and a lower computer. This repository contains the program running on the upper computer, which is typically a Raspberry Pi in this setup.  

The program running on the lower computer is either named [ugv_base_ros](https://github.com/effectsmachine/ugv_base_ros.git) or [ugv_base_general](https://github.com/effectsmachine/ugv_base_general.git) depending on the type of robot driver being used.  

The upper computer communicates with the lower computer (the robot's driver based on ESP32) by sending JSON commands via GPIO UART. The host controller, which employs a Raspberry Pi, handles AI vision and strategy planning, while the sub-controller, utilizing an ESP32, manages motion control and sensor data processing. This setup ensures efficient collaboration and enhanced performance.

## Features
- Real-time video based on WebRTC
- Interactive tutorial based on JupyterLab
- Pan-tilt camera control
- Robotic arm control
- Cross-platform web application base on Flask
- Auto targeting (OpenCV)
- Object Recognition (OpenCV)
- Gesture Recognition (MediaPipe)
- Face detection (OpenCV & MediaPipe)
- Motion detection (OpenCV)
- Line tracking base on vision (OpenCV)
- Color Recognition (OpenCV)
- Multi-threaded CV processing
- Audio interactive
- Shortcut key control
- Photo taking
- Video Recording

## Quick Install
You need to install a Raspberry Pi on your robot if you are using **WAVE ROVER**, **UGV01** or **UGV02**.  

This app is already installed on the SD card of **UGV Rover**, **UGV Beast** and **RaspRover**.  

To **upgrade** an existing upper-computer install, or to **install** this program on a fresh Raspberry Pi OS, follow **Quick Install** below. Product wiki (host-computer notes): [UGV Rover](https://www.waveshare.com/wiki/UGV-Rover), [UGV01](https://www.waveshare.com/wiki/UGV01), [UGV02](https://www.waveshare.com/wiki/UGV02).


Run the steps **in order**. Always `cd` with a `~/...` path (not a relative `ugv_rpi/`). Clone the repo to **`~/ugv_rpi`** — `setup.sh` / `autorun.sh` / systemd services all use that location. **RoArm 3D preview is optional** (RoArm-M2 / M3 only); skip that section unless you need it.

### 1. Clone ugv_rpi

    cd ~
    git clone -b refactor/debian12-2025.10.01-py3.11 https://github.com/waveshareteam/ugv_rpi.git
    cd ~/ugv_rpi
    sudo chmod +x controllers/Mediamtx/mediamtx

### 2. Run setup.sh (from scripts/)

`setup.sh` lives in `scripts/` and must be started with **sudo**. It always installs into `~/ugv_rpi` (venv, `requirements.txt`, `asound.conf`), even if your shell was elsewhere. Still run it from `scripts/` as below.

    cd ~/ugv_rpi/scripts
    sudo chmod +x setup.sh autorun.sh start_jupyter.sh start_roarm_web_app.sh
    sudo ./setup.sh

This takes a while. It also installs `git-lfs`. Then pull the TTS model from the **repo root** (not from `scripts/`):

    cd ~/ugv_rpi
    git lfs pull

### Optional: RoArm 3D preview (skip unless you use a robotic arm)

Only for **RoArm-M2** / **RoArm-M3**. Chassis-only and Camera PT robots can skip this. If you want the 3D preview, do it **before** `autorun.sh` (step 3), then answer `y` when asked. You can also install it later and run `./autorun.sh` again.

It is a separate Node.js app. Clone it to **`~/roarm_web_app`** (not inside `ugv_rpi`). `autorun.sh` only enables the user service.

    cd ~
    git clone -b ugv_roarm https://github.com/waveshareteam/roarm_web_app.git
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - && sudo apt-get install -y nodejs
    cd ~/roarm_web_app
    npm install --legacy-peer-deps
    npm run build

### 3. Autorun (from scripts/, without sudo)

    cd ~/ugv_rpi/scripts
    ./autorun.sh

`autorun.sh` will ask whether to enable the **optional** RoArm 3D preview service. Answer `y` only if you installed it in the optional section above. If `~/roarm_web_app` is not installed, it skips that service; the rest of ugv_rpi still starts.

### 4. AccessPopup (from AccessPopup/, with sudo)

`installconfig.sh` copies `./accesspopup` from the **current** directory, so you must be in `AccessPopup/` (not `scripts/`).

    cd ~/ugv_rpi/AccessPopup
    sudo chmod +x installconfig.sh
    sudo ./installconfig.sh

In the menu:

    1  Install AccessPopup
    (press any key)
    8  Additional Menu
    1  Web Interface — enable & disable switch  (AccessPopup web UI on port 8052)
    (press any key)
    5  Back to the Main menu
    9  Exit

### 5. inotify limit, then reboot

    echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p
    sudo reboot

After powering on the robot, the Raspberry Pi will automatically establish a hotspot, and the LED screen will display a series of system initialization messages:  

![](./images/RaspRover-LED-screen.png)
- The first line `E` displays the IP address of the Ethernet port, which allows remote access to the Raspberry Pi. If it shows No Ethernet, it indicates that the Raspberry Pi is not connected to an Ethernet cable.
- The second line `W` indicates the robot's wireless mode. In Access Point (AP) mode, the robot automatically sets up a hotspot with the default IP address `192.168.50.5`. In Station (STA) mode, the Raspberry Pi connects to a known WiFi network and displays the IP address for remote access.
- The third line `F/J` specifies the Ethernet port numbers. Port `5000` provides access to the robot control Web UI, while port `8888` grants access to the JupyterLab interface.
- The fourth line `STA` indicates that the WiFi is in Station (STA) mode. The time value represents the duration of robot usage. The dBm value indicates the signal strength RSSI in STA mode.  


You can access the robot web app using a mobile phone or PC. Simply open your browser and enter `[IP]:5000` (for example, `192.168.10.50:5000`) in the URL bar to control the robot.  

For how to use the control page (drive, camera, CV, keyboard, and gamepad), see [Web UI](docs/web_ui.md). A USB gamepad can be plugged into the **PC** (browser) or into the **Raspberry Pi** (onboard `joy_ctrl`); do not use both at once. The arm 3D preview (**RoArm View**, port **3000**) is **optional** — only for RoArm-M2 / RoArm-M3; see **Optional: RoArm 3D preview** above. AccessPopup WiFi helper web UI is on port **8052** after you install it from `installconfig.sh` menu **8 → 1**.  

To access JupyterLab, use `[IP]:8888` (for example, `192.168.10.50:8888`).  

If the robot is not connected to a known WiFi network, it will automatically set up a hotspot named "`AccessPopup`" with the password `1234567890`. You can then use a mobile phone or PC to connect to this hotspot. Once connected, open your browser and enter `192.168.50.5:5000` in the URL bar to control the robot.  

To ensure compatibility with various types of robots running on Raspberry Pi, we utilize a config.yaml file to specify the particular robot being used. After the Web UI is open (`http://<robot-ip>:5000`), type this in **Enter Command** and click **Send**, then reload the page:

    s 22

In this command, the `s` directive denotes a robot-type setting. The first digit, `2`, signifies that the robot is a `UGV Rover` (also **WAVE ROVER** and **UGV02**), with `1` representing `RaspRover` and `3` indicating `UGV Beast` (also **UGV01**). The second digit, also `2`, specifies the module as `Camera PT`, where `0` denotes `Nothing` , `1` signifies `RoArm-M2`，`3` signifies `RoArm-M3`. `s XY` does not set the gripper; `gripper_type` in `config.yaml` only switches the RoArm 3D preview (`0` = `roarm_m2`, otherwise `roarm_m2_ga`). See [Web UI](docs/web_ui.md).  

### v4l2.py error
If the program fails to run and encounters errors related to v4l2.py during runtime, you need to delete v4l2.py from both the Python virtual environment and the user environment. This will allow the program to automatically use the system-wide v4l2.py.  

    cd ~/ugv_rpi
    sudo rm ugv-env/lib/python3.11/site-packages/v4l2.py
    sudo rm ~/.local/lib/python3.11/site-packages/v4l2.py  

Now you can restart the main program app.py.

# License
ugv_rpi for the Raspberry Pi: an open source robotics platform for the Raspberry Pi.
Copyright (C) 2026 [Waveshare](https://www.waveshare.com/)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/gpl-3.0.txt>.
