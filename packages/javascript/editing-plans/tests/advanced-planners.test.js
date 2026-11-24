"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { MockEditingAdapter } = require("../lib/safe-editing-primitive");
const { executeCaptionEffects, planCaptionEffects } = require("../lib/caption-effect-planner");
const { executeImageReplacement, planImageReplacement } = require("../lib/image-replacement-planner");
const { executePauseRemoval, planPauseRemoval } = require("../lib/pause-removal-planner");

function source() {
  return {
    guid: "source-guid",
    sequence_id: "source-sequence",
    inventory: [{ id: "base-video", track: { type: "video", index: 0 }, start: 0, duration: 60 }]
  };
}

const provenance = { source_id: "captured:fixture", captured_at: "2026-08-26" };

test("caption planner produces deterministic clone-only MOGRT operations from ticks", () => {
  const input = {
    source: source(),
    cues: [
      { cue_id: "cue-2", start_ticks: 254016000 * 4, end_ticks: 254016000 * 6, provenance },
      { cue_id: "cue-1", start_ticks: 0, end_ticks: 254016000 * 2, provenance }
    ],
    template: { id: "caption.mogrt", kind: "mogrt", controls: ["Text"] },
    assetInventory: ["caption.mogrt"],
    ticksPerSecond: 254016000,
    existingItems: [{ id: "unrelated", track: { type: "video", index: 0 }, start: 0, duration: 60 }]
  };
  const first = planCaptionEffects(input);
  const second = planCaptionEffects(input);
  assert.equal(first.status, "dry_run");
  assert.deepEqual(first.plan, second.plan);
  assert.deepEqual(first.plan.operations.map((operation) => operation.id), ["caption-effect:cue-1", "caption-effect:cue-2"]);
  assert.equal(first.plan.metadata.caption_mutation, false);
  assert.equal(first.source_mutations, 0);
  assert.equal(first.external_writes, 0);
});

test("caption planner rejects duplicate, overlapping, locked, colliding, and missing-template inputs", () => {
  const base = {
    source: source(),
    cues: [{ cue_id: "a", start: 0, end: 3, provenance }],
    template: { id: "caption.mogrt", kind: "mogrt" },
    assetInventory: ["caption.mogrt"]
  };
  assert.equal(planCaptionEffects({ ...base, cues: [
    { cue_id: "a", start: 0, end: 3, provenance },
    { cue_id: "a", start: 4, end: 5, provenance }
  ] }).errors[0].code, "duplicate_cue_id");
  assert.equal(planCaptionEffects({ ...base, cues: [
    { cue_id: "a", start: 0, end: 3, provenance },
    { cue_id: "b", start: 2, end: 5, provenance }
  ] }).errors[0].code, "overlapping_cues");
  assert.equal(planCaptionEffects({ ...base, lockedTracks: ["video:1"] }).errors[0].code, "locked_track");
  assert.equal(planCaptionEffects({ ...base, existingItems: [{ id: "occupied", track: { type: "video", index: 1 }, start: 1, duration: 1 }] }).errors[0].code, "timeline_collision");
  assert.equal(planCaptionEffects({ ...base, assetInventory: [] }).errors[0].code, "missing_template");
});

test("caption execution keeps source unchanged and rechecks the fingerprint", () => {
  const original = source();
  const before = JSON.stringify(original);
  const adapter = new MockEditingAdapter({ assetInventory: ["caption.mogrt"] });
  const result = executeCaptionEffects({
    source: original,
    adapter,
    cues: [{ cue_id: "cue-1", start: 0, end: 2, provenance }],
    template: { id: "caption.mogrt" },
    assetInventory: ["caption.mogrt"],
    approval: true,
    dryRun: false
  });
  assert.equal(result.status, "completed");
  assert.equal(result.source_mutations, 0);
  assert.equal(JSON.stringify(original), before);

  const changed = executeCaptionEffects({
    source: original,
    adapter: new MockEditingAdapter({ assetInventory: ["caption.mogrt"] }),
    expectedSourceFingerprint: "stale",
    cues: [{ cue_id: "cue-1", start: 0, end: 2, provenance }],
    template: { id: "caption.mogrt" },
    assetInventory: ["caption.mogrt"],
    dryRun: false
  });
  assert.equal(changed.status, "fingerprint_changed");
  assert.equal(changed.clone_status, "not_created");
});

test("image planner only plans isolated insertion and never global relink", () => {
  const result = planImageReplacement({
    source: source(),
    target: { asset_id: "subject-image.png", path: "subject-image.png", format: "png", start: 4, duration: 2, width: 1920, height: 1080, alpha: "preserved", crop: "fit", placeholder: "none" },
    assetInventory: ["subject-image.png"],
    provenance
  });
  assert.equal(result.status, "dry_run");
  assert.equal(result.global_media_relink, false);
  assert.equal(result.source_project_item_mutations, 0);
  assert.equal(result.plan.metadata.global_media_relink, false);
  assert.equal(result.plan.operations[0].metadata.forbidden_api, "changeMediaFilePath");
});

