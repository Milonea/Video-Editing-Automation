"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { normalizePath, toUxpFileUrl } = require("../path_utils.js");

test("normalizes Premiere extended-length drive paths", () => {
  assert.equal(
    normalizePath("\\\\?\\C:\\VideoProjects\\sample\\review.prproj"),
    normalizePath("C:/VideoProjects/sample/review.prproj"),
  );
});

test("normalizes extended UNC paths without losing the network prefix", () => {
  assert.equal(
    normalizePath("\\\\?\\UNC\\server\\share\\project.prproj"),
    normalizePath("\\\\server\\share\\project.prproj"),
  );
  assert.equal(normalizePath("\\\\server\\share\\project.prproj"), "//server/share/project.prproj");
});

test("normalizes case and repeated separators", () => {
  assert.equal(normalizePath("C:\\VideoProjects\\\\Sample\\FILE.prproj"), "c:/videoprojects/sample/file.prproj");
});

test("builds UXP Windows file URLs without percent-encoding Unicode paths", () => {
  assert.equal(
    toUxpFileUrl("C:\\VideoProjects\\편집 샘플\\08_PREMIERE"),
    "file:/C:/VideoProjects/편집 샘플/08_PREMIERE",
  );
});

test("builds UXP file URLs for extended Windows and POSIX paths", () => {
  assert.equal(
    toUxpFileUrl("\\\\?\\C:\\VideoProjects\\Sample"),
    "file:/C:/VideoProjects/Sample",
  );
  const userPath = ["", "Users", "fixture-home", "VEA Project"].join("/");
  const expectedUrl = ["file:", "Users", "fixture-home", "VEA Project"].join("/");
  assert.equal(toUxpFileUrl(userPath), expectedUrl);
});
