# m6media — Haval M6 (2023) USB video converter

**Haval M6 does not play AVI/XviD, MKV with AC3, or some files from a USB
flash drive?** The container may be supported while the codec is not. This
CLI converts only the incompatible files to **H.264 Main@4.0 + AAC-LC in
MP4**, prepares music/photos, and leaves files that already work untouched.

Russian manual: [README.md](README.md).  
Compatibility matrix: [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).  
FAQ: [FAQ.md](FAQ.md).

## The short answer

A Haval M6 (2023 / M6 Plus) can show an `.avi` file in the list but fail to
decode it if the video is **MPEG-4 Part 2 (XviD/DivX)**. The same applies to
HDR/10-bit H.264, unusual profiles, and AC3/DTS audio in MP4. The safe target
is:

* MP4 container (`+faststart`);
* H.264 Main@4.0, `yuv420p`, up to 1080p and 30 fps;
* AAC-LC, 48 kHz, stereo.

`m6media` probes each file with `ffprobe` and decides: copy, remux, or
transcode. If the video is already compatible H.264, it is copied without
re-encoding whenever possible.

## Quick start

Requirements: Python 3.9+ and `ffmpeg`/`ffprobe` with `libx264`, `aac`,
`libmp3lame`.

```bash
# macOS
brew install ffmpeg

# see what would happen (no writes)
./m6media.py /Volumes/USB --diagnose

# convert only incompatible files into /Volumes/USB/M6
./m6media.py /Volumes/USB

# verify the result
./m6media.py /Volumes/USB/M6 --check-only
```

Default output is `M6` next to the input. Existing targets are skipped with
a printed reason; `--force` overwrites them. Files that already work are
skipped; add `--normalize` to convert everything into one format.

## What it does

| Input | Action |
|---|---|
| H.264 + AAC in MP4/MKV | `remux` or skip |
| H.264 in MKV + AC3 | `copy-video`: video copy, audio → AAC |
| XviD/DivX AVI | `transcode` to H.264 Main@4.0 + AAC |
| MP3 / FLAC / WAV / OGG | compatible audio is left alone; MP3 target available |
| HEIC/PNG/JPEG photos | JPEG, max 1920 px |
| Video > 4 GiB on FAT32 | `--fat32 fit` or `--fat32 split` |

## Supported by the car (manual)

* Video: WMV, MP4, MPEG, AVI, 3GP, MKV, MOV, ASF, VOB.
* Audio: MP3, WMA, AAC, FLAC, WAV, OGG.
* Photo: JPG, PNG, BMP.
* USB: FAT16/FAT32; exFAT works in practice.

Container support does **not** imply codec support. XviD/DivX is the most
common reason an AVI file "does not show up".

## Useful commands

```bash
# faster on a USB flash drive: 2 jobs, fast x264 preset
./m6media.py /Volumes/USB --jobs 2 --x264-preset veryfast

# full re-pack of an existing library, MP4/AAC
./m6media.py /Volumes/USB --normalize --container mp4

# keep the original Unicode file names
./m6media.py /Volumes/USB --keep-names

# overwrite existing outputs
./m6media.py /Volumes/USB --force

# full help
./m6media.py --help
```

## Development

```bash
make check    # compile + 38 unit tests, no ffmpeg needed
make smoke    # synthetic end-to-end test, requires ffmpeg
```

The project is intentionally a single Python file (`m6media.py`). See
[AGENTS.md](AGENTS.md) for agent instructions,
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for internals, and
[schema/manifest.schema.json](schema/manifest.schema.json) for the JSON
report.

## License

MIT. See [LICENSE](LICENSE).
