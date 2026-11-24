"use strict";

const { TimelinePlan } = require("./timeline-plan-ir");
const {
  PlannerValidationError,
  asError,
  cloneValue,
  normalizeLocks,
  normalizeProvenance,
  normalizeSource,
  plannerResult,
  requireNumber,
  requireObject,
  requireString,
  sourceFingerprint,
  trackKey
} = require("./editing-planner-utils");

const UNSAFE_BOUNDARY_TYPES = new Set(["transition", "nested", "multicam", "speed_change", "speed-change", "time_remap"]);

function normalizeBoundary(boundary, index) {
  requireObject(boundary, `boundary_items[${index}]`);
  const type = requireString(boundary.type || boundary.kind || "", `boundary_items[${index}].type`).toLowerCase();
  const start = requireNumber(boundary.start, `boundary_items[${index}].start`);
  const duration = boundary.duration === undefined
    ? requireNumber(boundary.end, `boundary_items[${index}].end`) - start
    : requireNumber(boundary.duration, `boundary_items[${index}].duration`, { positive: true });
  if (duration <= 0) throw new PlannerValidationError(`boundary_items[${index}] end must be greater than start`, "invalid_boundary");
  return { id: requireString(boundary.id || `boundary-${index + 1}`, `boundary_items[${index}].id`), type, start, duration, track_group: boundary.track_group || null };
}

function normalizeInterval(interval, index) {
  requireObject(interval, `intervals[${index}]`);
  const id = requireString(interval.id || interval.interval_id || `pause-${index + 1}`, `intervals[${index}].id`);
  const start = requireNumber(interval.start, `intervals[${index}].start`);
  const end = requireNumber(interval.end, `intervals[${index}].end`);
  if (end <= start) throw new PlannerValidationError(`intervals[${index}] end must be greater than start`, "invalid_interval");
  const padding = interval.padding === undefined ? 0 : requireNumber(interval.padding, `intervals[${index}].padding`);
  const trackGroup = interval.track_group === undefined ? "all" : requireString(String(interval.track_group), `intervals[${index}].track_group`);
  const approval = interval.approved === true || interval.approval === true;
  if (!approval) throw new PlannerValidationError(`interval ${id} requires explicit approval`, "interval_not_approved");
  const provenance = normalizeProvenance(interval.provenance, `intervals[${index}].provenance`);
  return {
    id,
    start,
    end,
    duration: end - start,
    padding,
    track_group: trackGroup,
    approved: true,
    provenance,
    boundary_types: Array.isArray(interval.boundary_types) ? interval.boundary_types.map((value) => String(value).toLowerCase()) : []
  };
}

function intervalOverlaps(left, right) {
  return left.start < right.start + right.duration && right.start < left.start + left.duration;
}

function normalizeIntervals(intervals) {
  if (!Array.isArray(intervals) || !intervals.length) throw new PlannerValidationError("intervals must be a non-empty array", "invalid_intervals");
  const values = intervals.map(normalizeInterval).sort((left, right) => left.start - right.start || left.end - right.end || left.id.localeCompare(right.id));
  const ids = new Set();
  for (const value of values) {
    if (ids.has(value.id)) throw new PlannerValidationError(`duplicate interval id: ${value.id}`, "duplicate_interval_id");
    ids.add(value.id);
  }
  const merged = [];
  for (const value of values) {
    const previous = merged[merged.length - 1];
    if (previous && value.start <= previous.end && value.track_group === previous.track_group) {
      previous.end = Math.max(previous.end, value.end);
      previous.duration = previous.end - previous.start;
      previous.padding = Math.max(previous.padding, value.padding);
      previous.merged_from.push(value.id);
      previous.provenance = previous.provenance.source_id <= value.provenance.source_id ? previous.provenance : value.provenance;
      previous.boundary_types = Array.from(new Set(previous.boundary_types.concat(value.boundary_types))).sort();
    } else {
      merged.push({ ...value, merged_from: [value.id] });
    }
  }
  return { source: values, merged };
}

