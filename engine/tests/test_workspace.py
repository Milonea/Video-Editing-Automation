import json
from pathlib import Path

import pytest

from vea.workspace import (
    AmbiguousWorkspaceError,
    WorkspaceError,
    WorkspaceNotFoundError,
    create_workspace_manifest,
    resolve_workspace,
)


def _write_manifest(root: Path, *, workspace_id: str = "work-ssd", projects_path: str = "VideoProjects") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".vea-workspace.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_id": workspace_id,
                "workspace_type": "video_projects",
                "projects_relative_path": projects_path,
            }
        ),
        encoding="utf-8",
    )


def test_explicit_workspace_has_highest_priority_and_does_not_create_paths(tmp_path: Path):
    explicit = tmp_path / "external"
    explicit.mkdir()
    (explicit / ".vea-workspace.json").write_text(
        '{"schema_version":1,"workspace_id":"work-ssd","workspace_type":"video_projects","projects_relative_path":"VideoProjects"}',
        encoding="utf-8",
    )
    other = tmp_path / "other"
    _write_manifest(other)

    result = resolve_workspace(
        config={"workspace": {"workspace_id": "work-ssd", "video_workspace_root": str(other)}},
        explicit_root=explicit,
        search_roots=[explicit, other],
        code_root=tmp_path / "code",
    )

    assert result.workspace_root == explicit.resolve()
    assert result.source == "explicit"
    assert not result.projects_root.exists()


def test_local_config_root_precedes_automatic_manifest_discovery(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    discovered = tmp_path / "mounted"
    _write_manifest(discovered)

    result = resolve_workspace(
        config={"workspace": {"workspace_id": "work-ssd", "video_workspace_root": str(local)}},
        search_roots=[discovered],
        code_root=tmp_path / "code",
    )

    assert result.workspace_root == local.resolve()
    assert result.source == "local_config"
    assert result.manifest_found is False


def test_manifest_discovery_rejects_multiple_matching_volumes(tmp_path: Path):
    first = tmp_path / "disk-a"
    second = tmp_path / "disk-b"
    _write_manifest(first)
    _write_manifest(second)

    with pytest.raises(AmbiguousWorkspaceError, match="여러 개"):
        resolve_workspace(search_roots=[first, second], code_root=tmp_path / "code")


def test_missing_workspace_never_falls_back_to_current_directory(tmp_path: Path):
    with pytest.raises(WorkspaceNotFoundError, match="대체 프로젝트를 만들지 않았습니다"):
        resolve_workspace(search_roots=[], code_root=tmp_path / "code")


def test_manifest_path_traversal_and_code_repository_paths_are_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    _write_manifest(workspace, projects_path="../projects")
    with pytest.raises(WorkspaceError, match="상대 경로"):
        resolve_workspace(search_roots=[workspace], code_root=tmp_path / "code")

    code_root = tmp_path / "VEA"
    code_root.mkdir()
    with pytest.raises(WorkspaceError, match="코드 저장소 안"):
        resolve_workspace(explicit_root=code_root, code_root=code_root)


def test_workspace_manifest_create_is_non_overwriting_and_portable(tmp_path: Path):
    workspace = tmp_path / "disk"
    workspace.mkdir()
    path = create_workspace_manifest(workspace, workspace_id="work-ssd", projects_relative_path="VideoProjects")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "workspace_id": "work-ssd",
        "workspace_type": "video_projects",
        "projects_relative_path": "VideoProjects",
    }
    with pytest.raises(WorkspaceError, match="덮어쓰지 않았습니다"):
        create_workspace_manifest(workspace, workspace_id="work-ssd")


def test_workspace_manifest_dry_run_cli_does_not_write(tmp_path: Path, capsys):
    from vea.cli import main

    workspace = tmp_path / "disk"
    workspace.mkdir()
    assert main(["workspace", "init", str(workspace)]) == 0
    assert not (workspace / ".vea-workspace.json").exists()
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
