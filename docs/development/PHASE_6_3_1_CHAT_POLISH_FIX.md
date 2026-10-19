# Phase 6.3.1 — Chat Polish Fix

This patch is a focused follow-up to Phase 6.3 based on real UI testing.

## Fixes

### 1. Weather location parsing
- Phrases such as `weather temperature for today` are no longer interpreted as a location named `temperature for`.
- The common misspelling `weather tempruter for today` is also rejected as a location hint.
- Generic time/request words are filtered before geocoding.
- Explicit queries such as `weather in Hamburg today`, `weather Hamburg today`, and `temperature for Hamburg` still resolve normally.

### 2. Weather follow-up routing
- When Chat asks for a location, a short reply such as `Hamburg` remains in the weather route.
- The plain city reply is geocoded and live weather is fetched instead of falling back to Ollama general knowledge.

### 3. Scientific equation presentation
- Important equations are requested from the LLM as standalone display-math blocks.
- The frontend now preserves `$$...$$` and `\\[...\\]` blocks as dedicated centered containers before Markdown processing.
- Inline math is protected from Markdown emphasis parsing.
- Long equations scroll horizontally rather than collapsing the chat layout.

### 4. Hybrid evidence compacting
- Hybrid answers receive at most 3 meeting evidence chunks by default.
- `Technical Terms` chunks are removed when stronger slide/transcript/key-point/summary evidence exists.
- The prompt explicitly asks for the smallest sufficient citation set.

## Regression tests

Added tests for:
- `tell me weather temperature for today` not becoming a fake location.
- misspelled `tempruter` not becoming a fake location.
- `Hamburg` as a weather-location follow-up.
- rejection of generic words such as `temperature` as a follow-up location.
- compact Hybrid evidence with Technical Terms suppression.

Full backend suite: **105 tests, all passing**.
Frontend JavaScript: `node --check` passing, plus a direct renderer smoke test for display and inline math.

Frontend build marker: `APP.JS 2026-08-14.23 LOADED`.
