import json
from fractions import Fraction

import pytest

from vea.checkpoint import Checkpoint, atomic_write_text, canonical_hash, file_fingerprint
from vea.instruction_parser import parse_instructions
from vea.models import FrameRate
from vea.timecode import seconds_to_frames
from vea.timeline import TimelineError, build_timeline


def test_timeline_preserves_order_and_uses_integer_frames(tmp_path):
    source = tmp_path / "원본 파일.mkv"
    source.touch()
    parsed = parse_instructions(
        "00:00:02~00:00:03 유지\n00:00:00~00:00:01 유지",
        source_file=str(source),
        fps=FrameRate.parse("30000/1001"),
        duration=10,
    )
    clips = build_timeline(parsed.edits, source, Fraction(10), FrameRate.parse("30000/1001"))
    assert [clip.ordering for clip in clips] == [1, 2]
    assert [clip.timeline_start_frame for clip in clips] == [0, 30]
    assert clips[0].source_in_frame == seconds_to_frames(Fraction(2), FrameRate.parse("30000/1001"))


def test_explicit_reorder_controls_timeline_sequence(tmp_path):
    source = tmp_path / "source.mkv"
    source.touch()
    parsed = parse_instructions(
        '{"edits":['
        '{"source_in":"00:00:05","source_out":"00:00:06","action":"keep","ordering":2,"label":"second"},'
        '{"source_in":"00:00:01","source_out":"00:00:02","action":"keep","ordering":1,"label":"first"}'
        ']}',
        source_file=str(source),
        duration=10,
    )
    clips = build_timeline(parsed.edits, source, Fraction(10), FrameRate.parse(30))
    assert [clip.label for clip in clips] == ["first", "second"]
    assert [clip.timeline_start_frame for clip in clips] == [0, 30]


def test_ambiguous_overlapping_ranges_are_skipped_while_clear_ranges_continue(tmp_path):
    source = tmp_path / "source.mkv"
    source.touch()
    parsed = parse_instructions(
        "00:00:01~00:00:04 유지\n00:00:03~00:00:05 유지\n00:00:07~00:00:08 유지",
        source_file=str(source),
        duration=10,
    )
    clips = build_timeline(parsed.edits, source, Fraction(10), FrameRate.parse(30))
    assert len(clips) == 1
    assert clips[0].source_in_seconds == 7


def test_delete_ranges_build_complement(tmp_path):
    source = tmp_path / "source.mkv"
    source.touch()
    parsed = parse_instructions(
        '{"edits":[{"source_in":"00:00:02","source_out":"00:00:04","action":"delete"}]}',
        source_file=str(source),
        duration=10,
    )
    clips = build_timeline(parsed.edits, source, Fraction(10), FrameRate.parse(30))
    assert [(clip.source_in_seconds, clip.source_out_seconds) for clip in clips] == [(Fraction(0), Fraction(2)), (Fraction(4), Fraction(10))]


def test_edit_range_outside_source_fails(tmp_path):
    source = tmp_path / "source.mkv"
    source.touch()
    parsed = parse_instructions(
        '{"edits":[{"source_in":8,"source_out":12,"action":"keep"}]}',
        source_file=str(source),
        duration=10,
    )
    with pytest.raises(TimelineError):
        build_timeline(parsed.edits, source, Fraction(10), FrameRate.parse(30))


def test_checkpoint_cache_checks_signature_and_output(tmp_path):
    checkpoint = Checkpoint(tmp_path, "p1")
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    signature = canonical_hash({"input": 1})
    checkpoint.start("parse", signature, [output])
    checkpoint.complete("parse")
    assert checkpoint.cached("parse", signature, [output])
    assert not checkpoint.cached("parse", "changed", [output])
    output.unlink()
    assert not checkpoint.cached("parse", signature, [output])


def test_file_fingerprint_stat_and_hash(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    stat = file_fingerprint(source)
    full = file_fingerprint(source, full_hash=True)
    assert stat["hash_mode"] == "stat"
    assert full["sha256"] and full["size_bytes"] == 6


def test_atomic_text_write_keeps_previous_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "validation.md"
    target.write_text("previous valid report", encoding="utf-8")

    def fail_replace(_source, _target):
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr("vea.checkpoint.os.replace", fail_replace)
    with pytest.raises(PermissionError, match="simulated replace failure"):
        atomic_write_text(target, "new report")

    assert target.read_text(encoding="utf-8") == "previous valid report"
    assert list(tmp_path.glob(".validation.md.*.tmp")) == []


def test_corrupt_checkpoint_is_preserved(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text("{bad json", encoding="utf-8")
    checkpoint = Checkpoint(tmp_path, "p2")
    assert (tmp_path / "checkpoint.corrupt.json").read_text(encoding="utf-8") == "{bad json"
    assert json.loads(path.read_text(encoding="utf-8"))["project_id"] == "p2"
