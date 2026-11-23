"""Юнит-тесты m6media. Не требуют ffmpeg."""

import argparse
import logging
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import m6media as m6  # noqa: E402


def make_ctx(**overrides):
    args = argparse.Namespace(
        fps=30.0,
        fat32="fit",
        max_file_size=int(3.8 * 1024 ** 3),
        mode="auto",
        burn_subs=False,
        photo_max=1920,
        max_width=1920,
        max_height=1080,
        audio_format="mp3",
        audio_bitrate=256_000,
        container="mp4",
        x264_preset="medium",
        threads=2,
        tonemap=False,
        force=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return m6.Ctx(
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        preset=m6.PRESETS["compat"],
        args=args,
        output=Path("/tmp/m6-test-out"),
        used_names=set(),
        lock=threading.Lock(),
        log=logging.getLogger("test-m6media"),
    )


def make_media(
    codec="h264", profile="Main", level=40, pix_fmt="yuv420p",
    width=1920, height=1080, fps="30/1", rotation=None,
    color_transfer="bt709", color_primaries="bt709",
    audio=None, duration=60.0, size=100 * 1024 ** 2,
):
    streams = [
        m6.StreamInfo(
            index=0, codec_type="video", codec_name=codec, profile=profile,
            level=level, pix_fmt=pix_fmt, width=width, height=height,
            r_frame_rate=fps, rotation=rotation,
            color_transfer=color_transfer, color_primaries=color_primaries,
            sample_aspect_ratio="1:1",
        )
    ]
    if audio is not None:
        streams.append(audio)
    return m6.MediaInfo(
        path=Path("input.mkv"), format_name="matroska,webm",
        duration=duration, size=size, streams=streams,
    )


def audio_codec(name="aac", profile="LC", channels=2, sample_rate=48000):
    return m6.StreamInfo(
        index=1, codec_type="audio", codec_name=name, profile=profile,
        channels=channels, sample_rate=sample_rate,
    )


class NamingTests(unittest.TestCase):
    def test_transliteration(self):
        result = m6.transliterate("Тестовый фильм_2022")
        self.assertIn("Testovyy", result)
        self.assertIn("film", result)
        self.assertTrue(result.isascii())

    def test_ascii_safe_stem(self):
        self.assertEqual(m6.safe_stem("Тест: 1/2", False), "Test_1_2")
        self.assertEqual(m6.safe_stem("", False), "file")
        self.assertEqual(m6.safe_stem("CON", False), "_CON")
        self.assertLessEqual(len(m6.safe_stem("a" * 200, False)), 80)

    def test_keep_names(self):
        self.assertEqual(m6.safe_stem("Тест 1", True), "Тест 1")
        self.assertEqual(m6.safe_stem('a/b:c*?"', True), "a_b_c")

    def test_parse_size(self):
        self.assertEqual(m6.parse_size("3.8G"), int(3.8 * 1024 ** 3))
        self.assertEqual(m6.parse_size("4000M"), 4000 * 1024 ** 2)
        with self.assertRaises(argparse.ArgumentTypeError):
            m6.parse_size("nope")

    def test_parse_bitrate(self):
        self.assertEqual(m6.parse_bitrate("8M"), 8_000_000)
        self.assertEqual(m6.parse_bitrate("8000k"), 8_000_000)
        with self.assertRaises(argparse.ArgumentTypeError):
            m6.parse_bitrate("10")


class StreamTests(unittest.TestCase):
    def test_display_size_rotation(self):
        stream = m6.StreamInfo(width=1920, height=1080, rotation=-90)
        self.assertEqual(m6.display_size(stream), (1080, 1920))
        stream.rotation = 180
        self.assertEqual(m6.display_size(stream), (1920, 1080))

    def test_pick_fps_cap(self):
        media = make_media(fps="60000/1001")
        self.assertEqual(m6.pick_fps(media, 30), "30")
        media = make_media(fps="24000/1001")
        self.assertEqual(m6.pick_fps(media, 30), "24000/1001")
        media = make_media(fps="25/1")
        self.assertEqual(m6.pick_fps(media, 30), "25")
        media = make_media(fps="0/0")
        self.assertEqual(m6.pick_fps(media, 0), "30")

    def test_classify(self):
        image = m6.MediaInfo(path=Path("x.jpg"), format_name="image2")
        self.assertEqual(m6.classify(Path("x.jpg"), image), "image")
        video = make_media()
        self.assertEqual(m6.classify(Path("x.mkv"), video), "video")
        audio = m6.MediaInfo(
            path=Path("x.mp3"), format_name="mp3",
            streams=[audio_codec("mp3")],
        )
        self.assertEqual(m6.classify(Path("x.mp3"), audio), "audio")
        gif = m6.MediaInfo(
            path=Path("x.gif"), format_name="gif", duration=2.0,
            streams=[m6.StreamInfo(codec_type="video", codec_name="gif")],
        )
        self.assertEqual(m6.classify(Path("x.gif"), gif), "video")


class CompatibilityTests(unittest.TestCase):
    def test_h264_1080p_main_is_compatible(self):
        media = make_media(audio=audio_codec())
        self.assertEqual(m6.video_copy_reasons(media, make_ctx()), [])
        self.assertEqual(m6.audio_copy_reasons(media), [])

    def test_h264_41_lowres_is_ok(self):
        media = make_media(profile="High", level=41, width=1152, height=480)
        self.assertEqual(m6.video_copy_reasons(media, make_ctx()), [])

    def test_h264_41_1080p_needs_reencode(self):
        media = make_media(profile="High", level=41)
        reasons = m6.video_copy_reasons(media, make_ctx())
        self.assertTrue(any("4.1" in reason for reason in reasons))

    def test_xvid_needs_reencode(self):
        media = make_media(codec="mpeg4", profile="Advanced Simple Profile", level=5,
                           width=704, height=384)
        reasons = m6.video_copy_reasons(media, make_ctx())
        self.assertTrue(any("MPEG-4 Part 2" in reason for reason in reasons))

    def test_hdr_needs_reencode(self):
        media = make_media(color_transfer="smpte2084", color_primaries="bt2020")
        reasons = m6.video_copy_reasons(media, make_ctx())
        self.assertTrue(any("HDR" in reason for reason in reasons))

    def test_too_large_frame(self):
        media = make_media(width=1920, height=1200)
        reasons = m6.video_copy_reasons(media, make_ctx())
        self.assertTrue(any("больше" in reason for reason in reasons))

    def test_ac3_audio_needs_reencode(self):
        media = make_media(audio=audio_codec("ac3", profile=None, channels=6))
        reasons = m6.audio_copy_reasons(media)
        self.assertTrue(any("AC3" in reason for reason in reasons))
        self.assertFalse(any("6 каналов" in reason for reason in reasons))

    def test_aac_51_needs_stereo(self):
        media = make_media(audio=audio_codec("aac", channels=6))
        reasons = m6.audio_copy_reasons(media)
        self.assertTrue(any("6 каналов" in reason for reason in reasons))


class PlanningTests(unittest.TestCase):
    def test_fit_two_hours(self):
        ctx = make_ctx(fat32="fit")
        parts, cap, why = m6.compute_size_plan(7200, ctx)
        self.assertEqual(parts, 1)
        self.assertLess(cap, ctx.preset.maxrate)
        self.assertGreaterEqual(cap, 2_200_000)
        self.assertEqual(why, "")

    def test_fit_long_video_splits(self):
        ctx = make_ctx(fat32="fit")
        parts, cap, why = m6.compute_size_plan(4 * 3600, ctx)
        self.assertGreater(parts, 1)
        self.assertIn("разбить", why)

    def test_split_mode(self):
        ctx = make_ctx(fat32="split")
        parts, cap, why = m6.compute_size_plan(7200, ctx)
        self.assertEqual(parts, 2)
        self.assertEqual(cap, ctx.preset.maxrate)
        self.assertIn("2 частей", why)

    def test_fat32_off(self):
        ctx = make_ctx(fat32="off")
        parts, cap, why = m6.compute_size_plan(7200, ctx)
        self.assertEqual((parts, cap, why), (1, ctx.preset.maxrate, ""))

    def test_split_ranges(self):
        ranges = m6.split_ranges(100.0, 4)
        self.assertEqual(len(ranges), 4)
        self.assertAlmostEqual(sum(length for _, length in ranges), 100.0)
        self.assertEqual(ranges[0][0], 0.0)
        self.assertEqual(m6.split_ranges(100.0, 1), [(None, None)])



class DefaultSkipTests(unittest.TestCase):
    """По умолчанию совместимые файлы не трогаем."""

    def video_item(self, media, action, suffix=".mkv"):
        return m6.PlanItem(1, Path("input" + suffix), "video", media, action=action)

    def test_mkv_h264_ac3_is_skipped(self):
        media = make_media(audio=audio_codec("ac3", profile=None, channels=6))
        item = self.video_item(media, "copy-video")
        self.assertTrue(m6.already_compatible(item, make_ctx()))

    def test_mp4_h264_aac_is_skipped(self):
        media = make_media(audio=audio_codec("aac"))
        media.format_name = "mov,mp4,m4a,3gp,3g2,mj2"
        item = self.video_item(media, "remux", ".mp4")
        self.assertTrue(m6.already_compatible(item, make_ctx()))

    def test_avi_h264_aac_is_not_skipped(self):
        media = make_media(audio=audio_codec("aac"))
        media.format_name = "avi"
        item = self.video_item(media, "remux", ".avi")
        self.assertFalse(m6.already_compatible(item, make_ctx()))

    def test_xvid_is_not_skipped(self):
        media = make_media(codec="mpeg4", profile="Advanced Simple Profile",
                           level=5, width=704, height=384,
                           audio=audio_codec("ac3", profile=None, channels=6))
        item = self.video_item(media, "transcode", ".avi")
        self.assertFalse(m6.already_compatible(item, make_ctx()))

    def test_mp3_is_skipped_by_default(self):
        media = m6.MediaInfo(
            path=Path("song.mp3"), format_name="mp3", duration=10,
            streams=[audio_codec("mp3")],
        )
        item = m6.PlanItem(1, Path("song.mp3"), "audio", media, action="remux-audio")
        self.assertTrue(m6.already_compatible(item, make_ctx()))

    def test_ac3_audio_is_not_skipped(self):
        media = m6.MediaInfo(
            path=Path("track.ac3"), format_name="ac3", duration=10,
            streams=[audio_codec("ac3", profile=None, channels=6)],
        )
        item = m6.PlanItem(1, Path("track.ac3"), "audio", media,
                           action="transcode-audio-only")
        self.assertFalse(m6.already_compatible(item, make_ctx()))

    def test_jpeg_is_skipped(self):
        media = m6.MediaInfo(path=Path("photo.jpg"), format_name="image2")
        item = m6.PlanItem(1, Path("photo.jpg"), "image", media, action="image")
        self.assertTrue(m6.already_compatible(item, make_ctx()))

    def test_heic_is_not_skipped(self):
        media = m6.MediaInfo(path=Path("photo.heic"), format_name="image2")
        item = m6.PlanItem(1, Path("photo.heic"), "image", media, action="image")
        self.assertFalse(m6.already_compatible(item, make_ctx()))


class DefaultOutputTests(unittest.TestCase):
    def test_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            movies = Path(tmp) / "movies"
            movies.mkdir()
            self.assertEqual(m6.default_output([str(movies)]), movies / "M6")

    def test_file(self):
        self.assertEqual(
            m6.default_output(["/tmp/movies/a.avi"]), Path("/tmp/movies/M6")
        )

    def test_multiple_same_parent(self):
        self.assertEqual(
            m6.default_output(["/tmp/movies/a.avi", "/tmp/movies/b.mkv"]),
            Path("/tmp/movies/M6"),
        )


class ExistingSkipTests(unittest.TestCase):
    def test_existing_is_skipped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "M6"
            video = out / "Video"
            video.mkdir(parents=True)
            target = video / "x.mp4"
            target.write_bytes(b"x")
            ctx = make_ctx()
            ctx.output = out
            item = m6.PlanItem(
                1, Path("x.mkv"), "video", make_media(),
                action="remux", out_paths=[target],
            )
            skipped = m6.mark_existing_skips([item], ctx)
            self.assertEqual(len(skipped), 1)
            self.assertEqual(item.status, "skipped")
            self.assertIn("уже существует", item.notes[0])

    def test_force_does_not_skip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "M6"
            video = out / "Video"
            video.mkdir(parents=True)
            target = video / "x.mp4"
            target.write_bytes(b"x")
            ctx = make_ctx(force=True)
            ctx.output = out
            item = m6.PlanItem(
                1, Path("x.mkv"), "video", make_media(),
                action="remux", out_paths=[target],
            )
            self.assertEqual(m6.mark_existing_skips([item], ctx), [])


class RepoTests(unittest.TestCase):
    def test_version_matches_pyproject(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{m6.APP_VERSION}"', pyproject)

    def test_mit_license(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 m6media contributors", text)


class FfmpegCompatibilityTests(unittest.TestCase):
    def test_ffmpeg4_uses_vsync(self):
        ctx = make_ctx()
        ctx.ffmpeg_major = 4
        item = m6.PlanItem(
            1, Path("input.mkv"), "video", make_media(), action="transcode",
            target_fps="24",
        )
        item.cap = 8_000_000
        cmd = m6.build_video_cmd(ctx, item, Path("/tmp/out.mp4"))
        self.assertIn("-vsync", cmd)
        self.assertNotIn("-fps_mode", cmd)

    def test_ffmpeg5_uses_fps_mode(self):
        ctx = make_ctx()
        ctx.ffmpeg_major = 5
        item = m6.PlanItem(
            1, Path("input.mkv"), "video", make_media(), action="transcode",
            target_fps="24",
        )
        item.cap = 8_000_000
        cmd = m6.build_video_cmd(ctx, item, Path("/tmp/out.mp4"))
        self.assertIn("-fps_mode", cmd)
        self.assertNotIn("-vsync", cmd)


class PlatformTests(unittest.TestCase):
    @unittest.skipUnless(__import__("os").name == "nt", "Windows only")
    def test_windows_filesystem_detection(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fs = m6.filesystem_type(Path(tmp)).upper()
            self.assertIn(fs, {"NTFS", "FAT32", "FAT", "EXFAT"})

if __name__ == "__main__":
    unittest.main()
