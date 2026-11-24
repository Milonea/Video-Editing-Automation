"""Read-only discovery and explicit initialization for shared video workspaces."""

from __future__ import annotations

import ctypes
import json
import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


WORKSPACE_MANIFEST_NAME = ".vea-workspace.json"
WORKSPACE_SCHEMA_VERSION = 1


class WorkspaceError(RuntimeError):
    """Base class for workspace resolution errors."""


class WorkspaceNotFoundError(WorkspaceError):
    """No mounted workspace matching the requested identity was found."""


class AmbiguousWorkspaceError(WorkspaceError):
    """More than one mounted workspace matches the requested identity."""


@dataclass(frozen=True)
class WorkspaceResolution:
    workspace_root: Path
    projects_root: Path
    workspace_id: str
    source: str
    manifest_path: Path | None
    manifest_found: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "resolved",
            "workspace_id": self.workspace_id,
            "workspace_root": str(self.workspace_root),
            "projects_root": str(self.projects_root),
            "projects_root_exists": self.projects_root.is_dir(),
            "source": self.source,
            "manifest_found": self.manifest_found,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
        }


def _safe_relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceError("manifest의 projects_relative_path가 비어 있습니다.")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"..", ""} for part in candidate.parts):
        raise WorkspaceError("manifest의 프로젝트 경로는 안전한 상대 경로여야 합니다.")
    return candidate


def _manifest(root: Path) -> tuple[dict[str, Any], Path] | None:
    path = root / WORKSPACE_MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"워크스페이스 manifest를 읽지 못했습니다: {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise WorkspaceError(f"지원하지 않는 워크스페이스 manifest 형식입니다: {path}")
    if value.get("workspace_type") != "video_projects":
        raise WorkspaceError(f"영상 프로젝트 저장소가 아닌 manifest입니다: {path}")
    if not isinstance(value.get("workspace_id"), str) or not value["workspace_id"].strip():
        raise WorkspaceError(f"manifest의 workspace_id가 올바르지 않습니다: {path}")
    _safe_relative_path(value.get("projects_relative_path"))
    return value, path


def _default_volume_roots(system: str | None = None) -> list[Path]:
    name = (system or os.name).casefold()
    if name in {"nt", "windows"}:
        roots: list[Path] = []
        if os.name == "nt":
            try:
                mask = ctypes.windll.kernel32.GetLogicalDrives()
            except (AttributeError, OSError):
                mask = 0
            for index, letter in enumerate(string.ascii_uppercase):
                if mask & (1 << index):
                    roots.append(Path(f"{letter}:\\"))
        else:
            roots = [Path(f"{letter}:\\") for letter in string.ascii_uppercase if Path(f"{letter}:\\").is_dir()]
        return roots
    if name in {"darwin", "macos"}:
        volume_root = Path("/Volumes")
        if not volume_root.is_dir():
            return []
        return sorted((path for path in volume_root.iterdir() if path.is_dir()), key=lambda item: str(item).casefold())

    roots = []
    for parent in (Path("/media") / os.environ.get("USER", ""), Path("/run/media") / os.environ.get("USER", ""), Path("/mnt")):
        if parent.is_dir():
            roots.extend(path for path in parent.iterdir() if path.is_dir())
    return sorted(set(roots), key=lambda item: str(item).casefold())


def _outside_code_root(candidate: Path, code_root: str | Path | None) -> None:
    if code_root is None:
        return
    code = Path(code_root).expanduser().resolve()
    try:
        candidate.relative_to(code)
    except ValueError:
        return
    raise WorkspaceError(f"영상 워크스페이스가 VEA 코드 저장소 안에 있습니다: {candidate}")


