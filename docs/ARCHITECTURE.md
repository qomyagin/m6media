# Architecture

`m6media.py` is intentionally one file. It has no third-party Python
dependencies: only `ffmpeg`, `ffprobe`, and optionally macOS `sips`.

## Goals and non-goals

Goals:

* turn incompatible files into a format the Haval M6 player can decode;
* preserve quality when only the container or audio codec is the problem;
* never modify source files;
* be predictable and safe on a USB flash drive (FAT32 4 GiB limit, exFAT);
* leave a machine-readable report.

Non-goals:

* downloading, ripping, or decrypting media;
* editing video, adding effects, or managing subtitle tracks;
* building a GUI;
* becoming a general-purpose transcoder.

## Pipeline

```
paths
  │
  ├─ collect_files()          recursive scan, skip hidden/service files
  │
  ├─ build_plan()             per-file:
  │    probe_media()            ffprobe JSON → MediaInfo
  │    classify()               video | audio | image | unknown
  │    plan_video/audio/image() decide action and target size
  │    assign_output()          output name, extension, parts
  │
  ├─ already_compatible()     default: skip what the player already reads
  ├─ mark_existing_skips()    default: skip existing targets
  │
  ├─ execute_item()           ThreadPoolExecutor(--jobs)
  │    build_*_cmd()            ffmpeg command
  │    run_ffmpeg()             progress, stderr capture
  │    encode_with_ffmpeg()     .part file → atomic rename
  │
  ├─ verify_items()           optional --check
  └─ write_manifest()         manifest.json/csv + run.log
```

## Data model

```python
StreamInfo   # one ffprobe stream: codec, profile, level, pix_fmt, size, fps...
MediaInfo    # one input file: format, duration, size, streams, cover art
PlanItem     # one planned output: source, kind, action, parts, reasons, paths
Ctx          # tools, preset, args, output dir, used names, lock, logger
```

All dataclasses live at module level so tests can construct them without
running ffmpeg. `MediaInfo.video` returns the first non-attached-picture video
stream; `MediaInfo.cover` returns attached cover art.

## Compatibility policy

The supported list comes from the Haval M6 Plus manual (2023–2026), page 116:

* audio: MP3, WMA, AAC, FLAC, WAV, OGG;
* video: WMV, MP4, MPEG, AVI, 3GP, MKV, MOV, ASF, VOB;
* photo: JPG, PNG, BMP;
* USB: FAT16/FAT32 (exFAT is accepted in practice).

The player cares about **codecs**, not only containers. The target for
converted video is deliberately conservative:

* MP4 (or MKV with `--container mkv`);
* H.264 Main@4.0, `yuv420p`, 8-bit 4:2:0, ≤ 1920×1080, ≤ 30 fps;
* AAC-LC, 48 kHz, stereo;
* `+faststart` for MP4.

`already_compatible()` decides what not to touch:

* video: H.264 in MKV/MP4/MOV with compatible profile/level and AAC audio;
  MKV with AC3 or MP3 audio is also accepted (observed working);
* audio: supported codec and extension;
* image: JPG/JPEG/PNG/BMP.

`--normalize` disables these skips.

## Actions

| Action | Trigger | What happens |
|---|---|---|
| `remux` | video/audio codecs are compatible | `-c copy`, new container |
| `copy-video` | H.264 video is compatible, audio is not | video copy, audio → AAC |
| `transcode` | video codec/profile/level/HDR/rotation is incompatible | x264 + AAC |
| `transcode-audio-only` | audio file needs a different codec | ffmpeg audio encode |
| `remux-audio` | audio file already matches target codec | copy + retag |
| `image` | unsupported photo format / requested conversion | JPEG via sips/ffmpeg |
| `copy` | `--audio-format copy` | byte copy |
| `skip-compatible` | `already_compatible()` true | no output |
| `skip-existing` | target path exists and no `--force` | no output, reason printed |
| `error` | probe/planning failure | no output, error reported |

