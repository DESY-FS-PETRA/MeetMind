# MeetMind Phase 6.4.3 — Scientific Taxonomy & Visual Polish

## Goals

This patch builds on Phase 6.4.2 without changing the database schema or RAG index format.
It addresses the remaining cross-meeting synthesis polish and applies the first production UI identity for MeetMind.

## Cross-meeting scientific synthesis

### Deterministic method taxonomy

Union-style questions such as:

- `What image-processing or reconstruction methods were discussed across meetings?`
- `Which techniques were discussed across all meetings?`

are no longer left entirely to the local LLM. MeetMind groups evidence by meeting and classifies supported terms into:

- Reconstruction / image formation
- Image processing / segmentation
- Synthetic-data / projection generation
- Machine learning / modeling
- Evaluation metrics

This prevents SSIM, PSNR and FRC from being presented as reconstruction methods and prevents supporting data-generation steps from being mixed with image-processing operations.

### Technical-term canonicalization

Generated cross-meeting prose is normalized for a small high-value set of scientific spellings, including:

- `Ots- segmentation` -> `Otsu segmentation`
- `Astra Toolbox` -> `ASTRA Toolbox`
- `Ssim` -> `SSIM`
- `Psnr` -> `PSNR`
- `Frc` -> `FRC`

### Explicit inference labeling

When MeetMind synthesizes a comparison across separate meetings, comparison headings are labeled as:

`Evidence-based comparison (MeetMind inference)`

This makes it clear that the comparison is derived by MeetMind from independently cited meeting evidence and was not necessarily stated inside either meeting.

## MeetMind visual identity

The header now uses a real segmented wordmark:

- `Me` — violet
- `et` — dark navy
- `Mi` — violet
- `nd` — dark navy

A lightweight inline SVG waveform/network motif is included in the header. No external image asset is required.

Visual changes include:

- violet / indigo primary palette
- translucent premium header card
- subtle neural/network background motifs
- gradient active navigation tab and primary buttons
- improved section headers and icons for History and Chat
- softer card hierarchy and shadows
- violet-focused selected meeting state
- improved chat bubbles, source groups and composer
- updated technical-term chips and math blocks

## Compatibility

- No database migration
- No RAG reindex required
- No new Python dependency
- No new frontend package dependency
- Existing MathJax integration is unchanged

## Validation

- Full Python unittest suite passes: 139 tests
- Python compileall passes
- `node --check frontend/app.js` passes
- HTML structure checked with BeautifulSoup
