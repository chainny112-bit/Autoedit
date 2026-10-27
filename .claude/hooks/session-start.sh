#!/bin/bash
# Install AutoEdit's dependencies in Claude Code cloud sessions so dropped clips can be edited right away.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "$CLAUDE_PROJECT_DIR"
command -v ffmpeg >/dev/null || { apt-get update -qq && apt-get install -y -qq ffmpeg libegl1 libgles2; }
python3 -c "import fastapi, pythainlp, cv2, faster_whisper, mediapipe, pytest" 2>/dev/null || pip install -q -r requirements.txt pytest
