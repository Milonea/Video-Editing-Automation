"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { buildTargetedCutPlan, validateCompletedCandidates } = require("../cut_plan.js");

const candidate = (id, start, end) => ({
  candidate_id: id,
  candidate_type: "inter_caption",
  start_frame: start,
  end_frame: end,
});

test("plans only selected tracks with a clip spanning each candidate boundary", () => {
  const plan = buildTargetedCutPlan(
    [candidate("SILENCE_001", 20, 80)],
    [
      { media_type: "VIDEO", track_index: 0, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
      { media_type: "AUDIO", track_index: 0, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
      { media_type: "AUDIO", track_index: 1, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
    ],
    [{ media_type: "VIDEO", track_index: 0 }, { media_type: "AUDIO", track_index: 1 }],
  );

  assert.deepEqual(plan.actions.map((action) => `${action.media_type}:${action.track_index}:${action.frame}`), [
    "VIDEO:0:20",
    "AUDIO:1:20",
    "VIDEO:0:80",
    "AUDIO:1:80",
  ]);
  assert.equal(plan.candidate_outcomes[0].start_covered, true);
  assert.equal(plan.candidate_outcomes[0].end_covered, true);
});

test("cuts every explicitly selected video track and only opted-in audio tracks", () => {
  const plan = buildTargetedCutPlan(
    [candidate("SILENCE_001", 20, 80)],
    [
      { media_type: "VIDEO", track_index: 0, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
      { media_type: "VIDEO", track_index: 1, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
      { media_type: "AUDIO", track_index: 0, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
      { media_type: "AUDIO", track_index: 1, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
    ],
    [{ media_type: "VIDEO", track_index: 0 }, { media_type: "VIDEO", track_index: 1 }, { media_type: "AUDIO", track_index: 1 }],
  );

  assert.deepEqual(
    plan.actions.map((action) => `${action.media_type}:${action.track_index}:${action.frame}`),
    [
      "VIDEO:0:20", "VIDEO:1:20", "AUDIO:1:20",
      "VIDEO:0:80", "VIDEO:1:80", "AUDIO:1:80",
    ],
  );
  assert.equal(plan.actions.some((action) => action.type === "delete"), false);
});

test("deduplicates shared frames and skips boundaries that are already cuts", () => {
  const plan = buildTargetedCutPlan(
    [candidate("SILENCE_001", 20, 40), candidate("SILENCE_002", 40, 60)],
    [{
      media_type: "VIDEO",
      track_index: 0,
      intervals: [{ start_frame: 0, end_frame: 100 }],
      boundary_frames: [40],
    }],
    [{ media_type: "VIDEO", track_index: 0 }],
  );

  assert.deepEqual(plan.boundaries.map((boundary) => boundary.frame), [20, 40, 60]);
  assert.equal(plan.actions.filter((action) => action.frame === 40).length, 0);
  assert.equal(plan.boundaries.find((boundary) => boundary.frame === 40).covered_targets.length, 1);
});

test("keeps sequence-edge review candidates out of split actions", () => {
  const plan = buildTargetedCutPlan(
    [
      { candidate_id: "EDGE_HEAD", candidate_type: "sequence_head", start_frame: 0, end_frame: 20 },
      candidate("SILENCE_001", 20, 40),
    ],
    [{ media_type: "VIDEO", track_index: 0, intervals: [{ start_frame: 0, end_frame: 60 }], boundary_frames: [] }],
    [{ media_type: "VIDEO", track_index: 0 }],
  );

  assert.deepEqual(plan.actions.map((action) => action.frame), [20, 40]);
  assert.deepEqual(plan.candidate_outcomes.map((outcome) => outcome.candidate_id), ["SILENCE_001"]);
});

test("reports incomplete candidate boundaries after runtime verification", () => {
  const plan = buildTargetedCutPlan(
    [candidate("SILENCE_001", 20, 80), candidate("SILENCE_002", 40, 90)],
    [{ media_type: "VIDEO", track_index: 0, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] }],
    [{ media_type: "VIDEO", track_index: 0 }],
  );
  const checked = validateCompletedCandidates(plan, ["VIDEO:0:20", "VIDEO:0:40", "VIDEO:0:80"]);

  assert.equal(checked[0].complete, true);
  assert.equal(checked[1].complete, false);
});

test("does not report a candidate complete until every covered selected track has both cuts", () => {
  const plan = buildTargetedCutPlan(
    [candidate("SILENCE_001", 20, 80)],
    [
      { media_type: "VIDEO", track_index: 0, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
      { media_type: "AUDIO", track_index: 1, intervals: [{ start_frame: 0, end_frame: 100 }], boundary_frames: [] },
    ],
    [{ media_type: "VIDEO", track_index: 0 }, { media_type: "AUDIO", track_index: 1 }],
  );

  const videoOnly = validateCompletedCandidates(plan, ["VIDEO:0:20", "VIDEO:0:80"]);
  assert.equal(videoOnly[0].start_cut_verified, false);
  assert.equal(videoOnly[0].end_cut_verified, false);
  assert.equal(videoOnly[0].complete, false);

  const everyTrack = validateCompletedCandidates(plan, [
    "VIDEO:0:20", "VIDEO:0:80", "AUDIO:1:20", "AUDIO:1:80",
  ]);
  assert.equal(everyTrack[0].complete, true);
});
