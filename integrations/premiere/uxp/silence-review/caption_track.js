"use strict";

function resolveCaptionTrack(tracks, expectedName) {
  const named = tracks.filter((track) => expectedName && track.name === expectedName);
  if (named.length === 1) return { track: named[0], matchedBy: "name" };
  if (named.length > 1) {
    throw new Error(`캡션 트랙 이름이 중복되어 모호합니다: ${expectedName}`);
  }
  if (tracks.length === 1) return { track: tracks[0], matchedBy: "only_track" };

  const available = tracks.map((track) => track.name || "(이름 없음)").join(", ") || "없음";
  throw new Error(`계획된 캡션 트랙을 안전하게 확인할 수 없습니다: 기대 ${expectedName || "미지정"}, 확인 ${available}`);
}

module.exports = { resolveCaptionTrack };
