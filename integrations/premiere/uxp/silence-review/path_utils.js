"use strict";

function normalizePath(value) {
  let path = String(value || "").replace(/\\/g, "/");

  if (/^\/\/\?\/unc\//i.test(path)) {
    path = `//${path.slice(8)}`;
  } else if (/^\/\/\?\//.test(path)) {
    path = path.slice(4);
  }

  if (path.startsWith("//")) {
    path = `//${path.slice(2).replace(/\/{2,}/g, "/")}`;
  } else {
    path = path.replace(/\/{2,}/g, "/");
  }

  return path.replace(/\/$/, "").toLowerCase();
}

function toUxpFileUrl(value) {
  let path = String(value || "").replace(/\\/g, "/");

  if (/^\/\/\?\/unc\//i.test(path)) {
    path = `//${path.slice(8)}`;
  } else if (/^\/\/\?\//.test(path)) {
    path = path.slice(4);
  }

  if (/^[a-z]:\//i.test(path)) return `file:/${path}`;
  if (path.startsWith("/")) return `file:${path}`;
  throw new Error(`Expected an absolute filesystem path: ${value}`);
}

module.exports = { normalizePath, toUxpFileUrl };
