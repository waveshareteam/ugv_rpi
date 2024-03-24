AccessPopup automated Access Point script.
Copyright RaspberryConnect.com

Website Guide at
https://www.raspberryconnect.com/projects/65-raspberrypi-hotspot-accesspoints/203-automated-switching-accesspoint-wifi-network


Activate an easy Automated WiFi AccessPoint or connect to a local WiFi Network for Raspberry Pi OS Bookworm. The AP is automatically created when you are not in range of a known WiFi network. Useful for both headerless or desktop setups.  

With the Raspberry Pi being so portable it is always useful to have a wifi connection. When the wifi signal has been lost due to a weak signal, it can be a bit of a nightmare trying to get access to the Pi without a screen.

The script in this Article will monitor the wifi connection and make sure you are connected to a known Wifi network when the signal is good or it will create a WiFi access point, so you will always have a wifi connection available.  It will also allow you to flip to an Access Point with a simple command and back to a WiFi network on demand.


The Access Point will allow a direct Wifi connection to the Pi from a Phone, Tablet, Laptop for use with ssh, VNC desktop sharing, a local web server, etc.

Every 2 minutes the AccessPopup script will check the local wifi network signals. If a known one comes back into range, then a connection is made to the wifi network and the Access Point is stopped.

This is useful for Devices that may be running sensors, cameras or other monitoring software in your Garden, Greenhouse, Shed or Garage that may be where the WiFi signal is weak. You will always be able to get a connection over wifi and is ideal for headerless setups. 

This is also useful for any setups where the Pi is required to go in and out of wifi range.
Compatability:
requires Raspberry PiOS 12 Bookworm or derivative using Network Manager.
Also works with Ubuntu 23.10 Raspberry Pi Image.
This will NOT work on PiOS 11 Bullseye or 10 Bullseye or older as they do not use Network Manager

A similar script is available for these called AutoHotspot.
This is available at
https://www.raspberryconnect.com/projects/65-raspberrypi-hotspot-accesspoints/183-raspberry-pi-automatic-hotspot-and-static-hotspot-installer

Installation and Use:
Installation:
download the archive file with
curl "https://www.raspberryconnect.com/images/scripts/AccessPopup.tar.gz" -o AccessPopup.tar.gz

unarchive with
tar -xvzf ./AccessPopup.tar.gz

change to the AccessPopup folder
cd AccessPopup

Run the Installer script
sudo ./installconfig.sh

The options below will be presented. Use option 1 to install the AccessPopup scripts.
This will automatically start monitoring the wifi connection every 2 minutes. It will also check the wifi at startup and then at every 2 minute intervals.

Setting a Constant Access Point:
Sometimes it is useful to be able to use the AccessPoint even though the Pi is in range of a known WiFi network.
This can be done by opening a terminal window and entering the command:
sudo accesspopup -a

to go back to normal use, just run the script without the -a argument.
sudo accesspopup

alternately use option 4 "Live Switch..." on this installer script.

Menu Options:
1 = Install AccessPopup Script
Installs the AccessPopup script and starts the 2 minute checks

2 = Change the Access Points SSID or Password
The access points wifi name (ssid) is AccessPopup and the password is 1234567890.
Use this option to change either or both. At least change the terrible password.

3 = Change the Access Points IP Address
The Access Points IP address is 192.168.50.5. Use this option to choose a new IP address, based on 10.0.#.# or 192.168.#.#

4 = Live Switch between: Network WiFi <> Access Point
Switch on demand. Set the Pi to an Access Point until the next reboot or switch back to a known WiFi Network in range.

5 = Setup a New WiFi Network or change the password to an existing Wifi Network
Scan for local WiFi networks and connect to a new one or change the password to an existing

6 = Change Hostname
Change the system Hostname, so a connection can be made by name instead of an IP

7 = Uninstall AccessPopup
Uninstall the AccessPopup script and return the PI to its default wifi setup.

8 = Run AccessPopup now. It will decide between a suitable WiFi network or AP

9 = Exit

 

