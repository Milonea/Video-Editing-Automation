from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from . import __version__
from .config import load_config as load_layered_config
from .audio import build_voice_roughcut
from .benchmark import benchmark_media, write_benchmark_report
from .cfr import cfr_sidecar_path, create_cfr_proxy
from .checkpoint import Checkpoint, atomic_write_json, atomic_write_text, canonical_hash, file_fingerprint
from .disk_space import (
    disk_space_message,
    disk_space_report,
    estimate_prepare_space,
    estimate_transcription_scratch,
)
from .environment import collect_environment, select_transcription_device
from .instruction_parser import parse_instructions
from .media import AudioStream, MediaInfo, audio_preview_paths, make_audio_previews, probe_media, require_binary
from .models import EditDecision, FrameRate, InstructionSet, TimelineClip
from .package import finalize_handoff, premiere_verification_status, refresh_codex_handoff_report, write_cuts_csv
from .premiere import export_fcp7_xml, export_video_only_source_xml
from .paths import normalize_path, same_path
from .project import find_existing_projects, initialize_project, safe_project_name
from .relink import relink_project
from .subtitles import (
    SubtitleSegment,
    detect_silence_intervals,
    make_silence_tail_preview,
    read_srt,
    validate_subtitles,
    write_srt,
)
from .timecode import format_srt_timestamp, frames_to_seconds
from .timeline import TimelineError, build_timeline, make_edit_map
from .transcriber import transcribe_project
from .validation import ValidationIssue, validate_manifest_assets, validate_project, write_validation_report
from .workspace import (
    WorkspaceError,
    create_workspace_manifest,
    resolve_workspace,
)
from .silence_split import analyze_caption_gaps, read_whisper_json, write_candidate_artifacts
from .versioning import (
    PROJECT_STAGES,
    create_version_snapshot,
    now_kst,
    refresh_project_versions,
    register_project_version,
    verify_project_versions,
    version_filename,
)


