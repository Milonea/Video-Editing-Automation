import json
from pathlib import Path

import pytest

from vea.project import initialize_project


def test_new_project_records_workspace_relative_paths_and_handoff_fields(tmp_path: Path):
    workspace = tmp_path / "workspace"
    source = workspace / "Incoming" / "synthetic-source.mkv"
    source.parent.mkdir(parents=True)
    source.write_text("synthetic metadata fixture", encoding="utf-8")
    project = workspace / "VideoProjects" / "sample"

    metadata = initialize_project(project, "sample", source, workspace_id="work-ssd", workspace_root=workspace)

    assert metadata["project_structure_version"] == 1
    assert metadata["video_workspace"] == {
        "workspace_id": "work-ssd",
        "project_relative_path": "VideoProjects/sample",
    }
    assert metadata["source_reference"] == {
        "kind": "workspace_relative",
        "path": "Incoming/synthetic-source.mkv",
    }
    assert metadata["latest_transcript"] is None
    assert metadata["latest_premiere_project"] is None
    assert json.loads((project / "project.json").read_text(encoding="utf-8")) == metadata


def test_project_creation_inside_source_repository_is_rejected_before_writes():
    repository_root = Path(__file__).resolve().parents[1]
    forbidden_project = repository_root / "VideoProjects" / "should-not-exist"
    with pytest.raises(ValueError, match="코드 저장소 안"):
        initialize_project(forbidden_project, "blocked")
    assert not forbidden_project.exists()
