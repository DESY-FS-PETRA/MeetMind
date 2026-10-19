# Phase 5 — Database Persistence and Meeting History

## Goal

Phase 5 replaces the Phase 1–4 JSON persistence layer with a relational database and adds a Meeting History interface.

The default setup uses SQLite, so no external database server is required. The persistence code uses SQLAlchemy 2.x and reads `DATABASE_URL`, allowing a later move to PostgreSQL without changing the meeting/transcription services.

## Database schema

### `meetings`

- meeting id, title and status
- creation/start/end timestamps
- final transcript
- transcript count
- average word confidence
- low-confidence word count

### `transcript_segments`

- event and stable segment identifiers
- rolling revision number
- partial/final state
- transcript text
- word timestamps/probabilities as JSON
- average confidence and review count

The pair `(meeting_id, segment_id)` is unique, so rolling transcript revisions update one row instead of creating duplicates.

### `meeting_summaries`

- executive summary
- key points, decisions and open questions
- provider/model metadata
- generation timestamp and transcript statistics

### `action_items`

- task, owner, deadline and completion state
- ordered relationship to the meeting summary

Foreign keys use cascade deletion, so deleting a meeting also removes its transcript, summary and action items.

## API added

- `GET /meetings` — list/search meetings
- `GET /meetings/{meeting_id}` — load complete meeting details
- `PATCH /meetings/{meeting_id}` — rename a meeting
- `DELETE /meetings/{meeting_id}` — delete a meeting and related data

The older singular endpoint `GET /meeting/{meeting_id}` remains available for compatibility.

## Frontend added

The application now has two views:

1. **New Meeting** — existing recording, live transcript and summary workflow.
2. **Meeting History** — database statistics, transcript/title search, meeting list and detail view.

The detail view includes:

- editable title
- status, date, duration and confidence metadata
- final transcript with low-confidence word highlighting
- summary, key points, decisions, action items and open questions
- delete action

## Configuration

Copy `.env.example` to `.env` and keep:

```env
DATABASE_URL=sqlite:///data/meeting_ai.db
```

The database is created automatically on first backend start.

For a future PostgreSQL deployment, install a PostgreSQL driver and change only the URL, for example:

```env
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/meeting_ai
```

## Importing Phase 1–4 JSON meetings

Keep the old `backend/data/meetings` folder and run once:

```powershell
python -m app.database.migrate_json --source data/meetings
```

Existing meeting ids are skipped, making the importer safe to run again.

## Confidence threshold refinement

Short function words such as `a`, `the`, `to` and `of` now use a lower review threshold to reduce false-positive highlights:

```env
WHISPER_LOW_CONFIDENCE_THRESHOLD=0.65
WHISPER_FUNCTION_WORD_THRESHOLD=0.35
```

No transcript word is automatically changed.

## Tests

Run:

```powershell
python -m unittest discover -s tests -v
```

Phase 5 includes tests for:

- database CRUD
- transcript revision upsert
- summary/action-item persistence
- search and title update
- cascade deletion
- legacy JSON migration
- all Phase 3/4 streaming, overlap, cleanup and confidence behavior

Expected result: **15 tests pass**.

## Deliberately deferred

- Alembic schema migrations
- PostgreSQL container
- authentication and multi-user ownership
- action-item completion editing
- RAG/vector indexing

Those belong to the next production and retrieval phases.
