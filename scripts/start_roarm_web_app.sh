#!/bin/bash
ROARM_DIR="${HOME}/roarm_web_app"
if [ ! -d "$ROARM_DIR" ] || [ ! -f "$ROARM_DIR/package.json" ]; then
    echo "roarm_web_app is not installed at $ROARM_DIR" >&2
    echo "Install it first (see ugv_rpi README Quick Install), then start this service." >&2
    exit 1
fi
cd "$ROARM_DIR" || exit 1

export PATH=/usr/bin:/bin:/usr/local/bin:$PATH
export NODE_ENV=production

echo "Node: $(which node)" >> roarm_web_app.log 2>&1
echo "NPM: $(which npm)" >> roarm_web_app.log 2>&1

# npm install >> roarm_web_app.log 2>&1

# build + start
# npm run build >> roarm_web_app.log 2>&1
npm run start >> roarm_web_app.log 2>&1
