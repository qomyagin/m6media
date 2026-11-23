#!/usr/bin/env bash
#
# End-to-end smoke test. Generates 2-second synthetic clips, so it does not
# need any real media and does not touch user files.
#
# Requires: ffmpeg, ffprobe, python3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/m6media-smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

fail() {
  echo "smoke: FAIL: $*" >&2
  exit 1
}

command -v ffmpeg  >/dev/null || fail "ffmpeg not found"
command -v ffprobe >/dev/null || fail "ffprobe not found"
command -v "$PY"    >/dev/null || fail "python3 not found"

IN="$TMP/in"
OUT="$TMP/out"
mkdir -p "$IN"

# Already compatible: H.264 Main 4.0 + AAC in MP4.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i "testsrc2=size=320x180:rate=24" \
  -f lavfi -i "sine=frequency=440:sample_rate=48000" \
  -t 2 -c:v libx264 -profile:v main -level 4.0 -pix_fmt yuv420p \
  -c:a aac -b:a 96k -movflags +faststart \
  "$IN/compatible.mp4"

# Needs video re-encode: MPEG-4 Part 2 (XviD-like) + AC3 in AVI.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i "testsrc2=size=320x180:rate=24" \
  -f lavfi -i "sine=frequency=330:sample_rate=48000" \
  -t 2 -c:v mpeg4 -vtag XVID -q:v 5 -c:a ac3 -b:a 128k \
  "$IN/incompatible.avi"

run_m6() {
  "$PY" "$ROOT/m6media.py" "$@"
}

# First pass: compatible skipped, incompatible transcoded and checked.
run_m6 "$IN" -o "$OUT" --only video --fat32 off \
  --x264-preset veryfast --jobs 1 --check

[[ -f "$OUT/Video/incompatible.mp4" ]] || fail "missing incompatible.mp4"
[[ ! -e "$OUT/Video/compatible.mp4" ]] || fail "compatible.mp4 should be skipped"

vcodec="$(ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name -of csv=p=0 "$OUT/Video/incompatible.mp4")"
acodec="$(ffprobe -v error -select_streams a:0 \
  -show_entries stream=codec_name -of csv=p=0 "$OUT/Video/incompatible.mp4")"
[[ "$vcodec" == "h264" ]] || fail "expected H.264, got $vcodec"
[[ "$acodec" == "aac" ]]  || fail "expected AAC, got $acodec"

"$PY" - "$OUT/_m6media/manifest.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
summary = data["summary"]
assert summary["ok"] == 1, summary
assert summary["skipped"] == 1, summary
actions = {item["action"] for item in data["items"]}
assert "transcode" in actions, actions
assert "skip-compatible" in actions, actions
PY

# Second pass: existing target must be skipped with a printed reason.
second="$("$PY" "$ROOT/m6media.py" "$IN" -o "$OUT" --only video --fat32 off \
  --x264-preset veryfast --jobs 1 2>&1)"
if ! grep -q "файл уже существует" <<<"$second"; then
  echo "$second" >&2
  fail "existing-file reason was not printed"
fi

# Third pass: --force must overwrite.
run_m6 "$IN" -o "$OUT" --only video --fat32 off \
  --x264-preset veryfast --jobs 1 --force --check

echo "smoke: OK"
