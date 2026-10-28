#!/usr/bin/env bash
# One-shot auto edit: cut silence/fillers, Thai subtitles, SFX + music, 1080x1920 MP4.
#   tools/quick_edit.sh CLIP [extra cli.py args...]     e.g. --srt clip.srt --music song.mp3 --preset dark_gold_story
# Output: output/<clip name>_edited.mp4
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -ge 1 ] || { echo "usage: $0 CLIP [cli.py args...]"; exit 1; }
clip="$1"; shift
name="$(basename "${clip%.*}")"
srt="${clip%.*}.srt"
args=()
# Use a transcript placed next to the clip when there is one (skips speech-to-text).
[ -f "$srt" ] && [[ " $* " != *" --srt "* ]] && args+=(--srt "$srt")
# Thai speech-to-text is much more accurate with large-v3-turbo than the engine's default "small" model.
[[ " $* " != *" --settings "* ]] && args+=(--settings '{"asr_model":"large-v3-turbo"}')
mkdir -p output
python3 cli.py "$clip" "${args[@]}" "$@" -o "output/${name}_edited.mp4"
