from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from typing import Any

from .media import MediaInfo
from .models import FrameRate, TimelineClip
from .timecode import seconds_to_frames


def _rate_element(parent: ET.Element, fps: FrameRate) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(fps.nominal)
    ET.SubElement(rate, "ntsc").text = "TRUE" if fps.value.denominator != 1 else "FALSE"


def _file_element(parent: ET.Element, media: MediaInfo, file_id: str, fps: FrameRate, include_source_info: bool) -> None:
    file_node = ET.SubElement(parent, "file", {"id": file_id})
    if not include_source_info:
        return
    ET.SubElement(file_node, "name").text = Path(media.path).name
    ET.SubElement(file_node, "pathurl").text = Path(media.path).resolve().as_uri()
    ET.SubElement(file_node, "duration").text = str(
        max(1, seconds_to_frames(Fraction(str(media.duration)), fps))
    )
    _rate_element(file_node, fps)
    media_node = ET.SubElement(file_node, "media")
    if media.video:
        video = ET.SubElement(media_node, "video")
        sample = ET.SubElement(video, "samplecharacteristics")
        ET.SubElement(sample, "width").text = str(media.video.get("width") or 0)
        ET.SubElement(sample, "height").text = str(media.video.get("height") or 0)
    audio = ET.SubElement(media_node, "audio")
    for stream in media.audio_streams:
        track = ET.SubElement(audio, "track")
        sample = ET.SubElement(track, "samplecharacteristics")
        if stream.sample_rate:
            ET.SubElement(sample, "samplerate").text = str(stream.sample_rate)
        ET.SubElement(track, "channelcount").text = str(stream.channels or 2)


def _clip_item(
    track: ET.Element,
    media: MediaInfo,
    clip: TimelineClip,
    fps: FrameRate,
    item_id: str,
    file_id: str,
    audio_stream: Any | None = None,
    include_source_info: bool = False,
) -> ET.Element:
    item = ET.SubElement(track, "clipitem", {"id": item_id})
    ET.SubElement(item, "masterclipid").text = "master-1"
    _rate_element(item, fps)
    ET.SubElement(item, "name").text = clip.label or Path(media.path).name
    ET.SubElement(item, "duration").text = str(clip.duration_frames)
    ET.SubElement(item, "start").text = str(clip.timeline_start_frame)
    ET.SubElement(item, "end").text = str(clip.timeline_end_frame)
    ET.SubElement(item, "in").text = str(clip.source_in_frame)
    ET.SubElement(item, "out").text = str(clip.source_out_frame)
    ET.SubElement(item, "enabled").text = "FALSE" if audio_stream is not None and clip.mute_audio else "TRUE"
    ET.SubElement(item, "anamorphic").text = "FALSE"
    ET.SubElement(item, "alphatype").text = "none"
    ET.SubElement(item, "pixelaspectratio").text = "square"
    if clip.notes:
        marker = ET.SubElement(item, "marker")
        ET.SubElement(marker, "name").text = "편집 메모"
        ET.SubElement(marker, "comment").text = clip.notes
    if audio_stream is not None:
        source_track = ET.SubElement(item, "sourcetrack")
        ET.SubElement(source_track, "mediatype").text = "audio"
        ET.SubElement(source_track, "trackindex").text = str(audio_stream.audio_ordinal + 1)
    _file_element(item, media, file_id, fps, include_source_info)
    return item


def _link_clipitem(item: ET.Element, clip_index: int, audio_track_count: int) -> None:
    """Link one video edit to the matching source-audio edits in the sequence."""
    insert_index = next((i for i, child in enumerate(item) if child.tag == "file"), len(item))
    self_link = ET.Element("link")
    ET.SubElement(self_link, "mediatype").text = "video"
    ET.SubElement(self_link, "trackindex").text = "1"
    ET.SubElement(self_link, "clipindex").text = str(clip_index)
    item.insert(insert_index, self_link)
    insert_index += 1
    for audio_track_index in range(1, audio_track_count + 1):
        link = ET.Element("link")
        ET.SubElement(link, "mediatype").text = "audio"
        ET.SubElement(link, "trackindex").text = str(audio_track_index)
        ET.SubElement(link, "clipindex").text = str(clip_index)
        ET.SubElement(link, "groupindex").text = str(audio_track_index)
        item.insert(insert_index, link)
        insert_index += 1


