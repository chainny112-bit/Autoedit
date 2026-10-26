#!/usr/bin/env bash
# Start the AutoEdit web app on http://localhost:8000
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "ต้องติดตั้ง FFmpeg ก่อน (apt install ffmpeg / brew install ffmpeg)"; exit 1; }
python3 -c "import fastapi, uvicorn, cv2, pythainlp" 2>/dev/null || pip install -r requirements.txt
exec python3 app.py
