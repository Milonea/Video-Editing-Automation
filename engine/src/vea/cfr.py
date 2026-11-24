from __future__ import annotations

import os
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from .checkpoint import atomic_write_json, file_fingerprint
from .disk_space import disk_space_message, disk_space_report
from .media import MediaToolError, probe_media, require_binary
from .models import FrameRate


def cfr_sidecar_path(proxy_path: str | Path) -> Path:
    proxy = Path(proxy_path)
    return proxy.with_suffix(proxy.suffix + ".vea-cfr-map.json")


def _estimate_proxy_bytes(duration_seconds: float, audio_stream_count: int) -> int:
    # The video encoder is rate-capped at 6 Mb/s; reserve 10% for container
    # overhead and audio tracks (each AAC track is capped near 192 kb/s).
    video_bytes_per_second = 6_000_000 / 8
    audio_bytes_per_second = max(0, audio_stream_count) * 192_000 / 8
    return int((video_bytes_per_second + audio_bytes_per_second) * duration_seconds * 1.1) + 32 * 1024**2


def create_cfr_proxy(
    source_path: str | Path,
    output_path: str | Path | None = None,
    fps: str | int | float | Fraction | None = None,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Any]:
    """Create an editable CFR proxy with all audio streams and a time map."""
    source = Path(source_path).expanduser().resolve()
    source_media = probe_media(source)
    if not source_media.video:
        raise ValueError("CFR 변환에는 영상 스트림이 필요합니다.")
    chosen_rate = FrameRate.parse(fps) if fps is not None else FrameRate.parse(
        source_media.video.get("avg_frame_rate") or source_media.video.get("r_frame_rate")
    )
    if output_path is None:
        rate_label = f"{chosen_rate.value.numerator}-{chosen_rate.value.denominator}"
        output = source.with_name(f"{source.stem}_cfr_{rate_label}.mp4")
    else:
        output = Path(output_path).expanduser().resolve()
    if output == source:
        raise ValueError("CFR 출력 경로는 원본과 달라야 합니다.")
    if output.suffix.casefold() != ".mp4":
        raise ValueError("CFR proxy 출력 확장자는 .mp4여야 합니다.")
    if output.exists():
        raise FileExistsError(f"기존 파일을 덮어쓰지 않았습니다: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    estimate = {"cfr_proxy": _estimate_proxy_bytes(source_media.duration, len(source_media.audio_streams))}
    report = disk_space_report(output.parent, estimate)
    print(disk_space_message(report))
    if not report["sufficient"]:
        raise RuntimeError("CFR proxy를 만들 디스크 공간이 부족합니다. 다른 볼륨을 선택하거나 공간을 확보하세요.")

    binary = require_binary(ffmpeg)
    temporary = output.with_name(f".{output.stem}.part{output.suffix}")
    filter_rate = f"{chosen_rate.value.numerator}/{chosen_rate.value.denominator}"
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        "1",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        f"setpts=PTS-STARTPTS,fps=fps={filter_rate}:round=near",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        "6000k",
        "-maxrate",
        "6000k",
        "-threads:v",
        "1",
        "-bufsize",
        "12000k",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-fps_mode",
        "cfr",
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        temporary.unlink(missing_ok=True)
        raise MediaToolError(f"CFR proxy 생성 실패: {result.stderr.strip()}")
    try:
        proxy_media = probe_media(temporary)
        if not proxy_media.video:
            raise MediaToolError("CFR proxy에 영상 스트림이 없습니다.")
        proxy_rate = FrameRate.parse(proxy_media.video.get("avg_frame_rate") or proxy_media.video.get("frame_rate"))
        if proxy_rate.value != chosen_rate.value or proxy_media.video.get("is_vfr_heuristic"):
            raise MediaToolError(
                f"CFR 출력 FPS 검증 실패: 요청 {chosen_rate.value}, FFprobe {proxy_rate.value}"
            )
        if len(proxy_media.audio_streams) != len(source_media.audio_streams):
            raise MediaToolError("CFR proxy의 오디오 스트림 수가 원본과 다릅니다.")
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    sidecar = cfr_sidecar_path(output)
    mapping = {
        "schema_version": 1,
        "conversion": "ffmpeg-setpts-fps-cfr",
        "source_path": str(source),
        "source_fingerprint": file_fingerprint(source),
        "proxy_path": str(output),
        "proxy_fingerprint": file_fingerprint(output),
        "source_duration_seconds": source_media.duration,
        "proxy_duration_seconds": proxy_media.duration,
        "source_start_time_seconds": source_media.video.get("start_time", 0.0),
        "proxy_start_time_seconds": proxy_media.video.get("start_time", 0.0),
        "fps": chosen_rate.to_json(),
        "source_time_to_proxy_frame": {
            "formula": "round_fraction(source_elapsed_seconds * fps)",
            "rounding": "nearest frame; ties away from zero",
            "time_origin": "first decoded video frame is elapsed time zero",
            "inverse_formula": "proxy_elapsed_seconds = frame_index / fps",
        },
        "audio_policy": "all source audio streams mapped and encoded as AAC at 192 kb/s per stream",
        "ffmpeg": "setpts=PTS-STARTPTS,fps=<fps>:round=near",
    }
    atomic_write_json(sidecar, mapping)
    return {"proxy": output, "sidecar": sidecar, "mapping": mapping}
