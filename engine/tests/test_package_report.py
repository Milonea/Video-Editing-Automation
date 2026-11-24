from __future__ import annotations

import json

from vea.package import refresh_codex_handoff_report


def test_codex_handoff_includes_silence_candidates_and_version_selection(tmp_path):
    project = tmp_path / "VEA"
    reports = project / "10_REPORTS"
    reports.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "p-report", "title": "Fixture"}),
        encoding="utf-8",
    )
    (project / "manifest.json").write_text(
        json.dumps({"project_id": "p-report", "clip_count": 4, "timeline_fps": {"numerator": 30, "denominator": 1}, "assets": []}),
        encoding="utf-8",
    )
    (project / "checkpoint.json").write_text(json.dumps({"stages": {"silence_split_analysis": {"status": "completed"}}}), encoding="utf-8")
    (reports / "validation.json").write_text(json.dumps({"issues": []}), encoding="utf-8")
    (project / "project_versions.json").write_text(
        json.dumps({
            "versions": [{"file_path": "08_PREMIERE/work.prproj"}],
            "latest_working_version": "08_PREMIERE/work.prproj",
            "latest_verified_version": "08_PREMIERE/verified.prproj",
        }),
        encoding="utf-8",
    )
    (reports / "silence_split_plan.json").write_text(
        json.dumps({
            "project_id": "p-report",
            "analysis": {
                "time_source": "SRT subtitle_end used as-is",
                "candidates": [{"candidate_id": "SILENCE_001"}],
            },
            "actions": {"split_applied": False, "auto_delete": False},
            "premiere_result": {
                "registered": True,
                "registered_project_file": "08_PREMIERE/Fixture_REVIEW.prproj",
                "review_sequence_name": "SILENCE_SPLIT_REVIEW_TEST",
                "report_path": "10_REPORTS/result.json",
                "marker_count": 1,
                "split_method": None,
                "validation_status": "pending",
                "split_applied": False,
                "split_api_available": False,
                "split_all_tracks_api_available": False,
                "track_edit_api_availability": {
                    "cloneTrackItem": True,
                    "videoTrackItem": {
                        "createSetStartAction": True,
                        "createSetEndAction": True,
                        "createSetInPointAction": True,
                        "createSetOutPointAction": True,
                        "createMoveAction": True,
                    },
                    "audioTrackItem": {
                        "createSetStartAction": True,
                        "createSetEndAction": True,
                        "createSetInPointAction": True,
                        "createSetOutPointAction": True,
                        "createMoveAction": True,
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    for name in ("silence_candidates.json", "silence_candidates.csv", "silence_split_validation.md"):
        (reports / name).write_text("fixture", encoding="utf-8")

    report_path = refresh_codex_handoff_report(project)
    report = report_path.read_text(encoding="utf-8")

    assert "1개 자막 공백 후보" in report
    assert "최신 작업 후보=08_PREMIERE/work.prproj" in report
    assert "최신 검증본=08_PREMIERE/verified.prproj" in report
    assert "실제 분할은 적용되지 않았습니다" in report
    assert "클립 분할=미적용" in report
    assert "Razor track=미노출" in report
    assert "clone=있음" in report
    assert "분할 방식=clone_trim" not in report
    assert "video[StartAction=있음,EndAction=있음,InPointAction=있음,OutPointAction=있음,MoveAction=있음]" in report
    assert "10_REPORTS/silence_split_plan.json" in report
    assert "project_versions.json" in report

    plan_path = reports / "silence_split_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["actions"]["split_applied"] = True
    plan["premiere_result"]["split_applied"] = True
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    report = refresh_codex_handoff_report(project).read_text(encoding="utf-8")
    assert "클립 분할=적용" in report
    assert "실제 분할이 적용됐습니다" in report
