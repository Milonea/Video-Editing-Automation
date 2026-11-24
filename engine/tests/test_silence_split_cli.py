from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vea.cli import build_parser
from vea.cli import _attach_silence_review_result
from vea.cli import _update_silence_split_manifest


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "VEA"
    premiere = project / "08_PREMIERE" / "verified.prproj"
    premiere.parent.mkdir(parents=True)
    premiere.write_bytes(b"verified Premiere fixture")
    (project / "project.json").write_text(
        json.dumps({"project_id": "test-1", "title": "Fixture Project"}),
        encoding="utf-8",
    )
    (project / "manifest.json").write_text(
        json.dumps({"timeline_fps": {"numerator": 30, "denominator": 1}}),
        encoding="utf-8",
    )
    (project / "04_ROUGHCUT").mkdir()
    (project / "04_ROUGHCUT" / "edit_map.json").write_text(
        json.dumps({"fps": {"numerator": 30, "denominator": 1}, "duration_frames": 90, "clips": []}),
        encoding="utf-8",
    )
    transcript = project / "07_TRANSCRIPTS" / "transcript.srt"
    transcript.parent.mkdir()
    transcript.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n첫 문장\n\n"
        "2\n00:00:02,000 --> 00:00:02,500\n다음 문장\n",
        encoding="utf-8",
    )
    report_dir = project / "10_REPORTS"
    report_dir.mkdir()
    report = {
        "status": "verified",
        "project_path": "08_PREMIERE/verified.prproj",
        "sequence": "Verified Sequence",
        "sequence_duration": "00:00:03:00",
        "cue_count": 2,
        "caption_track": {"name": "C1"},
        "save_evidence": {
            "sha256": hashlib.sha256(premiere.read_bytes()).hexdigest(),
            "size_bytes": premiere.stat().st_size,
        },
    }
    (report_dir / "premiere_subtitle_verification.json").write_text(json.dumps(report), encoding="utf-8")
    return project, premiere, transcript


def _run(project: Path, *extra: str) -> int:
    args = build_parser().parse_args(["silence-split", str(project), *extra])
    return args.handler(args)


def test_silence_split_uses_hash_matched_verification_and_existing_srt(tmp_path, capsys):
    project, premiere, transcript = _project(tmp_path)

    result = _run(project)

    plan = json.loads((project / "10_REPORTS" / "silence_split_plan.json").read_text(encoding="utf-8"))
    candidates = json.loads((project / "10_REPORTS" / "silence_candidates.json").read_text(encoding="utf-8"))
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    assert result == 0
    assert plan["premiere_project"]["path"] == str(premiere.resolve())
    assert plan["premiere_project"]["verified_reference"] is True
    assert plan["premiere_project"]["sequence_name"] == "Verified Sequence"
    assert plan["premiere_project"]["caption_track_name"] == "C1"
    assert plan["input"]["path"] == str(transcript.resolve())
    assert plan["input"]["end_time_kind"] == "subtitle_end"
    assert plan["input"]["tail_added_seconds"] == 0.0
    assert candidates["candidate_count"] == 1
    assert candidates["candidates"][0]["split_applied"] is False
    assert plan["actions"]["auto_delete"] is False
    assert manifest["smart_silence_split"]["candidate_count"] == 1
    assert manifest["smart_silence_split"]["split_applied"] is False
    manifest_assets = {item["path"]: item for item in manifest["assets"]}
    assert manifest_assets["10_REPORTS/silence_split_plan.json"]["generated_at"] == plan["generated_at"]
    assert "후보 1개" in capsys.readouterr().out


def test_explicit_unverified_project_does_not_inherit_sequence_or_caption_evidence(tmp_path):
    project, _, _ = _project(tmp_path)
    other = project / "08_PREMIERE" / "newer_working.prproj"
    other.write_bytes(b"newer but unverified")

    _run(
        project,
        "--premiere-project",
        "08_PREMIERE/newer_working.prproj",
        "--sequence-name",
        "Manual Sequence",
        "--caption-track",
        "Captions",
        "--sequence-duration",
        "3",
    )

    plan = json.loads((project / "10_REPORTS" / "silence_split_plan.json").read_text(encoding="utf-8"))
    assert plan["premiere_project"]["verified_reference"] is False
    assert plan["premiere_project"]["verified_caption_count"] is None
    assert plan["premiere_project"]["sequence_name"] == "Manual Sequence"
    assert plan["premiere_project"]["caption_track_name"] == "Captions"


