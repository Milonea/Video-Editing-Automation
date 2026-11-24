from fractions import Fraction

import pytest

from vea.instruction_parser import parse_instructions
from vea.models import FrameRate
from vea.timecode import parse_timecode, seconds_to_frames


def test_parse_seconds_and_milliseconds():
    assert parse_timecode("03:20") == 200
    assert parse_timecode("01:02:03.250") == Fraction(14893, 4)
    assert parse_timecode("00:00:01,125") == Fraction(9, 8)


def test_parse_fractional_rates_and_drop_frame():
    fps = FrameRate.parse("29.97")
    assert fps.value == Fraction(30000, 1001)
    assert seconds_to_frames(Fraction(60), fps) == 1798
    assert parse_timecode("00:01:00;02", fps) == Fraction(1800 * 1001, 30000)
    with pytest.raises(ValueError, match="Illegal dropped"):
        parse_timecode("00:01:00;00", fps)
    with pytest.raises(ValueError, match="explicit FPS"):
        parse_timecode("00:00:00:12")


def test_natural_parser_keeps_only_explicit_ranges():
    request = "\n".join(
        [
            "00:03:20~00:04:15 유지",
            "00:12:10~00:13:40 사용",
            "00:28:00~00:29:20 보스전",
            "00:40:00 여기서 컷",
        ]
    )
    result = parse_instructions(request, source_file="/tmp/source.mkv", fps=FrameRate.parse(30), duration=3600)
    assert [edit.action for edit in result.edits] == ["keep", "keep", "unknown", "cut_at"]
    assert result.edits[0].source_in == 200
    assert result.edits[0].source_out == 255
    assert result.edits[2].interpretation_status == "needs_review"
    assert result.edits[3].source_out is None
    assert result.interpretation_status == "needs_review"


def test_full_request_global_sequence_applies_to_unlabeled_ranges():
    request = """새 영상편집 의뢰가 들어왔어.
원본: gameplay.mkv
00:03:20~00:04:15 유지
00:12:10~00:13:40 사용
00:28:00~00:29:20 보스전
순서대로 붙여주고, 게임 사운드와 마이크도 살려줘.
"""
    result = parse_instructions(request, source_file="gameplay.mkv", fps=FrameRate.parse(30), duration=3600)
    assert [edit.action for edit in result.edits] == ["keep", "keep", "keep"]
    assert result.edits[2].label == "보스전"
    assert result.validation_status == "valid"


def test_structured_ordering_is_validated_and_preserved():
    result = parse_instructions(
        '{"edits":['
        '{"source_in":"00:00:05","source_out":"00:00:06","action":"keep","ordering":2},'
        '{"source_in":"00:00:01","source_out":"00:00:02","action":"keep","ordering":1}'
        ']}',
        duration=10,
    )
    assert [edit.ordering for edit in result.edits] == [2, 1]
    assert result.validation_status == "valid"

    duplicate = parse_instructions(
        '{"edits":['
        '{"source_in":"00:00:05","source_out":"00:00:06","action":"keep","ordering":1},'
        '{"source_in":"00:00:01","source_out":"00:00:02","action":"keep","ordering":1}'
        ']}',
        duration=10,
    )
    assert duplicate.validation_status == "needs_review"
    assert [edit.validation_status for edit in duplicate.edits] == ["valid", "invalid_order"]

    invalid = parse_instructions(
        '{"edits":[{"source_in":"00:00:01","source_out":"00:00:02","action":"keep","ordering":0}]}',
        duration=10,
    )
    assert invalid.edits[0].validation_status == "invalid_order"


def test_single_timecode_is_not_extended_to_range():
    result = parse_instructions("00:12:10", duration=1000)
    assert len(result.edits) == 1
    assert result.edits[0].action == "unknown"
    assert result.edits[0].source_out is None


def test_explicit_cut_at_creates_a_non_destructive_boundary(tmp_path):
    from vea.timeline import build_timeline

    source = tmp_path / "source.mkv"
    source.touch()
    result = parse_instructions("00:00:05 여기서 컷", source_file=str(source), duration=10)
    assert result.edits[0].action == "cut_at"
    assert result.validation_status == "valid"
    clips = build_timeline(result.edits, source, Fraction(10), FrameRate.parse(30))
    assert [(clip.source_in_seconds, clip.source_out_seconds) for clip in clips] == [
        (Fraction(0), Fraction(5)),
        (Fraction(5), Fraction(10)),
    ]


