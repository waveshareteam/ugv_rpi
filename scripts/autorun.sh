#!/bin/bash
if [ -n "$SUDO_USER" ] || [ -n "$SUDO_UID" ]; then
    echo "This script was executed with sudo."
    echo "Use './autorun.sh' instead of 'sudo ./autorun.sh'"
    exit 1
fi

USER_NAME=$(logname)
USER_HOME=$(eval echo "~$USER_NAME")
SYSTEMD_DIR="$USER_HOME/.config/systemd/user"

APP_PATH="$USER_HOME/ugv_rpi/app.py"
PYTHON_BIN="$USER_HOME/ugv_rpi/ugv-env/bin/python"

mkdir -p "$SYSTEMD_DIR"

APP_SERVICE="$SYSTEMD_DIR/ugv-app.service"
cat > "$APP_SERVICE" <<EOL
[Unit]
Description=UGV Python App
After=sound.target pipewire.service
Wants=pipewire.service

[Service]
ExecStart=/bin/bash -c "$USER_HOME/ugv_rpi/ugv-env/bin/python -u $USER_HOME/ugv_rpi/app.py >> $USER_HOME/ugv_rpi/ugv-app.log 2>&1"
Restart=always
Environment=XDG_RUNTIME_DIR=/run/user/%U
WorkingDirectory=$USER_HOME/ugv_rpi

[Install]
WantedBy=default.target
EOL

JUPYTER_SERVICE="$SYSTEMD_DIR/ugv-jupyter.service"
cat > "$JUPYTER_SERVICE" <<EOL
[Unit]
Description=UGV Jupyter Notebook

[Service]
ExecStart=/bin/bash -c "$USER_HOME/ugv_rpi/scripts/start_jupyter.sh >> $USER_HOME/ugv_rpi/ugv-jupyter.log 2>&1"
Restart=always
Environment=XDG_RUNTIME_DIR=/run/user/%U
WorkingDirectory=$USER_HOME

[Install]
WantedBy=default.target
EOL

systemctl --user daemon-reload
systemctl --user enable ugv-app.service
systemctl --user enable ugv-jupyter.service
sudo loginctl enable-linger $USER_NAME

export PATH=$HOME/.local/bin:$PATH
source "$USER_HOME/ugv_rpi/ugv-env/bin/activate"
CONFIG_FILE="$USER_HOME/.jupyter/jupyter_notebook_config.py"
if [ ! -f "$CONFIG_FILE" ]; then
    jupyter notebook --generate-config
fi

grep -q "c.NotebookApp.token" "$CONFIG_FILE" || echo "c.NotebookApp.token = ''" >> "$CONFIG_FILE"
grep -q "c.NotebookApp.password" "$CONFIG_FILE" || echo "c.NotebookApp.password = ''" >> "$CONFIG_FILE"

echo "Setup complete. You can start services with:"
echo "systemctl --user start ugv-app.service"
echo "systemctl --user start ugv-jupyter.service"
echo "Logs: journalctl --user -u ugv-app.service -f"
echo "      journalctl --user -u ugv-jupyter.service -f"

ROARM_DIR="$USER_HOME/roarm_web_app"
START_ROARM="$USER_HOME/ugv_rpi/scripts/start_roarm_web_app.sh"

if [ ! -d "$ROARM_DIR" ] || [ ! -f "$ROARM_DIR/package.json" ]; then
    echo "RoArm 3D preview is optional and is not installed at $ROARM_DIR. Skipping that service."
    echo "To add it later: clone branch ugv_roarm to ~/roarm_web_app, Node.js 20, npm install --legacy-peer-deps, npm run build,"
    echo "then re-run ./autorun.sh and answer y. See README: Optional: RoArm 3D preview."
elif [ ! -d "$ROARM_DIR/.next" ]; then
    echo "RoArm 3D preview is optional. $ROARM_DIR exists but has not been built. Skipping that service."
    echo "To enable it: cd $ROARM_DIR && npm install --legacy-peer-deps && npm run build"
    echo "Then re-run ./autorun.sh and answer y."
else
    read -p "Enable optional ROARM Web App service (3D preview)? [y/N]: " INSTALL_ROARM
    INSTALL_ROARM=${INSTALL_ROARM:-N}

    if [[ "$INSTALL_ROARM" =~ ^[Yy]$ ]]; then
        echo "Installing ROARM Web App service..."
        chmod +x "$START_ROARM"

        ROARM_SERVICE="$SYSTEMD_DIR/roarm_web_app.service"
        cat > "$ROARM_SERVICE" <<EOL
[Unit]
Description=ROARM Web App
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash -c "$START_ROARM >> $ROARM_DIR/roarm_web_app.log 2>&1"
WorkingDirectory=$ROARM_DIR
Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=500
#KillMode=process
Environment=NODE_ENV=production
Environment=PATH=/usr/bin:/bin:/usr/local/bin

[Install]
WantedBy=default.target
EOL

        systemctl --user daemon-reload
        systemctl --user enable roarm_web_app.service

        echo "ROARM Web App service installed and enabled."
        echo "You can start it with: systemctl --user start roarm_web_app.service"
    fi
fi