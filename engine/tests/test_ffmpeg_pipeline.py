import json
import os
import shutil
import subprocess
import sys
import types
import wave
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from vea.audio import build_voice_roughcut
from vea.benchmark import benchmark_media
from vea.cfr import create_cfr_proxy
from vea import cli, transcriber
from vea.cli import main
from vea.media import preview_sample_positions, probe_media
from vea.models import FrameRate, TimelineClip
from vea.package import finalize_handoff
from vea.premiere import export_fcp7_xml
from vea.project import initialize_project
from vea.timecode import frames_to_seconds


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="FFmpeg/FFprobe가 필요합니다.")


@pytest.fixture
def synthetic_media(tmp_path):
    source = tmp_path / "한글 이름 [synthetic].mkv"
    command = [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x90:rate=30:duration=3",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=3",
        "-itsoffset",
        "0.5",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=48000:duration=3",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "2:a:0",
        "-t",
        "3",
        "-c:v",
        "mpeg4",
        "-q:v",
        "8",
        "-c:a",
        "pcm_s16le",
        "-metadata:s:a:0",
        "title=Mic",
        "-metadata:s:a:1",
        "title=Game",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        pytest.skip(f"현재 FFmpeg 빌드에서 합성 소스 생성 실패: {result.stderr}")
    return source


def _clips(source: Path) -> list[TimelineClip]:
    fps = FrameRate.parse(30)
    return [
        TimelineClip(
            source_file=str(source),
            source_in_frame=0,
            source_out_frame=30,
            timeline_start_frame=0,
            timeline_end_frame=30,
            source_in_seconds=Fraction(0),
            source_out_seconds=Fraction(1),
            label="first",
            ordering=1,
        ),
        TimelineClip(
            source_file=str(source),
            source_in_frame=45,
            source_out_frame=60,
            timeline_start_frame=30,
            timeline_end_frame=45,
            source_in_seconds=Fraction(3, 2),
            source_out_seconds=Fraction(2),
            label="second",
            ordering=2,
        ),
    ]


def test_probe_finds_named_delayed_audio_streams(synthetic_media):
    media = probe_media(synthetic_media)
    assert media.video is not None
    assert [item.audio_ordinal for item in media.audio_streams] == [0, 1]
    assert media.audio_streams[0].global_index != media.audio_streams[0].audio_ordinal
    assert media.audio_streams[0].candidate == "voice_candidate"
    assert media.audio_streams[1].candidate == "game_or_mix_candidate"
    assert media.audio_streams[1].start_time >= 0.45


def test_full_source_transcription_selects_saved_global_audio_stream(
    synthetic_media, tmp_path, monkeypatch
):
    project = tmp_path / "full source project"
    assert main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:03 유지",
            "--project-dir",
            str(project),
            "--audio-streams",
            "2",
        ]
    ) == 0
    assert cli._full_source_audio(project, None) == (synthetic_media.resolve(), 2)

    measured_frequencies: list[float] = []

    class FakeWhisperModel:
        def __init__(self, _name: str, **_kwargs: object):
            pass

        def transcribe(self, path: str, **_kwargs: object):
            with wave.open(path, "rb") as audio:
                sample_rate = audio.getframerate()
                audio.readframes(sample_rate)  # Ignore the source stream's initial offset.
                samples = audio.readframes(sample_rate)
            values = [int.from_bytes(samples[index : index + 2], "little", signed=True) for index in range(0, len(samples), 2)]
            crossings = sum(left <= 0 < right for left, right in zip(values, values[1:]))
            measured_frequencies.append(float(crossings))
            segment = SimpleNamespace(start=0.0, end=0.8, text="선택 스트림", avg_logprob=-0.1, no_speech_prob=0.0)
            return iter([segment]), SimpleNamespace(language="ko", language_probability=0.99)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    assert main(
        [
            "transcribe",
            str(project),
            "--full-source",
            "--audio-stream-index",
            "2",
            "--model",
            "small",
            "--fallback-models",
            "medium",
            "--device",
            "cpu",
            "--compute-type",
            "int8",
            "--allow-non-windows",
        ]
    ) == 0

    assert measured_frequencies == pytest.approx([880.0], abs=3.0)
    assert (project / "07_TRANSCRIPTS" / "full_source_global_2.srt").is_file()
    chunk = json.loads(
        (project / "07_TRANSCRIPTS" / ".chunks" / "chunk_full_source_global_2_0000.json").read_text(
            encoding="utf-8"
        )
    )
    assert chunk["requested"]["audio_stream_index"] == 2


