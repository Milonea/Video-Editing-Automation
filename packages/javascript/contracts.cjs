"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../..");
const SCHEMA_PATH = path.join(ROOT, "contracts", "schemas", "contracts-v1.schema.json");

function loadSchema() {
  return JSON.parse(fs.readFileSync(SCHEMA_PATH, "utf8"));
}

function isRelativePath(value) {
  if (typeof value !== "string" || !value.trim()) return false;
  const normalized = value.replace(/\\/g, "/");
  return !normalized.startsWith("/") && !/^[a-z]:/i.test(normalized) && !normalized.split("/").includes("..");
}

function unique(items, key) {
  if (!Array.isArray(items)) return true;
  const values = items.map((item) => item && item[key]);
  return new Set(values).size === values.length;
}

function validateContract(kind, value) {
  const errors = [];
  const definitions = loadSchema().$defs;
  if (!Object.prototype.hasOwnProperty.call(definitions, kind)) return [`unknown contract type: ${kind}`];
  if (kind === "MediaAsset" && !isRelativePath(value && value.relative_path)) errors.push("relative_path must stay inside its declared root");
  if (kind === "AssetIndex") {
    if (!unique(value.assets, "asset_id")) errors.push("assets contain duplicate asset_id values");
    for (const asset of value.assets || []) if (!isRelativePath(asset.relative_path)) errors.push("asset path must stay inside its declared root");
  }
  if (kind === "ProjectManifest" && !isRelativePath(value.asset_index)) errors.push("asset_index must stay inside its declared root");
  if (kind === "TimelineIR") {
    if (!unique(value.tracks, "track_id")) errors.push("tracks contain duplicate track_id values");
    if (!unique(value.clips, "clip_id")) errors.push("clips contain duplicate clip_id values");
    const trackIds = new Set((value.tracks || []).map((track) => track.track_id));
    for (const clip of value.clips || []) {
      if (!trackIds.has(clip.track_id)) errors.push(`clip ${clip.clip_id} references an undeclared track`);
      if (clip.end_frame <= clip.start_frame || clip.source_out_frame <= clip.source_in_frame) errors.push(`clip ${clip.clip_id} has a non-positive frame range`);
    }
  }
  if (kind === "EditPlan" && (!unique(value.operations, "operation_id") || value.approval_required !== true || value.source_mutation !== "forbid")) {
    errors.push("edit plans require unique operations, approval, and source preservation");
  }
  if (kind === "EditingRecipe") {
    if (!unique(value.steps, "step_id")) errors.push("recipe steps contain duplicate step_id values");
    const policy = value.policies || {};
    if (policy.preview !== true || policy.approval_required !== true || policy.clone_sequence !== true || policy.source_mutation !== "forbid") {
      errors.push("recipes must preview, require approval, clone the sequence, and preserve the source");
    }
  }
  if (kind === "Transcript" || kind === "Subtitle") {
    const entries = kind === "Transcript" ? value.segments || [] : value.cues || [];
    const id = kind === "Transcript" ? "segment_id" : "cue_id";
    if (!unique(entries, id)) errors.push(`${kind} contains duplicate ${id} values`);
    for (const entry of entries) if (entry.end_frame <= entry.start_frame) errors.push(`${id} ${entry[id]} has a non-positive frame range`);
  }
  if (kind === "Checkpoint" && (value.completed_step_ids || []).some((id) => (value.pending_step_ids || []).includes(id))) {
    errors.push("completed and pending checkpoint steps must be disjoint");
  }
  if (kind === "ExtensionManifest") {
    if (!unique(value.capabilities, "capability_id")) errors.push("extension capabilities contain duplicate ids");
    if (!unique(value.actions, "action_id")) errors.push("extension actions contain duplicate ids");
    for (const assetRoot of value.asset_roots || []) if (!isRelativePath(assetRoot)) errors.push("extension asset roots must stay inside their declared root");
    for (const schemaPath of value.schemas || []) if (!isRelativePath(schemaPath)) errors.push("extension schema paths must stay inside their declared root");
  }
  if (kind === "AgentResult") for (const artifactRef of value.artifact_refs || []) if (!isRelativePath(artifactRef)) errors.push("agent artifact references must be relative paths");
  if (kind === "ExecutionResult" && (value.source_mutations !== 0 || value.external_writes !== 0)) {
    errors.push("execution result reports a forbidden source mutation or external write");
  }
  return errors;
}

module.exports = { loadSchema, validateContract };
