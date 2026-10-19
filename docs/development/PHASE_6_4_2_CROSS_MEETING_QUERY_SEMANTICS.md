# MeetMind Phase 6.4.2 — Cross-Meeting Query Semantics & Citation Coverage

This patch hardens cross-meeting questions after the Phase 6.4.1 real two-meeting test.

## Fixed

- **UNION vs INTERSECTION semantics**
  - `methods/topics across meetings` means the union of relevant items from the meetings.
  - `shared/common/both/overlap` means the intersection.
  - `compare ...` is treated as a comparison, not an overlap-only search.
  - `which meetings discussed ...` remains topic-membership retrieval.

- **Named-meeting resolver**
  - Natural references such as `Shahin's meeting` resolve to `shahin 5`.
  - `holography demo meeting` resolves to `[DEMO] Near-Field Holography Reconstruction`.
  - Resolved named comparisons are scoped to the intended meetings before retrieval.
  - Leading command words such as `Compare` and `Summarize` are not parsed as person/entity names.

- **Per-meeting citation coverage**
  - UNION and COMPARISON answers must expose at least one citation from every relevant meeting.
  - If a small local model mentions multiple meetings but cites only one, MeetMind adds a compact grounded evidence line for any missing meeting.
  - Correct existing citation bindings are preserved; wrong cross-meeting bindings are still repaired.

- **Grounded comparison fallback**
  - If Ollama incorrectly returns a no-evidence answer for a named comparison, MeetMind builds a safe comparison from each meeting's own evidence instead of failing.
  - Ambiguous comparison prose such as `another meeting` / `the other meeting` triggers the grounded structured fallback.
  - Executive Summary is preferred as the representative source for overview/comparison synthesis.

- **Cross-meeting method union fallback**
  - If a UNION question is mistakenly answered as `no common/shared method`, that intersection-style answer is discarded.
  - MeetMind falls back to representative evidence from each meeting, so methods present in different meetings are not lost.

- **Unresolved-question synthesis**
  - Cross-meeting unresolved questions are generated deterministically after Q&A/Open Question deduplication.
  - One unresolved issue per semantic issue is shown with a citation from the correct meeting.
  - Answered Q&A entries remain excluded.

## Regression coverage

Added `backend/tests/test_phase642_cross_meeting_semantics.py` covering:

1. UNION vs INTERSECTION vs COMPARISON vs MEMBERSHIP intent.
2. `Shahin's meeting` + `holography demo meeting` alias resolution.
3. Recovery from the exact false no-evidence named-comparison failure.
4. Recovery from the exact `no strong supported overlap` methods-across failure.
5. Per-meeting citation coverage when Ollama cites only one meeting.
6. Deterministic deduplicated unresolved-question synthesis.

Full suite: **135 tests passed**.

## Versions

- MeetMind API: `1.1.2`
- Frontend marker: `APP.JS 2026-08-14.27 LOADED`

No database migration and no RAG reindex are required.
