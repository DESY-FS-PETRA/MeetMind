# Phase 5.7.1 — Slide Summary and Transcript Cleanup

This release refines the Phase 5.7 slide-aware meeting assistant using the synthetic reference deck and narration.

## Main changes

### Safer final transcript cleanup

The final rolling transcript now:

- joins split hyphenated tokens such as `X -ray` → `X-ray` and `Slide -Aware` → `Slide-Aware`;
- removes immediately repeated words such as `cluster cluster`;
- removes immediately repeated multiword overlap echoes;
- keeps the higher-confidence copy when an adjacent word is repeated;
- does not perform broad lexical rewriting in the transcript cleaner.

### Reference-tested scientific aliases

The local glossary now includes aliases for:

- `synogram` → `sinogram`;
- `CSX`, `CSX code`, and related forms → `cSAXS code`;
- `SCMOS detector` → `sCMOS detector`;
- `object retrieve` → `object retrieval`;
- `dark-field correct` → `dark-field correction`;
- `l learning` → `machine learning`;
- `llama` → `Ollama` when Ollama is active in the slide context;
- `TRA-4` → `PETRA IV`;
- split/plural forms of `autoencoder`.

Corrections remain limited to active slide/domain terms.

### Metalinguistic context protection

Evaluation phrases are protected. For example:

```text
ASTRA Toolbox is not confused with ASTA football.
```

The intentionally incorrect phrase `ASTA football` is preserved because it follows `not confused with`.

Other protected patterns include:

- `transcribed as`;
- `incorrect transcription is`;
- `Whisper wrote`;
- `the output was`;
- `recognized as`;
- `heard as`;
- `mistaken for`;
- `instead of`.

### Slide timeline and transcript alignment

Every slide change now creates a local database event containing:

- slide number;
- source (`initial`, `automatic`, or `manual`);
- match score;
- transcript character and word offsets;
- timestamp.

Spoken phrases such as `On slide 5` and `On the final slide` are also used as deterministic alignment anchors.

New table:

```text
meeting_slide_events
```

### Slide-by-slide summary

The summary response now contains:

```json
{
  "slide_summaries": [
    {
      "slide_number": 5,
      "title": "Tomography reconstruction",
      "summary": "The presenter described sinogram reconstruction using ASTRA Toolbox, SIRT, CGLS, and filtered back projection.",
      "key_terms": ["ASTRA Toolbox", "sinogram", "SIRT", "CGLS"]
    }
  ],
  "technical_terms": ["ASTRA Toolbox", "PtyPy", "Fresnel propagation"],
  "transcription_uncertainties": ["sinogram (42% confidence)"]
}
```

If the small LLM omits slide summaries, a deterministic fallback creates them from the slide-aligned transcript sections.

### Persistent summary extras

The new fields are stored in a separate table so existing SQLite databases do not need destructive column migration:

```text
meeting_summary_extras
```

The fields are available in both the live post-meeting view and Meeting History.

## Installation

1. Stop the backend and frontend.
2. Extract the patch into the project root:

```text
D:\meeting-ai-assistant
```

3. Confirm file replacement.
4. No new Python dependency is required.
5. Start the backend:

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m uvicorn app.main:app --reload
```

6. Start the frontend:

```powershell
cd D:\meeting-ai-assistant\frontend
python -m http.server 3000
```

7. Open `http://localhost:3000` and press `Ctrl + F5`.

The browser console should show:

```text
APP.JS 2026-07-23.10 LOADED
```

## Tests

Run:

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected:

```text
Ran 48 tests

OK
```

The tests include the exact reference-error patterns discussed during development.