test("image planner fails closed for unsupported media slots and unsafe targets", () => {
  const base = {
    source: source(),
    target: { asset_id: "subject-image.png", path: "subject-image.png", format: "png", start: 4, duration: 2 },
    assetInventory: ["subject-image.png"]
  };
  const unsupported = planImageReplacement({ ...base, mode: "mogrt_media_slot", template: { id: "card.mogrt", media_slot_id: "hero", media_slot_assignment_supported: false } });
  assert.equal(unsupported.status, "unsupported");
  assert.equal(unsupported.errors[0].code, "media_slot_assignment_unverified");
  assert.equal(planImageReplacement({ ...base, lockedTracks: ["video:1"] }).errors[0].code, "locked_track");
  assert.equal(planImageReplacement({ ...base, existingItems: [{ id: "occupied", track: { type: "video", index: 1 }, start: 4.5, duration: 1 }] }).errors[0].code, "timeline_collision");
  assert.equal(planImageReplacement({ ...base, assetInventory: [] }).errors[0].code, "missing_image_asset");
});

test("image execution preserves source and clone-only mutation contract", () => {
  const original = source();
  const before = JSON.stringify(original);
  const result = executeImageReplacement({
    source: original,
    adapter: new MockEditingAdapter({ assetInventory: ["subject-image.png"] }),
    target: { asset_id: "subject-image.png", path: "subject-image.png", format: "png", start: 4, duration: 2 },
    assetInventory: ["subject-image.png"],
    approval: true,
    dryRun: false
  });
  assert.equal(result.status, "completed");
  assert.equal(result.global_media_relink, false);
  assert.equal(JSON.stringify(original), before);
});

function markerAdapter({ fail = false } = {}) {
  const adapter = {
    discarded: [],
    cloneSequence(value) {
      return { ...JSON.parse(JSON.stringify(value)), guid: `${value.guid}-clone`, markers: [] };
    },
    addMarkers(clone, markers) {
      if (fail) return { failed: [{ id: markers[0].id, reason: "fixture_failure" }] };
      clone.markers.push(...JSON.parse(JSON.stringify(markers)));
      return { applied: markers.map((marker) => marker.id), failed: [] };
    },
    preview(clone) {
      return { clone_guid: clone.guid, marker_count: clone.markers.length };
    },
    discardClone(clone) { this.discarded.push(clone.guid); },
    finalizeClone(clone) { clone.finalized = true; return clone; }
  };
  return adapter;
}

test("pause planner merges approved intervals and only emits markers", () => {
  const input = {
    source: source(),
    intervals: [
      { id: "pause-b", start: 4, end: 6, padding: 0.25, track_group: "all", approved: true, provenance },
      { id: "pause-a", start: 3, end: 5, padding: 0.1, track_group: "all", approved: true, provenance }
    ]
  };
  const result = planPauseRemoval(input);
  assert.equal(result.status, "dry_run");
  assert.equal(result.mode, "clone-and-mark");
  assert.equal(result.source_interval_count, 2);
  assert.equal(result.merged_interval_count, 1);
  assert.equal(result.markers[0].start, 3);
  assert.equal(result.markers[0].end, 6);
  assert.equal(result.plan.operations.length, 0);
  assert.equal(result.plan.metadata.source_mutation_forbidden, true);
});

test("pause planner blocks unapproved, locked, and unsafe intervals and disables cut without every gate", () => {
  const base = {
    source: source(),
    intervals: [{ id: "pause", start: 3, end: 6, track_group: "video:1", approved: true, provenance }]
  };
  assert.equal(planPauseRemoval({ ...base, intervals: [{ ...base.intervals[0], approved: false }] }).errors[0].code, "interval_not_approved");
  assert.equal(planPauseRemoval({ ...base, lockedTracks: ["video:1"] }).errors[0].code, "locked_track");
  assert.equal(planPauseRemoval({ ...base, boundaryItems: [{ id: "transition", type: "transition", start: 4, duration: 1 }] }).errors[0].code, "unsafe_boundary");
  const cut = planPauseRemoval({ ...base, allowCut: true, futureCutGate: { public_range_split_api: true, sync_preservation_proof: true, rollback_proof: false, host_version_verified: true } });
  assert.equal(cut.mode, "clone-and-mark");
  assert.equal(cut.cut_status, "disabled_until_gate");
});

test("pause execution adds markers only to a clone and discards on failure", () => {
  const original = source();
  const before = JSON.stringify(original);
  const args = {
    source: original,
    intervals: [{ id: "pause", start: 3, end: 6, approved: true, provenance }],
    dryRun: false,
    approval: true
  };
  const complete = executePauseRemoval({ ...args, adapter: markerAdapter() });
  assert.equal(complete.status, "completed");
  assert.equal(complete.clone_status, "finalized");
  assert.equal(complete.markers.length, 1);
  assert.equal(JSON.stringify(original), before);

  const failedAdapter = markerAdapter({ fail: true });
  const failed = executePauseRemoval({ ...args, adapter: failedAdapter });
  assert.equal(failed.status, "mutation_failed");
  assert.equal(failed.clone_status, "discarded");
  assert.deepEqual(failedAdapter.discarded, ["source-guid-clone"]);
  assert.equal(JSON.stringify(original), before);
});

