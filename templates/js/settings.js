const socketCtrl = io('http://' + location.host + '/ctrl');

const servoCmd = {
  s_panid: null,
  release: null,
  set_mid: null,
  s_tilid: null,
};

let lastTimeCmdSend = Date.now();
let lastArgsCmdSend;

function cmdSend(inputCmd, inputMode) {
  if (inputCmd == null) {
    return;
  }
  const now = Date.now();
  if (!lastArgsCmdSend || inputCmd != lastArgsCmdSend || now - lastTimeCmdSend >= 10) {
    socketCtrl.send(JSON.stringify({
      cmd: inputCmd,
      mode: inputMode,
    }));
    lastArgsCmdSend = inputCmd;
    lastTimeCmdSend = now;
  }
}

function confirmSetPanID() {
  if (confirm("Make sure that you have already DISCONNECT the wire of the Tilt Servo")) {
    cmdSend(servoCmd.s_panid, 0);
  }
}

function confirmRelease() {
  if (confirm("You will unlock the torque lock, then you can manually adjust the angle of the two servos.")) {
    cmdSend(servoCmd.release, 0);
  }
}

function confirmMiddleSet() {
  if (confirm("Set the current position as the middle position.")) {
    cmdSend(servoCmd.set_mid, 0);
  }
}

function confirmSetTiltID() {
  if (confirm("If you didn't disconnect the Tilt Servo in step 1, then both servo IDs will be set to 2 after you click the [Set Pan ID] button. Only in this case, you need to click [Set Tilt ID] to restore both servo IDs to 1, then repeat the entire setup process!")) {
    cmdSend(servoCmd.s_tilid, 0);
  }
}

window.confirmSetPanID = confirmSetPanID;
window.confirmRelease = confirmRelease;
window.confirmMiddleSet = confirmMiddleSet;
window.confirmSetTiltID = confirmSetTiltID;

function applyModuleVisibility(moduleType) {
  const setup = document.getElementById("pt_setup");
  const notice = document.getElementById("pt_only_notice");
  const isPanTilt = moduleType === 2;
  if (setup) {
    setup.classList.toggle("hidden", !isPanTilt);
  }
  if (notice) {
    notice.classList.toggle("hidden", isPanTilt);
  }
}

fetch("/config")
  .then((response) => response.text())
  .then((yamlText) => {
    const yamlObject = jsyaml.load(yamlText);
    servoCmd.s_panid = yamlObject.code.s_panid;
    servoCmd.release = yamlObject.code.release;
    servoCmd.set_mid = yamlObject.code.set_mid;
    servoCmd.s_tilid = yamlObject.code.s_tilid;
    applyModuleVisibility(yamlObject.base_config.module_type);
  })
  .catch((error) => {
    console.error("Error fetching YAML file:", error);
  });
