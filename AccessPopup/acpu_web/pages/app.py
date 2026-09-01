#!venv/bin/python3.11
#AccessPopup web files 16th April 2026
#Systemd Activation

#Copyright Graeme Richards. RaspberryConnect.com

import pathlib
from fastapi import FastAPI, Request, Form, status, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from i18n import get_lang, get_t, msg
from pydantic import BaseModel
import subprocess, os, tempfile, shutil

import socket
import threading
import json
from datetime import datetime
import time

app = FastAPI()

BASE_DIR = pathlib.Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(pathlib.Path(BASE_DIR, "templates")))

app.mount("/static", StaticFiles(directory="static"), name="static")


def render(request: Request, template: str, context: dict | None = None):
    lang = get_lang(request)
    ctx = {"request": request, "t": get_t(lang), "lang": lang}
    if context:
        ctx.update(context)
    return templates.TemplateResponse(template, ctx)


@app.get("/set_lang/{lang}")
async def set_lang(lang: str, request: Request):
    if lang not in ("en", "zh"):
        lang = "en"
    referer = request.headers.get("referer", "/")
    response = RedirectResponse(url=referer, status_code=303)
    response.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return response

script_path="/etc/"
scriptname="accesspopup.conf"

scan_result = None
myssids_in_scan = None
scan_running = False
wifi_dev = 'wlan0'
Comms = None

BACKEND_ADDR = ("localhost", 65432)
_backend_sock = None


class User(BaseModel):
   username:str
   password:str
   
class Wifi(BaseModel):
    wifi_ip:str
    hostname:str
    device:str

def get_nm_update():
    Comms.send_out("UPDT","")
    x = wait_for_msg()
    Comms.send_out("WIAC",wifi_dev)
    active_wifi = wait_for_msg()
    Comms.send_out("WIPL","")
    avail_profiles = wait_for_msg()
    Comms.send_out("LANP","")
    lan = wait_for_msg()
    Comms.send_out("APPL","")
    ap = wait_for_msg()
    Comms.send_out("HOST","")
    hostname = wait_for_msg()
    #print("Active_wifi is:", active_wifi)
    if active_wifi:
        try:
            wiip = active_wifi[0][5]
        except:
            wiip = ""
        wifi_act = [active_wifi[0][0],active_wifi[0][1],wiip]
    else:
        wifi_act = ["Not Available","",""]
        
       
    status = {
        "wifi": {"Connection":wifi_act[0], "Device":wifi_act[1], "wifiip":wifi_act[2].split("/")[0]},
        "profiles":avail_profiles,
        "hostname":hostname,
        "lan":lan,
        "ap_prof":ap
    }
    #print("Lan Returned:",lan)
    if not lan:
        status.update(lan1 = {"lan_device":"None","lan_active":"no"})
        status.update(lan2 = {"lan_device":"None","lan_active":"no"})
    else:
        if len(lan) > 0:
                if lan[0].get("conip"):
                    status.update(lan1 = {"lan_device":lan[0]["devname"], "lan_active":lan[0]["active"], "lan_ip":lan[0]["conip"].split("/")[0]})
                else:
                    status.update(lan1 = {"lan_device":lan[0]["devname"], "lan_active":lan[0]["active"],"lan_ip":""})
        else:
            status.update(lan1 = {"lan_device":"None","lan_active":"no"})
        if len(lan) > 1:
                if lan[1].get("conip"):
                    status.update(lan2 = {"lan_device":lan[1]["devname"], "lan_active":lan[1]["active"], "lan_ip":lan[1]["conip"].split("/")[0]})
                else:
                    status.update(lan2 = {"lan_device":lan[1]["devname"], "lan_active":lan[1]["active"],"lan_ip":""})
        else:
            status.update(lan2 = {"lan_device":"None","lan_active":"no"})
    return status

def get_wifidev(filepath= script_path + scriptname):
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("wdev0="):
                    # Remove wdev0= and surrounding quotes if present
                    value = line.split("=", 1)[1].strip().strip("'\"")
                    return value
    except FileNotFoundError:
        print(f"Error: File {filepath} not found. Please install AcessPopup")
    except Exception as e:
        print(f"An error occurred: {e}")
    quit()

def get_local_wifi():
    Comms.send_out("SCAN",wifi_dev)
    w = wait_for_msg()
    return w

