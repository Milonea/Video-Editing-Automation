import json
import subprocess

import pytest

from vea.media import probe_media


@pytest.mark.parametrize(
    ("average_rate", "expected_vfr"),
    [("0/0", True), ("25/1", True), ("30/1", False)],
)
def test_probe_uses_average_and_real_rate_consistently(tmp_path, monkeypatch, average_rate, expected_vfr):
    source = tmp_path / "probe.mkv"
    source.write_bytes(b"synthetic")
    payload = {
        "format": {"duration": "1.0", "format_name": "matroska"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "mpeg4",
                "width": 160,
                "height": 90,
                "pix_fmt": "yuv420p",
                "time_base": "1/1000",
                "r_frame_rate": "30/1",
                "avg_frame_rate": average_rate,
                "start_time": "0",
                "duration": "1.0",
            }
        ],
    }
    monkeypatch.setattr("vea.media.require_binary", lambda _name: "ffprobe")
    monkeypatch.setattr(
        "vea.media.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["ffprobe"], returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )

    media = probe_media(source)
    assert media.video["is_vfr_heuristic"] is expected_vfr
    assert media.video["frame_rate"] == {"0/0": "30", "25/1": "25", "30/1": "30"}[average_rate]
