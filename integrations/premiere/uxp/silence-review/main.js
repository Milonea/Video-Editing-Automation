"use strict";

const ppro = require("premierepro");
const { storage } = require("uxp");
const cutPlan = require("./cut_plan.js");
const { chooseSplitMode } = require("./split_mode.js");
const { normalizePath } = require("./path_utils.js");
const { assertOutputFolder, assertOutputFile, assertSiblingFile, assertSiblingFolder } = require("./output_path.js");
const { resolveCaptionTrack } = require("./caption_track.js");
const fs = storage.localFileSystem;

const prepareButton = document.getElementById("prepare");
const applyButton = document.getElementById("apply");
const statusBox = document.getElementById("status");
const targetPanel = document.getElementById("track-targets");
const targetNote = document.getElementById("track-target-note");
const audioTrackLegend = document.getElementById("audio-track-legend");
const videoTrackList = document.getElementById("video-tracks");
const audioTrackList = document.getElementById("audio-tracks");

let pending = null;
let selectedTargets = [];

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.toggle("error", isError);
}

function safeName(value) {
  const name = String(value || "VEA_Project")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/\s+/g, " ")
    .replace(/[ ._]+$/g, "")
    .slice(0, 100);
  return name || "VEA_Project";
}

function kstStamp(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}${value.month}${value.day}_${value.hour}${value.minute}${value.second}_KST`;
}

function equalRate(actual, expected) {
  const expectedValue = Number(expected.numerator) / Number(expected.denominator);
  return Number.isFinite(expectedValue) && Math.abs(actual - expectedValue) <= 0.001;
}

function verifyPlanShape(plan) {
  if (!plan || plan.schema_version !== 1) throw new Error("지원하지 않는 VEA 작업 계획입니다.");
  if (!plan.actions || plan.actions.auto_delete !== false) throw new Error("작업 계획에서 자동 삭제가 금지되어 있지 않습니다.");
  if (!new Set(["split_with_review_marker_fallback", "review_markers_only"]).has(plan.actions.implemented_mode)) {
    throw new Error("이 패널이 처리할 수 없는 작업 계획입니다.");
  }
  if (plan.analysis?.blocked || !Array.isArray(plan.analysis?.candidates)) {
    throw new Error("자막 시간 검증이 보류된 계획은 Premiere에 적용하지 않습니다.");
  }
  if (!plan.analysis.candidates.length) throw new Error("표시할 무음 후보가 없습니다.");
  if (!plan.premiere_project?.path || !plan.premiere_project?.sequence_name) {
    throw new Error("Premiere 기준본 경로 또는 시퀀스 이름이 없습니다.");
  }
  const splitApi = plan.actions.split_api;
  if (plan.actions.implemented_mode === "split_with_review_marker_fallback"
      && (!splitApi || splitApi.method !== "SequenceEditor.createRazorTrackAction")) {
    throw new Error("분할 작업 계획에 Premiere Razor API 요구 정보가 없습니다.");
  }
}

function sequenceGuid(sequence) {
  return String(sequence.guid);
}

async function findSequenceByGuid(project, guid) {
  const sequences = await project.getSequences();
  return sequences.find((sequence) => sequenceGuid(sequence) === guid) || null;
}

async function inspectTrackEditApis(sequence, editor) {
  const itemMethods = [
    "createSetStartAction",
    "createSetEndAction",
    "createSetInPointAction",
    "createSetOutPointAction",
    "createMoveAction",
  ];
  const result = {
    cloneTrackItem: typeof editor.createCloneTrackItemAction === "function",
    videoTrackItem: null,
    audioTrackItem: null,
  };

  try {
    const trackCount = await sequence.getVideoTrackCount();
    for (let index = 0; index < trackCount && !result.videoTrackItem; index += 1) {
      const track = await sequence.getVideoTrack(index);
      const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      if (Array.isArray(items) && items.length) {
        result.videoTrackItem = Object.fromEntries(itemMethods.map((name) => [name, typeof items[0][name] === "function"]));
      }
    }
  } catch (error) {
    result.videoTrackItemError = String(error);
  }

  try {
    const trackCount = await sequence.getAudioTrackCount();
    for (let index = 0; index < trackCount && !result.audioTrackItem; index += 1) {
      const track = await sequence.getAudioTrack(index);
      const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      if (Array.isArray(items) && items.length) {
        result.audioTrackItem = Object.fromEntries(itemMethods.map((name) => [name, typeof items[0][name] === "function"]));
      }
    }
  } catch (error) {
    result.audioTrackItemError = String(error);
  }

  return result;
}

function trackEditApiSummary(apis) {
  const summarizeItem = (item) => item === null
    ? "sample=none"
    : Object.entries(item).map(([name, available]) => `${name}=${available}`).join(",");
  return `clone=${apis.cloneTrackItem}; video[${summarizeItem(apis.videoTrackItem)}]; audio[${summarizeItem(apis.audioTrackItem)}]`;
}

function razorUnavailableReason(context) {
  return `Razor API 미노출: createRazorTrackAction=${context.razorAvailable}, createRazorAllTracksAction=${context.razorAllTracksAvailable}. Clone/trim 액션(${trackEditApiSummary(context.trackEditApis)})은 인접 클립을 덮을 수 있어 자동 분할 대체로 사용하지 않습니다.`;
}

async function getActiveContext(plan) {
  const project = await ppro.Project.getActiveProject();
  if (!project) throw new Error("열린 Premiere 프로젝트가 없습니다.");
  if (normalizePath(project.path) !== normalizePath(plan.premiere_project.path)) {
    throw new Error(`열린 프로젝트가 계획의 해시 검증 기준본과 다릅니다.\n계획: ${plan.premiere_project.path}\n열림: ${project.path}`);
  }
  const sequence = await project.getActiveSequence();
  if (!sequence || sequence.name !== plan.premiere_project.sequence_name) {
    throw new Error(`활성 시퀀스가 계획과 다릅니다. 기대: ${plan.premiere_project.sequence_name}`);
  }

  const settings = await sequence.getSettings();
  const frameRate = await settings.getVideoFrameRate();
  if (!equalRate(frameRate.value, plan.fps)) {
    throw new Error(`시퀀스 FPS가 다릅니다. 기대: ${plan.fps.numerator}/${plan.fps.denominator}, 실제: ${frameRate.value}`);
  }
  const endTime = await sequence.getEndTime();
  const expectedDuration = typeof plan.premiere_project.sequence_duration_seconds === "number"
    ? plan.premiere_project.sequence_duration_seconds
    : Number.NaN;
  const oneFrame = Number(plan.fps.denominator) / Number(plan.fps.numerator);
  if (Number.isFinite(expectedDuration) && Math.abs(endTime.seconds - expectedDuration) > oneFrame + 0.001) {
    throw new Error(`시퀀스 길이가 계획과 다릅니다. 기대: ${expectedDuration.toFixed(3)}초, 실제: ${endTime.seconds.toFixed(3)}초`);
  }

  const captionTrackCount = await sequence.getCaptionTrackCount();
  const captionTrackName = plan.premiere_project.caption_track_name;
  const captionTracks = [];
  for (let index = 0; index < captionTrackCount; index += 1) {
    const track = await sequence.getCaptionTrack(index);
    captionTracks.push({ index, name: track.name, track });
  }
  const captionTrackResolution = resolveCaptionTrack(captionTracks, captionTrackName);
  const selectedCaptionTrack = captionTrackResolution.track.track;
  const captionItems = await selectedCaptionTrack.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
  const actualCueCount = Array.isArray(captionItems) ? captionItems.length : 0;
  if (actualCueCount <= 0) throw new Error("선택한 캡션 트랙에 항목이 없습니다.");
  const expectedCueCount = Number(plan.input?.cue_count);
  const captionCountMatchesSrt = Number.isFinite(expectedCueCount) && expectedCueCount > 0
    ? actualCueCount === expectedCueCount
    : null;
  const captionCountDelta = captionCountMatchesSrt === null ? null : actualCueCount - expectedCueCount;

  const editor = ppro.SequenceEditor.getEditor(sequence);
  const razorAvailable = typeof editor.createRazorTrackAction === "function";
  const razorAllTracksAvailable = typeof editor.createRazorAllTracksAction === "function";
  const trackEditApis = await inspectTrackEditApis(sequence, editor);
  return {
    project,
    sequence,
    frameRate,
    actualCueCount,
    expectedCueCount: Number.isFinite(expectedCueCount) ? expectedCueCount : null,
    captionCountMatchesSrt,
    captionCountDelta,
    captionTrackName: selectedCaptionTrack.name || "",
    captionTrackResolution: captionTrackResolution.matchedBy,
    editor,
    razorAvailable,
    razorAllTracksAvailable,
    trackEditApis,
  };
}

function uniqueName(folderEntries, stem, extension) {
  const used = new Set(folderEntries.map((entry) => String(entry.name).toLowerCase()));
  let name = `${stem}.${extension}`;
  let suffix = 1;
  while (used.has(name.toLowerCase())) {
    name = `${stem}_${String(suffix).padStart(2, "0")}.${extension}`;
    suffix += 1;
  }
  return name;
}

async function chooseOutput(plan, originalPath) {
  const outputFolder = await fs.getFolder();
  if (!outputFolder) return null;
  assertOutputFolder(outputFolder.nativePath, plan.suggested_output_folder);
  const entries = await outputFolder.getEntries();
  const stem = `${safeName(plan.project_name)}_REVIEW_${kstStamp()}`;
  const suggestedName = uniqueName(entries, stem, "prproj");
  const output = await fs.getFileForSaving(suggestedName, {
    initialLocation: outputFolder,
    types: ["prproj"],
  });
  if (!output) return null;
  const path = output.nativePath;
  assertOutputFile(path, plan.suggested_output_folder, originalPath, suggestedName);
  return { path, suggestedName };
}

function addTrackCheckbox(list, mediaType, index, name) {
  const row = document.createElement("label");
  row.className = "track-option";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.dataset.mediaType = mediaType;
  checkbox.dataset.trackIndex = String(index);
  const text = document.createElement("span");
  text.textContent = `${mediaType === "VIDEO" ? "V" : "A"}${index + 1}${name ? ` · ${name}` : ""}`;
  row.appendChild(checkbox);
  row.appendChild(text);
  list.appendChild(row);
  checkbox.addEventListener("change", updateSelectedTargets);
}

function updateSelectedTargets() {
  selectedTargets = [...videoTrackList.querySelectorAll("input:checked"), ...audioTrackList.querySelectorAll("input:checked")]
    .map((checkbox) => ({
      media_type: checkbox.dataset.mediaType,
      track_index: Number(checkbox.dataset.trackIndex),
    }));
  applyButton.disabled = Boolean(pending?.splitMode && !selectedTargets.some((target) => target.media_type === "VIDEO"));
}

async function renderTrackChoices(sequence) {
  videoTrackList.replaceChildren();
  audioTrackList.replaceChildren();
  const videoCount = await sequence.getVideoTrackCount();
  const audioCount = await sequence.getAudioTrackCount();
  for (let index = 0; index < videoCount; index += 1) {
    const track = await sequence.getVideoTrack(index);
    addTrackCheckbox(videoTrackList, "VIDEO", index, track.name);
  }
  for (let index = 0; index < audioCount; index += 1) {
    const track = await sequence.getAudioTrack(index);
    addTrackCheckbox(audioTrackList, "AUDIO", index, track.name);
  }
  updateSelectedTargets();
}

async function prepareReview() {
  prepareButton.disabled = true;
  applyButton.disabled = true;
  targetPanel.hidden = true;
  pending = null;
  selectedTargets = [];
  try {
    setStatus("VEA 작업 계획 JSON을 선택하세요.");
    const planFile = await fs.getFileForOpening({ types: ["json"] });
    if (!planFile) return;
    const plan = JSON.parse(await planFile.read());
    verifyPlanShape(plan);
    setStatus("Premiere 기준 프로젝트, 시퀀스, FPS, 길이, 캡션을 확인하고 있습니다.");
    const context = await getActiveContext(plan);
    const splitMode = chooseSplitMode(plan, context);
    pending = { planFile, plan, context, splitMode, preparedAt: Date.now() };
    if (splitMode) {
      await renderTrackChoices(context.sequence);
      targetPanel.hidden = false;
      applyButton.disabled = !selectedTargets.some((target) => target.media_type === "VIDEO");
      audioTrackLegend.textContent = "추가 오디오 트랙";
      targetNote.innerHTML = "<strong>Razor 분할 트랙을 지정하세요.</strong> 선택한 영상 트랙의 연결 오디오는 함께 분할됩니다. 추가 오디오 트랙은 직접 선택해야 합니다.";
      setStatus("Premiere Razor API를 사용합니다.");
    } else {
      const reason = plan.actions.implemented_mode === "review_markers_only"
        ? (plan.actions.reason || "계획이 마커 전용 경로를 요청했습니다.")
        : razorUnavailableReason(context);
      setStatus(`${reason}\n원본 프로젝트는 저장하지 않으며, 새 REVIEW 사본을 만듭니다.`);
      applyButton.disabled = false;
    }
  } catch (error) {
    pending = null;
    setStatus(`준비 중단: ${error?.stack || error}`, true);
  } finally {
    prepareButton.disabled = false;
  }
}

function tickTimeForFrame(frame, frameRate) {
  if (!Number.isInteger(frame) || frame < 0) throw new Error(`유효하지 않은 컷 프레임입니다: ${frame}`);
  return ppro.TickTime.createWithFrameAndFrameRate(frame, frameRate);
}

function validateCandidates(candidates) {
  return candidates.map((candidate) => {
    const start = Number(candidate.start_frame);
    const end = Number(candidate.end_frame);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) {
      throw new Error(`유효하지 않은 후보 프레임입니다: ${candidate.candidate_id}`);
    }
    return candidate;
  });
}

async function cloneSequence(project, sourceSequence, newName) {
  const before = await project.getSequences();
  const known = new Set(before.map(sequenceGuid));
  let applied = false;
  project.lockedAccess(() => {
    applied = project.executeTransaction((compound) => {
      compound.addAction(sourceSequence.createCloneAction());
    }, "VEA: Clone review sequence");
  });
  if (!applied) throw new Error("Premiere가 검토 시퀀스 복제를 완료하지 못했습니다.");
  const after = await project.getSequences();
  const clones = after.filter((sequence) => !known.has(sequenceGuid(sequence)));
  if (clones.length !== 1) throw new Error(`복제된 시퀀스를 하나로 확인하지 못했습니다. 새 시퀀스 수: ${clones.length}`);
  const reviewSequence = clones[0];
  const projectItem = await reviewSequence.getProjectItem();
  let renamed = false;
  project.lockedAccess(() => {
    renamed = project.executeTransaction((compound) => {
      compound.addAction(projectItem.createSetNameAction(newName));
    }, "VEA: Name review sequence");
  });
  if (!renamed) throw new Error("복제 시퀀스 이름 변경을 완료하지 못했습니다.");
  return reviewSequence;
}

function secondsToFrame(seconds, fps) {
  const value = Number(seconds) * Number(fps.numerator) / Number(fps.denominator);
  if (!Number.isFinite(value) || value < 0) throw new Error(`Premiere가 반환한 트랙 시간이 올바르지 않습니다: ${seconds}`);
  return Math.round(value);
}

async function snapshotTrack(track, mediaType, trackIndex, fps, includeSourcePoints = false) {
  const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
  const intervals = [];
  for (const item of items || []) {
    const start = await item.getStartTime();
    const end = await item.getEndTime();
    const startFrame = secondsToFrame(start.seconds, fps);
    const endFrame = secondsToFrame(end.seconds, fps);
    if (endFrame > startFrame) {
      const interval = { start_frame: startFrame, end_frame: endFrame };
      if (includeSourcePoints) {
        const inPoint = await item.getInPoint();
        const outPoint = await item.getOutPoint();
        interval.in_seconds = inPoint.seconds;
        interval.out_seconds = outPoint.seconds;
      }
      intervals.push(interval);
    }
  }
  const boundaryFrames = [...new Set(intervals.flatMap((interval) => [interval.start_frame, interval.end_frame]))].sort((a, b) => a - b);
  return { media_type: mediaType, track_index: trackIndex, name: track.name || "", intervals, boundary_frames: boundaryFrames };
}

async function snapshotAllTracks(sequence, fps, includeSourcePoints = false) {
  const tracks = [];
  const videoCount = await sequence.getVideoTrackCount();
  const audioCount = await sequence.getAudioTrackCount();
  for (let index = 0; index < videoCount; index += 1) {
    tracks.push(await snapshotTrack(await sequence.getVideoTrack(index), "VIDEO", index, fps, includeSourcePoints));
  }
  for (let index = 0; index < audioCount; index += 1) {
    tracks.push(await snapshotTrack(await sequence.getAudioTrack(index), "AUDIO", index, fps, includeSourcePoints));
  }
  return tracks;
}

function selectedTrackBoundaryKeys(snapshots, targets) {
  const selected = new Set(targets.map((target) => `${target.media_type}:${target.track_index}`));
  return snapshots
    .filter((track) => selected.has(`${track.media_type}:${track.track_index}`))
    .flatMap((track) => track.boundary_frames.map((frame) => `${track.media_type}:${track.track_index}:${frame}`));
}

async function applyRazorCuts(project, sequence, frameRate, fps, candidates, targets) {
  const editor = ppro.SequenceEditor.getEditor(sequence);
  if (typeof editor.createRazorTrackAction !== "function") {
    return { status: "not_supported", split_applied: false, action_count: 0, candidate_results: [], error: "Razor API is unavailable in this Premiere build." };
  }
  if (!targets.some((target) => target.media_type === "VIDEO")) {
    return { status: "no_video_track_selected", split_applied: false, action_count: 0, candidate_results: [] };
  }

  const validCandidates = validateCandidates(candidates);
  const snapshots = await snapshotAllTracks(sequence, fps);
  const plan = cutPlan.buildTargetedCutPlan(validCandidates, snapshots, targets);
  if (!plan.actions.length) {
    const trackBoundaryKeys = selectedTrackBoundaryKeys(snapshots, targets);
    const candidateResults = cutPlan.validateCompletedCandidates(plan, trackBoundaryKeys);
    return {
      status: candidateResults.every((item) => item.complete) ? "already_split" : "no_target_clips",
      split_applied: false,
      action_count: 0,
      candidate_results: candidateResults,
      target_tracks: targets,
      linked_audio_requested: true,
    };
  }

  let applied = false;
  project.lockedAccess(() => {
    applied = project.executeTransaction((compound) => {
      for (const actionInfo of plan.actions) {
        const mediaType = actionInfo.media_type === "VIDEO"
          ? ppro.Constants.MediaType.VIDEO
          : ppro.Constants.MediaType.AUDIO;
        compound.addAction(editor.createRazorTrackAction(
          mediaType,
          actionInfo.track_index,
          tickTimeForFrame(actionInfo.frame, frameRate),
          true,
          ppro.Constants.MediaType.VIDEO,
        ));
      }
    }, "VEA: Split subtitle-gap candidates");
  });
  if (!applied) {
    return {
      status: "transaction_failed",
      split_applied: false,
      action_count: plan.actions.length,
      candidate_results: [],
      target_tracks: targets,
      linked_audio_requested: true,
      error: "Premiere did not confirm the Razor transaction.",
    };
  }

  try {
    const after = await snapshotAllTracks(sequence, fps);
    const candidateResults = cutPlan.validateCompletedCandidates(plan, selectedTrackBoundaryKeys(after, targets));
    const completed = candidateResults.filter((item) => item.complete).length;
    const status = completed === candidateResults.length ? "complete" : completed > 0 ? "partial" : "applied_unverified";
    return {
      status,
      split_applied: candidateResults.length > 0 && completed === candidateResults.length,
      action_count: plan.actions.length,
      candidate_count: candidateResults.length,
      candidate_split_count: completed,
      candidate_results: candidateResults,
      target_tracks: targets,
      linked_audio_requested: true,
      verification_scope: "selected track clip boundaries; linked audio behavior still requires Premiere timeline inspection",
    };
  } catch (error) {
    return {
      status: "applied_unverified",
      split_applied: false,
      action_count: plan.actions.length,
      candidate_count: plan.candidate_outcomes.length,
      candidate_results: [],
      target_tracks: targets,
      linked_audio_requested: true,
      error: String(error?.stack || error),
    };
  }
}

async function addCandidateMarkers(project, sequence, frameRate, candidates) {
  const validCandidates = validateCandidates(candidates);
  const markers = await ppro.Markers.getMarkers(sequence);
  const beforeCount = markers.getMarkers().length;
  let applied = false;
  project.lockedAccess(() => {
    applied = project.executeTransaction((compound) => {
      for (const candidate of validCandidates) {
        const start = Number(candidate.start_frame);
        const end = Number(candidate.end_frame);
        const startTime = tickTimeForFrame(start, frameRate);
        const duration = tickTimeForFrame(end - start, frameRate);
        const markerName = `${candidate.candidate_id} | ${Number(candidate.duration_seconds).toFixed(2)}s`;
        const comments = JSON.stringify({
          candidate_id: candidate.candidate_id,
          sequence_start: candidate.sequence_start,
          sequence_end: candidate.sequence_end,
          start_frame: start,
          end_frame: end,
          previous_caption: candidate.previous_caption,
          next_caption: candidate.next_caption,
          auto_delete: false,
          note: "자막 사이 공백 검토 후보입니다. 실제 무음이 확정된 구간이 아닙니다.",
        });
        compound.addAction(markers.createAddMarkerAction(
          markerName,
          ppro.Marker.MARKER_TYPE_COMMENT,
          startTime,
          duration,
          comments,
        ));
      }
    }, "VEA: Add silence review markers");
  });
  if (!applied) throw new Error("Premiere가 검토 마커를 추가하지 못했습니다.");
  const afterCount = markers.getMarkers().length;
  if (afterCount < beforeCount + validCandidates.length) {
    throw new Error(`마커 수를 확인하지 못했습니다. 기대 증가량 ${validCandidates.length}, 실제 증가량 ${afterCount - beforeCount}`);
  }
  return validCandidates.length;
}

async function writeResult(planFile, plan, result) {
  const resultFolder = await fs.getFolder();
  if (!resultFolder) throw new Error("결과 JSON 저장 폴더 선택이 취소되었습니다.");
  assertSiblingFolder(resultFolder.nativePath, planFile.nativePath);
  const entries = await resultFolder.getEntries();
  const name = uniqueName(entries, `silence_split_premiere_result_${kstStamp()}`, "json");
  const resultFile = await resultFolder.createFile(name);
  assertSiblingFile(resultFile.nativePath, planFile.nativePath, name);
  const payload = {
    schema_version: 1,
    status: "saved_pending_reopen_review",
    project_id: plan.project_id,
    source_project_path: plan.premiere_project.path,
    review_project_path: result.review_project_path,
    review_sequence_name: result.review_sequence_name,
    candidate_count: plan.analysis.candidates.length,
    split_candidate_count: (plan.analysis.candidates || []).filter((item) => item.candidate_type === "inter_caption").length,
    srt_cue_count: result.srt_cue_count,
    premiere_caption_item_count: result.premiere_caption_item_count,
    caption_count_matches_srt: result.caption_count_matches_srt,
    caption_count_delta: result.caption_count_delta,
    caption_track_name: result.caption_track_name,
    caption_track_resolution: result.caption_track_resolution,
    marker_count: result.marker_count,
    actual_mode: result.actual_mode,
    split_method: result.split_method || null,
    split_api_available: result.split_api_available,
    split_all_tracks_api_available: result.split_all_tracks_api_available,
    track_edit_api_availability: result.track_edit_api_availability,
    split_status: result.split_status,
    split_applied: result.split_applied,
    cut_action_count: result.cut_action_count,
    candidate_split_count: result.candidate_split_count,
    target_tracks: result.target_tracks,
    candidate_results: result.candidate_results,
    split_error: result.split_error,
    marker_error: result.marker_error,
    auto_delete: false,
    project_openable_check: result.project_openable_check,
    saved_at: new Date().toISOString(),
  };
  await resultFile.write(JSON.stringify(payload, null, 2));
  return resultFile.nativePath;
}

async function applyReview() {
  if (!pending) return;
  prepareButton.disabled = true;
  applyButton.disabled = true;
  let savedCopyPath = null;
  try {
    const { planFile, plan, splitMode: preparedSplitMode } = pending;
    setStatus("기준본과 시퀀스를 다시 확인합니다.");
    const context = await getActiveContext(plan);
    const splitMode = chooseSplitMode(plan, context);
    if (splitMode !== preparedSplitMode) {
      throw new Error("준비 단계 이후 Premiere 분할 API 상태가 바뀌었습니다. 계획을 다시 불러오세요.");
    }
    if (splitMode && !selectedTargets.some((target) => target.media_type === "VIDEO")) {
      throw new Error("분할할 영상 트랙을 하나 이상 선택해야 합니다.");
    }
    setStatus("새 REVIEW 사본의 저장 위치를 준비합니다. 기준 .prproj는 덮어쓰지 않습니다.");
    const outputChoice = await chooseOutput(plan, context.project.path);
    if (!outputChoice) return;

    const copied = await context.project.saveAs(outputChoice.path);
    if (!copied || normalizePath(context.project.path) !== normalizePath(outputChoice.path)) {
      throw new Error("Premiere가 Save As로 만든 새 REVIEW 사본을 확인하지 못했습니다.");
    }
    savedCopyPath = outputChoice.path;

    const reviewName = `SILENCE_SPLIT_REVIEW_${kstStamp()}`;
    const sourceGuid = sequenceGuid(context.sequence);
    const project = context.project;
    const sourceSequence = await findSequenceByGuid(project, sourceGuid);
    if (!sourceSequence) throw new Error("Save As 후 기준 시퀀스를 다시 가져오지 못했습니다.");
    const reviewSequence = await cloneSequence(project, sourceSequence, reviewName);

    let splitResult = {
      status: splitMode ? "pending" : "not_supported",
      split_applied: false,
      action_count: 0,
      candidate_split_count: 0,
      candidate_results: [],
      target_tracks: splitMode ? selectedTargets : [],
      error: splitMode
        ? undefined
        : plan.actions.implemented_mode === "review_markers_only"
          ? (plan.actions.reason || "계획이 후보 마커만 요청했습니다.")
          : razorUnavailableReason(context),
    };
    if (splitMode) {
      setStatus("복제 시퀀스에 선택한 트랙만 Razor 분할하고 결과 경계를 확인합니다.");
      try {
        splitResult = await applyRazorCuts(project, reviewSequence, context.frameRate, plan.fps, plan.analysis.candidates, selectedTargets);
      } catch (error) {
        splitResult = {
          status: "failed",
          split_applied: false,
          action_count: 0,
          candidate_split_count: 0,
          candidate_results: [],
          target_tracks: selectedTargets,
          method: splitMode,
          error: String(error?.stack || error),
        };
      }
    }

    let markerCount = 0;
    let markerError;
    try {
      markerCount = await addCandidateMarkers(project, reviewSequence, context.frameRate, plan.analysis.candidates);
    } catch (error) {
      markerError = String(error?.stack || error);
    }
    const saved = await project.save();
    if (!saved) throw new Error("Premiere가 검토 프로젝트 저장을 확인하지 못했습니다.");
    const openable = typeof ppro.Project.isProject === "function" ? ppro.Project.isProject(outputChoice.path) : null;
    if (openable === false) throw new Error("Premiere 프로젝트 검사에서 새 REVIEW 사본을 열 수 없다고 반환했습니다.");
    const resultPath = await writeResult(planFile, plan, {
      review_project_path: outputChoice.path,
      review_sequence_name: reviewName,
      srt_cue_count: context.expectedCueCount,
      premiere_caption_item_count: context.actualCueCount,
      caption_count_matches_srt: context.captionCountMatchesSrt,
      caption_count_delta: context.captionCountDelta,
      caption_track_name: context.captionTrackName,
      caption_track_resolution: context.captionTrackResolution,
      marker_count: markerCount,
      actual_mode: splitMode ? "split_with_markers" : "review_markers_only",
      split_method: splitResult.method || splitMode,
      split_api_available: context.razorAvailable,
      split_all_tracks_api_available: context.razorAllTracksAvailable,
      track_edit_api_availability: context.trackEditApis,
      split_status: splitResult.status,
      split_applied: splitResult.split_applied,
      cut_action_count: splitResult.action_count,
      candidate_split_count: splitResult.candidate_split_count || 0,
      target_tracks: splitResult.target_tracks || [],
      candidate_results: splitResult.candidate_results || [],
      split_error: splitResult.error,
      marker_error: markerError,
      project_openable_check: openable,
    });

    const splitLine = splitMode
      ? `Razor 분할 결과: ${splitResult.candidate_split_count || 0}/${splitResult.candidate_count || 0} 후보 완결 (${splitResult.status})`
      : `분할 0개 (${splitResult.error || "계획이 분할을 요청하지 않았습니다."}; 마커 전용 사본)`;
    setStatus([
      "검토용 Premiere 사본을 저장했습니다.",
      `프로젝트: ${outputChoice.path}`,
      `시퀀스: ${reviewName}`,
      `Premiere 캡션 항목: ${context.actualCueCount}개 / SRT: ${context.expectedCueCount ?? "미기록"}개`,
      `캡션 트랙 매칭: ${context.captionTrackName || "이름 없음"} (${context.captionTrackResolution})`,
      context.captionCountMatchesSrt === false
        ? `검토 필요: 캡션 항목 수 차이 ${context.captionCountDelta}개. 마커 시각은 SRT 기준이며 후보를 사람 검토 없이 삭제하지 마세요.`
        : "",
      `후보 마커: ${markerCount}/${plan.analysis.candidates.length}개`,
      splitLine,
      "자동 삭제: 안 함",
      `결과 JSON: ${resultPath}`,
      markerError ? `마커 경고: ${markerError}` : "",
      splitResult.error ? `분할 경고: ${splitResult.error}` : "",
      "다음 단계: Premiere에서 새 사본을 다시 열어 확인한 뒤 vea project register로 등록하세요.",
    ].filter(Boolean).join("\n"));
    pending = null;
  } catch (error) {
    setStatus(savedCopyPath
      ? `검토 복사본 생성이 완전히 끝나지 않았습니다. 재실행 전 확인하세요.\n저장된 사본: ${savedCopyPath}\n${error?.stack || error}`
      : `기준본을 수정하지 않았습니다.\n${error?.stack || error}`, true);
  } finally {
    prepareButton.disabled = false;
    applyButton.disabled = !pending;
  }
}

prepareButton.addEventListener("click", prepareReview);
applyButton.addEventListener("click", applyReview);
