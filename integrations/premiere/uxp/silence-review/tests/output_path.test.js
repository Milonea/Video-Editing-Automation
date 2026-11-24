"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { assertOutputFolder, assertOutputFile, assertSiblingFile, assertSiblingFolder } = require("../output_path.js");

const project = "C:\\VideoProjects\\sample";
const premiere = `${project}\\08_PREMIERE`;
const reports = `${project}\\10_REPORTS`;

test("accepts a user-selected expected Windows output folder", () => {
  assert.doesNotThrow(() => assertOutputFolder(
    premiere,
    `${project.replaceAll("\\", "/")}/08_PREMIERE/`,
  ));
});

test("rejects a user-selected folder outside the planned output directory", () => {
  assert.throws(
    () => assertOutputFolder("D:\\OtherProject", premiere),
    /08_PREMIERE/,
  );
});

test("accepts the generated review filename inside the expected directory", () => {
  assert.doesNotThrow(() => assertOutputFile(
    `${premiere}\\Sample_REVIEW_20261119_120000.prproj`,
    premiere,
    `${premiere}\\source.prproj`,
    "Sample_REVIEW_20261119_120000.prproj",
  ));
});

test("rejects original project and filenames outside the generated name", () => {
  const original = `${premiere}\\source.prproj`;
  assert.throws(() => assertOutputFile(original, premiere, original, "review.prproj"), /원본/);
  assert.throws(() => assertOutputFile(`${premiere}\\manual.prproj`, premiere, original, "review.prproj"), /자동 생성/);
});

test("accepts the generated result JSON next to the selected plan", () => {
  assert.doesNotThrow(() => assertSiblingFile(
    `${reports}\\silence_split_premiere_result_20261119_120000_KST.json`,
    `${reports}\\silence_split_plan.json`,
    "silence_split_premiere_result_20261119_120000_KST.json",
  ));
});

test("rejects result JSON outside the plan folder or with a different name", () => {
  const plan = `${reports}\\silence_split_plan.json`;
  const name = "silence_split_premiere_result_20261119_120000_KST.json";
  assert.throws(() => assertSiblingFile(`${premiere}\\${name}`, plan, name), /같은 10_REPORTS/);
  assert.throws(() => assertSiblingFile(`${reports}\\manual.json`, plan, name), /자동 생성/);
});

test("accepts only the report folder that contains the selected plan", () => {
  const plan = `${reports}\\silence_split_plan.json`;
  assert.doesNotThrow(() => assertSiblingFolder(reports, plan));
  assert.throws(() => assertSiblingFolder(premiere, plan), /같은 10_REPORTS/);
});
