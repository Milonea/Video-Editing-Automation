from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .checkpoint import atomic_write_json, atomic_write_text
from .media import require_binary
from .timecode import format_srt_timestamp, parse_timecode


@dataclass
class SubtitleSegment:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    words: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SilenceInterval:
    start: float
    end: float | None
    duration: float | None


def read_srt(path: str | Path) -> list[SubtitleSegment]:
    source = Path(path)
    content = source.read_text(encoding="utf-8-sig")
    cue_pattern = re.compile(
        r"(?ms)^\s*\d+\s*\r?\n"
        r"(\d{2,}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
        r"(\d{2,}:\d{2}:\d{2}[,.]\d{1,3})[^\r\n]*\r?\n"
        r"(.*?)(?=\r?\n\s*\r?\n|\Z)"
    )
    segments: list[SubtitleSegment] = []
    for match in cue_pattern.finditer(content):
        start, end, text = match.groups()
        normalized_text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
        if not normalized_text:
            raise ValueError(f"SRT에 빈 자막이 있습니다: {source}")
        segments.append(
            SubtitleSegment(
                start=float(parse_timecode(start)),
                end=float(parse_timecode(end)),
                text=normalized_text,
            )
        )
    if not segments:
        raise ValueError(f"SRT 자막 구간을 읽지 못했습니다: {source}")
    return segments


def detect_silence_intervals(
    audio_path: str | Path,
    *,
    threshold_db: float = -50.0,
    min_duration: float = 0.5,
) -> list[SilenceInterval]:
    if min_duration <= 0:
        raise ValueError("무음 최소 길이는 0보다 커야 합니다.")
    audio = Path(audio_path).expanduser().resolve()
    if not audio.is_file():
        raise FileNotFoundError(f"무음 분석 오디오를 찾을 수 없습니다: {audio}")
    ffmpeg = require_binary("ffmpeg")
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-i",
        str(audio),
        "-af",
        f"silencedetect=noise={threshold_db:g}dB:d={min_duration:g}",
        "-f",
        "null",
        os.devnull,
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 무음 분석에 실패했습니다: {result.stderr[-2000:]}")

    event_pattern = re.compile(
        r"silence_start:\s*(-?\d+(?:\.\d+)?)|"
        r"silence_end:\s*(-?\d+(?:\.\d+)?)(?:\s*\|\s*silence_duration:\s*(-?\d+(?:\.\d+)?))?"
    )
    intervals: list[SilenceInterval] = []
    pending_start: float | None = None
    for match in event_pattern.finditer(result.stderr):
        if match.group(1) is not None:
            pending_start = float(match.group(1))
            continue
        end = float(match.group(2))
        duration = float(match.group(3)) if match.group(3) is not None else None
        start = pending_start if pending_start is not None else (end - duration if duration is not None else None)
        if start is not None and end >= start and end - start + 1e-6 >= min_duration:
            intervals.append(SilenceInterval(start=start, end=end, duration=end - start))
        pending_start = None
    if pending_start is not None:
        intervals.append(SilenceInterval(start=pending_start, end=None, duration=None))
    return intervals


def make_silence_tail_preview(
    segments: list[SubtitleSegment],
    intervals: list[SilenceInterval],
    *,
    tail_seconds: float = 0.5,
) -> tuple[list[SubtitleSegment], dict[str, Any]]:
    if tail_seconds < 0:
        raise ValueError("무음 뒤 자막 유지 시간은 0 이상이어야 합니다.")
    preview = [SubtitleSegment(**segment.to_dict()) for segment in segments]
    changes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    no_change = 0

    for index, segment in enumerate(preview):
        candidates: list[SilenceInterval] = []
        for interval in intervals:
            # Only associate a gap at the cue's tail. If speech resumes before
            # the cue ends, keep the existing cue unchanged (no word alignment
            # is available to split it safely).
            if interval.start > segment.end + tail_seconds:
                continue
            if interval.end is not None and interval.end < segment.end - 1e-6:
                continue
            if interval.start <= segment.end + tail_seconds:
                candidates.append(interval)
        if not candidates:
            no_change += 1
            continue

        interval = min(candidates, key=lambda item: abs(item.start - segment.end))
        proposed_end = interval.start + tail_seconds
        if interval.start <= segment.start and (interval.end is None or interval.end >= segment.end):
            unresolved.append(
                {
                    "cue": index + 1,
                    "start": segment.start,
                    "end": segment.end,
                    "silence_start": interval.start,
                    "silence_end": interval.end,
                    "text": segment.text,
                    "reason": "cue_wholly_inside_detected_silence",
                }
            )
            no_change += 1
            continue
        if proposed_end <= segment.start:
            unresolved.append(
                {
                    "cue": index + 1,
                    "start": segment.start,
                    "end": segment.end,
                    "silence_start": interval.start,
                    "silence_end": interval.end,
                    "text": segment.text,
                    "reason": "silence_tail_would_make_cue_invalid",
                }
            )
            no_change += 1
            continue

        next_start = preview[index + 1].start if index + 1 < len(preview) else None
        if next_start is not None and next_start < proposed_end - 1e-6:
            unresolved.append(
                {
                    "cue": index + 1,
                    "start": segment.start,
                    "end": segment.end,
                    "silence_start": interval.start,
                    "silence_end": interval.end,
                    "proposed_end": proposed_end,
                    "next_cue_start": next_start,
                    "text": segment.text,
                    "reason": "would_overlap_next_cue",
                }
            )
            no_change += 1
            continue

        if abs(proposed_end - segment.end) <= 0.001:
            no_change += 1
            continue
        changes.append(
            {
                "cue": index + 1,
                "old_start": segment.start,
                "old_end": segment.end,
                "new_start": segment.start,
                "new_end": proposed_end,
                "delta_seconds": proposed_end - segment.end,
                "silence_start": interval.start,
                "silence_end": interval.end,
                "text": segment.text,
            }
        )
        segment.end = proposed_end

    summary = {
        "cue_count": len(segments),
        "silence_interval_count": len(intervals),
        "changed_cue_count": len(changes),
        "unchanged_cue_count": no_change,
        "unresolved_cue_count": len(unresolved),
        "tail_seconds": tail_seconds,
        "changes": changes,
        "unresolved": unresolved,
    }
    return preview, summary


