# MeetMind Conference Mode

Conference Mode is a separate scientific-event workspace layered on top of the existing MeetMind meeting pipeline. Existing Meetings, History, Chat, database records and RAG behavior are preserved.

## Workflow

1. Start MeetMind and choose **Conferences** on the landing page.
2. Create a conference (name, location, dates, optional official program URL and conference-wide vocabulary).
3. Import the program using:
   - **Import URL**: best-effort parsing of public HTML schedule pages.
   - **Import JSON**: deterministic/recommended import for complex conference websites.
4. Talks are grouped by **day → session → time**, and show room, speaker metadata, processing state and Interesting status.
5. Open a talk to inspect its automatically generated **Scientific Context Pack**.
6. Click **Record / Process this Talk**. The existing MeetMind recording page opens with the talk title and context loaded.
7. Use either live microphone capture or **Fast recorded meeting**. The resulting normal MeetMind meeting record is linked back to the conference talk.
8. Return to **Conference** and ask questions over the processed talks using Conference RAG.

## Scientific Context Pack

Context terms are built from conference-wide terms plus each talk's title, abstract, session, track, speaker, institution and imported keywords. They are supplied to Whisper as a bounded ASR bias. They are **not** treated as evidence and never appear as transcript claims unless actually spoken/retrieved.

This is designed to improve recognition of scientific names, methods, acronyms and facility terminology while preserving MeetMind's existing hallucination safeguards.

## JSON program format

Use `conference_program_template.json` as a starting point. The root can be either an array or `{ "talks": [...] }`.

Important fields:

- `external_id`: stable program/talk code if available
- `title`
- `speaker`
- `institution`
- `day_label`
- `start_at`, `end_at`: `HH:MM` or ISO timestamps
- `room`
- `session_name`
- `track`
- `abstract`
- `keywords`: array
- `context_terms`: optional additional ASR terms

## Data model

Conference records are stored in two new SQLAlchemy tables:

- `conferences`
- `conference_talks`

A processed talk links to the existing `meetings.id`. This deliberately reuses the proven transcription, summary, presentation, vocabulary and RAG pipeline instead of duplicating it.

Existing SQLite databases are safe: SQLAlchemy `create_all()` adds the new tables without replacing existing meeting tables.

## URL importer

Public HTML program pages differ widely. The URL importer is intentionally best-effort and includes schedule heuristics for time ranges, rooms, sessions and APTOR-style programs. For JavaScript-only, authenticated, or unusually structured sites, JSON import is the reliable fallback.
