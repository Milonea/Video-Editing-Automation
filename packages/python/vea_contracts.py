"""Validation helpers for the language-neutral VEA contract bundle."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "contracts" / "schemas" / "contracts-v1.schema.json"


class ContractValidationError(ValueError):
    """A contract failed schema or cross-field validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _relative_path_error(value: Any, field: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{field} must be a non-empty relative path"
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return f"{field} must not be absolute"
    if any(part == ".." for part in normalized.split("/")):
        return f"{field} must not escape its declared root"
    return None


def _unique(items: Any, key: str, field: str, errors: list[str]) -> None:
    if not isinstance(items, list):
        return
    values = [item.get(key) for item in items if isinstance(item, dict)]
    if len(values) != len(set(values)):
        errors.append(f"{field} contains duplicate {key} values")


def _semantic_errors(kind: str, value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return errors

    if kind == "MediaAsset":
        error = _relative_path_error(value.get("relative_path"), "relative_path")
        if error:
            errors.append(error)
    elif kind == "AssetIndex":
        assets = value.get("assets", [])
        _unique(assets, "asset_id", "assets", errors)
        for index, asset in enumerate(assets if isinstance(assets, list) else []):
            if isinstance(asset, dict):
                error = _relative_path_error(asset.get("relative_path"), f"assets[{index}].relative_path")
                if error:
                    errors.append(error)
    elif kind == "ProjectManifest":
        error = _relative_path_error(value.get("asset_index"), "asset_index")
        if error:
            errors.append(error)
    elif kind == "TimelineIR":
        tracks = value.get("tracks", [])
        clips = value.get("clips", [])
        _unique(tracks, "track_id", "tracks", errors)
        _unique(clips, "clip_id", "clips", errors)
        track_ids = {item.get("track_id") for item in tracks if isinstance(item, dict)}
        for index, clip in enumerate(clips if isinstance(clips, list) else []):
            if not isinstance(clip, dict):
                continue
            if clip.get("track_id") not in track_ids:
                errors.append(f"clips[{index}].track_id is not declared in tracks")
            if clip.get("end_frame", 0) <= clip.get("start_frame", 0):
                errors.append(f"clips[{index}] must end after it starts")
            if clip.get("source_out_frame", 0) <= clip.get("source_in_frame", 0):
                errors.append(f"clips[{index}] source range must have positive duration")
    elif kind == "EditPlan":
        _unique(value.get("operations", []), "operation_id", "operations", errors)
    elif kind == "EditingRecipe":
        _unique(value.get("steps", []), "step_id", "steps", errors)
        for index, step in enumerate(value.get("steps", [])):
            if isinstance(step, dict) and step.get("duration_frames", 0) < 1:
                errors.append(f"steps[{index}].duration_frames must be positive")
    elif kind in {"Transcript", "Subtitle"}:
        field = "segments" if kind == "Transcript" else "cues"
        id_field = "segment_id" if kind == "Transcript" else "cue_id"
        entries = value.get(field, [])
        _unique(entries, id_field, field, errors)
        for index, entry in enumerate(entries if isinstance(entries, list) else []):
            if isinstance(entry, dict) and entry.get("end_frame", 0) <= entry.get("start_frame", 0):
                errors.append(f"{field}[{index}] must end after it starts")
    elif kind == "Checkpoint":
        completed = set(value.get("completed_step_ids", []))
        pending = set(value.get("pending_step_ids", []))
        if completed & pending:
            errors.append("completed and pending checkpoint steps must be disjoint")
    elif kind == "ExtensionManifest":
        for index, path in enumerate(value.get("asset_roots", [])):
            error = _relative_path_error(path, f"asset_roots[{index}]")
            if error:
                errors.append(error)
        for index, path in enumerate(value.get("schemas", [])):
            error = _relative_path_error(path, f"schemas[{index}]")
            if error:
                errors.append(error)
        _unique(value.get("capabilities", []), "capability_id", "capabilities", errors)
        _unique(value.get("actions", []), "action_id", "actions", errors)
    elif kind == "AgentResult":
        for index, path in enumerate(value.get("artifact_refs", [])):
            error = _relative_path_error(path, f"artifact_refs[{index}]")
            if error:
                errors.append(error)

    return errors


def validate_contract(kind: str, value: Any) -> None:
    """Raise ContractValidationError when schema or safety invariants fail."""
    schema = load_schema()
    if kind not in schema.get("$defs", {}):
        raise ContractValidationError([f"unknown contract type: {kind}"])
    Draft202012Validator.check_schema(schema)
    selected_schema = dict(schema)
    selected_schema["$ref"] = f"#/$defs/{kind}"
    validator = Draft202012Validator(selected_schema, format_checker=FormatChecker())
    schema_errors = [error.message for error in validator.iter_errors(value)]
    semantic_errors = _semantic_errors(kind, value) if not schema_errors else []
    errors = sorted(schema_errors + semantic_errors)
    if errors:
        raise ContractValidationError(errors)

