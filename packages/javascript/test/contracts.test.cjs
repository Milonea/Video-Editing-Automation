"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadSchema, validateContract } = require("../contracts.cjs");

const root = path.resolve(__dirname, "../../..");
const fixtures = JSON.parse(fs.readFileSync(path.join(root, "contracts/examples/contracts-v1.json"), "utf8"));

test("each shared fixture has a schema definition and passes runtime invariants", () => {
  const definitions = loadSchema().$defs;
  assert.deepEqual(Object.keys(fixtures).sort(), Object.keys(definitions).sort());
  for (const [kind, value] of Object.entries(fixtures)) {
    assert.deepEqual(validateContract(kind, value), [], `${kind} fixture should pass`);
  }
});

test("timeline references declared tracks and uses positive frame ranges", () => {
  const timeline = structuredClone(fixtures.TimelineIR);
  timeline.clips[0].track_id = "missing-track";
  timeline.clips[0].end_frame = 0;
  const errors = validateContract("TimelineIR", timeline);
  assert.ok(errors.some((error) => error.includes("undeclared track")));
  assert.ok(errors.some((error) => error.includes("non-positive frame range")));
});

test("recipe safety policies cannot be disabled", () => {
  const recipe = structuredClone(fixtures.EditingRecipe);
  recipe.policies.approval_required = false;
  assert.ok(validateContract("EditingRecipe", recipe).some((error) => error.includes("require approval")));
});

test("asset paths cannot be absolute or escape the workspace", () => {
  assert.ok(validateContract("MediaAsset", { ...fixtures.MediaAsset, relative_path: "C:/private/file.mov" }).length > 0);
  assert.ok(validateContract("MediaAsset", { ...fixtures.MediaAsset, relative_path: "../../private/file.mov" }).length > 0);
});
