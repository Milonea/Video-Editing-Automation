from __future__ import annotations

import gc
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .checkpoint import Checkpoint, atomic_write_json, canonical_hash, file_fingerprint
from .disk_space import disk_space_message, disk_space_report, estimate_transcription_scratch
from .media import MediaToolError, probe_media, require_binary
from .subtitles import SubtitleSegment, safe_transcript_name, write_transcript_artifacts


OOM_MARKERS = (
    "out of memory",
    "cuda_error_out_of_memory",
    "cudnn_status_alloc_failed",
    "cublas_status_alloc_failed",
    "memory allocation",
)


def _looks_like_oom(error: BaseException) -> bool:
    message = str(error).casefold()
    return any(marker in message for marker in OOM_MARKERS)


def _gpu_memory_used_mb() -> float | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    result = subprocess.run(
        [nvidia_smi, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode:
        return None
    values: list[float] = []
    for line in result.stdout.splitlines():
        try:
            values.append(float(line.strip()))
        except ValueError:
            continue
    return max(values) if values else None


def _process_peak_ram_mb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                return counters.PeakWorkingSetSize / (1024 * 1024)
            return None
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux and the BSDs typically report KiB.
        return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024
    except (ImportError, AttributeError, OSError):
        return None


class ResourceSampler:
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.peak_vram_mb: float | None = None
        self.peak_ram_mb: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        while not self._stop.is_set():
            vram = _gpu_memory_used_mb()
            ram = _process_peak_ram_mb()
            if vram is not None:
                self.peak_vram_mb = max(self.peak_vram_mb or 0, vram)
            if ram is not None:
                self.peak_ram_mb = max(self.peak_ram_mb or 0, ram)
            self._stop.wait(self.interval)

    def __enter__(self) -> "ResourceSampler":
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


class ChunkProgress:
    """Persist chunk-level model, inference, and segment progress as JSONL."""

    def __init__(
        self,
        path: Path,
        requested: dict[str, Any],
        chunk_index: int,
        chunk_start: float,
        chunk_duration: float,
        heartbeat_seconds: float = 30.0,
    ) -> None:
        self.path = path
        self.requested = {
            key: requested.get(key)
            for key in (
                "model",
                "fallback_models",
                "device",
                "compute_type",
                "cpu_fallback",
                "language",
                "beam_size",
                "chunk_seconds",
                "word_timestamps",
                "audio_stream_index",
            )
        }
        self.chunk_index = chunk_index
        self.chunk_start = chunk_start
        self.chunk_duration = chunk_duration
        self.started = time.perf_counter()
        self.heartbeat_seconds = heartbeat_seconds
        self.phase = "chunk_setup"
        self.actual: dict[str, str] | None = None
        self.candidate: dict[str, str] | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._model_load_started: float | None = None
        self._model_load_current = 0.0
        self._model_load_total = 0.0
        self._inference_started: float | None = None
        self._inference_total = 0.0
        self._attempt_number = 0
        self._audio_processed = 0.0
        self._segment_count = 0
        self._has_segment = False
        self._decoded_until: float | None = None
        self._last_segment_start: float | None = None
        self._last_segment_end: float | None = None
        self._closed = False
        self._write("chunk_started")
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            self._write("heartbeat")

    def _write(self, event: str, terminal_status: str | None = None, message: str | None = None) -> None:
        now = time.perf_counter()
        with self._lock:
            inference_elapsed = self._inference_total
            if self._inference_started is not None:
                inference_elapsed += now - self._inference_started
            model_load_current = self._model_load_current
            model_load_active = 0.0
            if self._model_load_started is not None:
                model_load_active = now - self._model_load_started
                model_load_current = model_load_active
            model_load_total = self._model_load_total + model_load_active
            decoded_until = self._decoded_until
            audio_processed = self._audio_processed
            if decoded_until is not None:
                audio_processed = decoded_until
            wall_elapsed = now - self.started
            rtf = wall_elapsed / audio_processed if audio_processed > 0 else None
            inference_rtf = inference_elapsed / audio_processed if audio_processed > 0 else None
            payload = {
                "schema_version": 1,
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": event,
                "phase": self.phase,
                "chunk_index": self.chunk_index,
                "chunk_range_seconds": {
                    "start": self.chunk_start,
                    "end": self.chunk_start + self.chunk_duration,
                },
                "chunk_duration_seconds": self.chunk_duration,
                "requested": self.requested,
                "actual": self.actual,
                "model_load_candidate": self.candidate,
                "model_load_current_seconds": model_load_current,
                "model_load_total_seconds": model_load_total,
                "wall_elapsed_seconds": wall_elapsed,
                "inference_elapsed_seconds": inference_elapsed,
                "audio_processed_seconds": audio_processed,
                "decoded_until_seconds": decoded_until,
                "last_segment_start_seconds": self._last_segment_start,
                "last_segment_end_seconds": self._last_segment_end,
                "rtf": rtf,
                "inference_rtf": inference_rtf,
                "attempt_number": self._attempt_number,
                "segments_yielded": self._segment_count,
                "terminal_status": terminal_status or ("running" if not self._closed else "unknown"),
                "message": message,
            }
            if decoded_until is None:
                if self.phase == "model_load":
                    payload["progress_note"] = "모델 로드 중; 세그먼트 0; 진행률·RTF 계산 불가."
                elif self.phase == "inference":
                    payload["progress_note"] = "모델 호출/세그먼트 iterator 대기, segment 0; 진행률·RTF 계산 불가."
                else:
                    payload["progress_note"] = f"{self.phase}; segment 0; 진행률·RTF 계산 불가."
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                line = json.dumps(payload, ensure_ascii=False)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                print(line, flush=True)
            except OSError as exc:
                print(f"전사 진행 로그를 기록하지 못했습니다: {self.path} ({exc})", file=sys.stderr, flush=True)

    def model_load_started(self, model: str, device: str, compute_type: str) -> None:
        with self._lock:
            self.phase = "model_load"
            self.candidate = {"model": model, "device": device, "compute_type": compute_type}
            self.actual = None
            self._model_load_current = 0.0
            self._model_load_started = time.perf_counter()
        self._write("model_load_started")

    def model_load_finished(self, model: str, device: str, compute_type: str) -> None:
        with self._lock:
            now = time.perf_counter()
            elapsed = now - self._model_load_started if self._model_load_started is not None else 0.0
            self._model_load_total += elapsed
            self._model_load_current = elapsed
            self._model_load_started = None
            self.actual = {"model": model, "device": device, "compute_type": compute_type}
            self.candidate = None
            self.phase = "model_loaded"
        self._write("model_load_completed")

    def model_load_failed(self, error: BaseException) -> None:
        with self._lock:
            now = time.perf_counter()
            elapsed = now - self._model_load_started if self._model_load_started is not None else 0.0
            self._model_load_total += elapsed
            self._model_load_current = elapsed
            self._model_load_started = None
            self.actual = None
            self.phase = "model_load_failed"
        self._write("model_load_failed", message=f"{type(error).__name__}: {error}")

    def inference_started(self, model: str, device: str, compute_type: str) -> None:
        with self._lock:
            self.phase = "inference"
            self.actual = {"model": model, "device": device, "compute_type": compute_type}
            self._attempt_number += 1
            self._inference_started = time.perf_counter()
            self._audio_processed = 0.0
            self._segment_count = 0
            self._has_segment = False
            self._decoded_until = None
            self._last_segment_start = None
            self._last_segment_end = None
        self._write("inference_started")

    def segment_yielded(self, segment: Any) -> None:
        end = max(0.0, min(float(segment.end), self.chunk_duration))
        start = max(0.0, min(float(segment.start), self.chunk_duration))
        with self._lock:
            self._audio_processed = max(self._audio_processed, end)
            self._segment_count += 1
            self._has_segment = True
            self._decoded_until = self._audio_processed
            self._last_segment_start = start
            self._last_segment_end = end
            self.phase = "inference"
        self._write("segment_yielded")

    def inference_attempt_failed(self, error: BaseException) -> None:
        with self._lock:
            if self._inference_started is not None:
                self._inference_total += time.perf_counter() - self._inference_started
                self._inference_started = None
            self.phase = "inference_attempt_failed"
        self._write("inference_attempt_failed", message=f"{type(error).__name__}: {error}")

    def finish(self, status: str, error: BaseException | None = None) -> None:
        if self._closed:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        with self._lock:
            if self._inference_started is not None:
                self._inference_total += time.perf_counter() - self._inference_started
                self._inference_started = None
            if status == "completed":
                self._decoded_until = self.chunk_duration
                self._audio_processed = self.chunk_duration
            self.phase = status
            self._closed = True
        self._write(
            f"chunk_{status}",
            terminal_status=status,
            message=f"{type(error).__name__}: {error}" if error is not None else None,
        )


def _split_chunk(
    audio: Path,
    destination: Path,
    start: float,
    duration: float,
    ffmpeg: str,
    audio_stream_index: int | None = None,
) -> None:
    target = destination.with_name(f".{destination.name}.part.wav")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.6f}",
        "-threads",
        "1",
        "-i",
        str(audio),
        "-t",
        f"{duration:.6f}",
        "-map",
        f"0:{audio_stream_index}" if audio_stream_index is not None else "0:a:0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        target.unlink(missing_ok=True)
        raise MediaToolError(f"전사 청크 생성 실패: {result.stderr.strip()}")
    os.replace(target, destination)


def _segment_to_dict(segment: Any) -> dict[str, Any]:
    words = getattr(segment, "words", None)
    word_data = None
    if words:
        word_data = [
            {
                "start": getattr(word, "start", None),
                "end": getattr(word, "end", None),
                "word": getattr(word, "word", ""),
                "probability": getattr(word, "probability", None),
            }
            for word in words
        ]
    return {
        "start": float(segment.start),
        "end": float(segment.end),
        "text": str(segment.text),
        "avg_logprob": getattr(segment, "avg_logprob", None),
        "no_speech_prob": getattr(segment, "no_speech_prob", None),
        "words": word_data,
    }


def _load_cached_segments(path: Path, offset: float) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for item in data["segments"]:
        adjusted = dict(item)
        adjusted["start"] += offset
        adjusted["end"] += offset
        if adjusted.get("words"):
            adjusted["words"] = [
                {**word, "start": word["start"] + offset, "end": word["end"] + offset}
                for word in adjusted["words"]
            ]
        result.append(adjusted)
    return result


def transcribe_project(
    project_dir: str | Path,
    audio_file: str | Path | None = None,
    model_name: str = "large-v3",
    fallback_models: list[str] | None = None,
    device: str = "cuda",
    compute_type: str = "int8_float16",
    language: str = "ko",
    beam_size: int = 5,
    chunk_seconds: int = 600,
    word_timestamps: bool = False,
    glossary_file: str | Path | None = None,
    cpu_fallback: bool = False,
    allow_non_windows: bool = False,
    output_stem: str | None = None,
    audio_stream_index: int | None = None,
) -> dict[str, Any]:
    """Transcribe in resumable chunks on supported Windows and macOS hosts."""
    if sys.platform not in {"win32", "darwin"} and not allow_non_windows:
        raise RuntimeError(
            "VEA 전사는 Windows 또는 macOS에서 실행하도록 설정되어 있습니다. "
            "다른 OS는 --allow-non-windows로 테스트/수동 진단할 때만 허용합니다."
        )
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper가 설치되지 않았습니다. 현재 OS의 VEA 설치 스크립트를 실행하세요.") from exc
    root = Path(project_dir).expanduser().resolve()
    audio = Path(audio_file).expanduser().resolve() if audio_file else root / "05_AUDIO" / "roughcut_voice.wav"
    if not audio.is_file():
        raise FileNotFoundError(f"전사할 오디오가 없습니다: {audio}")
    transcript_name = safe_transcript_name(output_stem or (Path(audio_file).stem if audio_file else "transcript"))
    ffmpeg = require_binary("ffmpeg")
    info = probe_media(audio)
    if info.duration <= 0:
        raise ValueError("오디오 길이가 0초입니다.")
    available_stream_indexes = {stream.global_index for stream in info.audio_streams}
    if audio_stream_index is not None and audio_stream_index not in available_stream_indexes:
        raise ValueError(
            f"전사할 오디오 전체 스트림 인덱스 {audio_stream_index}를 찾지 못했습니다. "
            f"사용 가능한 인덱스: {sorted(available_stream_indexes)}"
        )
    scratch = estimate_transcription_scratch(info.duration, chunk_seconds)
    disk_report = disk_space_report(root, scratch)
    disk_report_path = root / "10_REPORTS" / "transcription-disk-preflight.json"
    disk_report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(disk_report_path, disk_report)
    print(disk_space_message(disk_report))
    if not disk_report["sufficient"]:
        raise RuntimeError(
            "전사 청크를 저장할 공간이 부족합니다. 다른 볼륨을 선택하거나 공간을 확보한 뒤 다시 실행하세요."
        )
    output_dir = root / "07_TRANSCRIPTS"
    chunk_dir = output_dir / ".chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "transcription_progress.jsonl"
    checkpoint = Checkpoint(root)
    source_fp = file_fingerprint(audio, full_hash=True)
    glossary = ""
    if glossary_file:
        glossary_path = Path(glossary_file)
        if glossary_path.is_file():
            glossary = ", ".join(
                line.strip() for line in glossary_path.read_text(encoding="utf-8").splitlines() if line.strip()
            )
    requested = {
        "source": source_fp,
        "audio_stream_index": audio_stream_index,
        "model": model_name,
        "fallback_models": fallback_models or ["large-v3-turbo", "medium"],
        "device": device,
        "compute_type": compute_type,
        "cpu_fallback": cpu_fallback,
        "language": language,
        "beam_size": beam_size,
        "chunk_seconds": chunk_seconds,
        "word_timestamps": word_timestamps,
        "glossary": glossary,
    }
    if chunk_seconds < 60:
        raise ValueError("chunk_seconds는 60초 이상이어야 합니다.")
    chunk_count = max(1, math.ceil(info.duration / chunk_seconds))
    requested_models = list(dict.fromkeys([model_name, *(fallback_models or ["large-v3-turbo", "medium"])]))
    model_instance = None
    actual_model = None
    actual_device = device
    # int8_float16 is CUDA-specific. If CPU was explicitly selected, prefer
    # the supported low-memory CPU mode instead of failing during model load.
    primary_compute = "int8" if device == "cpu" and compute_type == "int8_float16" else compute_type
    actual_compute = primary_compute
    segments_all: list[dict[str, Any]] = []
    chunk_cache_hits = 0
    started = time.perf_counter()
    attempts: list[dict[str, str]] = []

    def load_model(name: str, selected_device: str, selected_compute: str) -> Any:
        return WhisperModel(name, device=selected_device, compute_type=selected_compute)

    def model_plan(selected_device: str) -> list[tuple[str, str]]:
        primary = primary_compute if selected_device == device else "int8"
        if selected_device == "cuda":
            alternatives = [value for value in ("int8", "float16", "int8_float16") if value != primary]
        else:
            alternatives = [value for value in ("int8", "int8_float32", "float32") if value != primary]
        # Preserve the preferred precision while stepping down model size
        # first; try alternate supported compute types only after all configured
        # models have failed with the preferred type.
        return [
            *((name, primary) for name in requested_models),
            *((name, alternate) for alternate in alternatives for name in requested_models),
        ]

    with ResourceSampler() as sampler:
        for index in range(chunk_count):
            start = index * chunk_seconds
            duration = min(float(chunk_seconds), info.duration - start)
            chunk_suffix = f"_{transcript_name}" if transcript_name != "transcript" else ""
            chunk_path = chunk_dir / f"chunk{chunk_suffix}_{index:04d}.wav"
            chunk_json = chunk_dir / f"chunk{chunk_suffix}_{index:04d}.json"
            signature = canonical_hash({**requested, "chunk_index": index, "start": start, "duration": duration})
            stage_prefix = "transcribe" if transcript_name == "transcript" else f"transcribe_{transcript_name}"
            stage_name = f"{stage_prefix}_chunk_{index:04d}"
            if checkpoint.cached(stage_name, signature, [chunk_json]):
                segments_all.extend(_load_cached_segments(chunk_json, start))
                chunk_cache_hits += 1
                continue
            _split_chunk(audio, chunk_path, start, duration, ffmpeg, audio_stream_index)
            progress = ChunkProgress(progress_path, requested, index, start, duration)
            chunk_segments: list[dict[str, Any]] | None = None
            # Continue below the model that actually succeeded on the previous
            # chunk. If that model fails on a later chunk, do not retry the same
            # known-bad primary model before trying the remaining fallbacks.
            active_plan = model_plan(actual_device)
            active_pair = (actual_model, actual_compute)
            active_rank = active_plan.index(active_pair) if actual_model and active_pair in active_plan else -1
            model_names = active_plan[active_rank + 1 :] if active_rank >= 0 else active_plan.copy()
            while chunk_segments is None:
                if model_instance is None:
                    if not model_names:
                        if device == "cuda" and cpu_fallback and actual_device != "cpu":
                            actual_device = "cpu"
                            actual_compute = "int8"
                            model_names = model_plan(actual_device)
                            continue
                        details = "; ".join(
                            f"{item['model']}({item['device']}/{item['compute_type']}): {item['error']}"
                            for item in attempts
                        )
                        error = RuntimeError(
                            "사용 가능한 Whisper 모델 후보가 모두 실패했습니다. "
                            f"시도 기록: {details or '기록 없음'}"
                        )
                        progress.finish("failed", error)
                        raise error
                    candidate, candidate_compute = model_names.pop(0)
                    actual_compute = candidate_compute
                    progress.model_load_started(candidate, actual_device, actual_compute)
                    try:
                        model_instance = load_model(candidate, actual_device, actual_compute)
                        actual_model = candidate
                        progress.model_load_finished(candidate, actual_device, actual_compute)
                    except KeyboardInterrupt as exc:
                        progress.model_load_failed(exc)
                        checkpoint.fail(stage_name, exc)
                        progress.finish("interrupted", exc)
                        raise
                    except Exception as exc:
                        progress.model_load_failed(exc)
                        attempts.append(
                            {
                                "model": candidate,
                                "device": actual_device,
                                "compute_type": actual_compute,
                                "failure_type": "out_of_memory" if _looks_like_oom(exc) else "runtime_or_compatibility",
                                "error": str(exc),
                            }
                        )
                        # CUDA/cuDNN/CTranslate2 compatibility errors are not
                        # always reported as OOM. Try the configured smaller
                        # models for any load failure before stopping.
                        if model_names:
                            gc.collect()
                            continue
                        if device == "cuda" and cpu_fallback and actual_device != "cpu":
                            actual_device = "cpu"
                            actual_compute = "int8"
                            model_names = model_plan(actual_device)
                            continue
                        error = RuntimeError(
                            f"Whisper 모델 {candidate} 로드 실패 ({actual_device}/{actual_compute}): {exc}"
                        )
                        progress.finish("failed", error)
                        raise error from exc
                checkpoint.start(stage_name, signature, [chunk_json])
                try:
                    kwargs: dict[str, Any] = {
                        "language": language,
                        "beam_size": beam_size,
                        "word_timestamps": word_timestamps,
                        "condition_on_previous_text": True,
                    }
                    if glossary:
                        kwargs["initial_prompt"] = glossary
                    progress.inference_started(actual_model or model_name, actual_device, actual_compute)
                    generated, transcription_info = model_instance.transcribe(str(chunk_path), **kwargs)
                    chunk_segments = []
                    for segment in generated:
                        progress.segment_yielded(segment)
                        chunk_segments.append(_segment_to_dict(segment))
                    atomic_write_json(
                        chunk_json,
                        {
                            "requested": requested,
                            "model": actual_model,
                            "device": actual_device,
                            "compute_type": actual_compute,
                            "language": getattr(transcription_info, "language", language),
                            "language_probability": getattr(transcription_info, "language_probability", None),
                            "segments": chunk_segments,
                        },
                    )
                    checkpoint.complete(
                        stage_name,
                        {
                            "chunk_index": index,
                            "model": actual_model,
                            "device": actual_device,
                            "segment_count": len(chunk_segments),
                        },
                    )
                    progress.finish("completed")
                except KeyboardInterrupt as exc:
                    checkpoint.fail(stage_name, exc)
                    progress.finish("interrupted", exc)
                    raise
                except Exception as exc:
                    progress.inference_attempt_failed(exc)
                    checkpoint.fail(stage_name, exc)
                    if model_names:
                        attempts.append(
                            {
                                "model": actual_model or "unknown",
                                "device": actual_device,
                                "compute_type": actual_compute,
                                "failure_type": "out_of_memory" if _looks_like_oom(exc) else "runtime_or_compatibility",
                                "error": str(exc),
                            }
                        )
                        del model_instance
                        model_instance = None
                        actual_model = None
                        gc.collect()
                        continue
                    if device == "cuda" and cpu_fallback and actual_device != "cpu":
                        attempts.append(
                            {
                                "model": actual_model or "unknown",
                                "device": actual_device,
                                "compute_type": actual_compute,
                                "failure_type": "out_of_memory" if _looks_like_oom(exc) else "runtime_or_compatibility",
                                "error": str(exc),
                            }
                        )
                        del model_instance
                        model_instance = None
                        actual_model = None
                        actual_device = "cpu"
                        actual_compute = "int8"
                        model_names = model_plan(actual_device)
                        gc.collect()
                        continue
                    attempts.append(
                        {
                            "model": actual_model or "unknown",
                            "device": actual_device,
                            "compute_type": actual_compute,
                            "failure_type": "out_of_memory" if _looks_like_oom(exc) else "runtime_or_compatibility",
                            "error": str(exc),
                        }
                    )
                    error = RuntimeError(
                        "Whisper 전사 단계가 실패했습니다. "
                        f"{actual_model or 'unknown'} ({actual_device}/{actual_compute}): {exc}"
                    )
                    progress.finish("failed", error)
                    raise error from exc
            segments_all.extend(_load_cached_segments(chunk_json, start))
            chunk_path.unlink(missing_ok=True)

    final_segments = [
        SubtitleSegment(
            start=float(item["start"]),
            end=float(item["end"]),
            text=str(item.get("text", "")),
            avg_logprob=item.get("avg_logprob"),
            no_speech_prob=item.get("no_speech_prob"),
            words=item.get("words"),
        )
        for item in sorted(segments_all, key=lambda item: (item["start"], item["end"]))
    ]
    edit_map_path = root / "04_ROUGHCUT" / "edit_map.json"
    boundaries: list[float] = []
    if edit_map_path.is_file():
        try:
            edit_map = json.loads(edit_map_path.read_text(encoding="utf-8"))
            from fractions import Fraction

            fps = Fraction(edit_map["fps"]["numerator"], edit_map["fps"]["denominator"])
            boundaries = [
                int(clip["timeline_end_frame"]) / float(fps)
                for clip in edit_map.get("clips", [])[:-1]
            ]
        except (OSError, ValueError, KeyError, TypeError):
            boundaries = []
    elapsed = time.perf_counter() - started
    metadata = {
        "requested": requested,
        "model": actual_model or model_name,
        "device": actual_device,
        "compute_type": actual_compute,
        "duration_seconds": info.duration,
        "elapsed_seconds": elapsed,
        "chunk_count": chunk_count,
        "chunk_cache_hits": chunk_cache_hits,
        "attempts": attempts,
        "peak_ram_mb": sampler.peak_ram_mb,
        "peak_vram_mb": sampler.peak_vram_mb,
        "progress_log": str(progress_path),
        "hardware_check": (
            "Windows runtime"
            if sys.platform == "win32"
            else "macOS CPU runtime; MLX execution is not implemented"
            if sys.platform == "darwin"
            else "non-production runtime; manual validation required"
        ),
    }
    artifacts = write_transcript_artifacts(
        output_dir,
        final_segments,
        info.duration,
        metadata,
        boundaries,
        transcript_name=transcript_name,
    )
    checkpoint.data["transcription"] = {
        "status": "completed",
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metadata": metadata,
        "outputs": {key: str(path) for key, path in artifacts.items()},
    }
    checkpoint.save()
    return {"artifacts": artifacts, "metadata": metadata, "segment_count": len(final_segments)}
