"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { TimelinePlan } = require("../lib/timeline-plan-ir");
const { ContractAdapterError, toContractEditPlan } = require("../legacy-contract-adapter");

function plan(overrides = {}) {
  return new TimelinePlan({
    plan_id: "fixture-plan",
    sequence_id: "sequence-main",
    operations: [{
      id: "title-card",
      action: "insert_mogrt",
      track: { type: "video", index: 1 },
      start: 1.2,
      duration: 2,
      asset: { id: "title-card", kind: "mogrt" },
      source_cue: { in: 0.4, out: 1.2 },
      provenance: { source_id: "fixture" },
      metadata: { template_role: "title" }
    }],
    ...overrides
  });
}

test("legacy seconds plan converts to the shared integer-frame EditPlan contract", () => {
  const result = toContractEditPlan(plan(), {
    projectId: "project-sample",
    sourceFingerprint: "sha256:fixture",
    frameRate: { numerator: 25, denominator: 1 }
  });
  assert.deepEqual(result, {
    schema_version: 1,
    plan_id: "fixture-plan",
    project_id: "project-sample",
    timeline_id: "sequence-main",
    source_fingerprint: "sha256:fixture",
    operations: [{
      operation_id: "title-card",
      action: "insert_mogrt",
      asset_id: "title-card",
      track: { track_id: "video-1", kind: "video", index: 1 },
      start_frame: 30,
      duration_frames: 50,
      collision_policy: "block",
      metadata: { template_role: "title", source_cue_frames: { in_frame: 10, out_frame: 30 } }
    }],
    approval_required: true,
    source_mutation: "forbid",
    status: "planned"
  });
});

test("legacy plan adapter refuses silent rounding of non-frame-aligned time", () => {
  const nonAligned = plan({ operations: [{
    id: "image",
    action: "insert_media",
    track: { type: "video", index: 1 },
    start: 0.1,
    duration: 1,
    asset: { id: "image", kind: "image" },
    provenance: { source_id: "fixture" }
  }] });
  assert.throws(() => toContractEditPlan(nonAligned, {
    projectId: "project-sample",
    sourceFingerprint: "sha256:fixture",
    frameRate: { numerator: 24, denominator: 1 }
  }), (error) => error instanceof ContractAdapterError && error.code === "NON_FRAME_ALIGNED_TIME");
});

test("legacy plan adapter blocks unknown operations instead of guessing their shared action", () => {
  const unsupported = plan({ operations: [{
    id: "text-edit",
    action: "set_text",
    track: { type: "video", index: 1 },
    start: 0,
    duration: 1,
    provenance: { source_id: "fixture" }
  }] });
  assert.throws(() => toContractEditPlan(unsupported, {
    projectId: "project-sample",
    sourceFingerprint: "sha256:fixture",
    frameRate: { numerator: 25, denominator: 1 }
  }), (error) => error instanceof ContractAdapterError && error.code === "UNSUPPORTED_LEGACY_ACTION");
});
