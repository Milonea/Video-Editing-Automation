from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

from .models import EditDecision, FrameRate, TimelineClip
from .paths import normalize_path, same_path
from .timecode import frames_to_seconds, seconds_to_frames


class TimelineError(ValueError):
    pass


def _subtract(
    interval: tuple[Fraction, Fraction, EditDecision],
    cut: tuple[Fraction, Fraction],
) -> list[tuple[Fraction, Fraction, EditDecision]]:
    start, end, edit = interval
    cut_start, cut_end = cut
    if cut_end <= start or cut_start >= end:
        return [interval]
    pieces: list[tuple[Fraction, Fraction, EditDecision]] = []
    if cut_start > start:
        pieces.append((start, min(cut_start, end), edit))
    if cut_end < end:
        pieces.append((max(cut_end, start), end, edit))
    return [piece for piece in pieces if piece[1] > piece[0]]


def resolve_intervals(
    edits: list[EditDecision],
    source_file: str | Path,
    duration: Fraction,
) -> list[tuple[Fraction, Fraction, EditDecision]]:
    source = normalize_path(source_file)
    usable = [edit for edit in edits if edit.validation_status in {"valid", "pending"}]
    relevant = [edit for edit in usable if edit.source_file is None or same_path(edit.source_file, source)]
    if any(edit.source_file and not same_path(edit.source_file, source) for edit in usable):
        raise TimelineError("한 타임라인에서 여러 원본 파일의 편집점은 현재 지원하지 않습니다.")
    ranges = [edit for edit in relevant if edit.source_out is not None and edit.action in {"keep", "delete"}]

    def expanded_range(edit: EditDecision) -> tuple[Fraction, Fraction]:
        start = edit.source_in - edit.padding_before
        end = (edit.source_out or edit.source_in) + edit.padding_after
        if edit.padding_before < 0 or edit.padding_after < 0 or start < 0 or end > duration:
            raise TimelineError(
                f"앞뒤 여유를 적용한 편집 구간이 원본 범위를 벗어납니다: {start}–{end}초 (원본 {duration}초)"
            )
        return start, end

    keeps = sorted((edit for edit in ranges if edit.action == "keep"), key=lambda item: item.ordering)
    deletes = [expanded_range(edit) for edit in ranges if edit.action == "delete"]
    cut_points = sorted({edit.source_in for edit in relevant if edit.action == "cut_at"})
    if keeps:
        intervals = [(*expanded_range(edit), edit) for edit in keeps]
    elif deletes:
        seed = EditDecision(source_file=source, source_in=Fraction(0), source_out=duration, action="keep", ordering=0)
        intervals = [(Fraction(0), duration, seed)]
    elif cut_points:
        seed = EditDecision(source_file=source, source_in=Fraction(0), source_out=duration, action="keep", ordering=0)
        intervals = [(Fraction(0), duration, seed)]
    else:
        raise TimelineError("확정된 유지/삭제 구간이 없습니다. 모호한 지시를 먼저 확인하세요.")
    for start, end, _ in intervals:
        if start < 0 or end <= start or end > duration:
            raise TimelineError(f"편집 구간이 원본 범위를 벗어납니다: {start}–{end}초 (원본 {duration}초)")
    for cut in deletes:
        for interval in list(intervals):
            intervals.remove(interval)
            intervals.extend(_subtract(interval, cut))
    for point in cut_points:
        if point <= 0 or point >= duration:
            continue
        split_intervals: list[tuple[Fraction, Fraction, EditDecision]] = []
        for start, end, edit in intervals:
            if start < point < end:
                split_intervals.extend([(start, point, edit), (point, end, edit)])
            else:
                split_intervals.append((start, end, edit))
        intervals = split_intervals
    if not intervals:
        raise TimelineError("지정된 편집점이 모든 구간을 제거했습니다.")
    intervals.sort(key=lambda item: item[2].ordering)
    return intervals


def build_timeline(
    edits: list[EditDecision],
    source_file: str | Path,
    duration: Fraction,
    fps: FrameRate,
) -> list[TimelineClip]:
    intervals = resolve_intervals(edits, source_file, duration)
    clips: list[TimelineClip] = []
    cursor = 0
    for start_seconds, end_seconds, edit in intervals:
        in_frame = seconds_to_frames(start_seconds, fps)
        out_frame = seconds_to_frames(end_seconds, fps)
        if out_frame <= in_frame:
            raise TimelineError("프레임 반올림 후 길이가 0인 편집 구간이 생겼습니다.")
        clip = TimelineClip(
            source_file=normalize_path(source_file),
            source_in_frame=in_frame,
            source_out_frame=out_frame,
            timeline_start_frame=cursor,
            timeline_end_frame=cursor + out_frame - in_frame,
            source_in_seconds=frames_to_seconds(in_frame, fps),
            source_out_seconds=frames_to_seconds(out_frame, fps),
            label=edit.label,
            notes=edit.notes,
            ordering=edit.ordering,
            mute_audio=edit.mute_audio,
        )
        clips.append(clip)
        cursor += clip.duration_frames
    return clips


def make_edit_map(clips: list[TimelineClip], fps: FrameRate) -> dict[str, Any]:
    return {
        "version": 1,
        "fps": fps.to_json(),
        "duration_frames": clips[-1].timeline_end_frame if clips else 0,
        "duration_seconds": str(frames_to_seconds(clips[-1].timeline_end_frame, fps)) if clips else "0",
        "clips": [
            {
                **clip.to_dict(),
                "timeline_start_seconds": str(frames_to_seconds(clip.timeline_start_frame, fps)),
                "timeline_end_seconds": str(frames_to_seconds(clip.timeline_end_frame, fps)),
            }
            for clip in clips
        ],
    }