function detectUnsafeBoundaries(intervals, boundaryItems) {
  const boundaries = boundaryItems.map(normalizeBoundary);
  const unsafe = [];
  for (const interval of intervals) {
    for (const type of interval.boundary_types) {
      if (UNSAFE_BOUNDARY_TYPES.has(type)) unsafe.push({ interval_id: interval.id, type, source: "interval" });
    }
    for (const boundary of boundaries) {
      if (intervalOverlaps(interval, boundary) && UNSAFE_BOUNDARY_TYPES.has(boundary.type)) {
        unsafe.push({ interval_id: interval.id, boundary_id: boundary.id, type: boundary.type, source: "timeline" });
      }
    }
  }
  return unsafe;
}

function planPauseRemoval({
  source,
  intervals,
  boundaryItems = [],
  lockedTracks = [],
  allowCut = false,
  futureCutGate = {},
  plannerId = "pause-removal",
  provenance
} = {}) {
  try {
    const normalizedSource = normalizeSource(source);
    const normalized = normalizeIntervals(intervals);
    const locks = normalizeLocks(lockedTracks);
    const groups = Array.from(new Set(normalized.merged.map((interval) => interval.track_group)));
    const lockedGroups = groups.filter((group) => group !== "all" && locks.has(String(group).toLowerCase()));
    if (lockedGroups.length) throw new PlannerValidationError(`locked pause track group: ${lockedGroups.join(", ")}`, "locked_track");
    const unsafeBoundaries = detectUnsafeBoundaries(normalized.merged, boundaryItems);
    if (unsafeBoundaries.length) throw new PlannerValidationError("pause interval crosses an unsafe editing boundary", "unsafe_boundary", unsafeBoundaries.map((item) => JSON.stringify(item)));
    const gate = {
      public_range_split_api: futureCutGate.public_range_split_api === true,
      sync_preservation_proof: futureCutGate.sync_preservation_proof === true,
      rollback_proof: futureCutGate.rollback_proof === true,
      host_version_verified: futureCutGate.host_version_verified === true
    };
    const cutEnabled = allowCut && Object.values(gate).every(Boolean);
    const sourceProvenance = provenance ? normalizeProvenance(provenance, "provenance") : { source_id: `pause-planner:${normalizedSource.sequence_id}` };
    const markers = normalized.merged.map((interval) => ({
      id: `pause-marker:${interval.id}`,
      name: "approved-pause",
      start: interval.start,
      end: interval.end,
      duration: interval.duration,
      track_group: interval.track_group,
      provenance: interval.provenance || sourceProvenance,
      metadata: { padding: interval.padding, merged_from: interval.merged_from }
    }));
    const plan = new TimelinePlan({
      schema_version: 1,
      plan_id: `${plannerId}@1`,
      sequence_id: normalizedSource.sequence_id,
      operations: [],
      metadata: {
        planner: "pause-removal",
        planner_version: 1,
        source_guid: normalizedSource.guid,
        source_fingerprint: sourceFingerprint(source),
        mode: cutEnabled ? "clone-and-cut" : "clone-and-mark",
        markers,
        interval_ids: normalized.merged.map((interval) => interval.id),
        approved_intervals: normalized.merged.every((interval) => interval.approved),
        clone_only: true,
        source_mutation_forbidden: true,
        future_cut_gate: gate
      }
    });
    const plannedRemovalDuration = normalized.merged.reduce((sum, interval) => sum + interval.duration + interval.padding * 2, 0);
    return plannerResult({
      status: "dry_run",
      stage: "dry_run_plan",
      source,
      plan,
      extra: {
        mode: cutEnabled ? "clone-and-cut" : "clone-and-mark",
        markers,
        interval_count: normalized.merged.length,
        merged_interval_count: normalized.merged.length,
        source_interval_count: normalized.source.length,
        planned_removal_duration: plannedRemovalDuration,
        clone_required: true,
        cut_status: cutEnabled ? "gate_passed_but_host_execution_not_implemented" : "disabled_until_gate",
        future_cut_gate: gate,
        host_validation_status: "not_run"
      }
    });
  } catch (error) {
    return plannerResult({ status: "preflight_failed", stage: "preflight", source, errors: [asError(error)], extra: { clone_required: true, source_mutation_forbidden: true } });
  }
}

