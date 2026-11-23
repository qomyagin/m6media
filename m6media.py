#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
m6media.py — подготовка видео, музыки и фотографий для мультимедиа
Haval M6 (M6 Plus, российское издание 2023–2026).

Что делает скрипт:
  * читает файлы во входных папках (или отдельные файлы);
  * определяет тип и параметры потоков через ffprobe;
  * приводит видео к MP4 / H.264 Main / AAC-LC / 8-bit 4:2:0;
  * приводит музыку к MP3 (ID3v2.3) либо AAC/M4A;
  * приводит фото к JPEG, при необходимости уменьшает;
  * раскладывает результат по папкам Video / Music / Photo;
  * разбивает слишком большие видео на части, чтобы каждая была < 4 ГиБ
    (ограничение FAT32, который поддерживает головное устройство);
  * пишет отчёт (JSON + CSV + журнал) и умеет проверять готовый результат.

Зависимости: Python 3.9+ и ffmpeg/ffprobe (libx264, aac, libmp3lame).
На macOS для фото используется встроенный sips (понимает HEIC/RAW).
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Optional

APP_NAME = "m6media"
APP_VERSION = "1.3.1"

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff",
    ".heic", ".heif", ".avif", ".jp2", ".j2k",
    # RAW (на macOS их умеет sips)
    ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".orf",
    ".rw2", ".raf", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".mef", ".mos",
}
AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".wave", ".ogg", ".oga", ".opus",
    ".wma", ".aif", ".aiff", ".aifc", ".alac", ".ape", ".wv", ".dsf", ".dff",
}
VIDEO_EXTS = {
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".asf", ".mpg", ".mpeg",
    ".vob", ".3gp", ".3g2", ".ts", ".m2ts", ".mts", ".webm", ".flv", ".ogv",
    ".divx", ".rm", ".rmvb",
}
SUPPORTED_AUDIO_COPY_EXTS = {".mp3", ".wma", ".aac", ".flac", ".wav", ".wave", ".ogg"}

# Кодеки/расширения, которые M6 читает по инструкции (или проверенно).
AUDIO_OK_CODECS = {
    "mp3", "wma", "wmav1", "wmav2", "wmapro", "aac", "flac", "vorbis",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_u8",
}
AUDIO_OK_EXTS = {".mp3", ".wma", ".m4a", ".aac", ".flac", ".wav", ".wave", ".ogg", ".oga"}
IMAGE_OK_EXTS = {".jpg", ".jpeg", ".jpe", ".png", ".bmp"}

SKIP_NAMES = {".DS_Store", "Thumbs.db", "thumbs.db", "desktop.ini", "Icon\r"}
DIRS = {"video": "Video", "audio": "Music", "image": "Photo"}

FAT32_LIMIT = 4_294_967_295          # 4 ГиБ, фактический предел FAT32
DEFAULT_MAX_FILE = int(3.8 * 1024 ** 3)  # запас под накладные расходы MP4

# Профили H.264, которые заведомо понимает_head unit.
H264_OK_PROFILES = {"constrained baseline", "baseline", "main", "high"}
H264_OUTPUT_PROFILE = "main"
H264_OUTPUT_LEVEL = "4.0"

GIB = 1024 ** 3
MIB = 1024 ** 2


# ---------------------------------------------------------------------------
# Ошибки и утилиты
# ---------------------------------------------------------------------------

class M6Error(Exception):
    """Ошибка, которую нужно показать пользователю без traceback."""


class ProbeError(M6Error):
    """ffprobe не смог прочитать файл."""


@dataclass(frozen=True)
class Preset:
    name: str
    max_w: int
    max_h: int
    crf: int
    maxrate: int          # бит/с
    audio_kbps: int
    fps: float            # 0 = не ограничивать


PRESETS = {
    "compat": Preset("compat", 1920, 1080, 21, 8_000_000, 192, 30.0),
    "quality": Preset("quality", 1920, 1080, 19, 12_000_000, 256, 30.0),
    "compact": Preset("compact", 1280, 720, 23, 3_000_000, 128, 30.0),
}


def human_size(n: int) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ"):
        if n < 1024 or unit == "ТиБ":
            if unit == "Б":
                return f"{int(n)} Б"
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} ТиБ"


def human_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "?"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_rate(value: Optional[str]) -> Optional[float]:
    """'30000/1001' -> 29.97."""
    if not value:
        return None
    try:
        frac = Fraction(value)
        if frac.denominator == 0:
            return None
        rate = float(frac)
        return rate if 0 < rate < 1000 else None
    except (ValueError, ZeroDivisionError, TypeError):
        try:
            rate = float(value)
            return rate if 0 < rate < 1000 else None
        except (ValueError, TypeError):
            return None


def parse_size(value: str) -> int:
    """'3.8G', '4000M', '3.8GiB', '1000000' -> байты (K/M/G = 1024^n)."""
    s = str(value).strip().replace(" ", "")
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGTkmgt]?)(?:i?[Bb])?", s)
    if not m:
        raise argparse.ArgumentTypeError(f"не понимаю размер: {value!r}")
    number = float(m.group(1))
    suffix = m.group(2).upper()
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[suffix]
    result = int(number * mult)
    if result <= 0:
        raise argparse.ArgumentTypeError("размер должен быть больше нуля")
    return result


def parse_bitrate(value: str) -> int:
    """'8M', '8000k', '8000000' -> бит/с."""
    s = str(value).strip().replace(" ", "")
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kKmMgG]?)", s)
    if not m:
        raise argparse.ArgumentTypeError(f"не понимаю битрейт: {value!r}")
    number = float(m.group(1))
    suffix = m.group(2).lower()
    mult = {"": 1, "k": 1000, "m": 1_000_000, "g": 1_000_000_000}[suffix]
    result = int(number * mult)
    if result < 10_000:
        raise argparse.ArgumentTypeError("битрейт слишком мал")
    return result


