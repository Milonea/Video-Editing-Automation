"use strict";

const {
  PlanValidationError,
  SUPPORTED_ACTIONS,
  canonicalStringify,
  stableFingerprint,
  validateTimelinePlan
} = require("./timeline-plan-ir");

const PIPELINE = [
  "input",
  "preflight",
  "source_fingerprint",
  "dry_run_plan",
  "clone_sequence",
  "mutation_on_clone",
  "post_validation",
  "preview",
  "user_approval",
  "final_use"
];

class SafeEditingError extends Error {
  constructor(message, code = "safe_editing_error") {
    super(message);
    this.name = "SafeEditingError";
    this.code = code;
  }
}

function cloneValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function requireSequence(sequence, label = "source_sequence") {
  if (!sequence || typeof sequence !== "object" || Array.isArray(sequence)) {
    throw new SafeEditingError(`${label} must be an object`, "invalid_sequence");
  }
  if (typeof sequence.guid !== "string" || !sequence.guid.trim()) {
    throw new SafeEditingError(`${label}.guid is required`, "invalid_sequence_identity");
  }
  if (!Array.isArray(sequence.inventory)) {
    throw new SafeEditingError(`${label}.inventory must be an array`, "invalid_sequence_inventory");
  }
  return sequence;
}

function normalizeInventory(sequence) {
  requireSequence(sequence);
  return sequence.inventory.map((item, index) => {
    if (typeof item === "string") return { id: item };
    if (!item || typeof item !== "object" || Array.isArray(item) || typeof item.id !== "string" || !item.id.trim()) {
      throw new SafeEditingError(`inventory[${index}].id is required`, "invalid_sequence_inventory");
    }
    return cloneValue(item);
  }).sort((left, right) => String(left.id).localeCompare(String(right.id)));
}

function inventoryFingerprint(sequence) {
  return stableFingerprint(normalizeInventory(sequence));
}

function fingerprintSource(sequence) {
  requireSequence(sequence);
  return stableFingerprint({
    guid: sequence.guid,
    sequence_id: sequence.sequence_id || null,
    inventory: normalizeInventory(sequence),
    duration: sequence.duration === undefined ? null : sequence.duration,
    settings: sequence.settings || null
  });
}

function sourceMutationCount(before, after) {
  return canonicalStringify(before) === canonicalStringify(after) ? 0 : 1;
}

function resultBase(plan, sourceFingerprint, status, stage, extra = {}) {
  return {
    schema_version: 1,
    status,
    stage,
    pipeline: PIPELINE.slice(),
    plan: plan ? plan.toObject() : null,
    source_fingerprint: sourceFingerprint || null,
    source_mutations: 0,
    external_writes: 0,
    ...extra
  };
}

class SafeEditingPrimitive {
  constructor(adapter) {
    if (!adapter || typeof adapter !== "object") throw new SafeEditingError("adapter is required", "missing_adapter");
    for (const method of ["cloneSequence", "applyPlan", "preview"]) {
      if (typeof adapter[method] !== "function") throw new SafeEditingError(`adapter.${method} is required`, "invalid_adapter");
    }
    this.adapter = adapter;
  }

  sourceFingerprint(source) {
    if (typeof this.adapter.fingerprintSource === "function") return this.adapter.fingerprintSource(source);
    return fingerprintSource(source);
  }