Using the Access Point:
When the Access Point has been activated, the SSID AccessPopup will be broadcast. Using a wifi device, scan for new wifi devices in the area, and select AccessPopup.

You will be prompted to enter the password.

If you have not already changed it, the password will be 1234567890. Don't use the password that is used to log into the Raspberry Pi.

The connection to the Access Point will be made.

SSH, VNC, Web Server
If you are using SSH, VNC or accessing a web server of the RPi then use:

ssh: username@192.168.50.5   so if your user is called  pi, then use
ssh pi@192.168.50.5

VNC remote desktop: enter the server as 192.168.50.5 

Web server: if there is a web server running on the PI, it can be used by entering http://192.168.50.5/ into a web browser.

The Hostname of the device can also be used in place of the IP address for any of the above options.

 

Using AccessPopup in a terminal window: 
 AccessPopup is set to run automatically every 2 minutes but it can be run manually to generate the Access Point.

In a terminal window enter:
sudo accesspopup -a

The access point will be activated and the timer will be stopped so it doesn't try to connect to a Wifi network again. 

To re-connect to a nearby known wifi network, either reboot or run the script without -a

sudo accesspopup

This will attempt to connect to a known local wifi network and re-activate the 2 minute timer.

If a wifi network connection can't be made it will activate the AccessPoint again.

 

Using Network Manager from The Desktop:
Alternately to using the AccesPopup script, the Network Manager interface can be used to make your own Access Point. This will be used if no know wifi network is found when the Pi is started. If a known Wifi Network is then in range, Network Manager will keep the Access Point going until it is manually stopped in the WiFi menu or the Pi rebooted. If this suits your needs and you are always using the desktop environment then the standard setup may be useful.

To create an Access Point in Network Manager use the "Create Wireles Hotspot" menu option

As standard Network Manager will use a previously setup Access Point if no known Wifi network is in range. Then when a known Wifi network comes into range you will need to manually stop the Access Point and select the desired Network.

So the AccessPopup script is not required if you are only using a Desktop environment.

AccessPopup is most useful for setups without a desktop (headerless) or where the wifi signal is inconsistent as the wifi connection will be remade every time it is strong again. 
If you are using the AccessPopup script and Network Manager desktop menu, then AccessPopup will switch from any Access Point back to a known Wifi network every 2 minutes unless the following command is used in a terminal screen window.
sudo accesspopup -a

This will also stop the timer and the script from running.

Using the "Advanced Options" and "Edit Connections" the AccessPoint settings for the profile AccessPopup can be changed, by selcting the profile and then the cog icon.

The AccessPopup profile will be removed from the Network Manager menu if option "7 Uninstall" of this script is used. Unless the profile name has been changed.

On re-installing AccessPopup the default options will be setup. Any other AccessPoint that has been setup, will be ignored in favour of the AccessPopup one.



Considerations:
The Access Point disconnects every 2 minutes.

If a WiFi network is setup but the password is not correct, then the connection will fail. Once there is an attempt to connect to a WiFi network, it is added to the list of known networks by Network Manager.
When an Access Point is active, every 2 minutes it will be deactivated to connect to the bad WiFi network when it is in range. This will disrupt any connections to the Access Point.
The Access Point will be re-enabled once the connection to the Wifi network has failed.
If you experience this, then correct the password with option 5 or the Desktop interface. Otherwise delete the bad Wifi network entry.

Ethernet connection to the Pi

If an Ethernet cable is connected to the Pi and the Access Point is available, any device on the access Point can ssh/vnc/ping etc the other devices also connected to the access point and the network the Ethernet is connected to. This includes the internet, if it is available.
No device on the Ethernet's network can connect ssh/vnc/ping etc to the devices connected to the access point. The Ethernet network can access the Pi, as it is on both networks.

 Using a Second WiFi Device

When a second Wifi device is setup such as a USB Wifi dongle, no device connected to the access point can ssh/vnc/ping etc the network that the second Wifi device is connected to. Devices connected to the Access Point can only access the internet or other networks through a connected Ethernet cable.
To do this through a second wifi device requires additional configuration.


