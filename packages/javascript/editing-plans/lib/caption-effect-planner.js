"use strict";

const {
  TimelinePlan,
  validateTimelinePlan
} = require("./timeline-plan-ir");
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

function normalizeCue(cue, index, ticksPerSecond) {
  requireObject(cue, `cues[${index}]`);
  const cueId = requireString(cue.cue_id || cue.id || "", `cues[${index}].cue_id`);
  let start;
  let end;
  let startTicks = null;
  let endTicks = null;
  if (cue.start_ticks !== undefined || cue.end_ticks !== undefined) {
    startTicks = requireNumber(cue.start_ticks, `cues[${index}].start_ticks`, { integer: true });
    endTicks = requireNumber(cue.end_ticks, `cues[${index}].end_ticks`, { integer: true });
    const timebase = requireNumber(cue.ticks_per_second === undefined ? ticksPerSecond : cue.ticks_per_second, `cues[${index}].ticks_per_second`, { positive: true });
    if (endTicks <= startTicks) throw new PlannerValidationError(`cues[${index}] end_ticks must be greater than start_ticks`, "invalid_cue_time");
    start = startTicks / timebase;
    end = endTicks / timebase;
  } else {
    start = requireNumber(cue.start, `cues[${index}].start`);
    end = requireNumber(cue.end, `cues[${index}].end`);
    if (end <= start) throw new PlannerValidationError(`cues[${index}] end must be greater than start`, "invalid_cue_time");
  }
  return {
    cue_id: cueId,
    start,
    end,
    duration: end - start,
    start_ticks: startTicks,
    end_ticks: endTicks,
    text: cue.text === undefined ? null : String(cue.text),
    provenance: normalizeProvenance(cue.provenance, `cues[${index}].provenance`)
  };
}

function normalizeCues(cues, ticksPerSecond) {
  if (!Array.isArray(cues) || !cues.length) throw new PlannerValidationError("cues must be a non-empty array", "invalid_cues");
  const normalized = cues.map((cue, index) => normalizeCue(cue, index, ticksPerSecond));
  const ids = new Set();
  for (const cue of normalized) {
    if (ids.has(cue.cue_id)) throw new PlannerValidationError(`duplicate cue_id: ${cue.cue_id}`, "duplicate_cue_id");
    ids.add(cue.cue_id);
  }
  normalized.sort((left, right) => left.start - right.start || left.end - right.end || left.cue_id.localeCompare(right.cue_id));
  for (let index = 1; index < normalized.length; index += 1) {
    if (normalized[index - 1].end > normalized[index].start) {
      throw new PlannerValidationError(`overlapping cues: ${normalized[index - 1].cue_id} and ${normalized[index].cue_id}`, "overlapping_cues");
    }
  }
  return normalized;
}