def export_fcp7_xml(
    output_path: str | Path,
    media: MediaInfo,
    clips: list[TimelineClip],
    fps: FrameRate,
    sequence_name: str = "VEA Roughcut",
    enabled_audio_global_indexes: set[int] | None = None,
) -> Path:
    """Write an editable Final Cut Pro 7 XML (xmeml) sequence.

    Premiere Pro import compatibility still requires validation in the target app.
    """
    if not media.video:
        raise ValueError("FCP7 XML 내보내기에는 영상 스트림이 필요합니다.")
    root = ET.Element("xmeml", {"version": "5"})
    sequence = ET.SubElement(root, "sequence", {"id": "sequence-1"})
    _rate_element(sequence, fps)
    ET.SubElement(sequence, "name").text = sequence_name
    duration_frames = clips[-1].timeline_end_frame if clips else 0
    ET.SubElement(sequence, "duration").text = str(duration_frames)
    timecode = ET.SubElement(sequence, "timecode")
    _rate_element(timecode, fps)
    ET.SubElement(timecode, "string").text = "00:00:00:00"
    ET.SubElement(timecode, "frame").text = "0"
    ET.SubElement(timecode, "displayformat").text = "NDF"

    media_node = ET.SubElement(sequence, "media")
    video = ET.SubElement(media_node, "video")
    video_format = ET.SubElement(video, "format")
    video_sample = ET.SubElement(video_format, "samplecharacteristics")
    ET.SubElement(video_sample, "width").text = str(media.video.get("width") or 0)
    ET.SubElement(video_sample, "height").text = str(media.video.get("height") or 0)
    ET.SubElement(video_sample, "anamorphic").text = "FALSE"
    ET.SubElement(video_sample, "pixelaspectratio").text = "square"
    ET.SubElement(video_sample, "fielddominance").text = "none"
    _rate_element(video_sample, fps)
    video_track = ET.SubElement(video, "track")
    ET.SubElement(video_track, "enabled").text = "TRUE"
    ET.SubElement(video_track, "locked").text = "FALSE"
    for index, clip in enumerate(clips, 1):
        video_clip_id = f"video-clip-{index}"
        video_item = _clip_item(
            video_track,
            media,
            clip,
            fps,
            video_clip_id,
            "source-1",
            include_source_info=index == 1,
        )
        _link_clipitem(
            video_item,
            index,
            len(media.audio_streams),
        )

    audio = ET.SubElement(media_node, "audio")
    audio_format = ET.SubElement(audio, "format")
    audio_sample = ET.SubElement(audio_format, "samplecharacteristics")
    sample_rates = [stream.sample_rate for stream in media.audio_streams if stream.sample_rate]
    if sample_rates:
        ET.SubElement(audio_sample, "samplerate").text = str(sample_rates[0])
    outputs = ET.SubElement(audio, "outputs")
    output_group = ET.SubElement(outputs, "group")
    ET.SubElement(output_group, "index").text = "1"
    ET.SubElement(output_group, "numchannels").text = "2"
    for channel_index in (1, 2):
        channel = ET.SubElement(output_group, "channel")
        ET.SubElement(channel, "index").text = str(channel_index)
    enabled_audio_global_indexes = enabled_audio_global_indexes or set()
    for stream in media.audio_streams:
        track = ET.SubElement(audio, "track")
        ET.SubElement(track, "enabled").text = (
            "TRUE" if stream.global_index in enabled_audio_global_indexes else "FALSE"
        )
        ET.SubElement(track, "locked").text = "FALSE"
        for index, clip in enumerate(clips, 1):
            _clip_item(
                track,
                media,
                clip,
                fps,
                f"audio-{stream.audio_ordinal}-clip-{index}",
                "source-1",
                audio_stream=stream,
            )
    ET.indent(root, space="  ")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def export_video_only_source_xml(
    input_path: str | Path,
    output_path: str | Path,
    source_file_id: str = "source-1",
) -> Path:
    """Write a derived XMEML where a sidecar-split source is video-only.

    This is intended for sequences whose audio tracks already reference separate,
    audio-only sidecar files. It refuses to remove source audio when sequence
    audio clips still reference the same source file.
    """
    source = Path(input_path).expanduser().resolve()
    target = Path(output_path).expanduser()
    if source == target.resolve():
        raise ValueError("입력 XML을 덮어쓰지 않도록 출력 경로를 별도로 지정하세요.")

    root = ET.parse(source).getroot()
    if root.tag != "xmeml":
        raise ValueError("Final Cut Pro 7 XML(xmeml) 파일이 아닙니다.")

    sequence = root.find("./sequence")
    if sequence is None:
        raise ValueError("XML에 sequence가 없습니다.")

    definitions = [
        node
        for node in root.iter("file")
        if node.get("id") == source_file_id
        and node.find("name") is not None
        and node.find("media") is not None
    ]
    if len(definitions) != 1:
        raise ValueError(
            f"{source_file_id!r} 전체 정의를 하나 찾아야 합니다. 발견: {len(definitions)}"
        )
    source_definition = definitions[0]
    source_media = source_definition.find("media")
    if source_media is None or source_media.find("video") is None:
        raise ValueError(f"{source_file_id!r}에 영상 스트림이 없습니다.")
    source_audio = source_media.find("audio")
    if source_audio is None:
        raise ValueError(f"{source_file_id!r}은 이미 오디오 없는 영상 소스입니다.")

    audio_tracks = sequence.findall("./media/audio/track")
    if not audio_tracks:
        raise ValueError("시퀀스에 오디오 트랙이 없어 sidecar 분리를 확인할 수 없습니다.")

    sequence_audio_ids: set[str] = set()
    for track in audio_tracks:
        for clip_item in track.iter("clipitem"):
            file_ref = clip_item.find("file")
            if file_ref is not None and file_ref.get("id"):
                sequence_audio_ids.add(file_ref.get("id", ""))
    sequence_audio_ids.discard("")
    if not sequence_audio_ids:
        raise ValueError("시퀀스 오디오 트랙의 미디어 참조를 찾지 못했습니다.")
    if source_file_id in sequence_audio_ids:
        raise ValueError(
            "시퀀스 오디오가 원본 파일을 직접 참조합니다. 오디오를 제거하지 않았습니다."
        )

    for file_id in sorted(sequence_audio_ids):
        sidecar_defs = [
            node
            for node in root.iter("file")
            if node.get("id") == file_id
            and node.find("name") is not None
            and node.find("media") is not None
        ]
        if len(sidecar_defs) != 1:
            raise ValueError(
                f"오디오 sidecar {file_id!r} 전체 정의가 하나가 아닙니다: {len(sidecar_defs)}"
            )
        sidecar_media = sidecar_defs[0].find("media")
        if (
            sidecar_media is None
            or sidecar_media.find("audio") is None
            or sidecar_media.find("video") is not None
        ):
            raise ValueError(f"{file_id!r}은 오디오 전용 sidecar가 아닙니다.")

    source_media.remove(source_audio)
    ET.indent(root, space="  ")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target
