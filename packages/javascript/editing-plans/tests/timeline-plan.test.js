"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  PlanValidationError,
  TimelinePlan,
  diffPlans,
  validateTimelinePlan
} = require("../lib/timeline-plan-ir");
const {
  MockEditingAdapter,
  SafeEditingPrimitive
} = require("../lib/safe-editing-primitive");
const {
  compileRecipe,
  executeRecipe
} = require("../lib/edit-recipe");

const provenance = { source_id: "test-fixture", captured_at: "2026-08-26" };

function operation(id, overrides = {}) {
  return {
    id,
    action: "insert_media",
    track: { type: "video", index: 1 },
    start: 0,
    duration: 5,
    asset: { id: `${id}.png`, kind: "media" },
    provenance,
    ...overrides
  };
}

function plan(operations) {
  return new TimelinePlan({
    plan_id: "fixture-plan",
    sequence_id: "sequence-1",
    operations
  });
}

function source() {
  return {
    guid: "source-sequence-1",
    sequence_id: "sequence-1",
    inventory: [{ id: "existing-clip", track: { type: "video", index: 0 }, start: 0, duration: 10 }]
  };
}

test("Timeline Plan IR canonicalizes and diffs deterministically", () => {
  const first = plan([operation("intro")]);
  const same = plan([operation("intro")]);
  const changed = plan([operation("intro", { duration: 6 })]);

  assert.equal(JSON.stringify(first), JSON.stringify(same));
  assert.equal(diffPlans(first, same).status, "no_change");
  assert.deepEqual(diffPlans(first, new TimelinePlan({
    plan_id: "fixture-plan",
    sequence_id: "sequence-2",
    operations: [operation("intro")]
  })).changed_paths, ["plan.sequence_id"]);
  assert.deepEqual(diffPlans(first, changed).modified, [{
    id: "intro",
    changed_paths: ["operations.intro.duration"]
  }]);
});

test("Timeline Plan IR rejects range, collision, lock, asset, and action violations", () => {
  assert.throws(
    () => plan([operation("bad", { start: -1 })]),
    PlanValidationError
  );

  const colliding = plan([operation("a"), operation("b", { start: 3 })]);
  assert.throws(
    () => validateTimelinePlan(colliding, { assetInventory: ["a.png", "b.png"] }),
    (error) => error instanceof PlanValidationError && error.errors.some((item) => item.includes("collision"))
  );

  const locked = plan([operation("locked")]);
  assert.throws(
    () => validateTimelinePlan(locked, { assetInventory: ["locked.png"], lockedTracks: ["video:1"] }),
    (error) => error instanceof PlanValidationError && error.errors.some((item) => item.includes("locked track"))
  );

  const missing = plan([operation("missing")]);
  assert.throws(
    () => validateTimelinePlan(missing, { assetInventory: [] }),
    (error) => error instanceof PlanValidationError && error.errors.some((item) => item.includes("missing asset"))
  );

  assert.throws(
    () => validateTimelinePlan(plan([operation("unsupported", { action: "delete_clip" })]), { assetInventory: ["unsupported.png"] }),
    (error) => error instanceof PlanValidationError && error.errors.some((item) => item.includes("unsupported action"))
  );
});

test("Safe Editing Primitive keeps source unchanged through dry-run, approval, and clone mutation", () => {
  const original = source();
  const originalText = JSON.stringify(original);
  const editingPlan = plan([operation("intro")]);
  const adapter = new MockEditingAdapter({ assetInventory: ["intro.png"] });
  const primitive = new SafeEditingPrimitive(adapter);

  const dryRun = primitive.execute({ source: original, plan: editingPlan, dryRun: true });
  assert.equal(dryRun.status, "dry_run");
  assert.equal(JSON.stringify(original), originalText);

  const preview = primitive.execute({ source: original, plan: editingPlan, approval: false });
  assert.equal(preview.status, "awaiting_approval");
  assert.equal(preview.clone_status, "retained_for_approval");
  assert.equal(JSON.stringify(original), originalText);

  const completed = primitive.execute({ source: original, plan: editingPlan, approval: true });
  assert.equal(completed.status, "completed");
  assert.equal(completed.source_mutations, 0);
  assert.equal(JSON.stringify(original), originalText);
});

