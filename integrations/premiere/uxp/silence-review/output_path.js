"use strict";

const { normalizePath } = require("./path_utils.js");

function assertOutputFolder(selectedPath, expectedPath) {
  if (!selectedPath) throw new Error("선택한 폴더의 로컬 경로를 확인하지 못했습니다.");
  if (normalizePath(selectedPath) !== normalizePath(expectedPath)) {
    throw new Error(`검토 프로젝트를 저장할 폴더로 VEA 프로젝트의 08_PREMIERE 폴더를 선택해야 합니다: ${expectedPath}`);
  }
}

function assertOutputFile(path, expectedDirectory, originalPath, expectedName) {
  if (!path) throw new Error("선택한 저장 위치에서 로컬 경로를 확인하지 못했습니다.");
  const normalizedPath = String(path).replace(/\\/g, "/");
  const separator = normalizedPath.lastIndexOf("/");
  const actualDirectory = separator < 0 ? "" : normalizedPath.slice(0, separator);
  const actualName = normalizedPath.slice(separator + 1);
  if (normalizePath(actualDirectory) !== normalizePath(expectedDirectory)) {
    throw new Error("검토 프로젝트는 VEA 프로젝트의 08_PREMIERE 폴더 안에 저장해야 합니다.");
  }
  if (normalizePath(path) === normalizePath(originalPath)) {
    throw new Error("원본 Premiere 프로젝트 경로로 저장할 수 없습니다.");
  }
  if (actualName !== expectedName) {
    throw new Error(`새 버전 파일명은 자동 생성 이름이어야 합니다: ${expectedName}`);
  }
}

function assertSiblingFile(path, referencePath, expectedName) {
  if (!path || !referencePath) throw new Error("선택한 파일의 로컬 경로를 확인하지 못했습니다.");
  const normalizedPath = String(path).replace(/\\/g, "/");
  const normalizedReference = String(referencePath).replace(/\\/g, "/");
  const pathSeparator = normalizedPath.lastIndexOf("/");
  const referenceSeparator = normalizedReference.lastIndexOf("/");
  const actualDirectory = pathSeparator < 0 ? "" : normalizedPath.slice(0, pathSeparator);
  const referenceDirectory = referenceSeparator < 0 ? "" : normalizedReference.slice(0, referenceSeparator);
  const actualName = normalizedPath.slice(pathSeparator + 1);
  if (normalizePath(actualDirectory) !== normalizePath(referenceDirectory)) {
    throw new Error("결과 JSON은 VEA 작업 계획 파일과 같은 10_REPORTS 폴더에 저장해야 합니다.");
  }
  if (actualName !== expectedName) {
    throw new Error(`결과 JSON 파일명은 자동 생성 이름이어야 합니다: ${expectedName}`);
  }
}

function assertSiblingFolder(path, referencePath) {
  if (!path || !referencePath) throw new Error("선택한 폴더의 로컬 경로를 확인하지 못했습니다.");
  const normalizedReference = String(referencePath).replace(/\\/g, "/");
  const referenceSeparator = normalizedReference.lastIndexOf("/");
  const referenceDirectory = referenceSeparator < 0 ? "" : normalizedReference.slice(0, referenceSeparator);
  if (normalizePath(path) !== normalizePath(referenceDirectory)) {
    throw new Error("결과 JSON을 저장할 때 VEA 작업 계획과 같은 10_REPORTS 폴더를 선택해야 합니다.");
  }
}

module.exports = { assertOutputFolder, assertOutputFile, assertSiblingFile, assertSiblingFolder };
