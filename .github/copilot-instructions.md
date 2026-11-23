# GitHub Copilot instructions

Follow [`AGENTS.md`](../AGENTS.md). In short:

- `m6media.py` is intentionally a single-file CLI; keep it that way.
- Default behavior: output `M6` next to input, skip compatible files, skip
  existing targets unless `--force`, `--normalize` processes everything.
- No new runtime dependencies; Python 3.9+ and ffmpeg only.
- Use synthetic `lavfi` clips in tests; never add real media or film titles.
- Run `make check`; run `make smoke` when ffmpeg is available.