def test_json_and_csv_formats():
    result = parse_instructions(
        '{"edits":[{"source_in":"00:00:01","source_out":"00:00:02","action":"keep","label":"intro"}]}',
        duration=10,
    )
    assert result.edits[0].label == "intro"
    assert result.edits[0].validation_status == "valid"

    csv_text = "source_in,source_out,action,label\n00:00:02,00:00:03,delete,remove"
    csv_result = parse_instructions(csv_text, duration=10)
    assert csv_result.edits[0].action == "delete"
    assert csv_result.edits[0].source_in == 2


def test_out_of_range_and_overlap_are_flagged():
    result = parse_instructions(
        "00:00:01~00:00:04 유지\n00:00:03~00:00:05 유지\n00:00:09~00:00:11 유지",
        duration=10,
    )
    assert any("겹치는 구간" in issue for issue in result.issues)
    assert any("초과" in issue for issue in result.issues)


def test_natural_padding_expands_the_same_timeline_used_by_audio_and_xml(tmp_path):
    from vea.timeline import build_timeline

    source = tmp_path / "source.mkv"
    source.touch()
    result = parse_instructions(
        "00:00:10~00:00:20 유지, 앞뒤 2초 여유 추가\n"
        "00:00:30~00:00:40 유지, 앞 1초 뒤 3초 여유",
        source_file=str(source),
        fps=FrameRate.parse(30),
        duration=60,
    )

    assert [(edit.padding_before, edit.padding_after) for edit in result.edits] == [
        (Fraction(2), Fraction(2)),
        (Fraction(1), Fraction(3)),
    ]
    clips = build_timeline(result.edits, source, Fraction(60), FrameRate.parse(30))
    assert [(clip.source_in_seconds, clip.source_out_seconds) for clip in clips] == [
        (Fraction(8), Fraction(22)),
        (Fraction(29), Fraction(43)),
    ]

    overlap = parse_instructions(
        "00:00:10~00:00:12 유지, 앞뒤 2초 여유\n00:00:13~00:00:15 유지",
        duration=30,
    )
    assert all(edit.validation_status == "overlap" for edit in overlap.edits)


def test_structured_padding_formats_and_source_bounds():
    result = parse_instructions(
        '{"edits":[{"source_in":"00:00:02","source_out":"00:00:05",'
        '"action":"keep","padding":{"before_seconds":1,"after_seconds":2}}]}',
        duration=10,
    )
    assert result.edits[0].padding_before == 1
    assert result.edits[0].padding_after == 2
    assert result.edits[0].validation_status == "valid"

    csv_result = parse_instructions(
        "source_in,source_out,action,padding_before_seconds,padding_after_seconds\n"
        "00:00:02,00:00:03,keep,0.5,1",
        duration=10,
    )
    assert (csv_result.edits[0].padding_before, csv_result.edits[0].padding_after) == (
        Fraction(1, 2),
        Fraction(1),
    )

    out_of_range = parse_instructions(
        '{"edits":[{"source_in":"00:00:08","source_out":"00:00:10",'
        '"action":"keep","padding_after_seconds":1}]}',
        duration=10,
    )
    assert out_of_range.edits[0].validation_status == "out_of_range"


def test_range_audio_mute_keeps_video_but_mutes_audio():
    natural = parse_instructions("00:00:01~00:00:02 오디오 음소거", duration=10)
    assert natural.edits[0].action == "keep"
    assert natural.edits[0].mute_audio is True
    assert natural.validation_status == "valid"

    structured = parse_instructions(
        '{"edits":[{"source_in":1,"source_out":2,"action":"keep","audio_action":"mute"}]}',
        duration=10,
    )
    assert structured.edits[0].mute_audio is True

    keep_audio = parse_instructions("00:00:01~00:00:02 오디오 음소거 하지 마", duration=10)
    assert keep_audio.edits[0].mute_audio is False
