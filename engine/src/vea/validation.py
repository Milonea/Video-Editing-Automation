from __future__ import annotations

import hashlib
import json
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checkpoint import atomic_write_json, atomic_write_text
from .media import MediaInfo, probe_media
from .models import FrameRate, TimelineClip
from .timecode import frames_to_seconds


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def validate_project(
    project_dir: str | Path,
    media: MediaInfo | None = None,
    clips: list[TimelineClip] | None = None,
    fps: FrameRate | None = None,
) -> list[ValidationIssue]:
    root = Path(project_dir)
    issues: list[ValidationIssue] = []
    for relative in ("03_ANALYSIS/instructions.json", "03_ANALYSIS/tracks.json", "04_ROUGHCUT/edit_map.json", "04_ROUGHCUT/cuts.csv"):
        if not (root / relative).is_file():
            issues.append(ValidationIssue("error", "missing_required_file", f"필수 파일이 없습니다: {relative}"))
    xml_path = root / "04_ROUGHCUT/roughcut.xml"
    if xml_path.is_file():
        try:
            xml_root = ET.parse(xml_path).getroot()
            if xml_root.tag != "xmeml":
                issues.append(ValidationIssue("error", "invalid_xml_root", "Premiere XML 루트가 xmeml이 아닙니다."))
            if not xml_root.findall(".//sequence/media/video/track/clipitem"):
                issues.append(ValidationIssue("error", "no_video_clips", "XML에 영상 클립이 없습니다."))
        except ET.ParseError as exc:
            issues.append(ValidationIssue("error", "invalid_xml", f"roughcut.xml 파싱 실패: {exc}"))
    else:
        issues.append(ValidationIssue("warning", "xml_not_generated", "roughcut.xml이 없어 Premiere 가져오기는 준비되지 않았습니다."))
    voice = root / "05_AUDIO/roughcut_voice.wav"
    if voice.is_file() and clips and fps:
        try:
            voice_info = probe_media(voice)
            expected = float(frames_to_seconds(clips[-1].timeline_end_frame, fps))
            if abs(voice_info.duration - expected) > max(0.05, 1 / float(fps.value)):
                issues.append(
                    ValidationIssue(
                        "error",
                        "voice_duration_mismatch",
                        f"보이스 길이 {voice_info.duration:.3f}s, 타임라인 예상 길이 {expected:.3f}s",
                    )
                )
        except Exception as exc:
            issues.append(ValidationIssue("error", "voice_probe_failed", f"보이스 WAV 검사 실패: {exc}"))
    else:
        selection_path = root / "03_ANALYSIS/voice_selection.json"
        selected_indexes: list[int] = []
        if selection_path.is_file():
            try:
                selection = json.loads(selection_path.read_text(encoding="utf-8"))
                selected_indexes = [int(value) for value in selection.get("selected_global_stream_indexes", [])]
            except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
                selected_indexes = []
        if selected_indexes:
            indexes_text = ", ".join(str(value) for value in selected_indexes)
            issues.append(
                ValidationIssue(
                    "needs_review",
                    "voice_roughcut_not_generated",
                    f"보이스 글로벌 스트림 {indexes_text}가 선택됐지만 05_AUDIO/roughcut_voice.wav가 아직 생성되지 않았습니다.",
                )
            )
        else:
            issues.append(ValidationIssue("needs_review", "voice_track_unselected", "전사용 보이스가 없습니다. 트랙 미리듣기 후 선택하세요."))
    instructions_path = root / "03_ANALYSIS/instructions.json"
    if instructions_path.is_file():
        try:
            data = json.loads(instructions_path.read_text(encoding="utf-8"))
            if data.get("interpretation_status") == "needs_review":
                issues.append(ValidationIssue("needs_review", "instruction_ambiguity", "일부 지시의 해석 또는 범위를 확인해야 합니다."))
        except (OSError, json.JSONDecodeError):
            issues.append(ValidationIssue("error", "invalid_instruction_json", "instructions.json을 읽을 수 없습니다."))
    project_path = root / "project.json"
    if project_path.is_file():
        try:
            metadata = json.loads(project_path.read_text(encoding="utf-8"))
            relink = metadata.get("source_relink") or {}
            if relink.get("match") == "technical_signature_only_user_confirmed":
                issues.append(
                    ValidationIssue(
                        "needs_review",
                        "relink_content_not_verified",
                        "재연결 파일은 기술 구성과 길이만 비교했습니다. 영상 내용과 기존 파생 오디오/전사 결과를 확인하세요.",
                    )
                )
        except (OSError, json.JSONDecodeError):
            issues.append(ValidationIssue("error", "invalid_project_json", "project.json을 읽을 수 없습니다."))
    if media and media.video and media.video.get("is_vfr_heuristic"):
        issues.append(ValidationIssue("needs_review", "possible_vfr", "FFprobe의 프레임레이트 불일치로 VFR 가능성이 있습니다. Premiere에서 원본 재생/싱크를 확인하세요."))
    return issues


