# Phase 5.7 — Uploaded Presentation Context

This phase adds local PPTX/PDF ingestion and slide-aware transcription to the
Meeting AI Assistant.

## What is implemented

- Upload a `.pptx` or `.pdf` before starting a meeting.
- Store the original file locally under `backend/data/presentations/`.
- Extract slide/page text and PowerPoint speaker notes.
- Detect up to 12 visible scientific terms per slide.
- Attach the uploaded deck to the meeting in SQLAlchemy.
- Start with slide 1 as the active context.
- Automatically match raw, hallucination-sanitized speech to the most likely
  slide while the presenter advances.
- Let the user manually select a slide or return to automatic matching.
- Prioritize current-slide terms in Whisper hotwords while preserving the
  Phase 5.6 safety caps: at most 24 phrases and 48 hotword words total.
- Include slide titles and visible terms as optional context for the local LLM
  meeting summary. Slide text cannot create decisions or action items by itself.
- Show the active slide and its terms in the frontend and Meeting History.

## Database compatibility

No columns are added to the existing `meetings` table. SQLAlchemy creates three
new tables automatically when the backend starts:

- `presentations`
- `presentation_slides`
- `meeting_presentations`

This preserves existing SQLite meeting history without a destructive migration.

## Installation

Activate the existing environment and install the updated requirements:

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
pip install -r requirements.txt
```

New dependencies:

- `python-multipart` for FastAPI file uploads
- `python-pptx` for PPTX text and notes
- `pypdf` for text-based PDF pages

## Optional `.env` settings

```env
PRESENTATION_STORAGE_DIR=data/presentations
PRESENTATION_MAX_MB=50
PRESENTATION_MAX_SLIDES=300
PRESENTATION_MAX_TEXT_CHARACTERS=500000
SLIDE_VOCABULARY_MAX_TERMS=12
SLIDE_MATCH_MIN_SCORE=5.0
SLIDE_MATCH_MIN_MARGIN=1.25
```

The hard vocabulary safety limits from Phase 5.6.1 remain active.

## Test a presentation without starting the UI

```powershell
python test_presentation_integration.py "D:\path\to\presentation.pptx"
```

The command prints each slide title, extracted terms, text preview, and speaker
notes preview.

## Normal UI workflow

1. Choose a `.pptx` or `.pdf`.
2. Click **Upload slides**.
3. Confirm the slide count and extracted title.
4. Click **Start Meeting**.
5. Keep **Automatic slide matching** selected.
6. If automatic matching is wrong, choose the correct slide manually.
7. Choose automatic matching again to resume tracking.

## Safety design

The uploaded deck is not used as a large global prompt. Only the current
slide's small term set is prioritized. Automatic matching reads the raw,
sanitized Whisper output before vocabulary correction, avoiding a feedback loop
where a hotword causes itself to be selected repeatedly.

## Current limitation

`pypdf` extracts embedded PDF text but is not OCR. Image-only or scanned PDF
slides may return little or no text. PPTX text boxes, tables, and speaker notes
are supported. OCR and local vision analysis remain a later phase.
