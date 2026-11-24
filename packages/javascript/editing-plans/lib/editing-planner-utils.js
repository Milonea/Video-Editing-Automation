"use strict";

const { stableFingerprint } = require("./timeline-plan-ir");

class PlannerValidationError extends Error {
  constructor(message, code = "planner_validation", errors = []) {
    super(message);
    this.name = "PlannerValidationError";
    this.code = code;
    this.errors = errors.length ? errors : [message];
  }
}

function cloneValue(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function requireObject(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PlannerValidationError(`${field} must be an object`);
  }
  return value;
}

function requireString(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new PlannerValidationError(`${field} must be a non-empty string`);
  }
  return value.normalize("NFC").trim();
}

function requireNumber(value, field, { integer = false, positive = false } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || (integer && !Number.isInteger(value)) || (positive ? value <= 0 : value < 0)) {
    throw new PlannerValidationError(`${field} must be a finite ${positive ? "positive" : "non-negative"}${integer ? " integer" : " number"}`);
  }
  return value;
}

function normalizeTrack(value, field = "track", defaultTrack = null) {
  const input = value === undefined || value === null ? defaultTrack : value;
  requireObject(input, field);
  const type = String(input.type || input.kind || "").trim().toLowerCase();
  if (!["video", "audio"].includes(type)) throw new PlannerValidationError(`${field}.type must be video or audio`);
  const index = requireNumber(input.index, `${field}.index`, { integer: true });
  return { type, index };
}

function trackKey(track) {
  return `${track.type}:${track.index}`;
}

function normalizeLocks(lockedTracks = []) {
  const values = lockedTracks instanceof Set ? Array.from(lockedTracks) : lockedTracks;
  if (!Array.isArray(values)) throw new PlannerValidationError("locked_tracks must be an array or Set");
  return new Set(values.map((value) => {
    if (typeof value === "string") return value.toLowerCase();
    return trackKey(normalizeTrack(value, "locked_tracks[]"));
  }));
}

function normalizeProvenance(value, field = "provenance") {
  requireObject(value, field);
  return {
    source_id: requireString(value.source_id || value.sourceId || "", `${field}.source_id`),
    ...(value.source_url === undefined ? {} : { source_url: requireString(value.source_url, `${field}.source_url`) }),
    ...(value.captured_at === undefined ? {} : { captured_at: requireString(value.captured_at, `${field}.captured_at`) }),
    ...(value.note === undefined ? {} : { note: requireString(value.note, `${field}.note`) })
  };
}

function normalizeSource(source) {
  requireObject(source, "source_sequence");
  const guid = requireString(source.guid, "source_sequence.guid");
  if (!Array.isArray(source.inventory)) throw new PlannerValidationError("source_sequence.inventory must be an array", "invalid_source_inventory");
  const sequenceId = requireString(source.sequence_id || source.sequenceId || guid, "source_sequence.sequence_id");
  return { guid, sequence_id: sequenceId, inventory: cloneValue(source.inventory), source };
}

function sourceFingerprint(source) {
  const normalized = normalizeSource(source);
  return stableFingerprint({
    guid: normalized.guid,
    sequence_id: normalized.sequence_id,
    inventory: normalized.inventory,
    duration: source.duration === undefined ? null : source.duration,
    settings: source.settings === undefined ? null : source.settings
  });
}

function inventoryIds(inventory) {
  if (inventory === undefined || inventory === null) return null;
  const values = inventory instanceof Set ? Array.from(inventory) : inventory;
  if (Array.isArray(values)) return new Set(values.map((item) => typeof item === "string" ? item : item && item.id).filter(Boolean).map(String));
  if (typeof values === "object") return new Set(Object.keys(values).filter((key) => values[key]).map(String));
  throw new PlannerValidationError("asset_inventory must be an array, Set, or object");
}

function itemInterval(item, field = "existing_items[]") {
  requireObject(item, field);
  const start = requireNumber(item.start, `${field}.start`);
  const duration = item.duration === undefined
    ? requireNumber(item.end, `${field}.end`) - start
    : requireNumber(item.duration, `${field}.duration`, { positive: true });
  if (duration <= 0) throw new PlannerValidationError(`${field} must have end greater than start`);
  const track = normalizeTrack(item.track, `${field}.track`);
  return { id: requireString(item.id || `${field}:${start}`, `${field}.id`), start, duration, track };
}

function overlaps(left, right) {
  return left.start < right.start + right.duration && right.start < left.start + left.duration;
}

function collectExistingItems(source, explicitItems = []) {
  const sourceItems = Array.isArray(source.items) ? source.items : [];
  return sourceItems.concat(explicitItems || []).map((item, index) => itemInterval(item, `existing_items[${index}]`));
}

function findCollisions(operations, existingItems) {
  const collisions = [];
  for (const operation of operations) {
    for (const item of existingItems) {
      if (trackKey(operation.track) === trackKey(item.track) && overlaps(operation, item)) {
        collisions.push({ operation_id: operation.id, item_id: item.id, track: trackKey(operation.track) });
      }
    }
  }
  return collisions;
}

function plannerResult({ status, stage = "preflight", source, plan = null, errors = [], warnings = [], extra = {} }) {
  return {
    schema_version: 1,
    status,
    stage,
    plan: plan ? (typeof plan.toObject === "function" ? plan.toObject() : cloneValue(plan)) : null,
    source_fingerprint: source ? sourceFingerprint(source) : null,
    source_mutations: 0,
    external_writes: 0,
    errors: cloneValue(errors),
    warnings: cloneValue(warnings),
    ...cloneValue(extra)
  };
}

function asError(error, fallbackCode = "planner_validation") {
  return {
    code: error && error.code ? error.code : fallbackCode,
    message: error && error.message ? error.message : String(error),
    details: error && Array.isArray(error.errors) ? cloneValue(error.errors) : []
  };
}

module.exports = {
  PlannerValidationError,
  asError,
  cloneValue,
  collectExistingItems,
  findCollisions,
  inventoryIds,
  normalizeLocks,
  normalizeProvenance,
  normalizeSource,
  normalizeTrack,
  overlaps,
  plannerResult,
  requireNumber,
  requireObject,
  requireString,
  sourceFingerprint,
  trackKey
};

