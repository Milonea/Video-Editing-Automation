from __future__ import annotations

import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .media import AudioStream, MediaInfo, MediaToolError, require_binary
from .models import TimelineClip
from .timecode import round_fraction


def build_voice_roughcut(
    media: MediaInfo,
    clips: list[TimelineClip],
    selected_global_indexes: list[int],
    output_dir: str | Path,
    sample_rate: int = 48000,
    crossfade_ms: int = 5,
    ffmpeg: str = "ffmpeg",
) -> list[Path]:
    """Extract selected source streams to cut-aligned PCM WAVs and a review mix."""
    if not clips:
        raise ValueError("음성 러프컷을 만들 타임라인 클립이 없습니다.")
    if not selected_global_indexes:
        raise ValueError("보이스 스트림을 먼저 선택하세요. 트랙명/VAD만으로 자동 확정하지 않습니다.")
    by_index = {stream.global_index: stream for stream in media.audio_streams}
    if len(set(selected_global_indexes)) != len(selected_global_indexes):
        raise ValueError("같은 오디오 스트림 인덱스가 중복 선택되었습니다.")
    missing = [index for index in selected_global_indexes if index not in by_index]
    if missing:
        raise ValueError(f"오디오 전체 스트림 인덱스를 찾지 못했습니다: {missing}")
    binary = require_binary(ffmpeg)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    individual: list[Path] = []
    for global_index in selected_global_indexes:
        stream = by_index[global_index]
        target = root / f"voice_stream_{stream.audio_ordinal:02d}_global_{global_index}.wav"
        temporary = target.with_name(f".{target.stem}.part.wav")
        labels: list[str] = []
        filters: list[str] = []
        for clip_index, clip in enumerate(clips):
            start_sample = round_fraction(clip.source_in_seconds * sample_rate)
            end_sample = round_fraction(clip.source_out_seconds * sample_rate)
            # Each cut is rounded at a sample boundary before concatenation.
            exact_seconds = clip.source_out_seconds - clip.source_in_seconds
            sample_count = max(1, round_fraction(exact_seconds * sample_rate))
            fade_samples = min(max(0, round_fraction(Fraction(crossfade_ms * sample_rate, 1000))), sample_count // 2)
            fade_seconds = Fraction(fade_samples, sample_rate)
            label = f"seg{clip_index}"
            labels.append(f"[{label}]")
            chain = (
                f"[0:{global_index}]aresample={sample_rate}:async=1:first_pts=0,"
                f"atrim=start_sample={start_sample}:end_sample={end_sample}"
            )
            if clip.mute_audio:
                chain += ",volume=0"
            chain += (
                ",asetpts=PTS-STARTPTS,"
                f"apad=whole_len={sample_count},atrim=end_sample={sample_count}"
            )
            if fade_samples:
                fade = float(fade_seconds)
                fade_out_start = max(0.0, float(Fraction(sample_count, sample_rate) - fade_seconds))
                chain += f",afade=t=in:st=0:d={fade:.9f},afade=t=out:st={fade_out_start:.9f}:d={fade:.9f}"
            chain += f"[{label}]"
            filters.append(chain)
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
        filter_graph = ";".join(filters)
        command = [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-threads",
            "1",
            "-i",
            media.path,
            "-filter_complex",
            filter_graph,
            "-map",
            "[out]",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(temporary),
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            temporary.unlink(missing_ok=True)
            raise MediaToolError(f"오디오 스트림 {global_index} 러프컷 생성 실패: {result.stderr.strip()}")
        os.replace(temporary, target)
        individual.append(target)
        generated.append(target)

    mix_path = root / "roughcut_voice.wav"
    mix_temp = mix_path.with_name(".roughcut_voice.part.wav")
    if len(individual) == 1:
        shutil.copyfile(individual[0], mix_temp)
        os.replace(mix_temp, mix_path)
    else:
        inputs: list[str] = []
        filter_inputs: list[str] = []
        for index, path in enumerate(individual):
            inputs.extend(["-i", str(path)])
            filter_inputs.append(f"[{index}:a]")
        graph = (
            "".join(filter_inputs)
            + f"amix=inputs={len(individual)}:duration=longest:normalize=1,"
            + "alimiter=limit=0.95[out]"
        )
        command = [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-threads",
            "1",
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(mix_temp),
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            mix_temp.unlink(missing_ok=True)
            raise MediaToolError(f"보이스 트랙 믹스 실패: {result.stderr.strip()}")
        os.replace(mix_temp, mix_path)
    generated.append(mix_path)
    return generated


def get_audio_ordinal(media: MediaInfo, global_index: int) -> int:
    for stream in media.audio_streams:
        if stream.global_index == global_index:
            return stream.audio_ordinal
    raise ValueError(f"오디오 전체 스트림 인덱스 {global_index}를 찾지 못했습니다.")
