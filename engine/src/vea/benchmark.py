from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # Windows
    resource = None  # type: ignore[assignment]

from .checkpoint import atomic_write_json, file_fingerprint
from .media import MediaToolError, probe_media, require_binary


def _child_peak_ram_mb() -> float | None:
    if resource is None:
        return None


def _sample_process_rss_mb(pid: int) -> float | None:
    if sys.platform not in {"darwin", "linux", "linux2"}:
        return None
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode:
            return None
        return int(result.stdout.strip()) / 1024
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _read_stream(stream: Any, collected: list[str]) -> None:
    for line in stream:
        collected.append(line)
    try:
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    except (AttributeError, OSError, ValueError):
        return None


def benchmark_media(
    source_path: str | Path,
    sample_seconds: float = 60.0,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Any]:
    """Decode a bounded video sample with one FFmpeg thread and discard frames."""
    if sample_seconds <= 0:
        raise ValueError("sample_seconds는 양수여야 합니다.")
    source = Path(source_path).expanduser().resolve()
    media = probe_media(source)
    if not media.video:
        raise ValueError("벤치마크에는 영상 스트림이 필요합니다.")
    duration = min(float(sample_seconds), media.duration)
    if duration <= 0:
        raise ValueError("벤치마크할 미디어 길이가 0초입니다.")
    binary = require_binary(ffmpeg)
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-ss",
        "0",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-t",
        f"{duration:.6f}",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "null",
        "-",
    ]
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_reader = threading.Thread(target=_read_stream, args=(process.stdout, stdout_lines), daemon=True)
    stderr_reader = threading.Thread(target=_read_stream, args=(process.stderr, stderr_lines), daemon=True)
    stdout_reader.start()
    stderr_reader.start()
    peak_ram_mb: float | None = None
    while process.poll() is None:
        sampled = _sample_process_rss_mb(process.pid)
        if sampled is not None:
            peak_ram_mb = max(peak_ram_mb or 0, sampled)
        time.sleep(1.0)
    stdout_reader.join()
    stderr_reader.join()
    elapsed = time.perf_counter() - started
    if process.returncode:
        raise MediaToolError(f"영상 샘플 벤치마크 실패: {''.join(stderr_lines).strip()}")
    progress = "".join(stdout_lines)
    frame_count = 0
    for line in progress.splitlines():
        if line.startswith("frame="):
            try:
                frame_count = max(frame_count, int(line.partition("=")[2]))
            except ValueError:
                continue
    return {
        "source": file_fingerprint(source),
        "source_duration_seconds": media.duration,
        "sample_duration_seconds": duration,
        "elapsed_seconds": elapsed,
        "real_time_factor": duration / elapsed if elapsed > 0 else None,
        "decoded_frames": frame_count,
        "decoded_frames_per_second": frame_count / elapsed if elapsed > 0 else None,
        "peak_child_ram_mb": peak_ram_mb or _child_peak_ram_mb(),
        "ffmpeg_threads": 1,
        "video_only": True,
        "output": "discarded via null muxer",
        "platform": sys.platform,
    }


def write_benchmark_report(path: str | Path, result: dict[str, Any]) -> Path:
    target = Path(path)
    atomic_write_json(target, result)
    return target
