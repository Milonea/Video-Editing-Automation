from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from .checkpoint import atomic_write_json, canonical_hash, file_fingerprint
from .media import MediaInfo
from .models import FrameRate, TimelineClip
from .package import write_cuts_csv
from .paths import normalize_path, same_recorded_path


class RelinkError(ValueError):
    """The replacement source cannot safely be connected to this project."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RelinkError(f"필요한 프로젝트 JSON을 읽지 못했습니다: {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RelinkError(f"프로젝트 JSON 형식이 객체가 아닙니다: {path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _compare_media_layout(previous: dict[str, Any], replacement: MediaInfo) -> None:
    current = replacement.to_dict()
    old_duration = float(previous.get("duration", 0))
    new_duration = float(current["duration"])
    old_video = previous.get("video")
    new_video = current.get("video")
    fps = None
    if old_video and old_video.get("frame_rate"):
        try:
            fps = FrameRate.parse(old_video["frame_rate"])
        except (TypeError, ValueError, ZeroDivisionError):
            fps = None
    duration_tolerance = max(0.1, 1 / float(fps.value)) if fps else 0.1
    if abs(old_duration - new_duration) > duration_tolerance:
        raise RelinkError(f"원본 길이가 다릅니다: 기존 {old_duration:.3f}s, 새 파일 {new_duration:.3f}s")
    if bool(old_video) != bool(new_video):
        raise RelinkError("기존 원본과 새 파일의 영상 스트림 구성이 다릅니다.")
    if old_video and new_video:
        for key in ("codec", "width", "height", "pixel_format", "frame_rate"):
            if old_video.get(key) != new_video.get(key):
                raise RelinkError(f"영상 스트림 {key}가 다릅니다: {old_video.get(key)!r} != {new_video.get(key)!r}")
    old_audio = previous.get("audio_streams", [])
    new_audio = current.get("audio_streams", [])
    if len(old_audio) != len(new_audio):
        raise RelinkError(f"오디오 스트림 수가 다릅니다: 기존 {len(old_audio)}, 새 파일 {len(new_audio)}")
    for ordinal, (old, new) in enumerate(zip(old_audio, new_audio)):
        for key in ("codec", "channels", "channel_layout", "sample_rate"):
            if old.get(key) != new.get(key):
                raise RelinkError(f"오디오 순번 {ordinal + 1}의 {key}가 다릅니다.")
        if abs(float(old.get("start_time") or 0) - float(new.get("start_time") or 0)) > 0.05:
            raise RelinkError(f"오디오 순번 {ordinal + 1}의 시작 시각이 다릅니다.")


def _replace_recorded_source(value: Any, old_source: str, new_source: str) -> Any:
    if not isinstance(value, str):
        return value
    if same_recorded_path(value, old_source):
        return new_source
    return value


def _render_xml_path(path: Path, source: Path) -> bytes:
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise RelinkError(f"Premiere XML을 읽지 못해 재연결을 중단했습니다: {exc}") from exc
    root = tree.getroot()
    path_nodes = root.findall(".//file/pathurl")
    if not path_nodes:
        raise RelinkError("roughcut.xml에 원본 pathurl이 없어 자동 재연결할 수 없습니다.")
    for node in path_nodes:
        node.text = source.as_uri()
    for node in root.findall(".//file/name"):
        node.text = source.name
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.relink.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def relink_project(
    project_dir: str | Path,
    replacement: MediaInfo,
    confirm_structural_match: bool = False,
) -> dict[str, Any]:
    """Update source references after verifying identity or an explicit layout match."""
    root = Path(project_dir).expanduser().resolve()
    source = Path(normalize_path(replacement.path))
    if not source.is_file():
        raise RelinkError("새 원본 파일이 존재하지 않습니다.")
    project_path = root / "project.json"
    info_path = root / "03_ANALYSIS" / "media_info.json"
    tracks_path = root / "03_ANALYSIS" / "tracks.json"
    map_path = root / "04_ROUGHCUT" / "edit_map.json"
    request_path = root / "02_INSTRUCTIONS" / "request.json"
    required = (project_path, info_path, tracks_path, map_path, request_path, root / "04_ROUGHCUT" / "roughcut.xml")
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise RelinkError(f"프로젝트에 재연결 필수 파일이 없습니다: {', '.join(missing)}")

    metadata = _read_json(project_path)
    old_source = metadata.get("source_file")
    source_fingerprint = metadata.get("source_fingerprint")
    if not isinstance(old_source, str) or not isinstance(source_fingerprint, dict):
        raise RelinkError("project.json에 기존 원본 경로 또는 원본 지문이 없습니다.")
    if same_recorded_path(old_source, str(source)):
        raise RelinkError("새 원본 경로가 이미 프로젝트에 연결되어 있습니다.")
    xml_path = root / "04_ROUGHCUT" / "roughcut.xml"
    xml_payload = _render_xml_path(xml_path, source)

    previous_media = _read_json(info_path)
    _compare_media_layout(previous_media, replacement)
    previous_sha = source_fingerprint.get("sha256")
    replacement_fingerprint = file_fingerprint(source, full_hash=bool(previous_sha))
    match = "sha256_verified"
    if previous_sha:
        if replacement_fingerprint.get("sha256") != previous_sha:
            raise RelinkError("새 원본 SHA-256이 저장된 원본과 다릅니다. 프로젝트 연결은 변경하지 않았습니다.")
    else:
        manifest_path = root / "manifest.json"
        copied_path = None
        if manifest_path.is_file():
            try:
                copied_to_project = json.loads(manifest_path.read_text(encoding="utf-8")).get("source", {}).get("copied_to_project")
                if copied_to_project:
                    copied_path = (root / copied_to_project).resolve()
                    copied_path.relative_to(root)
            except (OSError, json.JSONDecodeError, ValueError):
                copied_path = None
        if copied_path and copied_path.is_file() and _sha256(copied_path) == _sha256(source):
            replacement_fingerprint = file_fingerprint(source, full_hash=True)
            match = "sha256_verified_against_package_copy"
        else:
            if not confirm_structural_match:
                raise RelinkError(
                    "저장된 SHA-256이 없어 파일 내용 동일성을 확인할 수 없습니다. 기술 구성은 일치합니다. "
                    "동일한 원본이라고 확인한 경우에만 --confirm-structural-match를 지정하세요."
                )
            match = "technical_signature_only_user_confirmed"

    old_tracks = _read_json(tracks_path)
    new_media_dict = replacement.to_dict()
    old_audio = old_tracks.get("audio_streams", [])
    new_audio = [stream.to_dict() for stream in replacement.audio_streams]
    old_global_to_ordinal = {int(item["global_index"]): int(item["audio_ordinal"]) for item in old_audio}
    new_ordinal_to_global = {int(item["audio_ordinal"]): int(item["global_index"]) for item in new_audio}
    selection_path = root / "03_ANALYSIS" / "voice_selection.json"
    selection = _read_json(selection_path) if selection_path.is_file() else None
    if selection:
        try:
            selection["selected_global_stream_indexes"] = [
                new_ordinal_to_global[old_global_to_ordinal[int(index)]]
                for index in selection.get("selected_global_stream_indexes", [])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise RelinkError("선택한 보이스 스트림을 새 원본에서 대응시킬 수 없습니다.") from exc
        selection["track_signature"] = canonical_hash(new_audio)
        selection["source_fingerprint"] = replacement_fingerprint

    instructions_path = root / "03_ANALYSIS" / "instructions.json"
    instructions = _read_json(instructions_path) if instructions_path.is_file() else None
    if instructions:
        instructions["source_file"] = _replace_recorded_source(instructions.get("source_file"), old_source, str(source))
        for edit in instructions.get("edits", []):
            edit["source_file"] = _replace_recorded_source(edit.get("source_file"), old_source, str(source))

    edit_map = _read_json(map_path)
    for clip in edit_map.get("clips", []):
        clip["source_file"] = str(source)
    edit_map["source_fingerprint"] = replacement_fingerprint
    clips = []
    for clip in edit_map.get("clips", []):
        clips.append(
            TimelineClip(
                source_file=str(source),
                source_in_frame=int(clip["source_in_frame"]),
                source_out_frame=int(clip["source_out_frame"]),
                timeline_start_frame=int(clip["timeline_start_frame"]),
                timeline_end_frame=int(clip["timeline_end_frame"]),
                source_in_seconds=Fraction(str(clip["source_in_seconds"])),
                source_out_seconds=Fraction(str(clip["source_out_seconds"])),
                label=str(clip.get("label", "")),
                notes=str(clip.get("notes", "")),
                ordering=int(clip.get("ordering", 0)),
                mute_audio=bool(clip.get("mute_audio", False)),
            )
        )
    fps_data = edit_map.get("fps", {})
    fps = FrameRate.parse(Fraction(int(fps_data["numerator"]), int(fps_data["denominator"])))

    metadata["source_file"] = normalize_path(source)
    metadata["source_fingerprint"] = replacement_fingerprint
    metadata["source_relink"] = {"match": match, "relinked_at": datetime.now(timezone.utc).isoformat()}
    conversion_path = root / "03_ANALYSIS" / "cfr_time_map.json"
    conversion_map = _read_json(conversion_path) if conversion_path.is_file() else None
    if conversion_map is not None:
        conversion_map["proxy_path"] = str(source)
        conversion_map["proxy_fingerprint"] = replacement_fingerprint
    request = _read_json(request_path)
    request["source"] = str(source)
    previous_media = new_media_dict
    old_tracks.update({"source": str(source), "source_fingerprint": replacement_fingerprint, "audio_streams": new_audio})
    atomic_write_json(project_path, metadata)
    atomic_write_json(request_path, request)
    atomic_write_json(info_path, previous_media)
    atomic_write_json(tracks_path, old_tracks)
    atomic_write_json(map_path, edit_map)
    if conversion_map is not None:
        atomic_write_json(conversion_path, conversion_map)
    if instructions:
        atomic_write_json(instructions_path, instructions)
    if selection:
        atomic_write_json(selection_path, selection)
    _atomic_write_bytes(xml_path, xml_payload)
    write_cuts_csv(root / "04_ROUGHCUT" / "cuts.csv", clips, fps)
    return {"match": match, "source": str(source), "source_fingerprint": replacement_fingerprint}
