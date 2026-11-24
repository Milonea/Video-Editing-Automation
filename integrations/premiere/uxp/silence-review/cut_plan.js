"use strict";

function assertInteger(value, label) {
  const result = Number(value);
  if (!Number.isInteger(result) || result < 0) {
    throw new Error(`${label} must be a non-negative integer frame.`);
  }
  return result;
}

function buildTargetedCutPlan(candidates, trackSnapshots, selectedTargets) {
  const selected = new Set(
    selectedTargets.map((target) => `${target.media_type}:${assertInteger(target.track_index, "track index")}`),
  );
  const targetTracks = trackSnapshots.filter((track) => selected.has(`${track.media_type}:${track.track_index}`));
  const boundaries = new Map();

  for (const candidate of candidates) {
    if (candidate.candidate_type !== "inter_caption") continue;
    const start = assertInteger(candidate.start_frame, `${candidate.candidate_id} start`);
    const end = assertInteger(candidate.end_frame, `${candidate.candidate_id} end`);
    if (end <= start) throw new Error(`${candidate.candidate_id} has an invalid frame interval.`);
    for (const [edge, frame] of [["start", start], ["end", end]]) {
      const key = String(frame);
      const boundary = boundaries.get(key) || { frame, candidate_edges: [], actions: new Map(), covered_targets: new Set() };
      boundary.candidate_edges.push({ candidate_id: candidate.candidate_id, edge });
      for (const track of targetTracks) {
        const spans = track.intervals.some((interval) => interval.start_frame < frame && frame < interval.end_frame);
        const alreadyCut = track.boundary_frames.includes(frame);
        if (!spans && !alreadyCut) continue;
        boundary.covered_targets.add(`${track.media_type}:${track.track_index}`);
        if (!spans || alreadyCut) continue;
        const actionKey = `${track.media_type}:${track.track_index}:${frame}`;
        if (!boundary.actions.has(actionKey)) {
          boundary.actions.set(actionKey, {
            media_type: track.media_type,
            track_index: track.track_index,
            frame,
          });
        }
      }
      boundaries.set(key, boundary);
    }
  }

  const normalizedBoundaries = [...boundaries.values()]
    .sort((left, right) => left.frame - right.frame)
    .map((boundary) => ({
      frame: boundary.frame,
      candidate_edges: boundary.candidate_edges,
      actions: [...boundary.actions.values()],
      covered_targets: [...boundary.covered_targets].sort(),
    }));
  const candidateOutcomes = candidates
    .filter((candidate) => candidate.candidate_type === "inter_caption")
    .map((candidate) => {
      const start = normalizedBoundaries.find((boundary) => boundary.frame === Number(candidate.start_frame));
      const end = normalizedBoundaries.find((boundary) => boundary.frame === Number(candidate.end_frame));
      const startTargetTracks = start?.covered_targets || [];
      const endTargetTracks = end?.covered_targets || [];
      return {
        candidate_id: candidate.candidate_id,
        start_frame: Number(candidate.start_frame),
        end_frame: Number(candidate.end_frame),
        start_covered: startTargetTracks.length > 0,
        end_covered: endTargetTracks.length > 0,
        start_target_tracks: startTargetTracks,
        end_target_tracks: endTargetTracks,
      };
    });

  return {
    boundaries: normalizedBoundaries,
    actions: normalizedBoundaries.flatMap((boundary) => boundary.actions),
    candidate_outcomes: candidateOutcomes,
  };
}

function validateCompletedCandidates(plan, targetTrackBoundaryKeys) {
  const boundaries = new Set(targetTrackBoundaryKeys.map((value) => String(value)));
  const verifiedForEveryTrack = (trackKeys, frame) => trackKeys.length > 0
    && trackKeys.every((trackKey) => boundaries.has(`${trackKey}:${frame}`));
  return plan.candidate_outcomes.map((candidate) => ({
    candidate_id: candidate.candidate_id,
    start_cut_verified: verifiedForEveryTrack(candidate.start_target_tracks, candidate.start_frame),
    end_cut_verified: verifiedForEveryTrack(candidate.end_target_tracks, candidate.end_frame),
    complete: verifiedForEveryTrack(candidate.start_target_tracks, candidate.start_frame)
      && verifiedForEveryTrack(candidate.end_target_tracks, candidate.end_frame),
  }));
}

module.exports = { buildTargetedCutPlan, validateCompletedCandidates };
