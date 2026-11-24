from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from .checkpoint import atomic_write_json, atomic_write_text
from .subtitles import SubtitleSegment


@dataclass(frozen=True)
class CaptionInterval:
    index: int
    start: Fraction
    end: Fraction
    text: str


def _fraction_seconds(value: Any, *, label: str) -> Fraction:
    try:
        if isinstance(value, Fraction):
            result = value
        elif isinstance(value, int):
            result = Fraction(value)
        else:
            result = Fraction(str(value)).limit_denominator(1_000_000)
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise ValueError(f"{label} 타임스탬프가 올바르지 않습니다: {value!r}") from exc
    return result


def _as_caption_intervals(
    cues: Iterable[SubtitleSegment | dict[str, Any]],
    *,
    end_time_kind: str,
    subtitle_tail_seconds: Fraction,
) -> tuple[list[CaptionInterval], list[dict[str, Any]]]:
    if end_time_kind not in {"subtitle_end", "speech_end"}:
        raise ValueError("end_time_kind는 subtitle_end 또는 speech_end여야 합니다.")
    intervals: list[CaptionInterval] = []
    issues: list[dict[str, Any]] = []
    for index, cue in enumerate(cues, 1):
        if isinstance(cue, SubtitleSegment):
            raw_start, raw_end, text = cue.start, cue.end, cue.text
        else:
            raw_start, raw_end, text = cue.get("start"), cue.get("end"), cue.get("text", "")
        try:
            start = _fraction_seconds(raw_start, label=f"자막 {index} 시작")
            end = _fraction_seconds(raw_end, label=f"자막 {index} 종료")
        except ValueError as exc:
            issues.append({"code": "invalid_timestamp", "cue": index, "message": str(exc)})
            continue
        if start < 0:
            issues.append({"code": "negative_timestamp", "cue": index, "message": "음수 타임코드는 분할 계산에서 제외했습니다."})
            continue
        if end <= start:
            issues.append({"code": "invalid_interval", "cue": index, "message": "종료가 시작보다 빠르거나 같아 분할 계산에서 제외했습니다."})
            continue
        if not str(text).strip():
            issues.append({"code": "empty_caption", "cue": index, "message": "문구가 비어 있어 분할 계산을 중단해야 합니다."})
            continue
        if end_time_kind == "speech_end":
            end += subtitle_tail_seconds
        intervals.append(CaptionInterval(index, start, end, str(text).strip()))
    intervals.sort(key=lambda item: (item.start, item.end, item.index))
    return intervals, issues