def update_ap_profile(new_ssid,new_pwd):
    """Change AP details in Accesspopup"""
    file_p = script_path + scriptname
    if new_ssid or new_pwd:
        if new_ssid:
            Comms.send_out("APED",('ap_ssid=',new_ssid,file_p))
            w = wait_for_msg()
        if new_pwd:
            Comms.send_out("APED",('ap_pw=',new_pwd,file_p))
            w = wait_for_msg()
        Comms.send_out("DELP","AccessPopup")
        w = wait_for_msg()
    
@app.on_event("startup")
def startup_event():
    global Comms, wifi_dev
    try:
        wifi_dev = get_wifidev()
        Comms = Messaging()
        threading.Thread(target=client, daemon=True).start()
    except Exception as e:
        print(f"[FATAL] Startup failed: {e}", flush=True)
        os._exit(1)   #systemd restart
    
#Render Index Page
@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    return render(request, "index.html", {"context": get_nm_update()})

@app.get("/guide",response_class=HTMLResponse)
async def guide(request: Request):
    return render(request, "guide.html")


#page
@app.get("/ap_edit",response_class=HTMLResponse)
async def get_ap_edit(request: Request, message: str | None = None ):
    file_p = script_path + scriptname
    context = get_nm_update()
    Comms.send_out("APGT",file_p)
    x = wait_for_msg()
    lang = get_lang(request)
    if x != None and len(x) == 2:
            apssid,appwd = x
    else:
        apssid,appwd = msg(lang, "not_available"), msg(lang, "please_refresh")
    if message == None:
        messagen = ""
    elif message == "No Network Selected":
        messagen = msg(lang, "msg_no_network")
    else:
        messagen = message
    return render(request, "ap_edit.html", {
        "context": context,
        "messagen": messagen,
        "apssid": apssid,
        "appwd": appwd
    })

#Edit AP Profile
@app.post("/ap_edit", response_class=HTMLResponse)
async def post_ap_edit(request: Request, ap_ssid: str = Form(""), ap_pwd: str = Form("")):

    # Get current saved SSID/password
    file_p = script_path + scriptname
    context = get_nm_update()
    Comms.send_out("APGT", file_p)
    x = wait_for_msg()
    current_ssid, current_pwd = x

    # Replace blanks with current values for message + update
    new_ssid = ap_ssid if ap_ssid else current_ssid
    new_pwd = ap_pwd if ap_pwd else current_pwd

    lang = get_lang(request)
    message = ""
    if ap_ssid == "" and ap_pwd == "":
        message = msg(lang, "msg_nothing_entered")
    elif ap_pwd and len(ap_pwd) < 8:
        message = msg(lang, "msg_invalid_password")
    else:
        update_ap_profile(new_ssid, new_pwd)
        message = msg(lang, "msg_ap_updated", ssid=new_ssid, pwd=new_pwd)

    # Get the actual saved values after update (ensures placeholders are correct)
    Comms.send_out("APGT", file_p)
    x = wait_for_msg()
    apssid, appwd = x

    return render(request, "ap_edit.html", {
        "apssid": apssid,
        "appwd": appwd,
        "message": message,
        "context": context
    })

#Edit Existing NW Profile
@app.post("/ap_edit_details") #, response_class=HTMLResponse)
async def ap_edit_details(request: Request, edit_nw: str | None = Form(None), submit: str = Form(...)):
    if edit_nw is None:
        return RedirectResponse(url="/ap_edit?message=No+Network+Selected",status_code=303)

    if submit == "delete":
        return render(request, "ap_delete_confirm.html", {"selected_prof": edit_nw})
    if submit == "connect":
        Comms.send_out("NWSL",edit_nw )
        x = wait_for_msg()
        return render(request, "index.html", {"context": get_nm_update()})
        
    return render(request, "ap_edit_details.html", {
        "selected_prof": edit_nw,
        "message": ""
    })
    
