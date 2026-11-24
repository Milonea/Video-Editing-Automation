from __future__ import annotations

import re
from fractions import Fraction

from .models import FrameRate

TIMECODE_RE = re.compile(
    r"^\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{2})(?:([.,])(\d{1,3})|([:;])(\d{1,2}))?\s*$"
)


def parse_timecode(value: str | int | float | Fraction, fps: FrameRate | None = None) -> Fraction:
    """Parse MM:SS, HH:MM:SS, milliseconds, or HH:MM:SS:FF / HH:MM:SS;FF."""
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, (int, float)):
        result = Fraction(str(value))
    else:
        raw = value.strip()
        try:
            result = Fraction(raw)
        except (ValueError, ZeroDivisionError):
            result = None
        if result is None:
            match = TIMECODE_RE.match(raw)
            if not match:
                raise ValueError(f"Unsupported timecode: {value!r}")
            hours_s, minutes_s, seconds_s, decimal_mark, millis_s, frame_sep, frames_s = match.groups()
            if frame_sep:
                if fps is None:
                    raise ValueError("Frame-based timecodes require an explicit FPS")
                hours = int(hours_s or 0)
                minutes = int(minutes_s)
                seconds = int(seconds_s)
                frame = int(frames_s)
                nominal = fps.nominal
                if minutes >= 60 or seconds >= 60 or frame >= nominal:
                    raise ValueError(f"Invalid frame timecode: {value!r}")
                total_nominal = ((hours * 60 + minutes) * 60 + seconds) * nominal + frame
                if frame_sep == ";":
                    if not fps.drop_frame_compatible:
                        raise ValueError("Drop-frame timecode requires 29.97 or 59.94 FPS")
                    drop = 2 if nominal == 30 else 4
                    elapsed_minutes = hours * 60 + minutes
                    skipped = drop * (elapsed_minutes - elapsed_minutes // 10)
                    if seconds == 0 and minutes % 10 != 0 and frame < drop:
                        raise ValueError(f"Illegal dropped frame number in {value!r}")
                    total_nominal -= skipped
                result = Fraction(total_nominal, 1) / fps.value
            else:
                hours = int(hours_s or 0)
                minutes = int(minutes_s)
                seconds = int(seconds_s)
                if seconds >= 60 or (hours_s is not None and minutes >= 60):
                    raise ValueError(f"Invalid timecode: {value!r}")
                result = Fraction((hours * 60 + minutes) * 60 + seconds, 1)
                if decimal_mark:
                    result += Fraction(int(millis_s), 10 ** len(millis_s))
    if result < 0:
        raise ValueError("Timecode cannot be negative")
    return result


def round_fraction(value: Fraction) -> int:
    """Round a non-negative fraction to the nearest integer, ties away from zero."""
    if value < 0:
        return -round_fraction(-value)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def seconds_to_frames(seconds: Fraction, fps: FrameRate) -> int:
    return round_fraction(seconds * fps.value)


def frames_to_seconds(frames: int, fps: FrameRate) -> Fraction:
    return Fraction(frames, 1) / fps.value


def format_srt_timestamp(seconds: Fraction | float | int) -> str:
    total_ms = round_fraction(Fraction(str(float(seconds))) * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    whole_seconds, milliseconds = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"