def _build_resolution(
    root: Path,
    *,
    source: str,
    expected_id: str,
    configured_projects_path: str,
    require_manifest: bool,
    code_root: str | Path | None,
) -> WorkspaceResolution | None:
    root = root.expanduser().resolve()
    if not root.is_dir():
        return None
    _outside_code_root(root, code_root)
    found = _manifest(root)
    if found is None and require_manifest:
        return None
    manifest_value: dict[str, Any] | None = None
    manifest_path: Path | None = None
    if found is not None:
        manifest_value, manifest_path = found
        if manifest_value["workspace_id"] != expected_id:
            return None
    relative = (
        _safe_relative_path(manifest_value["projects_relative_path"])
        if manifest_value is not None
        else _safe_relative_path(configured_projects_path)
    )
    projects_root = (root / relative).resolve()
    try:
        projects_root.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("프로젝트 경로가 워크스페이스 루트 밖을 가리킵니다.") from exc
    _outside_code_root(projects_root, code_root)
    return WorkspaceResolution(
        workspace_root=root,
        projects_root=projects_root,
        workspace_id=expected_id,
        source=source,
        manifest_path=manifest_path,
        manifest_found=manifest_value is not None,
    )


def resolve_workspace(
    *,
    config: Mapping[str, Any] | None = None,
    explicit_root: str | Path | None = None,
    search_roots: Iterable[str | Path] | None = None,
    code_root: str | Path | None = None,
    system: str | None = None,
) -> WorkspaceResolution:
    """Resolve an explicit/local/manifest workspace without creating directories."""
    workspace_config = (config or {}).get("workspace", {})
    if not isinstance(workspace_config, Mapping):
        raise WorkspaceError("workspace 설정은 TOML 테이블이어야 합니다.")
    expected_id = str(workspace_config.get("workspace_id", "work-ssd")).strip()
    if not expected_id:
        raise WorkspaceError("workspace_id를 설정해야 합니다.")
    projects_relative = str(workspace_config.get("projects_relative_path", "VideoProjects"))

    if explicit_root is not None:
        resolution = _build_resolution(
            Path(explicit_root),
            source="explicit",
            expected_id=expected_id,
            configured_projects_path=projects_relative,
            require_manifest=False,
            code_root=code_root,
        )
        if resolution is None:
            raise WorkspaceNotFoundError(f"지정한 영상 워크스페이스가 없습니다: {explicit_root}")
        return resolution

    local_root = workspace_config.get("video_workspace_root")
    if isinstance(local_root, str) and local_root.strip():
        resolution = _build_resolution(
            Path(local_root),
            source="local_config",
            expected_id=expected_id,
            configured_projects_path=projects_relative,
            require_manifest=False,
            code_root=code_root,
        )
        if resolution is not None:
            return resolution

    candidates = [Path(item).expanduser() for item in search_roots] if search_roots is not None else _default_volume_roots(system)
    matches: dict[str, WorkspaceResolution] = {}
    for candidate in candidates:
        resolution = _build_resolution(
            candidate,
            source="workspace_manifest",
            expected_id=expected_id,
            configured_projects_path=projects_relative,
            require_manifest=True,
            code_root=code_root,
        )
        if resolution is not None:
            matches[str(resolution.workspace_root).casefold()] = resolution
    if len(matches) > 1:
        paths = ", ".join(str(item.workspace_root) for item in matches.values())
        raise AmbiguousWorkspaceError(f"workspace_id={expected_id!r}인 저장장치가 여러 개입니다: {paths}")
    if matches:
        return next(iter(matches.values()))
    raise WorkspaceNotFoundError(
        f"영상 워크스페이스 {expected_id!r}를 찾지 못했습니다. 연결 상태를 확인하거나 --video-workspace-root를 지정하세요. "
        "코드 저장소 안에 대체 프로젝트를 만들지 않았습니다."
    )


def create_workspace_manifest(
    root: str | Path,
    *,
    workspace_id: str,
    projects_relative_path: str = "VideoProjects",
) -> Path:
    """Write a portable marker to an existing, explicitly selected workspace root."""
    workspace_root = Path(root).expanduser().resolve()
    if not workspace_root.is_dir():
        raise WorkspaceNotFoundError(f"워크스페이스 루트가 없습니다: {workspace_root}")
    if not workspace_id.strip():
        raise WorkspaceError("workspace_id가 비어 있습니다.")
    relative = _safe_relative_path(projects_relative_path)
    path = workspace_root / WORKSPACE_MANIFEST_NAME
    payload = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "workspace_id": workspace_id.strip(),
        "workspace_type": "video_projects",
        "projects_relative_path": relative.as_posix(),
    }
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise WorkspaceError(f"기존 workspace manifest를 덮어쓰지 않았습니다: {path}") from exc
    return path
