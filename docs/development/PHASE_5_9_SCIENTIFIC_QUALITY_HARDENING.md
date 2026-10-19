# Phase 5.9 — Scientific Meeting Quality Hardening

This release is based on the real Imaging Meeting test using:

- `Imaging_Meeting_Stereo_Image_Generation.pptx`
- an 18-minute recorded meeting
- Fast Recorded Meeting mode

It fixes the quality issues found in that real-world run while preserving the live microphone pipeline.

## What changed

### 1. Slide-grounded scientific transcript validation

Recorded meetings now run a conservative validation pass after Whisper and before the transcript is summarized. Corrections require presentation evidence or an explicit high-confidence domain rule.

Examples covered by the regression suite:

- `X-ray serial experiments` → `X-ray stereo experiment`
- `sterile experiment` → `stereo experiment`
- `eliminate a sample` → `illuminate a sample`
- `sensitively generate` → `synthetically generate`
- `UTSU segmentation` → `Otsu segmentation` (kept in the Scientific Review Queue because the slide itself does not spell out Otsu)
- `connect components` → `connected components`
- `SINA`, `CINA`, `Dina` → `Sina` when the deck confirms that name

Slide-confirmed replacements retain original Whisper confidence metadata but are marked `context_confirmed`, so they do not create unnecessary review warnings.

### 2. Global offline slide alignment

Fast Recorded Meeting no longer relies on local live-style slide decisions. After the complete transcript is available, a Viterbi-style monotonic aligner uses the whole recording and ordered deck to calculate one globally consistent slide timeline.

The aligner:

- keeps Zoom/screen-sharing/setup chatter outside the presentation summaries;
- uses title, body text, slide keywords, numbers, and ordered deck position;
- supports sparse/image-heavy scientific slides;
- may skip appendix slides that were not actually discussed;
- uses strong closing cues such as `thanks for your attention` for the Q&A slide;
- does not force every slide to appear in the report.

This is intentionally different from live mode, where future transcript context is unavailable.

### 3. Better slide summaries

Slide summaries are generated from the globally aligned sections. Setup chatter remains visible in the full transcript/history but does not contaminate the scientific slide summaries or executive summary.

### 4. Action-item false-positive protection

The action-item pipeline now validates model output against the transcript and rejects presentation-control/meta speech.

Rejected examples include:

- `Normally should be fine.`
- `I will finish it, just one more thing to say.`
- screen-sharing instructions
- thank-you/closing language

Adverbs such as `Normally`, `Probably`, and `Maybe` cannot be treated as owners. A retained action item must have task evidence plus a plausible assignment/future commitment in the transcript.

### 5. Discussion Q&A: answered vs unresolved

A new `discussion_questions` structure stores scientific/technical questions as either:

- `answered` — with the detected response, or
- `unresolved` — when the speaker says they do not know, defers the issue, or no grounded answer follows.

`Open Questions` now contains unresolved questions only. Questions answered later in the meeting are removed from that list.

The UI has a new **Discussion Q&A** section showing Answered/Unresolved badges.

### 6. Canonical technical terms

Technical terms are normalized before they are saved in the report. Common erroneous ASR forms are no longer allowed to become long-term knowledge-base terms.

Examples:

- `X-ray serial experiments` → `X-ray stereo experiment`
- `UTSU segmentation` → `Otsu segmentation`
- `connect components` → `connected components`
- `astra toolbox` → `ASTRA Toolbox`

Canonical scientific terms are included only when they are actually supported by the corrected transcript/presentation context.

### 7. Scientific Review Queue

The former `Transcription Uncertainties` section is now **Scientific Review Queue**.

It no longer lists generic low-confidence function words or ordinary statements such as `because`, `today`, or `I don't know, to be honest`.

It focuses on terms that can change scientific meaning. A domain correction not directly confirmed by the slide may appear as:

`Review correction: "UTSU segmentation" → "Otsu segmentation"`

### 8. Database-compatible Q&A storage

`meeting_summary_extras` now stores `discussion_questions`. Existing SQLite databases are upgraded automatically and non-destructively at startup by adding the missing nullable JSON column. Existing meetings are preserved.

## Processing order for Fast Recorded Meeting

```text
Complete audio/video upload
        ↓
Batched Faster-Whisper
        ↓
Hallucination + transcript cleanup
        ↓
Slide-grounded scientific validation
        ↓
Persist corrected final transcript
        ↓
Global monotonic slide alignment
        ↓
Slide-specific transcript sections
        ↓
Ollama structured intelligence
        ↓
Action validation + Q&A resolution
        ↓
Canonical technical terms
        ↓
Scientific Review Queue
        ↓
Saved report + Meeting History
```

## Safety / compatibility

- Live microphone/WebSocket behavior remains intact.
- Fast Recorded Meeting remains batched and faster than realtime.
- No new Python dependency is required.
- `.env`, SQLite database files, and uploaded presentation data are not part of the patch ZIP.
- Existing history data remains intact.

## Installation

1. Stop backend/frontend.
2. Extract the patch into `D:\meeting-ai-assistant` and allow file replacement.
3. Start the backend:

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m uvicorn app.main:app --reload
```

4. Start the frontend:

```powershell
cd D:\meeting-ai-assistant\frontend
python -m http.server 3000
```

5. Hard refresh the browser (`Ctrl + F5`).

Expected browser console version:

```text
APP.JS 2026-08-10.15 LOADED
```

## Tests

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected result:

```text
Ran 65 tests
OK
```

The Ollama offline/404 messages printed by mock failure tests are intentional; the final `OK` is the test result.
