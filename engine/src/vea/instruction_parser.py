from __future__ import annotations

import csv
import io
import json
import re
from fractions import Fraction
from typing import Any

from .models import EditDecision, FrameRate, InstructionSet
from .timecode import parse_timecode

_TIME_TOKEN = re.compile(r"(?<![\d:])(?:\d{1,3}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3}|[:;]\d{1,2})?(?![\d:])")
_RANGE_SEP = re.compile(r"(?:~|〜|～|–|—|\bto\b|\buntil\b|부터|까지)", re.IGNORECASE)
_MEDIA_SUFFIX = re.compile(r"\.(?:mkv|mp4|mov|mxf|webm|avi)\b", re.IGNORECASE)

_KEEP_WORDS = ("유지", "사용", "포함", "살려", "보존", "keep", "use", "include", "retain")
_DELETE_WORDS = ("삭제", "제거", "제외", "빼", "자르", "remove", "delete", "omit", "exclude")
_CUT_WORDS = ("해당 시각에서 컷", "여기서 컷", "cut at", "split at")
_GLOBAL_KEEP = re.compile(r"(?:순서대로\s*)?(?:붙여|이어\s*붙여|연결해|모아\s*붙여|편집점.*사용|구간.*사용)", re.IGNORECASE)
_PADDING_NUMBER = r"(\d+(?:[.,]\d+)?)\s*(?:초|seconds?|secs?|s)"
_SYMMETRIC_PADDING = (
    re.compile(rf"(?:앞뒤|양쪽|전후)\s*{_PADDING_NUMBER}\s*(?:여유|패딩|추가)?", re.IGNORECASE),
    re.compile(rf"{_PADDING_NUMBER}\s*(?:앞뒤|양쪽|전후)\s*(?:여유|패딩|추가)?", re.IGNORECASE),
)
_BEFORE_PADDING = re.compile(rf"(?:앞|전)\s*{_PADDING_NUMBER}\s*(?:여유|패딩|추가)?", re.IGNORECASE)
_AFTER_PADDING = re.compile(rf"(?:뒤|후)\s*{_PADDING_NUMBER}\s*(?:여유|패딩|추가)?", re.IGNORECASE)
_AUDIO_MUTE_WORDS = ("음소거", "소리 끄", "오디오 끄", "mute audio", "mute sound", "mute")


def _action(text: str, has_range: bool) -> tuple[str, str]:
    lower = text.casefold()
    if any(word in lower for word in _DELETE_WORDS):
        return "delete", "interpreted"
    if any(word in lower for word in _CUT_WORDS):
        return ("cut_at" if not has_range else "unknown"), ("interpreted" if not has_range else "needs_review")
    keep_words = tuple(word for word in _KEEP_WORDS if word != "사용")
    explicit_use = re.search(r"(?<![가-힣])사용(?:해|하세요|해주세요|하십시오)?(?![가-힣])", lower)
    if any(word in lower for word in keep_words) or explicit_use:
        return "keep", "interpreted"
    return "unknown", "needs_review"


def _fraction_time(value: Any, fps: FrameRate | None) -> Fraction:
    if value is None or value == "":
        raise ValueError("Missing time value")
    return parse_timecode(value, fps)


def _padding_seconds(value: Any, fps: FrameRate | None) -> Fraction:
    if value is None or value == "":
        return Fraction(0)
    if isinstance(value, (int, float, Fraction)):
        return Fraction(str(value))
    raw = str(value).strip()
    if ":" in raw or ";" in raw:
        return parse_timecode(raw, fps)
    return Fraction(raw.replace(",", "."))


def _line_padding(line: str) -> tuple[Fraction, Fraction]:
    for pattern in _SYMMETRIC_PADDING:
        match = pattern.search(line)
        if match:
            seconds = Fraction(match.group(1).replace(",", "."))
            return seconds, seconds
    before = _BEFORE_PADDING.search(line)
    after = _AFTER_PADDING.search(line)
    return (
        Fraction(before.group(1).replace(",", ".")) if before else Fraction(0),
        Fraction(after.group(1).replace(",", ".")) if after else Fraction(0),
    )


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"true", "yes", "1", "on", "mute", "muted"}:
        return True
    if normalized in {"false", "no", "0", "off", "keep", "unmuted", ""}:
        return False
    raise ValueError(f"음소거 여부를 해석할 수 없습니다: {value!r}")


