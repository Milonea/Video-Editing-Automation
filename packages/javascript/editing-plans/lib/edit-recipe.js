"use strict";

const {
  PlanValidationError,
  SUPPORTED_ACTIONS,
  TimelinePlan,
  validateTimelinePlan
} = require("./timeline-plan-ir");
const { SafeEditingPrimitive } = require("./safe-editing-primitive");

const STEP_ACTIONS = new Map([
  ["intro", "insert_media"],
  ["image", "insert_media"],
  ["information_template", "insert_mogrt"],
  ["sfx", "insert_audio"],
  ["caption", "caption"],
  ["outro", "insert_media"]
]);
const MISSING_ASSET_POLICIES = new Set(["fail", "partial", "skip"]);
const UNSUPPORTED_HOST_POLICIES = new Set(["blocked", "partial"]);

class RecipeValidationError extends Error {
  constructor(message, errors = []) {
    super(message);
    this.name = "RecipeValidationError";
    this.errors = errors;
  }
}

function requireString(value, field) {
  if (typeof value !== "string" || !value.trim()) throw new RecipeValidationError(`${field} must be a non-empty string`);
  return value.normalize("NFC").trim();
}

function requireNumber(value, field, positive = false) {
  if (typeof value !== "number" || !Number.isFinite(value) || (positive ? value <= 0 : value < 0)) {
    throw new RecipeValidationError(`${field} must be a finite ${positive ? "positive" : "non-negative"} number`);
  }
  return value;
}

function cloneValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalizePolicies(value = {}) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new RecipeValidationError("policies must be an object");
  }
  const policies = {
    clone_sequence: value.clone_sequence !== false,
    dry_run: value.dry_run === true,
    preview: value.preview !== false,
    approval_required: value.approval_required !== false,
    partial_success: value.partial_success !== false,
    missing_asset: value.missing_asset || "fail",
    unsupported_host: value.unsupported_host || "blocked",
    collision: value.collision || "reject"
  };
  if (!policies.clone_sequence) throw new RecipeValidationError("clone_sequence cannot be disabled for a safe recipe");
  if (!policies.preview) throw new RecipeValidationError("preview cannot be disabled for a safe recipe");
  if (!policies.approval_required) throw new RecipeValidationError("approval_required cannot be disabled for a safe recipe");
  if (!MISSING_ASSET_POLICIES.has(policies.missing_asset)) throw new RecipeValidationError(`unsupported missing_asset policy: ${policies.missing_asset}`);
  if (!UNSUPPORTED_HOST_POLICIES.has(policies.unsupported_host)) throw new RecipeValidationError(`unsupported unsupported_host policy: ${policies.unsupported_host}`);
  return policies;
}

function normalizeRecipe(recipe) {
  if (!recipe || typeof recipe !== "object" || Array.isArray(recipe)) throw new RecipeValidationError("recipe must be an object");
  const id = requireString(recipe.id, "recipe.id");
  const version = requireString(String(recipe.version || ""), "recipe.version");
  if (!recipe.inputs || typeof recipe.inputs !== "object" || Array.isArray(recipe.inputs)) {
    throw new RecipeValidationError("recipe.inputs must be an object");
  }
  const sequenceId = requireString(recipe.inputs.sequence_id || recipe.inputs.sequenceId || "", "recipe.inputs.sequence_id");
  const assets = recipe.inputs.assets || {};
  if (!assets || typeof assets !== "object" || Array.isArray(assets)) throw new RecipeValidationError("recipe.inputs.assets must be an object");
  if (!Array.isArray(recipe.steps) || !recipe.steps.length) throw new RecipeValidationError("recipe.steps must be a non-empty array");
  const policies = normalizePolicies(recipe.policies);
  const seen = new Set();
  const steps = recipe.steps.map((step, index) => {
    if (!step || typeof step !== "object" || Array.isArray(step)) throw new RecipeValidationError(`steps[${index}] must be an object`);
    const stepId = requireString(step.id || `step-${index + 1}`, `steps[${index}].id`);
    if (seen.has(stepId)) throw new RecipeValidationError(`duplicate step id: ${stepId}`);
    seen.add(stepId);
    const type = requireString(step.type, `steps[${index}].type`).toLowerCase();
    if (!STEP_ACTIONS.has(type)) throw new RecipeValidationError(`unsupported recipe step type: ${type}`);
    const order = step.order === undefined ? index : step.order;
    if (!Number.isInteger(order) || order < 0) throw new RecipeValidationError(`steps[${index}].order must be a non-negative integer`);
    const track = step.track;
    if (!track || typeof track !== "object" || !Number.isInteger(track.index) || track.index < 0) {
      throw new RecipeValidationError(`steps[${index}].track.index must be a non-negative integer`);
    }
    const trackType = String(track.type || track.kind || "").toLowerCase();
    if (!["video", "audio"].includes(trackType)) throw new RecipeValidationError(`steps[${index}].track.type must be video or audio`);
    const assetRef = step.asset === undefined || step.asset === null ? null : step.asset;
    return {
      id: stepId,
      type,
      action: STEP_ACTIONS.get(type),
      order,
      track: { type: trackType, index: track.index },
      start: requireNumber(step.start, `steps[${index}].start`),
      duration: requireNumber(step.duration, `steps[${index}].duration`, true),
      asset: assetRef,
      source_cue: step.source_cue === undefined ? null : cloneValue(step.source_cue),
      required_host_capability: step.required_host_capability || step.requiredHostCapability || null,
      provenance: step.provenance ? cloneValue(step.provenance) : null,
      metadata: step.metadata && typeof step.metadata === "object" && !Array.isArray(step.metadata) ? cloneValue(step.metadata) : {}
    };
  }).sort((left, right) => left.order - right.order || left.id.localeCompare(right.id));
  for (let index = 1; index < steps.length; index += 1) {
    if (steps[index - 1].order === steps[index].order) throw new RecipeValidationError("step order values must be unique");
  }
  return {
    schema_version: 1,
    id,
    version,
    inputs: { ...cloneValue(recipe.inputs), sequence_id: sequenceId, assets: cloneValue(assets) },
    steps,
    policies,
    provenance: recipe.provenance ? cloneValue(recipe.provenance) : { source_id: `recipe:${id}` }
  };
}

