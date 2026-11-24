"use strict";

/**
 * Host-neutral Timeline Plan IR.
 *
 * This file intentionally contains no UXP or Premiere imports.  It is the
 * seam between declarative plans, mock tests, and a future host adapter.
 */

const SUPPORTED_ACTIONS = new Set([
  "insert_media",
  "insert_mogrt",
  "insert_audio",
  "caption",
  "set_text"
]);
const COLLISION_POLICIES = new Set(["reject", "allow", "warn"]);

class PlanValidationError extends Error {
  constructor(message, errors = []) {
    super(message);
    this.name = "PlanValidationError";
    this.errors = errors;
  }
}

function requireString(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new PlanValidationError(`${field} must be a non-empty string`);
  }
  return value.normalize("NFC").trim();
}

function requireNonNegativeNumber(value, field) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new PlanValidationError(`${field} must be a finite non-negative number`);
  }
  return value;
}

function requirePositiveNumber(value, field) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new PlanValidationError(`${field} must be a finite positive number`);
  }
  return value;
}

function cloneValue(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    const result = {};
    for (const key of Object.keys(value).sort()) result[key] = canonicalize(value[key]);
    return result;
  }
  return value;
}

function canonicalStringify(value) {
  return JSON.stringify(canonicalize(value));
}

function stableFingerprint(value) {
  const text = canonicalStringify(value);
  let left = 2166136261;
  let right = 16777619;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    left = Math.imul(left ^ code, 16777619);
    right = Math.imul(right ^ ((code + index) & 0xff), 2246822519);
  }
  return `${(left >>> 0).toString(16).padStart(8, "0")}${(right >>> 0).toString(16).padStart(8, "0")}`;
}

function normalizeProvenance(value, field = "provenance") {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PlanValidationError(`${field} must be an object`);
  }
  const sourceId = requireString(value.source_id || value.sourceId || "", `${field}.source_id`);
  const result = { source_id: sourceId };
  if (value.source_url !== undefined) result.source_url = requireString(value.source_url, `${field}.source_url`);
  if (value.captured_at !== undefined) result.captured_at = requireString(value.captured_at, `${field}.captured_at`);
  if (value.note !== undefined) result.note = requireString(value.note, `${field}.note`);
  return result;
}

function normalizeTrack(value, field = "track") {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PlanValidationError(`${field} must be an object`);
  }
  const type = String(value.type || value.kind || "").trim().toLowerCase();
  if (!new Set(["video", "audio"]).has(type)) {
    throw new PlanValidationError(`${field}.type must be video or audio`);
  }
  if (!Number.isInteger(value.index) || value.index < 0) {
    throw new PlanValidationError(`${field}.index must be a non-negative integer`);
  }
  return { type, index: value.index };
}

function trackKey(track) {
  return `${track.type}:${track.index}`;
}

function normalizeAsset(value, field = "asset") {
  if (typeof value === "string") return { id: requireString(value, field), required: true };
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PlanValidationError(`${field} must be a string or object`);
  }
  const result = {
    id: requireString(value.id || value.asset_id || "", `${field}.id`),
    required: value.required !== false
  };
  if (value.kind !== undefined) result.kind = requireString(value.kind, `${field}.kind`);
  if (value.path !== undefined) result.path = requireString(value.path, `${field}.path`);
  return result;
}

function normalizeSourceCue(value) {
  if (value === undefined || value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PlanValidationError("source_cue must be an object");
  }
  const result = {};
  if (value.in !== undefined) result.in = requireNonNegativeNumber(value.in, "source_cue.in");
  if (value.out !== undefined) result.out = requireNonNegativeNumber(value.out, "source_cue.out");
  if (result.in === undefined && result.out === undefined) {
    throw new PlanValidationError("source_cue must contain in or out");
  }
  if (result.in !== undefined && result.out !== undefined && result.out <= result.in) {
    throw new PlanValidationError("source_cue.out must be greater than source_cue.in");
  }
  return result;
}

