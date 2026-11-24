"""Layered, cross-platform VEA configuration loading."""

from __future__ import annotations

import os
import platform
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a configured TOML layer cannot be loaded safely."""


@dataclass(frozen=True)
class ConfigResult:
    values: dict[str, Any]
    sources: tuple[str, ...]


def host_config_name(system: str | None = None) -> str:
    name = (system or platform.system()).casefold()
    if name == "windows":
        return "windows"
    if name == "darwin":
        return "macos"
    if name == "linux":
        return "linux"
    return "common"


def repository_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config"


def default_local_config_path(
    *,
    system: str | None = None,
    environment: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    env = os.environ if environment is None else environment
    name = (system or platform.system()).casefold()
    user_home = Path(home).expanduser() if home is not None else Path.home()
    if name == "windows":
        base = env.get("LOCALAPPDATA") or str(user_home / "AppData" / "Local")
        return Path(base) / "VEA" / "config.toml"
    if name == "darwin":
        return user_home / "Library" / "Application Support" / "VEA" / "config.toml"
    base = env.get("XDG_CONFIG_HOME") or str(user_home / ".config")
    return Path(base) / "vea" / "config.toml"


def _merge(target: dict[str, Any], layer: Mapping[str, Any]) -> None:
    for key, value in layer.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge(current, value)
        elif isinstance(value, Mapping):
            target[key] = {str(child): item for child, item in value.items()}
        else:
            target[key] = value


def _read_layer(path: Path, *, required: bool) -> dict[str, Any] | None:
    if not path.is_file():
        if required:
            raise ConfigError(f"설정 파일을 찾을 수 없습니다: {path}")
        return None
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"설정 파일을 읽지 못했습니다: {path}: {exc}") from exc
    return value


def load_config(
    *,
    project_config_path: str | Path | None = None,
    explicit_path: str | Path | None = None,
    local_config_path: str | Path | None = None,
    task_overrides: Mapping[str, Any] | None = None,
    config_dir: str | Path | None = None,
    system: str | None = None,
    profile: str | None = None,
) -> ConfigResult:
    """Merge common → host → profile → local → project → explicit → task overrides."""
    directory = Path(config_dir) if config_dir is not None else repository_config_dir()
    host = host_config_name(system)
    selected_profile = profile or os.environ.get("VEA_PROFILE")
    if selected_profile and selected_profile not in {"development", "lightweight", "production", "validation"}:
        raise ConfigError(f"지원하지 않는 실행 프로필입니다: {selected_profile}")
    layers: list[tuple[str, Path, bool]] = [
        ("common", directory / "common.toml", False),
        (host, directory / f"{host}.toml", False),
    ]
    if selected_profile:
        layers.append((f"profile:{selected_profile}", directory / "profiles" / f"{selected_profile}.toml", True))

    configured_local = local_config_path
    if configured_local is None:
        configured_local = os.environ.get("VEA_CONFIG_FILE") or default_local_config_path(system=system)
    layers.append(("local", Path(configured_local).expanduser(), False))
    if project_config_path is not None:
        layers.append(("project", Path(project_config_path).expanduser(), False))
    if explicit_path is not None:
        layers.append(("explicit", Path(explicit_path).expanduser(), True))

    merged: dict[str, Any] = {}
    sources: list[str] = []
    seen: set[Path] = set()
    for label, raw_path, required in layers:
        path = raw_path.resolve()
        if path in seen:
            continue
        seen.add(path)
        parsed = _read_layer(path, required=required)
        if parsed is None:
            continue
        _merge(merged, parsed)
        if label in {"common", "windows", "macos", "linux"} or label.startswith("profile:"):
            sources.append(label)
        else:
            sources.append(f"{label}:{path.name}")

    if task_overrides:
        _merge(merged, task_overrides)
        sources.append("task_overrides")
    return ConfigResult(values=merged, sources=tuple(sources))
