# Phase 5.5 — Local LLM Summarization with Ollama

## Goal

Replace the extractive development fallback with a real local LLM that produces
an executive summary, deduplicated key points, decisions, action items, and open
questions without sending meeting transcripts to an external API.

## Architecture

```text
Final cleaned transcript
        ↓
FastAPI MeetingSummaryService
        ↓
Ollama /api/chat
        ↓
Configured local model (default: qwen3:4b)
        ↓
Pydantic JSON schema validation
        ↓
SQLAlchemy summary persistence
        ↓
Meeting Intelligence UI + Meeting History
```

## Configuration

Add these settings to `backend/.env`:

```env
LLM_PROVIDER=ollama
LLM_ALLOW_FALLBACK=false
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_TIMEOUT_SECONDS=180
OLLAMA_NUM_CTX=32768
OLLAMA_KEEP_ALIVE=10m
OLLAMA_THINK=false
```

Install the default model once:

```powershell
ollama pull qwen3:4b
```

Verify Ollama and structured output before running a meeting:

```powershell
python test_ollama_integration.py
```

The API also exposes:

```http
GET /llm/status
```

## Failure behavior

With `LLM_PROVIDER=ollama` and `LLM_ALLOW_FALLBACK=false`, an unavailable Ollama
server or missing model returns a visible HTTP 503 error. The application no
longer silently produces a copied extractive summary.

Set `LLM_ALLOW_FALLBACK=true` only when a fallback is intentionally desired.

## Structured output

The Pydantic schema is sent directly to Ollama through the `format` field. The
response is then validated before being saved. Invalid or incomplete JSON is
rejected instead of being persisted as meeting intelligence.