  execute({
    source,
    plan,
    dryRun = false,
    approval = false,
    expectedSourceFingerprint = null,
    assetInventory = this.adapter.assetInventory,
    lockedTracks = this.adapter.lockedTracks,
    collisionPolicy = this.adapter.collisionPolicy || "reject",
    supportedActions = this.adapter.supportedActions || SUPPORTED_ACTIONS,
    cloneSequence = true
  } = {}) {
    let normalizedPlan = null;
    let initialFingerprint = null;
    let sourceBefore = null;
    try {
      sourceBefore = cloneValue(requireSequence(source));
      normalizedPlan = validateTimelinePlan(plan, {
        assetInventory,
        lockedTracks,
        collisionPolicy,
        supportedActions
      }).plan;
      if (cloneSequence !== true) {
        throw new SafeEditingError("clone_sequence must remain enabled", "clone_required");
      }
      initialFingerprint = this.sourceFingerprint(source);
      if (expectedSourceFingerprint && expectedSourceFingerprint !== initialFingerprint) {
        return resultBase(normalizedPlan, initialFingerprint, "fingerprint_changed", "source_fingerprint", {
          errors: [{ code: "expected_fingerprint_mismatch", message: "source fingerprint differs before execution" }],
          clone_status: "not_created"
        });
      }
    } catch (error) {
      const errors = error instanceof PlanValidationError
        ? error.errors.map((message) => ({ code: "preflight", message }))
        : [{ code: error.code || "preflight", message: error.message || String(error) }];
      return resultBase(normalizedPlan, initialFingerprint, "preflight_failed", "preflight", {
        errors,
        clone_status: "not_created"
      });
    }

    if (dryRun) {
      return resultBase(normalizedPlan, initialFingerprint, "dry_run", "dry_run_plan", {
        clone_status: "not_created",
        approval_required: true,
        preview: null
      });
    }

    let clone = null;
    try {
      clone = this.adapter.cloneSequence(source);
      requireSequence(clone, "clone_sequence");
      if (clone.guid === source.guid) throw new SafeEditingError("clone guid must differ from source", "clone_identity_mismatch");
      if (inventoryFingerprint(clone) !== inventoryFingerprint(source)) {
        throw new SafeEditingError("clone inventory must match source before mutation", "clone_inventory_mismatch");
      }
    } catch (error) {
      if (clone && typeof this.adapter.discardClone === "function") this.adapter.discardClone(clone);
      return resultBase(normalizedPlan, initialFingerprint, "preflight_failed", "clone_sequence", {
        errors: [{ code: error.code || "clone_validation", message: error.message || String(error) }],
        clone_status: "discarded"
      });
    }

    const mutationFingerprint = this.sourceFingerprint(source);
    if (mutationFingerprint !== initialFingerprint) {
      if (typeof this.adapter.discardClone === "function") this.adapter.discardClone(clone);
      return resultBase(normalizedPlan, mutationFingerprint, "fingerprint_changed", "source_fingerprint", {
        errors: [{ code: "source_changed_during_preflight", message: "source changed before clone mutation" }],
        clone_status: "discarded"
      });
    }

    let mutation;
    try {
      mutation = this.adapter.applyPlan(clone, normalizedPlan);
      if (!mutation || typeof mutation !== "object") mutation = { applied: [], failed: [], clone };
      const applied = Array.isArray(mutation.applied) ? mutation.applied : [];
      const failed = Array.isArray(mutation.failed) ? mutation.failed : [];
      const allIds = new Set(normalizedPlan.operations.map((operation) => operation.id));
      const appliedIds = new Set(applied.map((item) => typeof item === "string" ? item : item.id));
      const missingApplied = normalizedPlan.operations
        .map((operation) => operation.id)
        .filter((id) => !appliedIds.has(id));
      const reportedFailure = failed.length > 0 || missingApplied.length > 0;
      if (reportedFailure) {
        if (typeof this.adapter.discardClone === "function") this.adapter.discardClone(clone);
        return resultBase(normalizedPlan, initialFingerprint, applied.length ? "partial_success" : "mutation_failed", "mutation_on_clone", {
          clone_status: "discarded",
          applied,
          failed: failed.concat(missingApplied.map((id) => ({ id, reason: "operation_not_applied" }))),
          changed_paths: applied.map((item) => `clone.inventory[operation:${typeof item === "string" ? item : item.id}]`),
          errors: failed,
          source_inventory_fingerprint: inventoryFingerprint(sourceBefore),
          clone_inventory_fingerprint: inventoryFingerprint(clone)
        });
      }
      const postFingerprint = this.sourceFingerprint(source);
      if (postFingerprint !== initialFingerprint || sourceMutationCount(sourceBefore, source) !== 0) {
        if (typeof this.adapter.discardClone === "function") this.adapter.discardClone(clone);
        return resultBase(normalizedPlan, postFingerprint, "fingerprint_changed", "source_fingerprint", {
          clone_status: "discarded",
          errors: [{ code: "source_changed_after_mutation", message: "source changed while clone was being mutated" }]
        });
      }
    } catch (error) {
      if (typeof this.adapter.discardClone === "function") this.adapter.discardClone(clone);
      return resultBase(normalizedPlan, initialFingerprint, "mutation_failed", "mutation_on_clone", {
        clone_status: "discarded",
        errors: [{ code: error.code || "mutation", message: error.message || String(error) }]
      });
    }

    let preview;
    try {
      preview = this.adapter.preview(clone, normalizedPlan);
    } catch (error) {
      if (typeof this.adapter.discardClone === "function") this.adapter.discardClone(clone);
      return resultBase(normalizedPlan, initialFingerprint, "post_validation_failed", "preview", {
        clone_status: "discarded",
        errors: [{ code: error.code || "preview", message: error.message || String(error) }]
      });
    }

    if (!approval) {
      return resultBase(normalizedPlan, initialFingerprint, "awaiting_approval", "user_approval", {
        clone_status: "retained_for_approval",
        approval_required: true,
        preview,
        clone_identity: clone.guid,
        clone_inventory_fingerprint: inventoryFingerprint(clone)
      });
    }

    try {
      const finalClone = typeof this.adapter.finalizeClone === "function"
        ? this.adapter.finalizeClone(clone, normalizedPlan)
        : clone;
      return resultBase(normalizedPlan, initialFingerprint, "completed", "final_use", {
        clone_status: "finalized",
        approval_required: false,
        preview,
        clone_identity: finalClone.guid,
        clone_inventory_fingerprint: inventoryFingerprint(finalClone),
        applied: normalizedPlan.operations.map((operation) => operation.id)
      });
    } catch (error) {
      if (typeof this.adapter.discardClone === "function") this.adapter.discardClone(clone);
      return resultBase(normalizedPlan, initialFingerprint, "post_validation_failed", "final_use", {
        clone_status: "discarded",
        errors: [{ code: error.code || "finalize", message: error.message || String(error) }]
      });
    }
  }
}

