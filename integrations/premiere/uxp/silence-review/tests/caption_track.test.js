"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { resolveCaptionTrack } = require("../caption_track.js");

test("selects an exact caption track name among multiple tracks", () => {
  const tracks = [{ name: "C1" }, { name: "C2" }];
  assert.deepEqual(resolveCaptionTrack(tracks, "C2"), {
    track: tracks[1],
    matchedBy: "name",
  });
});

test("uses a sole host track when Premiere exposes a different caption label", () => {
  const track = { name: "Subtitle" };
  assert.deepEqual(resolveCaptionTrack([track], "C1"), {
    track,
    matchedBy: "only_track",
  });
});

test("rejects ambiguous mismatched or duplicate names", () => {
  assert.throws(
    () => resolveCaptionTrack([{ name: "Subtitle" }, { name: "C2" }], "C1"),
    /안전하게 확인할 수 없습니다/,
  );
  assert.throws(
    () => resolveCaptionTrack([{ name: "C1" }, { name: "C1" }], "C1"),
    /중복되어 모호합니다/,
  );
});
