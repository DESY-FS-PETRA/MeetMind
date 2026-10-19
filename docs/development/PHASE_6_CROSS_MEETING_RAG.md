# Phase 6 — Cross-Meeting RAG Chat

Phase 6 adds a third top-level **Chat** view next to **New Meeting** and **Meeting History**.

## What it does

- Indexes all completed meetings from the existing SQLAlchemy database.
- Chunks final transcripts plus structured meeting intelligence:
  - executive summaries
  - slide summaries
  - key points
  - decisions
  - action items
  - discussion Q&A
  - unresolved questions
  - canonical technical terms
- Uses local Ollama embeddings when the configured embedding model is installed.
- Falls back to lexical retrieval if embeddings are unavailable.
- Uses the existing Ollama chat model to answer only from retrieved meeting evidence.
- Returns source cards for every answer. Clicking a source opens that meeting in Meeting History.
- Re-indexing is incremental: unchanged meetings are skipped.

## New API endpoints

- `GET /rag/status`
- `POST /rag/index?force=false`
- `POST /rag/search`
- `POST /rag/ask`

## New database tables

- `rag_meeting_indexes`
- `rag_chunks`

They are created automatically on backend startup. Existing meeting data is unchanged.

## Recommended local embedding setup

The default is:

```env
RAG_EMBEDDING_MODEL=embeddinggemma
```

Install it once:

```powershell
ollama pull embeddinggemma
```

Without it the Chat page still works with lexical retrieval, but semantic retrieval is recommended for paraphrases and cross-meeting concept search.

## Optional `.env` settings

```env
RAG_EMBEDDING_MODEL=embeddinggemma
RAG_TOP_K=8
RAG_CHUNK_WORDS=180
RAG_CHUNK_OVERLAP_WORDS=35
RAG_MIN_SCORE=0.12
RAG_OLLAMA_TIMEOUT_SECONDS=180
```

## Test

```powershell
cd D:\meeting-ai-assistant\backend
..\venv\Scripts\activate
python -m unittest discover -s tests -v
```

Expected:

```text
Ran 87 tests
OK
```

Then test the real meeting database:

```powershell
python test_rag_integration.py
```

After installing the embedding model, `semantic_used` should become `true`.

## Example questions

- Which meetings discussed ASTRA Toolbox?
- What unresolved questions do we have about multilayer reconstruction?
- Compare the discussions about synthetic and measurement data.
- What methods have we discussed for phase retrieval?
- In which meetings was near-field holography mentioned?
- What were the main conclusions about CNN-based stereo X-ray reconstruction?

## Source grounding

The LLM is instructed to answer only from the retrieved evidence and cite it as `[S1]`, `[S2]`, etc. The frontend renders matching source cards containing the meeting title, date, source type, and evidence excerpt.
