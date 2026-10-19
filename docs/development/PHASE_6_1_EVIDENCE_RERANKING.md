# Phase 6.1 — Evidence Re-ranking & Citation Precision

This patch hardens the cross-meeting RAG layer introduced in Phase 6.

## Main changes

1. **No-evidence gate**
   - Questions about named people, software, or acronyms require matching meeting evidence.
   - Unrelated queries return a compact no-evidence response with `sources: []`.
   - The LLM is not called when the retrieval gate already proves that no evidence exists.

2. **Intent-aware evidence ranking**
   - `main goal / purpose / aim` favors executive summaries, slide summaries, and key points.
   - `how / generated / method / pipeline` favors method-related slide summaries and key points.
   - `open/unresolved questions` favors Open Questions and Discussion Q&A.
   - decisions and action-item queries favor their corresponding source types.

3. **Evidence re-ranking and duplicate suppression**
   - More candidates are retrieved first and then re-ranked.
   - Near-duplicate chunks from the same meeting are suppressed.
   - Common question words no longer inflate lexical similarity.

4. **Cited sources only**
   - After Ollama generates an answer, only source IDs actually cited in the answer are returned to the frontend.
   - Retrieved but unused chunks are no longer rendered as source cards.

5. **No citations on no-evidence answers**
   - If retrieval or the LLM concludes that evidence is unavailable, citations are removed and no source cards are shown.

## Optional .env settings

```env
RAG_CANDIDATE_K=16
RAG_MAX_SOURCES=6
RAG_MIN_EVIDENCE_SCORE=0.26
RAG_MIN_SEMANTIC_SCORE=0.38
```

The defaults above are built into the code, so adding them is optional.

## Regression example

Question:

```text
Do you know Vahid Rahmani?
```

Expected result when the indexed meetings contain no information about that person:

```text
I couldn't find any information about Vahid Rahmani in the indexed meetings.
```

No `[S1]` citation and no source cards are returned.

## Tests

Phase 6.1 adds regressions for:
- unrelated named-entity queries,
- no-evidence answers with accidental LLM citations,
- returning only source cards actually cited by the model.

Full suite: **90 tests**.
