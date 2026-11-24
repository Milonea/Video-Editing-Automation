# VEA Silence Review UXP panel

The panel validates the active project's exact path, sequence, FPS, duration, and caption track before saving a timestamped `.prproj` copy in `08_PREMIERE`. It clones the target sequence and adds one comment marker for each candidate. When Premiere exposes the Razor action, it also splits only the explicitly selected tracks in that copied sequence. It never edits the source project on disk and never deletes timeline media.

## Premiere API support

Adobe's current [Premiere UXP sample](https://github.com/AdobeDocs/uxp-premiere-pro-samples/blob/main/sample-panels/premiere-api/src/sequenceEditor.ts) demonstrates `SequenceEditor.createRazorTrackAction` and `createRazorAllTracksAction`, marking the razor workflow as available since Premiere 27.1. This panel uses the per-track method so it can honor explicit track selection; the all-tracks method is not an equivalent fallback. The panel checks the per-track method at runtime and records all-tracks availability separately. If the per-track method is missing, the approved fallback creates the review sequence and markers only. The [public SequenceEditor reference](https://developer.adobe.com/premiere-pro/uxp/ppro_reference/classes/sequenceeditor) currently does not list the Razor methods.

The public `SequenceEditor` reference and [Premiere TypeScript declarations](https://github.com/adobe/premierepro-types/blob/main/src/premierepro.d.ts) do not list another time-based split action. [`SequenceUtils.performSceneEditDetectionOnSelection()`](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequenceutils/) performs scene-cut detection on a selection and takes no requested cut time, so it cannot replace Razor for subtitle-gap boundaries. `SequenceOperation.APPLYCUT` is an enum value, not a callable time-based split method. The implementation does not treat either as an alternative.

The API call must be created and executed while holding project access. For one video track, the core pattern is:

```js
const editor = ppro.SequenceEditor.getEditor(sequence);
project.lockedAccess(() => {
  project.executeTransaction((compound) => {
    compound.addAction(editor.createRazorTrackAction(
      ppro.Constants.MediaType.VIDEO,
      trackIndex,
      cutTime,
      true,
      ppro.Constants.MediaType.VIDEO,
    ));
  }, "VEA: Split review track");
});
```

The method signature being present in Adobe's sample does not guarantee that every 27.1 Beta build exposes it. In the Windows Premiere Pro Beta 27.1.0.52 runtime checked on 2026-11-20, both Razor methods were `undefined`; `createCloneTrackItemAction` and the sampled video/audio start, end, in-point, and out-point actions were functions. Adobe's public `SequenceEditor` reference documents clone-track actions but not Razor methods. Treat the panel's runtime feature check as authoritative and do not infer that a split occurred from markers alone.

A disposable 4-second, 24 fps synthetic REVIEW copy was used to test clone/trim behavior in that runtime. Cloning a video clip at a +2-second offset with overwrite yielded V1 items at 0–2 and 2–6 seconds, but did not clone linked audio; cloning the audio item separately yielded aligned A1 items at 0–2 and 2–6 seconds. A compound transaction that set source In/Out and sequence Start/End to 2/4 seconds left both cloned items at 4–4 seconds with zero duration. A later panel integration attempt with repeated cuts on pre-split synthetic V1/A1 tracks stopped after the first cut because the clone operation had removed the expected clip at the next boundary. Timeline boundary checks still reported the candidate complete because the clone's new edge coincided with that cut. This showed that boundary-only verification could falsely report a complete split and that clone/trim can overwrite adjacent clip ranges. The trial copy was synthetic; clone/trim is not used as an automatic fallback. Until a Razor API is available and verified, this panel creates a REVIEW copy with candidate markers only.

When Razor is available, the panel requires explicit video-track selection. A selected video track requests cuts on linked items, including linked audio. Additional audio tracks are unselected by default and must be explicitly selected. The panel skips gaps and existing boundaries, keeps the cuts on video-frame boundaries, and re-reads selected-track clip boundaries after the transaction. Premiere reopening and visual confirmation are still required to verify linked audio, captions, effects, and project behavior.

## Run

1. Enable Developer Mode in Premiere Pro's Preferences > Plugins and restart Premiere.
2. Add this folder's `manifest.json` in Adobe UXP Developer Tool and load the panel.
3. Open the exact `.prproj` path recorded in `10_REPORTS/silence_split_plan.json` and activate the named sequence.
4. Open the `VEA Silence Review` panel and choose the VEA plan JSON.
5. If Razor is available, choose the video tracks to split and only the additional audio tracks that should follow those cuts. Click **새 REVIEW 사본 저장 및 처리** only after checking the displayed track list.
6. Save the new copy using the generated `*_REVIEW_YYYYMMDD_HHmmss_KST.prproj` name inside `08_PREMIERE`.
7. Reopen the copy in Premiere and visually inspect it before registering it:

   ```powershell
   vea project register PROJECT --file 08_PREMIERE\Project_REVIEW_YYYYMMDD_HHmmss_KST.prproj --stage REVIEW --source-version 08_PREMIERE\source.prproj --set-current
   vea project verify PROJECT
   ```

8. `vea project register` links a matching result JSON into the plan and refreshes the Codex handoff report. Hash integrity is separate from Premiere reopen and timeline review.

If any plan check fails, the panel stops before Save As. If a later step fails, it reports the saved copy path for manual inspection; the source project remains untouched.
