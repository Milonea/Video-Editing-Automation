from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from .models import FrameRate
from .paths import normalize_path

VOICE_HINTS = ("mic", "microphone", "voice", "discord", "chat", "보이스", "마이크", "음성")
GAME_HINTS = ("game", "desktop", "mix", "게임", "데스크톱", "믹스")


class MediaToolError(RuntimeError):
    pass


def require_binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise MediaToolError(f"{name}를 찾을 수 없습니다. FFmpeg 공식 배포본을 설치하고 PATH를 확인하세요.")
    return binary


@dataclass
class AudioStream:
    audio_ordinal: int
    global_index: int
    codec: str
    channels: int | None
    channel_layout: str | None
    sample_rate: int | None
    language: str | None
    title: str | None
    start_time: float
    duration: float | None
    is_default: bool
    candidate: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MediaInfo:
    path: str
    duration: float
    format_name: str
    size_bytes: int
    video: dict[str, Any] | None
    audio_streams: list[AudioStream]
    all_stream_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "duration": self.duration,
            "format_name": self.format_name,
            "size_bytes": self.size_bytes,
            "video": self.video,
            "audio_streams": [stream.to_dict() for stream in self.audio_streams],
            "all_stream_count": self.all_stream_count,
        }


def _float_or(value: Any, fallback: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _rate(value: Any) -> Fraction | None:
    if not value or value == "0/0":
        return None
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None


def _classify(title: str | None) -> str:
    if not title:
        return "unclassified"
    lowered = title.casefold()
    if any(key in lowered for key in VOICE_HINTS):
        return "voice_candidate"
    if any(key in lowered for key in GAME_HINTS):
        return "game_or_mix_candidate"
    return "unclassified"


def preview_sample_positions(duration: float, preview_seconds: float = 12.0) -> tuple[float, ...]:
    """Choose three short samples spread across short or long recordings."""
    if duration <= 0 or preview_seconds <= 0:
        return ()
    latest_start = max(0.0, duration - preview_seconds)
    return tuple(sorted({round(latest_start * fraction, 3) for fraction in (0.0, 0.5, 0.95)}))


def audio_preview_paths(
    media: MediaInfo,
    output_dir: str | Path,
    sample_positions: tuple[float, ...] | None = None,
    preview_seconds: float = 12.0,
) -> list[Path]:
    positions = sample_positions if sample_positions is not None else preview_sample_positions(media.duration, preview_seconds)
    out = Path(output_dir)
    return [
        out / f"audio_{stream.audio_ordinal:02d}_global_{stream.global_index}_at_{int(position):05d}.wav"
        for stream in media.audio_streams
        for position in positions
        if position < media.duration
    ]


def probe_media(path: str | Path, ffprobe: str = "ffprobe") -> MediaInfo:
    source = Path(normalize_path(path))
    if not source.is_file():
        raise FileNotFoundError(f"미디어 원본을 찾을 수 없습니다: {source}")
    binary = require_binary(ffprobe)
    command = [
        binary,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise MediaToolError(f"FFprobe 분석 실패: {result.stderr.strip() or '알 수 없는 오류'}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaToolError("FFprobe가 유효한 JSON을 반환하지 않았습니다.") from exc

    fmt = data.get("format", {})
    duration = _float_or(fmt.get("duration"))
    if duration is None:
        durations = [_float_or(stream.get("duration")) for stream in data.get("streams", [])]
        duration = max((value for value in durations if value is not None), default=0.0)
    streams = data.get("streams", [])
    video_raw = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    video = None
    if video_raw:
        real_rate = _rate(video_raw.get("r_frame_rate"))
        avg_rate = _rate(video_raw.get("avg_frame_rate"))
        chosen_rate = avg_rate or real_rate
        video = {
            "global_index": int(video_raw.get("index", 0)),
            "codec": video_raw.get("codec_name"),
            "width": video_raw.get("width"),
            "height": video_raw.get("height"),
            "pixel_format": video_raw.get("pix_fmt"),
            "time_base": video_raw.get("time_base"),
            "r_frame_rate": str(real_rate) if real_rate else None,
            "avg_frame_rate": str(avg_rate) if avg_rate else None,
            "frame_rate": str(chosen_rate) if chosen_rate else None,
            "start_time": _float_or(video_raw.get("start_time"), 0.0) or 0.0,
            "duration": _float_or(video_raw.get("duration"), duration),
            "is_vfr_heuristic": bool(real_rate and (avg_rate is None or real_rate != avg_rate)),
        }
    audio_streams: list[AudioStream] = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        title = tags.get("title") or tags.get("handler_name")
        audio_streams.append(
            AudioStream(
                audio_ordinal=len(audio_streams),
                global_index=int(stream.get("index", -1)),
                codec=str(stream.get("codec_name") or "unknown"),
                channels=int(stream["channels"]) if stream.get("channels") is not None else None,
                channel_layout=stream.get("channel_layout"),
                sample_rate=int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                language=tags.get("language"),
                title=title,
                start_time=_float_or(stream.get("start_time"), 0.0) or 0.0,
                duration=_float_or(stream.get("duration")),
                is_default=bool(disposition.get("default", 0)),
                candidate=_classify(title),
            )
        )
    return MediaInfo(
        path=str(source),
        duration=duration,
        format_name=str(fmt.get("format_name") or ""),
        size_bytes=source.stat().st_size,
        video=video,
        audio_streams=audio_streams,
        all_stream_count=len(streams),
    )


def make_audio_previews(
    media: MediaInfo,
    output_dir: str | Path,
    ffmpeg: str = "ffmpeg",
    sample_positions: tuple[float, ...] | None = None,
    preview_seconds: float = 12.0,
) -> list[Path]:
    binary = require_binary(ffmpeg)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    if sample_positions is None:
        sample_positions = preview_sample_positions(media.duration, preview_seconds)
    for stream in media.audio_streams:
        for position in sample_positions:
            if position >= media.duration:
                continue
            name = f"audio_{stream.audio_ordinal:02d}_global_{stream.global_index}_at_{int(position):05d}.wav"
            target = out / name
            temporary = target.with_name(f".{target.stem}.part.wav")
            command = [
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(position),
                "-threads",
                "1",
                "-i",
                media.path,
                "-t",
                str(min(preview_seconds, media.duration - position)),
                "-map",
                f"0:{stream.global_index}",
                "-vn",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode:
                temporary.unlink(missing_ok=True)
                raise MediaToolError(f"오디오 미리듣기 생성 실패(전체 스트림 {stream.global_index}): {result.stderr.strip()}")
            temporary.replace(target)
            generated.append(target)
    return generated