def safe_transcript_name(value: str) -> str:
    safe = re.sub(r"[^\w.-]+", "_", Path(value).name, flags=re.UNICODE).strip("._")[:80]
    return safe or "transcript"


def write_srt(segments: list[SubtitleSegment], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, segment in enumerate(segments, 1):
        lines.extend(
            [
                str(index),
                f"{format_srt_timestamp(segment.start)} --> {format_srt_timestamp(segment.end)}",
                segment.text.strip(),
                "",
            ]
        )
    atomic_write_text(target, "\n".join(lines), encoding="utf-8-sig")
    return target


def validate_subtitles(
    segments: list[SubtitleSegment],
    duration: float,
    clip_boundaries: list[float] | None = None,
    max_chars: int = 80,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    previous: SubtitleSegment | None = None
    for index, segment in enumerate(segments, 1):
        if not segment.text.strip():
            issues.append({"severity": "error", "code": "empty_text", "message": f"자막 {index}: 빈 문장"})
        if segment.end <= segment.start:
            issues.append({"severity": "error", "code": "invalid_interval", "message": f"자막 {index}: 종료가 시작보다 빠르거나 같습니다."})
        if segment.start < 0 or segment.end > duration + 0.05:
            issues.append({"severity": "error", "code": "out_of_range", "message": f"자막 {index}: 러프컷 음성 길이를 벗어납니다."})
        if previous:
            if segment.start < previous.start:
                issues.append({"severity": "error", "code": "time_reversal", "message": f"자막 {index}: 시작 시간이 앞 자막보다 빠릅니다."})
            if segment.start < previous.end:
                issues.append({"severity": "warning", "code": "overlap", "message": f"자막 {index - 1}과 {index}이 겹칩니다."})
        if len(segment.text.strip()) > max_chars:
            issues.append({"severity": "warning", "code": "long_text", "message": f"자막 {index}: {len(segment.text.strip())}자입니다. 분할 여부를 검토하세요."})
        if segment.avg_logprob is not None and segment.avg_logprob < -1.0:
            issues.append({"severity": "review", "code": "low_confidence", "message": f"자막 {index}: 평균 로그 확률이 낮아 청취 검수가 필요합니다."})
        previous = segment
    for boundary in clip_boundaries or []:
        if any(segment.start < boundary < segment.end for segment in segments):
            issues.append(
                {
                    "severity": "review",
                    "code": "cut_boundary_crossing",
                    "message": f"러프컷 컷 지점 {boundary:.3f}s를 가로지르는 자막이 있어 경계 청취 검수가 필요합니다.",
                }
            )
    return issues


def write_transcript_artifacts(
    output_dir: str | Path,
    segments: list[SubtitleSegment],
    duration: float,
    metadata: dict[str, Any],
    clip_boundaries: list[float] | None = None,
    transcript_name: str = "transcript",
) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    safe_name = safe_transcript_name(transcript_name)
    srt = write_srt(segments, root / f"{safe_name}.srt")
    payload = {
        "version": 1,
        "duration_seconds": duration,
        "metadata": metadata,
        "segments": [segment.to_dict() for segment in segments],
    }
    json_path = root / f"{safe_name}.json"
    atomic_write_json(json_path, payload)
    txt_path = root / f"{safe_name}.txt"
    atomic_write_text(txt_path, "\n".join(segment.text.strip() for segment in segments) + "\n")
    issues = validate_subtitles(segments, duration, clip_boundaries)
    review_path = root / f"{safe_name}_review.md"
    lines = [
        "# 전사 검토 리포트",
        "",
        f"- 구간 수: {len(segments)}",
        f"- 러프컷 음성 길이: {duration:.3f}초",
        f"- 모델: {metadata.get('model', 'unknown')}",
        f"- 실행 장치: {metadata.get('device', 'unknown')}",
        "",
        "## 확인 항목",
        "",
    ]
    if issues:
        lines.extend(f"- [{item['severity'].upper()}] {item['code']}: {item['message']}" for item in issues)
    else:
        lines.append("자동 타임코드 검사는 통과했습니다. 음성 청취 검수는 별도로 수행해야 합니다.")
    atomic_write_text(review_path, "\n".join(lines) + "\n")
    return {"srt": srt, "json": json_path, "text": txt_path, "review": review_path}
