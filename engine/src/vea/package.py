from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checkpoint import atomic_write_json, atomic_write_text, file_fingerprint
from .media import MediaInfo
from .models import FrameRate, TimelineClip
from .paths import normalize_path, same_path
from .project import PROJECT_FOLDERS
from .validation import validate_project, write_validation_report


def write_cuts_csv(path: str | Path, clips: list[TimelineClip], fps: FrameRate) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "ordering",
            "label",
            "source_file",
            "source_in_seconds",
            "source_out_seconds",
            "timeline_start_frame",
            "timeline_end_frame",
            "duration_frames",
            "notes",
        ],
    )
    writer.writeheader()
    for clip in clips:
        writer.writerow(
            {
                "ordering": clip.ordering,
                "label": clip.label,
                "source_file": clip.source_file,
                "source_in_seconds": str(clip.source_in_seconds),
                "source_out_seconds": str(clip.source_out_seconds),
                "timeline_start_frame": clip.timeline_start_frame,
                "timeline_end_frame": clip.timeline_end_frame,
                "duration_frames": clip.duration_frames,
                "notes": clip.notes,
            }
        )
    atomic_write_text(target, buffer.getvalue(), encoding="utf-8-sig")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json_if_present(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _availability_label(value: Any) -> str:
    if value is True:
        return "있음"
    if value is False:
        return "미노출"
    return "확인 안 됨"


def _silence_runtime_api_summary(result: dict[str, Any]) -> str:
    details = []
    split_method = result.get("split_method")
    if isinstance(split_method, str) and split_method:
        details.append(f"분할 방식={split_method}")
    for key, label in (
        ("split_api_available", "Razor track"),
        ("split_all_tracks_api_available", "Razor all"),
    ):
        if isinstance(result.get(key), bool):
            details.append(f"{label}={_availability_label(result[key])}")

    track_apis = result.get("track_edit_api_availability")
    if isinstance(track_apis, dict):
        if isinstance(track_apis.get("cloneTrackItem"), bool):
            details.append(f"clone={_availability_label(track_apis['cloneTrackItem'])}")
        methods = (
            "createSetStartAction",
            "createSetEndAction",
            "createSetInPointAction",
            "createSetOutPointAction",
        )
        for key, label in (("videoTrackItem", "video"), ("audioTrackItem", "audio")):
            sample = track_apis.get(key)
            if isinstance(sample, dict):
                method_detail = ",".join(
                    f"{method.removeprefix('createSet')}={_availability_label(sample.get(method))}"
                    for method in methods
                )
                move_detail = f",MoveAction={_availability_label(sample.get('createMoveAction'))}" if "createMoveAction" in sample else ""
                details.append(f"{label}[{method_detail}{move_detail}]")
            elif key in track_apis and sample is None:
                details.append(f"{label}=표본 없음")

    return f"API 진단: {', '.join(details)}" if details else ""


def _is_os_metadata_file(path: Path) -> bool:
    return path.name.startswith("._") or path.name in {".DS_Store", "Thumbs.db", "desktop.ini"}


def _has_completed_windows_transcription(project_dir: Path) -> bool:
    transcript = _read_json_if_present(project_dir / "07_TRANSCRIPTS" / "transcript.json")
    metadata = transcript.get("metadata")
    if not isinstance(metadata, dict):
        return False
    try:
        duration_seconds = float(metadata.get("duration_seconds") or 0)
        elapsed_seconds = float(metadata.get("elapsed_seconds") or 0)
        chunk_count = int(metadata.get("chunk_count") or 0)
    except (TypeError, ValueError):
        return False
    return (
        metadata.get("hardware_check") == "Windows runtime"
        and metadata.get("device") in {"cuda", "cpu"}
        and bool(metadata.get("model"))
        and duration_seconds > 0
        and elapsed_seconds > 0
        and chunk_count > 0
    )


def _has_verified_premiere_subtitles(project_dir: Path, project_id: str | None) -> bool:
    evidence = _read_json_if_present(project_dir / "10_REPORTS" / "premiere_subtitle_verification.json")
    if evidence.get("status") != "verified" or evidence.get("project_id") != project_id:
        return False
    caption_track = evidence.get("caption_track")
    if not isinstance(caption_track, dict) or caption_track.get("type") != "Subtitle":
        return False
    try:
        cue_count = int(evidence.get("cue_count") or 0)
    except (TypeError, ValueError):
        return False
    if cue_count <= 0:
        return False

    root = project_dir.resolve()

    def resolve_project_path(value: Any) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        path = (root / value.replace("/", os.sep)).resolve()
        return path if path.is_relative_to(root) else None

    save_evidence = evidence.get("save_evidence")
    source_evidence = evidence.get("source_immutability")
    if not isinstance(save_evidence, dict) or not isinstance(source_evidence, dict):
        return False
    if save_evidence.get("saved") is not True or save_evidence.get("title_has_unsaved_marker") is not False:
        return False
    if source_evidence.get("unchanged") is not True:
        return False

    validation_project = resolve_project_path(evidence.get("project_path"))
    original_project = resolve_project_path(source_evidence.get("path"))
    if validation_project is None or original_project is None:
        return False
    if not validation_project.is_file() or not original_project.is_file():
        return False
    if _sha256(validation_project) != save_evidence.get("sha256"):
        return False
    if validation_project.stat().st_size != save_evidence.get("size_bytes"):
        return False
    if _sha256(original_project) != source_evidence.get("sha256"):
        return False
    if original_project.stat().st_size != source_evidence.get("size_bytes"):
        return False

    samples = evidence.get("observed_samples")
    if not isinstance(samples, list):
        return False
    verified_points = {
        sample.get("point")
        for sample in samples
        if isinstance(sample, dict)
        and sample.get("caption_visible") is True
        and sample.get("video_visible") is True
    }
    if not {"start", "middle", "end", "cut_boundary"}.issubset(verified_points):
        return False

    original_project_evidence = evidence.get("mac_original_project")
    return (
        isinstance(original_project_evidence, dict)
        and original_project_evidence.get("opened_or_saved_during_validation") is False
    )


def premiere_verification_status(project_dir: str | Path) -> str:
    """Describe verified subtitle display while keeping human sync review separate."""
    root = Path(project_dir).expanduser().resolve()
    project_meta = _read_json_if_present(root / "project.json")
    project_id = project_meta.get("project_id")
    if _has_verified_premiere_subtitles(root, project_id):
        return "Premiere에서 SRT 가져오기와 시작·중간·끝·컷 경계 캡션 표시 확인; 원음 청취 및 사람 싱크 검수 대기"
    return "미수행"


def refresh_codex_handoff_report(project_dir: str | Path) -> Path:
    """Write a portable project summary and register its hash in the manifest."""
    root = Path(project_dir).expanduser().resolve()
    report_path = root / "10_REPORTS" / "codex_handoff.md"
    manifest_path = root / "manifest.json"
    manifest = _read_json_if_present(manifest_path)
    metadata = _read_json_if_present(root / "project.json")
    checkpoint = _read_json_if_present(root / "checkpoint.json")
    media_info = _read_json_if_present(root / "03_ANALYSIS" / "media_info.json")
    validation = _read_json_if_present(root / "10_REPORTS" / "validation.json")
    issues = validation.get("issues")
    if not isinstance(issues, list):
        issues = manifest.get("validation", [])
    if not isinstance(issues, list):
        issues = []

    source = manifest.get("source", {})
    if not isinstance(source, dict):
        source = {}
    metadata_fingerprint = metadata.get("source_fingerprint", {})
    if not isinstance(metadata_fingerprint, dict):
        metadata_fingerprint = {}
    video = manifest.get("video") or media_info.get("video", {})
    if not isinstance(video, dict):
        video = {}
    fps_data = manifest.get("timeline_fps")
    if isinstance(fps_data, dict):
        fps_text = f"{fps_data.get('numerator', '?')}/{fps_data.get('denominator', '?')}"
    else:
        fps_text = "미설정"
    duration = manifest.get("duration_seconds")
    if not isinstance(duration, (int, float)):
        duration = media_info.get("duration")
    duration_text = f"{float(duration):.1f}초" if isinstance(duration, (int, float)) else "확인 불가"
    width, height = video.get("width"), video.get("height")
    resolution = f"{width}×{height}" if width and height else "확인 불가"
    source_size = source.get("size_bytes") or metadata_fingerprint.get("size_bytes") or media_info.get("size_bytes")
    source_hash = source.get("sha256") or metadata_fingerprint.get("sha256")
    source_path = source.get("path") or media_info.get("path") or metadata.get("source_file") or "확인 불가"
    source_rate = video.get("frame_rate") or video.get("avg_frame_rate")
    source_rate_text = f", 원본 {source_rate}fps" if source_rate else ""

    voice_tracks = _read_json_if_present(root / "05_AUDIO" / "voice_tracks.json")
    selected_streams = voice_tracks.get("selected_global_stream_indexes", [])
    if not selected_streams:
        voice_selection = _read_json_if_present(root / "03_ANALYSIS" / "voice_selection.json")
        selected_streams = voice_selection.get("selected_global_stream_indexes", [])
    if not isinstance(selected_streams, list):
        selected_streams = []
    track_inventory = _read_json_if_present(root / "03_ANALYSIS" / "tracks.json")
    available_audio = track_inventory.get("audio_streams", [])
    if not isinstance(available_audio, list):
        available_audio = []
    instruction_data = _read_json_if_present(root / "03_ANALYSIS" / "instructions.json")
    parse_issues = instruction_data.get("issues", [])
    if not isinstance(parse_issues, list):
        parse_issues = []
    interpretation_status = instruction_data.get("interpretation_status", "unknown")
    parse_validation_status = instruction_data.get("validation_status", "unknown")
    premiere_status = premiere_verification_status(root)
    premiere_verified = premiere_status != "미수행"
    premiere_human_review_pending = premiere_verified and "검수 대기" in premiere_status
    ai_review_path = root / "10_REPORTS" / "transcript_ai_review.md"
    human_review_path = root / "10_REPORTS" / "transcript_human_review.md"
    ai_review_text = ai_review_path.read_text(encoding="utf-8") if ai_review_path.is_file() else ""
    human_review_text = human_review_path.read_text(encoding="utf-8") if human_review_path.is_file() else ""
    ai_review_complete = (
        f"VEA 프로젝트 ID: `{metadata.get('project_id')}`" in ai_review_text
        and "AI 보조 1차 검토 완료" in ai_review_text
    )
    human_audio_review_pending = any(
        marker in human_review_text
        for marker in ("사람 청취/싱크 검수 대기", "사람 청취 검수 대기", "human_audio_review: pending")
    )
    before_review_srt_path = root / "07_TRANSCRIPTS" / "transcript_before_review.srt"
    after_ai_review_srt_path = root / "07_TRANSCRIPTS" / "transcript_after_ai_review.srt"
    reviewed_srt_path = root / "07_TRANSCRIPTS" / "transcript_reviewed.srt"
    before_review_srt_exists = before_review_srt_path.is_file()
    after_ai_review_srt_exists = after_ai_review_srt_path.is_file()
    reviewed_srt_exists = reviewed_srt_path.is_file()
    stage_data = checkpoint.get("stages", {})
    if not isinstance(stage_data, dict):
        stage_data = {}
    silence_plan = _read_json_if_present(root / "10_REPORTS" / "silence_split_plan.json")
    if silence_plan.get("project_id") != metadata.get("project_id"):
        silence_plan = {}
    silence_analysis = silence_plan.get("analysis", {})
    if not isinstance(silence_analysis, dict):
        silence_analysis = {}
    silence_candidates = silence_analysis.get("candidates", [])
    if not isinstance(silence_candidates, list):
        silence_candidates = []
    silence_actions = silence_plan.get("actions", {})
    if not isinstance(silence_actions, dict):
        silence_actions = {}
    silence_result = silence_plan.get("premiere_result", {})
    if not isinstance(silence_result, dict):
        silence_result = {}
    silence_result_registered = silence_result.get("registered") is True
    split_applied_value = silence_result.get("split_applied")
    silence_split_applied = (
        split_applied_value
        if isinstance(split_applied_value, bool)
        else silence_actions.get("split_applied") is True
    )
    silence_review_pending = bool(silence_plan and silence_candidates and not silence_result_registered)
    version_index = _read_json_if_present(root / "project_versions.json")
    indexed_versions = version_index.get("versions", [])
    if not isinstance(indexed_versions, list):
        indexed_versions = []

    review_issues = [
        issue for issue in issues
        if isinstance(issue, dict) and issue.get("severity") in {"error", "warning", "needs_review"}
    ]
    review_needed = bool(
        review_issues
        or parse_issues
        or interpretation_status == "needs_review"
        or parse_validation_status not in {"valid", "unknown"}
        or premiere_human_review_pending
        or human_audio_review_pending
        or silence_review_pending
    )
    status_text = "확인 필요" if review_needed else "자동 검사 통과"
    issue_messages = [
        f"- [{issue.get('severity', 'unknown')}] {issue.get('code', 'unknown')}: {issue.get('message', '')}"
        for issue in review_issues
    ]
    issue_messages.extend(f"- [instruction] {item}" for item in parse_issues)
    if not issue_messages:
        issue_messages = ["- 자동 검증과 지시 파싱에서 추가 확인 항목이 없습니다."]
    if premiere_verified:
        issue_messages.append(f"- [Premiere UI] {premiere_status}")
    if ai_review_complete:
        issue_messages.append("- [Codex 자막 1차 검토] `10_REPORTS/transcript_ai_review.md` 작성 완료; 원음 청취 및 사람 싱크 검수는 대기 중입니다.")
    if before_review_srt_exists and after_ai_review_srt_exists:
        issue_messages.append("- [전·후 선택용 SRT] `transcript_before_review.srt`와 `transcript_after_ai_review.srt`가 있습니다. 둘 다 원음 검수 전 선택안이며, `transcript_reviewed.srt`는 아직 확정되지 않았습니다.")
    elif before_review_srt_exists and ai_review_complete:
        issue_messages.append("- [전·후 선택용 SRT] 전사 직후 비교본은 있으나 AI 후보본 `transcript_after_ai_review.srt`가 없습니다.")
    if reviewed_srt_exists:
        issue_messages.append("- [사람 검수 SRT] `transcript_reviewed.srt`가 프로젝트에 있습니다. 사람 검수 보고서와 상태를 함께 확인합니다.")
    if silence_plan:
        result_detail = ""
        if silence_result_registered:
            registered_project = silence_result.get("registered_project_file") or "경로 확인 필요"
            review_sequence = silence_result.get("review_sequence_name") or "이름 확인 필요"
            report_reference = silence_result.get("report_path") or "결과 JSON 확인 필요"
            srt_cue_count = silence_result.get("srt_cue_count")
            caption_count = silence_result.get("premiere_caption_item_count")
            caption_delta = silence_result.get("caption_count_delta")
            caption_detail = ""
            if isinstance(srt_cue_count, int) and isinstance(caption_count, int):
                delta_text = f"{caption_delta:+d}" if isinstance(caption_delta, int) else "확인 필요"
                caption_detail = f"; Premiere 캡션 {caption_count}/{srt_cue_count}개({delta_text})"
            result_detail = (
                f"; REVIEW 사본=`{registered_project}`, 시퀀스=`{review_sequence}`, "
                f"결과=`{report_reference}`{caption_detail}; 재열기 검수 대기"
            )
            api_detail = _silence_runtime_api_summary(silence_result)
            if api_detail:
                result_detail += f"; {api_detail}"
        issue_messages.append(
            f"- [Smart Silence Split] 자막 사이 공백 후보 {len(silence_candidates)}개 분석; "
            f"검토 마커 {silence_result.get('marker_count', 0)}개, "
            f"클립 분할 {'적용' if silence_actions.get('split_applied') else '미적용'}, "
            f"자동 삭제 {'허용됨' if silence_actions.get('auto_delete') else '금지'}; "
            f"버전 상태={silence_result.get('validation_status', '분석 대기')}{result_detail}; "
            "후보는 실제 무음으로 확정되지 않았습니다."
        )

    assets = manifest.get("assets", [])
    if not isinstance(assets, list):
        assets = []
    asset_paths = sorted(
        {
            str(asset.get("path"))
            for asset in assets
            if isinstance(asset, dict) and isinstance(asset.get("path"), str)
        }
    )
    if not asset_paths:
        fallback_paths = [root / "project.json", root / "checkpoint.json"]
        for relative in ("02_INSTRUCTIONS", "03_ANALYSIS", "05_AUDIO", "10_REPORTS"):
            folder = root / relative
            if folder.is_dir():
                fallback_paths.extend(
                    path for path in folder.rglob("*") if path.is_file() and not _is_os_metadata_file(path)
                )
        asset_paths = sorted(
            path.relative_to(root).as_posix()
            for path in fallback_paths
            if path.is_file() and path != report_path and not _is_os_metadata_file(path)
        )
    transcript_paths = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "07_TRANSCRIPTS").rglob("*")
        if (
            path.is_file()
            and path.suffix.lower() in {".srt", ".json", ".txt", ".md"}
            and not _is_os_metadata_file(path)
        )
    ) if (root / "07_TRANSCRIPTS").is_dir() else []
    listed_assets = sorted(set(asset_paths + transcript_paths))
    for relative in (
        "project_versions.json",
        "10_REPORTS/silence_candidates.json",
        "10_REPORTS/silence_candidates.csv",
        "10_REPORTS/silence_split_plan.json",
        "10_REPORTS/silence_split_validation.md",
    ):
        if (root / relative).is_file():
            listed_assets.append(relative)
    if silence_result.get("report_path") and (root / str(silence_result["report_path"])).is_file():
        listed_assets.append(str(silence_result["report_path"]))
    listed_assets = sorted(set(listed_assets))
    compatibility = manifest.get("compatibility", {})
    if not isinstance(compatibility, dict):
        compatibility = {}
    next_actions = []
    if review_needed:
        next_actions.append("위 확인 항목을 Codex가 의뢰 원문과 대조하고, 추측이 필요한 항목은 사용자에게 확인합니다.")
    if available_audio and not selected_streams:
        next_actions.append("오디오 미리듣기를 확인한 뒤 `vea select-audio PROJECT --streams INDEX`로 보이스 스트림을 선택합니다.")
    if not compatibility.get("premiere_import_verified", False):
        next_actions.append("대상 컴퓨터의 Premiere에서 XML을 가져와 컷 편집 가능 여부와 영상·오디오 싱크를 확인합니다.")
    roughcut_voice_exists = (root / "05_AUDIO" / "roughcut_voice.wav").is_file()
    if not transcript_paths and selected_streams and not roughcut_voice_exists:
        next_actions.append("Windows에서 원본 경로를 확인한 뒤 `vea audio PROJECT`로 선택된 보이스의 컷 정렬 WAV를 만들고, `vea verify PROJECT` 통과 후 `vea transcribe PROJECT`를 실행합니다.")
    elif not transcript_paths and selected_streams:
        next_actions.append("Windows에서 `vea verify PROJECT` 후 `vea transcribe PROJECT`를 실행해 SRT와 검토 리포트를 생성합니다.")
    if not transcript_paths and not available_audio and not selected_streams:
        next_actions.append("이 원본에는 확인된 오디오 스트림이 없습니다. 영상 편집 진행 여부를 확인합니다.")
    if human_audio_review_pending or premiere_human_review_pending:
        if ai_review_complete:
            if before_review_srt_exists and after_ai_review_srt_exists:
                next_actions.append("`07_TRANSCRIPTS/transcript_before_review.srt`와 `transcript_after_ai_review.srt`를 사용자에게 함께 제시해 기준본을 선택하게 합니다. 선택한 파일을 Premiere에서 원음과 대조하고 실제 수정만 `transcript_reviewed.srt`에 반영한 뒤, `10_REPORTS/transcript_human_review.md`에 청취·수정 사항을 기록합니다.")
            elif before_review_srt_exists:
                next_actions.append("전사 직후 비교본 `transcript_before_review.srt`는 있습니다. AI 검토 내용을 반영한 별도 `transcript_after_ai_review.srt`를 만들고 두 파일을 사용자에게 함께 제시한 뒤, 선택한 파일을 원음과 대조합니다.")
            else:
                next_actions.append("전사 직후 `transcript_before_review.srt`를 원본 SRT의 바이트 동일 복사본으로 만들고, AI 검토 뒤 별도 `transcript_after_ai_review.srt` 후보를 작성해 사용자에게 함께 제시합니다.")
            next_actions.append("원음 대조로 확인한 수정만 `07_TRANSCRIPTS/transcript_reviewed.srt`로 확정하고 `10_REPORTS/transcript_human_review.md`에 실제 청취·수정 사항을 기록합니다.")
        else:
            next_actions.append("`10_REPORTS/transcript_human_review.md`와 `07_TRANSCRIPTS/transcript_review.md`를 보며 원음 대조, 저신뢰·겹침·컷 경계 자막의 문구와 싱크를 검수하고, 수정본은 `07_TRANSCRIPTS/transcript_reviewed.srt`로 보존합니다.")
    if silence_review_pending:
        next_actions.append(
            "`10_REPORTS/silence_split_plan.json`을 확인한 뒤 Premiere의 VEA Silence Review 패널로 새 REVIEW 사본에 "
            "복제 시퀀스와 후보 범위 마커를 추가합니다. 패널은 Razor API가 런타임에 제공될 때만 선택 트랙을 분할합니다. "
            "Razor API가 없으면 인접 클립을 덮을 수 있는 clone/trim 대체 분할은 하지 않고 마커 전용 사본을 만듭니다."
        )
        next_actions.append(
            "새 Premiere 사본을 저장한 뒤 `vea project register PROJECT --file FILE --stage REVIEW --source-version SOURCE --set-current`로 pending 등록하고, Premiere 재열기 검수 후 검증 상태를 갱신합니다."
        )
    elif silence_result_registered:
        split_review_text = "실제 분할이 적용됐습니다" if silence_split_applied else "실제 분할은 적용되지 않았습니다"
        next_actions.append(
            f"등록된 REVIEW 사본 `{silence_result.get('registered_project_file')}`을 Premiere에서 다시 열어 시퀀스·캡션·오디오·효과와 {silence_result.get('marker_count', 0)}개 마커를 확인합니다. "
            f"{split_review_text}. 재열기 검수 전까지 버전은 pending으로 유지합니다."
        )
    if not manifest_path.is_file():
        next_actions.append("현재는 접수 검토 단계라 manifest.json과 러프컷이 없습니다. 편집 동작을 확인한 뒤 `vea resume PROJECT`로 준비를 이어갑니다.")
    if not next_actions:
        next_actions.append("새 검토 항목이 있는지 확인하고 최신 결과를 Notion과 사용자 보고에 반영합니다.")

    transfer_steps = [
        "Mac과 Windows 사이에는 이 프로젝트 폴더 전체를 전달합니다.",
        "현재 체크포인트는 편집 동작 확인 전 접수 단계라 `manifest.json`과 러프컷이 없습니다. Windows에서 원본 접근과 경로를 살펴볼 수 있지만, VEA 패키지 검증은 편집 동작을 확정하고 manifest가 생성된 뒤 실행합니다.",
        "편집 동작과 보이스 스트림을 확정한 뒤 `vea resume PROJECT`로 준비하고, 생성된 패키지를 Windows에서 `vea verify PROJECT`로 검사합니다. 원본 경로가 달라졌다면 같은 파일인지 SHA-256으로 확인한 뒤 `vea relink PROJECT --source SOURCE`를 실행합니다.",
        "Codex는 갱신된 보고서와 체크포인트를 읽어 Notion 기록을 갱신하고 사용자에게 결과를 보고합니다. 원본 영상은 Notion에 업로드하지 않습니다.",
    ]
    if manifest_path.is_file():
        transfer_steps = [
            "Mac과 Windows 사이에는 이 프로젝트 폴더 전체를 전달합니다. `project.json`, `manifest.json`, `checkpoint.json`과 하위 폴더를 함께 보존합니다.",
            "Windows에서 원본 경로가 달라졌으면 저장된 SHA-256과 대조하는 `vea relink PROJECT --source SOURCE`를 실행합니다. 보이스 선택은 전체 FFprobe 스트림 인덱스로 기록되어 있습니다.",
            "컷 기준 자막이 필요하면 `vea audio PROJECT`로 선택 스트림의 컷 정렬 WAV를 만들고 `vea verify PROJECT` 후 `vea transcribe PROJECT`를 실행합니다. 전사 직후 SRT 바이트 동일본과 Codex AI 후보본을 별도 저장해 사용자에게 전·후 선택지를 제공합니다.",
            "Windows 사람 검수 파일을 저장한 뒤 `vea handoff PROJECT`로 manifest를 갱신하고 `vea verify PROJECT`, `vea report PROJECT`를 실행한 다음 전체 프로젝트 폴더를 공유합니다.",
            "Codex는 이 보고서와 체크포인트를 읽어 Notion 기록을 갱신하고 사용자에게 결과를 보고합니다. 원본 영상은 Notion에 업로드하지 않습니다.",
        ]
        if premiere_verified:
            review_reference = " `10_REPORTS/transcript_ai_review.md`의 후보 목록을 확인한 뒤" if ai_review_complete else ""
            transfer_steps[2] = f"현재 SRT는 Windows Premiere 검증본의 C1 Subtitle 트랙에 가져와 시작·중간·끝·컷 경계 표시를 확인했습니다.{review_reference} 원음 청취 및 사람 싱크 검수는 남아 있습니다. 전·후 선택용 파일 `transcript_before_review.srt`와 `transcript_after_ai_review.srt`를 비교하고, 사용자가 선택한 기준으로 청취 검수한 뒤 `transcript_human_review.md`를 갱신해 전체 프로젝트 폴더를 Mac에 전달합니다."

    lines = [
        "# Codex 전달 보고서",
        "",
        f"- 생성 시각(UTC): {datetime.now(timezone.utc).isoformat()}",
        f"- 생성 환경: {platform.system() or 'unknown'}",
        f"- VEA 상태: **{status_text}**",
        "",
        "## 프로젝트",
        "",
        f"- 제목: {metadata.get('title') or manifest.get('title') or '미지정'}",
        f"- 프로젝트 ID: {metadata.get('project_id') or manifest.get('project_id') or '미지정'}",
        f"- 프로젝트 폴더(현재 컴퓨터): `{root}`",
        f"- 원본 경로(현재 컴퓨터): `{source_path}`",
        f"- 원본 크기: {source_size if source_size is not None else '확인 불가'} bytes",
        f"- 원본 SHA-256: {'저장됨' if source_hash else '미저장'}",
        f"- 영상: {duration_text}, {resolution}{source_rate_text}",
        f"- 타임라인: {manifest.get('clip_count', 0)}개 컷, FPS {fps_text}",
        f"- 지시 해석/검증: {interpretation_status} / {parse_validation_status}",
        f"- 선택된 보이스 스트림(전체 FFprobe 인덱스): {', '.join(map(str, selected_streams)) if selected_streams else '미선택'}",
        f"- Premiere 자막 표시 검증: {premiere_status}",
        f"- Codex 자막 1차 검토: {'완료 (`10_REPORTS/transcript_ai_review.md`)' if ai_review_complete else '미수행'}",
        f"- 전·후 선택용 SRT: before={'있음' if before_review_srt_exists else '없음'}, after AI={'있음' if after_ai_review_srt_exists else '없음'}, 사람 검수본={'있음' if reviewed_srt_exists else '미확정'}",
        f"- Smart Silence Split: {len(silence_candidates)}개 자막 공백 후보, 검토 마커={silence_result.get('marker_count', 0)}개, 시간 해석={silence_analysis.get('time_source', '미실행')}, 클립 분할={'적용' if silence_split_applied else '미적용'}, 분할 방식={silence_result.get('split_method') or '미기록'}",
        f"- Premiere 버전 인덱스: {len(indexed_versions)}개 파일, 최신 작업 후보={version_index.get('latest_working_version') or '미확인'}, 최신 검증본={version_index.get('latest_verified_version') or '미확인'}",
        "",
        "## 체크포인트",
        "",
    ]
    if stage_data:
        for name, stage in sorted(stage_data.items()):
            if not isinstance(stage, dict):
                continue
            detail = f" — {stage['error']}" if stage.get("error") else ""
            lines.append(f"- {name}: {stage.get('status', 'unknown')}{detail}")
    else:
        lines.append("- 아직 기록된 체크포인트가 없습니다.")
    lines.extend(["", "## 확인 항목", "", *issue_messages, "", "## 주요 산출물", ""])
    if listed_assets:
        lines.extend(f"- `{path}`" for path in listed_assets[:80])
        if len(listed_assets) > 80:
            lines.append(f"- 그 외 {len(listed_assets) - 80}개 파일은 `manifest.json`의 assets 참조")
    else:
        lines.append("- 아직 등록된 산출물이 없습니다.")
    if not manifest_path.is_file():
        lines.append("- `manifest.json`: 미생성 — 편집 동작 확인 전 접수 검토 단계")
    lines.extend(
        [
            "",
            "## 권장 다음 단계",
            "",
            *[f"- {item}" for item in next_actions],
            "",
            "## Mac·Windows 전달 순서",
            "",
            *[f"{index}. {item}" for index, item in enumerate(transfer_steps, start=1)],
            "",
            "## 외부 기록 소유자",
            "",
            "Notion 검색·생성·수정은 VEA 프로그램이 아니라 Codex의 연결된 Notion 도구가 담당합니다. Codex는 제목과 프로젝트 ID로 기존 항목을 확인하고, 중복 후보가 있으면 임의로 새 항목을 만들지 말고 사용자에게 알립니다.",
            "",
        ]
    )
    atomic_write_text(report_path, "\n".join(lines), encoding="utf-8")

    if manifest_path.is_file():
        assets = [asset for asset in assets if not (isinstance(asset, dict) and asset.get("path") == "10_REPORTS/codex_handoff.md")]
        assets.append(
            {
                "path": "10_REPORTS/codex_handoff.md",
                "size_bytes": report_path.stat().st_size,
                "sha256": _sha256(report_path),
            }
        )
        manifest["assets"] = sorted(assets, key=lambda asset: str(asset.get("path", "")))
        atomic_write_json(manifest_path, manifest)
    return report_path