def validate_manifest_assets(project_dir: str | Path) -> list[ValidationIssue]:
    """Check each manifest asset's containment, presence, size, and SHA-256."""
    root = Path(project_dir).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return [ValidationIssue("warning", "manifest_missing", "manifest.json이 없어 자산 해시 검사를 건너뛰었습니다.")]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [ValidationIssue("error", "invalid_manifest", f"manifest.json을 읽을 수 없습니다: {exc}")]
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        return [ValidationIssue("error", "invalid_manifest_assets", "manifest.json의 assets가 배열이 아닙니다.")]

    issues: list[ValidationIssue] = []
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            issues.append(ValidationIssue("error", "invalid_manifest_asset", "manifest 자산 항목에 상대 경로가 없습니다."))
            continue
        relative = Path(asset["path"])
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            issues.append(ValidationIssue("error", "manifest_path_escape", f"프로젝트 외부를 가리키는 자산 경로입니다: {asset['path']}"))
            continue
        if not candidate.is_file():
            candidate = _resolve_unicode_normalized_path(root, relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                issues.append(ValidationIssue("error", "manifest_path_escape", f"프로젝트 외부를 가리키는 자산 경로입니다: {asset['path']}"))
                continue
            if not candidate.is_file():
                issues.append(ValidationIssue("error", "manifest_asset_missing", f"매니페스트 자산이 없습니다: {asset['path']}"))
                continue
        expected_size = asset.get("size_bytes")
        actual_size = candidate.stat().st_size
        if expected_size != actual_size:
            issues.append(ValidationIssue("error", "manifest_asset_size_mismatch", f"자산 크기가 달라졌습니다: {asset['path']}"))
            continue
        expected_hash = asset.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            issues.append(ValidationIssue("error", "manifest_asset_hash_missing", f"자산 SHA-256이 없거나 잘못되었습니다: {asset['path']}"))
            continue
        digest = hashlib.sha256()
        try:
            with candidate.open("rb") as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            issues.append(ValidationIssue("error", "manifest_asset_unreadable", f"자산을 읽을 수 없습니다: {asset['path']}: {exc}"))
            continue
        if digest.hexdigest() != expected_hash:
            issues.append(ValidationIssue("error", "manifest_asset_hash_mismatch", f"자산 SHA-256이 다릅니다: {asset['path']}"))
    return issues


def _resolve_unicode_normalized_path(root: Path, relative: Path) -> Path:
    """Resolve a manifest path across filesystems with different Unicode normalization."""
    current = root
    for part in relative.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            current = current.parent
            continue
        direct = current / part
        if direct.exists():
            current = direct
            continue
        if not current.is_dir():
            return direct
        normalized = unicodedata.normalize("NFC", part)
        try:
            matches = [
                child
                for child in current.iterdir()
                if unicodedata.normalize("NFC", child.name) == normalized
            ]
        except OSError:
            return direct
        if len(matches) != 1:
            return direct
        current = matches[0]
    return current


def write_validation_report(path: str | Path, issues: list[ValidationIssue], context: dict[str, Any] | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# VEA 자동 검증 결과", "", "자동 검사는 파일 구조와 기본 시간축 조건만 확인합니다. Premiere 호환성은 실제 앱에서 가져와 확인해야 합니다.", ""]
    if context:
        for key, value in context.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    if not issues:
        lines.append("모든 자동 검사 항목을 통과했습니다.")
    else:
        for issue in issues:
            lines.append(f"- [{issue.severity.upper()}] {issue.code}: {issue.message}")
    atomic_write_text(target, "\n".join(lines) + "\n")
    atomic_write_json(target.with_suffix(".json"), {"issues": [issue.to_dict() for issue in issues], "context": context or {}})
    return target
