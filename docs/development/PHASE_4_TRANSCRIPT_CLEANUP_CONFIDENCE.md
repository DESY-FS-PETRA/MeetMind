# Phase 4 — Final Transcript Cleanup and Word Review Scores

## Goal

Improve the usability of the final transcript without allowing an LLM or a
post-processing rule to silently replace recognized words.

## What changed

### 1. Faster-Whisper word-level metadata

`WhisperService` now enables `word_timestamps=True` and returns, for each word:

- displayed text
- start and end time within the processed audio chunk
- Faster-Whisper word probability/score

The score is useful as a review signal, but it is not treated as a calibrated
certainty guarantee.

### 2. Configurable review threshold

Words below the configured threshold are marked with `needs_review=true`.

```env
WHISPER_LOW_CONFIDENCE_THRESHOLD=0.65
```

Lower the value to highlight fewer words; increase it to review more words.

### 3. Pause-based punctuation support

A sufficiently long word-level pause can close a sentence. This is conservative
and does not replace lexical content.

```env
WHISPER_PUNCTUATION_PAUSE_SECONDS=0.65
```

### 4. Conservative final cleanup

The final cleanup only:

- normalizes whitespace
- removes provisional chunk-edge punctuation such as `dip. restores`
- capitalizes sentence starts
- ensures terminal punctuation

It does not use an LLM and does not replace recognized words.

### 5. Confidence-aware rolling assembler

The rolling transcript now keeps word scores while merging overlapping chunks.
For the same word heard in two chunks, the stronger score is retained. For a
boundary disagreement, the older, more contextual overlap hypothesis is kept
and its score remains available for review.

### 6. Frontend review highlighting

The UI now displays:

- average word score for the rolling transcript
- number of words that need review
- yellow highlighting for low-scoring words
- a tooltip with the individual word score

### 7. Summary input

Meeting summaries are generated only from the finalized transcript when one is
available. Temporary live revisions are not sent to the summary pipeline.

## Main new files

```text
backend/app/transcription/result.py
backend/app/transcription/transcript_cleaner.py
backend/tests/test_transcript_confidence.py
backend/tests/test_transcript_storage.py
```

## Updated files

```text
backend/app/transcription/whisper_service.py
backend/app/transcription/streaming_assembler.py
backend/app/transcription/worker.py
backend/app/events/events.py
backend/app/engine/meeting_engine.py
backend/app/storage/meeting_storage.py
backend/app/services/meeting_summary_service.py
backend/test_transcription_accuracy.py
backend/.env.example
frontend/app.js
frontend/index.html
frontend/style.css
```

## Run tests

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected:

```text
Ran 11 tests
OK
```

## Accuracy test

```powershell
python test_transcription_accuracy.py "D:\meeting-ai-assistant\test\test2.wav" --expected "The stale smell of old beer lingers. It takes heat to bring out the odor. A cold dip restores health and zest. A salt pickle tastes fine with ham. Tacos al pastor are my favorite. A zestful food is the hot cross bun."
```

The diagnostic output now also shows average word score and words that need
review.

## Browser version check

After replacing the frontend, reload with `Ctrl + F5`. The browser console
should show:

```text
APP.JS 2026-07-21.5 LOADED
```

## Important limitation

A low word score is a review hint, not proof that the word is wrong. A wrong
word can occasionally receive a high score, and a correct word can receive a
low score. The system highlights uncertainty but does not silently guess a
replacement.