function cloneInventory(source) {
  return cloneValue(source.inventory).sort((left, right) => String(typeof left === "string" ? left : left.id).localeCompare(String(typeof right === "string" ? right : right.id)));
}

function executePauseRemoval({
  source,
  adapter,
  expectedSourceFingerprint = null,
  dryRun = true,
  approval = false,
  ...options
} = {}) {
  const planned = planPauseRemoval({ source, ...options });
  if (planned.status !== "dry_run") return planned;
  if (!adapter) return planned;
  const currentFingerprint = sourceFingerprint(source);
  if (expectedSourceFingerprint && expectedSourceFingerprint !== currentFingerprint) {
    return plannerResult({ status: "fingerprint_changed", stage: "source_fingerprint", source, plan: planned.plan, errors: [{ code: "expected_fingerprint_mismatch", message: "source fingerprint differs before execution" }], extra: { clone_status: "not_created" } });
  }
  if (dryRun) return { ...planned, stage: "dry_run_plan", approval_required: true, clone_status: "not_created" };
  for (const method of ["cloneSequence", "addMarkers", "preview"]) {
    if (typeof adapter[method] !== "function") {
      return plannerResult({ status: "preflight_failed", stage: "preflight", source, plan: planned.plan, errors: [{ code: "invalid_adapter", message: `adapter.${method} is required for clone-and-mark` }] });
    }
  }
  let clone = null;
  try {
    clone = adapter.cloneSequence(source);
    if (!clone || typeof clone !== "object" || typeof clone.guid !== "string" || clone.guid === source.guid) throw new PlannerValidationError("clone guid must differ from source", "clone_identity_mismatch");
    if (!Array.isArray(clone.inventory) || JSON.stringify(cloneInventory(clone)) !== JSON.stringify(cloneInventory(source))) throw new PlannerValidationError("clone inventory must match source", "clone_inventory_mismatch");
    if (sourceFingerprint(source) !== currentFingerprint) throw new PlannerValidationError("source changed before marker mutation", "source_changed_during_preflight");
    const mutation = adapter.addMarkers(clone, planned.markers);
    if (mutation && mutation.failed && mutation.failed.length) throw new PlannerValidationError("marker mutation failed", "marker_mutation_failed", mutation.failed.map((item) => JSON.stringify(item)));
    const preview = adapter.preview(clone, planned.plan);
    if (!approval) return plannerResult({ status: "awaiting_approval", stage: "user_approval", source, plan: planned.plan, extra: { clone_status: "retained_for_approval", clone_identity: clone.guid, preview, markers: planned.markers, approval_required: true } });
    const finalized = typeof adapter.finalizeClone === "function" ? adapter.finalizeClone(clone, planned.plan) : clone;
    return plannerResult({ status: "completed", stage: "final_use", source, plan: planned.plan, extra: { clone_status: "finalized", clone_identity: finalized.guid, preview, markers: planned.markers, approval_required: false, cut_status: "not_executed" } });
  } catch (error) {
    if (clone && typeof adapter.discardClone === "function") adapter.discardClone(clone);
    return plannerResult({ status: "mutation_failed", stage: "mutation_on_clone", source, plan: planned.plan, errors: [asError(error)], extra: { clone_status: "discarded", markers: planned.markers } });
  }
}

module.exports = {
  UNSAFE_BOUNDARY_TYPES,
  detectUnsafeBoundaries,
  executePauseRemoval,
  normalizeInterval,
  normalizeIntervals,
  planPauseRemoval
};

