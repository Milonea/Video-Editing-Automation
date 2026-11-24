from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any


@dataclass(frozen=True)
class FrameRate:
    value: Fraction

    @classmethod
    def parse(cls, value: str | int | float | Fraction) -> "FrameRate":
        if isinstance(value, Fraction):
            rate = value
        else:
            raw = str(value).strip()
            aliases = {
                "23.976": Fraction(24000, 1001),
                "29.97": Fraction(30000, 1001),
                "59.94": Fraction(60000, 1001),
                "119.88": Fraction(120000, 1001),
            }
            if raw in aliases:
                rate = aliases[raw]
            elif "/" in raw:
                left, right = raw.split("/", 1)
                rate = Fraction(int(left), int(right))
            else:
                rate = Fraction(raw)
        if rate <= 0:
            raise ValueError("FPS must be positive")
        return cls(rate)

    @property
    def nominal(self) -> int:
        return round(float(self.value))

    @property
    def drop_frame_compatible(self) -> bool:
        return self.value in (Fraction(30000, 1001), Fraction(60000, 1001))

    def to_json(self) -> dict[str, int]:
        return {"numerator": self.value.numerator, "denominator": self.value.denominator}


@dataclass
class EditDecision:
    source_file: str | None
    source_in: Fraction
    source_out: Fraction | None
    action: str
    ordering: int
    label: str = ""
    notes: str = ""
    original_instruction: str = ""
    padding_before: Fraction = Fraction(0)
    padding_after: Fraction = Fraction(0)
    mute_audio: bool = False
    interpretation_status: str = "interpreted"
    validation_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "source_in": str(self.source_in),
            "source_out": str(self.source_out) if self.source_out is not None else None,
            "action": self.action,
            "ordering": self.ordering,
            "label": self.label,
            "notes": self.notes,
            "original_instruction": self.original_instruction,
            "padding_before_seconds": str(self.padding_before),
            "padding_after_seconds": str(self.padding_after),
            "mute_audio": self.mute_audio,
            "interpretation_status": self.interpretation_status,
            "validation_status": self.validation_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EditDecision":
        return cls(
            source_file=data.get("source_file"),
            source_in=Fraction(str(data["source_in"])),
            source_out=Fraction(str(data["source_out"])) if data.get("source_out") is not None else None,
            action=str(data["action"]),
            ordering=int(data.get("ordering", 0)),
            label=str(data.get("label", "")),
            notes=str(data.get("notes", "")),
            original_instruction=str(data.get("original_instruction", "")),
            padding_before=Fraction(str(data.get("padding_before_seconds", data.get("padding_before", 0)))),
            padding_after=Fraction(str(data.get("padding_after_seconds", data.get("padding_after", 0)))),
            mute_audio=bool(data.get("mute_audio", False)),
            interpretation_status=str(data.get("interpretation_status", "interpreted")),
            validation_status=str(data.get("validation_status", "pending")),
        )


@dataclass
class InstructionSet:
    source_file: str | None
    original_text: str
    edits: list[EditDecision] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    interpretation_status: str = "interpreted"
    validation_status: str = "pending"
    fps: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "original_instruction": self.original_text,
            "fps": self.fps,
            "edits": [edit.to_dict() for edit in self.edits],
            "issues": self.issues,
            "interpretation_status": self.interpretation_status,
            "validation_status": self.validation_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstructionSet":
        return cls(
            source_file=data.get("source_file"),
            original_text=str(data.get("original_instruction", "")),
            edits=[EditDecision.from_dict(item) for item in data.get("edits", [])],
            issues=list(data.get("issues", [])),
            interpretation_status=str(data.get("interpretation_status", "interpreted")),
            validation_status=str(data.get("validation_status", "pending")),
            fps=data.get("fps"),
        )


@dataclass
class TimelineClip:
    source_file: str
    source_in_frame: int
    source_out_frame: int
    timeline_start_frame: int
    timeline_end_frame: int
    source_in_seconds: Fraction
    source_out_seconds: Fraction
    label: str = ""
    notes: str = ""
    ordering: int = 0
    mute_audio: bool = False

    @property
    def duration_frames(self) -> int:
        return self.timeline_end_frame - self.timeline_start_frame

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "source_in_frame": self.source_in_frame,
            "source_out_frame": self.source_out_frame,
            "timeline_start_frame": self.timeline_start_frame,
            "timeline_end_frame": self.timeline_end_frame,
            "source_in_seconds": str(self.source_in_seconds),
            "source_out_seconds": str(self.source_out_seconds),
            "duration_frames": self.duration_frames,
            "label": self.label,
            "notes": self.notes,
            "ordering": self.ordering,
            "mute_audio": self.mute_audio,
        }
