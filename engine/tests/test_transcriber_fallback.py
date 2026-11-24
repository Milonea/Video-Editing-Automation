from __future__ import annotations

import json
import sys
import types
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from vea import cli, transcriber


def _write_test_audio(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 16_000)


def test_macos_cpu_transcription_is_allowed_without_non_windows_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    _write_test_audio(project / "05_AUDIO" / "roughcut_voice.wav")

    class FakeWhisperModel:
        def __init__(self, _name: str, *, device: str, compute_type: str):
            assert device == "cpu"
            assert compute_type == "int8"

        def transcribe(self, _path: str, **_kwargs: object):
            segment = SimpleNamespace(start=0.0, end=0.8, text="synthetic", avg_logprob=-0.1, no_speech_prob=0.0)
            return iter([segment]), SimpleNamespace(language="ko", language_probability=0.99)

    monkeypatch.setattr(transcriber, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    result = transcriber.transcribe_project(
        project,
        model_name="small",
        fallback_models=["medium"],
        device="cpu",
        compute_type="int8",
    )

    assert result["metadata"]["device"] == "cpu"
    assert result["metadata"]["hardware_check"] == "macOS CPU runtime; MLX execution is not implemented"
    assert Path(result["artifacts"]["srt"]).is_file()


@pytest.mark.parametrize("failure_stage", ["load", "transcribe"])
def test_cuda_compatibility_failure_tries_next_configured_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    project = tmp_path / "project"
    audio = project / "05_AUDIO" / "roughcut_voice.wav"
    _write_test_audio(audio)
    calls: list[tuple[str, str, str]] = []

    class FakeWhisperModel:
        def __init__(self, name: str, device: str, compute_type: str):
            calls.append((name, device, compute_type))
            if failure_stage == "load" and name == "large-v3":
                raise RuntimeError("cuDNN compatibility failure")
            self.name = name

        def transcribe(self, _path: str, **_kwargs: object):
            if failure_stage == "transcribe" and self.name == "large-v3":
                raise RuntimeError("CUDA runtime compatibility failure")
            segment = SimpleNamespace(start=0.0, end=0.8, text="테스트 전사", avg_logprob=-0.1, no_speech_prob=0.0)
            return iter([segment]), SimpleNamespace(language="ko", language_probability=0.99)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    result = transcriber.transcribe_project(
        project,
        model_name="large-v3",
        fallback_models=["large-v3-turbo", "medium"],
        device="cuda",
        compute_type="int8_float16",
        allow_non_windows=True,
    )

    assert result["metadata"]["model"] == "large-v3-turbo"
    assert result["metadata"]["attempts"]
    assert "compatibility failure" in result["metadata"]["attempts"][0]["error"]
    assert result["metadata"]["attempts"][0]["failure_type"] == "runtime_or_compatibility"
    assert calls[:2] == [
        ("large-v3", "cuda", "int8_float16"),
        ("large-v3-turbo", "cuda", "int8_float16"),
    ]
    assert Path(result["artifacts"]["srt"]).is_file()


def test_unsupported_cuda_precision_retries_with_int8(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    audio = project / "05_AUDIO" / "roughcut_voice.wav"
    _write_test_audio(audio)
    calls: list[tuple[str, str]] = []

    class FakeWhisperModel:
        def __init__(self, name: str, device: str, compute_type: str):
            calls.append((name, compute_type))
            if compute_type != "int8":
                raise RuntimeError("unsupported CUDA compute type")

        def transcribe(self, _path: str, **_kwargs: object):
            segment = SimpleNamespace(start=0.0, end=0.8, text="테스트 전사", avg_logprob=-0.1, no_speech_prob=0.0)
            return iter([segment]), SimpleNamespace(language="ko", language_probability=0.99)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    result = transcriber.transcribe_project(
        project,
        model_name="large-v3",
        fallback_models=["large-v3-turbo", "medium"],
        device="cuda",
        compute_type="int8_float16",
        allow_non_windows=True,
    )

    assert calls[-1] == ("large-v3", "int8")
    assert result["metadata"]["model"] == "large-v3"
    assert result["metadata"]["compute_type"] == "int8"
    assert len(result["metadata"]["attempts"]) == 3


def test_separate_voice_stems_keep_distinct_transcript_artifacts_and_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    mic = project / "05_AUDIO" / "voice_mic.wav"
    discord = project / "05_AUDIO" / "voice_discord.wav"
    _write_test_audio(mic)
    _write_test_audio(discord)

    class FakeWhisperModel:
        def __init__(self, _name: str, **_kwargs: object):
            pass

        def transcribe(self, path: str, **_kwargs: object):
            segment = SimpleNamespace(
                start=0.0,
                end=0.8,
                text=Path(path).stem,
                avg_logprob=-0.1,
                no_speech_prob=0.0,
            )
            return iter([segment]), SimpleNamespace(language="ko", language_probability=0.99)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    results = [
        transcriber.transcribe_project(
            project,
            audio_file=audio,
            model_name="small",
            fallback_models=["medium"],
            device="cpu",
            compute_type="int8",
            allow_non_windows=True,
        )
        for audio in (mic, discord)
    ]

    paths = [result["artifacts"]["srt"] for result in results]
    assert [path.name for path in paths] == ["voice_mic.srt", "voice_discord.srt"]
    assert all(path.is_file() for path in paths)
    assert (project / "07_TRANSCRIPTS" / ".chunks" / "chunk_voice_mic_0000.json").is_file()
    assert (project / "07_TRANSCRIPTS" / ".chunks" / "chunk_voice_discord_0000.json").is_file()
    checkpoint = json.loads((project / "checkpoint.json").read_text(encoding="utf-8"))
    assert "transcribe_voice_mic_chunk_0000" in checkpoint["stages"]
    assert "transcribe_voice_discord_chunk_0000" in checkpoint["stages"]


def test_resume_transcription_forwards_audio_and_transcript_name(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "02_INSTRUCTIONS").mkdir(parents=True)
    (project / "02_INSTRUCTIONS" / "request.json").write_text("{}", encoding="utf-8")
    audio = tmp_path / "voice_mic.wav"
    forwarded = []
    monkeypatch.setattr(cli, "_command_transcribe", lambda args: forwarded.append(args) or 0)

    assert cli.main(
        [
            "resume",
            str(project),
            "--transcribe",
            "--audio",
            str(audio),
            "--transcript-name",
            "voice_mic",
        ]
    ) == 0
    assert forwarded[0].audio == str(audio)
    assert forwarded[0].transcript_name == "voice_mic"


def test_resume_transcription_forwards_full_source_stream(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "02_INSTRUCTIONS").mkdir(parents=True)
    (project / "02_INSTRUCTIONS" / "request.json").write_text("{}", encoding="utf-8")
    forwarded = []
    monkeypatch.setattr(cli, "_command_transcribe", lambda args: forwarded.append(args) or 0)

    assert cli.main(
        [
            "resume",
            str(project),
            "--transcribe",
            "--full-source",
            "--audio-stream-index",
            "2",
        ]
    ) == 0
    assert forwarded[0].audio is None
    assert forwarded[0].full_source is True
    assert forwarded[0].audio_stream_index == 2
