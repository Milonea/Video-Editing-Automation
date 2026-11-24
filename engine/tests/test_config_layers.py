from pathlib import Path

import pytest

from vea.config import ConfigError, default_local_config_path, load_config


def test_config_merges_common_host_local_project_explicit_and_task_layers(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "common.toml").write_text("[project]\naudio_sample_rate = 48000\n[transcription]\nmodel = 'large'\n", encoding="utf-8")
    (config_dir / "windows.toml").write_text("[transcription]\ndevice = 'auto'\n", encoding="utf-8")
    local = tmp_path / "local.toml"
    local.write_text("[project]\naudio_sample_rate = 44100\n", encoding="utf-8")
    project = tmp_path / "project.toml"
    project.write_text("[transcription]\nmodel = 'medium'\n", encoding="utf-8")
    explicit = tmp_path / "task.toml"
    explicit.write_text("[transcription]\nlanguage = 'en'\n", encoding="utf-8")

    result = load_config(
        config_dir=config_dir,
        system="Windows",
        local_config_path=local,
        project_config_path=project,
        explicit_path=explicit,
        task_overrides={"transcription": {"beam_size": 2}},
    )

    assert result.values["project"]["audio_sample_rate"] == 44100
    assert result.values["transcription"] == {
        "model": "medium",
        "device": "auto",
        "language": "en",
        "beam_size": 2,
    }
    assert result.sources == ("common", "windows", "local:local.toml", "project:project.toml", "explicit:task.toml", "task_overrides")


def test_explicit_config_path_must_exist(tmp_path: Path):
    with pytest.raises(ConfigError, match="찾을 수 없습니다"):
        load_config(explicit_path=tmp_path / "missing.toml", config_dir=tmp_path / "config")


def test_local_config_path_is_platform_specific_without_hardcoded_user_path():
    home = Path("/") / "Users" / "fixture-home"
    mac = default_local_config_path(system="Darwin", home=home, environment={})
    linux = default_local_config_path(system="Linux", home=home, environment={})
    assert mac == home / "Library" / "Application Support" / "VEA" / "config.toml"
    assert linux == home / ".config" / "vea" / "config.toml"


def test_profile_is_applied_after_host_and_before_local_project_explicit_and_cli(tmp_path: Path):
    config_dir = tmp_path / "config"
    profiles = config_dir / "profiles"
    profiles.mkdir(parents=True)
    (config_dir / "common.toml").write_text("[transcription]\nmodel = 'base'\n", encoding="utf-8")
    (config_dir / "macos.toml").write_text("[transcription]\nmodel = 'medium'\n", encoding="utf-8")
    (profiles / "lightweight.toml").write_text("[transcription]\nmodel = 'tiny'\n", encoding="utf-8")
    local = tmp_path / "local.toml"
    local.write_text("[transcription]\ncompute_type = 'int8'\n", encoding="utf-8")
    project = tmp_path / "project.toml"
    project.write_text("[transcription]\nmodel = 'small'\n", encoding="utf-8")
    explicit = tmp_path / "explicit.toml"
    explicit.write_text("[transcription]\nlanguage = 'en'\n", encoding="utf-8")

    result = load_config(
        config_dir=config_dir,
        system="Darwin",
        profile="lightweight",
        local_config_path=local,
        project_config_path=project,
        explicit_path=explicit,
        task_overrides={"transcription": {"beam_size": 1}},
    )

    assert result.values["transcription"] == {
        "model": "small",
        "compute_type": "int8",
        "language": "en",
        "beam_size": 1,
    }
    assert result.sources == (
        "common", "macos", "profile:lightweight", "local:local.toml",
        "project:project.toml", "explicit:explicit.toml", "task_overrides"
    )


def test_unknown_profile_is_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="지원하지 않는 실행 프로필"):
        load_config(config_dir=tmp_path, profile="unsupported")


def test_cli_accepts_profile_after_command():
    from vea.cli import build_parser

    args = build_parser().parse_args(["inspect", "sample.mov", "--profile", "lightweight"])
    assert args.profile == "lightweight"
