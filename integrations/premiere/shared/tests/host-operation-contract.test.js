"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { runInsertionFlow } = require("../host-operation-contract");
const { sanitizeForDisplay, sanitizeText } = require("../error-sanitizer");
const { ProjectItemCache } = require("../project-item-cache");

function adapters({ preflight, insertMedia, insertMogrt, insertAudio } = {}) {
  return {
    paths: {
      getExternalRoot: async () => ({ id: "fixture-workspace" }),
      resolveExternalAssetPath: async (value) => `/fixture/${value}`,
      resolvePluginAssetPath: async (value) => `/plugin/${value}`
    },
    premiere: {
      preflight: preflight || (async () => ({ ok: true, checks: [{ name: "track-clear", ok: true }] })),
      insertMedia: insertMedia || (async () => ({ operation: { status: "success", stages: [] }, playerPosition: 120 })),
      insertMogrt: insertMogrt || (async () => ({ operation: { status: "success", stages: [] }, playerPosition: 120 })),
      insertAudio: insertAudio || (async () => null)
    }
  };
}

test("insertion flow never mutates Premiere when preflight blocks", async () => {
  let insertions = 0;
  const value = adapters({
    preflight: async () => ({ ok: false, checks: [{ name: "track-clear", ok: false, code: "TRACK_LOCKED" }] }),
    insertMedia: async () => { insertions += 1; }
  });
  const result = await runInsertionFlow({ ...value, assetPath: "media/title.png", assetKind: "media", durationSeconds: 2 });
  assert.equal(result.status, "failed");
  assert.equal(result.stage, "preflight");
  assert.equal(result.source_mutations, 0);
  assert.equal(insertions, 0);
});

test("insertion flow dry-run resolves and preflights but does not call the host mutation", async () => {
  let insertions = 0;
  const value = adapters({ insertMedia: async () => { insertions += 1; } });
  const result = await runInsertionFlow({ ...value, assetPath: "media/title.png", assetKind: "media", durationSeconds: 2, dryRun: true });
  assert.equal(result.status, "dry_run");
  assert.equal(result.external_writes, 0);
  assert.equal(insertions, 0);
});

test("insertion flow waits for explicit approval after a successful preflight", async () => {
  let insertions = 0;
  const value = adapters({ insertMedia: async () => { insertions += 1; } });
  const result = await runInsertionFlow({ ...value, assetPath: "media/title.png", assetKind: "media", durationSeconds: 2 });
  assert.equal(result.status, "awaiting_approval");
  assert.equal(result.stage, "approval");
  assert.equal(insertions, 0);
});

test("insertion flow reports complete success only after the injected host succeeds", async () => {
  let insertedPath = null;
  const value = adapters({ insertMedia: async (path) => {
    insertedPath = path;
    return { operation: { status: "success", stages: [] }, playerPosition: 120 };
  } });
  const result = await runInsertionFlow({ ...value, assetPath: "media/title.png", assetKind: "media", durationSeconds: 2, approval: true });
  assert.equal(result.status, "success");
  assert.equal(insertedPath, "/plugin/media/title.png");
  assert.equal(result.source_mutations, 0);
});

test("error display sanitization hides native paths recursively", () => {
  const windowsPath = ["C:", "Users", "fixture-home", "source.js"].join("\\");
  const unixPath = ["", "Users", "fixture-home", "media.mov"].join("/");
  assert.equal(sanitizeText(`failed at ${windowsPath}`), "failed at [native path omitted]");
  assert.deepEqual(sanitizeForDisplay({ path: unixPath }), { path: "[native path omitted]" });
});

test("project item cache invalidates when the active project changes", () => {
  const cache = new ProjectItemCache((value) => String(value).toLowerCase());
  cache.useProject("project-a");
  cache.set("/MEDIA/title.png", { id: "title" });
  assert.equal(cache.get("/media/title.png").id, "title");
  cache.useProject("project-b");
  assert.equal(cache.get("/media/title.png"), null);
  assert.equal(cache.diagnostics().projectKey, "project-b");
});
