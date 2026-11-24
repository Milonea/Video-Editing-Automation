"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { chooseSplitMode } = require("../split_mode.js");

const splitPlan = { actions: { implemented_mode: "split_with_review_marker_fallback" } };

test("uses Razor only when the per-track Razor API exists", () => {
  assert.equal(chooseSplitMode(splitPlan, { razorAvailable: true }), "razor");
  assert.equal(chooseSplitMode(splitPlan, {
    razorAvailable: false,
    trackEditApis: { cloneTrackItem: true },
  }), null);
});

test("does not split when the plan explicitly requests review markers only", () => {
  assert.equal(chooseSplitMode({ actions: { implemented_mode: "review_markers_only" } }, { razorAvailable: true }), null);
});

test("does not infer split support from a missing or incomplete context", () => {
  assert.equal(chooseSplitMode(splitPlan, {}), null);
  assert.equal(chooseSplitMode(null, { razorAvailable: true }), null);
});
