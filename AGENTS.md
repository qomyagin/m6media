# AGENTS.md

Canonical instructions for AI coding agents working on this repository.
Read this file before changing code. `README.md` is the user-facing manual
(in Russian); `docs/ARCHITECTURE.md` explains the internals.
License: MIT (see `LICENSE`).

## What this project is

`m6media` is a Python 3.9+ CLI that prepares media for the media player of a
Haval M6 (2023 / M6 Plus, Russian edition 2023–2026):

* video → MP4 (or MKV) with H.264 Main@4.0, AAC-LC stereo;
* music → MP3 (or AAC/M4A) with ID3v2.3;
* photos → JPEG, downscaled to 1920 px;
* runs on macOS, Linux, and Windows (native drive-letter / mount handling);
* incompatible video can be split into < 4 GiB parts for FAT32;
* a manifest (`_m6media/manifest.json`) and optional verification are written.

The program is deliberately a **single file** (`m6media.py`) plus tests. Do not
split it into a package unless the user explicitly asks; single-file delivery
is a product requirement.

## Golden rules

1. **Never modify or delete source media.** The tool reads input files and
   writes only to the output directory (`M6` by default).
2. **Do not add real film titles, release names, torrent links, or personal
   paths.** Use neutral fixtures such as `movie-xvid-1.avi` and
   `movie-h264-1.mkv`. The repository is public.
3. **SEO must stay honest.** Use natural headings that match real problems
   (“Haval M6 does not play AVI/XviD”), never keyword stuffing or invented
   format support. Update `llms.txt`, `FAQ.md`, and `README.en.md` when the
   user-facing story changes.
4. **Never add secrets.** No tokens, passwords, API keys, cookies, `.env`
   files, private keys, or personal email addresses. Commits must not contain
   them either.
5. **Keep the default contract.** Unless the user explicitly asks otherwise:
   * output directory: `M6` next to the input (created automatically);
   * already-compatible files are skipped;
   * existing target files are skipped with a printed reason;
   * `--force` overwrites targets;
   * `--normalize` processes compatible files too.
6. **Prefer copy over re-encode.** If the video is H.264 in a supported
   profile and only audio/container is incompatible, use `copy-video` /
   `remux`; never re-encode video just for convenience.
7. **No new runtime dependencies** outside Python stdlib + `ffmpeg`/`ffprobe`.
   `sips` (macOS) and ImageMagick `magick` (Windows/Linux) are optional
   image fallbacks.
8. **Python 3.9 compatibility.** `from __future__ import annotations` is used;
   avoid `match`, `tomllib`, `str.removeprefix`, and PEP 604 unions.
9. **No network access** in code or tests.

## Environment

Required for actual conversion:

* Python 3.9+
* `ffmpeg` and `ffprobe` with `libx264`, `aac`, `libmp3lame`

Optional:

* `sips` on macOS or ImageMagick (`magick`) on any OS for HEIC/RAW photos;
* `ffmpeg-full` (`libass`, `zscale`) for `--burn-subs` and `--tonemap`.

Unit tests **must not** require ffmpeg. The smoke test does.

## Commands

```bash
# unit tests (no ffmpeg required)
python3 -m unittest discover -s tests -v

# same via make
make test

# syntax check + unit tests
make check

# end-to-end smoke test (requires ffmpeg; generates 2-second synthetic clips)
make smoke

# CLI help / version
./m6media.py --help
./m6media.py --version

# dry-run on a folder (no writes)
./m6media.py /Volumes/USB --dry-run
# Windows: py -3 m6media.py E:\ --dry-run

# normal run
./m6media.py /Volumes/USB
# Windows: py -3 m6media.py E:\
```

The version is duplicated in `m6media.py` (`APP_VERSION`) and
`pyproject.toml`. Keep them in sync.

## File map

| Path | Purpose |
|---|---|
| `m6media.py` | entire CLI: probe, plan, ffmpeg commands, execution, manifest, checks |
| `tests/test_m6media.py` | unit tests for naming, compatibility, planning, default skip, output defaults |
| `tests/smoke_test.py` | synthetic end-to-end test with ffmpeg |
| `docs/ARCHITECTURE.md` | pipeline, data model, action names, exit codes |
| `docs/COMPATIBILITY.md` | codec/container matrix and symptom → fix table |
| `docs/SEO.md` | GitHub description/topics and discovery notes |
| `schema/manifest.schema.json` | JSON Schema for `_m6media/manifest.json` |
| `README.md` | user manual (Russian) |
| `README.en.md` | English manual |
| `FAQ.md` | Haval M6 incompatible-media FAQ |
| `CHANGELOG.md` | release notes |
| `LICENSE` | MIT license |
| `AGENTS.md` | this file |
| `llms.txt` | short machine-readable documentation index |
| `CLAUDE.md` | Claude Code entry point |
| `.github/copilot-instructions.md` | GitHub Copilot entry point |
| `Makefile` | deterministic test/smoke/check commands |
| `.github/workflows/ci.yml` | unit + smoke CI |
| `.editorconfig`, `.gitattributes` | LF, UTF-8, 4-space Python / tab Makefile |
| `pyproject.toml` | package metadata, `m6media` console script |

