"use strict";

const { sanitizeErrorMessage } = require("./error-sanitizer");

/**
 * Injectable boundary for the UXP panel's path -> preflight -> Premiere flow.
 * The production adapters can call UXP/Premiere, while Node tests use plain
 * objects. No adapter in this module is allowed to mutate the source before
 * preflight succeeds.
 */

const STAGES = ["external_root", "asset_resolution", "cache", "preflight", "approval", "insert", "audio", "complete"];

function clone(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function stageResult(status, stage, extra = {}) {
  return {
    schema_version: 1,
    status,
    stage,
    stages: [],
    source_mutations: 0,
    external_writes: 0,
    rollback: { status: "not_needed", residual_mutation: "none" },
    residual_mutation: "none",
    ...clone(extra)
  };
}

function addStage(result, name, ok, code, message, details = {}) {
  result.stages.push({ name, ok, code, message, ...clone(details) });
  return result;
}

function errorMessage(error) {
  return sanitizeErrorMessage(error);
}

function operationFailure(result) {
  const operation = result && result.operation;
  if (!operation || operation.status === "success") return null;
  const stages = Array.isArray(operation.stages) ? operation.stages : [];
  for (let index = stages.length - 1; index >= 0; index -= 1) {
    const stage = stages[index];
    if (stage && stage.ok === false) {
      return Object.assign(new Error(stage.message || stage.code || "video operation failed"), {
        code: stage.code || "video_operation_failed",
        rollback: clone(operation.rollback),
        residual_mutation: operation.rollback && operation.rollback.residual_mutation
          ? operation.rollback.residual_mutation
          : "unknown"
      });
    }
  }
  return Object.assign(new Error("video operation did not finish successfully"), {
    rollback: clone(operation.rollback),
    residual_mutation: operation.rollback && operation.rollback.residual_mutation
      ? operation.rollback.residual_mutation
      : "unknown"
  });
}

function isPreflightCheck(check) {
  if (!check || typeof check !== "object" || Array.isArray(check)) return false;
  if (typeof check.name !== "string" || !check.name.trim() || typeof check.ok !== "boolean") return false;
  if (check.code !== undefined && typeof check.code !== "string") return false;
  if (check.message !== undefined && typeof check.message !== "string") return false;
  return true;
}

function isPreflightResponse(preflight) {
  if (!preflight || typeof preflight !== "object" || Array.isArray(preflight)) return false;
  if (typeof preflight.ok !== "boolean" || !Array.isArray(preflight.checks) || preflight.checks.length === 0) return false;
  if (!preflight.checks.every(isPreflightCheck)) return false;
  return preflight.ok === preflight.checks.every((check) => check.ok === true);
}

function preflightIsSafe(preflight) {
  return isPreflightResponse(preflight) && preflight.ok === true;
}

async function runInsertionFlow({
  paths,
  premiere,
  feature,
  assetPath,
  assetKind = "mogrt",
  durationSeconds,
  videoTrackIndex,
  audio = null,
  dryRun = false,
  approval = false,
  preflightConfig = {}
} = {}) {
  const result = stageResult("failed", "external_root", {
    feature: feature || null,
    asset_kind: assetKind,
    dry_run: dryRun,
    cache: null
  });
  if (!paths || typeof paths !== "object" || !premiere || typeof premiere !== "object") {
    return addStage(result, "external_root", false, "invalid_adapters", "paths and premiere adapters are required");
  }

  let root;
  try {
    if (typeof paths.getExternalRoot !== "function") throw new Error("paths.getExternalRoot is required");
    root = await paths.getExternalRoot();
  } catch (error) {
    result.stage = "external_root";
    return addStage(result, "external_root", false, error.code || "external_root_error", errorMessage(error));
  }
  if (!root) {
    result.stage = "external_root";
    return addStage(result, "external_root", false, "external_root_not_selected", "an external root must be selected before insertion");
  }
  addStage(result, "external_root", true, "EXTERNAL_ROOT_READY", "external root selected");

  let resolvedAsset;
  try {
    if (typeof assetPath !== "string" || !assetPath.trim()) throw new Error("assetPath is required");
    const resolver = assetKind === "external" ? paths.resolveExternalAssetPath : paths.resolvePluginAssetPath;
    if (typeof resolver !== "function") throw new Error(`${assetKind === "external" ? "paths.resolveExternalAssetPath" : "paths.resolvePluginAssetPath"} is required`);
    resolvedAsset = await resolver(assetPath);
    if (!resolvedAsset) throw new Error(`asset was not found: ${assetPath}`);
  } catch (error) {
    result.stage = "asset_resolution";
    return addStage(result, "asset_resolution", false, error.code || "asset_resolution_error", errorMessage(error), { config_path: assetPath || null });
  }
  addStage(result, "asset_resolution", true, "ASSET_READY", "asset resolved", { config_path: assetPath });

  if (typeof premiere.getCacheDiagnostics === "function") {
    result.cache = clone(await premiere.getCacheDiagnostics());
    addStage(result, "cache", true, "CACHE_INSPECTED", "project cache diagnostics captured", { diagnostics: result.cache });
  } else {
    addStage(result, "cache", true, "CACHE_NOT_EXPOSED", "project cache adapter is not exposed");
  }

  let preflight;
  try {
    if (typeof premiere.preflight !== "function") throw new Error("premiere.preflight is required");
    preflight = await premiere.preflight({
      feature,
      videoTrackIndex,
      assetKind,
      audio: audio ? { trackIndex: audio.trackIndex, startOffsetFrames: audio.startOffsetFrames || 0 } : null,
      ...clone(preflightConfig)
    }, durationSeconds, audio && audio.durationSeconds ? audio.durationSeconds : 1);
  } catch (error) {
    result.stage = "preflight";
    return addStage(result, "preflight", false, error.code || "preflight_error", errorMessage(error));
  }
  if (!preflightIsSafe(preflight)) {
    result.stage = "preflight";
    return addStage(result, "preflight", false, "PREFLIGHT_BLOCKED", "preflight blocked the operation", { checks: clone(preflight && Array.isArray(preflight.checks) ? preflight.checks : []) });
  }
  addStage(result, "preflight", true, "PREFLIGHT_OK", "preflight passed", { checks: clone(preflight.checks || []) });
  if (dryRun) {
    result.status = "dry_run";
    result.stage = "complete";
    addStage(result, "complete", true, "DRY_RUN", "no Premiere mutation was requested");
    return result;
  }
  if (!approval) {
    result.status = "awaiting_approval";
    result.stage = "approval";
    addStage(result, "approval", true, "APPROVAL_REQUIRED", "explicit user approval is required before Premiere mutation");
    return result;
  }

  try {
    const methodName = assetKind === "media" ? "insertMedia" : "insertMogrt";
    const method = premiere[methodName];
    if (typeof method !== "function") throw new Error(`premiere.${methodName} is required`);
    result.video = await method.call(premiere, resolvedAsset, videoTrackIndex, durationSeconds, `${feature || "asset"} video insertion`);
    const videoFailure = operationFailure(result.video);
    if (videoFailure) throw videoFailure;
    addStage(result, "insert", true, "VIDEO_INSERTED", "video/MOGRT insertion completed");
  } catch (error) {
    result.stage = "insert";
    const rollback = clone(error.rollback || {
      status: "unavailable",
      residual_mutation: error.residual_mutation || "unknown"
    });
    result.rollback = rollback;
    result.residual_mutation = error.residual_mutation || rollback.residual_mutation || "unknown";
    return addStage(result, "insert", false, error.code || "video_insert_error", errorMessage(error), {
      rollback,
      residual_mutation: result.residual_mutation
    });
  }

  if (audio) {
    let audioPath;
    try {
      if (typeof paths.resolveExternalAssetPath !== "function") throw new Error("paths.resolveExternalAssetPath is required");
      audioPath = await paths.resolveExternalAssetPath(audio.path);
      if (!audioPath) throw new Error(`audio asset was not found: ${audio.path}`);
    } catch (error) {
      result.status = "partial";
      result.audio = { ok: false, warning: errorMessage(error) };
      addStage(result, "audio", false, "AUDIO_MISSING", errorMessage(error), { required: audio.required === true });
      result.stage = "complete";
      addStage(result, "complete", true, "PARTIAL_SUCCESS", "video succeeded; audio was skipped");
      return result;
    }
    try {
      if (typeof premiere.insertAudio !== "function") throw new Error("premiere.insertAudio is required");
      const warning = await premiere.insertAudio(audioPath, audio.trackIndex, result.video && result.video.playerPosition, `${feature || "asset"} audio insertion`, audio.startOffsetFrames || 0);
      if (warning) throw new Error(String(warning));
      result.audio = { ok: true };
      addStage(result, "audio", true, "AUDIO_INSERTED", "audio insertion completed");
    } catch (error) {
      result.status = "partial";
      result.audio = { ok: false, warning: errorMessage(error) };
      addStage(result, "audio", false, "AUDIO_FAILED", errorMessage(error), { required: audio.required === true });
      result.stage = "complete";
      addStage(result, "complete", true, "PARTIAL_SUCCESS", "video succeeded; audio failed");
      return result;
    }
  }

  result.status = "success";
  result.stage = "complete";
  addStage(result, "complete", true, "SUCCESS", "insertion completed");
  return result;
}

module.exports = { STAGES, addStage, isPreflightCheck, isPreflightResponse, preflightIsSafe, runInsertionFlow, stageResult };