def _mutes_audio(line: str) -> bool:
    lower = line.casefold()
    if any(phrase in lower for phrase in ("음소거 하지", "음소거하지", "소리 끄지", "소리끄지")):
        return False
    if re.search(r"\b(?:unmute|do not mute|don't mute|not muted)\b", lower):
        return False
    return any(word in lower for word in _AUDIO_MUTE_WORDS)


def _from_structured(
    rows: list[dict[str, Any]],
    original: str,
    source_file: str | None,
    fps: FrameRate | None,
    duration: Fraction | None,
) -> InstructionSet:
    result = InstructionSet(source_file=source_file, original_text=original, fps=fps.to_json() if fps else None)
    for order, row in enumerate(rows, 1):
        line = str(row.get("original_instruction") or row.get("instruction") or "")
        row_source = row.get("source_file") or source_file
        action = str(row.get("action") or "").casefold().replace(" ", "_")
        if action in ("use", "include", "retain"):
            action = "keep"
        elif action in ("remove", "omit", "exclude"):
            action = "delete"
        try:
            start = _fraction_time(row.get("source_in", row.get("in")), fps)
            end_value = row.get("source_out", row.get("out"))
            end = _fraction_time(end_value, fps) if end_value is not None and end_value != "" else None
            padding = row.get("padding") if isinstance(row.get("padding"), dict) else {}
            padding_before = _padding_seconds(
                row.get("padding_before_seconds", row.get("padding_before", padding.get("before_seconds", 0))), fps
            )
            padding_after = _padding_seconds(
                row.get("padding_after_seconds", row.get("padding_after", padding.get("after_seconds", 0))), fps
            )
            audio_action = str(row.get("audio_action") or "").casefold().replace(" ", "_")
            if audio_action in {"mute", "muted", "silence"}:
                mute_audio = True
            elif audio_action in {"keep", "retain", "preserve"}:
                mute_audio = False
            elif not audio_action:
                mute_audio = _bool_value(row.get("mute_audio", False))
            else:
                raise ValueError(f"지원하지 않는 audio_action: {audio_action}")
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            result.issues.append(f"행 {order}: 시간값을 해석하지 못했습니다: {exc}")
            continue
        interpretation = "interpreted" if action in {"keep", "delete", "cut_at"} else "needs_review"
        if action not in {"keep", "delete", "cut_at"}:
            result.issues.append(f"행 {order}: action이 keep/delete/cut_at 중 하나가 아닙니다.")
        if end is None and action != "cut_at":
            interpretation = "needs_review"
            result.issues.append(f"행 {order}: 종료 시각이 없어 구간을 확정하지 않았습니다.")
        ordering_value = row.get("ordering", row.get("order", order))
        if ordering_value is None or ordering_value == "":
            ordering_value = order
        try:
            ordering = int(ordering_value)
        except (TypeError, ValueError):
            ordering = 0
            result.issues.append(f"행 {order}: ordering은 정수여야 합니다.")
        edit = EditDecision(
            source_file=str(row_source) if row_source else None,
            source_in=start,
            source_out=end,
            action=action or "unknown",
            ordering=ordering,
            label=str(row.get("label") or ""),
            notes=str(row.get("notes") or ""),
            original_instruction=line or json.dumps(row, ensure_ascii=False),
            padding_before=padding_before,
            padding_after=padding_after,
            mute_audio=mute_audio,
            interpretation_status=interpretation,
        )
        result.edits.append(edit)
    _validate(result, duration)
    return result


def _parse_json(
    value: Any,
    original: str,
    source_file: str | None,
    fps: FrameRate | None,
    duration: Fraction | None,
) -> InstructionSet:
    if isinstance(value, dict):
        rows = value.get("edits", value.get("segments", value.get("cuts")))
        if rows is None:
            rows = [value]
    elif isinstance(value, list):
        rows = value
    else:
        raise ValueError("JSON instruction must be an object or array")
    if not isinstance(rows, list):
        raise ValueError("JSON edits/segments/cuts must be an array")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Each JSON edit must be an object")
    return _from_structured(rows, original, source_file, fps, duration)


