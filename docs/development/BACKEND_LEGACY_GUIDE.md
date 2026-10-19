# MeetMind — Local AI Meeting Intelligence

## Install

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m pip install -r requirements.txt
```

Create `.env` if needed:

```powershell
Copy-Item .env.example .env
notepad .env
```

Default database setting:

```env
DATABASE_URL=sqlite:///data/meeting_ai.db
```

## Optional: import old JSON meetings

Run this before deleting or moving the old `data/meetings` folder:

```powershell
python -m app.database.migrate_json --source data/meetings
```

## Run

```powershell
python -m uvicorn app.main:app --reload
```

The SQLite database will be created at:

```text
backend\data\meeting_ai.db
```

## Frontend

```powershell
cd D:\meeting-ai-assistant\frontend
python -m http.server 3000
```

Open `http://localhost:3000` and press `Ctrl + F5` once. The console should show:

```text
APP.JS 2026-08-14.25 LOADED
```

## Test

```powershell
cd D:\meeting-ai-assistant\backend
python -m unittest discover -s tests -v
```

Expected: `Ran 123 tests` and `OK`.

## Phase 5.7 presentation upload

Install the updated requirements, then upload a PPTX/PDF from the frontend
before starting a meeting. The backend extracts slide text locally and uses only
the active slide's bounded terminology as Whisper context.

Standalone test:

```powershell
python test_presentation_integration.py "D:\path\to\deck.pptx"
```
