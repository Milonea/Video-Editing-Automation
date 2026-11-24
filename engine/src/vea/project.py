from __future__ import annotations

import json
import os
import platform
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checkpoint import atomic_write_json
from .paths import normalize_path, same_path

PROJECT_FOLDERS = (
    "01_SOURCE",
    "02_INSTRUCTIONS",
    "03_ANALYSIS",
    "04_ROUGHCUT",
    "05_AUDIO",
    "06_HANDOFF",
    "07_TRANSCRIPTS",
    "08_PREMIERE",
    "09_EXPORT",
    "10_REPORTS",
)


def safe_project_name(value: str) -> str:
    cleaned = re.sub(r"[^\w가-힣 .()-]+", "_", value, flags=re.UNICODE).strip(" ._")
    return cleaned[:100] or "VEA_Project"


def _ensure_outside_code_repository(project_root: Path) -> None:
    code_root = Path(__file__).resolve().parents[2]
    try:
        project_root.resolve().relative_to(code_root.resolve())
    except ValueError:
        return
    raise ValueError(
        "영상 프로젝트 데이터는 VEA 코드 저장소 안에 만들 수 없습니다. "
        "외장 영상 워크스페이스 또는 별도의 프로젝트 폴더를 지정하세요."
    )


def _relative_to(root: Path | None, path: Path) -> str | None:
    if root is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def initialize_project(
    project_dir: str | Path,
    title: str,
    source_file: str | Path | None = None,
    *,
    workspace_id: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(normalize_path(project_dir))
    _ensure_outside_code_repository(root)
    root.mkdir(parents=True, exist_ok=True)
    for folder in PROJECT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    metadata_path = root / "project.json"
    resolved_workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root else None
    project_relative_path = _relative_to(resolved_workspace_root, root)
    source_reference: dict[str, Any] | None = None
    if source_file:
        normalized_source = Path(normalize_path(source_file))
        workspace_relative_source = _relative_to(resolved_workspace_root, normalized_source)
        if workspace_relative_source is not None:
            source_reference = {"kind": "workspace_relative", "path": workspace_relative_source}
        else:
            source_reference = {
                "kind": "host_absolute",
                "host_os": platform.system().casefold(),
                "path": str(normalized_source),
            }
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata.setdefault("title", title)
            metadata.setdefault("project_id", uuid.uuid4().hex[:12])
            metadata.setdefault("project_structure_version", 1)
            metadata.setdefault("latest_transcript", None)
            metadata.setdefault("latest_premiere_project", None)
            metadata.setdefault("progress_status", "in_progress")
            metadata.setdefault("last_run_environment", None)
            metadata.setdefault("last_run_at", None)
            metadata.setdefault("next_step", None)
            if source_file:
                source_path = normalize_path(source_file)
                existing_source = metadata.get("source_file")
                if existing_source and not same_path(existing_source, source_path):
                    raise ValueError(
                        f"프로젝트 폴더가 다른 원본에 연결되어 있습니다: {existing_source}. "
                        "기존 프로젝트를 덮어쓰지 않도록 새 폴더를 지정하세요."
                    )
                metadata["source_file"] = source_path
                metadata["source_reference"] = source_reference
            if workspace_id:
                workspace_record: dict[str, Any] = {"workspace_id": workspace_id}
                if project_relative_path is not None:
                    workspace_record["project_relative_path"] = project_relative_path
                metadata["video_workspace"] = workspace_record
            atomic_write_json(metadata_path, metadata)
        except (OSError, json.JSONDecodeError):
            raise ValueError(f"project.json이 손상되어 자동 덮어쓰지 않았습니다: {metadata_path}")
    else:
        metadata = {
            "schema_version": 1,
            "project_structure_version": 1,
            "project_id": uuid.uuid4().hex[:12],
            "title": title,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_file": normalize_path(source_file) if source_file else None,
            "source_reference": source_reference,
            "video_workspace": (
                {
                    "workspace_id": workspace_id,
                    **({"project_relative_path": project_relative_path} if project_relative_path is not None else {}),
                }
                if workspace_id
                else None
            ),
            "latest_transcript": None,
            "latest_premiere_project": None,
            "progress_status": "initialized",
            "last_run_environment": None,
            "last_run_at": None,
            "next_step": "vea inspect and prepare",
        }
        atomic_write_json(metadata_path, metadata)
    return metadata


def find_existing_projects(source_file: str | Path, search_root: str | Path) -> list[Path]:
    source = normalize_path(source_file)
    root = Path(search_root).expanduser().resolve()
    if not root.is_dir():
        return []
    matches: list[Path] = []
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in ignored and not name.startswith(".")]
        if "project.json" not in files:
            continue
        metadata_path = Path(directory) / "project.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            existing = metadata.get("source_file")
            if existing and same_path(existing, source):
                matches.append(Path(directory).resolve())
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return sorted(set(matches))
