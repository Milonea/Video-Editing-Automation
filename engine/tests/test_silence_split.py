from fractions import Fraction

from vea.silence_split import analyze_caption_gaps, write_candidate_artifacts
from vea.subtitles import SubtitleSegment


def test_exact_minimum_gap_is_included_and_frame_boundaries_are_conservative():
    result = analyze_caption_gaps(
        [SubtitleSegment(0.0, 1.0, "A"), SubtitleSegment(1.8, 2.0, "B")],
        fps=Fraction(24, 1),
        sequence_duration_seconds=Fraction(5, 2),
    )
    candidate = result["candidates"][0]
    assert result["candidate_count"] == 1
    assert candidate["start_frame"] == 24
    assert candidate["end_frame"] == 43
    assert candidate["split_applied"] is False
    assert candidate["sequence_start"] == "1.000000"
    assert candidate["sequence_end"] == "1.791667"


def test_gap_below_threshold_is_not_a_candidate():
    result = analyze_caption_gaps(
        [SubtitleSegment(0.0, 1.0, "A"), SubtitleSegment(1.79, 2.0, "B")],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(12, 5),
    )
    assert result["candidate_count"] == 0


def test_srt_subtitle_end_does_not_receive_the_tail_twice():
    result = analyze_caption_gaps(
        [SubtitleSegment(0.0, 1.0, "A"), SubtitleSegment(1.8, 2.0, "B")],
        fps=Fraction(25, 1),
        subtitle_tail_seconds=Fraction(1, 2),
        end_time_kind="subtitle_end",
        sequence_duration_seconds=Fraction(5, 2),
    )
    assert result["candidate_count"] == 1
    assert result["tail_added_seconds"] == 0.0
    assert "0.5초를 다시 더하지 않았습니다" in result["candidates"][0]["notes"][0]


def test_raw_whisper_speech_end_receives_the_configured_tail_once():
    result = analyze_caption_gaps(
        [{"start": 0, "end": 1, "text": "A"}, {"start": 1.8, "end": 2, "text": "B"}],
        fps=Fraction(30, 1),
        subtitle_tail_seconds=Fraction(1, 2),
        end_time_kind="speech_end",
        sequence_duration_seconds=Fraction(3),
    )
    assert result["candidate_count"] == 0
    assert result["tail_added_seconds"] == 0.5


def test_overlapping_captions_are_merged_as_protected_intervals():
    result = analyze_caption_gaps(
        [
            SubtitleSegment(0.0, 2.0, "A"),
            SubtitleSegment(1.0, 3.0, "B"),
            SubtitleSegment(4.0, 5.0, "C"),
        ],
        fps=Fraction(60, 1),
        sequence_duration_seconds=Fraction(6),
    )
    candidate = next(item for item in result["candidates"] if item["candidate_type"] == "inter_caption")
    assert candidate["sequence_start"] == "3.000000"
    assert candidate["sequence_end"] == "4.000000"
    assert candidate["previous_caption"] == "B"
    assert result["overlapping_cue_pairs_merged"] == 1
    assert result["issues"][0]["code"] == "overlapping_captions_merged"


def test_invalid_cue_blocks_gap_inference():
    result = analyze_caption_gaps(
        [SubtitleSegment(0.0, 1.0, "A"), SubtitleSegment(2.0, 2.0, "bad"), SubtitleSegment(4.0, 5.0, "C")],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(6),
    )
    assert result["blocked"] is True
    assert result["candidate_count"] == 0
    assert result["issues"][0]["code"] == "invalid_interval"


def test_negative_timestamp_blocks_gap_inference():
    result = analyze_caption_gaps(
        [SubtitleSegment(-0.1, 0.5, "negative"), SubtitleSegment(2.0, 2.5, "B")],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(3),
    )
    assert result["blocked"] is True
    assert result["candidate_count"] == 0
    assert result["issues"][0]["code"] == "negative_timestamp"


def test_empty_caption_sequence_is_review_only_and_never_split():
    result = analyze_caption_gaps(
        [],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(4),
    )
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["candidate_type"] == "no_captions"
    assert result["candidates"][0]["split_applied"] is False
    assert result["candidates"][0]["split_api_required"] is False
    assert result["auto_delete"] is False


def test_fractional_fps_uses_rational_conservative_frame_boundaries():
    result = analyze_caption_gaps(
        [SubtitleSegment(0, 1, "A"), SubtitleSegment(2, 2.5, "B")],
        fps=Fraction(30_000, 1_001),
        sequence_duration_seconds=Fraction(3),
    )
    candidate = result["candidates"][0]
    assert candidate["start_frame"] == 30
    assert candidate["end_frame"] == 59
    assert Fraction(candidate["sequence_start_seconds"]) >= 1
    assert Fraction(candidate["sequence_end_seconds"]) <= 2


def test_sequence_timebase_mismatch_blocks_all_candidates():
    result = analyze_caption_gaps(
        [SubtitleSegment(0.0, 1.0, "A"), SubtitleSegment(2.0, 4.0, "B")],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(3),
    )
    assert result["blocked"] is True
    assert result["candidate_count"] == 0
    assert result["issues"][0]["code"] == "sequence_timebase_mismatch"


def test_sequence_head_and_tail_are_review_only_candidates():
    result = analyze_caption_gaps(
        [SubtitleSegment(1.0, 2.0, "A")],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(4),
    )
    edges = [item for item in result["candidates"] if item["candidate_type"] != "inter_caption"]
    assert [item["candidate_type"] for item in edges] == ["sequence_head", "sequence_tail"]
    assert all(item["split_applied"] is False for item in edges)
    assert all(item["validation_status"] == "review_only_boundary_gap" for item in edges)


def test_existing_edit_boundaries_and_source_ranges_are_recorded():
    edit_map = {
        "clips": [
            {
                "timeline_start_frame": 0,
                "timeline_end_frame": 60,
                "source_in_frame": 100,
                "source_file": "source.mp4",
            },
            {
                "timeline_start_frame": 60,
                "timeline_end_frame": 180,
                "source_in_frame": 400,
                "source_file": "source.mp4",
            },
        ]
    }
    result = analyze_caption_gaps(
        [SubtitleSegment(0.0, 0.8, "A"), SubtitleSegment(3.0, 3.5, "B")],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(4),
        existing_cut_frames={24, 60},
        edit_map=edit_map,
    )
    candidate = result["candidates"][0]
    assert candidate["existing_cut_boundaries"] == [24]
    assert candidate["source_time_ranges"] == [
        {
            "source_file": "source.mp4",
            "source_start_frame": 124,
            "source_end_frame": 160,
            "sequence_start_frame": 24,
            "sequence_end_frame": 60,
        },
        {
            "source_file": "source.mp4",
            "source_start_frame": 400,
            "source_end_frame": 430,
            "sequence_start_frame": 60,
            "sequence_end_frame": 90,
        },
    ]


def test_candidate_csv_contains_required_columns_and_preserves_caption_commas(tmp_path):
    result = analyze_caption_gaps(
        [SubtitleSegment(0.0, 1.0, "A, B"), SubtitleSegment(2.0, 2.5, "C, D")],
        fps=Fraction(30, 1),
        sequence_duration_seconds=Fraction(3),
    )
    json_path, csv_path = write_candidate_artifacts(
        result,
        json_path=tmp_path / "silence_candidates.json",
        csv_path=tmp_path / "silence_candidates.csv",
    )
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert json_path.is_file()
    assert "candidate_id,sequence_start,sequence_end,duration_seconds,start_frame,end_frame" in csv_text
    assert '"A, B"' in csv_text
