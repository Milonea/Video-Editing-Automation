from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .checkpoint import atomic_write_json

KST = timezone(timedelta(hours=9), name="KST")
VERSION_INDEX_NAME = "project_versions.json"
PROJECT_STAGES = {
    "SOURCE",
    "ROUGHCUT",
    "TRANSCRIBED",
    "SILENCE_SPLIT",
    "EDITING",
    "REVIEW",
    "FINAL",
}
VERSIONED_EXTENSIONS = {".prproj", ".xml"}
EXPORT_EXTENSIONS = {".mp4", ".mov", ".mxf", ".avi"}
VERSION_STAMP_PATTERN = re.compile(
    r"_(SOURCE|ROUGHCUT|TRANSCRIBED|SILENCE_SPLIT|EDITING|REVIEW|FINAL)_"
    r"(\d{8}_\d{6})_KST(?:_\d{2,})?$",
    re.IGNORECASE,
)


def now_kst() -> datetime:
    return datetime.now(KST)


def format_kst_timestamp(value: datetime | None = None) -> str:
    moment = (value or now_kst()).astimezone(KST)
    return moment.strftime("%Y%m%d_%H%M%S_KST")


def safe_filename_component(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    cleaned = cleaned[:100].rstrip(" ._")
    if not cleaned:
        cleaned = "VEA_Project"
    if cleaned.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        cleaned = f"VEA_{cleaned}"
    return cleaned


def version_filename(
    project_name: str,
    stage: str,
    extension: str,
    *,
    at: datetime | None = None,
    directory: str | Path | None = None,
) -> str:
    normalized_stage = stage.upper()
    if normalized_stage not in PROJECT_STAGES:
        raise ValueError(f"지원하지 않는 프로젝트 단계입니다: {stage}")
    suffix = extension if extension.startswith(".") else f".{extension}"
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix):
        raise ValueError(f"지원하지 않는 파일 확장자입니다: {extension}")
    if suffix.casefold() not in VERSIONED_EXTENSIONS:
        raise ValueError(f"지원하지 않는 프로젝트 파일 확장자입니다: {extension}")
    base = f"{safe_filename_component(project_name)}_{normalized_stage}_{format_kst_timestamp(at)}"
    candidate = f"{base}{suffix}"
    if directory is None:
        return candidate
    root = Path(directory)
    ordinal = 1
    while (root / candidate).exists():
        candidate = f"{base}_{ordinal:02d}{suffix}"
        ordinal += 1
    return candidate


def version_path(
    directory: str | Path,
    project_name: str,
    stage: str,
    extension: str,
    *,
    at: datetime | None = None,
) -> Path:
    root = Path(directory)
    return root / version_filename(project_name, stage, extension, at=at, directory=root)


def _iso_kst(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=KST).isoformat(timespec="seconds")


def _filesystem_created_at(stat: os.stat_result) -> str | None:
    birthtime = getattr(stat, "st_birthtime", None)
    if birthtime is not None:
        return _iso_kst(birthtime)
    if os.name == "nt":
        return _iso_kst(stat.st_ctime)
    return None


def _filename_generated_at(path: Path) -> str | None:
    match = VERSION_STAMP_PATTERN.search(path.stem)
    if not match:
        return None
    try:
        moment = datetime.strptime(match.group(2), "%Y%m%d_%H%M%S").replace(tzinfo=KST)
    except ValueError:
        return None
    return moment.isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _stage_for_file(root: Path, path: Path) -> str | None:
    text = f"{path.relative_to(root).as_posix()} {path.stem}".casefold()
    if "silence_split" in text:
        return "SILENCE_SPLIT"
    if "roughcut" in text or "러프컷" in text or "04_roughcut" in text:
        return "ROUGHCUT"
    if "transcribed" in text or "transcript" in text or "subtitle" in text:
        return "TRANSCRIBED"
    if "final" in text or "export" in text:
        return "FINAL"
    if any(marker in text for marker in ("review", "validation", "검수", "검증")):
        return "REVIEW"
    return "EDITING" if path.suffix.casefold() == ".prproj" else None


def _is_autosave(path: Path) -> bool:
    return any(part.casefold() in {"adobe premiere pro auto-save", "auto-save", "autosave"} for part in path.parts)


def _is_backup(path: Path) -> bool:
    return any(part.casefold() in {"backup", "backups"} for part in path.parts)


