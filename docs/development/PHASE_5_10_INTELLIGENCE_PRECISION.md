# Phase 5.10 — Scientific Intelligence Precision

This patch is built directly on Phase 5.9 and targets the remaining issues found in the real Shahin imaging-meeting regression output.

## 1. Multi-turn semantic Q&A resolution

Discussion Q&A now uses final transcript segment boundaries instead of relying only on punctuation in one concatenated transcript string. This prevents adjacent speaker turns from being merged into malformed questions.

The resolver now:

- ignores meeting-control/meta questions such as `What's your question?`, `Are there any questions?`, `Who's next up?`, and screen-sharing questions;
- ignores declarative confirmation prompts ending in `...right?` when they are not a substantive question;
- follows a question across up to ten later discussion units to find a grounded answer;
- recognizes rephrased/follow-up versions of the same scientific question;
- keeps an immediate `I don't know` / `not sure` response unresolved;
- removes answered questions from Open Questions.

Regression behavior for the real meeting:

- `What is the problem with the numerical approach when you have multiple layers?` -> Answered.
- Answer evidence includes that the approach breaks down for multiple layers / two views because the information is insufficient.
- `How does the distance between layers compare to the microchip?` -> Unresolved.
- `What's your question?` -> removed.

## 2. Numeric Fact Validator

A new `app/ai/numeric_fact_validator.py` validates the semantic role of quantities before summaries are saved.

It currently performs conservative role-aware validation for sample counts and normalizes common ASR number forms such as:

- `five thousand`
- `5k`
- `4 ,000`
- `4,000`

The key regression is:

- 5,000 synthetic samples were generated.
- 4,000 samples were used for training.
- 500 samples were used for validation and testing.

The report is no longer allowed to convert `5,000 generated samples` into `5,000 training samples`.

The validator is applied to:

- Executive Summary
- Key Points
- Slide-by-Slide Summary

## 3. More compact slide summaries

Slide summaries are now capped and cleaned when a small local LLM copies a long transcript passage instead of summarizing it.

The fallback:

- ranks slide-relevant scientific/numeric statements;
- removes common presentation filler;
- limits the result to about 65 words / 420 characters;
- preserves grounded numbers and technical facts;
- removes post-talk chatter such as `Who's next up?`.

## 4. Scientific Review Queue precision

The Scientific Review Queue no longer promotes ordinary low-confidence words such as:

- `has`
- `vice-versa`
- generic discourse markers

It also scans for suspicious acronym+digit forms even when Whisper confidence is high. Example:

`Possible terminology mismatch: "CNN2" -> "CNN"`

A genuinely uncertain scientific token such as `D-layer` remains reviewable.

## 5. Prompt hardening

The structured LLM prompt now explicitly requires:

- multi-turn Q&A reasoning;
- removal of meta/confirmation questions;
- compact 1-3 sentence slide summaries;
- numeric-role grounding (generated vs training vs validation/testing);
- scientific-only review candidates.

## Compatibility

- Based directly on Phase 5.9.
- Live microphone/WebSocket processing is unchanged.
- Fast Recorded Meeting remains batched.
- No new pip dependency is required.
- `.env`, SQLite database files, and uploaded presentations are not included in the patch.

## Installation

Stop backend and frontend. Extract the patch into:

`D:\meeting-ai-assistant`

and allow replacement.

Then run:

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m uvicorn app.main:app --reload
```

Frontend:

```powershell
cd D:\meeting-ai-assistant\frontend
python -m http.server 3000
```

Hard refresh with `Ctrl + F5`.

Expected browser console version:

`APP.JS 2026-08-10.16 LOADED`

## Tests

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected:

```text
Ran 74 tests
OK
```

The mock Ollama offline/404 lines printed by failure-path tests are intentional.
