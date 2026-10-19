# Phase 6.2 — Intelligent Query Router

Phase 6.2 upgrades the Chat tab from a meeting-only RAG interface into a routed local scientific assistant while preserving strict grounding for meeting-specific claims.

## Routes

### 1. Meeting archive (RAG-only)
Used for explicit archive questions such as:
- Which meetings discussed ASTRA Toolbox?
- What was the main goal of Shahin's presentation?
- What unresolved questions remain?
- Do you know Vahid Rahmani? (named-person questions stay archive-grounded to avoid invented biography)

Meeting claims are answerable only from retrieved evidence and keep [S#] citations.

### 2. General knowledge
Used when a general scientific question has no sufficiently relevant archive evidence.
Example: `What is the Fourier transform?`
The local Ollama chat model answers without meeting citations.

### 3. Hybrid: general knowledge + meeting archive
Used for broad scientific questions when the indexed meetings contain concrete relevant evidence.
Example: `Tell me about Otsu segmentation.`
The answer can contain:
- `General context:` model knowledge without meeting citations.
- `From your meetings:` only grounded meeting-specific statements with [S#] citations.
Only cited meeting source cards are shown.

### 4. System date/time
Date/time questions bypass RAG and Ollama.
Examples:
- What is today's date?
- What time is it?
- What is the current date and time?
The backend returns its local system date/time.

## Safety / grounding rules
- Explicit meeting questions never silently fall back to general knowledge.
- Named-person `Do you know ...?` questions remain archive-grounded.
- General questions only enter Hybrid mode when archive evidence has a concrete lexical anchor; semantic similarity alone is not enough.
- Meeting-specific facts in Hybrid answers must be cited.
- Retrieved-but-unused sources are not displayed.
- No-evidence RAG answers return zero source cards.

## UI changes
The Chat page now describes the intelligent router and reports the active route:
- Answered from system date/time
- Answered using local Ollama · general knowledge
- Answered using general knowledge + meeting sources
- Answered from meeting archive using semantic + lexical retrieval
- No supporting meeting evidence found

## Regression coverage
Five new router tests cover:
1. system date handling with zero RAG/Ollama calls,
2. general knowledge fallback,
3. Hybrid general + meeting answer,
4. archive-grounded unknown named person,
5. explicit meeting RAG question.

Full backend suite after Phase 6.2: 95 tests, all passing.
