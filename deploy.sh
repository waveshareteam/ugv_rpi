#!/bin/bash
# One-connection deploy of the repaired web UI to the robot.
# Usage: ROBOT_PASS='your-password' bash deploy.sh
# Self-sufficient: creates its own SSH askpass helper if missing.
if [ -z "$ROBOT_PASS" ]; then
  echo "Set ROBOT_PASS env var first, e.g.: ROBOT_PASS='...' bash deploy.sh" >&2
  exit 1
fi
if [ ! -x /tmp/ap.sh ]; then
  printf '#!/bin/sh\necho "%s"\n' "$ROBOT_PASS" > /tmp/ap.sh && chmod +x /tmp/ap.sh
fi
export SSH_ASKPASS=/tmp/ap.sh SSH_ASKPASS_REQUIRE=force DISPLAY=:
H=ws@172.30.136.241
for i in $(seq 1 40); do
  if ping -n 1 -w 1500 172.30.136.241 > /dev/null 2>&1; then
    echo "link up (poll $i) - deploying immediately"
    tar czf - app.py templates/index.html templates/conn.js | \
    ssh -o ConnectTimeout=25 -o ServerAliveInterval=5 $H "cd ~/ugv_rpi && cp app.py backup_20260908/app.py.pass4 && cp templates/index.html backup_20260908/index.html.pass4 && tar xzf - && kill -9 \$(pgrep -f 'ugv_rpi/ap[p].py') 2>/dev/null; echo TAR_DEPLOY_OK" && { echo "DEPLOY COMPLETE - app relaunches via cron/autorun"; break; }
  fi
  sleep 5
done