function inventorySet(inventory) {
  if (inventory === undefined || inventory === null) return null;
  if (inventory instanceof Set) return new Set(Array.from(inventory, String));
  if (Array.isArray(inventory)) return new Set(inventory.map((item) => typeof item === "string" ? item : item && item.id).filter(Boolean).map(String));
  if (typeof inventory === "object") return new Set(Object.keys(inventory).filter((key) => inventory[key]).map(String));
  throw new RecipeValidationError("asset_inventory must be an array, Set, or object");
}

function hostSet(capabilities) {
  if (capabilities === undefined || capabilities === null) return new Set();
  if (!Array.isArray(capabilities) && !(capabilities instanceof Set)) throw new RecipeValidationError("host_capabilities must be an array or Set");
  return new Set(Array.from(capabilities, (item) => String(item)));
}

function resolveAsset(step, assets) {
  if (step.asset === null) return null;
  if (typeof step.asset === "string") {
    const resolved = assets[step.asset];
    if (resolved === undefined) return { id: step.asset, missing_reference: true };
    if (typeof resolved === "string") return { id: resolved, required: true };
    if (resolved && typeof resolved === "object" && !Array.isArray(resolved)) return { ...cloneValue(resolved), id: resolved.id || step.asset, required: resolved.required !== false };
    return { id: step.asset, missing_reference: true };
  }
  if (!step.asset || typeof step.asset !== "object" || Array.isArray(step.asset)) return { id: null, missing_reference: true };
  return { ...cloneValue(step.asset), id: step.asset.id || step.asset.asset_id, required: step.asset.required !== false };
}

