from vea.subtitles import SubtitleSegment, validate_subtitles, write_srt


def test_srt_and_validation(tmp_path):
    segments = [
        SubtitleSegment(0.0, 1.0, "안녕하세요"),
        SubtitleSegment(0.8, 2.5, "확인할 문장", avg_logprob=-1.4),
        SubtitleSegment(2.5, 2.5, ""),
    ]
    path = write_srt(segments, tmp_path / "transcript.srt")
    text = path.read_text(encoding="utf-8-sig")
    assert "00:00:00,000 --> 00:00:01,000" in text
    issues = validate_subtitles(segments, 2.4, clip_boundaries=[0.9])
    codes = {item["code"] for item in issues}
    assert {"overlap", "low_confidence", "empty_text", "invalid_interval", "out_of_range", "cut_boundary_crossing"} <= codes
