# Phase 5.5.1 — Structured Decision and Action-Item Extraction Fix

## Why this patch was needed

The local Qwen 4B model generated a good abstractive summary, but sometimes left
`decisions` and `action_items` empty even when the transcript explicitly said:

- "They agreed to use Ollama..."
- "Vahid will integrate the Ollama endpoint into FastAPI before Friday."

## What changed

### 1. Stronger extraction prompt

The system prompt now defines every output field and requires an audit before
returning JSON:

- `agreed`, `decided`, `selected`, and `we will use` are treated as decisions.
- named `will`, `must`, `needs to`, and `is responsible for` statements are
  treated as action items.
- owner and deadline must be preserved when explicitly stated.
- decisions/actions may not appear only in the summary while their dedicated
  arrays remain empty.

A compact extraction example is included for small local models.

### 2. Richer JSON Schema descriptions

Pydantic fields now describe the exact meaning of `decisions`, `action_items`,
`owner`, and `deadline`, so Ollama receives a more informative schema.

### 3. Deterministic StructuredMeetingEnricher

A conservative post-processing layer checks the original transcript after the
LLM response. It only recovers explicit evidence:

- explicit decisions such as `the team agreed to ...`
- named assignments such as `Vahid will ... before Friday`
- exact owner and deadline phrases

It does not invent missing facts. If the model already extracted an item, the
layer deduplicates it and only fills missing owner/deadline values.

### 4. Stronger integration test

`test_ollama_integration.py` now validates that:

- the Ollama decision is present,
- the FastAPI integration task is present,
- the owner is `Vahid`,
- the deadline contains `Friday`.

A successful run ends with:

```text
=== VALIDATION PASSED ===
Decision, action-item owner, and deadline were extracted correctly.
```

## Test result

```text
Ran 25 tests
OK
```

The tests include the exact failure mode where a small model returns good
summary text but empty decision/action arrays.
