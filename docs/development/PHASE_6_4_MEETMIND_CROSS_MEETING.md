# Phase 6.4 — MeetMind Cross-Meeting Validation

Phase 6.4 gives the application its product name, **MeetMind**, and hardens the RAG pipeline for genuine multi-meeting questions.

## Product branding

The visible application title is now `MeetMind`, the browser title is `MeetMind — AI Meeting Intelligence`, and the FastAPI service identifies itself as `MeetMind API`.

## Cross-meeting retrieval

Cross-meeting queries are detected explicitly, including phrases such as:

- `Which meetings discussed ...?`
- `Compare the topics across all meetings`
- `Summarize all meetings`
- `Compare discussions ...`

For archive-wide overview questions, MeetMind seeds retrieval with the Executive Summary of each completed meeting. For topic-specific questions, a meeting is only admitted to the comparison when its evidence contains concrete topic anchors. Generic words such as `meeting`, `discussed`, `compare`, and `across` do not qualify an unrelated meeting.

The answer context is diversified so that, when several meetings are genuinely relevant, at least one strong source from each meeting reaches the LLM before remaining source slots are filled. Responses expose `cross_meeting` and `meetings_used`, and the frontend reports the number of meetings represented in a cross-meeting answer.

## Safe demo meeting

`backend/seed_cross_meeting_demo.py` creates one clearly labeled, reversible test meeting:

`[DEMO] Near-Field Holography Reconstruction`

The demo contains synthetic text about near-field X-ray holography, Fresnel propagation, phase retrieval, SSIM/PSNR, and FRC. It is intentionally distinct from Shahin's stereo X-ray synthetic-data meeting.

Create it from the backend directory:

```powershell
python seed_cross_meeting_demo.py
```

The script is idempotent and refreshes the RAG index. Remove it later with:

```powershell
python seed_cross_meeting_demo.py --remove
```

The `[DEMO]` prefix is deliberate so demo content cannot be mistaken for a real meeting.

## Recommended validation questions

```text
Compare the topics across all meetings.
Which meetings discussed Otsu segmentation?
Which meetings discussed phase retrieval?
What reconstruction or image-processing methods were discussed across meetings?
Summarize the unresolved questions across all meetings.
Compare Shahin's meeting with the holography demo meeting.
```

Expected high-level behavior with the current Shahin meeting plus the demo:

- `Compare the topics across all meetings` uses evidence from both meetings.
- `Which meetings discussed Otsu segmentation?` returns Shahin only.
- `Which meetings discussed phase retrieval?` returns the holography demo only.

## Regression status

Phase 6.4 adds five tests for cross-meeting diversity, topic membership, routing, and reversible demo seeding.

```text
Ran 123 tests
OK
```

Python compile checks and `node --check frontend/app.js` also pass.