def run_cmd(cmd: list[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise M6Error(f"не найден исполняемый файл: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise M6Error(f"команда зависла и была прервана: {' '.join(cmd[:3])}…") from exc


def find_tool(name: str, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        raise M6Error(f"указанный путь не является исполняемым файлом: {explicit}")
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}", f"/usr/bin/{name}",
        f"/opt/local/bin/{name}", f"/snap/bin/{name}",
    ]
    if os.name == "nt":
        exe = name if name.lower().endswith(".exe") else f"{name}.exe"
        local = os.environ.get("LOCALAPPDATA", "")
        programdata = os.environ.get("ProgramData", "")
        candidates = [
            rf"C:\ffmpeg\bin\{exe}",
            rf"C:\Program Files\ffmpeg\bin\{exe}",
            rf"{programdata}\chocolatey\bin\{exe}",
            rf"{local}\Microsoft\WinGet\Links\{exe}",
        ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


# ---------------------------------------------------------------------------
# Модель медиафайла
# ---------------------------------------------------------------------------

@dataclass
class StreamInfo:
    index: int = 0
    codec_type: str = ""
    codec_name: str = ""
    profile: Optional[str] = None
    level: Optional[int] = None
    pix_fmt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    sample_aspect_ratio: Optional[str] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None
    bit_rate: Optional[int] = None
    r_frame_rate: Optional[str] = None
    avg_frame_rate: Optional[str] = None
    duration: Optional[float] = None
    attached_pic: bool = False
    rotation: Optional[float] = None
    field_order: Optional[str] = None
    color_transfer: Optional[str] = None
    color_primaries: Optional[str] = None
    tags: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "StreamInfo":
        tags = {str(k): str(v) for k, v in (data.get("tags") or {}).items()}
        rotation = None
        for side in data.get("side_data_list") or []:
            if "rotation" in side:
                try:
                    rotation = float(side["rotation"])
                except (TypeError, ValueError):
                    pass
                break
        if rotation is None:
            raw_rot = tags.get("rotate")
            if raw_rot is not None:
                try:
                    rotation = float(raw_rot)
                except ValueError:
                    pass

        def _int(value):
            try:
                return int(str(value))
            except (TypeError, ValueError):
                return None

        def _float(value):
            try:
                return float(str(value))
            except (TypeError, ValueError):
                return None

        disposition = data.get("disposition") or {}
        return cls(
            index=_int(data.get("index")) or 0,
            codec_type=str(data.get("codec_type") or ""),
            codec_name=str(data.get("codec_name") or ""),
            profile=data.get("profile"),
            level=_int(data.get("level")),
            pix_fmt=data.get("pix_fmt"),
            width=_int(data.get("width")),
            height=_int(data.get("height")),
            sample_aspect_ratio=data.get("sample_aspect_ratio"),
            channels=_int(data.get("channels")),
            sample_rate=_int(data.get("sample_rate")),
            bit_rate=_int(data.get("bit_rate")),
            r_frame_rate=data.get("r_frame_rate"),
            avg_frame_rate=data.get("avg_frame_rate"),
            duration=_float(data.get("duration")),
            attached_pic=bool(disposition.get("attached_pic")),
            rotation=rotation,
            field_order=data.get("field_order"),
            color_transfer=data.get("color_transfer"),
            color_primaries=data.get("color_primaries"),
            tags=tags,
        )

    def summary(self) -> str:
        if self.codec_type == "video":
            size = ""
            if self.width and self.height:
                size = f" {self.width}x{self.height}"
            return f"{self.codec_name}{size}"
        if self.codec_type == "audio":
            parts = [self.codec_name]
            if self.channels:
                parts.append(f"{self.channels}ch")
            if self.sample_rate:
                parts.append(f"{self.sample_rate} Hz")
            return " ".join(parts)
        return self.codec_name


@dataclass
class MediaInfo:
    path: Path
    format_name: str = ""
    format_long_name: str = ""
    duration: float = 0.0
    size: int = 0
    bit_rate: int = 0
    streams: list = field(default_factory=list)
    chapters: int = 0

    @property
    def video(self) -> Optional[StreamInfo]:
        for stream in self.streams:
            if stream.codec_type == "video" and not stream.attached_pic:
                return stream
        return None

    @property
    def audio(self) -> Optional[StreamInfo]:
        for stream in self.streams:
            if stream.codec_type == "audio":
                return stream
        return None

    @property
    def cover(self) -> Optional[StreamInfo]:
        for stream in self.streams:
            if stream.codec_type == "video" and stream.attached_pic:
                return stream
        return None

    def to_dict(self) -> dict:
        return {
            "format": self.format_name,
            "duration": round(self.duration, 3),
            "size": self.size,
            "bit_rate": self.bit_rate,
            "chapters": self.chapters,
            "video": {
                "codec": self.video.codec_name if self.video else None,
                "profile": self.video.profile if self.video else None,
                "level": self.video.level if self.video else None,
                "pix_fmt": self.video.pix_fmt if self.video else None,
                "width": self.video.width if self.video else None,
                "height": self.video.height if self.video else None,
                "rotation": self.video.rotation if self.video else None,
                "fps": parse_rate(self.video.r_frame_rate) if self.video else None,
            } if self.video else None,
            "audio": {
                "codec": self.audio.codec_name if self.audio else None,
                "channels": self.audio.channels if self.audio else None,
                "sample_rate": self.audio.sample_rate if self.audio else None,
                "bit_rate": self.audio.bit_rate if self.audio else None,
            } if self.audio else None,
        }


def probe_media(path: Path, ffprobe: str, timeout: float = 120.0) -> MediaInfo:
    cp = run_cmd(
        [ffprobe, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", "-show_chapters", str(path)],
        timeout=timeout,
    )
    if cp.returncode != 0:
        message = (cp.stderr or "").strip().splitlines()
        raise ProbeError(message[-1] if message else f"ffprobe код {cp.returncode}")
    try:
        data = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe вернул некорректный JSON: {exc}") from exc

    fmt = data.get("format") or {}
    streams = [StreamInfo.from_dict(item) for item in (data.get("streams") or [])]

    def _float(value):
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return 0.0

    def _int(value):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return 0

    duration = _float(fmt.get("duration"))
    if duration <= 0:
        duration = max((s.duration or 0.0 for s in streams), default=0.0)
    size = _int(fmt.get("size"))
    if size <= 0:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
    return MediaInfo(
        path=path,
        format_name=str(fmt.get("format_name") or ""),
        format_long_name=str(fmt.get("format_long_name") or ""),
        duration=duration,
        size=size,
        bit_rate=_int(fmt.get("bit_rate")),
        streams=streams,
        chapters=len(data.get("chapters") or []),
    )


def display_size(video: Optional[StreamInfo]) -> tuple[int, int]:
    if not video:
        return 0, 0
    w, h = video.width or 0, video.height or 0
    if video.rotation is not None and int(round(abs(video.rotation))) % 180 == 90:
        w, h = h, w
    return w, h


def is_hdr(video: Optional[StreamInfo]) -> bool:
    if not video:
        return False
    if (video.color_transfer or "").lower() in {"smpte2084", "arib-std-b67"}:
        return True
    return (video.color_primaries or "").lower() == "bt2020"


def classify(path: Path, info: Optional[MediaInfo]) -> str:
    ext = path.suffix.lower()
    if ext == ".gif" and info and info.video and (info.duration or 0) > 0.2:
        return "video"  # анимированный GIF -> MP4
    if ext in IMAGE_EXTS:
        return "image"
    if info and info.video:
        return "video"
    if info and info.audio:
        return "audio"
    return "unknown"


# ---------------------------------------------------------------------------
# Имена файлов
# ---------------------------------------------------------------------------

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # украинский / белорусский / сербский
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
    "ђ": "dj", "ј": "j", "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz",
}

_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def transliterate(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        tr = _TRANSLIT.get(low)
        if tr is None:
            out.append(ch)
        elif ch.isupper() and tr:
            out.append(tr[0].upper() + tr[1:])
        else:
            out.append(tr)
    text = "".join(out)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.encode("ascii", "ignore").decode("ascii")


def safe_stem(stem: str, keep_names: bool) -> str:
    if keep_names:
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
        text = re.sub(r"\s+", " ", text)
        max_len = 110
    else:
        text = transliterate(stem)
        text = re.sub(r"[^A-Za-z0-9._ -]+", "_", text)
        text = text.replace(" ", "_")
        max_len = 80

    text = re.sub(r"[_\-]{2,}", lambda m: m.group(0)[0], text)
    text = text.strip(" ._-")
    if not text:
        text = "file"
    if text.split(".")[0].upper() in _RESERVED_NAMES:
        text = "_" + text
    text = text[:max_len].rstrip(" ._-")
    return text or "file"


# ---------------------------------------------------------------------------
# Планирование
# ---------------------------------------------------------------------------

@dataclass
class PlanItem:
    idx: int
    src: Path
    kind: str
    info: Optional[MediaInfo]
    action: str = "skip"
    reasons: list = field(default_factory=list)
    out_stem: str = ""
    out_paths: list = field(default_factory=list)
    parts: int = 1
    cap: int = 0
    est_size: int = 0
    target_fps: str = ""
    subtitle: Optional[Path] = None
    error: str = ""
    status: str = "planned"
    duration_out: float = 0.0
    notes: list = field(default_factory=list)


@dataclass
class Ctx:
    ffmpeg: str
    ffprobe: str
    preset: Preset
    args: argparse.Namespace
    output: Path
    used_names: set
    lock: threading.Lock
    log: logging.Logger
    has_zscale: bool = False
    has_subtitles_filter: bool = False
    sips: Optional[str] = None
    magick: Optional[str] = None
    ffmpeg_version: str = ""
    ffmpeg_major: int = 0
    fs_name: str = ""

    def progress(self, label: str, pct: int) -> None:
        if pct < 100 and pct % 20 != 0:
            return
        with self.lock:
            eprint(f"    {label}: {pct:3d}%")


def video_copy_reasons(info: MediaInfo, ctx: Ctx) -> list:
    video = info.video
    reasons = []
    if not video:
        return ["нет видеопотока"]
    if video.codec_name in {"mpeg4", "msmpeg4v3", "msmpeg4v2", "xvid", "divx", "h263"}:
        reasons.append(
            "видеокодек MPEG-4 Part 2 (XviD/DivX) — M6 его не воспроизводит"
        )
    elif video.codec_name != "h264":
        reasons.append(f"видеокодек {video.codec_name or '?'}, нужен H.264")
    if video.pix_fmt not in {"yuv420p", "yuvj420p"}:
        reasons.append(f"пиксельный формат {video.pix_fmt or '?'}")
    width, height = display_size(video)
    if width <= 0 or height <= 0:
        reasons.append("не удалось определить размер кадра")
    elif width > ctx.preset.max_w or height > ctx.preset.max_h:
        reasons.append(f"размер {width}x{height} больше {ctx.preset.max_w}x{ctx.preset.max_h}")
    if video.codec_name == "h264":
        if (video.profile or "").lower() not in H264_OK_PROFILES:
            reasons.append(f"профиль H.264 {video.profile!r}")
        if video.level is None:
            reasons.append("не указан level H.264")
        elif video.level > 41:
            reasons.append(f"level H.264 {video.level / 10:.1f} > 4.1")
        elif video.level == 41 and height > 720:
            # Проверено на вашем M6: High@4.1 при 480p играет. Для 1080p
            # перестрахуемся и приведём к 4.0.
            reasons.append("level H.264 4.1 при высоте > 720p")
    fps = parse_rate(video.r_frame_rate) or parse_rate(video.avg_frame_rate)
    if ctx.args.fps and fps and fps > ctx.args.fps + 0.5:
        reasons.append(f"{fps:g} кадр/с > {ctx.args.fps:g}")
    if video.rotation is not None and abs(video.rotation) % 360 not in (0.0, 180.0):
        reasons.append("видео повёрнуто (нужно «запечь» поворот)")
    if is_hdr(video):
        reasons.append("HDR/10-бит (нужен SDR 8-бит)")
    return reasons


def audio_copy_reasons(info: MediaInfo) -> list:
    audio = info.audio
    if not audio:
        return []
    reasons = []
    codec_reason = False
    if audio.codec_name in {"ac3", "eac3", "dts", "truehd"}:
        reasons.append(
            f"звук {audio.codec_name.upper()} {audio.channels or '?'}ch — "
            "перекодируем в AAC для MP4"
        )
        codec_reason = True
    elif audio.codec_name != "aac":
        reasons.append(f"аудиокодек {audio.codec_name or '?'}, нужен AAC")
        codec_reason = True
    if audio.profile and audio.profile.upper() not in {"LC"}:
        reasons.append(f"профиль AAC {audio.profile}")
    if (audio.channels or 2) > 2 and not codec_reason:
        reasons.append(f"{audio.channels} каналов, нужен стерео")
    if (audio.sample_rate or 48000) > 48000:
        reasons.append(f"{audio.sample_rate} Гц, нужно ≤ 48 кГц")
    return reasons


def compute_size_plan(duration: float, ctx: Ctx) -> tuple:
    """Возвращает (частей, битрейт видео, пояснение)."""
    preset = ctx.preset
    if ctx.args.fat32 == "off" or duration <= 0:
        return 1, preset.maxrate, ""

    limit = ctx.args.max_file_size
    budget = limit * 0.97
    audio_bps = preset.audio_kbps * 1000
    overhead = 64_000
    fit_cap = int(budget * 8 / duration - audio_bps - overhead)
    floor = 2_200_000 if preset.max_h >= 1080 else 1_200_000
    worst = (preset.maxrate + audio_bps + overhead) * duration / 8
    parts = max(1, int(math.ceil(worst / budget)))

    if ctx.args.fat32 == "split":
        if parts > 1:
            return parts, preset.maxrate, (
                f"не помещается в FAT32: разбить на {parts} частей"
            )
        return 1, preset.maxrate, ""

    if fit_cap >= floor:
        cap = min(preset.maxrate, max(10_000, fit_cap))
        return 1, cap, ""

    parts = max(2, parts)
    return parts, preset.maxrate, (
        f"чтобы уложиться в {human_size(limit)}, битрейт был бы ниже "
        f"{floor / 1e6:.1f} Мбит/с — разбить на {parts} частей"
    )


_COMMON_RATES = (
    (24000 / 1001, "24000/1001"),
    (24.0, "24"),
    (25.0, "25"),
    (30000 / 1001, "30000/1001"),
    (30.0, "30"),
    (50.0, "50"),
    (60000 / 1001, "60000/1001"),
    (60.0, "60"),
)


def pick_fps(info: MediaInfo, cap: float) -> str:
    video = info.video
    if not video:
        return str(int(cap or 30))
    rate = parse_rate(video.r_frame_rate) or parse_rate(video.avg_frame_rate)
    if not rate:
        return str(int(cap or 30))
    if cap and rate > cap + 0.01:
        return f"{cap:g}"
    for value, label in _COMMON_RATES:
        if abs(rate - value) < 0.02:
            return label
    return f"{rate:.6f}".rstrip("0").rstrip(".")


def find_subtitle(src: Path) -> Optional[Path]:
    for ext in (".srt", ".ass", ".ssa", ".vtt"):
        candidate = src.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def video_already_compatible(item: PlanItem, ctx: Ctx) -> bool:
    """Файл уже играет на M6 — не трогаем без --normalize.

    Опираемся на проверенные файлы: MKV/H.264 + AC3 5.1 работает;
    MP4/MKV с H.264 + AAC тоже. MP4 с AC3 и AVI не считаем гарантированно
    совместимыми.
    """
    if item.kind != "video" or item.status == "failed" or not item.info:
        return False
    if item.action not in {"remux", "copy-video"}:
        return False
    fmt = (item.info.format_name or "").lower()
    is_mkv = "matroska" in fmt
    is_mp4 = "mp4" in fmt or "mov" in fmt
    if item.action == "remux":
        return is_mkv or is_mp4
    # copy-video: H.264 уже совместим, но звук не AAC. В MKV звук AC3/MP3
    # на вашем M6 работает; в MP4 — не рискуем.
    audio = item.info.audio
    codec = audio.codec_name if audio else ""
    return is_mkv and codec in {"ac3", "mp3"}


def already_compatible(item: PlanItem, ctx: Ctx) -> bool:
    """Файл уже в поддерживаемом M6 виде — по умолчанию не трогаем."""
    if item.status == "failed" or not item.info:
        return False
    if item.kind == "video":
        return video_already_compatible(item, ctx)
    if item.kind == "audio":
        # Явно запрошен другой аудиоформат — обрабатываем.
        if ctx.args.audio_format in {"aac", "copy"}:
            return False
        audio = item.info.audio
        if not audio:
            return False
        codec = (audio.codec_name or "").lower()
        suffix = item.src.suffix.lower()
        return codec in AUDIO_OK_CODECS and suffix in AUDIO_OK_EXTS
    if item.kind == "image":
        return item.src.suffix.lower() in IMAGE_OK_EXTS
    return False


def plan_video(item: PlanItem, ctx: Ctx) -> None:
    info = item.info
    assert info is not None
    video = info.video
    if not video:
        item.error = "нет видеопотока"
        return

    item.target_fps = pick_fps(info, ctx.args.fps)

    v_reasons = video_copy_reasons(info, ctx)
    a_reasons = audio_copy_reasons(info)
    if ctx.args.mode == "copy":
        if v_reasons or a_reasons:
            item.error = "режим copy: " + "; ".join(v_reasons + a_reasons)
        else:
            item.action = "remux"
            item.est_size = info.size
        return

    need_video = ctx.args.mode == "encode" or bool(v_reasons)
    need_audio = bool(info.audio) and (ctx.args.mode == "encode" or bool(a_reasons))

    if need_video:
        item.action = "transcode"
        item.reasons.extend(v_reasons or ["принудительное перекодирование видео"])
        if need_audio:
            item.reasons.extend(a_reasons)
    elif need_audio:
        item.action = "copy-video"
        item.reasons.extend(a_reasons)
    else:
        item.action = "remux"
        item.reasons.append("видео и звук совместимы — только смена контейнера")

    if ctx.args.fat32 == "off":
        item.cap = ctx.preset.maxrate
    else:
        if item.action == "remux":
            if info.size > ctx.args.max_file_size * 0.98:
                item.action = "transcode"
                item.reasons.append(
                    f"исходный файл {human_size(info.size)} близок к лимиту FAT32 — "
                    "перекодирую видео"
                )
                need_video = True
            else:
                item.est_size = info.size
        if item.action == "copy-video":
            if info.size > ctx.args.max_file_size * 0.95:
                item.action = "transcode"
                item.reasons.append(
                    "файл близок к лимиту FAT32 — перекодирую видео, чтобы "
                    "уложиться в размер"
                )
                need_video = True

    if item.action in {"transcode", "copy-video"}:
        if item.action == "transcode":
            parts, cap, why = compute_size_plan(info.duration, ctx)
            if parts > 60:
                item.error = (
                    f"при лимите {human_size(ctx.args.max_file_size)} получилось бы "
                    f"{parts} частей — увеличьте лимит или используйте --fat32 off"
                )
                return
            item.parts = parts
            item.cap = cap
            if why:
                item.reasons.append(why)
            source_rate = info.video.bit_rate if info.video else 0
            estimate_rate = cap
            if source_rate:
                estimate_rate = min(cap, max(int(source_rate * 1.3), 500_000))
            item.est_size = int(
                (estimate_rate + ctx.preset.audio_kbps * 1000 + 64_000)
                * max(info.duration, 0) / 8
            )
        else:
            item.cap = ctx.preset.maxrate
            item.est_size = info.size

    if ctx.args.burn_subs:
        subtitle = find_subtitle(item.src)
        if subtitle and ctx.has_subtitles_filter:
            item.subtitle = subtitle
            item.reasons.append(f"субтитры вжигаются: {subtitle.name}")
        elif subtitle:
            item.notes.append(
                "фильтр subtitles недоступен в этом ffmpeg — субтитры пропущены "
                "(нужна сборка с libass, например ffmpeg-full)"
            )
        else:
            item.notes.append("внешние субтитры не найдены")

    if item.action == "transcode" and not need_video and not need_audio:
        item.action = "remux"


def audio_file_reasons(info: MediaInfo, target: str) -> list:
    audio = info.audio
    if not audio:
        return ["нет аудиопотока"]
    reasons = []
    if target == "mp3":
        if audio.codec_name != "mp3":
            reasons.append(f"аудиокодек {audio.codec_name}, нужен MP3")
        if (audio.sample_rate or 44100) > 48000:
            reasons.append(f"частота {audio.sample_rate} Гц")
        if (audio.channels or 2) > 2:
            reasons.append(f"{audio.channels} каналов")
    elif target == "aac":
        if audio.codec_name != "aac":
            reasons.append(f"аудиокодек {audio.codec_name}, нужен AAC")
        if audio.profile and audio.profile.upper() != "LC":
            reasons.append(f"профиль AAC {audio.profile}")
        if (audio.sample_rate or 48000) > 48000:
            reasons.append(f"частота {audio.sample_rate} Гц")
        if (audio.channels or 2) > 2:
            reasons.append(f"{audio.channels} каналов")
    return reasons


def plan_audio(item: PlanItem, ctx: Ctx) -> None:
    info = item.info
    assert info is not None
    if not info.audio:
        item.error = "нет аудиопотока"
        return

    if ctx.args.audio_format == "copy":
        if item.src.suffix.lower() in SUPPORTED_AUDIO_COPY_EXTS:
            item.action = "copy"
            item.est_size = info.size
            item.reasons.append("формат уже поддерживается, файл копируется как есть")
        else:
            item.error = f"формат {item.src.suffix} не поддерживается головным устройством"
        return

    if ctx.args.mode == "copy":
        target = ctx.args.audio_format
        reasons = audio_file_reasons(info, target)
        if reasons:
            item.error = "режим copy: " + "; ".join(reasons)
        else:
            item.action = "remux-audio"
            item.est_size = info.size
        return

    target = ctx.args.audio_format
    reasons = audio_file_reasons(info, target)
    if ctx.args.mode == "encode":
        reasons = reasons or ["принудительное перекодирование звука"]
    if reasons:
        item.action = "transcode-audio-only"
        item.reasons.extend(reasons)
        bitrate = ctx.args.audio_bitrate
        item.est_size = int(bitrate / 8 * max(info.duration, 0)) if info.duration else info.size
    else:
        item.action = "remux-audio"
        item.est_size = info.size
        item.reasons.append("звук совместим — только перезапись тегов/контейнера")


def plan_image(item: PlanItem, ctx: Ctx) -> None:
    info = item.info
    if info and info.size:
        item.est_size = int(info.size * 1.1)
    item.action = "image"
    item.reasons.append("JPEG для просмотра на головном устройстве")
    if item.src.suffix.lower() in {".heic", ".heif"}:
        item.notes.append("HEIC будет преобразован через sips")


def assign_output(item: PlanItem, ctx: Ctx, counters: dict) -> None:
    if item.error:
        return
    kind = item.kind
    stem = safe_stem(item.src.stem, ctx.args.keep_names)
    if ctx.args.number:
        number = counters[kind]
        counters[kind] = number + 1
        base = f"{number:03d}_{stem}"
    else:
        base = stem

    if kind == "video":
        ext = ".mp4" if ctx.args.container == "mp4" else ".mkv"
    elif kind == "audio":
        if ctx.args.audio_format == "aac":
            ext = ".m4a"
        elif ctx.args.audio_format == "copy":
            ext = item.src.suffix.lower() or ".mp3"
        else:
            ext = ".mp3"
    else:
        ext = ".jpg"

    candidate = base
    suffix_no = 2
    while (candidate + ext).casefold() in ctx.used_names:
        candidate = f"{base}_{suffix_no}"
        suffix_no += 1
    ctx.used_names.add((candidate + ext).casefold())
    item.out_stem = candidate

    out_dir = ctx.output / DIRS[kind]
    if kind == "video" and item.parts > 1:
        item.out_paths = [
            out_dir / f"{candidate}_part{i:02d}{ext}"
            for i in range(1, item.parts + 1)
        ]
    else:
        item.out_paths = [out_dir / f"{candidate}{ext}"]


def build_plan(files: list, ctx: Ctx) -> list:
    items: list = []
    counters = {"video": 1, "audio": 1, "image": 1}

    for idx, path in enumerate(files, start=1):
        info = None
        probe_error = ""
        try:
            file_size = path.stat().st_size
        except OSError as exc:
            file_size = 0
            probe_error = f"нет доступа к файлу: {exc}"
        if file_size == 0 and not probe_error:
            probe_error = "файл пустой"
        if not probe_error:
            try:
                info = probe_media(path, ctx.ffprobe)
            except ProbeError as exc:
                probe_error = str(exc)

        kind = classify(path, info)
        if ctx.args.only != "all" and kind != ctx.args.only:
            continue
        item = PlanItem(idx=idx, src=path, kind=kind, info=info)
        if probe_error and kind != "image":
            item.error = f"не удалось прочитать файл: {probe_error}"
        elif kind == "unknown":
            item.error = "неизвестный тип файла"

        if not item.error:
            if kind == "video":
                plan_video(item, ctx)
            elif kind == "audio":
                plan_audio(item, ctx)
            else:
                plan_image(item, ctx)

        if item.error and item.error.startswith("пропущено"):
            item.action = "skip"
            item.status = "skipped"
            item.reasons.append(item.error)
            item.error = ""
        elif item.error:
            item.action = "error"
            item.status = "failed"

        assign_output(item, ctx, counters)
        items.append(item)

    for number, item in enumerate(items, 1):
        item.idx = number
    return items


# ---------------------------------------------------------------------------
# Команды ffmpeg
# ---------------------------------------------------------------------------

def escape_filter_path(path: Path) -> str:
    text = str(path).replace("\\", "/")
    text = text.replace(":", r"\:")
    text = text.replace("'", r"\'")
    text = text.replace("[", r"\[").replace("]", r"\]")
    text = text.replace(",", r"\,")
    return text


def build_vf(item: PlanItem, ctx: Ctx) -> str:
    info = item.info
    assert info is not None
    video = info.video
    assert video is not None
    filters = []

    if (video.field_order or "").lower() in {"tt", "bb", "tb", "bt"}:
        filters.append("yadif=deinterlace=send_frame:parity=auto:deint=all")

    if ctx.args.tonemap and is_hdr(video):
        if ctx.has_zscale:
            filters.append(
                "zscale=t=linear:npl=100,format=gbrpf32le,"
                "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
            )
        else:
            item.notes.append("HDR: zscale недоступен, тональная компрессия пропущена")

    width, height = display_size(video)
    needs_scale = (
        width > ctx.preset.max_w or height > ctx.preset.max_h
        or width % 2 or height % 2
    )
    if needs_scale:
        filters.append(
            f"scale=w='min(iw,{ctx.preset.max_w})':h='min(ih,{ctx.preset.max_h})'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2"
        )

    sar = video.sample_aspect_ratio
    if sar and sar not in {"1:1", "0:1", "N/A"}:
        filters.append("setsar=1")

    if item.subtitle:
        filters.append(
            "subtitles=filename='{}':force_style="
            "'FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,MarginV=18'"
            .format(escape_filter_path(item.subtitle))
        )
    return ",".join(filters)


def video_mux_args(ctx: Ctx) -> list:
    if getattr(ctx.args, "container", "mp4") == "mp4":
        return ["-movflags", "+faststart", "-brand", "mp42"]
    return []


def build_video_cmd(
    ctx: Ctx, item: PlanItem, out_path: Path,
    start: Optional[float] = None, duration: Optional[float] = None,
) -> list:
    preset = ctx.preset
    cap = item.cap or preset.maxrate
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    cmd += ["-stats_period", "1", "-progress", "pipe:1"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(item.src)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-map", "0:v:0"]
    if item.info and item.info.audio:
        cmd += ["-map", "0:a:0"]
    else:
        cmd += ["-an"]
    cmd += ["-map_metadata", "0", "-map_chapters", "-1", "-sn", "-dn"]

    vf = build_vf(item, ctx)
    if vf:
        cmd += ["-vf", vf]

    cmd += [
        "-c:v", "libx264", "-threads", str(ctx.args.threads),
        "-preset", ctx.args.x264_preset,
        "-crf", str(preset.crf),
        "-maxrate", str(cap), "-bufsize", str(cap * 2),
        "-profile:v", H264_OUTPUT_PROFILE, "-level:v", H264_OUTPUT_LEVEL,
        "-pix_fmt", "yuv420p",
        "-r", item.target_fps or str(int(ctx.args.fps or 30)),
        ("-fps_mode" if ctx.ffmpeg_major >= 5 else "-vsync"), "cfr",
    ]
    if item.info and item.info.audio:
        cmd += [
            "-c:a", "aac", "-b:a", f"{preset.audio_kbps}k",
            "-ar", "48000", "-ac", "2",
        ]
    cmd += video_mux_args(ctx) + [str(out_path)]
    return cmd


def build_video_copy_cmd(ctx: Ctx, item: PlanItem, out_path: Path) -> list:
    """Копирует видео, перекодирует только звук (если нужно)."""
    preset = ctx.preset
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    cmd += ["-stats_period", "1", "-progress", "pipe:1"]
    cmd += ["-i", str(item.src), "-map", "0:v:0"]
    if item.info and item.info.audio:
        cmd += ["-map", "0:a:0"]
    cmd += ["-map_metadata", "0", "-map_chapters", "-1", "-sn", "-dn", "-c:v", "copy"]
    if item.info and item.info.audio:
        cmd += [
            "-c:a", "aac", "-b:a", f"{preset.audio_kbps}k",
            "-ar", "48000", "-ac", "2",
        ]
    else:
        cmd += ["-an"]
    cmd += video_mux_args(ctx) + [str(out_path)]
    return cmd


def build_remux_cmd(ctx: Ctx, item: PlanItem, out_path: Path) -> list:
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    cmd += ["-i", str(item.src), "-map", "0:v:0"]
    if item.info and item.info.audio:
        cmd += ["-map", "0:a:0"]
    cmd += ["-map_metadata", "0", "-map_chapters", "-1", "-sn", "-dn", "-c", "copy"]
    cmd += video_mux_args(ctx) + [str(out_path)]
    return cmd


def build_audio_cmd(ctx: Ctx, item: PlanItem, out_path: Path) -> list:
    info = item.info
    assert info is not None
    target = ctx.args.audio_format
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    cmd += ["-stats_period", "1", "-progress", "pipe:1"]
    cmd += ["-i", str(item.src), "-map", "0:a:0"]
    if info.cover:
        cmd += [
            "-map", "0:v:0", "-c:v", "mjpeg", "-q:v", "2",
            "-disposition:v", "attached_pic",
        ]
    cmd += ["-map_metadata", "0"]

    if target == "mp3":
        cmd += [
            "-c:a", "libmp3lame", "-b:a", f"{ctx.args.audio_bitrate // 1000}k",
            "-ar", "44100", "-ac", "2",
            "-id3v2_version", "3", "-write_id3v1", "1",
        ]
    elif target == "aac":
        cmd += [
            "-c:a", "aac", "-b:a", f"{ctx.args.audio_bitrate // 1000}k",
            "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        ]
    else:
        raise M6Error(f"неизвестный аудиоформат: {target}")
    cmd += [str(out_path)]
    return cmd


def build_audio_remux_cmd(ctx: Ctx, item: PlanItem, out_path: Path) -> list:
    info = item.info
    assert info is not None
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    cmd += ["-i", str(item.src), "-map", "0:a:0"]
    if info.cover:
        cmd += [
            "-map", "0:v:0", "-c:v", "mjpeg", "-q:v", "2",
            "-disposition:v", "attached_pic",
        ]
    cmd += ["-c:a", "copy", "-map_metadata", "0"]
    if ctx.args.audio_format == "mp3":
        cmd += ["-id3v2_version", "3", "-write_id3v1", "1"]
    else:
        cmd += ["-movflags", "+faststart"]
    cmd += [str(out_path)]
    return cmd


# ---------------------------------------------------------------------------
# Выполнение
# ---------------------------------------------------------------------------

def split_ranges(duration: float, parts: int) -> list:
    if parts <= 1:
        return [(None, None)]
    step = duration / parts
    result = []
    for i in range(parts):
        start = i * step
        length = duration - start if i == parts - 1 else step
        result.append((start, length))
    return result


def tmp_path(out_path: Path) -> Path:
    return out_path.with_name(out_path.stem + ".part" + out_path.suffix)


def run_ffmpeg(cmd: list, duration: float, ctx: Ctx, label: str) -> None:
    ctx.log.debug("RUN: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    stderr_lines = []

    def drain() -> None:
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                stderr_lines.append(line)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    last_pct = -10
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                raw = line.split("=", 1)[1]
                try:
                    micros = int(raw)
                except ValueError:
                    continue
                if duration and duration > 0:
                    pct = max(0, min(99, int(micros / 1e6 / duration * 100)))
                    if pct >= last_pct + 10:
                        last_pct = pct
                        ctx.progress(label, pct)
            elif line.startswith("progress=") and line.endswith("end"):
                ctx.progress(label, 100)
        proc.wait()
    except BaseException:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise
    finally:
        reader.join(timeout=5)
    if proc.returncode != 0:
        tail = "\n".join(stderr_lines[-25:]).strip()
        raise M6Error(tail or f"ffmpeg завершился с кодом {proc.returncode}")


def encode_with_ffmpeg(
    ctx: Ctx, item: PlanItem, out_path: Path, cmd: list,
    duration: float, label: str,
) -> int:
    tmp = tmp_path(out_path)
    tmp.unlink(missing_ok=True)
    cmd = list(cmd[:-1]) + [str(tmp)]
    try:
        run_ffmpeg(cmd, duration, ctx, label)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise M6Error("ffmpeg не создал выходной файл")
        os.replace(tmp, out_path)
        return out_path.stat().st_size
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def check_output_limit(out: Path, item: PlanItem, ctx: Ctx) -> None:
    if ctx.args.fat32 == "off":
        return
    size = out.stat().st_size if out.exists() else 0
    if size > ctx.args.max_file_size:
        raise M6Error(
            f"выходной файл {human_size(size)} больше лимита "
            f"{human_size(ctx.args.max_file_size)}; повторите с --fat32 split "
            "или профилем compact"
        )


def remove_previous(item: PlanItem, ctx: Ctx) -> None:
    out_dir = (item.out_paths[0].parent if item.out_paths else ctx.output / DIRS[item.kind])
    for path in list(item.out_paths):
        if path.exists():
            path.unlink(missing_ok=True)
    # старые части и старый контейнер от предыдущего запуска
    if out_dir.is_dir() and item.out_stem:
        for path in out_dir.glob(f"{item.out_stem}_part*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        if item.kind == "video":
            for extension in (".mp4", ".mkv"):
                path = out_dir / f"{item.out_stem}{extension}"
                if path.exists():
                    path.unlink(missing_ok=True)
        elif item.kind == "audio":
            for extension in (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".wma"):
                path = out_dir / f"{item.out_stem}{extension}"
                if path.exists():
                    path.unlink(missing_ok=True)


def execute_transcode_video(item: PlanItem, ctx: Ctx, retry: int = 0) -> None:
    info = item.info
    assert info is not None
    parts = max(1, item.parts)
    if parts == 1:
        out = item.out_paths[0]
        label = out.name
        cmd = build_video_cmd(ctx, item, out)
        encode_with_ffmpeg(ctx, item, out, cmd, info.duration, label)
        outputs = [out]
    else:
        outputs = []
        ranges = split_ranges(info.duration, parts)
        for number, (start, length) in enumerate(ranges, 1):
            suffix = item.out_paths[0].suffix
            out = item.out_paths[0].parent / f"{item.out_stem}_part{number:02d}{suffix}"
            label = out.name
            cmd = build_video_cmd(ctx, item, out, start, length)
            encode_with_ffmpeg(ctx, item, out, cmd, length or info.duration, label)
            outputs.append(out)

    item.out_paths = outputs
    item.parts = len(outputs)
    item.duration_out = info.duration

    if ctx.args.fat32 == "off":
        return
    limit = ctx.args.max_file_size
    oversized = [path for path in outputs if path.stat().st_size > limit]
    if not oversized:
        return
    if retry >= 1:
        raise M6Error(
            f"даже после разбиения файл больше {human_size(limit)}; "
            "уменьшите битрейт или используйте --fat32 off"
        )

    biggest = max(path.stat().st_size for path in outputs)
    new_parts = max(len(outputs) + 1, int(math.ceil(biggest / (limit * 0.9))))
    if new_parts > 60:
        raise M6Error("слишком длинное видео: получилось бы больше 60 частей")
    ctx.log.warning(
        "  %s: файл больше лимита (%s), повторяю с разбиением на %d частей",
        item.src.name, human_size(limit), new_parts,
    )
    for path in outputs:
        path.unlink(missing_ok=True)
    item.parts = new_parts
    item.cap = ctx.preset.maxrate
    suffix = outputs[0].suffix
    item.out_paths = [
        outputs[0].parent / f"{item.out_stem}_part{i:02d}{suffix}"
        for i in range(1, new_parts + 1)
    ]
    execute_transcode_video(item, ctx, retry + 1)


def execute_video(item: PlanItem, ctx: Ctx) -> None:
    info = item.info
    assert info is not None
    if item.action == "remux":
        out = item.out_paths[0]
        cmd = build_remux_cmd(ctx, item, out)
        encode_with_ffmpeg(
            ctx, item, out, cmd, info.duration, out.name
        )
        item.duration_out = info.duration
        check_output_limit(out, item, ctx)
        return
    if item.action == "copy-video":
        out = item.out_paths[0]
        cmd = build_video_copy_cmd(ctx, item, out)
        encode_with_ffmpeg(
            ctx, item, out, cmd, info.duration, out.name
        )
        item.duration_out = info.duration
        check_output_limit(out, item, ctx)
        return
    execute_transcode_video(item, ctx)


def execute_audio(item: PlanItem, ctx: Ctx) -> None:
    info = item.info
    assert info is not None
    out = item.out_paths[0]
    label = out.name
    if item.action == "copy":
        tmp = tmp_path(out)
        tmp.unlink(missing_ok=True)
        try:
            shutil.copy2(item.src, tmp)
            os.replace(tmp, out)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        item.duration_out = info.duration
    elif item.action == "remux-audio":
        cmd = build_audio_remux_cmd(ctx, item, out)
        encode_with_ffmpeg(ctx, item, out, cmd, info.duration, label)
        item.duration_out = info.duration
    else:
        cmd = build_audio_cmd(ctx, item, out)
        encode_with_ffmpeg(ctx, item, out, cmd, info.duration, label)
        item.duration_out = info.duration

    if out.stat().st_size > ctx.args.max_file_size and ctx.args.fat32 != "off":
        raise M6Error(f"аудиофайл больше {human_size(ctx.args.max_file_size)}")


def sips_dimensions(path: Path, sips: str) -> Optional[tuple]:
    cp = run_cmd([sips, "-g", "pixelWidth", "-g", "pixelHeight", str(path)], timeout=30)
    if cp.returncode != 0:
        return None
    width = height = 0
    for line in cp.stdout.splitlines():
        if "pixelWidth:" in line:
            try:
                width = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif "pixelHeight:" in line:
            try:
                height = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return (width, height) if width and height else None


def convert_image(item: PlanItem, ctx: Ctx) -> int:
    out = item.out_paths[0]
    tmp = tmp_path(out)
    tmp.unlink(missing_ok=True)
    ctx.log.debug("IMAGE: %s -> %s", item.src, out)

    dims = sips_dimensions(item.src, ctx.sips) if ctx.sips else None
    if not dims and item.info and item.info.video:
        dims = (item.info.video.width or 0, item.info.video.height or 0)
    max_side = max(dims) if dims else 0
    resize = ctx.args.photo_max > 0 and (max_side <= 0 or max_side > ctx.args.photo_max)
    if ctx.sips:
        cmd = [
            ctx.sips, "-s", "format", "jpeg",
            "-s", "formatOptions", str(ctx.args.photo_quality),
        ]
        if resize:
            cmd += ["--resampleHeightWidthMax", str(ctx.args.photo_max)]
        cmd += [str(item.src), "--out", str(tmp)]
        cp = run_cmd(cmd, timeout=180)
        if cp.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
            os.replace(tmp, out)
            return out.stat().st_size
        ctx.log.debug(
            "sips failed: %s",
            (cp.stderr or "").strip().splitlines()[-1:] or "unknown error",
        )
        tmp.unlink(missing_ok=True)

    # ImageMagick (Windows/Linux) — понимает HEIC/RAW при установленных
    # делегатах и не требует знания размеров: ">" не увеличивает картинку.
    if ctx.magick:
        cmd = [ctx.magick, str(item.src), "-auto-orient"]
        if ctx.args.photo_max > 0:
            cmd += ["-resize", f"{ctx.args.photo_max}x{ctx.args.photo_max}>"]
        cmd += ["-quality", str(ctx.args.photo_quality), str(tmp)]
        cp = run_cmd(cmd, timeout=180)
        if cp.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
            os.replace(tmp, out)
            return out.stat().st_size
        ctx.log.debug(
            "ImageMagick failed: %s",
            (cp.stderr or "").strip().splitlines()[-1:] or "unknown error",
        )
        tmp.unlink(missing_ok=True)

    # Запасной вариант — ffmpeg. HEIC/RAW он может не понять.
    cmd = [
        ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(item.src), "-frames:v", "1",
    ]
    filters = []
    if resize:
        filters.append(
            f"scale=w='min(iw,{ctx.args.photo_max})':h='min(ih,{ctx.args.photo_max})'"
            ":force_original_aspect_ratio=decrease"
        )
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-q:v", "2", str(tmp)]
    cp = run_cmd(cmd, timeout=180)
    if cp.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tail = (cp.stderr or "").strip().splitlines()[-1:] or ["ffmpeg failed"]
        raise M6Error(
            "не удалось преобразовать изображение в JPEG: " + " / ".join(tail)
        )
    os.replace(tmp, out)
    return out.stat().st_size


def execute_item(item: PlanItem, ctx: Ctx) -> PlanItem:
    if item.status in {"failed", "skipped"} or item.action in {"error", "skip"}:
        return item
    if not item.out_paths:
        item.status = "failed"
        item.error = "не определено имя выходного файла"
        return item

    out_dir = item.out_paths[0].parent
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        item.status = "failed"
        item.error = f"не удалось создать папку {out_dir}: {exc}"
        return item

    existing = [path for path in item.out_paths if path.exists()]
    if existing and not ctx.args.force:
        item.status = "skipped"
        item.notes.append(
            f"файл уже существует: {existing[0].name} — пропускаю "
            "(--force для перезаписи)"
        )
        ctx.log.info("  SKIP %s: %s", item.src.name, item.notes[-1])
        return item
    if ctx.args.force:
        remove_previous(item, ctx)

    ctx.log.info("  .... %s", item.src.name)
    try:
        if item.kind == "video":
            execute_video(item, ctx)
        elif item.kind == "audio":
            execute_audio(item, ctx)
        elif item.kind == "image":
            convert_image(item, ctx)
        else:
            raise M6Error(f"неизвестный тип: {item.kind}")
        item.status = "ok"
        item.error = ""
        total = sum(path.stat().st_size for path in item.out_paths if path.exists())
        item.est_size = total
        ctx.log.info(
            "  OK   %s -> %s (%s)",
            item.src.name,
            ", ".join(path.name for path in item.out_paths),
            human_size(total),
        )
    except (M6Error, OSError) as exc:
        item.status = "failed"
        item.error = str(exc)
        for path in item.out_paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        ctx.log.error("  FAIL %s: %s", item.src.name, item.error)
    return item


# ---------------------------------------------------------------------------
# Проверка результата
# ---------------------------------------------------------------------------

def verify_media(path: Path, item: PlanItem, ctx: Ctx) -> list:
    issues = []
    try:
        info = probe_media(path, ctx.ffprobe)
    except ProbeError as exc:
        return [f"файл не читается: {exc}"]

    if item.kind == "video":
        if path.suffix.lower() == ".mkv":
            if "matroska" not in info.format_name:
                issues.append(f"контейнер {info.format_name}, ожидался MKV")
        elif "mp4" not in info.format_name and "mov" not in info.format_name:
            issues.append(f"контейнер {info.format_name}, ожидался MP4")
        video = info.video
        if not video:
            issues.append("нет видеопотока")
        else:
            if video.codec_name != "h264":
                issues.append(f"видеокодек {video.codec_name}, ожидался H.264")
            if (video.profile or "").lower() not in H264_OK_PROFILES:
                issues.append(f"профиль {video.profile}")
            if video.pix_fmt != "yuv420p":
                issues.append(f"pix_fmt {video.pix_fmt}")
            if video.level and video.level > 41:
                issues.append(f"level {video.level / 10:.1f}")
            width, height = display_size(video)
            if width > ctx.preset.max_w or height > ctx.preset.max_h:
                issues.append(f"размер {width}x{height}")
            fps = parse_rate(video.r_frame_rate) or parse_rate(video.avg_frame_rate)
            if ctx.args.fps and fps and fps > ctx.args.fps + 0.5:
                issues.append(f"{fps:g} кадр/с")
        audio = info.audio
        if audio:
            if audio.codec_name != "aac":
                issues.append(f"аудиокодек {audio.codec_name}, ожидался AAC")
            if (audio.channels or 2) > 2:
                issues.append(f"{audio.channels} каналов")
    elif item.kind == "audio":
        audio = info.audio
        if not audio:
            issues.append("нет аудиопотока")
        else:
            suffix = path.suffix.lower().lstrip(".")
            target = "aac" if suffix in {"m4a", "aac"} else suffix
            if target == "mp3" and audio.codec_name != "mp3":
                issues.append(f"кодек {audio.codec_name}, ожидался MP3")
            if target == "aac" and audio.codec_name != "aac":
                issues.append(f"кодек {audio.codec_name}, ожидался AAC")
            if (audio.channels or 2) > 2:
                issues.append(f"{audio.channels} каналов")
    elif item.kind == "image":
        video = info.video
        if not video or video.codec_name not in {"mjpeg", "jpg"}:
            issues.append(f"кодек {video.codec_name if video else '?'}, ожидался JPEG")
        elif ctx.args.photo_max > 0:
            width, height = display_size(video)
            if width > ctx.args.photo_max or height > ctx.args.photo_max:
                issues.append(f"размер {width}x{height} > {ctx.args.photo_max}")

    if info.size > ctx.args.max_file_size and ctx.args.fat32 != "off":
        issues.append(f"размер {human_size(info.size)} > {human_size(ctx.args.max_file_size)}")
    if item.parts == 1 and item.info and item.info.duration > 0:
        delta = abs(info.duration - item.info.duration)
        if delta > max(3.0, item.info.duration * 0.02):
            issues.append(f"длительность {info.duration:.1f} вместо {item.info.duration:.1f}")
    return issues


def verify_items(items: list, ctx: Ctx) -> None:
    for item in items:
        if item.status != "ok":
            continue
        for path in item.out_paths:
            issues = verify_media(path, item, ctx)
            if issues:
                item.status = "failed"
                item.error = "; ".join(issues)
                ctx.log.error("  CHECK FAIL %s: %s", path.name, item.error)
            else:
                ctx.log.debug("  CHECK OK %s", path.name)


# ---------------------------------------------------------------------------
# Отчёты и диагностика
# ---------------------------------------------------------------------------

def item_to_dict(item: PlanItem) -> dict:
    outputs = []
    for path in item.out_paths:
        outputs.append({
            "path": str(path),
            "size": path.stat().st_size if path.exists() else None,
        })
    return {
        "index": item.idx,
        "source": str(item.src),
        "type": item.kind,
        "action": item.action,
        "status": item.status,
        "outputs": outputs,
        "parts": item.parts,
        "reasons": item.reasons,
        "notes": item.notes,
        "error": item.error,
        "source_media": item.info.to_dict() if item.info else None,
    }


def summarize(items: list) -> dict:
    summary = {"total": len(items), "ok": 0, "failed": 0, "skipped": 0}
    for item in items:
        if item.status == "ok":
            summary["ok"] += 1
        elif item.status == "skipped":
            summary["skipped"] += 1
        else:
            summary["failed"] += 1
    summary["bytes_out"] = sum(
        path.stat().st_size
        for item in items for path in item.out_paths if path.exists()
    )
    return summary


def write_manifest(items: list, ctx: Ctx, started: float) -> None:
    if not ctx.args.manifest:
        return
    manifest_dir = ctx.output / "_m6media"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    summary = summarize(items)
    data = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "created": created,
        "ffmpeg": ctx.ffmpeg_version,
        "settings": {
            "preset": ctx.preset.name,
            "container": ctx.args.container,
            "normalize": ctx.args.normalize,
            "jobs": ctx.args.jobs,
            "threads": ctx.args.threads,
            "mode": ctx.args.mode,
            "fat32": ctx.args.fat32,
            "max_file_size": ctx.args.max_file_size,
            "max_width": ctx.preset.max_w,
            "max_height": ctx.preset.max_h,
            "fps": ctx.args.fps,
            "crf": ctx.preset.crf,
            "video_maxrate": ctx.preset.maxrate,
            "audio_format": ctx.args.audio_format,
            "audio_bitrate": ctx.args.audio_bitrate,
            "photo_max": ctx.args.photo_max,
            "photo_quality": ctx.args.photo_quality,
            "keep_names": ctx.args.keep_names,
            "filesystem": ctx.fs_name,
        },
        "summary": summary,
        "items": [item_to_dict(item) for item in items],
    }
    json_path = manifest_dir / "manifest.json"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    csv_path = manifest_dir / "manifest.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([
            "index", "type", "status", "action", "source", "outputs",
            "size_out", "reason", "error",
        ])
        for item in items:
            writer.writerow([
                item.idx, item.kind, item.status, item.action, str(item.src),
                " | ".join(str(path) for path in item.out_paths),
                sum(path.stat().st_size for path in item.out_paths if path.exists()),
                " | ".join(item.reasons + item.notes), item.error,
            ])
    log_path = manifest_dir / "run.log"
    if log_path.exists():
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                for item in items:
                    if item.status == "skipped":
                        handle.write(
                            f"{created} INFO SKIP {item.src.name}: "
                            f"{'; '.join(item.notes) or item.error}\n"
                        )
        except OSError:
            pass
    ctx.log.info("Отчёт: %s", json_path)
    ctx.log.info("Отчёт: %s", csv_path)


def print_plan(items: list, ctx: Ctx, diagnostics: bool = False) -> None:
    print()
    if diagnostics:
        print("ДИАГНОСТИКА ФАЙЛОВ")
    else:
        print("ПЛАН ОБРАБОТКИ")
    print("=" * 78)
    for item in items:
        info = item.info
        out = ", ".join(str(path) for path in item.out_paths) or "—"
        if item.status == "failed":
            status = "FAIL"
        elif item.status == "skipped":
            status = "SKIP"
        else:
            status = "OK  "
        print(f"[{item.idx:03d}] {status} {item.kind.upper():5} {item.src}")
        if info:
            if info.video:
                width, height = display_size(info.video)
                fps = parse_rate(info.video.r_frame_rate)
                print(
                    f"       видео: {info.video.codec_name} "
                    f"{info.video.profile or ''} level={info.video.level or '?'} "
                    f"{width}x{height} {fps:g} fps {info.video.pix_fmt or ''}"
                    if fps else
                    f"       видео: {info.video.codec_name} "
                    f"{info.video.profile or ''} level={info.video.level or '?'} "
                    f"{width}x{height} {info.video.pix_fmt or ''}"
                )
            if info.audio:
                print(
                    f"       звук:  {info.audio.codec_name} "
                    f"{info.audio.channels or '?'} каналов, "
                    f"{info.audio.sample_rate or '?'} Гц"
                )
            print(
                f"       файл:  {info.format_name}, {human_duration(info.duration)}, "
                f"{human_size(info.size)}"
            )
        print(f"       => {out}")
        print(f"       действие: {item.action}", end="")
        if item.parts > 1:
            print(f" ({item.parts} частей)", end="")
        print()
        if item.action == "copy-video":
            print("       (видео копируется без перекодирования; меняется контейнер, звук → AAC)")
        for reason in item.reasons:
            print(f"       • {reason}")
        for note in item.notes:
            print(f"       ! {note}")
        if item.error:
            print(f"       ОШИБКА: {item.error}")
    print("=" * 78)
    sys.stdout.flush()


def print_header(ctx: Ctx, items: list) -> None:
    counts = {"video": 0, "audio": 0, "image": 0}
    actions = {}
    work = [item for item in items if item.status != "skipped"]
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    for item in work:
        actions[item.action] = actions.get(item.action, 0) + 1
    print()
    print(f"{APP_NAME} {APP_VERSION} — Haval M6 (2023) media preparation")
    print(f"ffmpeg: {ctx.ffmpeg_version}")
    print(f"Выход:  {ctx.output}")
    if ctx.fs_name:
        print(f"ФС:     {ctx.fs_name}")
    print(
        "Режим:  "
        + ("normalize — обработать всё" if ctx.args.normalize
           else "только несовместимое (совместимое пропускается)")
    )
    print(
        f"Профиль: {ctx.preset.name} — до {ctx.preset.max_w}x{ctx.preset.max_h}, "
        f"{ctx.args.fps:g} fps, CRF {ctx.preset.crf}, "
        f"до {ctx.preset.maxrate / 1e6:.1f} Мбит/с, "
        f"контейнер {ctx.args.container.upper()}"
    )
    print(
        f"Файлов: {len(items)} (видео {counts.get('video', 0)}, "
        f"музыка {counts.get('audio', 0)}, фото {counts.get('image', 0)}); "
        f"к обработке: {len(work)}; пропущено: {len(items) - len(work)}"
    )
    for action, count in sorted(actions.items()):
        print(f"  {action}: {count}")
    if len(work) < len(items):
        print("  совместимые файлы не трогаются (--normalize — обработать всё)")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Файлы, ФС, USB
# ---------------------------------------------------------------------------

def collect_files(
    inputs: list, output: Path, excludes: list, exclude_output: bool = True,
) -> list:
    skip_ext = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".nfo", ".url", ".lnk"}
    found = []
    seen = set()
    output_resolved = output.resolve()

    def is_excluded(path: Path) -> bool:
        name = path.name
        for pattern in excludes:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str(path), pattern):
                return True
        return False

    for raw in inputs:
        path = Path(raw).expanduser()
        if not path.exists():
            eprint(f"  ! не найдено: {path}")
            continue
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = []
            for root, dirs, names in os.walk(path):
                root_path = Path(root)
                dirs[:] = sorted(
                    d for d in dirs
                    if not d.startswith(".")
                    and d.upper() not in {
                        "_M6MEDIA", "LOST.DIR", "SYSTEM VOLUME INFORMATION",
                        "$RECYCLE.BIN",
                    }
                    and not (root_path / d).is_symlink()
                    and (root_path / d).resolve() != output_resolved
                )
                video_stems = {
                    Path(name).stem.lower() for name in names
                    if Path(name).suffix.lower() in VIDEO_EXTS
                    and not name.startswith("._")
                }
                for name in sorted(names):
                    if name.startswith("._") or name.startswith(".") or name in SKIP_NAMES:
                        continue
                    suffix = Path(name).suffix.lower()
                    if suffix in skip_ext:
                        continue
                    # Внешние аудиодорожки рядом с фильмом (Movie.Ukr.ac3)
                    if suffix in {".ac3", ".dts", ".mka"}:
                        stem = Path(name).stem.lower()
                        if any(
                            stem == vs or stem.startswith(vs + ".")
                            or stem.startswith(vs + "_")
                            for vs in video_stems
                        ):
                            continue
                    candidates.append(root_path / name)
        else:
            continue

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if exclude_output and (
                    resolved == output_resolved or output_resolved in resolved.parents
                ):
                    continue
                if resolved in seen:
                    continue
                if is_excluded(candidate):
                    continue
                if candidate.is_symlink():
                    continue
                seen.add(resolved)
                found.append(candidate)
            except OSError:
                continue

    def natural_key(path: Path):
        return [
            int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", str(path))
        ]

    found.sort(key=natural_key)
    return found


def has_output_media(output: Path) -> bool:
    for folder in DIRS.values():
        path = output / folder
        if path.is_dir():
            for item in path.iterdir():
                if item.is_file():
                    return True
    return False


def find_mount_point(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = Path(os.path.abspath(str(path)))
    if os.name == "nt":
        # Windows: "D:\\" или "\\server\share\".
        anchor = resolved.anchor
        return Path(anchor) if anchor else resolved
    current = resolved
    while not os.path.ismount(current):
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def filesystem_type(path: Path) -> str:
    try:
        mount = find_mount_point(path)
    except OSError:
        return "unknown"
    if sys.platform == "darwin":
        cp = run_cmd(["diskutil", "info", str(mount)], timeout=30)
        if cp.returncode == 0:
            match = re.search(r"File System Personality:\s*(.+)", cp.stdout)
            if match:
                return match.group(1).strip()
        return "unknown"
    if os.name == "nt":
        try:
            import ctypes

            root = str(mount)
            if not root.endswith("\\"):
                root += "\\"
            volume = ctypes.create_unicode_buffer(261)
            fs_name = ctypes.create_unicode_buffer(261)
            serial = ctypes.c_uint()
            max_component = ctypes.c_uint()
            flags = ctypes.c_uint()
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                root, volume, 261,
                ctypes.byref(serial), ctypes.byref(max_component),
                ctypes.byref(flags), fs_name, 261,
            )
            if ok and fs_name.value:
                return fs_name.value
        except (AttributeError, OSError, ValueError):
            pass
        return "unknown"
    if sys.platform.startswith("linux"):
        cp = run_cmd(["stat", "-f", "-c", "%T", str(mount)], timeout=30)
        if cp.returncode == 0:
            return cp.stdout.strip()
        return "unknown"
    return "unknown"


def resolve_filesystem_mode(args: argparse.Namespace, output: Path) -> tuple:
    mount = find_mount_point(output)
    fs_name = filesystem_type(output)
    if args.fat32 != "auto":
        return args.fat32, fs_name
    low = fs_name.lower()
    if "exfat" in low:
        return "off", fs_name
    if "ntfs" in low:
        return "off", fs_name
    return "fit", fs_name


def check_usb(ctx: Ctx, items: list) -> None:
    mount = find_mount_point(ctx.output)
    low = (ctx.fs_name or "").lower()
    if ctx.args.usb:
        system_drive = os.environ.get("SystemDrive", "C:").upper()
        on_system_drive = (
            os.name == "nt"
            and str(mount).upper().rstrip("\\/") == system_drive
        )
        if mount == Path("/") or on_system_drive:
            raise M6Error("выходная папка не на съёмном носителе")
        if not any(token in low for token in ("fat", "msdos", "vfat", "exfat")):
            if not ctx.args.allow_any_fs:
                raise M6Error(
                    f"файловая система {ctx.fs_name!r} не поддерживается "
                    "головным устройством (нужны FAT16/FAT32; exFAT работает "
                    "на практике). Используйте --allow-any-fs, чтобы продолжить."
                )
        if "exfat" in low:
            ctx.log.warning(
                "  ! exFAT: инструкция обещает только FAT16/FAT32, "
                "но на практике exFAT часто работает. Если M6 не увидит "
                "флешку — переформатируйте её в FAT32."
            )
        if "fat" in low and "exfat" not in low:
            ctx.log.info(
                "  Лимит FAT16/FAT32: файлы должны быть меньше %s — "
                "включено разбиение.",
                human_size(ctx.args.max_file_size),
            )

    estimate = sum(
        item.est_size for item in items
        if item.status not in {"failed", "skipped"}
    )
    if estimate:
        free = shutil.disk_usage(str(mount)).free
        ctx.log.info(
            "  Свободно на носителе: %s, оценка результата: %s",
            human_size(free), human_size(estimate),
        )
        if free < estimate * 0.9:
            ctx.log.warning(
                "  ! свободного места может не хватить; освободите %.1f ГиБ",
                (estimate * 1.02 - free) / GIB,
            )


# ---------------------------------------------------------------------------
# Проверка готовой папки
# ---------------------------------------------------------------------------

def check_only(ctx: Ctx) -> int:
    if ctx.args.inputs:
        probe_target = Path(ctx.args.inputs[0]).expanduser()
        fs_name = filesystem_type(probe_target)
        if fs_name:
            ctx.fs_name = fs_name
            low = fs_name.lower()
            if getattr(ctx.args, "fat32_auto", False):
                if "exfat" in low or "ntfs" in low:
                    ctx.args.fat32 = "off"
                elif "fat" in low:
                    ctx.args.fat32 = "fit"
        files = collect_files(
            ctx.args.inputs, ctx.output, ctx.args.exclude, exclude_output=False
        )
        where = ", ".join(str(Path(item).expanduser()) for item in ctx.args.inputs)
    else:
        if not ctx.output.is_dir():
            raise M6Error(f"папка не найдена: {ctx.output}")
        files = []
        for folder in DIRS.values():
            path = ctx.output / folder
            if path.is_dir():
                files.extend(sorted(path.rglob("*")))
        files = [path for path in files if path.is_file()]
        where = str(ctx.output)

    if not files:
        raise M6Error("не найдено файлов для проверки")
    print(f"Проверка: {where} ({len(files)} файлов)")
    bad = 0
    for number, path in enumerate(files, 1):
        try:
            info = probe_media(path, ctx.ffprobe)
        except ProbeError as exc:
            print(f"[{number:03d}] FAIL {path.name}: {exc}")
            bad += 1
            continue
        kind = classify(path, info)
        if kind == "unknown":
            print(f"[{number:03d}] SKIP {path.name}: неизвестный тип")
            continue
        item = PlanItem(idx=number, src=path, kind=kind, info=info)
        issues = verify_media(path, item, ctx)
        if issues:
            print(f"[{number:03d}] FAIL {path.name}: {'; '.join(issues)}")
            bad += 1
        else:
            print(f"[{number:03d}] OK   {path.name}")
    print(f"\nИтог: {len(files) - bad} OK, {bad} с ошибками")
    return 0 if bad == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Подготовка видео, музыки и фото для мультимедиа Haval M6 (2023): "
            "H.264/AAC MP4 или MKV, MP3, JPEG."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  ./m6media.py ~/Movies -o ~/m6-ready\n"
            "  ./m6media.py /Volumes/USB -o /Volumes/USB/M6 --usb --only video\n"
            "  ./m6media.py /Volumes/USB --diagnose --only video\n"
            "  ./m6media.py ~/m6-ready --check-only\n"
            "\n"
            "Форматы из инструкции Haval M6 Plus (2023–2026):\n"
            "  видео: WMV, MP4, MPEG, AVI, 3GP, MKV, MOV, ASF, VOB\n"
            "  аудио: MP3, WMA, AAC, FLAC, WAV, OGG\n"
            "  фото:  JPG, PNG, BMP\n"
            "  USB:   FAT16 или FAT32 (exFAT на практике работает)\n"
        ),
    )
    parser.add_argument("inputs", nargs="*", help="файлы и/или папки")
    parser.add_argument(
        "-o", "--output", default=None,
        help="папка результата (по умолчанию M6 рядом с исходниками)",
    )
    parser.add_argument(
        "--preset", choices=sorted(PRESETS), default="compat",
        help="профиль качества (по умолчанию compat)",
    )
    parser.add_argument(
        "--mode", choices=("auto", "copy", "encode"), default="auto",
        help="auto — конвертировать только несовместимое; copy — не перекодировать; "
             "encode — перекодировать всё",
    )
    parser.add_argument(
        "--container", choices=("mp4", "mkv"), default="mp4",
        help="контейнер видео (по умолчанию mp4; mkv — если M6 капризничает с MP4)",
    )
    parser.add_argument(
        "--only", choices=("all", "video", "audio", "image"), default="all",
        help="обрабатывать только один тип файлов",
    )
    parser.add_argument(
        "--normalize", action="store_true",
        help="обработать все файлы, включая уже совместимые (по умолчанию "
             "совместимое видео не трогается)",
    )
    # Оставлено для совместимости со старыми командами: теперь это поведение
    # по умолчанию.
    parser.add_argument("--only-problem", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--fat32", choices=("auto", "fit", "split", "off"), default="auto",
        help="auto — по файловой системе; fit — ужать битрейт под 4 ГиБ; "
             "split — разбить; off — не ограничивать",
    )
    parser.add_argument(
        "--max-file-size", type=parse_size, default=DEFAULT_MAX_FILE,
        help=f"лимит файла (по умолчанию {DEFAULT_MAX_FILE / GIB:.1f} ГиБ)",
    )
    parser.add_argument("--max-width", type=int, default=0, help="макс. ширина видео")
    parser.add_argument("--max-height", type=int, default=0, help="макс. высота видео")
    parser.add_argument("--fps", type=float, default=None, help="макс. кадров/с (0 = не ограничивать)")
    parser.add_argument("--video-crf", type=int, default=0, help="CRF x264 (0 = из профиля)")
    parser.add_argument(
        "--x264-preset", default="medium",
        choices=("ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow"),
        help="скорость/качество x264 (по умолчанию medium; veryfast — быстрее)",
    )
    parser.add_argument(
        "--video-maxrate", type=parse_bitrate, default=None,
        help="макс. битрейт видео, например 8M",
    )
    parser.add_argument(
        "--audio-format", choices=("mp3", "aac", "copy"), default="mp3",
        help="формат музыки (по умолчанию mp3)",
    )
    parser.add_argument(
        "--audio-bitrate", type=parse_bitrate, default=256_000,
        help="битрейт музыки (по умолчанию 256k)",
    )
    parser.add_argument(
        "--photo-max", type=int, default=1920,
        help="макс. сторона фото, px (0 = не уменьшать)",
    )
    parser.add_argument("--photo-quality", type=int, default=90, help="качество JPEG 1–100")
    parser.add_argument(
        "--jobs", type=int, default=0,
        help="параллельных задач (0 = авто по числу ядер; для USB лучше 1–2)",
    )
    parser.add_argument(
        "--threads", type=int, default=0,
        help="потоков x264 на задачу (0 = авто: ядра / jobs)",
    )
    parser.add_argument("--dry-run", action="store_true", help="только показать план")
    parser.add_argument(
        "--diagnose", action="store_true",
        help="подробная диагностика совместимости без обработки",
    )
    parser.add_argument("--force", action="store_true", help="перезаписать готовые файлы")
    parser.add_argument(
        "--keep-names", action="store_true",
        help="не транслитерировать имена (кириллица/пробелы сохраняются)",
    )
    parser.add_argument(
        "--number", action="store_true",
        help="добавлять номера 001_, 002_ … к именам (по умолчанию без номеров)",
    )
    parser.add_argument("--no-manifest", action="store_false", dest="manifest",
                        help="не писать JSON/CSV-отчёт")
    parser.add_argument("--check", action="store_true", help="проверить результат после обработки")
    parser.add_argument("--check-only", action="store_true", help="только проверить готовую папку")
    parser.add_argument("--burn-subs", action="store_true", help="вжечь внешние .srt/.ass")
    parser.add_argument("--tonemap", action="store_true", help="HDR → SDR (zscale)")
    parser.add_argument("--usb", action="store_true", help="выход прямо на USB-носитель")
    parser.add_argument("--allow-any-fs", action="store_true",
                        help="разрешить не-FAT файловую систему с --usb")
    parser.add_argument("--exclude", action="append", default=[],
                        help="исключить файлы по маске (можно несколько раз)")
    parser.add_argument("--verbose", action="store_true", help="подробный журнал")
    parser.add_argument("--ffmpeg", help="путь к ffmpeg")
    parser.add_argument("--ffprobe", help="путь к ffprobe")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser


def setup_logger(verbose: bool) -> logging.Logger:
    logger = logging.getLogger(APP_NAME)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def default_output(inputs: list) -> Path:
    """Куда писать по умолчанию: M6 рядом с исходниками."""
    paths = [Path(item).expanduser() for item in inputs]
    if len(paths) == 1:
        path = paths[0]
        return (path if path.is_dir() else path.parent) / "M6"
    parents = set()
    for path in paths:
        parents.add(path if path.is_dir() else path.parent)
    if len(parents) == 1:
        return parents.pop() / "M6"
    return Path.cwd() / "M6"


def create_ctx(args: argparse.Namespace) -> Ctx:
    logger = setup_logger(args.verbose)

    ffmpeg = find_tool("ffmpeg", args.ffmpeg)
    ffprobe = find_tool("ffprobe", args.ffprobe)
    if not ffmpeg or not ffprobe:
        raise M6Error(
            "не найден ffmpeg/ffprobe.\n"
            "  macOS:   brew install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg"
        )
    version_cp = run_cmd([ffmpeg, "-version"], timeout=30)
    ffmpeg_version = version_cp.stdout.splitlines()[0] if version_cp.stdout else "ffmpeg"
    version_match = re.search(r"ffmpeg version\s+(\d+)", ffmpeg_version)
    ffmpeg_major = int(version_match.group(1)) if version_match else 0
    encoders = run_cmd([ffmpeg, "-hide_banner", "-encoders"], timeout=30).stdout
    if "libx264" not in encoders:
        raise M6Error("в ffmpeg нет libx264 — установите полную сборку ffmpeg")
    if args.audio_format == "mp3" and "libmp3lame" not in encoders:
        raise M6Error("в ffmpeg нет libmp3lame — установите полную сборку ffmpeg")
    filters = run_cmd([ffmpeg, "-hide_banner", "-filters"], timeout=30).stdout
    has_zscale = "zscale" in filters
    has_subtitles = "subtitles" in filters
    sips = shutil.which("sips") if sys.platform == "darwin" else None
    magick = shutil.which("magick")

    preset = PRESETS[args.preset]
    max_w = args.max_width or preset.max_w
    max_h = args.max_height or preset.max_h
    if max_w < 64 or max_h < 64:
        raise M6Error("--max-width/--max-height слишком малы")
    if args.video_crf and not 0 <= args.video_crf <= 51:
        raise M6Error("--video-crf должен быть в диапазоне 0…51")
    if not 1 <= args.photo_quality <= 100:
        raise M6Error("--photo-quality должен быть в диапазоне 1…100")
    if args.photo_max < 0:
        raise M6Error("--photo-max не может быть отрицательным")
    if args.fps is None:
        fps = preset.fps
    elif args.fps <= 0:
        fps = 0.0
    else:
        fps = args.fps
    args.fps = fps
    preset = Preset(
        preset.name, max_w, max_h,
        args.video_crf or preset.crf,
        args.video_maxrate or preset.maxrate,
        preset.audio_kbps, fps,
    )

    if not args.output:
        args.output = str(default_output(args.inputs or ["."]))
    output = Path(args.output).expanduser()
    try:
        output = output.resolve()
    except OSError:
        pass
    if output.exists() and not output.is_dir():
        raise M6Error(f"выходной путь существует и это не папка: {output}")
    for raw in args.inputs:
        try:
            if Path(raw).expanduser().resolve() == output:
                raise M6Error("выходная папка совпадает с входной")
        except OSError:
            continue

    if args.jobs <= 0:
        # 4 параллельных x264 на 8 ядрах передерутся за CPU и USB.
        args.jobs = min(4, max(1, (os.cpu_count() or 4) // 4))
    if args.threads <= 0:
        args.threads = max(1, (os.cpu_count() or 4) // max(1, args.jobs))
    args.jobs = max(1, args.jobs)
    args.threads = max(1, args.threads)

    args.fat32_auto = args.fat32 == "auto"
    fs_mode, fs_name = resolve_filesystem_mode(args, output)
    args.fat32 = fs_mode

    used_names = set()
    return Ctx(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        preset=preset,
        args=args,
        output=output,
        used_names=used_names,
        lock=threading.Lock(),
        log=logger,
        has_zscale=has_zscale,
        has_subtitles_filter=has_subtitles,
        sips=sips,
        magick=magick,
        ffmpeg_version=ffmpeg_version,
        ffmpeg_major=ffmpeg_major,
        fs_name=fs_name,
    )


def mark_existing_skips(items: list, ctx: Ctx) -> list:
    """Помечает файлы, которые уже есть в выходной папке, как пропущенные."""
    skipped = []
    if ctx.args.force:
        return skipped
    for item in items:
        if item.status in {"failed", "skipped"} or item.action in {"error", "skip"}:
            continue
        existing = [path for path in item.out_paths if path.exists()]
        if existing:
            item.status = "skipped"
            item.action = "skip-existing"
            item.notes.insert(
                0,
                f"файл уже существует: {existing[0].name} — пропускаю "
                "(--force для перезаписи)",
            )
            item.reasons = []
            skipped.append(item)
    return skipped


def print_skipped_summary(items: list, ctx: Ctx) -> None:
    skipped = [item for item in items if item.status == "skipped"]
    if not skipped:
        return
    print("\nПропущено:")
    for item in skipped:
        reason = item.notes[0] if item.notes else (item.error or "нет причины")
        print(f"  - {item.src.name}: {reason}")
    sys.stdout.flush()


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.time()
    try:
        if args.diagnose:
            args.dry_run = True
            args.verbose = True
        if args.mode == "encode":
            args.normalize = True
        inputs = args.inputs or ["."]
        if args.output is None:
            args.output = str(default_output(inputs))
        ctx = create_ctx(args)
        ctx.fs_name = filesystem_type(ctx.output)

        if args.check_only:
            return check_only(ctx)
        files = collect_files(inputs, ctx.output, args.exclude)
        if not files:
            raise M6Error("не найдено ни одного файла для обработки")

        items = build_plan(files, ctx)
        if not items:
            raise M6Error(
                "не найдено файлов выбранного типа"
                + (f" ({args.only})" if args.only != "all" else "")
            )

        work, skipped = [], []
        if not args.normalize:
            for item in items:
                if already_compatible(item, ctx):
                    item.status = "skipped"
                    item.notes.append(
                        "уже совместимо с M6 — не трогаю "
                        "(--normalize, если нужно перепаковать всё равно)"
                    )
                    item.notes.append(f"исходное действие было: {item.action}")
                    item.reasons = []
                    item.action = "skip-compatible"
                    item.out_paths = []
                    item.out_stem = ""
                    skipped.append(item)
                else:
                    work.append(item)
            if not work and not skipped:
                raise M6Error("нечего обрабатывать")
            # Свежая папка: собираем имена только для того, что обрабатываем.
            if work and not has_output_media(ctx.output):
                ctx.used_names = set()
                counters = {"video": 1, "audio": 1, "image": 1}
                for item in work:
                    assign_output(item, ctx, counters)
        else:
            work = list(items)

        # Уже существующие целевые файлы: по умолчанию не перезаписываем.
        skipped.extend(mark_existing_skips(work, ctx))
        work = [item for item in work if item.status != "skipped"]
        items = work + skipped
        for number, item in enumerate(items, 1):
            item.idx = number

        if not work:
            failed = [item for item in items if item.status == "failed"]
            print("Новых файлов нет: всё уже существует или совместимо.")
            print_skipped_summary(items, ctx)
            return 1 if failed else 0

        if args.dry_run:
            print_header(ctx, items)
            print_plan(items, ctx, diagnostics=args.diagnose)
            failed = sum(1 for item in items if item.status == "failed")
            print(f"Ошибок: {failed}. Ничего не записано (--dry-run).")
            return 0 if failed == 0 else 1

        ctx.output.mkdir(parents=True, exist_ok=True)
        manifest_dir = ctx.output / "_m6media"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            manifest_dir / "run.log", encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        ctx.log.addHandler(file_handler)

        print_header(ctx, items)
        check_usb(ctx, items)

        work_items = [
            item for item in items
            if item.status not in {"failed", "skipped"} and item.action not in {"error", "skip"}
        ]
        if work_items:
            print(f"\nОбработка ({len(work_items)} файлов, потоков: {args.jobs})…")
            sys.stdout.flush()
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = {pool.submit(execute_item, item, ctx): item for item in work_items}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001 — не роняем весь пакет
                    item = futures[future]
                    item.status = "failed"
                    item.error = str(exc)
                    ctx.log.error("  FAIL %s: %s", item.src.name, item.error)

        if args.check:
            print("\nПроверка результата…")
            sys.stdout.flush()
            verify_items(items, ctx)

        write_manifest(items, ctx, started)

        summary = summarize(items)
        print()
        print("=" * 78)
        print(
            f"Готово: {summary['ok']} OK, {summary['failed']} ошибок, "
            f"{summary['skipped']} пропущено; {human_size(summary['bytes_out'])}; "
            f"{time.time() - started:.0f} с"
        )
        print(f"Папка: {ctx.output}")
        print_skipped_summary(items, ctx)
        sys.stdout.flush()
        if summary["failed"]:
            print("\nОшибки:")
            for item in items:
                if item.status == "failed":
                    print(f"  - {item.src.name}: {item.error}")
        return 0 if summary["failed"] == 0 else 1
    except M6Error as exc:
        eprint(f"\nОшибка: {exc}")
        return 2
    except OSError as exc:
        eprint(f"\nОшибка файловой системы: {exc}")
        return 2
    except KeyboardInterrupt:
        eprint("\nПрервано пользователем.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
