import hashlib
import json
import os
from datetime import datetime, timezone

import pytest

from vea.cli import main
from vea.versioning import (
    create_version_snapshot,
    register_project_version,
    refresh_project_versions,
    verify_project_versions,
    version_filename,
)


def test_filename_uses_kst_and_cross_platform_characters(tmp_path):
    moment = datetime(2026, 11, 19, 10, 12, 13, tzinfo=timezone.utc)
    name = version_filename("Sample: Project/Timeline", "SILENCE_SPLIT", ".prproj", at=moment)
    assert name == "Sample_ Project_Timeline_SILENCE_SPLIT_20261119_191213_KST.prproj"

    output_dir = tmp_path / "versions"
    output_dir.mkdir()
    first = version_filename("Project", "REVIEW", "prproj", at=moment, directory=output_dir)
    (output_dir / first).write_bytes(b"one")
    second = version_filename("Project", "REVIEW", "prproj", at=moment, directory=output_dir)
    assert second == "Project_REVIEW_20261119_191213_KST_01.prproj"


def test_version_filename_rejects_unknown_stage_or_extension():
    with pytest.raises(ValueError):
        version_filename("Project", "DRAFT", ".prproj")
    with pytest.raises(ValueError):
        version_filename("Project", "REVIEW", ".project")