function compileRecipe(recipeInput, {
  assetInventory = null,
  hostCapabilities = [],
  lockedTracks = [],
  supportedActions = SUPPORTED_ACTIONS
} = {}) {
  const recipe = normalizeRecipe(recipeInput);
  const inventory = inventorySet(assetInventory);
  const capabilities = hostSet(hostCapabilities);
  const missingAssets = [];
  const unsupportedSteps = [];
  const skippedSteps = [];
  const operations = [];
  const assetKind = { insert_audio: "audio", insert_media: "media", insert_mogrt: "mogrt" };

  for (const step of recipe.steps) {
    const resolvedAsset = resolveAsset(step, recipe.inputs.assets);
    const needsAsset = ["insert_media", "insert_mogrt", "insert_audio"].includes(step.action);
    const missing = needsAsset && (!resolvedAsset || !resolvedAsset.id || resolvedAsset.missing_reference || (inventory && !inventory.has(String(resolvedAsset.id))));
    if (missing) {
      const id = resolvedAsset && resolvedAsset.id ? String(resolvedAsset.id) : "<missing-reference>";
      missingAssets.push({ step_id: step.id, asset_id: id });
      if (recipe.policies.missing_asset === "fail") {
        throw new RecipeValidationError("recipe has missing assets", missingAssets.map((item) => `missing asset ${item.step_id}:${item.asset_id}`));
      }
      skippedSteps.push({ step_id: step.id, reason: `missing_asset:${id}` });
      continue;
    }
    const capability = step.required_host_capability;
    if (capability && !capabilities.has(String(capability))) {
      unsupportedSteps.push({ step_id: step.id, capability: String(capability) });
      if (recipe.policies.unsupported_host === "blocked") continue;
      skippedSteps.push({ step_id: step.id, reason: `unsupported_host:${capability}` });
      continue;
    }
    const operation = {
      id: step.id,
      action: step.action,
      track: step.track,
      start: step.start,
      duration: step.duration,
      asset: needsAsset ? {
        id: String(resolvedAsset.id),
        kind: resolvedAsset.kind || assetKind[step.action],
        required: resolvedAsset.required !== false
      } : null,
      source_cue: step.source_cue,
      provenance: step.provenance || recipe.provenance,
      metadata: { ...step.metadata, recipe_step_type: step.type, order: step.order }
    };
    operations.push(operation);
  }

  let plan;
  try {
    plan = new TimelinePlan({
      schema_version: 1,
      plan_id: `${recipe.id}@${recipe.version}`,
      sequence_id: recipe.inputs.sequence_id,
      operations,
      metadata: {
        recipe_id: recipe.id,
        recipe_version: recipe.version,
        missing_asset_policy: recipe.policies.missing_asset,
        unsupported_host_policy: recipe.policies.unsupported_host
      }
    });
    const planValidation = validateTimelinePlan(plan, {
      assetInventory: inventory,
      lockedTracks,
      collisionPolicy: recipe.policies.collision,
      supportedActions
    });
    plan = planValidation.plan;
  } catch (error) {
    const errors = error instanceof PlanValidationError ? error.errors : [error.message || String(error)];
    throw new RecipeValidationError("compiled recipe plan is invalid", errors);
  }

  let status = "ready";
  if (unsupportedSteps.length && recipe.policies.unsupported_host === "blocked") status = "unsupported";
  else if (missingAssets.length || unsupportedSteps.length) status = "partial";
  return {
    schema_version: 1,
    status,
    recipe,
    plan,
    missing_assets: missingAssets,
    unsupported_steps: unsupportedSteps,
    skipped_steps: skippedSteps,
    warnings: []
  };
}

function executeRecipe(recipeInput, {
  source,
  adapter,
  assetInventory = null,
  hostCapabilities = [],
  lockedTracks = [],
  supportedActions = SUPPORTED_ACTIONS,
  dryRun = undefined,
  approval = false
} = {}) {
  let compiled;
  try {
    compiled = compileRecipe(recipeInput, { assetInventory, hostCapabilities, lockedTracks, supportedActions });
  } catch (error) {
    return {
      schema_version: 1,
      status: "preflight_failed",
      stage: "recipe_preflight",
      errors: [{ code: "recipe_validation", message: error.message || String(error), details: error.errors || [] }],
      external_writes: 0,
      source_mutations: 0
    };
  }
  if (compiled.status === "unsupported") {
    return {
      schema_version: 1,
      status: "unsupported",
      stage: "recipe_preflight",
      recipe_id: compiled.recipe.id,
      recipe_version: compiled.recipe.version,
      unsupported_steps: compiled.unsupported_steps,
      skipped_steps: compiled.skipped_steps,
      plan: compiled.plan.toObject(),
      external_writes: 0,
      source_mutations: 0
    };
  }
  const effectiveDryRun = dryRun === undefined ? compiled.recipe.policies.dry_run : dryRun;
  const primitive = new SafeEditingPrimitive(adapter);
  const execution = primitive.execute({
    source,
    plan: compiled.plan,
    dryRun: effectiveDryRun,
    approval,
    assetInventory,
    lockedTracks,
    collisionPolicy: compiled.recipe.policies.collision,
    supportedActions,
    cloneSequence: compiled.recipe.policies.clone_sequence
  });
  const wasPartial = compiled.status === "partial";
  const result = {
    ...execution,
    recipe_id: compiled.recipe.id,
    recipe_version: compiled.recipe.version,
    recipe_status: compiled.status,
    missing_assets: compiled.missing_assets,
    unsupported_steps: compiled.unsupported_steps,
    skipped_steps: compiled.skipped_steps
  };
  if (wasPartial && ["completed", "awaiting_approval", "dry_run"].includes(execution.status)) {
    result.underlying_status = execution.status;
    result.status = "partial_success";
  }
  return result;
}

module.exports = {
  MISSING_ASSET_POLICIES,
  STEP_ACTIONS,
  RecipeValidationError,
  compileRecipe,
  executeRecipe,
  normalizeRecipe
};