@app.post("/ap_edit_pw", response_class=HTMLResponse)
async def ap_edit_pw(request: Request, newpass: str = Form(...), profile: str = Form(...)):
    #print("Profile selected is " + profile)

    lang = get_lang(request)
    if not newpass.strip():
        messagen = msg(lang, "msg_nothing_entered_short")
    else:
        if len(newpass.strip()) >= 8: 
            Comms.send_out("EDNW",(profile.strip(),newpass.strip()) )
            x = wait_for_msg()
            if x == 0:
                messagen = msg(lang, "msg_pw_updated", profile=profile.strip(), password=newpass.strip())
            else: 
                messagen = msg(lang, "msg_pw_update_fail", profile=profile.strip())
                Comms.send_out("GONW","none")
                x = wait_for_msg()
        else:
            messagen = msg(lang, "msg_pw_too_short")

    file_p = script_path + scriptname
    context = get_nm_update()
    Comms.send_out("APGT", file_p)
    x = wait_for_msg()
    apssid, appwd = x

    return render(request, "ap_edit.html", {
        "context": context,
        "messagen": messagen,
        "apssid": apssid,
        "appwd": appwd
    })

@app.post("/ap_delete", response_class=HTMLResponse)
async def ap_delete(request: Request, profile: str = Form(...), confirm: str = Form(...)):
    lang = get_lang(request)
    if confirm == "yes":
        Comms.send_out("DELP", profile)
        x = wait_for_msg()
        if x == 0:
            message = msg(lang, "msg_profile_deleted", profile=profile)
        else:
            message = msg(lang, "msg_profile_delete_fail", profile=profile)
    else:
        message = msg(lang, "msg_deletion_cancelled")

    file_p = script_path + scriptname
    context = get_nm_update()
    Comms.send_out("APGT", file_p)
    x = wait_for_msg()
    apssid, appwd = x

    return render(request, "ap_edit.html", {
        "context": context,
        "messagen": message,
        "apssid": apssid,
        "appwd": appwd
    })

#Setup a New Wifi NW
@app.get("/add_network",response_class=HTMLResponse)
async def add_network(request: Request):
    return render(request, "add_network.html", {"newwifi": "", "message": ""})
    
@app.post("/refresh_list", response_class=HTMLResponse)
async def refresh_nw_list(
    request: Request,
    refresh_list: str = Form(...),
    background_tasks: BackgroundTasks = None):

    lang = get_lang(request)
    scan_msg = ""
    if refresh_list == "1":
        if not scan_running:
            background_tasks.add_task(do_scan)
            scan_msg = msg(lang, "add_network_scanning")
        else:
            scan_msg = msg(lang, "msg_scan_in_progress")

    return render(request, "add_network.html", {
        "newwifi": [],
        "message": scan_msg
    })

@app.get("/scan_status")
async def scan_status(request: Request):
    """Poll scan progress (always returns JSON)."""
    lang = get_lang(request)
    t = get_t(lang)
    if scan_running:
        return JSONResponse({"status": "running", "scanning_text": t["add_network_scanning"]})

    if scan_result is not None:
        if "-95" in scan_result[0]:
            return JSONResponse({"status": "error", "redirect": "/manual_add"})
        else:
            return JSONResponse({
                "status": "done",
                "results": scan_result,
                "mywifi": myssids_in_scan,
                "nearby_title": t["add_network_nearby"],
                "add_selected": t["add_network_add_selected"],
                "saved_title": t["add_network_saved"],
            })

    return JSONResponse({"status": "idle"})

@app.get("/manual_add")
async def manual_add(request: Request):
    """Show manual add page if scan failed (-95)."""
    return render(request, "add_nw_manual.html")

@app.post("/add_network_manual", response_class=HTMLResponse)
async def add_network_manual(request: Request, new_nw_ssid: str = Form(...), new_nw_pass:str = Form(...)):
	lang = get_lang(request)
	if not new_nw_pass.strip() or not new_nw_ssid.strip():
		message = msg(lang, "msg_enter_ssid_pwd")
	else:
		if len(new_nw_pass.strip()) >=8:
			Comms.send_out("ADSL", ( new_nw_ssid.strip(),new_nw_pass.strip(),'AP') )
			x = wait_for_msg()
			if x == 0:
				message = msg(lang, "msg_profile_created", ssid=new_nw_ssid.strip())
			elif x == 1:
				message = msg(lang, "msg_connection_problem")
		else:
			message = msg(lang, "msg_pw_too_short")
			
	return render(request, "add_nw_manual.html", {"message": message})	
	
    
@app.post("/new_nw", response_class=HTMLResponse)
async def add_network_pw(request: Request, new_nw: str = Form(...)):   
    return render(request, "add_network_pw.html", {"message": "", "new_nw": new_nw})

