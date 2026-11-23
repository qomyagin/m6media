#!/usr/bin/env python3
"""Cross-platform end-to-end smoke test.

Generates 2-second synthetic clips with ffmpeg, so it does not need real
media and does not touch user files. Works on macOS, Linux, and Windows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(cmd, **kwargs):
    return subprocess.run(
        [str(part) for part in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )


def fail(message: str) -> None:
    print(f"smoke: FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        fail(f"{name} not found")
    return path


def run_m6(*args):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return run([PY, ROOT / "m6media.py", *args], env=env)


def codec(path: Path, stream: str) -> str:
    cp = run([
        require_tool("ffprobe"), "-v", "error",
        "-select_streams", stream,
        "-show_entries", "stream=codec_name",
        "-of", "csv=p=0", path,
    ])
    return cp.stdout.strip()


def main() -> int:
    ffmpeg = require_tool("ffmpeg")
    require_tool("ffprobe")

    with tempfile.TemporaryDirectory(prefix="m6media-smoke-") as raw_tmp:
        tmp = Path(raw_tmp)
        source = tmp / "in"
        out = tmp / "out"
        source.mkdir()

        # Already compatible: H.264 Main 4.0 + AAC in MP4.
        cp = run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "2", "-c:v", "libx264", "-profile:v", "main",
            "-level", "4.0", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            source / "compatible.mp4",
        ])
        if cp.returncode != 0:
            fail(f"fixture compatible.mp4: {cp.stderr.strip()}")

        # Needs video re-encode: MPEG-4 Part 2 (XviD-like) + AC3 in AVI.
        cp = run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
            "-t", "2", "-c:v", "mpeg4", "-vtag", "XVID", "-q:v", "5",
            "-c:a", "ac3", "-b:a", "128k",
            source / "incompatible.avi",
        ])
        if cp.returncode != 0:
            fail(f"fixture incompatible.avi: {cp.stderr.strip()}")

        # 1. Convert only what is needed, verify.
        cp = run_m6(
            source, "-o", out, "--only", "video", "--fat32", "off",
            "--x264-preset", "veryfast", "--jobs", "1", "--check",
        )
        if cp.returncode != 0:
            sys.stdout.write(cp.stdout)
            sys.stderr.write(cp.stderr)
            fail("first conversion failed")

        target = out / "Video" / "incompatible.mp4"
        if not target.is_file():
            fail("missing incompatible.mp4")
        if (out / "Video" / "compatible.mp4").exists():
            fail("compatible.mp4 should be skipped")

        if codec(target, "v:0") != "h264":
            fail("video is not H.264")
        if codec(target, "a:0") != "aac":
            fail("audio is not AAC")

        manifest = json.loads((out / "_m6media" / "manifest.json").read_text(encoding="utf-8"))
        summary = manifest["summary"]
        if summary["ok"] != 1 or summary["skipped"] != 1:
            fail(f"unexpected manifest summary: {summary}")
        actions = {item["action"] for item in manifest["items"]}
        if "transcode" not in actions or "skip-compatible" not in actions:
            fail(f"unexpected actions: {actions}")

        # 2. Existing target must be skipped with a printed reason.
        second = run_m6(
            source, "-o", out, "--only", "video", "--fat32", "off",
            "--x264-preset", "veryfast", "--jobs", "1",
        )
        combined = second.stdout + second.stderr
        if "файл уже существует" not in combined:
            fail("existing-file reason was not printed")

        # 3. --force must overwrite.
        forced = run_m6(
            source, "-o", out, "--only", "video", "--fat32", "off",
            "--x264-preset", "veryfast", "--jobs", "1", "--force", "--check",
        )
        if forced.returncode != 0:
            sys.stdout.write(forced.stdout)
            sys.stderr.write(forced.stderr)
            fail("--force failed")

    print("smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
