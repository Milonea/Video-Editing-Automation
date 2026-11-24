"use strict";

function chooseSplitMode(plan, context) {
  if (plan?.actions?.implemented_mode !== "split_with_review_marker_fallback") return null;
  return context?.razorAvailable === true ? "razor" : null;
}

module.exports = { chooseSplitMode };
