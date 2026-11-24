from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


MIB = 1024**2
GIB = 1024**3
DEFAULT_SAFETY_RESERVE_BYTES = 512 * MIB


def estimate_prepare_space(
    *,
    duration_seconds: float,
    timeline_seconds: float,
    audio_stream_count: int,
    selected_audio_stream_count: int,
    sample_rate: int = 48_000,
    source_path: str | Path | None = None,
    project_dir: str | Path | None = None,
    source_size_bytes: int = 0,
    include_source: bool = False,
) -> dict[str, int]:
    """Estimate bounded disk outputs before FFmpeg starts writing media."""
    if duration_seconds < 0 or timeline_seconds < 0:
        raise ValueError("미디어/타임라인 길이는 음수일 수 없습니다.")
    if audio_stream_count < 0 or selected_audio_stream_count < 0:
        raise ValueError("오디오 스트림 수는 음수일 수 없습니다.")
    if sample_rate <= 0:
        raise ValueError("오디오 샘플레이트는 양수여야 합니다.")

    preview_positions = 0 if duration_seconds <= 0 else (1 if duration_seconds <= 12 else 3)
    preview_seconds = min(duration_seconds, 12.0)
    preview_bytes = int(audio_stream_count * preview_positions * preview_seconds * 48_000 * 2 * 2)

    mono_pcm_bytes = int(timeline_seconds * sample_rate * 2)
    # Selected track WAVs, one in-progress track, and the mixed WAV plus its
    # temporary replacement can coexist while FFmpeg runs.
    voice_bytes = mono_pcm_bytes * (selected_audio_stream_count + 3) if selected_audio_stream_count else 0

    copy_bytes = 0
    if include_source and source_path is not None and project_dir is not None:
        source = Path(source_path).expanduser().resolve()
        copy_target = (Path(project_dir).expanduser().resolve() / "01_SOURCE" / source.name).resolve()
        if copy_target != source:
            copy_bytes = max(0, source_size_bytes)

    return {
        "audio_previews": preview_bytes,
        "voice_roughcut_and_temporary_files": voice_bytes,
        "source_copy": copy_bytes,
    }


def estimate_transcription_scratch(duration_seconds: float, chunk_seconds: int = 600) -> dict[str, int]:
    if duration_seconds < 0 or chunk_seconds <= 0:
        raise ValueError("전사 길이는 음수가 될 수 없고 chunk_seconds는 양수여야 합니다.")
    chunk_duration = min(float(chunk_seconds), duration_seconds)
    # 16 kHz mono signed 16-bit PCM, plus a small JSON/checkpoint allowance.
    return {"transcription_chunk_and_metadata": int(chunk_duration * 16_000 * 2) + 8 * MIB}


def disk_space_report(
    path: str | Path,
    components: dict[str, int],
    safety_reserve_bytes: int = DEFAULT_SAFETY_RESERVE_BYTES,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    usage = shutil.disk_usage(target)
    required = sum(max(0, int(value)) for value in components.values())
    minimum_free = required + max(0, int(safety_reserve_bytes))
    return {
        "checked_path": str(target),
        "available_bytes": usage.free,
        "components_bytes": components,
        "estimated_required_bytes": required,
        "safety_reserve_bytes": max(0, int(safety_reserve_bytes)),
        "minimum_free_bytes": minimum_free,
        "sufficient": usage.free >= minimum_free,
    }


def format_bytes(value: int) -> str:
    if value >= GIB:
        return f"{value / GIB:.2f} GiB"
    if value >= MIB:
        return f"{value / MIB:.1f} MiB"
    return f"{value} B"


def disk_space_message(report: dict[str, Any]) -> str:
    return (
        "디스크 공간 사전 점검: "
        f"사용 가능 {format_bytes(int(report['available_bytes']))}, "
        f"예상 산출물 {format_bytes(int(report['estimated_required_bytes']))}, "
        f"보존 여유 {format_bytes(int(report['safety_reserve_bytes']))}."
    )
