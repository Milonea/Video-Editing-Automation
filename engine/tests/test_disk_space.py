from types import SimpleNamespace

import pytest

from vea.disk_space import (
    DEFAULT_SAFETY_RESERVE_BYTES,
    disk_space_report,
    estimate_prepare_space,
    estimate_transcription_scratch,
)


def test_two_hour_estimate_is_streamed_pcm_and_previews_stay_short(tmp_path):
    source = tmp_path / "recording.mkv"
    source.write_bytes(b"source")
    project = tmp_path / "project"
    components = estimate_prepare_space(
        duration_seconds=7200,
        timeline_seconds=3600,
        audio_stream_count=4,
        selected_audio_stream_count=2,
        source_path=source,
        project_dir=project,
        source_size_bytes=1234,
        include_source=True,
    )

    # Three 12-second previews per stream, two 48 kHz mono tracks, and a mix
    # plus temporary-file headroom. No decoded video frame buffer is estimated.
    assert components["audio_previews"] == 4 * 3 * 12 * 48_000 * 2 * 2
    assert components["voice_roughcut_and_temporary_files"] == 3600 * 48_000 * 2 * 5
    assert components["source_copy"] == 1234


def test_source_copy_is_not_estimated_when_source_is_already_package_target(tmp_path):
    project = tmp_path / "project"
    target = project / "01_SOURCE" / "recording.mkv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"source")
    components = estimate_prepare_space(
        duration_seconds=0,
        timeline_seconds=0,
        audio_stream_count=0,
        selected_audio_stream_count=0,
        source_path=target,
        project_dir=project,
        source_size_bytes=6,
        include_source=True,
    )
    assert components["source_copy"] == 0


def test_space_report_requires_estimate_plus_reserved_headroom(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "vea.disk_space.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=600, free=400),
    )
    report = disk_space_report(tmp_path, {"audio": 200}, safety_reserve_bytes=250)
    assert report["available_bytes"] == 400
    assert report["minimum_free_bytes"] == 450
    assert not report["sufficient"]


def test_transcription_scratch_estimate_covers_one_ten_minute_pcm_chunk():
    components = estimate_transcription_scratch(7200)
    assert components["transcription_chunk_and_metadata"] == 600 * 16_000 * 2 + 8 * 1024**2


def test_estimate_rejects_invalid_values():
    with pytest.raises(ValueError):
        estimate_prepare_space(
            duration_seconds=-1,
            timeline_seconds=0,
            audio_stream_count=0,
            selected_audio_stream_count=0,
        )
