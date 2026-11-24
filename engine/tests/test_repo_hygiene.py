from vea.repo_hygiene import MAX_TRACKED_FILE_BYTES, audit_repository_entries


def test_repository_hygiene_allows_source_and_synthetic_fixtures():
    assert audit_repository_entries(
        [
            ("src/vea/workspace.py", 1200),
            ("tests/fixtures/request.txt", 50),
            ("config/windows.toml", 80),
        ]
    ) == []


def test_repository_hygiene_rejects_video_data_and_generated_projects():
    failures = audit_repository_entries(
        [
            ("VideoProjects/project/source.mov", 100),
            ("tests/fixtures/client.srt", 100),
            ("nested/VIDEO_PROJECT/project.prproj", 100),
        ]
    )
    assert len(failures) == 5
    assert sum("project data path" in item for item in failures) == 2
    assert sum("media or Premiere output" in item for item in failures) == 3


def test_repository_hygiene_rejects_oversized_non_media_files():
    failures = audit_repository_entries([("docs/large-report.md", MAX_TRACKED_FILE_BYTES + 1)])
    assert len(failures) == 1
    assert "exceeds" in failures[0]
