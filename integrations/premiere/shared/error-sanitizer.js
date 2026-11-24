"use strict";

const NATIVE_PATH_PLACEHOLDER = "[native path omitted]";
const HOST_STACK_PLACEHOLDER = "[host stack omitted]";

function sanitizeText(value) {
  let text = String(value ?? "");

  // Stack frames are implementation detail and can contain absolute source paths.
  text = text.replace(/(^|\n)[ \t]*at\s+[^\n]*/g, `$1${HOST_STACK_PLACEHOLDER}`);

  // Cover drive-letter paths, including the extended Windows prefix. The match is
  // intentionally bounded by common message delimiters so the rest of a message
  // remains available to the user.
  text = text.replace(
    /(^|[\s("'=,:])(?:\\\\\?\\)?[A-Za-z]:[\\/][^\n"'<>)]*/g,
    `$1${NATIVE_PATH_PLACEHOLDER}`
  );

  // Cover UNC paths and the absolute Unix roots used by the plugin/host without
  // treating normal relative config paths as native paths.
  text = text.replace(
    /(^|[\s("'=,:])\\\\[^\n"'<>)]*/g,
    `$1${NATIVE_PATH_PLACEHOLDER}`
  );
  text = text.replace(
    /(^|[\s("'=,:])\/(?:Users|Volumes|private|tmp|var|home|mnt|opt|Applications|Library|System|etc|dev)\/[^\n"'<>)]*/g,
    `$1${NATIVE_PATH_PLACEHOLDER}`
  );

  return text;
}

function sanitizeErrorMessage(error) {
  if (error && typeof error === "object" && error.message) return sanitizeText(error.message);
  return sanitizeText(error);
}

function sanitizeForDisplay(value) {
  if (typeof value === "string") return sanitizeText(value);
  if (Array.isArray(value)) return value.map(sanitizeForDisplay);
  if (!value || typeof value !== "object") return value;

  const result = {};
  for (const [key, child] of Object.entries(value)) result[key] = sanitizeForDisplay(child);
  return result;
}

module.exports = {
  HOST_STACK_PLACEHOLDER,
  NATIVE_PATH_PLACEHOLDER,
  sanitizeErrorMessage,
  sanitizeForDisplay,
  sanitizeText
};

