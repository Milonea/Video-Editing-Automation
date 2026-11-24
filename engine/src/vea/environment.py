"""Secret-free host capability inventory for VEA backend selection."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .workspace import WorkspaceError, resolve_workspace


def _memory_total_bytes() -> int | None:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            value = MemoryStatus()
            value.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
                return int(value.ullTotalPhys)
        except (AttributeError, OSError):
            return None
        return None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
        total = page_size * page_count
        return total if total > 0 else None
    except (AttributeError, OSError, ValueError):
        pass
    if platform.system() == "Darwin" and shutil.which("sysctl"):
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return None


def _nvidia_devices() -> tuple[list[dict[str, Any]], str | None]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return [], None
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,driver_version,memory.total,memory.free",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], type(exc).__name__
    if result.returncode != 0:
        return [], "nvidia_smi_failed"
    devices = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if not parts or not parts[0]:
            continue
        devices.append(
            {
                "name": parts[0],
                "driver_version": parts[1] if len(parts) > 1 else None,
                "memory_total": parts[2] if len(parts) > 2 else None,
                "memory_free": parts[3] if len(parts) > 3 else None,
            }
        )
    return devices, None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return name in sys.modules


def _ctranslate_cuda() -> tuple[bool, list[str], str | None]:
    try:
        module = __import__("ctranslate2")
    except ImportError:
        return False, [], None
    except Exception as exc:
        return False, [], type(exc).__name__
    try:
        count = int(module.get_cuda_device_count())
        types = sorted(str(item) for item in module.get_supported_compute_types("cuda")) if count else []
        return count > 0, types, None
    except Exception as exc:
        return False, [], type(exc).__name__


def _disk_record(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    target = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        return {"path": str(path), "status": "unavailable"}
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "status": "available",
    }


def collect_environment(
    *,
    code_root: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    workspace_root: str | Path | None = None,
    search_roots: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Describe installed capabilities; never expose credentials or auth contents."""
    resolved_code_root = Path(code_root).expanduser().resolve() if code_root is not None else Path.cwd().resolve()
    workspace: dict[str, Any]
    try:
        resolved_workspace = resolve_workspace(
            config=config,
            explicit_root=workspace_root,
            search_roots=search_roots,
            code_root=resolved_code_root,
        )
    except WorkspaceError as exc:
        workspace = {"status": "unavailable", "reason": str(exc)}
    else:
        workspace = resolved_workspace.to_dict()

    nvidia_devices, nvidia_error = _nvidia_devices()
    cuda_available, cuda_compute_types, cuda_error = _ctranslate_cuda()
    system = platform.system()
    architecture = platform.machine()
    mlx_available = _module_available("mlx") if system == "Darwin" else False
    if cuda_available:
        recommended_device = "cuda"
    else:
        recommended_device = "cpu"

    video_disk: dict[str, Any] | None = None
    if workspace.get("status") == "resolved":
        video_disk = _disk_record(Path(str(workspace["projects_root"])))

    return {
        "schema_version": 1,
        "vea_version": __version__,
        "operating_system": {
            "name": system,
            "release": platform.release(),
            "architecture": architecture,
            "is_apple_silicon": system == "Darwin" and architecture.casefold() in {"arm64", "aarch64"},
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "cpu": {"logical_processors": os.cpu_count()},
        "memory": {"total_bytes": _memory_total_bytes()},
        "executables": {
            name: shutil.which(name)
            for name in ("ffmpeg", "ffprobe", "git", "gh", "codex")
        },
        "transcription": {
            "faster_whisper_installed": _module_available("faster_whisper"),
            "ctranslate2_installed": _module_available("ctranslate2"),
            "cuda_available": cuda_available,
            "cuda_compute_types": cuda_compute_types,
            "mlx_installed": mlx_available,
            "recommended_device": recommended_device,
            "ctranslate2_error": cuda_error,
        },
        "gpu": {
            "nvidia_devices": nvidia_devices,
            "nvidia_query_error": nvidia_error,
            "cuda_available": cuda_available,
        },
        "storage": {
            "development": _disk_record(resolved_code_root),
            "video_workspace": video_disk,
        },
        "video_workspace": workspace,
    }


def select_transcription_device(preference: str | None = "auto") -> tuple[str, str | None]:
    """Select only a backend that the installed CTranslate2 runtime reports."""
    requested = (preference or "auto").strip().casefold()
    cuda_available, _, error = _ctranslate_cuda()
    if requested in {"", "auto", "automatic"}:
        return ("cuda" if cuda_available else "cpu"), None
    if requested == "cpu":
        return "cpu", None
    if requested == "cuda":
        if cuda_available:
            return "cuda", None
        reason = "CTranslate2에서 CUDA 장치를 확인하지 못했습니다. 지원되지 않는 GPU 백엔드를 실행하지 않았습니다."
        if error:
            reason += f" ({error})"
        raise ValueError(reason)
    if requested == "mlx":
        raise ValueError("MLX는 감지 기능만 제공하며 현재 VEA 전사 실행 backend로 구현되지 않았습니다.")
    raise ValueError(f"지원하지 않는 전사 장치입니다: {preference}")


def format_environment_summary(report: Mapping[str, Any]) -> list[str]:
    os_info = report.get("operating_system", {})
    python_info = report.get("python", {})
    transcription = report.get("transcription", {})
    lines = [
        f"VEA {report.get('vea_version')} | Python {python_info.get('version')} | "
        f"OS {os_info.get('name')} {os_info.get('architecture')}",
        f"CPU 논리 프로세서: {(report.get('cpu') or {}).get('logical_processors') or '확인 불가'}",
        f"RAM: {(report.get('memory') or {}).get('total_bytes') or '확인 불가'} bytes",
        f"전사 권장 장치: {transcription.get('recommended_device')}",
    ]
    for name, path in (report.get("executables") or {}).items():
        lines.append(f"{name}: {path or '없음'}")
    devices = (report.get("gpu") or {}).get("nvidia_devices", [])
    if devices:
        lines.append("NVIDIA GPU:")
        lines.extend(
            "  {name} | driver {driver_version} | VRAM {memory_total}/{memory_free} free".format(**item)
            for item in devices
        )
    else:
        lines.append("NVIDIA GPU: 확인되지 않음")
    lines.append(
        "CTranslate2 CUDA: "
        + ("사용 가능" if transcription.get("cuda_available") else "사용 불가 — CPU 선택")
    )
    workspace = report.get("video_workspace") or {}
    if workspace.get("status") == "resolved":
        lines.append(f"영상 워크스페이스: {workspace.get('projects_root')}")
    else:
        lines.append(f"영상 워크스페이스: 미연결/미설정 ({workspace.get('reason', '확인 필요')})")
    return lines
