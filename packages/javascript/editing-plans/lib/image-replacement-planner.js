"use strict";

const { TimelinePlan, validateTimelinePlan } = require("./timeline-plan-ir");
const {
  PlannerValidationError,
  asError,
  collectExistingItems,
  findCollisions,
  inventoryIds,
  normalizeLocks,
  normalizeProvenance,
  normalizeSource,
  normalizeTrack,
  plannerResult,
  requireNumber,
  requireObject,
  requireString,
  sourceFingerprint,
  trackKey
} = require("./editing-planner-utils");
const { SafeEditingPrimitive } = require("./safe-editing-primitive");

const IMAGE_FORMATS = new Set(["png", "jpg", "jpeg", "webp", "tif", "tiff"]);

function normalizedFormat(target) {
  const format = String(target.format || String(target.path || "").split(".").pop() || "").toLowerCase();
  if (!IMAGE_FORMATS.has(format)) throw new PlannerValidationError(`unsupported image format: ${format || "<missing>"}`, "unsupported_image_format");
  return format;
}

function validateTemplateContract(template, mode) {
  if (template === undefined || template === null) return null;
  requireObject(template, "template");
  const id = requireString(template.id, "template.id");
  const contract = {
    id,
    kind: String(template.kind || "mogrt").toLowerCase(),
    media_slot_id: template.media_slot_id === undefined ? null : requireString(template.media_slot_id, "template.media_slot_id"),
    accepted_formats: Array.isArray(template.accepted_formats) ? template.accepted_formats.map((value) => String(value).toLowerCase()) : [],
    alpha: template.alpha === undefined ? "unknown" : String(template.alpha),
    crop: template.crop === undefined ? "unknown" : String(template.crop),
    placeholder: template.placeholder === undefined ? "unknown" : String(template.placeholder),
    media_slot_assignment_supported: template.media_slot_assignment_supported === true
  };
  if (contract.kind !== "mogrt") throw new PlannerValidationError("template.kind must be mogrt", "invalid_template");
  if (mode === "mogrt_media_slot") {
    if (!contract.media_slot_id) throw new PlannerValidationError("template.media_slot_id is required for media-slot mode", "missing_media_slot");
    if (!contract.media_slot_assignment_supported) {
      throw new PlannerValidationError("UXP media slot assignment is not verified", "media_slot_assignment_unverified");
    }
  }
  return contract;
}