function normalizeOperation(value, index) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PlanValidationError(`operations[${index}] must be an object`);
  }
  const action = requireString(value.action, `operations[${index}].action`).toLowerCase();
  const operation = {
    id: requireString(value.id || `op-${index + 1}`, `operations[${index}].id`),
    action,
    track: normalizeTrack(value.track, `operations[${index}].track`),
    start: requireNonNegativeNumber(value.start, `operations[${index}].start`),
    duration: requirePositiveNumber(value.duration, `operations[${index}].duration`),
    asset: value.asset === undefined || value.asset === null ? null : normalizeAsset(value.asset, `operations[${index}].asset`),
    source_cue: normalizeSourceCue(value.source_cue),
    provenance: normalizeProvenance(value.provenance, `operations[${index}].provenance`),
    metadata: value.metadata && typeof value.metadata === "object" && !Array.isArray(value.metadata)
      ? cloneValue(value.metadata)
      : {}
  };
  const expectedTrack = action === "insert_audio" ? "audio" : "video";
  if (operation.track.type !== expectedTrack) {
    throw new PlanValidationError(`${operation.id} action ${action} requires a ${expectedTrack} track`);
  }
  if (["insert_media", "insert_mogrt", "insert_audio"].includes(action) && !operation.asset) {
    throw new PlanValidationError(`${operation.id} requires an asset`);
  }
  return operation;
}

class TimelinePlan {
  constructor(value = {}) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new PlanValidationError("plan must be an object");
    }
    this.schema_version = value.schema_version === undefined ? 1 : value.schema_version;
    if (this.schema_version !== 1) throw new PlanValidationError("unsupported plan schema_version");
    this.plan_id = requireString(value.plan_id || "timeline-plan", "plan_id");
    this.sequence_id = requireString(value.sequence_id || "sequence", "sequence_id");
    if (!Array.isArray(value.operations)) throw new PlanValidationError("operations must be an array");
    this.operations = value.operations.map(normalizeOperation);
    this.metadata = value.metadata && typeof value.metadata === "object" && !Array.isArray(value.metadata)
      ? cloneValue(value.metadata)
      : {};
  }

  toObject() {
    return {
      schema_version: this.schema_version,
      plan_id: this.plan_id,
      sequence_id: this.sequence_id,
      operations: cloneValue(this.operations),
      metadata: cloneValue(this.metadata)
    };
  }

  toJSON() {
    return this.toObject();
  }
}

function normalizeInventory(inventory) {
  if (inventory === undefined || inventory === null) return null;
  if (inventory instanceof Set) return new Set(Array.from(inventory, (item) => String(item)));
  if (Array.isArray(inventory)) {
    return new Set(inventory.map((item) => typeof item === "string" ? item : item && item.id).filter(Boolean).map(String));
  }
  if (typeof inventory === "object") return new Set(Object.keys(inventory).filter((key) => inventory[key]));
  throw new PlanValidationError("asset_inventory must be an array, Set, or object");
}

function normalizeLocks(lockedTracks) {
  if (!lockedTracks) return new Set();
  const values = lockedTracks instanceof Set ? Array.from(lockedTracks) : lockedTracks;
  if (!Array.isArray(values)) throw new PlanValidationError("locked_tracks must be an array or Set");
  return new Set(values.map((item) => {
    if (typeof item === "string") return item.toLowerCase();
    return trackKey(normalizeTrack(item, "locked_tracks[]"));
  }));
}

function intervalsOverlap(left, right) {
  return left.start < right.start + right.duration && right.start < left.start + left.duration;
}