def test_safety_settings_cannot_disable_preservation_or_validation(tmp_path):
    project, _, _ = _project(tmp_path)
    config = tmp_path / "unsafe.toml"
    config.write_text("[smart_silence_split]\npreserve_subtitles = false\n", encoding="utf-8")

    with pytest.raises(ValueError, match="필수 보존·검증 설정"):
        _run(project, "--config", str(config))


def test_project_register_result_requires_matching_saved_copy_and_keeps_split_unapplied(tmp_path):
    project, premiere, _ = _project(tmp_path)
    review = project / "08_PREMIERE" / "Fixture_Project_REVIEW_20261119_191213_KST.prproj"
    review.write_bytes(b"review copy")
    plan = {
        "project_id": "test-1",
        "premiere_project": {"path": str(premiere.resolve()), "relative_path": "08_PREMIERE/verified.prproj"},
        "analysis": {"candidates": [{"candidate_id": "SILENCE_001"}]},
        "actions": {"auto_delete": False},
    }
    plan_path = project / "10_REPORTS" / "silence_split_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    result = {
        "schema_version": 1,
        "status": "saved_pending_reopen_review",
        "project_id": "test-1",
        "source_project_path": str(premiere.resolve()),
        "review_project_path": str(review.resolve()),
        "candidate_count": 1,
        "marker_count": 1,
        "actual_mode": "review_markers_only",
        "split_api_available": False,
        "split_all_tracks_api_available": False,
        "track_edit_api_availability": {
            "cloneTrackItem": True,
            "videoTrackItem": {
                "createSetStartAction": True,
                "createSetEndAction": True,
                "createSetInPointAction": True,
                "createSetOutPointAction": True,
            },
            "audioTrackItem": {
                "createSetStartAction": True,
                "createSetEndAction": True,
                "createSetInPointAction": True,
                "createSetOutPointAction": True,
            },
        },
        "split_status": "not_supported",
        "split_applied": False,
        "cut_action_count": 0,
        "candidate_split_count": 0,
        "target_tracks": [],
        "auto_delete": False,
        "project_openable_check": True,
    }
    (project / "10_REPORTS" / "silence_split_premiere_result_20261119_191213_KST.json").write_text(
        json.dumps(result),
        encoding="utf-8",
    )

    attached = _attach_silence_review_result(project, review)

    updated = json.loads(plan_path.read_text(encoding="utf-8"))
    assert attached["registered"] is True
    assert attached["validation_status"] == "pending"
    assert updated["actions"]["review_markers_added"] == 1
    assert updated["actions"]["split_applied"] is False
    assert updated["actions"]["split_status"] == "not_supported"
    assert updated["actions"]["candidate_split_count"] == 0
    assert updated["premiere_result"]["auto_delete"] is False
    assert updated["premiere_result"]["split_api_available"] is False
    assert updated["premiere_result"]["split_all_tracks_api_available"] is False
    assert updated["premiere_result"]["track_edit_api_availability"]["cloneTrackItem"] is True
    assert updated["premiere_result"]["track_edit_api_availability"]["videoTrackItem"]["createSetEndAction"] is True

    candidate_json = project / "10_REPORTS" / "silence_candidates.json"
    candidate_csv = project / "10_REPORTS" / "silence_candidates.csv"
    validation_path = project / "10_REPORTS" / "silence_split_validation.md"
    candidate_json.write_text("{}", encoding="utf-8")
    candidate_csv.write_text("candidate_id\nSILENCE_001\n", encoding="utf-8")
    validation_path.write_text("# Validation\n", encoding="utf-8")
    version_index = {
        "generated_at": "2026-11-20T00:00:00+09:00",
        "latest_working_version": "08_PREMIERE/Fixture_Project_REVIEW_20261119_191213_KST.prproj",
        "latest_verified_version": "08_PREMIERE/verified.prproj",
        "latest_export_version": None,
        "versions": [],
    }
    (project / "project_versions.json").write_text(json.dumps(version_index), encoding="utf-8")

    _update_silence_split_manifest(
        project,
        plan_path=plan_path,
        candidate_json=candidate_json,
        candidate_csv=candidate_csv,
        validation_path=validation_path,
        version_index=version_index,
    )

    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["smart_silence_split"]["split_api_available"] is False
    assert manifest["smart_silence_split"]["split_all_tracks_api_available"] is False
    assert manifest["smart_silence_split"]["track_edit_api_availability"]["audioTrackItem"]["createSetOutPointAction"] is True