function planImageReplacement({
  source,
  target,
  mode = "isolated_insert",
  template,
  assetInventory,
  lockedTracks = [],
  existingItems = [],
  targetTrack = { type: "video", index: 1 },
  plannerId = "image-replacement",
  provenance
} = {}) {
  try {
    const normalizedSource = normalizeSource(source);
    requireObject(target, "target");
    if (!["isolated_insert", "mogrt_media_slot"].includes(mode)) throw new PlannerValidationError(`unsupported image replacement mode: ${mode}`, "unsupported_mode");
    const contract = validateTemplateContract(template, mode);
    const assetId = requireString(target.asset_id || target.project_item_id || "", "target.asset_id");
    const format = normalizedFormat(target);
    const track = normalizeTrack(target.track || targetTrack, "target.track", { type: "video", index: 1 });
    if (track.type !== "video") throw new PlannerValidationError("image replacement target must use a video track", "invalid_target_track");
    const locks = normalizeLocks(lockedTracks);
    if (locks.has(trackKey(track))) throw new PlannerValidationError(`locked target track: ${trackKey(track)}`, "locked_track");
    const start = requireNumber(target.start, "target.start");
    const duration = requireNumber(target.duration, "target.duration", { positive: true });
    const width = target.width === undefined ? null : requireNumber(target.width, "target.width", { positive: true, integer: true });
    const height = target.height === undefined ? null : requireNumber(target.height, "target.height", { positive: true, integer: true });
    const inventory = inventoryIds(assetInventory);
    if (inventory && !inventory.has(assetId)) throw new PlannerValidationError(`missing image asset: ${assetId}`, "missing_image_asset");
    if (contract && contract.accepted_formats.length && !contract.accepted_formats.includes(format)) {
      throw new PlannerValidationError(`template does not accept ${format}`, "template_format_mismatch");
    }
    const sourceProvenance = provenance ? normalizeProvenance(provenance, "provenance") : { source_id: `image-planner:${normalizedSource.sequence_id}` };
    const operation = {
      id: `image-replacement:${assetId}:${start}`,
      action: "insert_media",
      track,
      start,
      duration,
      asset: { id: assetId, kind: "media", required: true },
      source_cue: null,
      provenance: sourceProvenance,
      metadata: {
        replacement_mode: mode,
        isolated_insert: mode === "isolated_insert",
        media_slot_id: contract ? contract.media_slot_id : null,
        media_slot_assignment_supported: contract ? contract.media_slot_assignment_supported : false,
        image_format: format,
        alpha: target.alpha === undefined ? "unknown" : String(target.alpha),
        crop: target.crop === undefined ? "unknown" : String(target.crop),
        placeholder: target.placeholder === undefined ? "unknown" : String(target.placeholder),
        width,
        height,
        global_media_relink: false,
        forbidden_api: "changeMediaFilePath"
      }
    };
    const collisions = findCollisions([operation], collectExistingItems(source, existingItems));
    if (collisions.length) throw new PlannerValidationError("image replacement collides with an existing timeline item", "timeline_collision", collisions.map((item) => JSON.stringify(item)));
    const plan = new TimelinePlan({
      schema_version: 1,
      plan_id: `${plannerId}@1`,
      sequence_id: normalizedSource.sequence_id,
      operations: [operation],
      metadata: {
        planner: "image-replacement",
        planner_version: 1,
        source_guid: normalizedSource.guid,
        source_fingerprint: sourceFingerprint(source),
        replacement_mode: mode,
        global_media_relink: false,
        clone_only: true,
        approval_required: true,
        host_validation_status: "not_run"
      }
    });
    validateTimelinePlan(plan, { assetInventory, lockedTracks, collisionPolicy: "reject" });
    return plannerResult({
      status: "dry_run",
      stage: "dry_run_plan",
      source,
      plan,
      extra: {
        replacement_mode: mode,
        target_asset_id: assetId,
        template_id: contract ? contract.id : null,
        global_media_relink: false,
        source_project_item_mutations: 0,
        clone_required: true,
        host_validation_status: "not_run"
      }
    });
  } catch (error) {
    const status = error && error.code === "media_slot_assignment_unverified" ? "unsupported" : "preflight_failed";
    return plannerResult({ status, stage: "preflight", source, errors: [asError(error)], extra: { global_media_relink: false, source_project_item_mutations: 0 } });
  }
}

function executeImageReplacement({
  source,
  adapter,
  expectedSourceFingerprint = null,
  dryRun = true,
  approval = false,
  ...options
} = {}) {
  const planned = planImageReplacement({ source, ...options });
  if (planned.status !== "dry_run") return planned;
  if (!adapter) return planned;
  if (expectedSourceFingerprint && expectedSourceFingerprint !== planned.source_fingerprint) {
    return plannerResult({ status: "fingerprint_changed", stage: "source_fingerprint", source, plan: planned.plan, errors: [{ code: "expected_fingerprint_mismatch", message: "source fingerprint differs before execution" }], extra: { clone_status: "not_created", global_media_relink: false } });
  }
  const primitive = new SafeEditingPrimitive(adapter);
  const execution = primitive.execute({
    source,
    plan: planned.plan,
    dryRun,
    approval,
    expectedSourceFingerprint,
    assetInventory: options.assetInventory,
    lockedTracks: options.lockedTracks,
    collisionPolicy: "reject"
  });
  return { ...execution, planner: "image-replacement", global_media_relink: false, source_project_item_mutations: 0 };
}

module.exports = {
  IMAGE_FORMATS,
  planImageReplacement,
  executeImageReplacement,
  validateTemplateContract
};