def test_full_source_requires_stream_when_multiple_voice_tracks_are_selected(synthetic_media, tmp_path):
    project = tmp_path / "multiple full source project"
    assert main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:03 유지",
            "--project-dir",
            str(project),
            "--audio-streams",
            "1,2",
        ]
    ) == 0
    with pytest.raises(ValueError, match="선택된 보이스가 여러 개"):
        cli._full_source_audio(project, None)
    assert cli._full_source_audio(project, 2) == (synthetic_media.resolve(), 2)


def test_preview_samples_cover_short_and_two_hour_recordings():
    assert preview_sample_positions(3.0, 12.0) == (0.0,)
    assert preview_sample_positions(7200.0, 12.0) == (0.0, 3594.0, 6828.6)


def test_vfr_source_is_blocked_until_cfr_proxy_and_map_exist(synthetic_media, tmp_path, monkeypatch):
    real_probe = probe_media

    def mark_source_as_vfr(source):
        media = real_probe(source)
        if Path(source).resolve() == synthetic_media.resolve():
            media.video["is_vfr_heuristic"] = True
        return media

    monkeypatch.setattr("vea.cli.probe_media", mark_source_as_vfr)
    project = tmp_path / "vfr project"
    status = main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(project),
        ]
    )
    assert status == 2
    assert not (project / "04_ROUGHCUT" / "roughcut.xml").exists()
    assert "possible_vfr" in (project / "10_REPORTS" / "validation.json").read_text(encoding="utf-8")

    assert main(
        ["cfr-proxy", str(synthetic_media), "--project-dir", str(project), "--fps", "30"]
    ) == 0
    proxy = project / "01_SOURCE" / f"{synthetic_media.stem}_cfr_30-1.mp4"
    converted = probe_media(proxy)
    assert not converted.video["is_vfr_heuristic"]
    assert converted.video["frame_rate"] == "30"
    project_metadata = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert project_metadata["source_file"] == str(proxy.resolve())

    prepare_status = main(
        [
            "prepare",
            "--source",
            str(proxy),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(project),
        ]
    )
    assert prepare_status == 2  # No audio stream was present to select.
    edit_map = json.loads((project / "04_ROUGHCUT" / "edit_map.json").read_text(encoding="utf-8"))
    assert edit_map["cfr_conversion"]["source_time_to_proxy_frame"]["formula"].startswith("round_fraction")
    assert (project / "03_ANALYSIS" / "cfr_time_map.json").is_file()


def test_cfr_proxy_preserves_all_audio_streams(synthetic_media, tmp_path):
    result = create_cfr_proxy(synthetic_media, tmp_path / "cfr-proxy.mp4", fps=30)
    proxy = probe_media(result["proxy"])
    assert len(proxy.audio_streams) == 2
    assert [stream.audio_ordinal for stream in proxy.audio_streams] == [0, 1]
    assert result["mapping"]["audio_policy"].startswith("all source audio streams mapped")


def test_cfr_proxy_command_writes_into_project_source_folder(synthetic_media, tmp_path):
    project = tmp_path / "proxy project"
    assert main(
        ["cfr-proxy", str(synthetic_media), "--project-dir", str(project), "--fps", "30"]
    ) == 0
    proxy = project / "01_SOURCE" / f"{synthetic_media.stem}_cfr_30-1.mp4"
    assert proxy.is_file()
    assert Path(str(proxy) + ".vea-cfr-map.json").is_file()


