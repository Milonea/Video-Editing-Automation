import pytest

from vea import environment


def test_auto_transcription_backend_uses_cuda_only_when_runtime_confirms_it(monkeypatch):
    monkeypatch.setattr(environment, "_ctranslate_cuda", lambda: (False, [], None))
    assert environment.select_transcription_device("auto") == ("cpu", None)
    with pytest.raises(ValueError, match="CUDA 장치"):
        environment.select_transcription_device("cuda")

    monkeypatch.setattr(environment, "_ctranslate_cuda", lambda: (True, ["int8_float16"], None))
    assert environment.select_transcription_device("auto") == ("cuda", None)


def test_mlx_detection_does_not_claim_a_vea_mlx_backend(monkeypatch):
    monkeypatch.setattr(environment, "_ctranslate_cuda", lambda: (False, [], None))
    with pytest.raises(ValueError, match="MLX"):
        environment.select_transcription_device("mlx")
