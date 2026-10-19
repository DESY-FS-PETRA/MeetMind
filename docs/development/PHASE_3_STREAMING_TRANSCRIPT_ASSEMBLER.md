# Phase 3 — Streaming Transcript Assembler

## Problem fixed

Overlapping 8-second audio chunks protect boundary words, but Whisper can return a slightly different hypothesis for the repeated 2-second region. Appending every result produced duplicates and contradictory tails, for example:

- `restores health and zest` followed by `restores health at zest`
- `A zest fulfills...` followed by `A zestful food is the hot cross bun.`

## New pipeline

1. Whisper returns the raw text for every overlapping audio chunk.
2. `StreamingTranscriptAssembler` keeps a mutable tail of the transcript.
3. The next chunk is aligned against that tail.
4. Older wording is preserved for small overlap substitutions.
5. An incomplete old tail is replaced by the newer continuation.
6. Backend broadcasts a `replace` event with a stable `segment_id`.
7. Frontend updates the existing transcript entry instead of appending a duplicate.
8. Storage upserts one cleaned rolling transcript, which is used for the summary.

## WebSocket transcript event

```json
{
  "id": "event-uuid",
  "meeting_id": "meeting-uuid",
  "segment_id": "meeting-uuid:rolling-transcript",
  "revision": 4,
  "operation": "replace",
  "is_final": false,
  "text": "The corrected rolling transcript...",
  "time": "2026-07-21T...Z"
}
```

## Main files

- `backend/app/transcription/streaming_assembler.py`
- `backend/app/transcription/worker.py`
- `backend/app/events/events.py`
- `backend/app/engine/meeting_engine.py`
- `backend/app/storage/meeting_storage.py`
- `frontend/app.js`
- `frontend/style.css`

## Tests

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected: 7 tests pass.

Accuracy test:

```powershell
python test_transcription_accuracy.py "D:\meeting-ai-assistant\test\test2.wav" --expected "The stale smell of old beer lingers. It takes heat to bring out the odor. A cold dip restores health and zest. A salt pickle tastes fine with ham. Tacos al pastor are my favorite. A zestful food is the hot cross bun."
```

The test tool now displays the complete assembled hypothesis after every chunk.