## Pipeline (do not break these stages)

1. `collect_files()` — recursive scan; skips hidden files, `_m6media`,
   `LOST.DIR`, `System Volume Information`, subtitles and sidecar `.ac3`.
2. `build_plan()` — `probe_media()` → `classify()` → `plan_video()` /
   `plan_audio()` / `plan_image()` → `assign_output()`.
3. Default skip: `already_compatible()` marks supported files as
   `skip-compatible`. `--normalize` disables this step.
4. `mark_existing_skips()` — existing target files become
   `skip-existing` (unless `--force`).
5. `execute_item()` — one ffmpeg job; `ThreadPoolExecutor` runs `--jobs`
   jobs; x264 threads are limited to `CPU / jobs`.
6. `verify_items()` — only with `--check`.
7. `write_manifest()` — JSON + CSV + run log.

If you add a stage, update `README.md` and `docs/ARCHITECTURE.md`.

## Action names

| Action | Meaning |
|---|---|
| `remux` | copy all streams into a new container; no re-encode |
| `copy-video` | copy H.264 video, re-encode audio (AC3/MP3 → AAC), new container |
| `transcode` | re-encode video (and usually audio) |
| `transcode-audio-only` | audio-only file: re-encode to target audio format |
| `remux-audio` | audio-only: copy codecs, rewrite tags/container |
| `image` | convert image to JPEG |
| `copy` | copy a file as-is (`--audio-format copy`) |
| `skip-compatible` | already supported by the player; not touched |
| `skip-existing` | target exists; skipped unless `--force` |
| `error` | planning/probe error |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success (including “nothing to do”) |
| 1 | one or more files failed / `--check` found a problem |
| 2 | usage, dependency, output-path, or filesystem error |
| 130 | interrupted by Ctrl+C |

## Common tasks

### Add a new input extension

1. Add it to `VIDEO_EXTS`, `AUDIO_EXTS`, or `IMAGE_EXTS`.
2. Make sure `classify()` chooses the right kind.
3. Add a unit test for `classify()` / compatibility.
4. Update the format table in `README.md` only if the player supports it.

### Change an encoding profile

Edit `PRESETS` in `m6media.py`. Keep `Main@4.0`, `yuv420p`, AAC-LC, and
faststart; these are compatibility requirements. Update the profile table in
`README.md` and the manifest defaults if needed.

### Add a CLI flag

1. Add it in `build_parser()`.
2. Put it on `args` / `Ctx` only if needed by planning or execution.
3. Pass it through the relevant `build_*_cmd()`.
4. Update `README.md`, `AGENTS.md`, and tests.
5. Keep the default behavior backward compatible.

### Debug an ffmpeg failure

* Run with `--verbose`; the full command is logged at debug level.
* Re-run the failing item with `--force`.
* Check `_m6media/run.log` and `_m6media/manifest.json`.
* Reproduce with a short `lavfi` clip, not a full film.

### Test safely

Use synthetic clips only:

```bash
ffmpeg -f lavfi -i testsrc2=size=320x180:rate=24 \
       -f lavfi -i sine=frequency=440:sample_rate=48000 \
       -t 2 -c:v libx264 -profile:v main -pix_fmt yuv420p \
       -c:a aac /tmp/movie-h264.mp4
```

Never add real media files, screenshots of film frames, or torrent metadata.

## Privacy / publication checks

Before committing, run:

```bash
git grep -InE 'password|secret|token\s*[:=]|api[_-]?key|ghp_|sk-[A-Za-z0-9]{20,}' -- . \
  ':!AGENTS.md' ':!CLAUDE.md' ':!llms.txt' || true
git grep -InE '(/Users/|/Volumes/|magnet:|torrent)' -- . \
  ':!AGENTS.md' | grep -v '/Volumes/USB' || true
git log --format='%an <%ae>'
```

The repository must not contain real film names, `/Users/<name>` paths,
personal `/Volumes/<label>` paths, or real email addresses in commits.

## Definition of done

* `make check` passes.
* `make smoke` passes if ffmpeg is available.
* `README.md` is updated for user-visible changes.
* `docs/ARCHITECTURE.md` and `schema/manifest.schema.json` are updated if the
  pipeline or manifest shape changed.
* No secrets, personal data, or real film titles are added.
* Working tree is clean and the commit message describes the change.
