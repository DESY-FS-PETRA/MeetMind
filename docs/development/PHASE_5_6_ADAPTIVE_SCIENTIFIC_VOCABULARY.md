# Phase 5.6 — Adaptive Scientific Vocabulary

## Goal

Improve transcription of synchrotron, X-ray imaging, physics, scientific-computing and AI terminology without requiring users to enter keywords before every meeting.

## What was added

### 1. Master glossary

- 1,000 unique canonical terms
- 12 scientific categories
- 65 core terms that are active from the start
- 162 explicit or generated ASR aliases
- JSON runtime file and editable CSV file
- Deterministic build script: `backend/build_scientific_vocabulary.py`

Categories:

1. Synchrotron, accelerator and beamline
2. X-ray optics and microscopy
3. Holography, phase contrast and coherence
4. Ptychography and coherent diffraction imaging
5. Tomography and inverse problems
6. Scanning modalities, spectroscopy and materials
7. Detectors, acquisition and calibration
8. AI, machine learning and image processing
9. Scientific software, programming and HPC
10. Simulation, numerical methods and optimization
11. Experimental methods and materials science
12. Scientific writing, proposals and EU projects

### 2. Bounded adaptive hotwords

The full glossary is never sent to Whisper. Each meeting uses:

- up to 70 core terms initially;
- automatically detected topic categories;
- at most 120 active terms;
- at most 240 whitespace-separated hotword words.

This keeps the Whisper prompt bounded while making specialist terminology more likely.

### 3. Automatic topic detection

After each preliminary transcript, the vocabulary service scores glossary categories using:

- category keyword matches;
- canonical-term matches;
- alias matches;
- token overlap.

The highest-scoring categories are activated automatically. The user does not need to know the meeting topic beforehand.

### 4. Confidence-aware terminology correction

Explicit ASR aliases are corrected only when the associated canonical term is active. Examples:

- `ASTA football` → `ASTRA Toolbox`
- `tomo pie` → `TomoPy`
- `pty pie` → `PtyPy`
- `pie F A I` → `pyFAI`
- `PETRA 3` → `PETRA III`

A conservative fuzzy correction path is also available only for low-confidence words and uses a high similarity threshold.

### 5. Database persistence

A new SQLAlchemy table stores, per meeting:

- detected categories;
- active terms;
- category scores;
- correction count;
- revision and finalization state.

`create_all()` adds the new SQLite table automatically. Existing meeting data is not deleted.

### 6. Frontend status

The header now shows a live vocabulary badge, for example:

`Tomography and inverse problems + Ptychography and coherent diffraction imaging · 120 terms · 2 corrected`

Meeting History also displays the detected vocabulary domains.

## New endpoints

- `GET /vocabulary/status`
- `GET /meeting/{meeting_id}/vocabulary`
- `POST /meeting/{meeting_id}/vocabulary/refresh`

## Environment settings

```env
VOCABULARY_ENABLED=true
VOCABULARY_PATH=app/vocabulary/data/scientific_vocabulary_1000.json
VOCABULARY_MAX_HOTWORDS=120
VOCABULARY_MAX_HOTWORD_WORDS=240
VOCABULARY_CORE_TERM_LIMIT=70
VOCABULARY_MAX_CATEGORIES=4
VOCABULARY_MIN_TOPIC_SCORE=2.0
VOCABULARY_CORRECTION_CONFIDENCE=0.72
VOCABULARY_FUZZY_THRESHOLD=0.92
VOCABULARY_INITIAL_PROMPT=Technical scientific meeting about synchrotron radiation, X-ray physics, imaging, reconstruction, simulation and AI.
```

## Diagnostic test

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python test_vocabulary_integration.py
```

Expected correction:

```text
Before: We used ASTA football and tomo pie for reconstruction.
After:  We used ASTRA Toolbox and TomoPy for reconstruction.
```

## Full test suite

```powershell
python -m unittest discover -s tests -v
```

Expected result:

```text
Ran 32 tests
OK
```

## Important safety behavior

The vocabulary corrector does not use an LLM to rewrite the transcript. It only applies:

- explicit aliases from the local glossary; or
- high-threshold fuzzy matches when the source words have low confidence.

Unrelated high-confidence sentences such as `The football match starts later` are not changed.

## Known limitation

`Nεo 2.0` is excluded because its exact canonical spelling/product identity was not confirmed. Add it after confirming the correct name.