def maybe_copy_source(source: str | Path, project_dir: str | Path, enabled: bool) -> Path | None:
    if not enabled:
        return None
    original = Path(normalize_path(source))
    target = Path(project_dir) / "01_SOURCE" / original.name
    if same_path(target, original):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == original.stat().st_size and _sha256(target) == _sha256(original):
            return target
        raise FileExistsError(f"원본과 다른 파일이 이미 있어 덮어쓰지 않았습니다: {target}")
    temporary = target.with_name(f".{target.name}.copying")
    try:
        with original.open("rb") as source_handle, temporary.open("wb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=8 * 1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        shutil.copystat(original, temporary)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def finalize_handoff(
    project_dir: str | Path,
    source: str | Path,
    media: MediaInfo,
    clips: list[TimelineClip] | None,
    fps: FrameRate | None,
    include_source: bool = False,
    full_media_hash: bool = False,
) -> dict[str, Any]:
    root = Path(project_dir).resolve()
    for folder in PROJECT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    source_path = Path(normalize_path(source))
    copied = maybe_copy_source(source_path, root, include_source) if source_path.is_file() else None
    if include_source and copied is None:
        raise FileNotFoundError(f"패키지에 원본을 복사하도록 요청했지만 원본을 찾을 수 없습니다: {source_path}")
    issues = validate_project(root, media=media, clips=clips, fps=fps)
    validation_path = write_validation_report(
        root / "10_REPORTS" / "validation.md",
        issues,
        {
            "원본": str(source_path),
            "프로젝트": str(root),
            "클립 수": len(clips) if clips is not None else 0,
            "Premiere 앱 검증": premiere_verification_status(root),
        },
    )
    atomic_write_text(root / "validation.md", validation_path.read_text(encoding="utf-8"))
    project_meta = _read_json_if_present(root / "project.json")
    recorded_fingerprint = project_meta.get("source_fingerprint", {})
    if not isinstance(recorded_fingerprint, dict):
        recorded_fingerprint = {}
    if source_path.is_file():
        source_fingerprint = file_fingerprint(source_path, full_hash=full_media_hash)
        recorded_path = recorded_fingerprint.get("path")
        recorded_sha = recorded_fingerprint.get("sha256")
        if (
            not full_media_hash
            and isinstance(recorded_path, str)
            and isinstance(recorded_sha, str)
            and same_path(recorded_path, source_path)
            and recorded_fingerprint.get("size_bytes") == source_fingerprint.get("size_bytes")
            and recorded_fingerprint.get("mtime_ns") == source_fingerprint.get("mtime_ns")
        ):
            # Preserve a previously content-verified digest when a later stage
            # only needs a stat fingerprint for the same unchanged source.
            source_fingerprint["hash_mode"] = "sha256"
            source_fingerprint["sha256"] = recorded_sha
    else:
        # Windows may receive the Mac-prepared project while the original SSD
        # is disconnected. Reuse the fingerprint captured during preparation.
        if not recorded_fingerprint:
            raise FileNotFoundError(
                f"원본이 연결되지 않았고 저장된 원본 지문도 없습니다: {source_path}"
            )
        source_fingerprint = recorded_fingerprint
    asset_paths: list[Path] = []
    for folder in ("02_INSTRUCTIONS", "03_ANALYSIS", "04_ROUGHCUT", "05_AUDIO", "07_TRANSCRIPTS", "08_PREMIERE", "10_REPORTS"):
        asset_paths.extend(
            path
            for path in (root / folder).rglob("*")
            if (
                path.is_file()
                and path.name not in {"validation.md", "validation.json"}
                and not _is_os_metadata_file(path)
            )
        )
    for relative in ("cuts.csv", "config.toml"):
        if (root / relative).is_file():
            asset_paths.append(root / relative)
    unique_paths = sorted(set(asset_paths))
    assets = []
    for path in unique_paths:
        item = {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        assets.append(item)
    source_relink = project_meta.get("source_relink") or {}
    conversion_path = root / "03_ANALYSIS" / "cfr_time_map.json"
    try:
        source_conversion = json.loads(conversion_path.read_text(encoding="utf-8")) if conversion_path.is_file() else None
    except (OSError, ValueError):
        source_conversion = {"status": "invalid_conversion_map"}
    manifest = {
        "manifest_version": 1,
        "project_id": None,
        "project_dir": str(root),
        "source": {
            **source_fingerprint,
            "copied_to_project": str(copied.relative_to(root)) if copied else None,
        },
        "source_conversion": source_conversion,
        "duration_seconds": media.duration,
        "video": media.video,
        "audio_streams": [stream.to_dict() for stream in media.audio_streams],
        "timeline_fps": fps.to_json() if fps else None,
        "clip_count": len(clips) if clips is not None else 0,
        "assets": assets,
        "validation": [issue.to_dict() for issue in issues],
        "compatibility": {
            "xmeml_generated": (root / "04_ROUGHCUT/roughcut.xml").is_file(),
            "premiere_import_verified": _has_verified_premiere_subtitles(root, project_meta.get("project_id")),
            "windows_transcription_verified": _has_completed_windows_transcription(root),
        },
        "relinking": {
            "status": source_relink.get("match", "original_path"),
            "premiere_xml_path_updated": bool(source_relink),
            "premiere_import_verified": False,
        },
    }
    manifest["project_id"] = project_meta.get("project_id")
    manifest["title"] = project_meta.get("title")
    atomic_write_json(root / "manifest.json", manifest)
    refresh_codex_handoff_report(root)
    return _read_json_if_present(root / "manifest.json")