@app.post("/add_network_pw", response_class=HTMLResponse)
async def add_network_pw(request: Request, new_nw_pass: str = Form(...), profile: str = Form(...)):
    #print("Profile selected is " + profile)
    lang = get_lang(request)
    if not new_nw_pass.strip():
        message = msg(lang, "msg_nothing_entered_short")
    else:
        if len(new_nw_pass.strip()) >= 8: 
            Comms.send_out("ADSL", ( profile,new_nw_pass.strip(),'') )
            x = wait_for_msg()
            if x == 0:
                message = msg(lang, "msg_connect_success", profile=profile)
            else: 
                message = msg(lang, "msg_connect_fail", profile=profile)
                Comms.send_out("GONW","none")
                x = wait_for_msg()              
        else:
            message = msg(lang, "msg_pw_too_short")
                
    return render(request, "add_network_pw.html", {"message": message, "new_nw": profile})

#Switch Buttons
@app.post('/', response_class=HTMLResponse)
def post_ap_switch(request: Request, switch: str = Form(...)):
    if switch == "to_ap":
        start_ap()
    elif switch == "to_nw":
        start_nw()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
def start_ap():
    Comms.send_out("GOAP","none")
    rec = wait_for_msg()
    if rec != None:
        print("AP Activated")
    
def start_nw():
    Comms.send_out("GONW","none")
    rec = wait_for_msg()
    if rec != None:
        print("NW Activated")
        
def do_scan():
    """Run wifi scan in background using Comms + wait_for_msg."""
    global scan_result, scan_running, myssids_in_scan
    scan_running = True
    try:
        Comms.send_out("SCAN", wifi_dev)
        s = wait_for_msg() or []
        Comms.send_out("WISS","none")
        w = wait_for_msg() or []
        scan_result = list(set(s) - set(w))
        myssids_in_scan = list(set(s) & set(w))
    finally:
        scan_running = False
        #print("Do Scan:",scan_result)

def wait_for_msg():
    t = time.time()
    while time.time() - t < 40: #check for messages up to 15 seconds
        msg = Comms.check_msg_in()
        if msg != None:
            #print("Msg Returned:",msg)
            return msg.get("args")
    return None
        
#Messaging
class Messaging:
    def __init__(self):
        self.msg_in = None
        self.msg_out = None
        
    def send_out(self,code,msg):
        d = {"code": code, "args": msg}
        m = self.__json_message(d).encode()
        self.msg_out = m

    def receive_in(self,msg):
        try:
            r = json.loads(msg)
            self.msg_in = r
        except json.JSONDecodeError:
                print("[Invalid JSON from server]")

    def __json_message(self,msg_text):
        return json.dumps(msg_text)

    def check_msg_in(self):
        x = None
        if self.msg_in != None:
            x = self.msg_in
            self.msg_in = None
        return x
        
    def check_msg_out(self):
        x = None
        if self.msg_out != None:
            x = self.msg_out
            self.msg_out = None
        return x

def receive_messages(sock):
    try:
        while True:
            data = sock.recv(1024)
            #print("After sock.recv")
            if not data:
                print("[Server disconnected]")
                break
            try:
                #print("Receive Try:")
                Comms.receive_in(data.decode())
            except:
                pass
    except (ConnectionResetError, OSError):
        print("[Receive error] Server may be down")


def client():
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(('127.0.0.1', 65432))
                print("[Client] Connected to server.")
                threading.Thread(target=receive_messages, args=(s,), daemon=True).start()

                while True:
                    msg = Comms.check_msg_out()
                    if msg:
                        s.sendall(msg)
                    time.sleep(0.02)

        except ConnectionRefusedError:
            print("[Backend] Not available, retrying...")
            time.sleep(1)

        except Exception as e:
            print(f"[FATAL] Backend client failed: {e}", flush=True)
            os._exit(1)   #systemd restart

def backend_send(msg: str) -> str:
    global _backend_sock

    while True:
        try:
            if _backend_sock is None:
                _backend_sock = socket.create_connection(BACKEND_ADDR, timeout=5)

            _backend_sock.sendall(msg.encode())
            return _backend_sock.recv(1024).decode()

        except (BrokenPipeError, ConnectionResetError, OSError):
            # backend crashed or restarted
            try:
                _backend_sock.close()
            except Exception:
                pass
            _backend_sock = None
            time.sleep(0.5)  # wait for systemd to restart backend            
    