## Output naming and layout

```
M6/
├── Video/<stem>.mp4|mkv
├── Music/<stem>.mp3|m4a|...
├── Photo/<stem>.jpg
└── _m6media/
    ├── manifest.json
    ├── manifest.csv
    └── run.log
```

Default output is `M6` next to the input. For a directory input it is
`<input>/M6`; for a file input it is `<file parent>/M6`; for multiple inputs
in one directory it is `<common parent>/M6`, otherwise `./M6`.

Names are transliterated to ASCII by default (`--keep-names` preserves
Unicode). Numeric prefixes are optional (`--number`); collisions get `_2`,
`_3`, etc. Split files use `_part01`, `_part02`.

## Size / FAT32 planning

`compute_size_plan(duration, ctx)` returns `(parts, video_bitrate, reason)`:

* `off` — one part, preset maxrate;
* `fit` — lower the cap so one file fits `--max-file-size` (default 3.8 GiB);
  if the cap would fall below 2.2 Mbit/s at 1080p (1.2 at 720p), split;
* `split` — keep the preset bitrate and split into equal-duration parts.

After encoding, `execute_transcode_video()` re-checks actual sizes; if a file
still exceeds the limit, it retries with more parts (max 60).

## Manifest

`schema/manifest.schema.json` describes `_m6media/manifest.json`.

Top-level fields:

* `app`, `version`, `created`, `ffmpeg`;
* `settings` (preset, container, normalize, fat32, sizes, fps, audio/photo
  settings, filesystem);
* `summary` (`total`, `ok`, `failed`, `skipped`, `bytes_out`);
* `items[]` (source, type, action, status, outputs, reasons, notes, error,
  source_media).

`manifest.csv` is a flat view with `;` separator and UTF-8 BOM. `run.log`
contains processing lines and skip reasons.

## Concurrency and performance

* `--jobs` defaults to `min(4, CPU // 4)` (2 on an 8-core Mac).
* `--threads` defaults to `CPU // jobs`; each x264 process gets that many
  threads, avoiding the load spike caused by 4 × 12 threads.
* Video encoding is CPU-bound; reading and writing the same USB drive is
  I/O-bound. For large batches, encode to a local disk and copy to USB.
* `+faststart` rewrites the MP4 at the end; large files can appear “stuck”
  at 100% for a while.

## Error handling and exit codes

| Code | Meaning |
|---|---|
| 0 | success, including “nothing to do” |
| 1 | one or more files failed, or `--check` found issues |
| 2 | CLI/dependency/output/filesystem error |
| 130 | Ctrl+C |

A single failing file does not abort the batch. `execute_item()` catches
`M6Error`/`OSError`, removes partial output, and records the error.

## Testing hooks

* Unit tests construct `StreamInfo`, `MediaInfo`, `PlanItem`, and `Ctx`
  directly; no ffmpeg or media files needed.
* `tests/smoke_test.sh` generates 2-second `lavfi` clips and exercises the
  default skip, transcode, check, rerun-skip, and `--force` paths.
* CI runs unit tests on Linux Python 3.9/3.12 and the smoke test on
  Ubuntu with ffmpeg. macOS is tested locally with `sips`.

## Extension points

* new extension → `VIDEO_EXTS`, `AUDIO_EXTS`, or `IMAGE_EXTS` + `classify()`;
* new profile → `PRESETS`;
* new action → `plan_*`, `build_*_cmd`, `execute_*`, `verify_media`, manifest;
* new output container → `video_mux_args()` and suffix handling in
  `assign_output()` / `execute_transcode_video()`;
* new metadata → `write_manifest()` and the JSON schema.

## Privacy and publication

The repository is public. Do not add real film titles, release names,
personal paths, emails, tokens, or media files. Use neutral fixtures such as
`movie-xvid-1.avi`. See `AGENTS.md` for the pre-commit checks.
