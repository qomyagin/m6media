# Claude Code entry point

Read [`AGENTS.md`](AGENTS.md) first. It is the canonical instruction file for
this repository: architecture, default behavior contract, test commands, and
privacy rules.

Quick checks:

```bash
make check
make smoke   # requires ffmpeg
```

Do not add real film titles, release names, personal paths, secrets, or media
files. Use neutral `movie-*` fixtures and synthetic `lavfi` clips.