def _json_read(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_config(
    config_path: str | Path | None,
    project_dir: Path | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    project_config = project_dir / "config.toml" if project_dir and (project_dir / "config.toml").is_file() else None
    return load_layered_config(project_config_path=project_config, explicit_path=config_path, profile=profile).values


def _code_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _command_config_status(args: argparse.Namespace) -> int:
    result = load_layered_config(explicit_path=args.config, profile=getattr(args, "profile", None))
    report = {"status": "valid", "sources": list(result.sources), "sections": sorted(result.values)}
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print("VEA 설정 레이어: " + (" → ".join(result.sources) if result.sources else "기본값만 적용"))
        print("설정 섹션: " + (", ".join(report["sections"]) if report["sections"] else "없음"))
    return 0


def _command_workspace_resolve(args: argparse.Namespace) -> int:
    config = _load_config(args.config, profile=getattr(args, "profile", None))
    resolution = resolve_workspace(
        config=config,
        explicit_root=args.root,
        code_root=_code_root(),
    )
    report = resolution.to_dict()
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print(f"워크스페이스 ID: {report['workspace_id']}")
        print(f"프로젝트 루트: {report['projects_root']}")
        print(f"탐색 방식: {report['source']}")
        print(f"프로젝트 루트 존재: {'예' if report['projects_root_exists'] else '아니요'}")
    return 0


def _command_workspace_init(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    try:
        root.relative_to(_code_root().resolve())
    except ValueError:
        pass
    else:
        raise ValueError("워크스페이스 manifest를 VEA 코드 저장소 안에 만들 수 없습니다.")
    preview = {
        "workspace_root": str(root),
        "manifest_path": str(root / ".vea-workspace.json"),
        "workspace_id": args.workspace_id,
        "workspace_type": "video_projects",
        "projects_relative_path": args.projects_path,
    }
    if not args.apply:
        preview["status"] = "dry_run"
        print(json.dumps(preview, ensure_ascii=True, indent=2))
        return 0
    path = create_workspace_manifest(
        root,
        workspace_id=args.workspace_id,
        projects_relative_path=args.projects_path,
    )
    preview["status"] = "created"
    preview["manifest_path"] = str(path)
    print(json.dumps(preview, ensure_ascii=True, indent=2))
    return 0


def _media_from_dict(data: dict[str, Any]) -> MediaInfo:
    return MediaInfo(
        path=data["path"],
        duration=float(data["duration"]),
        format_name=str(data.get("format_name", "")),
        size_bytes=int(data.get("size_bytes", 0)),
        video=data.get("video"),
        audio_streams=[AudioStream(**item) for item in data.get("audio_streams", [])],
        all_stream_count=int(data.get("all_stream_count", 0)),
    )


def _clips_from_map(data: dict[str, Any]) -> list[TimelineClip]:
    clips: list[TimelineClip] = []
    for item in data.get("clips", []):
        clips.append(
            TimelineClip(
                source_file=item["source_file"],
                source_in_frame=int(item["source_in_frame"]),
                source_out_frame=int(item["source_out_frame"]),
                timeline_start_frame=int(item["timeline_start_frame"]),
                timeline_end_frame=int(item["timeline_end_frame"]),
                source_in_seconds=Fraction(item["source_in_seconds"]),
                source_out_seconds=Fraction(item["source_out_seconds"]),
                label=item.get("label", ""),
                notes=item.get("notes", ""),
                ordering=int(item.get("ordering", 0)),
                mute_audio=bool(item.get("mute_audio", False)),
            )
        )
    return clips


def _parse_fps(value: str | None, media: MediaInfo) -> FrameRate:
    if value:
        return FrameRate.parse(value)
    rate = media.video.get("frame_rate") if media.video else None
    if not rate:
        raise ValueError("영상 FPS를 확인할 수 없습니다. --fps로 시퀀스 FPS를 지정하세요.")
    return FrameRate.parse(rate)


def _load_cfr_conversion_map(source: Path, project_dir: Path | None = None) -> dict[str, Any] | None:
    candidates = [cfr_sidecar_path(source)]
    if project_dir is not None:
        candidates.append(project_dir / "03_ANALYSIS" / "cfr_time_map.json")
    sidecar = next((path for path in candidates if path.is_file()), None)
    if sidecar is None:
        return None
    data = _json_read(sidecar)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"CFR 시간 매핑 sidecar 형식이 지원되지 않습니다: {sidecar}")
    recorded = data.get("proxy_fingerprint") or {}
    current = source.stat()
    if recorded.get("size_bytes") != current.st_size or recorded.get("mtime_ns") != current.st_mtime_ns:
        raise ValueError("CFR proxy가 sidecar 생성 후 변경되었습니다. 원본에서 다시 변환하세요.")
    return data


def _run_disk_preflight(
    project_dir: Path,
    stage_name: str,
    components: dict[str, int],
) -> dict[str, Any]:
    report = disk_space_report(project_dir, components)
    report_path = project_dir / "10_REPORTS" / f"{stage_name}-disk-preflight.json"
    atomic_write_json(report_path, report)
    checkpoint = Checkpoint(project_dir)
    signature = canonical_hash({"stage": stage_name, "components": components})
    checkpoint.start(f"{stage_name}_disk_preflight", signature, [report_path])
    print(disk_space_message(report))
    if not report["sufficient"]:
        message = (
            "사용 가능한 공간이 예상 산출물과 512 MiB 보존 여유보다 적습니다. "
            "다른 볼륨을 선택하거나 공간을 확보한 뒤 다시 실행하세요."
        )
        checkpoint.fail(f"{stage_name}_disk_preflight", RuntimeError(message), status="needs_review")
        raise RuntimeError(message)
    checkpoint.complete(f"{stage_name}_disk_preflight", report)
    return report


def _write_text(path: Path, value: str) -> None:
    atomic_write_text(path, value)


def _command_inspect(args: argparse.Namespace) -> int:
    media = probe_media(args.source)
    if args.output:
        atomic_write_json(args.output, media.to_dict())
    print(f"원본: {media.path}")
    print(f"길이: {media.duration:.3f}초 | 용량: {media.size_bytes:,}바이트 | 포맷: {media.format_name}")
    if media.video:
        print(
            "영상: 전체 스트림 {global_index} | {codec} | {width}x{height} | FPS {frame_rate} | VFR 의심 {is_vfr_heuristic}".format(
                **media.video
            )
        )
    else:
        print("영상 스트림이 없습니다.")
    print("오디오 스트림:")
    for stream in media.audio_streams:
        print(
            f"  오디오 순번 {stream.audio_ordinal} | 전체 스트림 인덱스 {stream.global_index} | "
            f"{stream.codec} | {stream.channels or '?'}ch | {stream.sample_rate or '?'}Hz | "
            f"이름={stream.title or '(없음)'} | 후보={stream.candidate} | 시작={stream.start_time:.3f}s"
        )
    if args.previews:
        paths = make_audio_previews(media, args.previews)
        print(f"미리듣기 파일 {len(paths)}개 생성: {Path(args.previews).resolve()}")
    return 0


def _command_cfr_proxy(args: argparse.Namespace) -> int:
    source = Path(normalize_path(args.source))
    project_dir = Path(args.project_dir).expanduser().resolve()
    rate = FrameRate.parse(args.fps) if args.fps else None
    rate_label = f"{rate.value.numerator}-{rate.value.denominator}" if rate else "source-fps"
    output = project_dir / "01_SOURCE" / f"{source.stem}_cfr_{rate_label}.mp4"
    metadata_path = project_dir / "project.json"
    metadata = _json_read(metadata_path) if metadata_path.is_file() else None
    if metadata:
        recorded_source = metadata.get("source_file")
        if not recorded_source or not same_path(recorded_source, source):
            raise ValueError("기존 VEA 프로젝트의 원본과 CFR 변환 입력이 다릅니다.")
        if (project_dir / "04_ROUGHCUT" / "roughcut.xml").exists() or (project_dir / "04_ROUGHCUT" / "edit_map.json").exists():
            raise ValueError("러프컷 산출물이 이미 있어 기존 프로젝트 원본을 CFR proxy로 바꾸지 않았습니다.")
    result = create_cfr_proxy(source, output_path=output, fps=args.fps)
    if metadata:
        previous_fingerprint = metadata.get("source_fingerprint") or {}
        proxy_fingerprint = file_fingerprint(result["proxy"], full_hash=bool(previous_fingerprint.get("sha256")))
        metadata["source_file"] = str(result["proxy"])
        metadata["source_fingerprint"] = proxy_fingerprint
        metadata["cfr_conversion"] = {
            "map_file": "03_ANALYSIS/cfr_time_map.json",
            "fps": result["mapping"]["fps"],
            "source_time_to_proxy_frame": result["mapping"]["source_time_to_proxy_frame"],
        }
        atomic_write_json(metadata_path, metadata)
        request_path = project_dir / "02_INSTRUCTIONS" / "request.json"
        if request_path.is_file():
            request = _json_read(request_path)
            request["source"] = str(result["proxy"])
            request["conversion_map_file"] = "03_ANALYSIS/cfr_time_map.json"
            atomic_write_json(request_path, request)
    print(f"CFR proxy: {result['proxy']}")
    print(f"시간 매핑: {result['sidecar']}")
    print(f"매핑 식: {result['mapping']['source_time_to_proxy_frame']['formula']}")
    return 0


def _command_benchmark(args: argparse.Namespace) -> int:
    result = benchmark_media(args.source, sample_seconds=args.seconds)
    report_path = Path(args.project_dir).expanduser().resolve() / "10_REPORTS" / "benchmark.json"
    path = write_benchmark_report(report_path, result)
    print(f"벤치마크 리포트: {path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _command_parse(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8-sig") if args.file else args.text
    fps = FrameRate.parse(args.fps) if args.fps else None
    duration = Fraction(args.duration) if args.duration else None
    result = parse_instructions(text, source_file=args.source, fps=fps, duration=duration)
    atomic_write_json(args.output, result.to_dict())
    print(f"편집 지시 {len(result.edits)}개를 기록했습니다: {Path(args.output).resolve()}")
    print(f"해석 상태: {result.interpretation_status} | 검증 상태: {result.validation_status}")
    for issue in result.issues:
        print(f"- 확인 필요: {issue}")
    return 0


def _command_tracks(args: argparse.Namespace) -> int:
    media = probe_media(args.source)
    print(f"오디오 스트림 {len(media.audio_streams)}개")
    for stream in media.audio_streams:
        print(
            f"  전체 스트림 인덱스 {stream.global_index} (오디오 순번 {stream.audio_ordinal}) | "
            f"{stream.title or '(이름 없음)'} | {stream.channels or '?'}ch | "
            f"{stream.sample_rate or '?'}Hz | 후보 {stream.candidate}"
        )
    print(f"track_signature: {canonical_hash([stream.to_dict() for stream in media.audio_streams])}")
    if args.preview_dir:
        paths = make_audio_previews(
            media,
            args.preview_dir,
            sample_positions=tuple(float(value) for value in args.positions.split(",") if value.strip()) if args.positions else None,
            preview_seconds=args.preview_seconds,
        )
        print(f"청취 후 선택할 미리듣기 파일: {Path(args.preview_dir).resolve()} ({len(paths)}개)")
    return 0


def _command_select_audio(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    tracks_path = root / "03_ANALYSIS" / "tracks.json"
    if not tracks_path.is_file():
        raise FileNotFoundError("프로젝트 트랙 정보가 없습니다. 먼저 vea prepare 또는 vea inspect를 실행하세요.")
    data = _json_read(tracks_path)
    allowed = {int(item["global_index"]) for item in data["audio_streams"]}
    selected = [int(value.strip()) for value in args.streams.split(",") if value.strip()]
    if not selected:
        raise ValueError("--streams에 전체 스트림 인덱스를 하나 이상 입력하세요.")
    missing = sorted(set(selected) - allowed)
    if missing:
        raise ValueError(f"선택한 인덱스가 오디오 스트림에 없습니다: {missing}. 전체 오디오 인덱스: {sorted(allowed)}")
    value = {
        "selected_global_stream_indexes": selected,
        "track_signature": canonical_hash(data["audio_streams"]),
        "source_fingerprint": data.get("source_fingerprint"),
        "selected_by_user": True,
    }
    target = root / "03_ANALYSIS" / "voice_selection.json"
    atomic_write_json(target, value)
    print(f"선택한 보이스 스트림: {selected}")
    print(f"기록 위치: {target}")
    return 0


def _selected_streams(root: Path, media: MediaInfo, override: str | None) -> list[int]:
    if override:
        selected = [int(value.strip()) for value in override.split(",") if value.strip()]
    else:
        selection_path = root / "03_ANALYSIS" / "voice_selection.json"
        tracks = _json_read(root / "03_ANALYSIS" / "tracks.json")
        if selection_path.is_file():
            selection = _json_read(selection_path)
            if selection.get("track_signature") != canonical_hash(tracks["audio_streams"]):
                raise ValueError("오디오 구성이 바뀌어 이전 보이스 선택을 재사용할 수 없습니다. 트랙을 다시 듣고 선택하세요.")
            if selection.get("source_fingerprint") != tracks.get("source_fingerprint"):
                raise ValueError("원본 파일이 바뀌어 이전 보이스 선택을 재사용할 수 없습니다. 트랙을 다시 듣고 선택하세요.")
            selected = [int(value) for value in selection.get("selected_global_stream_indexes", [])]
        else:
            # `prepare --audio-streams` records the explicit selection alongside
            # its generated stems, even when the user did not run select-audio.
            voice_tracks_path = root / "05_AUDIO" / "voice_tracks.json"
            if not voice_tracks_path.is_file():
                return []
            voice_tracks = _json_read(voice_tracks_path)
            expected_signature = canonical_hash(tracks["audio_streams"])
            if voice_tracks.get("track_signature") != expected_signature:
                raise ValueError("보이스 스템이 현재 오디오 구성과 일치하지 않습니다. 트랙을 다시 선택하세요.")
            if voice_tracks.get("source_fingerprint") != tracks.get("source_fingerprint"):
                raise ValueError("보이스 스템이 현재 원본과 일치하지 않습니다. 트랙을 다시 선택하세요.")
            selected = [int(value) for value in voice_tracks.get("selected_global_stream_indexes", [])]
    available = {item.global_index for item in media.audio_streams}
    if set(selected) - available:
        raise ValueError("저장된 보이스 스트림 인덱스가 현재 미디어에 없습니다. 트랙을 다시 선택하세요.")
    return selected


def _full_source_audio(root: Path, requested_stream_index: int | None) -> tuple[Path, int]:
    metadata = _json_read(root / "project.json")
    source_value = metadata.get("source_file")
    conversion_map = root / "03_ANALYSIS" / "cfr_time_map.json"
    if conversion_map.is_file():
        mapping = _json_read(conversion_map)
        source_value = mapping.get("source_path") or source_value
    if not source_value:
        raise ValueError("프로젝트의 원본 경로가 없습니다. --audio로 전사할 파일을 지정하세요.")
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(
            f"전체 원본을 찾지 못했습니다: {source}. 원본 저장 장치를 연결하거나 --audio로 파일을 지정하세요."
        )
    media = probe_media(source)
    available = {stream.global_index for stream in media.audio_streams}
    if requested_stream_index is None:
        selected = _selected_streams(root, media, None)
        if not selected:
            raise ValueError("전체 원본 전사 전에 vea select-audio로 보이스 스트림을 선택하세요.")
        if len(selected) != 1:
            raise ValueError(
                f"선택된 보이스가 여러 개입니다: {selected}. 한 번에 하나씩 --audio-stream-index로 지정하세요."
            )
        requested_stream_index = selected[0]
    if requested_stream_index not in available:
        raise ValueError(
            f"원본에 전체 오디오 스트림 인덱스 {requested_stream_index}가 없습니다. 사용 가능: {sorted(available)}"
        )
    return source, requested_stream_index


def _command_prepare(args: argparse.Namespace) -> int:
    source = Path(normalize_path(args.source))
    if not source.is_file():
        raise FileNotFoundError(f"원본 영상이 없습니다: {source}")
    if args.instructions_file:
        instruction_text = Path(args.instructions_file).read_text(encoding="utf-8-sig")
    else:
        instruction_text = args.instructions or ""
    if not instruction_text.strip():
        raise ValueError("--instructions 또는 --instructions-file을 입력하세요.")
    config_source = Path(args.config).expanduser().resolve() if args.config else None
    initial_config = _load_config(config_source, profile=getattr(args, "profile", None))
    workspace_resolution = None
    if args.project_dir:
        project_dir = Path(args.project_dir).expanduser().resolve()
        if getattr(args, "video_workspace_root", None):
            workspace_resolution = resolve_workspace(
                config=initial_config,
                explicit_root=args.video_workspace_root,
                code_root=_code_root(),
            )
            try:
                project_dir.relative_to(workspace_resolution.projects_root)
            except ValueError as exc:
                raise ValueError(
                    "--project-dir은 지정한 영상 워크스페이스의 프로젝트 루트 안이어야 합니다."
                ) from exc
    else:
        try:
            workspace_resolution = resolve_workspace(
                config=initial_config,
                explicit_root=getattr(args, "video_workspace_root", None),
                code_root=_code_root(),
            )
        except WorkspaceError:
            # A caller may name an existing project search root for a resume.
            # It is read-only discovery; a new project still requires a resolved
            # video workspace and is never created in the current directory.
            if not args.search_root:
                raise
        search_root = Path(args.search_root).expanduser().resolve() if args.search_root else (
            workspace_resolution.projects_root if workspace_resolution else None
        )
        existing = find_existing_projects(source, search_root) if search_root else []
        if len(existing) > 1:
            raise ValueError(f"같은 원본을 참조하는 기존 프로젝트가 여러 개입니다. --project-dir로 지정하세요: {existing}")
        if existing:
            project_dir = existing[0]
        elif workspace_resolution:
            project_dir = (workspace_resolution.projects_root / safe_project_name(f"{source.stem}_VEA")).resolve()
        else:
            raise WorkspaceError(
                "새 영상 프로젝트를 만들려면 외장 워크스페이스를 연결하거나 "
                "--video-workspace-root/--project-dir을 명시하세요. 현재 폴더에 대체 프로젝트를 만들지 않았습니다."
            )
    preserve_client_request = bool(getattr(args, "preserve_client_request", False))
    request_instruction_file = getattr(args, "request_instruction_file", None)
    if preserve_client_request:
        if not request_instruction_file:
            raise ValueError("재개 중 원문 요청을 보존하려면 저장된 instruction_file 경로가 필요합니다.")
        instruction_record_path = Path(request_instruction_file)
        if instruction_record_path.is_absolute() or ".." in instruction_record_path.parts:
            raise ValueError("재개용 instruction_file은 프로젝트 내부 상대 경로여야 합니다.")
        if not (project_dir / instruction_record_path).is_file():
            raise FileNotFoundError(f"재개용 지시 파일이 프로젝트에 없습니다: {instruction_record_path}")
    config = _load_config(config_source, project_dir, getattr(args, "profile", None))
    project_config = project_dir / "config.toml"
    project_settings = config.get("project", {})
    audio_settings = config.get("audio", {})
    configured_streams = audio_settings.get("selected_voice_stream_indexes", [])
    configured_signature = audio_settings.get("track_signature")
    if args.sample_rate is None:
        args.sample_rate = int(project_settings.get("audio_sample_rate", 48000))
    if args.crossfade_ms is None:
        args.crossfade_ms = int(project_settings.get("audio_crossfade_ms", 5))
    args.hash_media = bool(args.hash_media or project_settings.get("hash_media", False))
    args.include_source = bool(args.include_source or project_settings.get("copy_source_to_package", False))
    if args.fps is None:
        args.fps = project_settings.get("sequence_fps")
    title = args.title or project_settings.get("title") or source.stem
    metadata = initialize_project(
        project_dir,
        title,
        source,
        workspace_id=workspace_resolution.workspace_id if workspace_resolution else None,
        workspace_root=workspace_resolution.workspace_root if workspace_resolution else None,
    )
    metadata["progress_status"] = "preparing"
    metadata["last_run_at"] = datetime.now(timezone.utc).isoformat()
    metadata["last_run_environment"] = {
        "operating_system": platform.system(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "vea_version": __version__,
    }
    metadata["next_step"] = "검증 리포트와 Codex 인계 자료 확인"
    atomic_write_json(project_dir / "project.json", metadata)
    if config_source and config_source != project_config.resolve():
        # Store a portable snapshot so resume on Windows does not depend on a
        # Mac-only absolute config path.
        _write_text(project_config, config_source.read_text(encoding="utf-8"))
    checkpoint = Checkpoint(project_dir, metadata["project_id"])
    request_record = {
        "source": str(source),
        "title": title,
        "fps": args.fps,
        "include_source": args.include_source,
        "instruction_file": request_instruction_file if preserve_client_request else "02_INSTRUCTIONS/client_request.txt",
        "config_file": "config.toml" if project_config.is_file() else None,
        "hash_media": args.hash_media,
    }
    atomic_write_json(project_dir / "02_INSTRUCTIONS" / "request.json", request_record)
    if not preserve_client_request:
        _write_text(project_dir / "02_INSTRUCTIONS" / "client_request.txt", instruction_text)

    source_fp = file_fingerprint(source, full_hash=args.hash_media)
    metadata["source_fingerprint"] = source_fp
    atomic_write_json(project_dir / "project.json", metadata)
    probe_signature = canonical_hash({"source": source_fp, "ffprobe": "json-v1"})
    info_path = project_dir / "03_ANALYSIS" / "media_info.json"
    tracks_path = project_dir / "03_ANALYSIS" / "tracks.json"
    media: MediaInfo | None = None
    if checkpoint.cached("media_probe", probe_signature, [info_path, tracks_path]):
        try:
            cached_media = _media_from_dict(_json_read(info_path))
            cached_tracks = _json_read(tracks_path)
            if (
                cached_media.path == str(source)
                and cached_tracks.get("source") == str(source)
                and cached_tracks.get("source_fingerprint") == source_fp
                and cached_tracks.get("audio_streams") == [stream.to_dict() for stream in cached_media.audio_streams]
            ):
                media = cached_media
        except (AttributeError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            # A missing or malformed cached probe is recoverable: probe again
            # and replace both analysis files atomically.
            pass
    if media is None:
        checkpoint.start("media_probe", probe_signature, [info_path, tracks_path])
        try:
            media = probe_media(source)
            atomic_write_json(info_path, media.to_dict())
            atomic_write_json(
                tracks_path,
                {
                    "source": media.path,
                    "source_fingerprint": source_fp,
                    "audio_streams": [stream.to_dict() for stream in media.audio_streams],
                    "selection_required": bool(media.audio_streams),
                    "note": "트랙명은 후보 정보이며 보이스 판정이 아닙니다. 미리듣기 후 전체 스트림 인덱스로 선택하세요.",
                },
            )
            checkpoint.complete("media_probe", {"audio_stream_count": len(media.audio_streams), "duration": media.duration})
        except Exception as exc:
            checkpoint.fail("media_probe", exc)
            raise
    assert media is not None

    cfr_conversion = _load_cfr_conversion_map(source, project_dir)
    fps = _parse_fps(args.fps, media)
    if cfr_conversion:
        map_rate = cfr_conversion.get("fps") or {}
        mapped_fps = FrameRate.parse(Fraction(int(map_rate["numerator"]), int(map_rate["denominator"])))
        if mapped_fps.value != fps.value:
            raise ValueError(
                f"CFR proxy FPS({mapped_fps.value})와 시퀀스 FPS({fps.value})가 다릅니다. "
                "proxy 변환과 같은 FPS를 지정하세요."
            )
        cfr_conversion["proxy_path"] = str(source)
        cfr_conversion["proxy_fingerprint"] = source_fp
        request_record["conversion_map_file"] = "03_ANALYSIS/cfr_time_map.json"
        atomic_write_json(project_dir / "03_ANALYSIS" / "cfr_time_map.json", cfr_conversion)
        metadata["cfr_conversion"] = {
            "map_file": "03_ANALYSIS/cfr_time_map.json",
            "fps": mapped_fps.to_json(),
            "source_time_to_proxy_frame": cfr_conversion["source_time_to_proxy_frame"],
        }
        atomic_write_json(project_dir / "project.json", metadata)
        atomic_write_json(project_dir / "02_INSTRUCTIONS" / "request.json", request_record)

    if media.video and media.video.get("is_vfr_heuristic") and cfr_conversion is None:
        message = (
            "원본은 VFR일 가능성이 있어 프레임 단위 XML 생성을 보류했습니다. "
            "먼저 `vea cfr-proxy SOURCE --output PROJECT/01_SOURCE/source_cfr.mp4`를 실행한 뒤 "
            "그 proxy를 `vea prepare --source`로 지정하세요. 변환기는 source 시간→CFR 프레임 매핑을 함께 기록합니다."
        )
        checkpoint.fail("vfr_conversion", ValueError(message), status="needs_review")
        write_validation_report(
            project_dir / "10_REPORTS" / "validation.md",
            [ValidationIssue("needs_review", "possible_vfr", message)],
            {"원본": str(source), "Premiere 앱 검증": "미수행"},
        )
        print(message)
        return 2

    if args.audio_streams is None and not (project_dir / "03_ANALYSIS" / "voice_selection.json").is_file():
        current_track_signature = canonical_hash([stream.to_dict() for stream in media.audio_streams])
        if configured_streams and configured_signature == current_track_signature:
            args.audio_streams = ",".join(str(value) for value in configured_streams)
        elif configured_streams:
            print("저장된 녹화 환경의 오디오 구성이 달라 보이스 자동 선택을 적용하지 않았습니다.")

    fps = _parse_fps(args.fps, media)
    source_rate = FrameRate.parse(media.video["frame_rate"]) if media.video and media.video.get("frame_rate") else None
    if source_rate and source_rate.value != fps.value:
        raise ValueError(
            f"원본 FPS({source_rate.value})와 시퀀스 FPS({fps.value})가 다릅니다. "
            "VEA 0.1은 두 프레임레이트가 같은 소스만 지원합니다. 소스와 같은 FPS를 사용하거나 먼저 CFR 변환본을 준비하세요."
        )
    instructions_path = project_dir / "03_ANALYSIS" / "instructions.json"
    parse_signature = canonical_hash(
        {
            "instruction_text": instruction_text,
            "source_file": str(source),
            "fps": fps.to_json(),
            "duration_seconds": str(Fraction(str(media.duration))),
            "parser_version": 5,
        }
    )
    parsed: InstructionSet | None = None
    if checkpoint.cached("instruction_parse", parse_signature, [instructions_path]):
        try:
            cached_parsed = InstructionSet.from_dict(_json_read(instructions_path))
            if cached_parsed.original_text == instruction_text and cached_parsed.source_file == str(source):
                parsed = cached_parsed
        except (AttributeError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    if parsed is None:
        checkpoint.start("instruction_parse", parse_signature, [instructions_path])
        try:
            parsed = parse_instructions(
                instruction_text,
                source_file=str(source),
                fps=fps,
                duration=Fraction(str(media.duration)),
            )
            atomic_write_json(instructions_path, parsed.to_dict())
        except Exception as exc:
            checkpoint.fail("instruction_parse", exc)
            raise
    if parsed is not None and checkpoint.data.get("stages", {}).get("instruction_parse", {}).get("status") != "completed":
        checkpoint.complete("instruction_parse", {"edit_count": len(parsed.edits), "status": parsed.interpretation_status})
    if not any(edit.action in {"keep", "delete"} and edit.source_out is not None for edit in parsed.edits):
        write_validation_report(
            project_dir / "10_REPORTS" / "validation.md",
            [ValidationIssue("needs_review", "no_resolved_ranges", "확정된 시작/종료 구간이 없습니다. 편집 지시를 확인하세요.")],
        )
        print(f"확정 편집 구간이 없어 준비를 보류했습니다. 확인 결과: {project_dir / '03_ANALYSIS/instructions.json'}")
        return 2
    try:
        clips = build_timeline(parsed.edits, source, Fraction(str(media.duration)), fps)
    except TimelineError as exc:
        checkpoint.fail("timeline", exc, status="needs_review")
        print(f"타임라인 생성 보류: {exc}")
        return 2

    selected = _selected_streams(project_dir, media, args.audio_streams)
    needs_previews = bool(
        media.audio_streams
        and not selected
        and not (project_dir / "03_ANALYSIS" / "voice_selection.json").is_file()
    )
    timeline_seconds = sum(float(clip.source_out_seconds - clip.source_in_seconds) for clip in clips)
    components = estimate_prepare_space(
        duration_seconds=media.duration,
        timeline_seconds=timeline_seconds,
        audio_stream_count=len(media.audio_streams) if needs_previews else 0,
        selected_audio_stream_count=len(selected),
        sample_rate=args.sample_rate,
        source_path=source,
        project_dir=project_dir,
        source_size_bytes=media.size_bytes,
        include_source=args.include_source,
    )
    _run_disk_preflight(project_dir, "prepare", components)

    preview_dir = project_dir / "05_AUDIO" / "previews"
    if needs_previews:
        preview_outputs = audio_preview_paths(media, preview_dir)
        preview_signature = canonical_hash(
            {
                "source": source_fp,
                "streams": [stream.to_dict() for stream in media.audio_streams],
                "positions": "spread-v1",
                "preview_seconds": 12,
            }
        )
        if not checkpoint.cached("audio_previews", preview_signature, preview_outputs):
            checkpoint.start("audio_previews", preview_signature, preview_outputs)
            try:
                previews = make_audio_previews(media, preview_dir)
                checkpoint.complete("audio_previews", {"preview_count": len(previews)})
                print(f"미리듣기 {len(previews)}개 생성: {preview_dir}")
            except Exception as exc:
                checkpoint.fail("audio_previews", exc)
                print(f"미리듣기 생성 실패(프로젝트 준비는 계속): {exc}")

    edit_map = make_edit_map(clips, fps)
    edit_map["source_fingerprint"] = source_fp
    edit_map["instruction_fingerprint"] = canonical_hash(instruction_text)
    edit_map["source_duration_seconds"] = media.duration
    edit_map["source_is_vfr_heuristic"] = bool(media.video and media.video.get("is_vfr_heuristic"))
    if cfr_conversion:
        edit_map["cfr_conversion"] = {
            "map_file": "03_ANALYSIS/cfr_time_map.json",
            "source_time_to_proxy_frame": cfr_conversion["source_time_to_proxy_frame"],
            "fps": cfr_conversion["fps"],
            "proxy_duration_seconds": cfr_conversion["proxy_duration_seconds"],
        }
    edit_map_path = project_dir / "04_ROUGHCUT" / "edit_map.json"
    cuts_path = project_dir / "04_ROUGHCUT" / "cuts.csv"
    atomic_write_json(edit_map_path, edit_map)
    write_cuts_csv(cuts_path, clips, fps)
    xml_path = project_dir / "04_ROUGHCUT" / "roughcut.xml"
    xml_signature = canonical_hash(
        {
            "source": source_fp,
            "edits": [edit.to_dict() for edit in parsed.edits],
            "fps": fps.to_json(),
            "format": "xmeml-v5-sequence-format-audio-links-v3",
        }
    )
    if not checkpoint.cached("xml_export", xml_signature, [xml_path]):
        checkpoint.start("xml_export", xml_signature, [xml_path])
        try:
            export_fcp7_xml(
                xml_path,
                media,
                clips,
                fps,
                sequence_name=title,
                enabled_audio_global_indexes=set(selected),
            )
            checkpoint.complete("xml_export", {"clip_count": len(clips), "file": str(xml_path)})
        except Exception as exc:
            checkpoint.fail("xml_export", exc)
            raise
    versioned_xml_path = create_version_snapshot(
        xml_path,
        project_dir,
        stage="ROUGHCUT",
    )

    if selected:
        audio_outputs = [
            project_dir / "05_AUDIO" / f"voice_stream_{audio.audio_ordinal:02d}_global_{audio.global_index}.wav"
            for audio in media.audio_streams
            if audio.global_index in selected
        ] + [project_dir / "05_AUDIO" / "roughcut_voice.wav"]
        audio_signature = canonical_hash(
            {
                "source": source_fp,
                "cuts": edit_map["clips"],
                "selected_global_indexes": selected,
                "sample_rate": args.sample_rate,
                "crossfade_ms": args.crossfade_ms,
                "ffmpeg": "pcm-s16le-v1",
            }
        )
        if not checkpoint.cached("audio_roughcut", audio_signature, audio_outputs):
            checkpoint.start("audio_roughcut", audio_signature, audio_outputs)
            try:
                paths = build_voice_roughcut(
                    media,
                    clips,
                    selected,
                    project_dir / "05_AUDIO",
                    sample_rate=args.sample_rate,
                    crossfade_ms=args.crossfade_ms,
                )
                track_data = _json_read(project_dir / "03_ANALYSIS" / "tracks.json")
                atomic_write_json(
                    project_dir / "05_AUDIO" / "voice_tracks.json",
                    {
                        "selected_global_stream_indexes": selected,
                        "outputs": [str(path.name) for path in paths],
                        "track_signature": canonical_hash(track_data["audio_streams"]),
                        "source_fingerprint": track_data.get("source_fingerprint"),
                    },
                )
                checkpoint.complete("audio_roughcut", {"selected_global_stream_indexes": selected, "outputs": len(paths)})
            except Exception as exc:
                checkpoint.fail("audio_roughcut", exc)
                raise
    else:
        checkpoint.data["stages"]["audio_roughcut"] = {
            "status": "needs_review",
            "signature": None,
            "outputs": [],
            "error": "보이스 오디오 스트림 미선택",
        }
        checkpoint.save()

    checkpoint.start("handoff", canonical_hash({"source": source_fp, "include_source": args.include_source}))
    manifest = finalize_handoff(
        project_dir,
        source,
        media,
        clips,
        fps,
        include_source=args.include_source,
        full_media_hash=args.hash_media,
    )
    checkpoint.complete("handoff", {"asset_count": len(manifest["assets"]), "validation_issue_count": len(manifest["validation"])})
    refresh_codex_handoff_report(project_dir)
    needs_review = any(issue["severity"] in {"error", "warning", "needs_review"} for issue in manifest["validation"])
    metadata = _json_read(project_dir / "project.json")
    metadata["progress_status"] = "prepared_needs_review" if needs_review or needs_previews else "prepared"
    metadata["next_step"] = (
        "미리듣기 후 전체 스트림 인덱스로 보이스 선택"
        if needs_previews and not selected
        else "Premiere에서 생성 XML을 확인하고 실제 호환성 검수"
    )
    metadata["last_run_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(project_dir / "project.json", metadata)
    print(f"프로젝트: {project_dir}")
    print(f"타임라인: {len(clips)}개 컷, {edit_map['duration_seconds']}초, FPS {fps.value}")
    print(f"Premiere XML: {xml_path}")
    print(f"시간 스탬프 XML 버전: {versioned_xml_path}")
    print("보이스 러프컷: " + (str(project_dir / "05_AUDIO" / "roughcut_voice.wav") if selected else "미생성 — 트랙 미리듣기 후 vea select-audio 실행"))
    print(f"검증 상태: {'확인 필요' if needs_review else '자동 검사 통과'}")
    return 2 if needs_review else 0


def _load_project_media(project_dir: Path) -> tuple[MediaInfo, list[TimelineClip], FrameRate]:
    info_path = project_dir / "03_ANALYSIS" / "media_info.json"
    map_path = project_dir / "04_ROUGHCUT" / "edit_map.json"
    if not info_path.is_file() or not map_path.is_file():
        raise FileNotFoundError("미디어 분석 또는 edit_map.json이 없습니다. 먼저 vea prepare를 실행하세요.")
    info = _media_from_dict(_json_read(info_path))
    edit_map = _json_read(map_path)
    fps = FrameRate.parse(
        Fraction(edit_map["fps"]["numerator"], edit_map["fps"]["denominator"])
    )
    clips = _clips_from_map(edit_map)
    return info, clips, fps


def _command_audio(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    config = _load_config(args.config, root, getattr(args, "profile", None))
    project_settings = config.get("project", {})
    if args.sample_rate is None:
        args.sample_rate = int(project_settings.get("audio_sample_rate", 48000))
    if args.crossfade_ms is None:
        args.crossfade_ms = int(project_settings.get("audio_crossfade_ms", 5))
    args.hash_media = bool(args.hash_media or project_settings.get("hash_media", False))
    media, clips, fps = _load_project_media(root)
    selected = _selected_streams(root, media, args.streams)
    if not selected:
        raise ValueError("보이스 스트림을 지정하거나 vea select-audio로 저장하세요.")
    timeline_seconds = sum(float(clip.source_out_seconds - clip.source_in_seconds) for clip in clips)
    _run_disk_preflight(
        root,
        "audio",
        estimate_prepare_space(
            duration_seconds=0,
            timeline_seconds=timeline_seconds,
            audio_stream_count=0,
            selected_audio_stream_count=len(selected),
            sample_rate=args.sample_rate,
        ),
    )
    checkpoint = Checkpoint(root)
    outputs = build_voice_roughcut(
        media,
        clips,
        selected,
        root / "05_AUDIO",
        sample_rate=args.sample_rate,
        crossfade_ms=args.crossfade_ms,
    )
    track_data = _json_read(root / "03_ANALYSIS" / "tracks.json")
    atomic_write_json(
        root / "05_AUDIO" / "voice_tracks.json",
        {
            "selected_global_stream_indexes": selected,
            "outputs": [item.name for item in outputs],
            "track_signature": canonical_hash(track_data["audio_streams"]),
            "source_fingerprint": track_data.get("source_fingerprint"),
        },
    )
    checkpoint.complete("audio_roughcut", {"selected_global_stream_indexes": selected, "outputs": len(outputs)})
    manifest = finalize_handoff(root, media.path, media, clips, fps, full_media_hash=args.hash_media)
    print(f"보이스 러프컷 생성: {root / '05_AUDIO' / 'roughcut_voice.wav'}")
    print(f"자동 검증 이슈: {len(manifest['validation'])}")
    return 0


def _command_handoff(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    media, clips, fps = _load_project_media(root)
    if args.include_source:
        _run_disk_preflight(
            root,
            "handoff",
            estimate_prepare_space(
                duration_seconds=0,
                timeline_seconds=0,
                audio_stream_count=0,
                selected_audio_stream_count=0,
                source_path=media.path,
                project_dir=root,
                source_size_bytes=media.size_bytes,
                include_source=True,
            ),
        )
    manifest = finalize_handoff(
        root,
        media.path,
        media,
        clips,
        fps,
        include_source=args.include_source,
        full_media_hash=args.hash_media,
    )
    checkpoint = Checkpoint(root)
    checkpoint.complete("handoff", {"asset_count": len(manifest["assets"])})
    refresh_codex_handoff_report(root)
    print(f"전달 패키지 검증 완료: {root}")
    print(f"manifest.json에 등록된 자산: {len(manifest['assets'])}")
    print(f"검증 항목: {len(manifest['validation'])}개")
    return 2 if any(item["severity"] == "error" for item in manifest["validation"]) else 0


def _command_verify(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    info_path = root / "03_ANALYSIS" / "media_info.json"
    map_path = root / "04_ROUGHCUT" / "edit_map.json"
    media = _media_from_dict(_json_read(info_path)) if info_path.is_file() else None
    clips: list[TimelineClip] | None = None
    fps: FrameRate | None = None
    if map_path.is_file():
        edit_map = _json_read(map_path)
        clips = _clips_from_map(edit_map)
        fps = FrameRate.parse(Fraction(edit_map["fps"]["numerator"], edit_map["fps"]["denominator"]))
    issues = validate_project(root, media=media, clips=clips, fps=fps)
    issues.extend(validate_manifest_assets(root))
    write_validation_report(
        root / "10_REPORTS" / "validation.md",
        issues,
        {"프로젝트": str(root), "Premiere 앱 검증": premiere_verification_status(root)},
    )
    refresh_codex_handoff_report(root)
    print(f"검증 결과: {root / '10_REPORTS' / 'validation.md'}")
    for issue in issues:
        print(f"- {issue.severity}: {issue.code} — {issue.message}")
    return 2 if any(issue.severity in {"error", "warning", "needs_review"} for issue in issues) else 0


def _command_relink(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    replacement = probe_media(args.source)
    previous_manifest = root / "manifest.json"
    include_source = False
    if previous_manifest.is_file():
        try:
            copied_to_project = _json_read(previous_manifest).get("source", {}).get("copied_to_project")
            include_source = bool(copied_to_project)
        except (AttributeError, TypeError, ValueError):
            include_source = False
    result = relink_project(root, replacement, confirm_structural_match=args.confirm_structural_match)
    versioned_xml_path = create_version_snapshot(
        root / "04_ROUGHCUT" / "roughcut.xml",
        root,
        stage="ROUGHCUT",
    )
    media, clips, fps = _load_project_media(root)
    manifest = finalize_handoff(
        root,
        replacement.path,
        media,
        clips,
        fps,
        include_source=include_source,
        full_media_hash=bool(result["source_fingerprint"].get("sha256")),
    )
    checkpoint = Checkpoint(root)
    checkpoint.complete("relink", {"match": result["match"], "asset_count": len(manifest["assets"])})
    refresh_codex_handoff_report(root)
    print(f"원본 경로를 갱신했습니다: {replacement.path}")
    print(f"파일 동일성 검사: {result['match']}")
    print(f"시간 스탬프 XML 버전: {versioned_xml_path}")
    print(
        f"Premiere XML 경로와 전달 manifest 갱신 완료. "
        f"Premiere 확인 상태: {premiere_verification_status(root)}"
    )
    return 2 if any(issue["severity"] in {"error", "warning", "needs_review"} for issue in manifest["validation"]) else 0


def _command_transcribe(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    config = _load_config(args.config, root, getattr(args, "profile", None))
    options = config.get("transcription", {})
    model = args.model or options.get("model", "large-v3")
    fallback_models = args.fallback_models.split(",") if args.fallback_models else options.get("fallback_models", ["large-v3-turbo", "medium"])
    requested_device = args.device or options.get("device", "auto")
    device, device_note = select_transcription_device(requested_device)
    if device_note:
        print(device_note)
    compute_type = args.compute_type or options.get("compute_type", "auto")
    if str(compute_type).casefold() in {"", "auto", "automatic"}:
        compute_type = "int8_float16" if device == "cuda" else "int8"
    language = args.language or options.get("language", "ko")
    beam_size = args.beam_size or int(options.get("beam_size", 5))
    chunk_seconds = args.chunk_seconds or int(options.get("chunk_seconds", 600))
    word_timestamps = bool(args.word_timestamps or options.get("word_timestamps", False))
    glossary = args.glossary or options.get("glossary_file")
    cpu_fallback = bool(args.cpu_fallback or options.get("cpu_fallback", False))
    full_source = bool(getattr(args, "full_source", False))
    requested_stream_index = getattr(args, "audio_stream_index", None)
    if requested_stream_index is not None and not full_source:
        raise ValueError("--audio-stream-index는 --full-source와 함께 사용하세요.")
    if full_source:
        audio_path, audio_stream_index = _full_source_audio(root, requested_stream_index)
        output_stem = getattr(args, "transcript_name", None) or f"full_source_global_{audio_stream_index}"
    else:
        audio_path = getattr(args, "audio", None)
        audio_stream_index = None
        output_stem = getattr(args, "transcript_name", None)
    result = transcribe_project(
        root,
        audio_file=audio_path,
        model_name=model,
        fallback_models=fallback_models,
        device=device,
        compute_type=compute_type,
        language=language,
        beam_size=beam_size,
        chunk_seconds=chunk_seconds,
        word_timestamps=word_timestamps,
        glossary_file=glossary,
        cpu_fallback=cpu_fallback,
        allow_non_windows=args.allow_non_windows,
        output_stem=output_stem,
        audio_stream_index=audio_stream_index,
    )
    project_metadata_path = root / "project.json"
    if project_metadata_path.is_file():
        project_metadata = _json_read(project_metadata_path)
        generated_files: list[str] = []
        for value in result.get("artifacts", {}).values():
            candidate = Path(str(value))
            if candidate.suffix.casefold() not in {".json", ".srt", ".vtt"}:
                continue
            try:
                generated_files.append(candidate.resolve().relative_to(root).as_posix())
            except ValueError:
                continue
        generated_at = datetime.now(timezone.utc).isoformat()
        project_metadata["latest_transcript"] = {"files": generated_files, "generated_at": generated_at}
        project_metadata["progress_status"] = "transcription_complete_review_pending"
        project_metadata["last_run_at"] = generated_at
        project_metadata["last_run_environment"] = {
            "operating_system": platform.system(),
            "architecture": platform.machine(),
            "python_version": sys.version.split()[0],
            "vea_version": __version__,
            "transcription_device": device,
            "compute_type": compute_type,
        }
        project_metadata["next_step"] = "전사 결과를 원음과 대조하고 사람 검수본을 확정"
        atomic_write_json(project_metadata_path, project_metadata)
    print(f"전사 구간: {result['segment_count']}개")
    for path in result["artifacts"].values():
        print(path)
    print(json.dumps(result["metadata"], ensure_ascii=False, indent=2))
    try:
        media, clips, fps = _load_project_media(root)
        finalize_handoff(root, media.path, media, clips, fps)
    except Exception as exc:
        print(f"전사 결과를 기존 전달 manifest에 반영하지 못했습니다: {exc}")
    return 0


def _command_subtitles(args: argparse.Namespace) -> int:
    source = Path(args.transcript_json).expanduser().resolve()
    data = _json_read(source)
    segments = [
        SubtitleSegment(
            start=float(item["start"]),
            end=float(item["end"]),
            text=str(item.get("text", "")),
            avg_logprob=item.get("avg_logprob"),
            no_speech_prob=item.get("no_speech_prob"),
            words=item.get("words"),
        )
        for item in data.get("segments", [])
    ]
    out = Path(args.output or source.with_name("transcript.srt"))
    write_srt(segments, out)
    duration = float(data.get("duration_seconds", max((item.end for item in segments), default=0.0)))
    issues = validate_subtitles(segments, duration, max_chars=args.max_chars)
    atomic_write_json(out.with_suffix(".validation.json"), {"issues": issues, "count": len(segments), "duration": duration})
    print(f"SRT: {out}")
    print(f"자동 검토 항목: {len(issues)}")
    return 2 if any(issue["severity"] == "error" for issue in issues) else 0


def _command_silence_preview(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    source_srt = Path(args.input_srt).expanduser().resolve() if args.input_srt else (
        root / "07_TRANSCRIPTS" / "transcript_after_ai_review.srt"
    )
    audio = Path(args.audio).expanduser().resolve() if args.audio else root / "05_AUDIO" / "roughcut_voice.wav"
    output_srt = Path(args.output_srt).expanduser().resolve() if args.output_srt else (
        root / "07_TRANSCRIPTS" / "transcript_after_ai_review_silence_preview.srt"
    )
    report_json = Path(args.report_json).expanduser().resolve() if args.report_json else (
        root / "10_REPORTS" / "transcript_silence_preview.json"
    )
    report_md = Path(args.report_md).expanduser().resolve() if args.report_md else (
        root / "10_REPORTS" / "transcript_silence_preview.md"
    )
    targets = (output_srt, report_json, report_md)
    existing = [str(path) for path in targets if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            "미리보기 결과가 이미 있습니다. 기존 파일을 보존하려면 다른 출력 경로를 지정하거나 "
            "의도적으로 교체할 때만 --overwrite를 사용하세요: " + ", ".join(existing)
        )

    source_segments = read_srt(source_srt)
    intervals = detect_silence_intervals(
        audio,
        threshold_db=args.threshold_db,
        min_duration=args.min_silence,
    )
    preview, summary = make_silence_tail_preview(source_segments, intervals, tail_seconds=args.tail_seconds)
    write_srt(preview, output_srt)

    interval_payload = [
        {"start": item.start, "end": item.end, "duration": item.duration}
        for item in intervals
    ]
    payload = {
        "version": 1,
        "method": "ffmpeg_silencedetect_srt_tail_preview",
        "project_dir": str(root),
        "input_srt": str(source_srt),
        "audio": str(audio),
        "output_srt": str(output_srt),
        "threshold_db": args.threshold_db,
        "min_silence_seconds": args.min_silence,
        "tail_seconds": args.tail_seconds,
        "silence_intervals": interval_payload,
        **summary,
        "human_review_status": "pending",
        "premiere_preview_import_status": "pending",
        "limitations": [
            "자동 무음 탐지는 낮은 음량의 발화도 무음으로 분류할 수 있습니다.",
            "단어 타임스탬프가 없는 구간 안쪽의 침묵은 문구를 안전하게 나눌 수 없어 그대로 두었습니다.",
            "이 미리보기는 원음 청취 검수본이 아니며 입력 SRT와 두 선택본은 변경하지 않았습니다.",
        ],
    }
    atomic_write_json(report_json, payload)

    lines = [
        "# 무음 기준 자막 종료 미리보기",
        "",
        "이 파일은 원음 청취 검수 전의 비교용 자막입니다. 입력 SRT와 AI 검수 전·후 선택본은 그대로 보존했습니다.",
        "",
        f"- 입력 SRT: `{source_srt}`",
        f"- 오디오: `{audio}`",
        f"- 무음 기준: {args.threshold_db:g} dBFS 이하, {args.min_silence:g}초 이상",
        f"- 무음 뒤 자막 유지 시간: {args.tail_seconds:g}초",
        f"- 탐지 무음 구간: {len(intervals)}개",
        f"- 종료 시각 변경: {summary['changed_cue_count']}개 자막",
        f"- 자동 변경 보류: {summary['unresolved_cue_count']}개 자막",
        "- Premiere 가져오기/표시 확인: 이 미리보기 파일 기준 미수행",
        "",
        "## 변경 내역",
        "",
    ]
    if summary["changes"]:
        for item in summary["changes"]:
            lines.append(
                f"- 자막 {item['cue']}: {format_srt_timestamp(item['old_end'])} → "
                f"{format_srt_timestamp(item['new_end'])} "
                f"(무음 시작 {format_srt_timestamp(item['silence_start'])}; {item['text']})"
            )
    else:
        lines.append("종료 시각 변경이 없습니다.")
    lines.extend(
        [
            "",
            "## 자동 변경 보류 항목",
            "",
        ]
    )
    if summary["unresolved"]:
        for item in summary["unresolved"]:
            lines.append(
                f"- 자막 {item['cue']} ({format_srt_timestamp(item['start'])}–"
                f"{format_srt_timestamp(item['end'])}): {item['reason']} — {item['text']}"
            )
    else:
        lines.append("없음")
    lines.extend(
        [
            "",
            "## 해석 주의",
            "",
            "- -50 dBFS 기준은 낮은 음량의 발화도 무음으로 볼 수 있으므로, 변경 구간은 원음으로 확인해야 합니다.",
            "- 음성이 자막 구간 안에서 다시 시작하면 자막을 자르지 않았습니다. 단어 타임스탬프 없이 한 문장 안의 공백에서 문구를 쪼개지 않았습니다.",
            "- 무음 안에 놓인 자막이나 다음 자막과 겹칠 변경은 자동 수정하지 않고 검토 목록에 남겼습니다.",
            "- 이 미리보기는 사람 청취 검수 완료본이 아닙니다.",
            "",
        ]
    )
    atomic_write_text(report_md, "\n".join(lines))
    print(f"미리보기 SRT: {output_srt}")
    print(f"검수 내역: {report_md}")
    print(f"탐지 무음 {len(intervals)}개, 변경 자막 {summary['changed_cue_count']}개, 보류 {summary['unresolved_cue_count']}개")
    return 0


def _resolve_project_input(root: Path, value: str | None, default: Path | None = None) -> Path:
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = root / path
        return path.resolve()
    if default is None:
        raise ValueError("입력 파일 경로를 지정하세요.")
    return default.resolve()


def _timecode_seconds(value: str, fps: Fraction) -> Fraction:
    import re

    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})([:;])(\d{2})", value.strip())
    if not match:
        raise ValueError(f"Premiere 시퀀스 길이 타임코드를 읽을 수 없습니다: {value}")
    hours, minutes, seconds, separator, frames = match.groups()
    nominal = round(float(fps))
    total_seconds = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    frame_number = total_seconds * nominal + int(frames)
    if separator == ";":
        drop_count = 4 if nominal == 60 else 2 if nominal == 30 else 0
        elapsed_minutes = int(hours) * 60 + int(minutes)
        frame_number -= drop_count * (elapsed_minutes - elapsed_minutes // 10)
    return Fraction(frame_number, 1) / fps


def _fps_from_project(root: Path, manifest: dict[str, Any], edit_map: dict[str, Any], override: str | None) -> Fraction:
    if override:
        return FrameRate.parse(override).value
    for value in (manifest.get("timeline_fps"), edit_map.get("fps")):
        if isinstance(value, dict) and value.get("numerator") and value.get("denominator"):
            return Fraction(int(value["numerator"]), int(value["denominator"]))
    raise ValueError(f"프로젝트 시퀀스 FPS를 확인할 수 없습니다. --fps를 지정하세요: {root}")


def _update_silence_split_manifest(
    root: Path,
    *,
    plan_path: Path,
    candidate_json: Path,
    candidate_csv: Path,
    validation_path: Path,
    version_index: dict[str, Any],
) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = _json_read(manifest_path)
    plan = _json_read(plan_path)
    premiere_result = plan.get("premiere_result")
    if not isinstance(premiere_result, dict):
        premiere_result = {}
    assets = manifest.get("assets", [])
    if not isinstance(assets, list):
        assets = []
    by_path = {
        str(item.get("path")): item
        for item in assets
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    targets = [plan_path, candidate_json, candidate_csv, validation_path, root / "project_versions.json"]
    result_path_value = premiere_result.get("report_path")
    if isinstance(result_path_value, str) and result_path_value:
        result_file = (root / result_path_value).resolve()
        try:
            result_file.relative_to(root.resolve())
        except ValueError:
            result_file = None
        if result_file is not None and result_file.is_file():
            targets.append(result_file)
    for path in targets:
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        fingerprint = file_fingerprint(path, full_hash=True)
        generated_at = (
            plan.get("generated_at")
            if path in {plan_path, candidate_json, candidate_csv, validation_path}
            else version_index.get("generated_at")
        )
        if isinstance(result_path_value, str) and relative == result_path_value:
            generated_at = plan.get("premiere_result", {}).get("saved_at")
        by_path[relative] = {
            **by_path.get(relative, {}),
            "path": relative,
            "size_bytes": fingerprint.get("size_bytes"),
            "sha256": fingerprint.get("sha256"),
            "generated_at": generated_at,
        }
    manifest["assets"] = sorted(by_path.values(), key=lambda item: str(item.get("path", "")).casefold())
    registered_pending_review = (
        premiere_result.get("registered") is True
        and premiere_result.get("validation_status") == "pending"
    )
    manifest["smart_silence_split"] = {
        "status": "review_pending" if registered_pending_review else plan.get("validation_status"),
        "analysis_status": plan.get("validation_status"),
        "validation_status": premiere_result.get("validation_status"),
        "plan_path": plan_path.relative_to(root).as_posix(),
        "candidate_json": candidate_json.relative_to(root).as_posix(),
        "candidate_csv": candidate_csv.relative_to(root).as_posix(),
        "result_path": premiere_result.get("report_path"),
        "review_project_path": premiere_result.get("registered_project_file") or premiere_result.get("review_project_path"),
        "review_sequence_name": premiere_result.get("review_sequence_name"),
        "generated_at": plan.get("generated_at"),
        "input_path": plan.get("input", {}).get("path"),
        "input_sha256": plan.get("input", {}).get("sha256"),
        "cue_count": plan.get("input", {}).get("cue_count"),
        "candidate_count": len(plan.get("analysis", {}).get("candidates", [])),
        "marker_count": premiere_result.get("marker_count", 0),
        "premiere_caption_item_count": premiere_result.get("premiere_caption_item_count"),
        "caption_count_matches_srt": premiere_result.get("caption_count_matches_srt"),
        "caption_count_delta": premiere_result.get("caption_count_delta"),
        "split_method": premiere_result.get("split_method"),
        "split_api_available": premiere_result.get("split_api_available"),
        "split_all_tracks_api_available": premiere_result.get("split_all_tracks_api_available"),
        "track_edit_api_availability": premiere_result.get("track_edit_api_availability"),
        "time_source": plan.get("analysis", {}).get("time_source"),
        "tail_added_seconds": plan.get("analysis", {}).get("tail_added_seconds", 0.0),
        "split_applied": bool(premiere_result.get("split_applied", False)),
        "split_status": premiere_result.get("split_status"),
        "candidate_split_count": premiere_result.get("candidate_split_count", 0),
        "cut_action_count": premiere_result.get("cut_action_count", 0),
        "auto_delete": False,
    }
    manifest["project_versions"] = {
        "index_path": "project_versions.json",
        "generated_at": version_index.get("generated_at"),
        "latest_working_version": version_index.get("latest_working_version"),
        "latest_verified_version": version_index.get("latest_verified_version"),
        "latest_export_version": version_index.get("latest_export_version"),
        "version_count": len(version_index.get("versions", [])),
    }
    atomic_write_json(manifest_path, manifest)
    refresh_codex_handoff_report(root)


def _command_silence_split(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    metadata_path = root / "project.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"VEA project.json이 없습니다: {metadata_path}")
    project_meta = _json_read(metadata_path)
    config = _load_config(args.config, root, getattr(args, "profile", None))
    settings = {
        "enabled": True,
        "mode": "split",
        "subtitle_tail_seconds": 0.5,
        "min_silence_gap_seconds": 0.8,
        "auto_delete": False,
        "preserve_original_project": True,
        "preserve_original_sequence": True,
        "preserve_all_audio_tracks": True,
        "preserve_subtitles": True,
        "preserve_video_effects": True,
        "split_on_frame_boundaries": True,
        "create_review_sequence": True,
        "generate_validation_report": True,
        "generate_silence_candidate_list": True,
        **config.get("smart_silence_split", {}),
    }
    if args.min_gap is not None:
        settings["min_silence_gap_seconds"] = args.min_gap
    if args.subtitle_tail is not None:
        settings["subtitle_tail_seconds"] = args.subtitle_tail
    if not settings["enabled"]:
        raise ValueError("설정에서 smart_silence_split.enabled=false입니다.")
    if settings.get("auto_delete"):
        raise ValueError("Smart Silence Split은 구간을 자동 삭제하지 않습니다. auto_delete는 false여야 합니다.")
    if settings.get("mode") != "split":
        raise ValueError("smart_silence_split.mode는 현재 split만 지원합니다.")
    required_preservation = (
        "preserve_original_project",
        "preserve_original_sequence",
        "preserve_all_audio_tracks",
        "preserve_subtitles",
        "preserve_video_effects",
        "split_on_frame_boundaries",
        "create_review_sequence",
        "generate_validation_report",
        "generate_silence_candidate_list",
    )
    disabled = [key for key in required_preservation if settings.get(key) is not True]
    if disabled:
        raise ValueError("필수 보존·검증 설정은 true여야 합니다: " + ", ".join(disabled))

    edit_map_path = root / "04_ROUGHCUT" / "edit_map.json"
    manifest_path = root / "manifest.json"
    edit_map = _json_read(edit_map_path) if edit_map_path.is_file() else {}
    manifest = _json_read(manifest_path) if manifest_path.is_file() else {}
    fps = _fps_from_project(root, manifest, edit_map, args.fps)
    verification_path = root / "10_REPORTS" / "premiere_subtitle_verification.json"
    verification = _json_read(verification_path) if verification_path.is_file() else {}

    if args.premiere_project:
        premiere_project = _resolve_project_input(root, args.premiere_project)
        relative = verification.get("project_path")
        same_verified_path = bool(relative) and same_path(
            premiere_project,
            _resolve_project_input(root, str(relative)),
        )
        saved = verification.get("save_evidence") or {}
        current = file_fingerprint(premiere_project, full_hash=True) if premiere_project.is_file() else {}
        verification_matches = (
            verification.get("status") == "verified"
            and same_verified_path
            and current.get("size_bytes") == saved.get("size_bytes")
            and current.get("sha256") == saved.get("sha256")
        )
    else:
        relative = verification.get("project_path")
        if verification.get("status") != "verified" or not relative:
            raise ValueError("Premiere 기준본 검증 리포트가 없습니다. --premiere-project와 --sequence-name을 지정하세요.")
        premiere_project = _resolve_project_input(root, relative)
        saved = verification.get("save_evidence") or {}
        current = file_fingerprint(premiere_project, full_hash=True) if premiere_project.is_file() else {}
        verification_matches = (
            premiere_project.is_file()
            and current.get("size_bytes") == saved.get("size_bytes")
            and current.get("sha256") == saved.get("sha256")
        )
        if not verification_matches:
            raise ValueError("Premiere 검증 리포트의 파일 해시가 현재 기준본과 다릅니다. 임의로 최신 파일을 선택하지 않았습니다.")
    if not premiere_project.is_file() or premiere_project.suffix.casefold() != ".prproj":
        raise FileNotFoundError(f"Premiere .prproj 기준본을 찾을 수 없습니다: {premiere_project}")
    try:
        premiere_project.relative_to(root)
    except ValueError as exc:
        raise ValueError("Premiere 기준 프로젝트는 VEA 프로젝트 폴더 안에 있어야 합니다.") from exc

    verified_reference = verification if verification_matches else {}
    sequence_name = args.sequence_name or verified_reference.get("sequence")
    if not sequence_name:
        raise ValueError("시퀀스 이름을 자동으로 확인하지 못했습니다. --sequence-name을 지정하세요.")
    caption_track = args.caption_track or (verified_reference.get("caption_track") or {}).get("name")

    if args.input_json:
        input_path = _resolve_project_input(root, args.input_json)
        cues = read_whisper_json(input_path)
        end_time_kind = "speech_end"
        cue_count = len(cues)
    else:
        default_srt = next(
            (
                path
                for path in (
                    root / "07_TRANSCRIPTS" / "transcript_reviewed.srt",
                    root / "07_TRANSCRIPTS" / "transcript.srt",
                    root / "07_TRANSCRIPTS" / "transcript_after_ai_review.srt",
                )
                if path.is_file()
            ),
            None,
        )
        input_path = _resolve_project_input(root, args.input_srt, default_srt)
        cues = read_srt(input_path)
        end_time_kind = "subtitle_end"
        cue_count = len(cues)

    sequence_duration: Fraction | None = Fraction(args.sequence_duration) if args.sequence_duration else None
    if sequence_duration is None and verified_reference.get("sequence_duration"):
        sequence_duration = _timecode_seconds(str(verified_reference["sequence_duration"]), fps)
    if sequence_duration is None and edit_map:
        frames = edit_map.get("duration_frames")
        if frames is None:
            frames = max((int(clip.get("timeline_end_frame", 0)) for clip in edit_map.get("clips", [])), default=0)
        if frames:
            sequence_duration = Fraction(int(frames), 1) / fps

    cut_frames: set[int] = set()
    for clip in edit_map.get("clips", []):
        for key in ("timeline_start_frame", "timeline_end_frame"):
            if clip.get(key) is not None:
                cut_frames.add(int(clip[key]))
    settings_signature = {
        "project_id": project_meta.get("project_id"),
        "premiere_project": str(premiere_project),
        "premiere_project_sha256": file_fingerprint(premiere_project, full_hash=True)["sha256"],
        "sequence_name": sequence_name,
        "fps": f"{fps.numerator}/{fps.denominator}",
        "sequence_duration_seconds": str(sequence_duration) if sequence_duration is not None else None,
        "input_path": str(input_path),
        "input_fingerprint": file_fingerprint(input_path, full_hash=True),
        "end_time_kind": end_time_kind,
        "settings": settings,
        "premiere_split_api": "SequenceEditor.createRazorTrackAction@27.1+",
    }
    signature = canonical_hash(settings_signature)
    analysis = analyze_caption_gaps(
        cues,
        fps=fps,
        min_gap_seconds=Fraction(str(settings["min_silence_gap_seconds"])),
        subtitle_tail_seconds=Fraction(str(settings["subtitle_tail_seconds"])),
        end_time_kind=end_time_kind,
        sequence_duration_seconds=sequence_duration,
        existing_cut_frames=cut_frames,
        edit_map=edit_map,
    )
    if verification_matches and verified_reference.get("cue_count") is not None and int(verified_reference["cue_count"]) != cue_count:
        analysis.update(
            {
                "status": "needs_review",
                "blocked": True,
                "candidate_count": 0,
                "candidates": [],
            }
        )
        analysis.setdefault("issues", []).append(
            {
                "code": "verified_caption_count_mismatch",
                "message": f"검증된 C1 자막 {verified_reference['cue_count']}개와 입력 자막 {cue_count}개가 다릅니다.",
            }
        )

    generated_at = now_kst().isoformat(timespec="seconds")
    report_dir = root / "10_REPORTS"
    report_dir.mkdir(parents=True, exist_ok=True)
    candidates_json = report_dir / "silence_candidates.json"
    candidates_csv = report_dir / "silence_candidates.csv"
    plan_path = report_dir / "silence_split_plan.json"
    validation_path = report_dir / "silence_split_validation.md"
    outputs = [candidates_json, candidates_csv, plan_path, validation_path]
    checkpoint = Checkpoint(root, project_id=project_meta.get("project_id"))
    if checkpoint.cached("silence_split_analysis", signature, outputs):
        index = refresh_project_versions(root)
        _update_silence_split_manifest(
            root,
            plan_path=plan_path,
            candidate_json=candidates_json,
            candidate_csv=candidates_csv,
            validation_path=validation_path,
            version_index=index,
        )
        print(f"무음 후보 분석은 기존 체크포인트에서 재사용했습니다: {candidates_json}")
        print(f"최신 작업 후보: {index.get('latest_working_version') or '없음'}")
        print(f"최신 검증본: {index.get('latest_verified_version') or '없음'}")
        return 0 if not analysis.get("blocked") else 2
    existing_outputs = [str(path) for path in outputs if path.exists()]
    if existing_outputs and not args.overwrite:
        raise FileExistsError(
            "Smart Silence Split 산출물이 이미 있습니다. 다른 프로젝트 사본을 쓰거나, 입력을 바꿔 갱신할 때만 "
            "--overwrite를 지정하세요: " + ", ".join(existing_outputs)
        )

    existing_boundaries = set(cut_frames)
    project_name = str(project_meta.get("title") or root.name)
    output_folder = root / "08_PREMIERE"
    suggested_filename = version_filename(project_name, "REVIEW", ".prproj", directory=output_folder)
    input_fp = file_fingerprint(input_path, full_hash=True)
    plan = {
        "schema_version": 1,
        "project_id": project_meta.get("project_id"),
        "project_name": project_name,
        "project_dir": str(root),
        "generated_at": generated_at,
        "input": {
            "path": str(input_path),
            "sha256": input_fp.get("sha256"),
            "cue_count": cue_count,
            "end_time_kind": end_time_kind,
            "time_policy": analysis.get("time_source"),
            "tail_added_seconds": analysis.get("tail_added_seconds", 0.0),
        },
        "premiere_project": {
            "path": str(premiere_project),
            "relative_path": premiere_project.relative_to(root).as_posix(),
            "sha256": settings_signature["premiere_project_sha256"],
            "verified_reference": verification_matches,
            "sequence_name": sequence_name,
            "caption_track_name": caption_track,
            "verified_caption_count": verified_reference.get("cue_count") if verification_matches else None,
            "sequence_duration_seconds": float(sequence_duration) if sequence_duration is not None else None,
        },
        "fps": analysis["fps"],
        "settings": settings,
        "analysis": analysis,
        "candidate_json": str(candidates_json),
        "candidate_csv": str(candidates_csv),
        "suggested_output_folder": str(output_folder),
        "suggested_output_filename": suggested_filename,
        "actions": {
            "requested_mode": "split",
            "implemented_mode": "split_with_review_marker_fallback",
            "create_review_sequence": bool(settings.get("create_review_sequence", True)),
            "split_supported_by_documented_premiere_uxp_api": True,
            "split_api": {
                "method": "SequenceEditor.createRazorTrackAction",
                "minimum_premiere_version": "27.1.0",
                "runtime_feature_detection": True,
                "unsupported_host_behavior": "review_markers_only",
                "track_policy": "explicit_video_and_optional_audio_tracks; linked_items_follow_video",
            },
            "auto_delete": False,
            "preserve_original_project": True,
            "preserve_original_sequence": True,
            "preserve_all_audio_tracks": True,
            "preserve_subtitles": True,
            "preserve_video_effects": True,
            "reason": "Razor API는 Premiere 27.1+에서 사용할 수 있습니다. 패널이 런타임 지원 여부를 확인하며 미지원 버전에서는 검토 마커만 추가합니다.",
        },
        "validation_status": "analysis_ready" if not analysis.get("blocked") else "needs_review",
    }
    payload = {
        **analysis,
        "project_id": project_meta.get("project_id"),
        "project_name": project_name,
        "generated_at": generated_at,
        "input_file": str(input_path),
        "input_sha256": input_fp.get("sha256"),
        "end_time_kind": end_time_kind,
        "sequence_name": sequence_name,
        "caption_track_name": caption_track,
        "premiere_project": str(premiere_project),
        "premiere_project_verified_reference": verification_matches,
        "settings_signature": signature,
        "split_application_status": "not_applied",
        "auto_delete": False,
    }
    lines = [
        "# Smart Silence Split 검증 보고서",
        "",
        f"- VEA 프로젝트: `{root}` ({project_meta.get('project_id') or 'ID 미기록'})",
        f"- Premiere 기준본: `{premiere_project.relative_to(root).as_posix()}`",
        f"- 기준본 검증 일치: {'예' if verification_matches else '아니요'}",
        f"- 시퀀스: {sequence_name}",
        f"- 입력 자막: `{input_path.relative_to(root).as_posix() if input_path.is_relative_to(root) else input_path}` ({cue_count}개)",
        f"- 시간 해석: {analysis.get('time_source')}",
        f"- 추가 자막 여유: {analysis.get('tail_added_seconds', 0.0):g}초",
        f"- FPS: {fps.numerator}/{fps.denominator}",
        f"- 최소 후보 간격: {analysis.get('minimum_gap_seconds', float(settings['min_silence_gap_seconds'])):g}초",
        f"- 자막 사이 후보: {sum(1 for item in analysis.get('candidates', []) if item.get('candidate_type') == 'inter_caption')}개",
        f"- 시퀀스 시작/끝 검토 후보: {sum(1 for item in analysis.get('candidates', []) if item.get('candidate_type') != 'inter_caption')}개",
        "- 실제 클립 분할: 미수행",
        "- 자동 삭제: 하지 않음",
        "- Premiere UXP 공개 API 분할 지원: `SequenceEditor.createRazorTrackAction`은 Premiere 27.1+부터 제공됩니다.",
        "- 패널은 런타임에 API를 확인합니다. 미지원 버전에서는 마커 전용 REVIEW 사본으로 후퇴하며 임의 명령을 호출하지 않습니다.",
        "",
        "## 후보 목록",
        "",
    ]
    if analysis.get("candidates"):
        for item in analysis["candidates"]:
            lines.append(
                f"- {item['candidate_id']}: {item['sequence_start']}–{item['sequence_end']}초, "
                f"{item['duration_seconds']:.3f}초 ({item['validation_status']})"
            )
    else:
        lines.append("후보가 없거나 입력 검증 때문에 계산을 보류했습니다.")
    if analysis.get("issues"):
        lines.extend(["", "## 확인 필요", ""])
        lines.extend(f"- {item.get('code', 'issue')}: {item.get('message', '')}" for item in analysis["issues"])
    lines.extend(
        [
            "",
            "## Premiere 처리 상태",
            "",
            f"- UXP 실행 계획: `{plan_path}`",
            f"- 제안 파일명: `{suggested_filename}`",
            "- Premiere에서 복제 시퀀스, 가능한 컷, 마커가 저장된 뒤 `vea project register`로 새 파일을 인덱스에 등록합니다.",
            "- 기존 .prproj, 시퀀스, 자막, 효과, 원본 영상·오디오는 변경하지 않았습니다.",
            "",
        ]
    )

    checkpoint.start("silence_split_analysis", signature, outputs)
    try:
        write_candidate_artifacts(payload, json_path=candidates_json, csv_path=candidates_csv)
        atomic_write_json(plan_path, plan)
        atomic_write_text(validation_path, "\n".join(lines), encoding="utf-8")
        checkpoint.complete(
            "silence_split_analysis",
            {
                "candidate_count": len(analysis.get("candidates", [])),
                "split_applied": False,
                "plan": str(plan_path.relative_to(root)),
            },
        )
    except Exception as exc:
        checkpoint.fail("silence_split_analysis", exc)
        raise

    index = refresh_project_versions(root)
    _update_silence_split_manifest(
        root,
        plan_path=plan_path,
        candidate_json=candidates_json,
        candidate_csv=candidates_csv,
        validation_path=validation_path,
        version_index=index,
    )
    print(f"무음 후보 JSON: {candidates_json}")
    print(f"무음 후보 CSV: {candidates_csv}")
    print(f"Premiere 검토 작업 계획: {plan_path}")
    print(f"검증 보고서: {validation_path}")
    print(
        f"후보 {len(analysis.get('candidates', []))}개 | "
        "분할 API 최소 Premiere 27.1 (실행 시 런타임 확인) | 분석 단계 분할 미적용 | 자동 삭제 안 함"
    )
    print(f"최신 작업 후보: {index.get('latest_working_version') or '없음'}")
    print(f"최신 검증본: {index.get('latest_verified_version') or '없음'}")
    return 2 if analysis.get("blocked") else 0


def _command_project_versions(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    action = args.project_action
    if action == "register":
        version_file = Path(args.file).expanduser()
        if not version_file.is_absolute():
            version_file = root / version_file
        record = register_project_version(
            root,
            version_file,
            stage=args.stage,
            source_version=args.source_version,
            validation_status=args.validation_status,
            notes=args.notes,
            set_current=args.set_current,
        )
        if version_file.suffix.casefold() == ".prproj":
            metadata_path = root / "project.json"
            if metadata_path.is_file():
                metadata = _json_read(metadata_path)
                metadata["latest_premiere_project"] = record["file_path"]
                metadata["progress_status"] = "premiere_review_pending"
                metadata["last_run_at"] = datetime.now(timezone.utc).isoformat()
                metadata["next_step"] = "Premiere에서 프로젝트를 열어 미디어·시퀀스·재생을 확인하고 검증 상태를 기록"
                atomic_write_json(metadata_path, metadata)
        silence_result = _attach_silence_review_result(root, version_file)
        print(f"프로젝트 버전을 등록했습니다: {record['file_path']} ({record['stage']}, {record['validation_status']})")
        if silence_result:
            if silence_result.get("split_applied"):
                print(
                    "Smart Silence Split 검토 결과 연결: "
                    f"마커 {silence_result['marker_count']}개, 완결 분할 후보 {silence_result.get('candidate_split_count', 0)}개"
                )
            else:
                print(
                    "Smart Silence Split 검토 결과 연결: "
                    f"마커 {silence_result['marker_count']}개, 분할 상태 {silence_result.get('split_status', 'unknown')}"
                )
            report_path_value = silence_result.get("report_path")
            review_path_value = silence_result.get("registered_project_file")
            if isinstance(report_path_value, str) and isinstance(review_path_value, str):
                report_file = root / report_path_value
                review_file = root / review_path_value
                checkpoint = Checkpoint(root, project_id=silence_result.get("project_id"))
                checkpoint.start(
                    "silence_split_review",
                    canonical_hash(
                        {
                            "result": file_fingerprint(report_file, full_hash=True),
                            "review_project": file_fingerprint(review_file, full_hash=True),
                        }
                    ),
                    [report_file, review_file],
                )
                checkpoint.complete(
                    "silence_split_review",
                    {
                        "status": silence_result.get("status"),
                        "result_path": report_path_value,
                        "review_project_path": review_path_value,
                        "review_sequence_name": silence_result.get("review_sequence_name"),
                        "candidate_count": silence_result.get("candidate_count"),
                        "marker_count": silence_result.get("marker_count"),
                        "split_applied": silence_result.get("split_applied"),
                        "split_status": silence_result.get("split_status"),
                        "caption_count_delta": silence_result.get("caption_count_delta"),
                        "validation_status": silence_result.get("validation_status"),
                    },
                )
            version_index = refresh_project_versions(root)
            _update_silence_split_manifest(
                root,
                plan_path=root / "10_REPORTS" / "silence_split_plan.json",
                candidate_json=root / "10_REPORTS" / "silence_candidates.json",
                candidate_csv=root / "10_REPORTS" / "silence_candidates.csv",
                validation_path=root / "10_REPORTS" / "silence_split_validation.md",
                version_index=version_index,
            )
        else:
            refresh_codex_handoff_report(root)
        return 0
    if action == "verify":
        results = verify_project_versions(root)
        failed = [item for item in results if item["status"] != "integrity_ok"]
        for item in results:
            print(f"{item['status']}: {item['file_path']} (Premiere 검증 상태: {item.get('validation_status', 'unknown')})")
        if not results:
            print("인덱스에 Premiere 프로젝트/XML 파일이 없습니다.")
        print("무결성 확인과 Premiere에서의 실제 호환성 검증은 별개입니다.")
        return 2 if failed else 0
    index = refresh_project_versions(root)
    if action == "versions":
        for item in sorted(index["versions"], key=lambda entry: entry.get("last_modified_at") or "", reverse=True):
            print(
                f"{item['last_modified_at'] or '시간 미상'} | {item['stage'] or 'UNKNOWN'} | "
                f"{item['validation_status']} | {item['file_path']}"
            )
        return 0
    if action == "latest":
        integrity_by_path = {
            item["file_path"]: item
            for item in verify_project_versions(root)
        }
        print(f"최신 작업 후보: {index.get('latest_working_version') or '없음'}")
        if index.get("latest_working_version"):
            match = next(item for item in index["versions"] if item["file_path"] == index["latest_working_version"])
            integrity = integrity_by_path.get(match["file_path"], {})
            print(
                f"  수정: {match.get('last_modified_at')} | Premiere 검증: {match.get('validation_status')}"
                f" | 파일 무결성: {integrity.get('status', 'unknown')}"
            )
            if integrity.get("status") != "integrity_ok":
                print(
                    f"  기록 크기/SHA-256: {match.get('file_size_bytes')} bytes / {match.get('file_hash')}"
                    f" | 현재 크기/SHA-256: {integrity.get('file_size_bytes', '확인 불가')} bytes / "
                    f"{integrity.get('file_hash', '확인 불가')}"
                )
        print(f"최신 자동 저장본: {index.get('latest_autosave_version') or '없음'}")
        if index.get("latest_autosave_version"):
            autosave_integrity = integrity_by_path.get(index["latest_autosave_version"], {})
            print(f"  파일 무결성: {autosave_integrity.get('status', 'unknown')}")
        print(f"최신 검증본: {index.get('latest_verified_version') or '없음'}")
        print(f"최신 내보내기: {index.get('latest_export_version') or '없음'}")
        if index.get("latest_verified_version"):
            match = next(item for item in index["versions"] if item["file_path"] == index["latest_verified_version"])
            integrity = integrity_by_path.get(match["file_path"], {})
            print(
                f"  수정: {match.get('last_modified_at')} | Premiere 검증: {match.get('validation_status')}"
                f" | 파일 무결성: {integrity.get('status', 'unknown')} | SHA-256: {match['file_hash']}"
            )
        return 0
    if action == "status":
        print(f"프로젝트: {index.get('project_name')} | ID: {index.get('project_id') or '미기록'}")
        print(f"상태: {index.get('status')}")
        print(f"생성 시각: {index.get('created_at') or '확인 불가'}")
        print(f"현재 작업본(명시 선택): {index.get('current_working_version') or '미선택'}")
        print(f"최신 작업 후보: {index.get('latest_working_version') or '없음'}")
        print(f"최신 검증본: {index.get('latest_verified_version') or '없음'}")
        print(f"최신 내보내기: {index.get('latest_export_version') or '없음'}")
        return 0
    if action == "open-latest":
        from .versioning import open_project_version

        relative = index.get("latest_verified_version") if args.verified else index.get("latest_working_version")
        if not relative:
            raise FileNotFoundError("열 프로젝트 버전을 찾지 못했습니다.")
        target = (root / relative).resolve()
        open_project_version(target)
        print(f"Premiere 프로젝트를 열도록 요청했습니다: {target}")
        return 0
    if action == "index":
        print(f"프로젝트 버전 인덱스: {root / 'project_versions.json'}")
        print(f"등록된 프로젝트 파일: {len(index['versions'])}개")
        return 0
    raise ValueError(f"지원하지 않는 프로젝트 버전 명령입니다: {action}")


def _attach_silence_review_result(root: Path, review_project: Path) -> dict[str, Any] | None:
    plan_path = root / "10_REPORTS" / "silence_split_plan.json"
    if not plan_path.is_file():
        return None
    plan = _json_read(plan_path)
    if plan.get("project_id") != (_json_read(root / "project.json").get("project_id")):
        return None
    if not review_project.is_file() or review_project.suffix.casefold() != ".prproj":
        return None
    expected_source = (plan.get("premiere_project") or {}).get("path")
    expected_count = len((plan.get("analysis") or {}).get("candidates") or [])
    if not isinstance(expected_source, str) or not expected_source:
        return None
    report_dir = root / "10_REPORTS"
    matches: list[dict[str, Any]] = []
    for result_path in report_dir.glob("silence_split_premiere_result_*.json"):
        try:
            result = _json_read(result_path)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            result.get("schema_version") == 1
            and result.get("status") == "saved_pending_reopen_review"
            and result.get("project_id") == plan.get("project_id")
            and result.get("project_openable_check") is True
            and isinstance(result.get("split_applied"), bool)
            and result.get("actual_mode") in {"split_with_markers", "review_markers_only"}
            and isinstance(result.get("split_status"), str)
            and result.get("auto_delete") is False
            and result.get("candidate_count") == expected_count
            and result.get("marker_count") == expected_count
            and same_path(str(result.get("source_project_path", "")), str(expected_source or ""))
            and same_path(str(result.get("review_project_path", "")), str(review_project))
        ):
            result["report_path"] = result_path.relative_to(root).as_posix()
            matches.append(result)
    if len(matches) != 1:
        return None
    result = matches[0]
    result["registered"] = True
    result["registered_project_file"] = review_project.relative_to(root).as_posix()
    result["validation_status"] = "pending"
    plan["premiere_result"] = result
    actions = plan.setdefault("actions", {})
    actions["review_markers_added"] = result["marker_count"]
    actions["split_applied"] = bool(result.get("split_applied"))
    actions["split_status"] = result.get("split_status")
    actions["split_method"] = result.get("split_method")
    actions["cut_action_count"] = int(result.get("cut_action_count") or 0)
    actions["candidate_split_count"] = int(result.get("candidate_split_count") or 0)
    actions["target_tracks"] = result.get("target_tracks") or []
    atomic_write_json(plan_path, plan)
    return result


def _command_report(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    refresh_project_versions(root)
    checkpoint_path = root / "checkpoint.json"
    if checkpoint_path.exists():
        checkpoint = _json_read(checkpoint_path)
        print(f"프로젝트 ID: {checkpoint.get('project_id')}")
        print(f"현재 단계: {checkpoint.get('current_stage') or '없음'}")
        for name, stage in checkpoint.get("stages", {}).items():
            print(f"  {name}: {stage.get('status')} {stage.get('error') or ''}")
    for relative in (
        "04_ROUGHCUT/roughcut.xml",
        "04_ROUGHCUT/edit_map.json",
        "05_AUDIO/roughcut_voice.wav",
        "manifest.json",
        "07_TRANSCRIPTS/transcript.srt",
    ):
        print(f"{'있음' if (root / relative).exists() else '없음'}: {relative}")
    report = root / "10_REPORTS" / "validation.md"
    if report.exists():
        print(f"검증 리포트: {report}")
    codex_report = refresh_codex_handoff_report(root)
    print(f"Codex 전달 보고서: {codex_report}")
    return 0


def _command_premiere_video_only_xml(args: argparse.Namespace) -> int:
    output = export_video_only_source_xml(
        args.input_xml,
        args.output,
        source_file_id=args.source_file_id,
    )
    print(f"영상 전용 원본 XML: {output}")
    print("시퀀스 오디오는 검증된 오디오 전용 sidecar 참조를 유지했습니다.")
    return 0


def _command_resume(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    request_path = root / "02_INSTRUCTIONS" / "request.json"
    if not request_path.is_file():
        raise FileNotFoundError("재개할 요청 정보가 없습니다. vea prepare부터 실행하세요.")
    request = _json_read(request_path)
    if args.transcribe:
        transcribe_args = argparse.Namespace(
            project_dir=str(root),
            audio=getattr(args, "audio", None),
            full_source=getattr(args, "full_source", False),
            audio_stream_index=getattr(args, "audio_stream_index", None),
            model=args.model,
            fallback_models=args.fallback_models,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            beam_size=args.beam_size,
            chunk_seconds=args.chunk_seconds,
            word_timestamps=args.word_timestamps,
            glossary=args.glossary,
            cpu_fallback=args.cpu_fallback,
            transcript_name=args.transcript_name,
            allow_non_windows=args.allow_non_windows,
            config=args.config or (str(root / request["config_file"]) if request.get("config_file") else None),
            profile=getattr(args, "profile", None),
        )
        return _command_transcribe(transcribe_args)
    prepare_args = argparse.Namespace(
        source=request["source"],
        instructions=None,
        instructions_file=str(root / request["instruction_file"]),
        preserve_client_request=True,
        request_instruction_file=request["instruction_file"],
        project_dir=str(root),
        title=request.get("title"),
        fps=request.get("fps"),
        include_source=bool(request.get("include_source", False)),
        hash_media=bool(args.hash_media or request.get("hash_media", False)),
        sample_rate=args.sample_rate,
        crossfade_ms=args.crossfade_ms,
        audio_streams=None,
        config=args.config or (str(root / request["config_file"]) if request.get("config_file") else None),
        profile=getattr(args, "profile", None),
        search_root=None,
    )
    return _command_prepare(prepare_args)


def _command_roughcut(args: argparse.Namespace) -> int:
    root = Path(args.project_dir).expanduser().resolve()
    request = _json_read(root / "02_INSTRUCTIONS" / "request.json")
    prepare_args = argparse.Namespace(
        source=request["source"],
        instructions=None,
        instructions_file=str(root / request["instruction_file"]),
        preserve_client_request=True,
        request_instruction_file=request["instruction_file"],
        project_dir=str(root),
        search_root=None,
        title=request.get("title"),
        fps=request.get("fps"),
        include_source=bool(request.get("include_source", False)),
        hash_media=bool(args.hash_media or request.get("hash_media", False)),
        sample_rate=None,
        crossfade_ms=None,
        audio_streams=None,
        config=(str(root / request["config_file"]) if request.get("config_file") else None),
        profile=getattr(args, "profile", None),
    )
    return _command_prepare(prepare_args)


def _command_doctor(args: argparse.Namespace) -> int:
    config = _load_config(getattr(args, "config", None), profile=getattr(args, "profile", None))
    environment = collect_environment(
        code_root=_code_root(),
        config=config,
        workspace_root=getattr(args, "video_workspace_root", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(environment, ensure_ascii=True, indent=2))
        return 0
    print(f"VEA {__version__} | Python {sys.version.split()[0]} | OS {sys.platform}")
    for binary in ("ffmpeg", "ffprobe"):
        try:
            path = require_binary(binary)
            print(f"{binary}: {path}")
        except Exception as exc:
            print(f"{binary}: 없음 ({exc})")
    try:
        import faster_whisper

        print(f"faster-whisper: 설치됨 ({getattr(faster_whisper, '__version__', 'version unknown')})")
    except ImportError:
        print("faster-whisper: 미설치 (Windows/macOS 전사용 선택 의존성)")
    try:
        ctranslate2 = __import__("ctranslate2")
    except ImportError:
        print("CTranslate2: 미설치 (faster-whisper 전사 의존성)")
    except Exception as exc:
        print(f"CTranslate2: import 실패 ({type(exc).__name__}: {exc})")
    else:
        print(f"CTranslate2: {getattr(ctranslate2, '__version__', 'version unknown')}")
        try:
            cuda_count = int(ctranslate2.get_cuda_device_count())
            print(f"CUDA 장치 수: {cuda_count}")
            if cuda_count:
                compute_types = sorted(ctranslate2.get_supported_compute_types("cuda"))
                print(f"CUDA 지원 정밀도: {', '.join(compute_types)}")
        except Exception as exc:
            print(f"CUDA/CTranslate2 런타임 검사 실패: {type(exc).__name__}: {exc}")
    try:
        nvidia_smi = require_binary("nvidia-smi")
    except Exception:
        print("NVIDIA 드라이버 정보: nvidia-smi를 찾지 못했습니다.")
    else:
        try:
            result = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=name,driver_version,memory.total,memory.free",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                print("NVIDIA GPU (name, driver, VRAM total/free):")
                for line in result.stdout.splitlines():
                    print(f"  {line.strip()}")
            else:
                print(f"NVIDIA 드라이버 조회 실패: {result.stderr.strip() or result.returncode}")
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"NVIDIA 드라이버 조회 실패: {type(exc).__name__}: {exc}")
    print(f"CPU 논리 프로세서: {environment['cpu']['logical_processors'] or '확인 불가'}")
    memory_bytes = environment["memory"].get("total_bytes")
    print(f"RAM: {memory_bytes / (1024 ** 3):.1f} GiB" if memory_bytes else "RAM: 확인 불가")
    print(f"전사 권장 장치: {environment['transcription']['recommended_device']}")
    workspace = environment["video_workspace"]
    if workspace.get("status") == "resolved":
        print(f"영상 프로젝트 루트: {workspace['projects_root']}")
    else:
        print("영상 프로젝트 루트: 미연결 — 프로젝트 생성 시 현재 폴더로 대체하지 않습니다.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vea", description="Cross-platform Video Editing Automation")
    parser.add_argument("--version", action="version", version=f"vea {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("doctor", help="로컬 실행 환경과 backend 선택 확인")
    command.add_argument("--config", help="TOML 설정 레이어 추가")
    command.add_argument("--video-workspace-root", help="명시적으로 확인할 영상 워크스페이스 루트")
    command.add_argument("--json", action="store_true", help="민감 인증정보 없이 환경 JSON 출력")
    command.set_defaults(handler=_command_doctor)

    command = sub.add_parser("config", help="공통·OS·로컬·프로젝트 설정 레이어 검사")
    config_sub = command.add_subparsers(dest="config_action", required=True)
    child = config_sub.add_parser("status", help="적용된 레이어와 설정 섹션 이름만 표시")
    child.add_argument("--config", help="명시적 작업 설정 파일")
    child.add_argument("--json", action="store_true")
    child.set_defaults(handler=_command_config_status)

    command = sub.add_parser("workspace", help="영상 데이터 워크스페이스 검색 및 manifest 관리")
    workspace_sub = command.add_subparsers(dest="workspace_action", required=True)
    child = workspace_sub.add_parser("resolve", help="명시 경로·로컬 설정·저장장치 manifest 순서로 검색")
    child.add_argument("--root", help="가장 우선하는 명시적 워크스페이스 루트")
    child.add_argument("--config", help="명시적 TOML 설정 파일")
    child.add_argument("--json", action="store_true")
    child.set_defaults(handler=_command_workspace_resolve)
    child = workspace_sub.add_parser("init", help="기존 워크스페이스에 휴대 가능한 manifest 작성 미리보기")
    child.add_argument("root", help="이미 존재하는 저장장치 루트")
    child.add_argument("--workspace-id", default="work-ssd")
    child.add_argument("--projects-path", default="VideoProjects")
    child.add_argument("--apply", action="store_true", help="기본 dry-run 대신 새 manifest를 실제 작성")
    child.set_defaults(handler=_command_workspace_init)

    command = sub.add_parser("inspect", help="FFprobe로 원본과 모든 오디오 스트림 분석")
    command.add_argument("source")
    command.add_argument("--output")
    command.add_argument("--previews", help="미리듣기 파일 출력 폴더")
    command.set_defaults(handler=_command_inspect)

    command = sub.add_parser("cfr-proxy", help="VFR 원본을 CFR MP4로 변환하고 시간 매핑 기록")
    command.add_argument("source")
    command.add_argument("--project-dir", required=True, help="proxy와 매핑 지도를 저장할 VEA 프로젝트")
    command.add_argument("--fps", help="출력 FPS, 기본은 FFprobe 평균 FPS")
    command.set_defaults(handler=_command_cfr_proxy)

    command = sub.add_parser("benchmark", help="단일 스레드로 영상 샘플 디코딩 성능 측정")
    command.add_argument("source")
    command.add_argument("--project-dir", required=True, help="JSON 결과를 저장할 VEA 프로젝트")
    command.add_argument("--seconds", type=float, default=60.0, help="디코딩할 샘플 길이(초, 기본 60)")
    command.set_defaults(handler=_command_benchmark)

    command = sub.add_parser("tracks", help="오디오 후보 확인 및 미리듣기 생성")
    command.add_argument("source")
    command.add_argument("--preview-dir")
    command.add_argument("--positions", help="미리듣기 시작 시각(초), 기본은 영상 전체에서 균등 샘플")
    command.add_argument("--preview-seconds", type=float, default=12.0)
    command.set_defaults(handler=_command_tracks)

    command = sub.add_parser("parse", help="의뢰문을 구조화된 JSON으로 파싱")
    inputs = command.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--file")
    inputs.add_argument("--text")
    command.add_argument("--source")
    command.add_argument("--fps")
    command.add_argument("--duration", help="원본 길이(초)")
    command.add_argument("--output", default="instructions.json")
    command.set_defaults(handler=_command_parse)

    command = sub.add_parser("select-audio", help="청취 확인을 마친 보이스 스트림 저장")
    command.add_argument("project_dir")
    command.add_argument("--streams", required=True, help="FFprobe 전체 스트림 인덱스. 예: 1,2")
    command.set_defaults(handler=_command_select_audio)

    def add_prepare_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--source", required=True)
        inputs = command.add_mutually_exclusive_group(required=True)
        inputs.add_argument("--instructions")
        inputs.add_argument("--instructions-file")
        command.add_argument("--project-dir")
        command.add_argument("--video-workspace-root", help="새 프로젝트를 저장할 외장 워크스페이스 루트")
        command.add_argument("--search-root", help="기존 프로젝트를 추가로 검색할 위치(새 프로젝트 저장 위치로 쓰지 않음)")
        command.add_argument("--title")
        command.add_argument("--fps")
        command.add_argument("--audio-streams", help="청취가 끝난 전체 오디오 스트림 인덱스. 예: 1,2")
        command.add_argument("--sample-rate", type=int)
        command.add_argument("--crossfade-ms", type=int)
        command.add_argument("--include-source", action="store_true", help="원본 영상의 사본을 프로젝트에 포함")
        command.add_argument("--hash-media", action="store_true", help="대용량 원본 전체 SHA-256 계산")
        command.add_argument("--config", help="TOML 설정 파일")

    command = sub.add_parser("receive", help="외주 원본과 의뢰문 접수 후 준비")
    add_prepare_arguments(command)
    command.set_defaults(handler=_command_prepare)

    command = sub.add_parser("prepare", help="원본 분석부터 러프컷 및 전달 준비")
    add_prepare_arguments(command)
    command.set_defaults(handler=_command_prepare)

    command = sub.add_parser("roughcut", help="저장한 요청을 다시 파싱해 러프컷 갱신")
    command.add_argument("project_dir")
    command.add_argument("--hash-media", action="store_true")
    command.set_defaults(handler=_command_roughcut)

    command = sub.add_parser("audio", help="선택한 오디오 스트림으로 러프컷 음성 생성")
    command.add_argument("project_dir")
    command.add_argument("--streams", help="전체 스트림 인덱스, 예: 1,2")
    command.add_argument("--sample-rate", type=int)
    command.add_argument("--crossfade-ms", type=int)
    command.add_argument("--hash-media", action="store_true")
    command.add_argument("--config", help="TOML 설정 파일")
    command.set_defaults(handler=_command_audio)

    command = sub.add_parser("handoff", help="전달 패키지 생성 및 검사")
    command.add_argument("project_dir")
    command.add_argument("--include-source", action="store_true")
    command.add_argument("--hash-media", action="store_true")
    command.set_defaults(handler=_command_handoff)

    command = sub.add_parser("verify", help="프로젝트 파일, XML, 음성 길이 검사")
    command.add_argument("project_dir")
    command.set_defaults(handler=_command_verify)

    command = sub.add_parser("relink", help="새 원본 경로 확인 후 프로젝트와 Premiere XML 갱신")
    command.add_argument("project_dir")
    command.add_argument("--source", required=True, help="재연결할 원본 파일")
    command.add_argument(
        "--confirm-structural-match",
        action="store_true",
        help="SHA-256이 없을 때, 기술 스트림 구성이 같다는 조건으로 원본을 연결(내용 동일성은 별도 확인 필요)",
    )
    command.set_defaults(handler=_command_relink)

    command = sub.add_parser("transcribe", help="Windows faster-whisper 청크 전사 및 재개")
    command.add_argument("project_dir")
    source_group = command.add_mutually_exclusive_group()
    source_group.add_argument("--audio", help="전사할 오디오 파일(기본: cut-aligned roughcut_voice.wav)")
    source_group.add_argument("--full-source", action="store_true", help="러프컷이 아닌 원본 전체의 오디오 스트림 전사")
    command.add_argument("--audio-stream-index", type=int, help="--full-source에 사용할 글로벌 오디오 스트림 인덱스")
    command.add_argument("--model")
    command.add_argument("--fallback-models")
    command.add_argument("--device")
    command.add_argument("--compute-type")
    command.add_argument("--language")
    command.add_argument("--beam-size", type=int)
    command.add_argument("--chunk-seconds", type=int)
    command.add_argument("--word-timestamps", action="store_true")
    command.add_argument("--glossary")
    command.add_argument("--transcript-name", help="오디오별 결과 파일/체크포인트 이름(기본: transcript 또는 입력 오디오 이름)")
    command.add_argument("--cpu-fallback", action="store_true")
    command.add_argument("--config", help="TOML 설정 파일")
    command.add_argument("--allow-non-windows", action="store_true", help=argparse.SUPPRESS)
    command.set_defaults(handler=_command_transcribe)

    command = sub.add_parser("subtitles", help="전사 JSON에서 SRT를 다시 만들고 검증")
    command.add_argument("transcript_json")
    command.add_argument("--output")
    command.add_argument("--max-chars", type=int, default=80)
    command.set_defaults(handler=_command_subtitles)

    command = sub.add_parser("silence-preview", help="무음 시작 0.5초 뒤에 끝나는 자막 미리보기 생성")
    command.add_argument("project_dir")
    command.add_argument("--input-srt", help="기본: 07_TRANSCRIPTS/transcript_after_ai_review.srt")
    command.add_argument("--audio", help="기본: 05_AUDIO/roughcut_voice.wav")
    command.add_argument("--output-srt", help="기본: 07_TRANSCRIPTS/transcript_after_ai_review_silence_preview.srt")
    command.add_argument("--report-json", help="기본: 10_REPORTS/transcript_silence_preview.json")
    command.add_argument("--report-md", help="기본: 10_REPORTS/transcript_silence_preview.md")
    command.add_argument("--threshold-db", type=float, default=-50.0)
    command.add_argument("--min-silence", type=float, default=0.5)
    command.add_argument("--tail-seconds", type=float, default=0.5)
    command.add_argument("--overwrite", action="store_true", help="기존 미리보기/리포트 결과를 교체")
    command.set_defaults(handler=_command_silence_preview)

    command = sub.add_parser("silence-split", help="자막 사이 공백 후보와 Premiere 검토 작업 계획 생성")
    command.add_argument("project_dir")
    source_group = command.add_mutually_exclusive_group()
    source_group.add_argument("--input-srt", help="기본: transcript_reviewed.srt, 없으면 transcript.srt")
    source_group.add_argument("--input-json", help="원시 Whisper JSON; speech_end에 subtitle_tail_seconds를 한 번 적용")
    command.add_argument("--premiere-project", help="VEA 프로젝트 안의 Premiere .prproj 기준본")
    command.add_argument("--sequence-name", help="시퀀스 이름; 검증 리포트에서 가져오지 못하면 필수")
    command.add_argument("--caption-track", help="선택한 캡션 트랙 이름")
    command.add_argument("--fps", help="프로젝트 FPS 재정의. 예: 30000/1001")
    command.add_argument("--sequence-duration", help="시퀀스 길이(초), 실제 프로젝트 확인값")
    command.add_argument("--min-gap", type=float, help="후보 최소 간격(초); 기본 0.8")
    command.add_argument("--subtitle-tail", type=float, help="speech_end JSON에만 적용하는 자막 여유(초); 기본 0.5")
    command.add_argument("--config", help="TOML 설정 파일")
    command.add_argument("--overwrite", action="store_true", help="입력/설정 변경 시 기존 분석 산출물을 갱신")
    command.set_defaults(handler=_command_silence_split)

    command = sub.add_parser("project", help="Premiere 프로젝트 버전 인덱스 조회 및 무결성 검사")
    project_sub = command.add_subparsers(dest="project_action", required=True)
    for action, help_text in (
        ("latest", "최신 작업 후보와 검증본 조회"),
        ("versions", "프로젝트 파일 버전 목록 조회"),
        ("status", "프로젝트 버전 상태 조회"),
        ("verify", "인덱스에 기록된 파일 해시 확인"),
        ("index", "프로젝트 버전 인덱스 갱신"),
        ("open-latest", "최신 작업 후보 또는 검증본 열기"),
    ):
        child = project_sub.add_parser(action, help=help_text)
        child.add_argument("project_dir", nargs="?", default=".")
        if action == "open-latest":
            child.add_argument("--verified", action="store_true", help="최신 작업 후보 대신 최신 검증본 열기")
        child.set_defaults(handler=_command_project_versions)
    child = project_sub.add_parser("register", help="Premiere에서 저장한 프로젝트 버전 인덱스 등록")
    child.add_argument("project_dir", nargs="?", default=".")
    child.add_argument("--file", required=True, help="프로젝트 내부의 .prproj 또는 .xml 파일")
    child.add_argument("--stage", required=True, choices=sorted(PROJECT_STAGES))
    child.add_argument("--source-version", help="기준 프로젝트 버전 경로")
    child.add_argument("--validation-status", choices=("pending", "failed", "unknown"), default="pending")
    child.add_argument("--notes")
    child.add_argument("--set-current", action="store_true", help="현재 작업 버전으로 기록")
    child.set_defaults(handler=_command_project_versions)

    command = sub.add_parser("report", help="프로젝트 체크포인트와 결과 요약")
    command.add_argument("project_dir")
    command.set_defaults(handler=_command_report)

    command = sub.add_parser(
        "premiere-video-only-xml",
        help="분리 오디오 sidecar를 쓰는 Premiere XML에서 원본 영상의 오디오 참조 제거",
    )
    command.add_argument("input_xml", help="sidecar 오디오 트랙이 이미 구성된 xmeml XML")
    command.add_argument("--output", required=True, help="새로 만들 영상 전용 XML 경로")
    command.add_argument("--source-file-id", default="source-1", help="원본 영상 XML 파일 ID")
    command.set_defaults(handler=_command_premiere_video_only_xml)

    command = sub.add_parser("resume", help="저장된 요청과 체크포인트에서 작업 재개")
    command.add_argument("project_dir")
    command.add_argument("--transcribe", action="store_true")
    source_group = command.add_mutually_exclusive_group()
    source_group.add_argument("--audio", help="--transcribe에서 사용할 오디오 파일(화자별 전사 재개 시 지정)")
    source_group.add_argument("--full-source", action="store_true", help="--transcribe에서 원본 전체의 오디오 스트림 전사")
    command.add_argument("--audio-stream-index", type=int, help="--full-source에 사용할 글로벌 오디오 스트림 인덱스")
    command.add_argument("--model")
    command.add_argument("--fallback-models")
    command.add_argument("--device")
    command.add_argument("--compute-type")
    command.add_argument("--language")
    command.add_argument("--beam-size", type=int)
    command.add_argument("--chunk-seconds", type=int)
    command.add_argument("--word-timestamps", action="store_true")
    command.add_argument("--glossary")
    command.add_argument("--transcript-name", help="오디오별 전사 결과 이름")
    command.add_argument("--cpu-fallback", action="store_true")
    command.add_argument("--allow-non-windows", action="store_true", help=argparse.SUPPRESS)
    command.add_argument("--hash-media", action="store_true")
    command.add_argument("--sample-rate", type=int)
    command.add_argument("--crossfade-ms", type=int)
    command.add_argument("--config", help="TOML 설정 파일")
    command.set_defaults(handler=_command_resume)
    def add_profile_option(command_parser: argparse.ArgumentParser) -> None:
        if "--profile" not in command_parser._option_string_actions:
            command_parser.add_argument(
                "--profile",
                choices=("development", "lightweight", "production", "validation"),
                help="실행 프로필 (공통·OS 설정 뒤, 로컬·프로젝트·명시 설정 앞에 적용)",
            )
        for action in command_parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    add_profile_option(child)

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                add_profile_option(child)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("작업이 중단되었습니다. 완료된 체크포인트는 보존했습니다.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"vea: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