test("Safe Editing Primitive returns fingerprint and partial-failure states", () => {
  const editingPlan = plan([
    operation("intro"),
    operation("outro", { start: 6, asset: { id: "outro.png", kind: "media" } })
  ]);
  const partialAdapter = new MockEditingAdapter({ assetInventory: ["intro.png", "outro.png"], failAt: 1 });
  const partial = new SafeEditingPrimitive(partialAdapter).execute({ source: source(), plan: editingPlan, approval: true });
  assert.equal(partial.status, "partial_success");
  assert.equal(partial.clone_status, "discarded");
  assert.deepEqual(partialAdapter.discarded, ["source-sequence-1-clone"]);

  const changedAdapter = new MockEditingAdapter({ assetInventory: ["intro.png"], changeOnFingerprintRead: true });
  const changed = new SafeEditingPrimitive(changedAdapter).execute({ source: source(), plan: plan([operation("intro")]) });
  assert.equal(changed.status, "fingerprint_changed");
  assert.equal(changed.clone_status, "discarded");
});

function recipe(overrides = {}) {
  return {
    id: "sample-edit",
    version: "1.0.0",
    inputs: {
      sequence_id: "sequence-1",
      assets: {
        intro: "intro.png",
        sfx: "whoosh.wav",
        outro: "outro.png"
      }
    },
    policies: {
      missing_asset: "partial",
      unsupported_host: "blocked",
      collision: "reject"
    },
    steps: [
      { id: "intro", type: "intro", order: 0, track: { type: "video", index: 1 }, start: 0, duration: 5, asset: "intro" },
      { id: "sfx", type: "sfx", order: 1, track: { type: "audio", index: 2 }, start: 0, duration: 2, asset: "sfx", required_host_capability: "audio-overwrite" },
      { id: "outro", type: "outro", order: 2, track: { type: "video", index: 1 }, start: 6, duration: 5, asset: "outro" }
    ],
    ...overrides
  };
}

test("Edit Recipe compiles to deterministic IR and missing SFX stays partial", () => {
  const options = {
    assetInventory: ["intro.png", "outro.png"],
    hostCapabilities: ["audio-overwrite"]
  };
  const first = compileRecipe(recipe(), options);
  const second = compileRecipe(recipe(), options);
  assert.equal(first.status, "partial");
  assert.deepEqual(first.skipped_steps, [{ step_id: "sfx", reason: "missing_asset:whoosh.wav" }]);
  assert.deepEqual(first.plan.toObject(), second.plan.toObject());
  assert.deepEqual(first.plan.operations.map((item) => item.id), ["intro", "outro"]);

  const result = executeRecipe(recipe(), {
    source: source(),
    adapter: new MockEditingAdapter({ assetInventory: ["intro.png", "outro.png"] }),
    ...options,
    approval: true
  });
  assert.equal(result.status, "partial_success");
  assert.equal(result.underlying_status, "completed");
  assert.equal(result.external_writes, 0);
});

test("Edit Recipe leaves an unconfirmed host capability unsupported", () => {
  const result = executeRecipe(recipe({
    policies: { missing_asset: "partial", unsupported_host: "blocked", collision: "reject" },
    steps: [{
      id: "caption",
      type: "caption",
      order: 0,
      track: { type: "video", index: 1 },
      start: 0,
      duration: 3,
      required_host_capability: "caption-mogrt"
    }]
  }), {
    source: source(),
    adapter: new MockEditingAdapter(),
    assetInventory: [],
    hostCapabilities: []
  });
  assert.equal(result.status, "unsupported");
  assert.equal(result.source_mutations, 0);
  assert.equal(result.external_writes, 0);
});

test("Edit Recipe rejects missing required assets before execution", () => {
  const invalid = recipe({ policies: { missing_asset: "fail", unsupported_host: "blocked", collision: "reject" } });
  const result = executeRecipe(invalid, {
    source: source(),
    adapter: new MockEditingAdapter(),
    assetInventory: []
  });
  assert.equal(result.status, "preflight_failed");
  assert.equal(result.stage, "recipe_preflight");
  assert.equal(result.source_mutations, 0);
});

test("machine-readable IR, recipe, and source fixtures stay loadable", () => {
  const fixtureRoot = path.join(__dirname, "fixtures");
  const readJson = (name) => JSON.parse(fs.readFileSync(path.join(fixtureRoot, name), "utf8"));
  const planFixture = readJson("timeline-plan.json");
  const recipeFixture = readJson("edit-recipe.json");
  const sourceFixture = readJson("source-sequence.json");

  assert.equal(validateTimelinePlan(planFixture, {
    assetInventory: ["intro.png", "information.mogrt"]
  }).plan.schema_version, 1);
  const compiled = compileRecipe(recipeFixture, {
    assetInventory: ["intro.png", "information.mogrt"],
    hostCapabilities: ["mogrt-insert"]
  });
  assert.equal(compiled.status, "partial");
  assert.equal(sourceFixture.guid, "fixture-source-sequence");
});

