#!/bin/bash
[ -f ~/.bashrc ] && source ~/.bashrc
cd "$HOME/ugv_rpi" && source ugv-env/bin/activate && jupyter lab \
  --ip=0.0.0.0 --port=8888 --no-browser \
  --notebook-dir="$HOME/ugv_rpi" \
  --ServerApp.default_url=/lab/tree/tutorials \
  --FileContentsManager.preferred_dir=tutorials
