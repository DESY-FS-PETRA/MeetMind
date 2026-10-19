# MeetMind Phase 6.4.1 — Cross-Meeting Grounding & Deduplication

This patch hardens cross-meeting answers after the first real two-meeting RAG test.

## Fixed

### 1. Citation-to-meeting binding
Cross-meeting evidence is now grouped into explicit MEETING GROUP blocks with meeting IDs. After Ollama answers, MeetMind audits every line that explicitly names a meeting. If a citation points to a source from the wrong meeting, it is rebound to the best matching source from the named meeting before the answer reaches the UI. Unsupported meeting-specific lines are removed rather than shown with a false citation.

### 2. Missing citations in cross-meeting answers
Some local-LLM outputs answered broad questions such as "Compare the topics across all meetings" without citation markers. MeetMind now grounds substantive uncited lines against the retrieved evidence. A line gets a citation only when its content has a concrete source match; unsupported factual bullets are removed.

### 3. Unsupported shared themes / fake overlap
Shared claims such as "both meetings discussed image metrics" are now checked against evidence from at least two distinct meetings. If the claimed concept is not actually common to the cited meeting evidence, the line is removed. The prompt also receives a conservative list of lexical anchors that are genuinely shared across meeting groups.

### 4. Unresolved-question deduplication
For archive-wide unresolved-question summaries, MeetMind now:
- keeps only unresolved/open Discussion Q&A entries;
- ignores answered Q&A entries;
- merges duplicate or near-duplicate Open Question and Discussion Q&A representations within the same meeting;
- never describes duplicate sources from one meeting as separate "meeting instances".

### 5. Comparison behavior
Named comparisons such as `Compare Shahin's meeting with the holography demo meeting` are now recognized as true cross-meeting synthesis queries. Executive summaries and other intent-appropriate evidence are seeded per meeting. MeetMind is explicitly allowed to derive a comparison from independent meeting evidence and no longer requires the meetings themselves to have directly compared one another.

### 6. Contradictory no-evidence footer
If a comparison is already grounded with citations, a trailing sentence such as `No supporting meeting evidence was found that directly compares the two meetings` is removed. If there is genuinely no evidence at all, normal no-evidence behavior is unchanged.

### 7. Chat-history isolation
For a self-contained cross-meeting question, prior assistant answers are no longer passed as factual evidence to the RAG synthesis prompt. History is used only for genuinely referential follow-ups. This prevents facts from an earlier answer from contaminating a new comparison.

### 8. Source cards grouped by meeting
The Chat UI now groups cited source cards under their meeting title. This makes source attribution much easier to inspect during comparisons.

## Versions
- MeetMind API: 1.1.1
- Frontend: `APP.JS 2026-08-14.26 LOADED`

## Validation
- Full test suite: 129 tests, all passing.
- JavaScript syntax check: passed.
- Python compile check: passed.
- Real-data validation: clone of the single-Shahin database + the clearly labeled holography demo meeting.

Real-data retrieval checks passed for:
- `Compare the topics across all meetings.` → both meetings represented.
- `Which meetings discussed Otsu segmentation?` → Shahin only.
- `Which meetings discussed phase retrieval?` → holography demo only.
- `What image-processing or reconstruction methods were discussed across meetings?` → evidence from both meetings.
- `Summarize the unresolved questions across all meetings.` → one unresolved issue per relevant meeting; answered Q&A excluded.
- `Compare Shahin's meeting with the holography demo meeting.` → recognized as cross-meeting synthesis with both Executive Summaries available.

No database schema change is required. Reindexing is not required because chunk structure did not change.
