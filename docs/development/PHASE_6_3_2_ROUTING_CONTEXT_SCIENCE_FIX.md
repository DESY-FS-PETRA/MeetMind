# Phase 6.3.2 — Routing, Context Isolation & Scientific Answer Safety

This maintenance patch addresses regressions found during real interactive Chat testing after Phase 6.3.1.

## Fixed

### 1. Weather follow-up location parsing
Short replies such as `in hamburg`, `at Berlin`, or `near Munich` are normalized before geocoding when the previous assistant turn requested a weather location. The preposition is no longer sent as part of the place name.

### 2. New short topics no longer inherit unrelated history
The retrieval query only includes the previous user turn for genuinely referential follow-ups such as `what about the second method?`, `how does it work?`, or questions using `this/that/it/they`.

Self-contained short questions such as `Tell me about Otsu segmentation` now start a clean retrieval query even if the previous turn was about weather or another topic.

### 3. Explicit talk/presentation questions override prior chat context
Queries such as `what is the shahin's talk about?` are routed directly to the Meeting Archive even when the name is lowercase and even if the previous answer was Hybrid. This prevents a previous topic (for example Otsu) from leaking into the answer.

### 4. Meeting-title matches help scope retrieval without dominating it
Meeting titles are now included as a lower-weight lexical signal. A query mentioning `Shahin` can find the meeting `shahin 5`, but every chunk no longer gets an artificially dominant score solely because it shares the title. Overview questions therefore prefer Executive Summary / slide summaries over arbitrary transcript chunks.

### 5. Hybrid evidence gating uses the current question
Hybrid mode now evaluates concrete lexical anchors from the current retrieval query instead of allowing unrelated history text to determine whether meeting evidence is relevant.

### 6. Scientific formula safety
General and Hybrid prompts now discourage unsolicited equations. The model is instructed to:

- include formulas only when requested, genuinely necessary, or part of a standard mathematical definition;
- never invent or improvise equations;
- distinguish within-class/intra-class quantities from between-class/inter-class quantities;
- distinguish minimization from maximization criteria.

This specifically prevents explanatory questions such as `Tell me about Otsu segmentation` from receiving a decorative but incorrect formula, while mathematical topics such as the Fourier transform may still include their canonical defining equation.

## Regression coverage

New tests cover:

- `in hamburg` after a weather location request;
- Otsu asked immediately after a weather conversation;
- lowercase `shahin's talk` archive routing;
- retrieval-context isolation for a self-contained short topic;
- preservation of contextual follow-ups such as `what about the second method?`;
- equation policy for Otsu vs Fourier;
- explicit Shahin-talk questions after a Hybrid Otsu answer;
- summary-first evidence selection for talk-overview questions.

Expected full backend test result: **111 tests, OK**.