function validateTimelinePlan(planInput, options = {}) {
  const plan = planInput instanceof TimelinePlan ? planInput : new TimelinePlan(planInput);
  const errors = [];
  const warnings = [];
  const supportedActions = options.supported_actions || options.supportedActions || SUPPORTED_ACTIONS;
  const supported = supportedActions instanceof Set ? supportedActions : new Set(supportedActions);
  const locks = normalizeLocks(options.locked_tracks || options.lockedTracks);
  const inventory = normalizeInventory(options.asset_inventory || options.assetInventory);
  const collisionPolicy = options.collision_policy || options.collisionPolicy || "reject";
  if (!COLLISION_POLICIES.has(collisionPolicy)) errors.push(`unsupported collision policy: ${collisionPolicy}`);

  const ids = new Set();
  for (const operation of plan.operations) {
    if (ids.has(operation.id)) errors.push(`duplicate operation id: ${operation.id}`);
    ids.add(operation.id);
    if (!supported.has(operation.action)) errors.push(`unsupported action: ${operation.action}`);
    if (locks.has(trackKey(operation.track))) errors.push(`locked track: ${trackKey(operation.track)}`);
    if (inventory && operation.asset && operation.asset.required && !inventory.has(operation.asset.id)) {
      errors.push(`missing asset: ${operation.asset.id}`);
    }
    if (operation.asset && operation.asset.kind && operation.action === "insert_audio" && operation.asset.kind !== "audio") {
      errors.push(`asset kind mismatch: ${operation.id}`);
    }
    if (operation.asset && operation.asset.kind && operation.action !== "insert_audio" && operation.asset.kind === "audio") {
      errors.push(`audio asset on video action: ${operation.id}`);
    }
  }

  for (let leftIndex = 0; leftIndex < plan.operations.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < plan.operations.length; rightIndex += 1) {
      const left = plan.operations[leftIndex];
      const right = plan.operations[rightIndex];
      if (trackKey(left.track) !== trackKey(right.track)) continue;
      if (!intervalsOverlap(left, right)) continue;
      if (left.metadata.allow_overlap === true || right.metadata.allow_overlap === true) continue;
      const message = `collision: ${left.id} overlaps ${right.id}`;
      if (collisionPolicy === "reject") errors.push(message);
      if (collisionPolicy === "warn") warnings.push(message);
    }
  }

  if (errors.length) throw new PlanValidationError("timeline plan validation failed", errors);
  return { plan, warnings };
}

function diffValues(before, after, path, result) {
  if (canonicalStringify(before) === canonicalStringify(after)) return;
  if (!before || !after || typeof before !== "object" || typeof after !== "object" || Array.isArray(before) || Array.isArray(after)) {
    result.push(path);
    return;
  }
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  for (const key of Array.from(keys).sort()) diffValues(before[key], after[key], `${path}.${key}`, result);
}

function diffPlans(beforeInput, afterInput) {
  const before = beforeInput instanceof TimelinePlan ? beforeInput : new TimelinePlan(beforeInput);
  const after = afterInput instanceof TimelinePlan ? afterInput : new TimelinePlan(afterInput);
  const beforeMap = new Map(before.operations.map((operation) => [operation.id, operation]));
  const afterMap = new Map(after.operations.map((operation) => [operation.id, operation]));
  const added = [];
  const removed = [];
  const modified = [];
  const planChangedPaths = [];
  diffValues(
    {
      schema_version: before.schema_version,
      plan_id: before.plan_id,
      sequence_id: before.sequence_id,
      metadata: before.metadata
    },
    {
      schema_version: after.schema_version,
      plan_id: after.plan_id,
      sequence_id: after.sequence_id,
      metadata: after.metadata
    },
    "plan",
    planChangedPaths
  );
  for (const id of Array.from(new Set([...beforeMap.keys(), ...afterMap.keys()])).sort()) {
    if (!beforeMap.has(id)) added.push(id);
    else if (!afterMap.has(id)) removed.push(id);
    else if (canonicalStringify(beforeMap.get(id)) !== canonicalStringify(afterMap.get(id))) {
      const changedPaths = [];
      diffValues(beforeMap.get(id), afterMap.get(id), `operations.${id}`, changedPaths);
      modified.push({ id, changed_paths: changedPaths });
    }
  }
  return {
    schema_version: 1,
    plan_id_before: before.plan_id,
    plan_id_after: after.plan_id,
    status: added.length || removed.length || modified.length || planChangedPaths.length ? "changed" : "no_change",
    added,
    removed,
    modified,
    changed_paths: planChangedPaths
  };
}

module.exports = {
  COLLISION_POLICIES,
  PlanValidationError,
  SUPPORTED_ACTIONS,
  TimelinePlan,
  canonicalStringify,
  diffPlans,
  stableFingerprint,
  validateTimelinePlan
};

