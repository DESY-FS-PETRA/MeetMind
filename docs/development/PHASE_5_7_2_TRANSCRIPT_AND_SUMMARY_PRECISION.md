# Phase 5.7.2 — Transcript and Slide-Summary Precision

This release improves the real reference-deck results from Phase 5.7.1.

## Main fixes

### 1. Real slide titles from custom PowerPoint templates

Many scientific decks use ordinary text boxes rather than PowerPoint title placeholders. The extractor now ranks visual title candidates using position and font size.

Examples:

- `Slide 2` → `Motivation: synchrotron X-ray imaging`
- `Slide 3` → `Experimental setup and beamline context`
- `Slide 5` → `Tomography reconstruction with ASTRA Toolbox`

Generic labels such as `Slide 2` are no longer stored as slide titles.

### 2. Safer slide vocabulary

Displayed ASR-error examples are excluded from slide hotwords and technical-term lists.

For example:

- `Avoid ASTA football errors` does **not** add `ASTA` as a technical term.
- `ASTRA Toolbox` remains the canonical term.
- `Ray` is no longer extracted from the `X-ray` token.
- fragments such as `back projection` and `cone-beam` are suppressed when the canonical terms `filtered back projection` and `cone-beam geometry` are available.

The safe slide-term limit is now 14. The global hotword and word-count limits remain active, so this does not restore the old aggressive Phase 5.6 behavior.

### 3. Contextual correction from slide titles and visible terms

New reference errors are corrected only while the related slide is active:

- `modi-for` → `motivation for`
- `scientific vocab workload` → `scientific vocabulary`
- `l-learning` → `machine learning`
- `PyPhy` → `pyFAI`
- `cSAX` / `CSX` → `cSAXS code`

Metalinguistic examples remain protected:

- `ASTRA Toolbox is not confused with ASTA football.` remains unchanged.
- `PETRA III and PETRA IV` keeps both qualified facility names.

### 4. Scientific enumeration cleanup

Short overlap artifacts inside technical lists are removed:

Before:

`PtyPy PyNX pyFAI and the cSAXS code PtyPy, and the cSAXS code`

After:

`PtyPy PyNX pyFAI and the cSAXS code`

### 5. More reliable slide-to-transcript alignment

When a recording explicitly says `On slide 2`, `On slide 3`, and so on, those spoken markers become the primary alignment timeline. Asynchronous auto-match events are ignored for section boundaries in that situation, preventing one slide discussion from being split into small fragments.

### 6. Complete slide summaries

Small local models occasionally summarize only the first method from a long spoken list. Phase 5.7.2 measures terminology coverage. When an LLM slide summary omits most slide-supported terms, the system uses the complete spoken slide section instead.

### 7. Cleaner Technical Terms and Uncertainties

Technical Terms now prefer canonical terms from the uploaded slide.

Filtered examples:

- `Ray`
- `ASTA`
- `back projection` when `filtered back projection` exists
- `cone-beam` when `cone-beam geometry` exists
- generic UI phrases such as `Slide-Aware`

Correct canonical terms with low acoustic confidence are no longer shown as unresolved uncertainties when the uploaded slide confirms them. Examples include:

- `sinogram`
- `TomoPy`
- `SIRT`
- `PtyPy`
- `PyNX`
- `sCMOS detector`

## Installation

1. Stop backend and frontend.
2. Extract `meeting_ai_phase5_7_2_precision_patch.zip` into:

   `D:\meeting-ai-assistant`

3. Confirm file replacement.
4. Keep the existing `.env` and SQLite database.
5. Optional `.env` setting:

   `SLIDE_VOCABULARY_MAX_TERMS=14`

6. Restart the backend and frontend.
7. Upload the PPTX again. Existing presentation records retain the old extracted titles and keywords.
8. Start a new meeting and run the reference audio again.

## Tests

Run:

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected result:

`Ran 56 tests` followed by `OK`.

The mocked Ollama offline/404 lines printed during two failure-path tests are expected.

Frontend version:

`APP.JS 2026-07-23.11 LOADED`