def test_relink_updates_cfr_map_proxy_reference(synthetic_media, tmp_path):
    project = tmp_path / "cfr relink project"
    proxy = project / "01_SOURCE" / "cfr.mp4"
    create_cfr_proxy(synthetic_media, proxy, fps=30)
    assert main(
        [
            "prepare",
            "--source",
            str(proxy),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(project),
            "--audio-streams",
            "1",
            "--include-source",
            "--hash-media",
        ]
    ) == 0
    replacement_dir = tmp_path / "moved"
    replacement_dir.mkdir()
    replacement = replacement_dir / proxy.name
    shutil.copy2(proxy, replacement)

    assert main(["relink", str(project), "--source", str(replacement)]) == 0
    mapping = json.loads((project / "03_ANALYSIS" / "cfr_time_map.json").read_text(encoding="utf-8"))
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    assert mapping["proxy_path"] == str(replacement.resolve())
    assert manifest["source_conversion"]["proxy_path"] == str(replacement.resolve())


def test_benchmark_decodes_bounded_sample_with_one_thread(synthetic_media):
    result = benchmark_media(synthetic_media, sample_seconds=1.0)
    assert result["sample_duration_seconds"] == 1.0
    assert result["decoded_frames"] > 0
    assert result["ffmpeg_threads"] == 1
    assert result["output"] == "discarded via null muxer"


def test_benchmark_command_writes_only_to_project_report_folder(synthetic_media, tmp_path):
    project = tmp_path / "benchmark project"
    status = main(
        [
            "benchmark",
            str(synthetic_media),
            "--project-dir",
            str(project),
            "--seconds",
            "1",
        ]
    )
    report = project / "10_REPORTS" / "benchmark.json"
    assert status == 0
    assert report.is_file()
    assert json.loads(report.read_text(encoding="utf-8"))["ffmpeg_threads"] == 1


def test_prepare_disk_preflight_stops_before_generating_media(synthetic_media, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "vea.cli.disk_space_report",
        lambda _path, components: {
            "checked_path": str(tmp_path),
            "available_bytes": 100,
            "components_bytes": components,
            "estimated_required_bytes": 1000,
            "safety_reserve_bytes": 512 * 1024**2,
            "minimum_free_bytes": 512 * 1024**2 + 1000,
            "sufficient": False,
        },
    )
    project = tmp_path / "low-space project"
    status = main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(project),
        ]
    )
    assert status == 1
    assert (project / "10_REPORTS" / "prepare-disk-preflight.json").is_file()
    assert not list((project / "05_AUDIO" / "previews").glob("*.wav"))
    assert not (project / "04_ROUGHCUT" / "roughcut.xml").exists()


def test_voice_roughcut_respects_stream_and_frame_boundaries(synthetic_media, tmp_path):
    media = probe_media(synthetic_media)
    delayed = media.audio_streams[1]
    outputs = build_voice_roughcut(media, _clips(Path(media.path)), [delayed.global_index], tmp_path / "audio")
    assert len(outputs) == 2
    mix = tmp_path / "audio" / "roughcut_voice.wav"
    with wave.open(str(mix), "rb") as wav:
        assert wav.getframerate() == 48000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 72000
        raw = wav.readframes(wav.getnframes())
    samples = memoryview(raw).cast("h")
    first_quarter = samples[:12000]
    next_quarter = samples[24000:36000]
    assert max(map(abs, first_quarter)) < 100
    assert max(map(abs, next_quarter)) > 1000