class MockEditingAdapter {
  constructor({
    supportedActions = SUPPORTED_ACTIONS,
    assetInventory = [],
    lockedTracks = [],
    collisionPolicy = "reject",
    failAt = null,
    changeOnFingerprintRead = false
  } = {}) {
    this.supportedActions = supportedActions;
    this.assetInventory = assetInventory;
    this.lockedTracks = lockedTracks;
    this.collisionPolicy = collisionPolicy;
    this.failAt = failAt;
    this.changeOnFingerprintRead = changeOnFingerprintRead;
    this.fingerprintReads = 0;
    this.discarded = [];
  }

  fingerprintSource(source) {
    this.fingerprintReads += 1;
    if (this.changeOnFingerprintRead && this.fingerprintReads === 2) {
      const changed = cloneValue(source);
      changed.inventory = changed.inventory.concat([{ id: "external-change" }]);
      return fingerprintSource(changed);
    }
    return fingerprintSource(source);
  }

  cloneSequence(source) {
    const clone = cloneValue(source);
    clone.guid = `${source.guid}-clone`;
    clone.applied_operation_ids = [];
    return clone;
  }

  applyPlan(clone, plan) {
    const applied = [];
    const failed = [];
    plan.operations.forEach((operation, index) => {
      if (this.failAt !== null && index === this.failAt) {
        failed.push({ id: operation.id, reason: "mock_failure" });
        return;
      }
      clone.inventory.push({
        id: `operation:${operation.id}`,
        operation_id: operation.id,
        action: operation.action,
        track: cloneValue(operation.track),
        start: operation.start,
        duration: operation.duration
      });
      clone.applied_operation_ids.push(operation.id);
      applied.push({ id: operation.id, action: operation.action });
    });
    return { clone, applied, failed };
  }

  preview(clone, plan) {
    return {
      sequence_guid: clone.guid,
      operation_ids: plan.operations.map((operation) => operation.id),
      inventory_count: clone.inventory.length
    };
  }

  discardClone(clone) {
    this.discarded.push(clone.guid);
  }

  finalizeClone(clone) {
    clone.finalized = true;
    return clone;
  }
}

module.exports = {
  PIPELINE,
  MockEditingAdapter,
  SafeEditingError,
  SafeEditingPrimitive,
  fingerprintSource,
  inventoryFingerprint
};

