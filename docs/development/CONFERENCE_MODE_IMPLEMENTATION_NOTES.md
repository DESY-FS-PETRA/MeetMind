# Conference Mode implementation notes

Added on top of `PHASE_6_4_3_SCIENTIFIC_TAXONOMY_VISUAL_POLISH`.

## Added
- First-launch workspace chooser: **Meetings** or **Conferences**.
- Existing meeting workflow preserved as-is.
- Persistent conference/conference-talk SQLAlchemy tables.
- Conference Hub with create/list/open workflow.
- Program ingestion from public URL (best-effort HTML parser) and deterministic JSON import.
- Schedule grouped by day/session, with time/room/search filters.
- Interesting/follow-up marker and per-talk personal notes.
- Automatic Scientific Context Pack generated from conference + talk metadata.
- Talk-specific context passed into the existing bounded adaptive vocabulary / Whisper hotword pipeline.
- Talk → existing MeetMind meeting linkage for live and fast-recorded processing.
- Conference-specific RAG scope over processed talks only.
- Existing meeting and conference knowledge remain separated by default.

## Compatibility
No destructive database migration is used. Existing meeting records stay in the same tables. New conference tables are created automatically at application startup.

## Validation performed
- Python syntax compilation of the backend.
- JavaScript syntax validation with `node --check`.
- New conference schema creation tested against a copy of the existing SQLite database.
- Conference create/import/context generation tested with SQLite.
- Existing meeting count remained intact during schema-upgrade test.

## Important practical note
Conference websites vary greatly. URL import is intentionally best-effort. If a site's HTML is client-rendered or unusually structured, use the included `conference_program_template.json` for deterministic import.

## FIX6 — XRM title + abstract detail enrichment
- Keeps the HTTP client open while fetching clickable talk detail pages; this fixes silent abstract-import failures on APTOR-style sites.
- Improves APTOR title/speaker splitting by preferring the shortest plausible person-name suffix, preventing title endings such as `Holographic Data` from being attached to the presenter name.
- Added regression coverage for XRM talk `4DPP` / HoloZip and the detail-page client lifecycle.
- Full backend suite: 143 tests passing.
