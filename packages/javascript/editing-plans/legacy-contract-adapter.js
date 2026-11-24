"use strict";

const { PlanValidationError, TimelinePlan } = require("./lib/timeline-plan-ir");

const ACTION_MAP = Object.freeze({
  insert_media: "insert_media",
  insert_audio: "insert_audio",
  insert_mogrt: "insert_mogrt",
  caption: "add_caption"
});

class ContractAdapterError extends Error {
  constructor(message, code = "LEGACY_PLAN_ADAPTER_ERROR") {
    super(message);
    this.name = "ContractAdapterError";
    this.code = code;
  }
}

function requireIdentifier(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new ContractAdapterError(`${field} must be a non-empty string`, "INVALID_ADAPTER_INPUT");
  }
  return value.normalize("NFC").trim();
}

function normalizeFrameRate(frameRate) {
  if (!frameRate || !Number.isSafeInteger(frameRate.numerator) || frameRate.numerator <= 0
      || !Number.isSafeInteger(frameRate.denominator) || frameRate.denominator <= 0) {
    throw new ContractAdapterError("frameRate must contain positive integer numerator and denominator", "INVALID_FRAME_RATE");
  }
  return { numerator: frameRate.numerator, denominator: frameRate.denominator };
}

function secondsToFrames(seconds, frameRate, field) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
    throw new ContractAdapterError(`${field} must be a finite non-negative number`, "INVALID_PLAN_TIME");
  }
  const exactFrames = seconds * frameRate.numerator / frameRate.denominator;
  const roundedFrames = Math.round(exactFrames);
  if (!Number.isSafeInteger(roundedFrames) || Math.abs(exactFrames - roundedFrames) > 1e-7) {
    throw new ContractAdapterError(`${field}=${seconds} seconds is not aligned to the requested frame rate`, "NON_FRAME_ALIGNED_TIME");
  }
  return roundedFrames;
}

function toContractEditPlan(planInput, options = {}) {
  let plan;
  try {
    plan = planInput instanceof TimelinePlan ? planInput : new TimelinePlan(planInput);
  } catch (error) {
    if (error instanceof PlanValidationError) {
      throw new ContractAdapterError(error.message, "INVALID_LEGACY_PLAN");
    }
    throw error;
  }

  const projectId = requireIdentifier(options.projectId, "projectId");
  const sourceFingerprint = requireIdentifier(options.sourceFingerprint, "sourceFingerprint");
  const frameRate = normalizeFrameRate(options.frameRate);
  const timelineId = requireIdentifier(options.timelineId || plan.sequence_id, "timelineId");
  const collisionPolicy = options.collisionPolicy || "block";
  if (!["block", "skip", "overlay"].includes(collisionPolicy)) {
    throw new ContractAdapterError(`unsupported collisionPolicy: ${collisionPolicy}`, "INVALID_COLLISION_POLICY");
  }

  const operations = plan.operations.map((operation) => {
    const action = ACTION_MAP[operation.action];
    if (!action) {
      throw new ContractAdapterError(`operation ${operation.id} uses unsupported legacy action: ${operation.action}`, "UNSUPPORTED_LEGACY_ACTION");
    }
    const track = {
      track_id: `${operation.track.type}-${operation.track.index}`,
      kind: operation.track.type,
      index: operation.track.index
    };
    const metadata = { ...operation.metadata };
    if (operation.source_cue) {
      metadata.source_cue_frames = {
        ...(operation.source_cue.in === undefined ? {} : { in_frame: secondsToFrames(operation.source_cue.in, frameRate, `${operation.id}.source_cue.in`) }),
        ...(operation.source_cue.out === undefined ? {} : { out_frame: secondsToFrames(operation.source_cue.out, frameRate, `${operation.id}.source_cue.out`) })
      };
    }
    return {
      operation_id: operation.id,
      action,
      ...(operation.asset ? { asset_id: operation.asset.id } : {}),
      track,
      start_frame: secondsToFrames(operation.start, frameRate, `${operation.id}.start`),
      duration_frames: secondsToFrames(operation.duration, frameRate, `${operation.id}.duration`),
      collision_policy: collisionPolicy,
      metadata
    };
  });

  return {
    schema_version: 1,
    plan_id: plan.plan_id,
    project_id: projectId,
    timeline_id: timelineId,
    source_fingerprint: sourceFingerprint,
    operations,
    approval_required: true,
    source_mutation: "forbid",
    status: "planned"
  };
}

module.exports = { ContractAdapterError, secondsToFrames, toContractEditPlan };
