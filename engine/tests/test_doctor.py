from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from vea import cli


def test_doctor_reports_ctranslate_cuda_and_nvidia_driver_state(monkeypatch, capsys) -> None:
    ctranslate2 = SimpleNamespace(
        __version__="4.8.3",
        get_cuda_device_count=lambda: 1,
        get_supported_compute_types=lambda _device: {"int8_float16", "int8"},
    )
    monkeypatch.setitem(sys.modules, "ctranslate2", ctranslate2)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(__version__="1.2.1-test"))
    monkeypatch.setattr(cli, "require_binary", lambda name: f"/fake/{name}")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="NVIDIA GeForce RTX 2070 SUPER, 551.23, 8192 MiB, 6144 MiB\n",
            stderr="",
        ),
    )

    assert cli._command_doctor(SimpleNamespace()) == 0
    output = capsys.readouterr().out
    assert "CTranslate2: 4.8.3" in output
    assert "CUDA 장치 수: 1" in output
    assert "CUDA 지원 정밀도: int8, int8_float16" in output
    assert "RTX 2070 SUPER" in output
