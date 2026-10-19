# Phase 5.8.1 — History UI Fix, Processing Progress, and Automatic Dates

## What changed

### 1. History detail blank-space bug fixed
The large empty block above a selected meeting was caused by CSS precedence:
`.history-detail-empty` was declared after `.is-hidden`, so its `display: grid` overrode `display: none`.

The fix adds:

```css
.history-detail-empty.is-hidden { display: none; }
```

The meeting detail now begins immediately with the title, actions, metadata, transcript, and report.

### 2. Processing progress indicator
A reusable progress component now appears during:
- Fast recorded meeting uploads
- Fast recorded meeting GPU transcription/report generation
- Live meeting Stop & Summarize finalization

For fast recorded meetings, upload percentage is real browser upload progress. Once upload is complete, the bar switches to an indeterminate animation while Whisper and Ollama process the file, because the current batched Whisper API does not expose granular frame-by-frame progress callbacks.

### 3. Automatic report dates surfaced in History
Dates were already persisted automatically by the backend. The UI now makes them explicit:
- Every history card shows meeting date/time and duration in dedicated chips.
- Meeting detail shows `Meeting date`.
- Meeting detail shows `Report generated` from `summary.generated_at`.

No database migration is required.

## Frontend version

`APP.JS 2026-08-10.13 LOADED`

## Installation
Extract the patch into the project root and replace files. No `.env` or database files are included.

After restart, hard refresh the browser with Ctrl+F5.