def _ceil(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _floor(value: Fraction) -> int:
    return value.numerator // value.denominator


def _seconds_text(value: Fraction) -> str:
    return f"{float(value):.6f}"


def _merge_caption_intervals(
    intervals: list[CaptionInterval],
) -> tuple[list[CaptionInterval], int]:
    merged: list[CaptionInterval] = []
    overlap_count = 0
    for interval in intervals:
        if not merged or interval.start > merged[-1].end:
            merged.append(interval)
            continue
        current = merged[-1]
        if interval.start < current.end:
            overlap_count += 1
        # A merged protected span uses the cue that actually ends last for its
        # previous-caption label. Ties retain both original texts in notes via
        # the final interval's cue, while the range itself stays conservative.
        if interval.end > current.end:
            merged[-1] = CaptionInterval(interval.index, current.start, interval.end, interval.text)
    return merged, overlap_count


def _map_source_ranges(
    start_frame: int,
    end_frame: int,
    edit_map: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not edit_map or end_frame <= start_frame:
        return []
    result: list[dict[str, Any]] = []
    for clip in edit_map.get("clips", []):
        try:
            clip_start = int(clip["timeline_start_frame"])
            clip_end = int(clip["timeline_end_frame"])
            source_in = int(clip["source_in_frame"])
        except (KeyError, TypeError, ValueError):
            continue
        start = max(start_frame, clip_start)
        end = min(end_frame, clip_end)
        if end <= start:
            continue
        result.append(
            {
                "source_file": clip.get("source_file"),
                "source_start_frame": source_in + start - clip_start,
                "source_end_frame": source_in + end - clip_start,
                "sequence_start_frame": start,
                "sequence_end_frame": end,
            }
        )
    return result


def analyze_caption_gaps(
    cues: Iterable[SubtitleSegment | dict[str, Any]],
    *,
    fps: Fraction,
    min_gap_seconds: Fraction = Fraction(4, 5),
    subtitle_tail_seconds: Fraction = Fraction(1, 2),
    end_time_kind: str = "subtitle_end",
    sequence_duration_seconds: Fraction | None = None,
    existing_cut_frames: set[int] | None = None,
    edit_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rate = Fraction(fps)
    threshold = Fraction(min_gap_seconds)
    tail = Fraction(subtitle_tail_seconds)
    if rate <= 0:
        raise ValueError("FPS는 0보다 커야 합니다.")
    if threshold < 0 or tail < 0:
        raise ValueError("자막 여유 시간과 최소 공백은 0 이상이어야 합니다.")
    captions, issues = _as_caption_intervals(cues, end_time_kind=end_time_kind, subtitle_tail_seconds=tail)
    raw_cue_count = len(captions) + len(issues)
    if issues:
        # A malformed cue could be the missing edge of a gap. Do not bridge
        # around it and invent a candidate interval.
        return {
            "status": "needs_review",
            "blocked": True,
            "fps": {"numerator": rate.numerator, "denominator": rate.denominator},
            "cue_count": raw_cue_count,
            "candidate_count": 0,
            "candidates": [],
            "issues": issues,
            "time_source": "SRT subtitle_end used as-is" if end_time_kind == "subtitle_end" else "Whisper speech_end plus configured tail",
            "tail_added_seconds": 0.0 if end_time_kind == "subtitle_end" else float(tail),
            "auto_delete": False,
        }

    merged, overlap_count = _merge_caption_intervals(captions)
    duration = Fraction(sequence_duration_seconds) if sequence_duration_seconds is not None else None
    if duration is not None and duration < 0:
        raise ValueError("시퀀스 길이는 0 이상이어야 합니다.")
    if duration is not None and any(cue.start > duration or cue.end > duration + Fraction(1, 1000) for cue in merged):
        issues.append(
            {
                "code": "sequence_timebase_mismatch",
                "message": "자막 시간이 확인된 시퀀스 길이를 넘어 후보 계산을 중단했습니다.",
            }
        )
        return {
            "status": "needs_review",
            "blocked": True,
            "fps": {"numerator": rate.numerator, "denominator": rate.denominator},
            "sequence_duration_seconds": float(duration),
            "cue_count": len(captions),
            "candidate_count": 0,
            "candidates": [],
            "issues": issues,
            "time_source": "SRT subtitle_end used as-is" if end_time_kind == "subtitle_end" else "Whisper speech_end plus configured tail",
            "tail_added_seconds": 0.0 if end_time_kind == "subtitle_end" else float(tail),
            "auto_delete": False,
        }

    cuts = existing_cut_frames or set()
    candidates: list[dict[str, Any]] = []
    candidate_number = 0

    def append_candidate(
        candidate_type: str,
        start: Fraction,
        end: Fraction,
        previous_text: str,
        next_text: str,
        *,
        may_split: bool,
    ) -> None:
        nonlocal candidate_number
        gap = end - start
        if gap < threshold:
            return
        start_frame = _ceil(start * rate)
        end_frame = _floor(end * rate)
        if end_frame <= start_frame:
            issues.append(
                {
                    "code": "candidate_collapsed_to_frame_boundary",
                    "message": f"{candidate_type} 공백이 프레임 경계로 정렬된 뒤 유효하지 않습니다.",
                }
            )
            return
        candidate_number += 1
        start_seconds = Fraction(start_frame, 1) / rate
        end_seconds = Fraction(end_frame, 1) / rate
        existing_edges = [frame for frame in (start_frame, end_frame) if frame in cuts]
        notes: list[str] = []
        if end_time_kind == "subtitle_end":
            notes.append("SRT 종료 시각을 subtitle_end로 사용했으며 0.5초를 다시 더하지 않았습니다.")
        else:
            notes.append(f"Whisper speech_end에 {float(tail):g}초 자막 여유를 적용했습니다.")
        if existing_edges:
            notes.append(f"VEA edit_map에 기존 경계가 있습니다: {existing_edges}")
        if not may_split:
            notes.append("시퀀스 시작/끝 구간은 검토 후보로만 기록하며 자동 분할하지 않습니다.")
        if duration is None:
            notes.append("실제 Premiere 시퀀스 길이와의 비교가 아직 없습니다.")
        source_ranges = _map_source_ranges(start_frame, end_frame, edit_map)
        if not source_ranges:
            notes.append("원본 시간 매핑을 확인할 수 없습니다.")
        candidates.append(
            {
                "candidate_id": f"SILENCE_{candidate_number:03d}" if may_split else f"EDGE_{candidate_type.upper()}",
                "candidate_type": candidate_type,
                "sequence_start": _seconds_text(start_seconds),
                "sequence_end": _seconds_text(end_seconds),
                "sequence_start_seconds": float(start_seconds),
                "sequence_end_seconds": float(end_seconds),
                "duration_seconds": float(gap),
                "frame_aligned_duration_seconds": float(end_seconds - start_seconds),
                "start_frame": start_frame,
                "end_frame": end_frame,
                "previous_caption": previous_text.replace("\r", " ").replace("\n", " "),
                "next_caption": next_text.replace("\r", " ").replace("\n", " "),
                "split_applied": False,
                "split_api_required": bool(may_split),
                "validation_status": "split_candidate_ready" if may_split else "review_only_boundary_gap",
                "existing_cut_boundaries": existing_edges,
                "source_time_ranges": source_ranges,
                "notes": notes,
            }
        )

    for previous, following in zip(merged, merged[1:]):
        gap = following.start - previous.end
        if gap <= 0:
            continue
        if gap >= threshold:
            append_candidate("inter_caption", previous.end, following.start, previous.text, following.text, may_split=True)

    if duration is not None and merged:
        if merged[0].start >= threshold:
            append_candidate("sequence_head", Fraction(0), merged[0].start, "", merged[0].text, may_split=False)
        if duration - merged[-1].end >= threshold:
            append_candidate("sequence_tail", merged[-1].end, duration, merged[-1].text, "", may_split=False)
    elif duration is not None and not merged and duration >= threshold:
        append_candidate("no_captions", Fraction(0), duration, "", "", may_split=False)

    if overlap_count:
        issues.append(
            {
                "code": "overlapping_captions_merged",
                "count": overlap_count,
                "message": "겹치는 자막 구간을 보호 구간으로 병합한 뒤 후보를 계산했습니다.",
            }
        )
    return {
        "status": "ready" if duration is not None else "needs_sequence_duration_check",
        "blocked": False,
        "fps": {"numerator": rate.numerator, "denominator": rate.denominator},
        "sequence_duration_seconds": float(duration) if duration is not None else None,
        "cue_count": len(captions),
        "protected_interval_count": len(merged),
        "overlapping_cue_pairs_merged": overlap_count,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "issues": issues,
        "time_source": "SRT subtitle_end used as-is" if end_time_kind == "subtitle_end" else "Whisper speech_end plus configured tail",
        "configured_tail_seconds": float(tail),
        "tail_added_seconds": 0.0 if end_time_kind == "subtitle_end" else float(tail),
        "minimum_gap_seconds": float(threshold),
        "split_applied": False,
        "auto_delete": False,
    }


def read_whisper_json(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Whisper JSON을 읽지 못했습니다: {source}: {exc}") from exc
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        raise ValueError(f"Whisper JSON에 segments 배열이 없습니다: {source}")
    return segments


CSV_FIELDS = (
    "candidate_id",
    "sequence_start",
    "sequence_end",
    "duration_seconds",
    "start_frame",
    "end_frame",
    "previous_caption",
    "next_caption",
    "split_applied",
    "validation_status",
    "notes",
)


def write_candidate_artifacts(
    payload: dict[str, Any],
    *,
    json_path: str | Path,
    csv_path: str | Path,
) -> tuple[Path, Path]:
    json_target = Path(json_path)
    csv_target = Path(csv_path)
    atomic_write_json(json_target, payload)
    csv_target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for candidate in payload.get("candidates", []):
        row = dict(candidate)
        row["notes"] = " ".join(str(note) for note in candidate.get("notes", []))
        writer.writerow(row)
    lines.append(buffer.getvalue())
    atomic_write_text(csv_target, "".join(lines), encoding="utf-8-sig")
    return json_target, csv_target