def _parse_csv(
    original: str,
    source_file: str | None,
    fps: FrameRate | None,
    duration: Fraction | None,
) -> InstructionSet:
    rows = list(csv.DictReader(io.StringIO(original)))
    if not rows or not ({"source_in", "in"} & set(rows[0])):
        raise ValueError("CSV needs a source_in or in column")
    return _from_structured(rows, original, source_file, fps, duration)


def _parse_text(
    original: str,
    source_file: str | None,
    fps: FrameRate | None,
    duration: Fraction | None,
) -> InstructionSet:
    result = InstructionSet(source_file=source_file, original_text=original, fps=fps.to_json() if fps else None)
    # A clear top-level request such as "위 구간을 순서대로 붙여" applies to
    # otherwise unlabeled ranges. Per-line keep/delete actions still take precedence.
    global_keep = bool(_GLOBAL_KEEP.search(original))
    for line_number, raw_line in enumerate(original.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        numbered = re.match(r"^(\d+)[.)]\s+", line)
        explicit_order = int(numbered.group(1)) if numbered else None
        matches = list(_TIME_TOKEN.finditer(line))
        if not matches:
            continue
        range_match = _RANGE_SEP.search(line)
        adjacent_pair = (
            len(matches) == 2
            and not line[matches[0].end() : matches[1].start()].strip()
        )
        if len(matches) >= 2 and (range_match or adjacent_pair):
            # A line may contain several ranges; parse each adjacent pair only when a range separator
            # is directly between the timestamps.
            pairs: list[tuple[re.Match[str], re.Match[str]]] = []
            for left, right in zip(matches, matches[1:]):
                between = line[left.end() : right.start()]
                if _RANGE_SEP.search(between):
                    pairs.append((left, right))
            if not pairs:
                pairs = [(matches[0], matches[1])]
            for pair_index, (left, right) in enumerate(pairs):
                start_text, end_text = left.group(), right.group()
                context = line[max(0, left.start() - 40) : min(len(line), right.end() + 80)]
                action, interpretation = _action(context, has_range=True)
                mute_audio = _mutes_audio(context)
                if action == "unknown" and mute_audio:
                    # A clear range-scoped audio mute instruction retains the
                    # video segment and disables its audio in the timeline.
                    action, interpretation = "keep", "interpreted"
                if action == "unknown" and global_keep:
                    action, interpretation = "keep", "interpreted"
                label = line[right.end() :].strip(" \t-–—:：,，.。")
                label = re.sub(
                    r"^(?:유지|사용|포함|삭제|제거|제외|keep|use|include|delete|remove)(?:\s|$)",
                    "",
                    label,
                    flags=re.I,
                ).strip()
                try:
                    start, end = parse_timecode(start_text, fps), parse_timecode(end_text, fps)
                except ValueError as exc:
                    result.issues.append(f"줄 {line_number}: {exc}")
                    continue
                if action == "unknown":
                    result.issues.append(f"줄 {line_number}: 구간의 유지/삭제 의도가 불명확합니다. 임의 적용하지 않았습니다.")
                padding_before, padding_after = _line_padding(line)
                result.edits.append(
                    EditDecision(
                        source_file=source_file,
                        source_in=start,
                        source_out=end,
                        action=action,
                        ordering=(explicit_order + pair_index) if explicit_order is not None else len(result.edits) + 1,
                        label=label,
                        notes="",
                        original_instruction=raw_line,
                        padding_before=padding_before,
                        padding_after=padding_after,
                        mute_audio=mute_audio,
                        interpretation_status=interpretation,
                    )
                )
        else:
            token = matches[0].group()
            action, interpretation = _action(line, has_range=False)
            try:
                at = parse_timecode(token, fps)
            except ValueError as exc:
                result.issues.append(f"줄 {line_number}: {exc}")
                continue
            if action != "cut_at":
                action = "unknown"
                interpretation = "needs_review"
                result.issues.append(f"줄 {line_number}: 단일 타임코드만 있어 구간으로 확장하지 않았습니다.")
            result.edits.append(
                EditDecision(
                    source_file=source_file,
                    source_in=at,
                    source_out=None,
                    action=action,
                    ordering=len(result.edits) + 1,
                    label="",
                    notes=line,
                    original_instruction=raw_line,
                    interpretation_status=interpretation,
                )
            )
    _validate(result, duration)
    return result


def _validate(result: InstructionSet, duration: Fraction | None) -> None:
    valid_ranges: list[EditDecision] = []
    seen: set[tuple[Fraction, Fraction | None, str, str | None]] = set()
    seen_orderings: set[int] = set()
    needs_review = False
    for edit in result.edits:
        if edit.interpretation_status == "needs_review" or edit.action == "unknown":
            needs_review = True
        if edit.ordering <= 0 or edit.ordering in seen_orderings:
            edit.validation_status = "invalid_order"
            result.issues.append(f"지시 {edit.ordering}: 순서 번호가 0 이하이거나 중복됩니다.")
            needs_review = True
            continue
        seen_orderings.add(edit.ordering)
        if edit.action == "cut_at":
            if duration is not None and edit.source_in > duration:
                edit.validation_status = "out_of_range"
                result.issues.append(f"지시 {edit.ordering}: 컷 지점이 원본 길이를 초과합니다.")
                needs_review = True
            else:
                edit.validation_status = "valid"
            continue
        if edit.source_out is None:
            edit.validation_status = "needs_review"
            needs_review = True
            continue
        if edit.source_out <= edit.source_in:
            edit.validation_status = "invalid"
            result.issues.append(f"지시 {edit.ordering}: 종료 시각이 시작 시각보다 늦어야 합니다.")
            needs_review = True
            continue
        if edit.padding_before < 0 or edit.padding_after < 0:
            edit.validation_status = "invalid_padding"
            result.issues.append(f"지시 {edit.ordering}: 앞뒤 여유는 음수일 수 없습니다.")
            needs_review = True
            continue
        effective_start = edit.source_in - edit.padding_before
        effective_end = edit.source_out + edit.padding_after
        if effective_start < 0 or (duration is not None and effective_end > duration):
            edit.validation_status = "out_of_range"
            result.issues.append(f"지시 {edit.ordering}: 편집 구간이 원본 길이를 초과하거나 앞뒤 여유가 원본 범위를 벗어납니다.")
            needs_review = True
            continue
        key = (edit.source_in, edit.source_out, edit.action, edit.source_file)
        if key in seen:
            edit.validation_status = "duplicate"
            result.issues.append(f"지시 {edit.ordering}: 중복 구간입니다.")
            needs_review = True
            continue
        seen.add(key)
        edit.validation_status = "valid"
        valid_ranges.append(edit)
    ordered = sorted(valid_ranges, key=lambda item: (item.source_file or "", item.source_in, item.source_out or Fraction(0)))
    for previous, current in zip(ordered, ordered[1:]):
        previous_end = (previous.source_out or previous.source_in) + previous.padding_after
        current_start = current.source_in - current.padding_before
        if previous.source_file == current.source_file and previous_end and current_start < previous_end:
            previous.validation_status = current.validation_status = "overlap"
            result.issues.append(f"지시 {previous.ordering}과 {current.ordering}: 앞뒤 여유를 포함한 구간도 겹치는 구간입니다.")
            needs_review = True
    result.interpretation_status = "needs_review" if needs_review else "interpreted"
    result.validation_status = "needs_review" if needs_review else "valid"


def parse_instructions(
    text: str,
    source_file: str | None = None,
    fps: FrameRate | None = None,
    duration: Fraction | None = None,
) -> InstructionSet:
    """Parse JSON, CSV, or conservative line-oriented natural-language instructions."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("Instruction text is empty")
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON instructions: {exc}") from exc
        return _parse_json(value, text, source_file, fps, duration)
    first_line = next((line for line in stripped.splitlines() if line.strip()), "")
    if "," in first_line and ("source_in" in first_line.casefold() or "start" in first_line.casefold()):
        return _parse_csv(text, source_file, fps, duration)
    return _parse_text(text, source_file, fps, duration)