def _latest_export(root: Path) -> dict[str, Any] | None:
    folder = root / "09_EXPORT"
    if not folder.is_dir():
        return None
    paths = [
        path for path in folder.rglob("*")
        if path.is_file() and not path.name.startswith("._") and path.suffix.casefold() in EXPORT_EXTENSIONS
    ]
    path = max(paths, key=lambda item: item.stat().st_mtime, default=None)
    if path is None:
        return None
    stat = path.stat()
    return {
        "file_path": _relative_path(root, path),
        "generated_at": _filename_generated_at(path),
        "last_modified_at": _iso_kst(stat.st_mtime),
        "file_size_bytes": stat.st_size,
        "timestamp_basis": "version_filename_kst" if _filename_generated_at(path) else "filesystem_modification_time",
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _verified_evidence(root: Path) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    report_dir = root / "10_REPORTS"
    if not report_dir.is_dir():
        return evidence
    for report_path in report_dir.glob("*premiere*verification*.json"):
        report = _load_json(report_path)
        if not report or report.get("status") != "verified":
            continue
        relative = report.get("project_path")
        saved = report.get("save_evidence") or {}
        if not relative or not saved.get("sha256"):
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        stat = candidate.stat()
        if stat.st_size != saved.get("size_bytes") or _sha256(candidate) != saved.get("sha256"):
            continue
        try:
            key = _relative_path(root, candidate).casefold()
        except ValueError:
            continue
        evidence[key] = {
            "report_path": _relative_path(root, report_path),
            "verified_at": report.get("verified_at") or saved.get("last_write_time_utc"),
            "sha256": saved["sha256"],
        }
    return evidence


def _read_previous_index(root: Path) -> dict[str, Any]:
    data = _load_json(root / VERSION_INDEX_NAME)
    return data if data and data.get("schema_version") == 1 else {}


def _sync_manifest_version_summary(root: Path, index: dict[str, Any]) -> None:
    manifest_path = root / "manifest.json"
    manifest = _load_json(manifest_path)
    if not manifest:
        return
    summary = {
        "index_path": VERSION_INDEX_NAME,
        "generated_at": index.get("generated_at"),
        "latest_working_version": index.get("latest_working_version"),
        "latest_verified_version": index.get("latest_verified_version"),
        "latest_export_version": index.get("latest_export_version"),
        "version_count": len(index.get("versions", [])),
    }
    if manifest.get("project_versions") == summary:
        return
    manifest["project_versions"] = summary
    atomic_write_json(manifest_path, manifest)


def refresh_project_versions(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"VEA 프로젝트 폴더를 찾을 수 없습니다: {root}")
    metadata = _load_json(root / "project.json") or {}
    previous = _read_previous_index(root)
    previous_by_path = {
        str(item.get("file_path", "")).casefold(): item
        for item in previous.get("versions", [])
        if isinstance(item, dict) and item.get("file_path")
    }
    verified = _verified_evidence(root)
    discovered_at = previous.get("generated_at") or now_kst().isoformat(timespec="seconds")

    files: list[Path] = []
    for folder_name in ("04_ROUGHCUT", "08_PREMIERE"):
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or path.name.startswith("._"):
                continue
            if path.suffix.casefold() not in VERSIONED_EXTENSIONS:
                continue
            files.append(path)

    versions: list[dict[str, Any]] = []
    for path in sorted(set(files), key=lambda item: item.as_posix().casefold()):
        relative = _relative_path(root, path)
        old = previous_by_path.get(relative.casefold(), {})
        stat = path.stat()
        actual_file_hash = _sha256(path)
        recorded_file_hash = old.get("file_hash")
        has_recorded_identity = isinstance(recorded_file_hash, str) and bool(recorded_file_hash)
        file_hash = recorded_file_hash if has_recorded_identity else actual_file_hash
        recorded_file_size = old.get("file_size_bytes")
        file_size_bytes = (
            recorded_file_size
            if has_recorded_identity and isinstance(recorded_file_size, int) and not isinstance(recorded_file_size, bool)
            else stat.st_size
        )
        key = relative.casefold()
        evidence = verified.get(key)
        is_auto = _is_autosave(path)
        stage = _stage_for_file(root, path)
        if evidence and evidence["sha256"] == actual_file_hash:
            status = "verified"
            # A hash-matched Premiere verification report is explicit evidence
            # for the current bytes, so it may establish a new indexed identity.
            file_hash = actual_file_hash
            file_size_bytes = stat.st_size
        elif old.get("validation_status") == "verified" and actual_file_hash != file_hash:
            # A prior verification applies only to the bytes that were verified.
            status = "pending"
        else:
            status = old.get("validation_status", "unknown")
        notes = list(old.get("notes", [])) if isinstance(old.get("notes"), list) else []
        if is_auto and "Premiere 자동 저장본" not in notes:
            notes.append("Premiere 자동 저장본")
        if evidence:
            note = f"Premiere 확인 리포트: {evidence['report_path']}"
            if note not in notes:
                notes.append(note)
        if not old and "최초 발견 시각은 원래 Premiere 프로젝트 생성 시각을 뜻하지 않습니다" not in notes:
            notes.append("최초 발견 시각은 원래 Premiere 프로젝트 생성 시각을 뜻하지 않습니다")
        versions.append(
            {
                "filename": path.name,
                "stage": stage,
                "created_at": old.get("created_at") or _filesystem_created_at(stat),
                "original_created_at": old.get("original_created_at"),
                "generated_at": old.get("generated_at") or _filename_generated_at(path),
                "filesystem_created_at": _filesystem_created_at(stat),
                "last_modified_at": _iso_kst(stat.st_mtime),
                "first_discovered_at": old.get("first_discovered_at") or discovered_at,
                "source_version": old.get("source_version"),
                "validation_status": status,
                "file_path": relative,
                "file_hash": file_hash,
                "file_size_bytes": file_size_bytes,
                "timestamp_basis": old.get("timestamp_basis") or (
                    "version_filename_kst"
                    if _filename_generated_at(path)
                    else "filesystem_creation_time"
                    if _filesystem_created_at(stat)
                    else "unknown"
                ),
                "notes": notes,
            }
        )

    project_files = [item for item in versions if item["file_path"].casefold().endswith(".prproj")]
    working_candidates = [
        item for item in project_files
        if not _is_autosave(Path(item["file_path"])) and not _is_backup(Path(item["file_path"]))
    ]
    latest_working = max(working_candidates, key=lambda item: item.get("last_modified_at") or "", default=None)
    autosaves = [item for item in project_files if _is_autosave(Path(item["file_path"]))]
    latest_autosave = max(autosaves, key=lambda item: item.get("last_modified_at") or "", default=None)
    verified_versions = [item for item in project_files if item["validation_status"] == "verified"]
    latest_verified = max(verified_versions, key=lambda item: item.get("last_modified_at") or "", default=None)
    latest_export = _latest_export(root)
    previous_export = previous.get("latest_export_metadata") or {}
    if latest_export is None and previous_export.get("file_path"):
        previous_path = (root / str(previous_export["file_path"])).resolve()
        if previous_path.is_relative_to(root) and previous_path.is_file():
            latest_export = previous_export

    index = {
        "schema_version": 1,
        "project_id": metadata.get("project_id"),
        "project_name": metadata.get("title") or root.name,
        "project_dir": str(root),
        "source_project": previous.get("source_project") or (latest_verified["file_path"] if latest_verified else None),
        "created_at": metadata.get("created_at"),
        "generated_at": now_kst().isoformat(timespec="seconds"),
        "versions": versions,
        "current_working_version": previous.get("current_working_version"),
        "latest_working_version": latest_working["file_path"] if latest_working else None,
        "latest_working_selection_basis": "가장 최근 수정된 일반 .prproj 파일; 현재 사용자가 편집 중인 파일이라는 뜻은 아닙니다",
        "latest_autosave_version": latest_autosave["file_path"] if latest_autosave else None,
        "latest_verified_version": latest_verified["file_path"] if latest_verified else None,
        "latest_export_version": latest_export.get("file_path") if latest_export else None,
        "latest_export_metadata": latest_export,
        "status": previous.get("status") or "in_progress",
    }
    atomic_write_json(root / VERSION_INDEX_NAME, index)
    _sync_manifest_version_summary(root, index)
    return index


def register_project_version(
    project_dir: str | Path,
    file_path: str | Path,
    *,
    stage: str,
    source_version: str | None = None,
    validation_status: str = "pending",
    notes: str | None = None,
    set_current: bool = False,
) -> dict[str, Any]:
    if validation_status not in {"pending", "failed", "unknown"}:
        raise ValueError("새 버전은 Premiere 검수 리포트와 해시 대조 전까지 pending/failed/unknown 상태만 지정할 수 있습니다.")
    root = Path(project_dir).expanduser().resolve()
    target = Path(file_path).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("프로젝트 버전 파일은 프로젝트 폴더 안에 있어야 합니다.") from exc
    if target.suffix.casefold() not in VERSIONED_EXTENSIONS or not target.is_file():
        raise FileNotFoundError(f"프로젝트 버전 파일이 없거나 확장자를 지원하지 않습니다: {target}")
    normalized_stage = stage.upper()
    if normalized_stage not in PROJECT_STAGES:
        raise ValueError(f"지원하지 않는 프로젝트 단계입니다: {stage}")
    index = refresh_project_versions(root)
    relative = _relative_path(root, target)
    stat = target.stat()
    now = now_kst().isoformat(timespec="seconds")
    generated_at = _filename_generated_at(target)
    record = {
        "filename": target.name,
        "stage": normalized_stage,
        "created_at": _filesystem_created_at(stat),
        "original_created_at": None,
        "generated_at": generated_at or now,
        "filesystem_created_at": _filesystem_created_at(stat),
        "last_modified_at": _iso_kst(stat.st_mtime),
        "first_discovered_at": now,
        "source_version": source_version,
        "validation_status": validation_status,
        "file_path": relative,
        "file_hash": _sha256(target),
        "file_size_bytes": stat.st_size,
        "timestamp_basis": "version_filename_kst" if generated_at else "filesystem_creation_time",
        "notes": [notes] if notes else [],
    }
    records = [item for item in index["versions"] if item.get("file_path", "").casefold() != relative.casefold()]
    records.append(record)
    index["versions"] = records
    index["generated_at"] = now
    if set_current:
        index["current_working_version"] = relative
    atomic_write_json(root / VERSION_INDEX_NAME, index)
    return record


def create_version_snapshot(
    source_file: str | Path,
    project_dir: str | Path,
    *,
    stage: str,
    source_version: str | None = None,
) -> Path:
    """Create a timestamped sibling copy without replacing the canonical project file."""
    root = Path(project_dir).expanduser().resolve()
    source = Path(source_file).expanduser().resolve()
    try:
        source_relative = _relative_path(root, source)
    except ValueError as exc:
        raise ValueError("버전 스냅샷 원본은 VEA 프로젝트 폴더 안에 있어야 합니다.") from exc
    if not source.is_file() or source.suffix.casefold() not in VERSIONED_EXTENSIONS:
        raise FileNotFoundError(f"버전 스냅샷 원본 .prproj/.xml 파일을 찾을 수 없습니다: {source}")
    normalized_stage = stage.upper()
    if normalized_stage not in PROJECT_STAGES:
        raise ValueError(f"지원하지 않는 프로젝트 단계입니다: {stage}")

    source_hash = _sha256(source)
    project_name = (_load_json(root / "project.json") or {}).get("title") or root.name
    prefix = f"{safe_filename_component(str(project_name))}_{normalized_stage}_"
    for candidate in source.parent.glob(f"{prefix}*{source.suffix}"):
        if candidate.is_file() and _filename_generated_at(candidate) and _sha256(candidate) == source_hash:
            return candidate

    target = version_path(source.parent, str(project_name), normalized_stage, source.suffix)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    register_project_version(
        root,
        target,
        stage=normalized_stage,
        source_version=source_version or source_relative,
        validation_status="unknown",
        notes="VEA가 생성한 timestamped snapshot; Premiere 호환성은 별도 검증 필요",
    )
    return target


def verify_project_versions(project_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(project_dir).expanduser().resolve()
    index_path = root / VERSION_INDEX_NAME
    index = _load_json(index_path)
    if not index or index.get("schema_version") != 1:
        raise FileNotFoundError(f"프로젝트 버전 인덱스를 찾을 수 없거나 지원되지 않습니다: {index_path}")
    results: list[dict[str, Any]] = []
    for item in index.get("versions", []):
        path = (root / item["file_path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            results.append({"file_path": item.get("file_path"), "status": "invalid_path"})
            continue
        if not path.is_file():
            results.append({"file_path": item.get("file_path"), "status": "missing"})
            continue
        actual = _sha256(path)
        expected = item.get("file_hash")
        actual_size = path.stat().st_size
        expected_size = item.get("file_size_bytes")
        size_matches = expected_size is None or actual_size == expected_size
        results.append(
            {
                "file_path": item.get("file_path"),
                "status": "integrity_ok" if actual == expected and size_matches else "hash_mismatch",
                "validation_status": item.get("validation_status", "unknown"),
                "file_hash": actual,
                "file_size_bytes": actual_size,
                "expected_file_size_bytes": expected_size,
            }
        )
    return results


def open_project_version(path: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.suffix.casefold() != ".prproj":
        raise FileNotFoundError(f"Premiere 프로젝트 파일이 없습니다: {target}")
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    elif os.name == "posix" and __import__("sys").platform == "darwin":
        import subprocess

        subprocess.Popen(["open", str(target)])
    else:
        import subprocess

        subprocess.Popen(["xdg-open", str(target)])