function planCaptionEffects({
  source,
  cues,
  template,
  templateId = null,
  assetInventory,
  graphicsTrack = { type: "video", index: 1 },
  lockedTracks = [],
  existingItems = [],
  ticksPerSecond = null,
  plannerId = "caption-effect",
  provenance
} = {}) {
  try {
    const normalizedSource = normalizeSource(source);
    const track = normalizeTrack(graphicsTrack, "graphics_track", { type: "video", index: 1 });
    if (track.type !== "video") throw new PlannerValidationError("graphics_track must be a video track", "invalid_graphics_track");
    const locks = normalizeLocks(lockedTracks);
    if (locks.has(trackKey(track))) throw new PlannerValidationError(`locked graphics track: ${trackKey(track)}`, "locked_track");
    const normalizedTemplate = template || { id: templateId };
    requireObject(normalizedTemplate, "template");
    const resolvedTemplateId = requireString(normalizedTemplate.id || templateId || "", "template.id");
    const templateKind = String(normalizedTemplate.kind || "mogrt").toLowerCase();
    if (templateKind !== "mogrt") throw new PlannerValidationError("template.kind must be mogrt", "invalid_template");
    const inventory = inventoryIds(assetInventory);
    if (inventory && !inventory.has(resolvedTemplateId)) {
      throw new PlannerValidationError(`missing template asset: ${resolvedTemplateId}`, "missing_template");
    }
    if (normalizedTemplate.controls !== undefined && (!Array.isArray(normalizedTemplate.controls) || normalizedTemplate.controls.some((control) => typeof control !== "string" || !control.trim()))) {
      throw new PlannerValidationError("template.controls must be an array of names", "invalid_template_controls");
    }
    const normalizedCues = normalizeCues(cues, ticksPerSecond);
    const sourceProvenance = provenance ? normalizeProvenance(provenance, "provenance") : { source_id: `caption-planner:${normalizedSource.sequence_id}` };
    const operations = normalizedCues.map((cue) => ({
      id: `caption-effect:${cue.cue_id}`,
      action: "insert_mogrt",
      track,
      start: cue.start,
      duration: cue.duration,
      asset: { id: resolvedTemplateId, kind: "mogrt", required: true },
      source_cue: { in: cue.start, out: cue.end },
      provenance: cue.provenance || sourceProvenance,
      metadata: {
        cue_id: cue.cue_id,
        cue_start_ticks: cue.start_ticks,
        cue_end_ticks: cue.end_ticks,
        template_id: resolvedTemplateId,
        template_controls: normalizedTemplate.controls || [],
        caption_mutation: false,
        dedicated_graphics_track: trackKey(track),
        host_api_status: "public-api-contract-only"
      }
    }));
    const collisions = findCollisions(operations, collectExistingItems(source, existingItems));
    if (collisions.length) throw new PlannerValidationError("caption effect plan collides with existing timeline items", "timeline_collision", collisions.map((item) => JSON.stringify(item)));
    const plan = new TimelinePlan({
      schema_version: 1,
      plan_id: `${plannerId}@1`,
      sequence_id: normalizedSource.sequence_id,
      operations,
      metadata: {
        planner: "caption-effect",
        planner_version: 1,
        cue_ids: normalizedCues.map((cue) => cue.cue_id),
        template_id: resolvedTemplateId,
        source_guid: normalizedSource.guid,
        source_fingerprint: sourceFingerprint(source),
        caption_mutation: false,
        clone_only: true,
        approval_required: true
      }
    });
    validateTimelinePlan(plan, {
      assetInventory,
      lockedTracks,
      collisionPolicy: "reject"
    });
    return plannerResult({
      status: "dry_run",
      stage: "dry_run_plan",
      source,
      plan,
      extra: {
        deterministic_fingerprint: sourceFingerprint({ guid: normalizedSource.guid, sequence_id: normalizedSource.sequence_id, inventory: normalizedSource.inventory, cues: normalizedCues, template: normalizedTemplate, track }),
        cue_count: normalizedCues.length,
        template_id: resolvedTemplateId,
        clone_required: true,
        caption_mutations: 0,
        host_validation_status: "not_run"
      }
    });
  } catch (error) {
    return plannerResult({ status: "preflight_failed", stage: "preflight", source, errors: [asError(error)] });
  }
}

function executeCaptionEffects({
  source,
  adapter,
  expectedSourceFingerprint = null,
  dryRun = true,
  approval = false,
  ...options
} = {}) {
  const planned = planCaptionEffects({ source, ...options });
  if (planned.status !== "dry_run") return planned;
  if (!adapter) return planned;
  if (expectedSourceFingerprint && expectedSourceFingerprint !== planned.source_fingerprint) {
    return plannerResult({ status: "fingerprint_changed", stage: "source_fingerprint", source, plan: planned.plan, errors: [{ code: "expected_fingerprint_mismatch", message: "source fingerprint differs before execution" }], extra: { clone_status: "not_created", clone_required: true } });
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
  return { ...execution, planner: "caption-effect", template_id: planned.template_id, caption_mutations: 0 };
}

module.exports = {
  normalizeCue,
  normalizeCues,
  planCaptionEffects,
  executeCaptionEffects
};

