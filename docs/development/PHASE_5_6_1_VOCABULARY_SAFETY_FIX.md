# Phase 5.6.1 — Vocabulary Safety and Hallucination Guard

## Problem

Phase 5.6 supplied up to 120 scientific hotwords (240 words) to every 8-second Whisper chunk. On ordinary meeting speech, this could overpower acoustic evidence and create a feedback loop:

1. Whisper hallucinated an active scientific term.
2. Topic detection treated that hallucination as evidence.
3. More terms from that category were activated.
4. Whisper repeated the prompted term in later chunks.

Observed examples included repeated `X-ray beam induced current` and very long `ZZZZ...` strings.

## Fixes

- Hard cap: 24 active hotwords / 48 total hotword words.
- Curated 18-term always-on list instead of the first 65 core terms.
- Maximum two detected categories and eight retrieved terms per category.
- Topic activation requires at least 160 observed characters, score >= 6, and two distinct evidence signals.
- Only raw sanitized Whisper chunks update topic detection; corrected/assembled text no longer reinforces its own vocabulary.
- `initial_prompt` is disabled by default. It can be explicitly enabled with `VOCABULARY_USE_INITIAL_PROMPT=true`.
- Added repetition controls to Faster-Whisper:
  - repetition penalty 1.15
  - no-repeat 3-gram
  - compression-ratio threshold 2.2
  - hallucination-silence threshold 1.0
- Added `TranscriptHallucinationGuard`:
  - removes long one-character runs such as `ZZZZ...`
  - removes a prompted multi-word hotword repeated three or more times
  - collapses generic repeated phrases to one copy
- Added A/B testing through `test_transcription_accuracy.py --disable-vocabulary`.

## Safe environment settings

```env
WHISPER_REPETITION_PENALTY=1.15
WHISPER_NO_REPEAT_NGRAM_SIZE=3
WHISPER_COMPRESSION_RATIO_THRESHOLD=2.2
WHISPER_HALLUCINATION_SILENCE_THRESHOLD=1.0

VOCABULARY_MAX_HOTWORDS=24
VOCABULARY_MAX_HOTWORD_WORDS=48
VOCABULARY_CORE_TERM_LIMIT=18
VOCABULARY_MAX_CATEGORIES=2
VOCABULARY_MAX_TERMS_PER_CATEGORY=8
VOCABULARY_MIN_TOPIC_SCORE=6.0
VOCABULARY_MIN_TOPIC_EVIDENCE=2
VOCABULARY_TOPIC_WARMUP_CHARACTERS=160
VOCABULARY_MAX_OBSERVED_CHARACTERS=4000
VOCABULARY_USE_INITIAL_PROMPT=false
```

The code also applies hard safety caps, so old Phase 5.6 `.env` values such as 120 hotwords cannot reactivate the unsafe behavior.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Expected:

```text
Ran 37 tests
OK
```

A/B test on a real recording:

```powershell
python test_transcription_accuracy.py "D:\path\meeting.ogg"
python test_transcription_accuracy.py "D:\path\meeting.ogg" --disable-vocabulary
```
