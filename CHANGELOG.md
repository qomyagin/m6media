# Changelog

## 1.3.1 — 2026-11-23

* Added Kazakh documentation: `README.kk.md` and `FAQ.kk.md`.
* Added Uzbek documentation: `README.uz.md` and `FAQ.uz.md`.
* Added a language switcher to the Russian, English and FAQ pages.
* Linked translations from `llms.txt`, `docs/SEO.md`, and `AGENTS.md`.

## 1.3.0 — 2026-11-23

* Windows support: drive-letter mounts, `GetVolumeInformationW` filesystem
  detection, WinGet/Chocolatey ffmpeg paths, UTF-8 subprocess I/O.
* Linux support: native filesystem detection and `/media/...` paths.
* Optional ImageMagick (`magick`) fallback for HEIC/RAW photos on Windows
  and Linux; macOS still uses `sips`.
* Cross-platform smoke test in Python replaces the Bash-only test.
* CI: Ubuntu Python 3.9/3.12, Windows Python 3.12, and smoke tests on
  Ubuntu and Windows with ffmpeg.

## 1.2.0 — 2026-11-23

* Default output is `M6` next to the input; `-o` is optional.
* Compatible files are skipped by default; `--normalize` processes them.
* Existing target files are skipped with a printed reason and logged;
  `--force` overwrites them.
* Video action `copy-video` copies H.264 video and converts audio to AAC.
* `--jobs` defaults to 2 on 8 cores; x264 threads are limited to
  `CPU / jobs` (`--threads` available).
* Compatible with ffmpeg 4.4+ (`-vsync`) and ffmpeg 5+ (`-fps_mode`).
* Added agent tooling: `AGENTS.md`, `llms.txt`, architecture and compatibility
  docs, manifest schema, `pyproject.toml`, Makefile, smoke test and CI.
* Added FAQ, compatibility matrix, English README, SEO metadata guide and
  `llms.txt` answers for AI search.
* Added MIT license.

## Earlier

Initial single-file CLI: H.264/AAC MP4 target, MP3/JPEG conversion, FAT32
splitting, manifest and `--check`/`--check-only`.