def test_index_tracks_existing_files_and_marks_only_hash_matched_validation(tmp_path):
    project = tmp_path / "VEA"
    main = project / "08_PREMIERE" / "Windows_Continuation" / "validated.prproj"
    working = project / "08_PREMIERE" / "Windows_Continuation" / "working.prproj"
    autosave = project / "08_PREMIERE" / "Adobe Premiere Pro Auto-Save" / "working-auto.prproj"
    xml = project / "04_ROUGHCUT" / "roughcut.xml"
    for path in (main, working, autosave, xml):
        path.parent.mkdir(parents=True, exist_ok=True)
    main.write_bytes(b"validated Premiere project")
    working.write_bytes(b"newer unverified project")
    autosave.write_bytes(b"autosave")
    xml.write_text("<xmeml />", encoding="utf-8")
    project.mkdir(exist_ok=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "p-1", "title": "VEA", "created_at": "2026-11-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    report_dir = project / "10_REPORTS"
    report_dir.mkdir()
    report = {
        "status": "verified",
        "project_path": "08_PREMIERE/Windows_Continuation/validated.prproj",
        "save_evidence": {
            "sha256": hashlib.sha256(main.read_bytes()).hexdigest(),
            "size_bytes": main.stat().st_size,
            "last_write_time_utc": "2026-11-18T10:00:00Z",
        },
    }
    (report_dir / "premiere_project_verification.json").write_text(json.dumps(report), encoding="utf-8")
    os.utime(working, (main.stat().st_mtime + 10, main.stat().st_mtime + 10))

    index = refresh_project_versions(project)
    by_path = {item["file_path"]: item for item in index["versions"]}
    assert index["latest_verified_version"] == "08_PREMIERE/Windows_Continuation/validated.prproj"
    assert index["latest_working_version"] == "08_PREMIERE/Windows_Continuation/working.prproj"
    assert index["latest_autosave_version"] == "08_PREMIERE/Adobe Premiere Pro Auto-Save/working-auto.prproj"
    assert by_path["08_PREMIERE/Windows_Continuation/validated.prproj"]["validation_status"] == "verified"
    assert by_path["08_PREMIERE/Windows_Continuation/working.prproj"]["validation_status"] == "unknown"
    assert by_path["04_ROUGHCUT/roughcut.xml"]["stage"] == "ROUGHCUT"
    assert by_path["08_PREMIERE/Windows_Continuation/validated.prproj"]["notes"]
    assert main.name == "validated.prproj"
    assert working.name == "working.prproj"


def test_refresh_syncs_manifest_version_summary_without_dropping_fields(tmp_path):
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "work.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"synthetic project")
    (project / "project.json").write_text(json.dumps({"project_id": "p-manifest", "title": "VEA"}), encoding="utf-8")
    manifest_path = project / "manifest.json"
    manifest_path.write_text(json.dumps({"project_id": "p-manifest", "custom_field": "preserve me"}), encoding="utf-8")

    index = refresh_project_versions(project)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["custom_field"] == "preserve me"
    assert manifest["project_versions"] == {
        "index_path": "project_versions.json",
        "generated_at": index["generated_at"],
        "latest_working_version": "08_PREMIERE/work.prproj",
        "latest_verified_version": None,
        "latest_export_version": None,
        "version_count": 1,
    }


def test_integrity_check_does_not_upgrade_or_rewrite_validation_status(tmp_path):
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "work.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"before")
    (project / "project.json").write_text(json.dumps({"project_id": "p-2", "title": "VEA"}), encoding="utf-8")
    original = refresh_project_versions(project)["versions"][0]
    premiere.write_bytes(b"after")
    refreshed = refresh_project_versions(project)["versions"][0]
    results = verify_project_versions(project)
    assert refreshed["file_hash"] == original["file_hash"]
    assert refreshed["file_size_bytes"] == original["file_size_bytes"]
    assert results[0]["status"] == "hash_mismatch"
    assert results[0]["validation_status"] == "unknown"


def test_integrity_check_compares_recorded_size_as_well_as_hash(tmp_path):
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "work.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"unchanged project")
    (project / "project.json").write_text(json.dumps({"project_id": "p-size", "title": "VEA"}), encoding="utf-8")
    index = refresh_project_versions(project)
    index_path = project / "project_versions.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    data["versions"][0]["file_size_bytes"] += 1
    index_path.write_text(json.dumps(data), encoding="utf-8")

    result = verify_project_versions(project)[0]

    assert result["status"] == "hash_mismatch"
    assert result["file_hash"] == index["versions"][0]["file_hash"]
    assert result["file_size_bytes"] == premiere.stat().st_size
    assert result["expected_file_size_bytes"] == premiere.stat().st_size + 1


def test_refresh_downgrades_verified_version_when_indexed_bytes_change(tmp_path):
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "verified.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"verified bytes")
    (project / "project.json").write_text(json.dumps({"project_id": "p-verified", "title": "VEA"}), encoding="utf-8")
    report_dir = project / "10_REPORTS"
    report_dir.mkdir()
    report = {
        "status": "verified",
        "project_path": "08_PREMIERE/verified.prproj",
        "save_evidence": {
            "sha256": hashlib.sha256(premiere.read_bytes()).hexdigest(),
            "size_bytes": premiere.stat().st_size,
        },
    }
    (report_dir / "premiere_project_verification.json").write_text(json.dumps(report), encoding="utf-8")

    verified = refresh_project_versions(project)["versions"][0]
    premiere.write_bytes(b"changed bytes after verification")
    refreshed_index = refresh_project_versions(project)
    refreshed = refreshed_index["versions"][0]

    assert verified["validation_status"] == "verified"
    assert refreshed["file_hash"] == verified["file_hash"]
    assert refreshed["validation_status"] == "pending"
    assert refreshed_index["latest_verified_version"] is None
    assert verify_project_versions(project)[0]["status"] == "hash_mismatch"


def test_project_latest_reports_hash_mismatch_without_reblessing_file(tmp_path, capsys):
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "working.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"recorded project bytes")
    (project / "project.json").write_text(json.dumps({"project_id": "p-latest", "title": "VEA"}), encoding="utf-8")
    initial = refresh_project_versions(project)["versions"][0]
    premiere.write_bytes(b"changed project bytes")

    result = main(["project", "latest", str(project)])
    output = capsys.readouterr().out
    refreshed = json.loads((project / "project_versions.json").read_text(encoding="utf-8"))["versions"][0]

    assert result == 0
    assert "파일 무결성: hash_mismatch" in output
    assert initial["file_hash"] in output
    assert hashlib.sha256(premiere.read_bytes()).hexdigest() in output
    assert refreshed["file_hash"] == initial["file_hash"]
    assert refreshed["file_size_bytes"] == initial["file_size_bytes"]


def test_legacy_file_keeps_unknown_original_time_and_posix_relative_path(tmp_path):
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "Windows_Continuation" / "legacy.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"legacy project")
    (project / "project.json").write_text(json.dumps({"project_id": "p-legacy", "title": "VEA"}), encoding="utf-8")

    index = refresh_project_versions(project)
    record = next(item for item in index["versions"] if item["file_path"].endswith("legacy.prproj"))

    assert record["file_path"] == "08_PREMIERE/Windows_Continuation/legacy.prproj"
    assert record["original_created_at"] is None
    assert record["generated_at"] is None
    birthtime = getattr(premiere.stat(), "st_birthtime", None)
    if os.name == "nt" or birthtime is not None:
        assert record["filesystem_created_at"]
        assert record["created_at"] == record["filesystem_created_at"]
    else:
        assert record["filesystem_created_at"] is None
        assert record["created_at"] is None
        assert record["timestamp_basis"] == "unknown"
    assert premiere.name == "legacy.prproj"
    assert premiere.read_bytes() == b"legacy project"


def test_failed_version_is_never_selected_as_latest_verified(tmp_path):
    project = tmp_path / "VEA"
    verified = project / "08_PREMIERE" / "known-good.prproj"
    failed = project / "08_PREMIERE" / "Project_REVIEW_20261119_191213_KST.prproj"
    verified.parent.mkdir(parents=True)
    verified.write_bytes(b"known good")
    failed.write_bytes(b"failed review")
    (project / "project.json").write_text(json.dumps({"project_id": "p-failed", "title": "VEA"}), encoding="utf-8")
    report_dir = project / "10_REPORTS"
    report_dir.mkdir()
    report = {
        "status": "verified",
        "project_path": "08_PREMIERE/known-good.prproj",
        "save_evidence": {
            "sha256": hashlib.sha256(verified.read_bytes()).hexdigest(),
            "size_bytes": verified.stat().st_size,
        },
    }
    (report_dir / "premiere_project_verification.json").write_text(json.dumps(report), encoding="utf-8")
    register_project_version(project, failed, stage="REVIEW", validation_status="failed", set_current=True)

    index = refresh_project_versions(project)
    failed_record = next(item for item in index["versions"] if item["filename"] == failed.name)

    assert failed_record["validation_status"] == "failed"
    assert index["latest_verified_version"] == "08_PREMIERE/known-good.prproj"


def test_register_marks_new_review_copy_pending_and_can_set_current(tmp_path):
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "Project_REVIEW_20261119_191213_KST.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"saved copy")
    (project / "project.json").write_text(json.dumps({"project_id": "p-3", "title": "VEA"}), encoding="utf-8")
    record = register_project_version(
        project,
        premiere,
        stage="REVIEW",
        source_version="08_PREMIERE/source.prproj",
        notes="UXP review clone",
        set_current=True,
    )
    index = json.loads((project / "project_versions.json").read_text(encoding="utf-8"))
    assert record["validation_status"] == "pending"
    assert index["current_working_version"] == "08_PREMIERE/Project_REVIEW_20261119_191213_KST.prproj"
    assert index["latest_verified_version"] is None

    with pytest.raises(ValueError):
        register_project_version(project, premiere, stage="REVIEW", validation_status="verified")


def test_timestamped_xml_snapshot_is_additive_and_idempotent(tmp_path):
    project = tmp_path / "VEA"
    xml = project / "04_ROUGHCUT" / "roughcut.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text("<xmeml><sequence /></xmeml>", encoding="utf-8")
    (project / "project.json").write_text(json.dumps({"project_id": "p-4", "title": "Cut"}), encoding="utf-8")

    snapshot = create_version_snapshot(xml, project, stage="ROUGHCUT")
    original_bytes = xml.read_bytes()
    second = create_version_snapshot(xml, project, stage="ROUGHCUT")

    assert snapshot == second
    assert snapshot.name.startswith("Cut_ROUGHCUT_")
    assert snapshot.suffix == ".xml"
    assert xml.read_bytes() == original_bytes
    index = json.loads((project / "project_versions.json").read_text(encoding="utf-8"))
    record = next(item for item in index["versions"] if item["file_path"] == snapshot.relative_to(project).as_posix())
    assert record["stage"] == "ROUGHCUT"
    assert record["source_version"] == "04_ROUGHCUT/roughcut.xml"
    assert record["validation_status"] == "unknown"
    assert record["generated_at"].endswith("+09:00")
    assert record["timestamp_basis"] == "version_filename_kst"


def test_index_tracks_latest_export_without_hashing_it_as_a_premiere_project(tmp_path):
    project = tmp_path / "VEA"
    export = project / "09_EXPORT" / "Cut_FINAL_20261119_201500_KST.mp4"
    export.parent.mkdir(parents=True)
    export.write_bytes(b"synthetic export")
    (project / "project.json").write_text(json.dumps({"project_id": "p-5", "title": "Cut"}), encoding="utf-8")

    index = refresh_project_versions(project)

    assert index["latest_export_version"] == "09_EXPORT/Cut_FINAL_20261119_201500_KST.mp4"
    assert index["latest_export_metadata"]["generated_at"].endswith("+09:00")
    assert all(not item["file_path"].endswith(".mp4") for item in index["versions"])