def test_range_audio_mute_applies_to_voice_stems_and_editable_xml(synthetic_media, tmp_path):
    media = probe_media(synthetic_media)
    clip = _clips(Path(media.path))[0]
    clip.mute_audio = True
    outputs = build_voice_roughcut(media, [clip], [media.audio_streams[0].global_index], tmp_path / "muted")
    with wave.open(str(outputs[-1]), "rb") as wav:
        samples = memoryview(wav.readframes(wav.getnframes())).cast("h")
    assert max(map(abs, samples)) == 0

    path = export_fcp7_xml(tmp_path / "muted.xml", media, [clip], FrameRate.parse(30))
    root = ET.parse(path).getroot()
    video_clip = root.find(".//sequence/media/video/track/clipitem")
    audio_clip = root.find(".//sequence/media/audio/track/clipitem")
    assert video_clip is not None and video_clip.findtext("enabled") == "TRUE"
    assert audio_clip is not None and audio_clip.findtext("enabled") == "FALSE"


def test_xmeml_has_independent_video_and_audio_clips(synthetic_media, tmp_path):
    media = probe_media(synthetic_media)
    fps = FrameRate.parse(30)
    path = export_fcp7_xml(tmp_path / "roughcut.xml", media, _clips(Path(media.path)), fps)
    from xml.etree import ElementTree as ET

    root = ET.parse(path).getroot()
    assert root.tag == "xmeml"
    assert len(root.findall(".//sequence/media/video/track/clipitem")) == 2
    assert len(root.findall(".//sequence/media/audio/track")) == 2
    assert len(root.findall(".//sequence/media/audio/track/clipitem")) == 4
    assert root.findtext(".//sequence/duration") == "45"


def test_prepare_builds_manifest_edit_map_audio_and_checkpoint(synthetic_media, tmp_path):
    project = tmp_path / "video project"
    external_config = tmp_path / "local-config.toml"
    external_config.write_text('[project]\nsequence_fps = "30"\n', encoding="utf-8")
    code = main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:01 유지\n00:00:01~00:00:02 유지",
            "--project-dir",
            str(project),
            "--audio-streams",
            "1",
            "--config",
            str(external_config),
        ]
    )
    assert code == 0
    assert (project / "04_ROUGHCUT" / "roughcut.xml").is_file()
    assert (project / "04_ROUGHCUT" / "edit_map.json").is_file()
    assert (project / "05_AUDIO" / "roughcut_voice.wav").is_file()
    assert (project / "manifest.json").is_file()
    assert (project / "checkpoint.json").is_file()
    assert (project / "validation.md").is_file()
    codex_report = project / "10_REPORTS" / "codex_handoff.md"
    assert codex_report.is_file()
    assert "Notion 검색·생성·수정은 VEA 프로그램이 아니라 Codex" in codex_report.read_text(encoding="utf-8")
    request = json.loads((project / "02_INSTRUCTIONS" / "request.json").read_text(encoding="utf-8"))
    assert request["config_file"] == "config.toml"
    assert (project / "config.toml").is_file()
    assert any(item["path"] == "config.toml" for item in json.loads((project / "manifest.json").read_text(encoding="utf-8"))["assets"])
    assert any(item["path"] == "10_REPORTS/codex_handoff.md" for item in json.loads((project / "manifest.json").read_text(encoding="utf-8"))["assets"])

    media = probe_media(synthetic_media)
    synthetic_media.unlink()
    manifest = finalize_handoff(project, media.path, media, _clips(Path(media.path)), FrameRate.parse(30))
    assert manifest["source"]["path"] == str(media.path)
    assert all(item["path"] != "checkpoint.json" for item in manifest["assets"])


def test_prepare_reuses_valid_probe_and_parse_checkpoints(synthetic_media, tmp_path, monkeypatch):
    project = tmp_path / "cached project"
    probe_calls = 0
    parse_calls = 0
    real_probe = cli.probe_media
    real_parse = cli.parse_instructions

    def counted_probe(*args, **kwargs):
        nonlocal probe_calls
        probe_calls += 1
        return real_probe(*args, **kwargs)

    def counted_parse(*args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(cli, "probe_media", counted_probe)
    monkeypatch.setattr(cli, "parse_instructions", counted_parse)

    def prepare(instructions):
        return main(
            [
                "prepare",
                "--source",
                str(synthetic_media),
                "--instructions",
                instructions,
                "--project-dir",
                str(project),
                "--audio-streams",
                "1",
            ]
        )

    initial_instructions = "00:00:00~00:00:01 유지\n00:00:01~00:00:02 유지"
    assert prepare(initial_instructions) == 0
    assert (probe_calls, parse_calls) == (1, 1)

    assert prepare(initial_instructions) == 0
    assert (probe_calls, parse_calls) == (1, 1)

    # A present but malformed analysis artifact must invalidate the cache.
    (project / "03_ANALYSIS" / "media_info.json").write_text("{bad json", encoding="utf-8")
    assert prepare(initial_instructions) == 0
    assert (probe_calls, parse_calls) == (2, 1)

    # A syntactically valid but wrong-shaped stream report is invalid too.
    (project / "03_ANALYSIS" / "tracks.json").write_text("[]", encoding="utf-8")
    assert prepare(initial_instructions) == 0
    assert (probe_calls, parse_calls) == (3, 1)

    # Source metadata changes invalidate the probe, while the unchanged parse
    # inputs remain reusable.
    stat = synthetic_media.stat()
    os.utime(synthetic_media, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert prepare(initial_instructions) == 0
    assert (probe_calls, parse_calls) == (4, 1)

    assert prepare("00:00:00~00:00:00.500 유지") == 0
    assert (probe_calls, parse_calls) == (4, 2)


def test_receive_reuses_unique_existing_project_and_refuses_ambiguous_matches(synthetic_media, tmp_path):
    project = tmp_path / "existing client project"
    initialize_project(project, "existing client", synthetic_media)
    instruction_file = tmp_path / "client request.txt"
    instruction_file.write_text("00:00:00~00:00:01 유지", encoding="utf-8")
    args = [
        "receive",
        "--source",
        str(synthetic_media),
        "--instructions-file",
        str(instruction_file),
        "--search-root",
        str(tmp_path),
        "--audio-streams",
        "1",
    ]

    assert main(args) == 0
    assert (project / "04_ROUGHCUT" / "roughcut.xml").is_file()
    request_path = project / "02_INSTRUCTIONS" / "request.json"
    original_request = request_path.read_bytes()

    duplicate = tmp_path / "second project for same source"
    initialize_project(duplicate, "duplicate", synthetic_media)
    assert main(args) == 1
    assert request_path.read_bytes() == original_request
    assert not (duplicate / "02_INSTRUCTIONS" / "request.json").exists()


def test_two_hour_multitrack_source_prepares_three_sparse_cuts(tmp_path):
    source = tmp_path / "two hour source.mp4"
    command = [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x90:rate=1:duration=7200",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=mono:sample_rate=8000:duration=7200",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=8000:duration=7200",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "2:a:0",
        "-c:v",
        "mpeg4",
        "-q:v",
        "15",
        "-r",
        "1",
        "-fps_mode",
        "cfr",
        "-c:a",
        "aac",
        "-b:a",
        "12k",
        "-t",
        "7200",
        "-shortest",
        "-video_track_timescale",
        "90000",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        pytest.skip(f"현재 FFmpeg 빌드에서 2시간 합성 소스 생성 실패: {result.stderr}")

    source_stat = source.stat()
    media = probe_media(source)
    assert media.duration == pytest.approx(7200, abs=0.1)
    assert media.video is not None and not media.video["is_vfr_heuristic"]
    assert [stream.global_index for stream in media.audio_streams] == [1, 2]

    project = tmp_path / "two hour project"
    assert main(
        [
            "prepare",
            "--source",
            str(source),
            "--instructions",
            "00:00:10~00:00:20 유지\n00:59:50~01:00:10 유지\n01:59:30~01:59:50 유지",
            "--project-dir",
            str(project),
            "--audio-streams",
            "2",
        ]
    ) == 0
    assert main(["verify", str(project)]) == 0

    edit_map = json.loads((project / "04_ROUGHCUT" / "edit_map.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((project / "checkpoint.json").read_text(encoding="utf-8"))
    assert len(edit_map["clips"]) == 3
    assert edit_map["source_duration_seconds"] == pytest.approx(7200, abs=0.1)
    assert checkpoint["stages"]["audio_roughcut"]["status"] == "completed"
    assert checkpoint["stages"]["handoff"]["status"] == "completed"
    with wave.open(str(project / "05_AUDIO" / "roughcut_voice.wav"), "rb") as output:
        assert output.getframerate() == 48000
        assert output.getnframes() / output.getframerate() == pytest.approx(50.0, abs=0.01)
    assert source.is_file()
    assert (source.stat().st_size, source.stat().st_mtime_ns) == (source_stat.st_size, source_stat.st_mtime_ns)


def test_prepare_creates_spread_audio_previews_when_tracks_need_review(synthetic_media, tmp_path):
    project = tmp_path / "unselected project"
    code = main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(project),
        ]
    )
    assert code == 2
    previews = list((project / "05_AUDIO" / "previews").glob("*.wav"))
    assert len(previews) == 2
    assert "vea select-audio PROJECT --streams INDEX" in (project / "10_REPORTS" / "codex_handoff.md").read_text(encoding="utf-8")
    checkpoint = json.loads((project / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["stages"]["audio_previews"]["status"] == "completed"


def test_relink_updates_project_references_and_premiere_xml_for_matching_source(synthetic_media, tmp_path):
    project = tmp_path / "relink project"
    prepared = main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(project),
            "--audio-streams",
            "1",
            "--hash-media",
        ]
    )
    assert prepared == 0
    replacement = tmp_path / "replacement-name.mkv"
    shutil.copy2(synthetic_media, replacement)

    assert main(["relink", str(project), "--source", str(replacement)]) == 0
    metadata = json.loads((project / "project.json").read_text(encoding="utf-8"))
    edit_map = json.loads((project / "04_ROUGHCUT" / "edit_map.json").read_text(encoding="utf-8"))
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    xml = ET.parse(project / "04_ROUGHCUT" / "roughcut.xml").getroot()

    assert metadata["source_file"] == str(replacement.resolve())
    assert edit_map["clips"][0]["source_file"] == str(replacement.resolve())
    assert xml.findtext(".//file/pathurl") == replacement.resolve().as_uri()
    assert manifest["relinking"]["status"] == "sha256_verified"
    assert main(["verify", str(project)]) == 0


def test_relink_requires_confirmation_without_saved_content_hash(synthetic_media, tmp_path):
    project = tmp_path / "structural relink project"
    assert main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(project),
            "--audio-streams",
            "1",
        ]
    ) == 0
    replacement = tmp_path / "replacement.mkv"
    shutil.copy2(synthetic_media, replacement)

    assert main(["relink", str(project), "--source", str(replacement)]) == 1
    original_path = json.loads((project / "project.json").read_text(encoding="utf-8"))["source_file"]
    assert original_path == str(synthetic_media.resolve())

    assert main(["relink", str(project), "--source", str(replacement), "--confirm-structural-match"]) == 2
    metadata = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert metadata["source_relink"]["match"] == "technical_signature_only_user_confirmed"
    assert main(["verify", str(project)]) == 2


def test_prepare_rejects_sequence_fps_that_differs_from_source(synthetic_media, tmp_path):
    config = tmp_path / "mismatched-fps.toml"
    config.write_text('[project]\nsequence_fps = "25"\n', encoding="utf-8")
    code = main(
        [
            "prepare",
            "--source",
            str(synthetic_media),
            "--instructions",
            "00:00:00~00:00:01 유지",
            "--project-dir",
            str(tmp_path / "mismatched-project"),
            "--config",
            str(config),
        ]
    )
    assert code == 1
    assert not (tmp_path / "mismatched-project" / "04_ROUGHCUT" / "roughcut.xml").exists()
